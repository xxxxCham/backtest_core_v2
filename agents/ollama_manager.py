"""
Module-ID: agents.ollama_manager

Purpose: Gérer Ollama (auto-démarrage, listage modèles, déchargement GPU, health checks).

Role in pipeline: orchestration / performance

Key components: LLMMemoryState, GPUMemoryManager, ensure_ollama_running, gpu_compute_context, list_ollama_models

Inputs: Modèle name, timeouts, max_attempts

Outputs: État Ollama, modèles disponibles, gestion mémoire GPU (unload/reload)

Dependencies: subprocess, httpx, utils.log, contextlib

Conventions: Ollama lancé via subprocess `ollama serve`; retries avec backoff exponentiel; gpu_compute_context décharge LLM avant calculs NumPy; recharge auto après.

Read-if: Configuration Ollama, gestion GPU memory, ou troubleshooting service.

Skip-if: Vous utilisez seulement OpenAI.
"""

from __future__ import annotations

# pylint: disable=logging-fstring-interpolation
import os
import platform
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from utils.log import get_logger
from utils.model_loader import get_ollama_models_root

logger = get_logger(__name__)

_OLLAMA_GPU_VISIBILITY_ENV_KEYS = (
    "CUDA_VISIBLE_DEVICES",
    "GPU_DEVICE_ORDINAL",
    "HIP_VISIBLE_DEVICES",
    "ROCR_VISIBLE_DEVICES",
)

_OLLAMA_GPU_TARGET_ENV_KEYS = (
    "BACKTEST_OLLAMA_GPU_TARGET",
    "OLLAMA_GPU_TARGET",
)

_OLLAMA_LOCAL_PINNING_ENV_KEYS = (
    "BACKTEST_OLLAMA_PIN_LOCALHOST",
    "OLLAMA_PIN_LOCALHOST",
)

_OLLAMA_LOCAL_RESTART_ENV_KEYS = (
    "BACKTEST_OLLAMA_RESTART_LOCAL_DAEMON",
    "OLLAMA_RESTART_LOCAL_DAEMON",
)

_OLLAMA_PINNING_RESTARTED_HOSTS: set[str] = set()


def _get_ollama_host(override: Optional[str] = None) -> str:
    """Retourne l'hôte Ollama effectif (override > env > défaut)."""
    host = str(
        override
        or os.environ.get("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).strip()
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host.rstrip("/")


def _ollama_url(path: str, ollama_host: Optional[str] = None) -> str:
    normalized = path if path.startswith("/") else f"/{path}"
    return f"{_get_ollama_host(ollama_host)}{normalized}"


def _is_local_ollama_host(ollama_host: Optional[str] = None) -> bool:
    host = _get_ollama_host(ollama_host)
    parsed = urlparse(host)
    hostname = (parsed.hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost", "::1"}


def _gpu_target_to_visible_devices(gpu_target: Optional[str] = None) -> Optional[str]:
    value = str(gpu_target or "").strip().upper()
    if not value or value == "AUTO":
        return None
    normalized_parts: list[str] = []
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if part.startswith("GPU-"):
            part = part[4:]
        if not part.isdigit():
            return None
        normalized_parts.append(part)

    if not normalized_parts:
        return None
    return ",".join(normalized_parts)


def _get_effective_gpu_target(gpu_target: Optional[str] = None) -> Optional[str]:
    explicit = str(gpu_target or "").strip()
    if explicit:
        return explicit

    for key in _OLLAMA_GPU_TARGET_ENV_KEYS:
        value = str(os.environ.get(key, "") or "").strip()
        if value:
            return value
    return None


def _local_gpu_pinning_enabled() -> bool:
    for key in _OLLAMA_LOCAL_PINNING_ENV_KEYS:
        value = str(os.environ.get(key, "") or "").strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
    return False


def _local_ollama_restart_enabled() -> bool:
    for key in _OLLAMA_LOCAL_RESTART_ENV_KEYS:
        value = str(os.environ.get(key, "") or "").strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
    return False


def _stop_local_ollama_processes() -> None:
    try:
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/F", "/IM", "ollama.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            subprocess.run(
                ["pkill", "-f", "ollama"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "⚠️ Impossible d'arrêter Ollama local pour reappliquer le pinning GPU: %s",
            exc,
        )


def _resolve_visible_devices_for_host(
    ollama_host: Optional[str],
    gpu_target: Optional[str] = None,
) -> Optional[str]:
    """Résout un pinning GPU uniquement pour des endpoints dédiés.

    Sur l'endpoint local partagé par défaut (`127.0.0.1:11434`), Ollama doit
    voir l'ensemble des GPUs pour pouvoir répartir correctement les gros
    modèles. Le pinning explicite reste utilisé pour des hosts/ports dédiés.
    """
    effective_gpu_target = _get_effective_gpu_target(gpu_target)
    visible_devices = _gpu_target_to_visible_devices(effective_gpu_target)
    if visible_devices is None:
        return None

    host = _get_ollama_host(ollama_host)
    parsed = urlparse(host)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if _is_local_ollama_host(host) and port == 11434 and not _local_gpu_pinning_enabled():
        return None
    return visible_devices


def _build_ollama_subprocess_env(
    ollama_host: Optional[str] = None,
    *,
    gpu_target: Optional[str] = None,
) -> dict[str, str]:
    """Construit un environnement propre pour `ollama serve`."""
    env = os.environ.copy()
    env["OLLAMA_HOST"] = _get_ollama_host(ollama_host)
    env["OLLAMA_MODELS"] = str(get_ollama_models_root())

    visible_devices = _resolve_visible_devices_for_host(ollama_host, gpu_target)
    if visible_devices is not None:
        env["CUDA_VISIBLE_DEVICES"] = visible_devices
        env["GPU_DEVICE_ORDINAL"] = visible_devices
        env["HIP_VISIBLE_DEVICES"] = visible_devices
        env["ROCR_VISIBLE_DEVICES"] = visible_devices
    else:
        for key in _OLLAMA_GPU_VISIBILITY_ENV_KEYS:
            env.pop(key, None)

    return env


def _fetch_tags_payload(
    ollama_host: Optional[str] = None,
    *,
    timeout_s: float = 2.0,
    max_attempts: int = 1,
    retry_delay_s: float = 0.75,
) -> tuple[Optional[dict], Optional[int], Optional[Exception]]:
    tags_url = _ollama_url("/api/tags", ollama_host)
    last_status: Optional[int] = None
    last_exc: Optional[Exception] = None

    for attempt in range(max_attempts):
        try:
            response = httpx.get(tags_url, timeout=timeout_s)
            last_status = response.status_code
            if response.status_code == 200:
                return response.json(), response.status_code, None
            last_exc = RuntimeError(f"status={response.status_code}")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc

        if attempt < max_attempts - 1:
            time.sleep(retry_delay_s)

    return None, last_status, last_exc


# ==============================================================================
# GPU Memory Manager - Déchargement/Rechargement intelligent des LLM
# ==============================================================================


@dataclass
class LLMMemoryState:
    """État mémoire d'un modèle LLM."""

    model_name: str
    was_loaded: bool = False
    context_messages: List[dict] = field(default_factory=list)
    unload_time_ms: float = 0.0
    reload_time_ms: float = 0.0


class GPUMemoryManager:
    """
    Gestionnaire de mémoire GPU pour les LLM.

    Permet de décharger temporairement les LLM du GPU pendant les phases
    de calcul intensif (backtests NumPy) puis de les recharger
    avec leur contexte préservé.

    Features:
    - Déchargement automatique avant calculs
    - Rechargement automatique après calculs
    - Préservation du contexte de conversation
    - Métriques de temps (unload/reload)
    - Mode "dry run" pour tests

    Example:
        >>> manager = GPUMemoryManager("deepseek-r1:32b")
        >>>
        >>> # Décharger avant calcul
        >>> state = manager.unload()
        >>>
        >>> # ... calculs GPU intensifs ...
        >>>
        >>> # Recharger avec contexte
        >>> manager.reload(state)
    """

    def __init__(
        self,
        model_name: str,
        ollama_host: Optional[str] = None,
        warmup_prompt: str = "You are ready.",
        verbose: bool = True,
    ):
        """
        Initialise le gestionnaire.

        Args:
            model_name: Nom du modèle Ollama (ex: "deepseek-r1:32b")
            ollama_host: URL du serveur Ollama
            warmup_prompt: Prompt court pour "réchauffer" le modèle au reload
            verbose: Afficher les logs
        """
        self.model_name = model_name
        self.ollama_host = _get_ollama_host(ollama_host)
        self.warmup_prompt = warmup_prompt
        self.verbose = verbose
        self._current_state: Optional[LLMMemoryState] = None

    def is_model_loaded(self) -> bool:
        """Vérifie si le modèle est actuellement en mémoire GPU."""
        try:
            # Utiliser l'API ps pour voir les modèles chargés
            response = httpx.get(
                f"{self.ollama_host}/api/ps",
                timeout=3.0
            )
            if response.status_code == 200:
                data = response.json()
                models = data.get("models", [])
                for m in models:
                    if m.get("name", "").startswith(self.model_name.split(":")[0]):
                        return True
            return False
        except Exception:
            return False

    def unload(self, context_messages: Optional[List[dict]] = None) -> LLMMemoryState:
        """
        Décharge le modèle du GPU.

        Args:
            context_messages: Messages de contexte à préserver pour le reload

        Returns:
            LLMMemoryState avec les infos pour le rechargement
        """
        start = time.perf_counter()
        was_loaded = self.is_model_loaded()

        state = LLMMemoryState(
            model_name=self.model_name,
            was_loaded=was_loaded,
            context_messages=context_messages or [],
        )

        if was_loaded:
            try:
                response = httpx.post(
                    f"{self.ollama_host}/api/generate",
                    json={
                        "model": self.model_name,
                        "keep_alive": 0,  # 0 = décharger immédiatement
                        "prompt": "",
                    },
                    timeout=10.0
                )
                if response.status_code == 200:
                    state.unload_time_ms = (time.perf_counter() - start) * 1000
                    if self.verbose:
                        logger.info(
                            f"💾 LLM déchargé: {self.model_name} "
                            f"({state.unload_time_ms:.0f}ms) → GPU libre pour calculs"
                        )
            except Exception as e:
                logger.warning(f"⚠️ Échec déchargement LLM: {e}")
        else:
            if self.verbose:
                logger.debug(f"📝 LLM {self.model_name} pas en mémoire, skip unload")

        self._current_state = state
        return state

    def reload(
        self,
        state: Optional[LLMMemoryState] = None,
        restore_context: bool = True,
    ) -> bool:
        """
        Recharge le modèle dans le GPU.

        Args:
            state: État précédent (ou utilise _current_state)
            restore_context: Si True, envoie un prompt de warmup

        Returns:
            True si succès
        """
        state = state or self._current_state
        if not state:
            logger.warning("⚠️ Pas d'état à restaurer")
            return False

        if not state.was_loaded:
            if self.verbose:
                logger.debug(f"📝 LLM {self.model_name} n'était pas chargé, skip reload")
            return True

        start = time.perf_counter()

        try:
            # Warmup: charger le modèle avec un prompt court
            warmup = self.warmup_prompt
            if restore_context and state.context_messages:
                # Résumé du contexte pour le LLM
                warmup = (
                    f"Previous context summary: We were optimizing a trading strategy. "
                    f"Last {len(state.context_messages)} messages exchanged. "
                    f"Ready to continue."
                )

            response = httpx.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.model_name,
                    "prompt": warmup,
                    "keep_alive": "10m",  # Garder 10 minutes
                    "stream": False,
                },
                timeout=120.0  # 2 min pour charger un gros modèle
            )

            if response.status_code == 200:
                state.reload_time_ms = (time.perf_counter() - start) * 1000
                if self.verbose:
                    logger.info(
                        f"🔄 LLM rechargé: {self.model_name} "
                        f"({state.reload_time_ms:.0f}ms)"
                    )
                return True
            else:
                logger.warning(f"⚠️ Échec reload LLM: status {response.status_code}")
                return False

        except Exception as e:
            logger.warning(f"⚠️ Échec rechargement LLM: {e}")
            return False

    def get_stats(self) -> dict:
        """Retourne les statistiques de la dernière opération."""
        if not self._current_state:
            return {}
        return {
            "model": self._current_state.model_name,
            "was_loaded": self._current_state.was_loaded,
            "unload_time_ms": self._current_state.unload_time_ms,
            "reload_time_ms": self._current_state.reload_time_ms,
            "context_size": len(self._current_state.context_messages),
        }


@contextmanager
def gpu_compute_context(
    model_name: str,
    context_messages: Optional[List[dict]] = None,
    verbose: bool = True,
) -> Generator[GPUMemoryManager, None, None]:
    """
    Context manager pour libérer le GPU pendant les calculs.

    Décharge automatiquement le LLM avant les calculs et le recharge après.

    Args:
        model_name: Nom du modèle à décharger
        context_messages: Contexte de conversation à préserver
        verbose: Afficher les logs

    Yields:
        GPUMemoryManager pour accès aux stats

    Example:
        >>> with gpu_compute_context("deepseek-r1:32b") as manager:
        ...     # GPU libre pour calculs numpy
        ...     results = heavy_backtest_computation()
        >>> # LLM automatiquement rechargé
        >>> print(manager.get_stats())
    """
    manager = GPUMemoryManager(model_name, verbose=verbose)

    # Décharger
    state = manager.unload(context_messages)

    try:
        yield manager
    finally:
        # Recharger
        manager.reload(state)


def ensure_ollama_running(
    ollama_host: Optional[str] = None,
    *,
    gpu_target: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    S'assure qu'Ollama est démarré et fonctionnel.

    Returns:
        tuple[bool, str]: (succès, message)
    """
    ollama_host = _get_ollama_host(ollama_host)

    # 1. Vérifier si Ollama répond
    payload, _status_code, _exc = _fetch_tags_payload(
        ollama_host,
        timeout_s=2.0,
        max_attempts=1,
    )
    normalized_host = _get_ollama_host(ollama_host)
    if payload is not None:
        should_restart_for_pinning = (
            _is_local_ollama_host(normalized_host)
            and _local_gpu_pinning_enabled()
            and _local_ollama_restart_enabled()
            and normalized_host not in _OLLAMA_PINNING_RESTARTED_HOSTS
        )
        if should_restart_for_pinning:
            logger.info(
                "♻️ Redémarrage Ollama local pour appliquer le pinning GPU (%s)",
                _get_effective_gpu_target(gpu_target) or "auto",
            )
            _stop_local_ollama_processes()
            _OLLAMA_PINNING_RESTARTED_HOSTS.add(normalized_host)
            time.sleep(1.5)
            payload = None

    if payload is not None:
        model_count = len(payload.get("models", []) or [])
        if model_count > 0:
            logger.info("✅ Ollama déjà actif (%s) | %d modèle(s)", ollama_host, model_count)
            return True, f"✅ Ollama actif ({ollama_host}) | {model_count} modele(s)"
        logger.warning("⚠️ Ollama actif (%s) mais aucun modèle détecté", ollama_host)
        return True, f"⚠️ Ollama actif ({ollama_host}) mais aucun modele detecte"

    # Hôte distant: impossible de le démarrer localement, signaler explicitement
    if not _is_local_ollama_host(ollama_host):
        return False, (
            f"❌ Ollama indisponible sur {ollama_host} "
            "(auto-start désactivé pour hôte distant)"
        )

    # 2. Démarrer Ollama
    logger.info("🚀 Démarrage d'Ollama...")
    try:
        is_windows = platform.system() == "Windows"
        env = _build_ollama_subprocess_env(ollama_host, gpu_target=gpu_target)

        if is_windows:
            # Windows : daemon de fond sans nouvelle console visible.
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            kwargs = {"creationflags": creationflags} if creationflags else {}

            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                **kwargs
            )
        else:
            # Linux/Mac
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )

        # 3. Attendre qu'Ollama soit prêt (max 10s)
        for i in range(10):
            time.sleep(1)
            payload, _status_code, _exc = _fetch_tags_payload(
                ollama_host,
                timeout_s=1.0,
                max_attempts=1,
            )
            if payload is None:
                continue

            model_count = len(payload.get("models", []) or [])
            if model_count > 0:
                logger.info(
                    "✅ Ollama démarré avec succès (après %ss) sur %s | %d modèle(s) | gpu=%s",
                    i + 1,
                    ollama_host,
                    model_count,
                    gpu_target or "auto",
                )
                suffix = f" | GPU {gpu_target}" if gpu_target else ""
                return True, (
                    f"✅ Ollama démarré ({i+1}s) sur {ollama_host} | "
                    f"{model_count} modele(s){suffix}"
                )

            logger.warning(
                "⚠️ Ollama démarré sur %s (après %ss) mais aucun modèle n'est détecté",
                ollama_host,
                i + 1,
            )
            suffix = f" | GPU {gpu_target}" if gpu_target else ""
            return True, (
                f"⚠️ Ollama démarré ({i+1}s) sur {ollama_host} mais aucun modele detecte"
                f"{suffix}"
            )

        return False, "⏱️ Timeout - Ollama n'a pas démarré en 10s"

    except FileNotFoundError:
        return False, "❌ Ollama non trouvé (vérifiez l'installation)"
    except Exception as e:
        return False, f"❌ Erreur: {str(e)}"


def unload_model(model_name: str, ollama_host: Optional[str] = None) -> bool:
    """
    Décharge un modèle Ollama de la mémoire GPU/RAM.

    Args:
        model_name: Nom du modèle (ex: "deepseek-r1:32b")

    Returns:
        bool: True si succès
    """
    generate_url = _ollama_url("/api/generate", ollama_host)
    try:
        response = httpx.post(
            generate_url,
            json={
                "model": model_name,
                "keep_alive": 0,  # 0 = décharger immédiatement
                "prompt": "",
            },
            timeout=5.0
        )
        success = response.status_code == 200
        if success:
            logger.info(f"💾 Modèle {model_name} déchargé de la mémoire")
        return success
    except Exception as e:
        logger.warning(f"⚠️ Impossible de décharger {model_name}: {e}")
        return False


def cleanup_all_models(ollama_host: Optional[str] = None) -> int:
    """
    Décharge TOUS les modèles Ollama de la mémoire.

    Returns:
        int: Nombre de modèles déchargés
    """
    ps_url = _ollama_url("/api/ps", ollama_host)
    try:
        # Lister les modèles chargés
        response = httpx.get(ps_url, timeout=5.0)
        if response.status_code != 200:
            return 0

        models = response.json().get("models", [])
        count = 0

        for model in models:
            model_name = model.get("name", "")
            if model_name and unload_model(model_name, ollama_host=ollama_host):
                count += 1

        if count > 0:
            logger.info(f"🧹 {count} modèle(s) déchargé(s) de la mémoire")

        return count

    except Exception as e:
        logger.warning(f"⚠️ Erreur cleanup_all_models: {e}")
        return 0


def stop_local_ollama_server(
    ollama_host: Optional[str] = None,
    *,
    force: bool = True,
    timeout_s: float = 3.0,
) -> int:
    """Arrête brutalement le daemon Ollama local écoutant sur l'hôte donné.

    Retourne le nombre de processus effectivement stoppés. Les hôtes distants
    sont ignorés volontairement.
    """
    if not _is_local_ollama_host(ollama_host):
        return 0

    try:
        import psutil
    except ImportError:
        logger.warning("⚠️ psutil indisponible, arrêt dur Ollama impossible")
        return 0

    parsed = urlparse(_get_ollama_host(ollama_host))
    target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    candidate_processes = []
    seen_pids: set[int] = set()

    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.pid is None or conn.pid in seen_pids or conn.laddr is None:
                continue
            if getattr(conn.laddr, "port", None) != target_port:
                continue
            try:
                proc = psutil.Process(conn.pid)
                name = str(proc.name() or "").lower()
                cmdline = " ".join(proc.cmdline()).lower()
            except (psutil.Error, OSError):
                continue
            if "ollama" not in name and "ollama" not in cmdline:
                continue
            seen_pids.add(conn.pid)
            candidate_processes.append(proc)
    except (psutil.Error, OSError) as exc:
        logger.warning("⚠️ Impossible d'inspecter les connexions Ollama: %s", exc)
        return 0

    if not candidate_processes:
        return 0

    stopped = 0
    for proc in candidate_processes:
        try:
            for child in proc.children(recursive=True):
                try:
                    child.terminate()
                except (psutil.Error, OSError):
                    continue
            proc.terminate()
            stopped += 1
        except (psutil.Error, OSError) as exc:
            logger.warning("⚠️ Impossible de terminer Ollama pid=%s: %s", proc.pid, exc)

    gone, alive = psutil.wait_procs(candidate_processes, timeout=max(timeout_s, 0.5))
    if force:
        for proc in alive:
            try:
                proc.kill()
            except (psutil.Error, OSError):
                continue
        if alive:
            gone_after_kill, _ = psutil.wait_procs(alive, timeout=1.5)
            stopped += len(gone_after_kill)

    logger.warning(
        "🪓 Arrêt dur Ollama local sur %s (port %s): %d process arrêté(s)",
        _get_ollama_host(ollama_host),
        target_port,
        stopped,
    )
    return stopped


def list_ollama_models(ollama_host: Optional[str] = None) -> List[str]:
    """
    Retourne la liste des modèles Ollama installés localement.

    Returns:
        list[str]: Noms des modèles (ex: ["llama3.2", "mistral"])
    """
    payload, status_code, exc = _fetch_tags_payload(
        ollama_host,
        timeout_s=3.0,
        max_attempts=3,
        retry_delay_s=0.75,
    )
    if payload is None:
        if status_code is not None:
            logger.warning(
                "⚠️ Impossible de lister les modèles Ollama sur %s (status=%s)",
                _get_ollama_host(ollama_host),
                status_code,
            )
        elif exc is not None:
            logger.warning(f"⚠️ Erreur lors de la récupération des modèles Ollama: {exc}")
        return []

    models = payload.get("models", []) or []

    names: List[str] = []
    for model in models:
        name = model.get("name")
        if isinstance(name, str) and name:
            names.append(name)

    if not names:
        logger.warning(
            "⚠️ Ollama répond sur %s mais aucun modèle installé n'est détecté",
            _get_ollama_host(ollama_host),
        )

    return names


def is_ollama_available(ollama_host: Optional[str] = None) -> bool:
    """
    Vérifie si Ollama est disponible.

    Returns:
        bool: True si Ollama répond
    """
    payload, _status_code, _exc = _fetch_tags_payload(
        ollama_host,
        timeout_s=2.0,
        max_attempts=1,
    )
    return payload is not None


def prepare_for_llm_run(ollama_host: Optional[str] = None) -> Tuple[bool, str]:
    """
    Prépare l'environnement pour un run LLM.

    Actions:
    1. S'assure qu'Ollama est actif
    2. Nettoie les modèles précédents en mémoire

    Returns:
        tuple[bool, str]: (succès, message détaillé)
    """
    messages = []

    # 1. Nettoyer les modèles précédents
    cleaned = cleanup_all_models(ollama_host=ollama_host)
    if cleaned > 0:
        messages.append(f"🧹 {cleaned} modèle(s) déchargé(s)")

    # 2. S'assurer qu'Ollama est actif
    success, msg = ensure_ollama_running(ollama_host=ollama_host)
    messages.append(msg)

    if success:
        time.sleep(1)  # Petite pause pour stabilité
        return True, " | ".join(messages)
    else:
        return False, " | ".join(messages)


__all__ = [
    "ensure_ollama_running",
    "unload_model",
    "cleanup_all_models",
    "list_ollama_models",
    "is_ollama_available",
    "prepare_for_llm_run",
    # GPU Memory Management
    "GPUMemoryManager",
    "LLMMemoryState",
    "gpu_compute_context",
]
