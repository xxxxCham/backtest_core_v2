"""Module-ID: agents.ollama_manager

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

# pylint: disable=broad-except
# pylint: disable=logging-fstring-interpolation
import atexit
import os
import platform
import subprocess
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from agents.model_config import is_cloud_only_model
from agents.ollama_runtime import (
    _get_ollama_host,
    _is_local_ollama_host,
    _ollama_url,
    get_ollama_cloud_runtime_model_candidates,
    is_ollama_cloud_model,
    is_ollama_model_not_found_response,
    resolve_ollama_request_context,
    strip_ollama_cloud_model_alias,
)
from utils.log import get_logger
from utils.model_loader import get_ollama_models_root, normalize_model_name

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


@dataclass
class _OwnedOllamaProcess:
    host: str
    process: subprocess.Popen
    started_at: float = field(default_factory=time.time)
    windows_job_bound: bool = False
    visible_devices: str | None = None


_OWNED_OLLAMA_PROCESSES: dict[str, _OwnedOllamaProcess] = {}
_OWNED_OLLAMA_LOCK = threading.Lock()
_WINDOWS_OLLAMA_STATE: dict[str, int | None] = {"job_handle": None}
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_KERNEL32: Any = None


if platform.system() == "Windows":
    import ctypes
    from ctypes import wintypes

    class _LargeInteger(ctypes.Structure):
        _fields_ = [("QuadPart", ctypes.c_longlong)]

    class _IOCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", _LargeInteger),
            ("PerJobUserTimeLimit", _LargeInteger),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JobObjectBasicLimitInformation),
            ("IoInfo", _IOCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _KERNEL32.CreateJobObjectW.restype = wintypes.HANDLE
    _KERNEL32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _KERNEL32.SetInformationJobObject.restype = wintypes.BOOL
    _KERNEL32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _KERNEL32.AssignProcessToJobObject.restype = wintypes.BOOL
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL


def _prune_owned_ollama_processes() -> None:
    stale_hosts: list[str] = []
    with _OWNED_OLLAMA_LOCK:
        for host, record in _OWNED_OLLAMA_PROCESSES.items():
            if record.process.poll() is not None:
                stale_hosts.append(host)
        for host in stale_hosts:
            _OWNED_OLLAMA_PROCESSES.pop(host, None)


def _get_owned_ollama_process(ollama_host: str | None = None) -> _OwnedOllamaProcess | None:
    normalized_host = _get_ollama_host(ollama_host)
    _prune_owned_ollama_processes()
    with _OWNED_OLLAMA_LOCK:
        return _OWNED_OLLAMA_PROCESSES.get(normalized_host)


def _ensure_windows_kill_on_close_job() -> int | None:
    if platform.system() != "Windows" or _KERNEL32 is None:
        return None

    existing_handle = _WINDOWS_OLLAMA_STATE["job_handle"]
    if existing_handle is not None:
        return existing_handle

    job_handle = _KERNEL32.CreateJobObjectW(None, None)
    if not job_handle:
        raise ctypes.WinError(ctypes.get_last_error())

    job_info = _JobObjectExtendedLimitInformation()
    job_info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    success = _KERNEL32.SetInformationJobObject(
        job_handle,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(job_info),
        ctypes.sizeof(job_info),
    )
    if not success:
        _KERNEL32.CloseHandle(job_handle)
        raise ctypes.WinError(ctypes.get_last_error())

    _WINDOWS_OLLAMA_STATE["job_handle"] = int(job_handle)
    return _WINDOWS_OLLAMA_STATE["job_handle"]


def _bind_process_to_lifecycle(process: subprocess.Popen) -> bool:
    if platform.system() != "Windows" or _KERNEL32 is None:
        return False

    process_handle_value = getattr(process, "_handle", None)
    if process_handle_value is None:
        return False

    try:
        job_handle = _ensure_windows_kill_on_close_job()
    except OSError as exc:
        logger.warning("⚠️ JobObject Ollama indisponible: %s", exc)
        return False

    if job_handle is None:
        return False

    success = _KERNEL32.AssignProcessToJobObject(
        wintypes.HANDLE(job_handle),
        wintypes.HANDLE(int(process_handle_value)),
    )
    if not success:
        error = ctypes.get_last_error()
        logger.warning(
            "⚠️ Impossible d'attacher Ollama pid=%s au JobObject: %s",
            process.pid,
            ctypes.WinError(error),
        )
        return False

    return True


def _terminate_process_tree(
    process: Any,
    *,
    timeout_s: float,
    force: bool = True,
) -> int:
    """Termine un processus et, si possible, tous ses enfants."""
    if process is None:
        return 0

    poll = getattr(process, "poll", None)
    if callable(poll):
        try:
            if poll() is not None:
                return 0
        except Exception:
            pass

    pid_raw = getattr(process, "pid", None)
    try:
        pid = int(pid_raw or 0)
    except (TypeError, ValueError):
        pid = 0

    tracked_processes: list[Any] = []
    psutil_module: Any = None
    if pid > 0:
        try:
            import psutil as psutil_module

            root_process = psutil_module.Process(pid)
            tracked_processes = list(root_process.children(recursive=True))
            tracked_processes.append(root_process)
        except ImportError:
            psutil_module = None
        except Exception:
            tracked_processes = []
            psutil_module = None

    if tracked_processes and psutil_module is not None:
        unique_processes: list[Any] = []
        seen_markers: set[int] = set()
        for tracked in tracked_processes:
            marker_raw = getattr(tracked, "pid", None)
            try:
                marker = int(marker_raw)
            except (TypeError, ValueError):
                marker = id(tracked)
            if marker in seen_markers:
                continue
            seen_markers.add(marker)
            unique_processes.append(tracked)

        for tracked in unique_processes:
            try:
                tracked.terminate()
            except Exception:
                continue

        try:
            _gone, alive = psutil_module.wait_procs(
                unique_processes,
                timeout=max(timeout_s, 0.5),
            )
        except Exception:
            alive = []

        if force and alive:
            for tracked in alive:
                try:
                    tracked.kill()
                except Exception:
                    continue
            try:
                psutil_module.wait_procs(alive, timeout=1.5)
            except Exception:
                pass

        wait = getattr(process, "wait", None)
        if callable(wait):
            try:
                wait(timeout=0.2)
            except Exception:
                pass

        poll = getattr(process, "poll", None)
        if callable(poll):
            try:
                return 1 if poll() is not None else 0
            except Exception:
                pass
        return 1

    try:
        process.terminate()
    except OSError:
        return 0

    try:
        process.wait(timeout=max(timeout_s, 0.5))
        return 1
    except subprocess.TimeoutExpired:
        if not force:
            return 0
        try:
            process.kill()
            process.wait(timeout=1.5)
            return 1
        except (OSError, subprocess.SubprocessError):
            return 0


def _terminate_owned_ollama_process(record: _OwnedOllamaProcess, *, timeout_s: float) -> int:
    return _terminate_process_tree(record.process, timeout_s=timeout_s, force=True)


def stop_owned_local_ollama_server(
    ollama_host: str | None = None,
    *,
    timeout_s: float = 3.0,
) -> int:
    """Arrête uniquement les daemons Ollama auto-démarrés par l'application."""
    _prune_owned_ollama_processes()

    with _OWNED_OLLAMA_LOCK:
        if ollama_host is None:
            owned_items = list(_OWNED_OLLAMA_PROCESSES.items())
            _OWNED_OLLAMA_PROCESSES.clear()
        else:
            normalized_host = _get_ollama_host(ollama_host)
            record = _OWNED_OLLAMA_PROCESSES.pop(normalized_host, None)
            owned_items = [(normalized_host, record)] if record is not None else []

    stopped = 0
    for host, record in owned_items:
        if record is None or not _is_local_ollama_host(host):
            continue
        stopped += _terminate_owned_ollama_process(record, timeout_s=timeout_s)

    if stopped > 0:
        logger.info("⛔ Ollama auto-démarré arrêté: %d process(s)", stopped)

    return stopped


def _cleanup_owned_ollama_processes_at_exit() -> None:
    stop_owned_local_ollama_server()


atexit.register(_cleanup_owned_ollama_processes_at_exit)


def _gpu_target_to_visible_devices(gpu_target: str | None = None) -> str | None:
    value = str(gpu_target or "").strip().upper()
    if not value or value == "AUTO":
        return None
    normalized_parts: list[str] = []
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        part = part.removeprefix("GPU-")
        if not part.isdigit():
            return None
        normalized_parts.append(part)

    if not normalized_parts:
        return None
    return ",".join(normalized_parts)


def _get_effective_gpu_target(gpu_target: str | None = None) -> str | None:
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
    ollama_host: str | None,
    gpu_target: str | None = None,
) -> str | None:
    """Résout le pinning GPU effectif demandé par le runtime appelant."""
    effective_gpu_target = _get_effective_gpu_target(gpu_target)
    return _gpu_target_to_visible_devices(effective_gpu_target)


def _build_ollama_subprocess_env(
    ollama_host: str | None = None,
    *,
    gpu_target: str | None = None,
) -> dict[str, str]:
    """Construit un environnement propre pour `ollama serve`.

    Règles GPU canoniques (un seul endroit de décision) :
    - gpu_target explicite → pinning mono-GPU via CUDA_VISIBLE_DEVICES, pas de SCHED_SPREAD.
    - gpu_target None/AUTO → tous les GPUs visibles, OLLAMA_SCHED_SPREAD=1 activé pour
      que Ollama distribue les couches du modèle sur l'ensemble des cartes (évite le
      débordement CPU quand le modèle dépasse la VRAM d'une seule carte).
    """
    env = os.environ.copy()
    env["OLLAMA_HOST"] = _get_ollama_host(ollama_host)
    env["OLLAMA_MODELS"] = str(get_ollama_models_root())

    visible_devices = _resolve_visible_devices_for_host(ollama_host, gpu_target)
    if visible_devices is not None:
        # Pinning explicite : une ou plusieurs cartes précises, pas de spread.
        env["CUDA_VISIBLE_DEVICES"] = visible_devices
        env["GPU_DEVICE_ORDINAL"] = visible_devices
        env["HIP_VISIBLE_DEVICES"] = visible_devices
        env["ROCR_VISIBLE_DEVICES"] = visible_devices
        env.pop("OLLAMA_SCHED_SPREAD", None)
    else:
        # Mode multi-GPU automatique : on retire les contraintes de visibilité pour
        # que tous les GPUs soient accessibles, et on active le spread scheduler.
        for key in _OLLAMA_GPU_VISIBILITY_ENV_KEYS:
            env.pop(key, None)
        env["OLLAMA_SCHED_SPREAD"] = "1"

    return env


def _fetch_tags_payload(
    ollama_host: str | None = None,
    *,
    model_name: str | None = None,
    timeout_s: float = 2.0,
    max_attempts: int = 1,
    retry_delay_s: float = 0.75,
) -> tuple[dict | None, int | None, Exception | None]:
    request_ctx = resolve_ollama_request_context(
        ollama_host,
        model_name=model_name,
    )
    tags_url = _ollama_url("/api/tags", request_ctx["effective_host"])
    last_status: int | None = None
    last_exc: Exception | None = None

    for attempt in range(max_attempts):
        try:
            request_kwargs: dict[str, Any] = {"timeout": timeout_s}
            headers = dict(request_ctx.get("headers", {}) or {})
            if headers:
                request_kwargs["headers"] = headers
            response = httpx.get(tags_url, **request_kwargs)
            last_status = response.status_code
            if response.status_code == 200:
                return response.json(), response.status_code, None
            last_exc = RuntimeError(f"status={response.status_code}")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc

        if attempt < max_attempts - 1:
            time.sleep(retry_delay_s)

    return None, last_status, last_exc


def probe_model_runtime_acceptance(
    model_name: str,
    *,
    requested_model: str | None = None,
    ollama_host: str | None = None,
    tags_payload: dict | None = None,
    tags_status_code: int | None = None,
    tags_error: Exception | None = None,
    timeout_s: float = 20.0,
) -> dict:
    """Teste si l'hôte Ollama accepte réellement un nom de modèle exact."""
    requested_name = str(requested_model or model_name or "").strip()
    request_ctx = resolve_ollama_request_context(
        ollama_host,
        model_name=requested_name or model_name,
    )
    normalized_host = str(request_ctx["effective_host"] or _get_ollama_host(ollama_host))
    exact_name = str(
        request_ctx["request_model"] or strip_ollama_cloud_model_alias(model_name),
    ).strip()
    requested_name = str(
        strip_ollama_cloud_model_alias(requested_name)
        if request_ctx["direct_cloud"]
        else requested_name
    ).strip()
    probe_candidates = get_ollama_cloud_runtime_model_candidates(
        requested_name or exact_name,
        direct_cloud=bool(request_ctx.get("direct_cloud")),
    )
    if not probe_candidates:
        probe_candidates = [exact_name]
    result = {
        "requested_model": requested_name,
        "resolved_model": exact_name,
        "ollama_host": normalized_host,
        "host_reachable": False,
        "present_in_tags": False,
        "accepted": False,
        "status": "invalid_model_name",
        "message": "Nom de modèle vide.",
        "tags_status_code": tags_status_code,
        "runtime_status_code": None,
        "runtime_error_body": "",
        "requested_matches_resolved": requested_name == exact_name,
        "direct_cloud": bool(request_ctx.get("direct_cloud")),
        "api_key_present": bool(request_ctx.get("api_key_present")),
    }
    if not exact_name:
        return result

    if tags_payload is None and tags_status_code is None and tags_error is None:
        tags_payload, tags_status_code, tags_error = _fetch_tags_payload(
            normalized_host,
            model_name=requested_name or exact_name,
            timeout_s=min(timeout_s, 5.0),
            max_attempts=1,
        )

    result["tags_status_code"] = tags_status_code
    if tags_payload is None:
        if tags_status_code is None:
            result["status"] = "host_unreachable"
            result["message"] = f"Ollama inaccessible sur {normalized_host}. Détail: {tags_error}"
        else:
            result["status"] = "host_http_error"
            result["message"] = (
                f"Ollama répond sur {normalized_host}, mais /api/tags retourne status={tags_status_code}."
            )
        return result

    result["host_reachable"] = True
    tag_models = tags_payload.get("models", []) or []
    tag_names = [
        str(item.get("name", "") or "").strip() for item in tag_models if str(item.get("name", "") or "").strip()
    ]
    normalized_candidates = {normalize_model_name(candidate) for candidate in probe_candidates if candidate}
    result["present_in_tags"] = any(normalize_model_name(name) in normalized_candidates for name in tag_names)

    try:
        request_kwargs: dict[str, Any] = {"timeout": timeout_s}
        headers = dict(request_ctx.get("headers", {}) or {})
        if headers:
            request_kwargs["headers"] = headers

        tried_models: list[str] = []
        for candidate_name in probe_candidates:
            tried_models.append(candidate_name)
            response = httpx.post(
                _ollama_url("/api/chat", normalized_host),
                json={
                    "model": candidate_name,
                    "messages": [{"role": "user", "content": "ping"}],
                    "stream": False,
                    "keep_alive": "0m",
                    "options": {"num_predict": 1},
                },
                **request_kwargs,
            )
            result["runtime_status_code"] = response.status_code
            body = str(getattr(response, "text", "") or "").strip().replace("\n", " ")
            if len(body) > 300:
                body = body[:300] + "..."
            result["runtime_error_body"] = body
            result["resolved_model"] = candidate_name
            result["requested_matches_resolved"] = requested_name == candidate_name

            if response.status_code == 200:
                result["accepted"] = True
                result["status"] = "accepted"
                if result["present_in_tags"]:
                    result["message"] = (
                        f"L'hôte {normalized_host} accepte `{candidate_name}` et le modèle est visible dans /api/tags."
                    )
                elif candidate_name != requested_name:
                    result["message"] = (
                        f"L'hôte {normalized_host} accepte l'alias runtime cloud `{candidate_name}` "
                        f"pour la demande `{requested_name or candidate_name}`, même s'il n'apparaît pas dans /api/tags."
                    )
                else:
                    result["message"] = (
                        f"L'hôte {normalized_host} accepte le nom exact `{candidate_name}` "
                        "même s'il n'apparaît pas dans /api/tags."
                    )
                return result

            if is_ollama_model_not_found_response(response.status_code, body) and candidate_name != probe_candidates[-1]:
                continue

            if is_ollama_model_not_found_response(response.status_code, body):
                cloud_candidate = bool(is_cloud_only_model(requested_name) or is_cloud_only_model(candidate_name))
                if (
                    cloud_candidate
                    and _is_local_ollama_host(normalized_host)
                    and not bool(request_ctx.get("direct_cloud"))
                    and not bool(request_ctx.get("api_key_present"))
                    and not bool(result["present_in_tags"])
                ):
                    result["status"] = "cloud_model_not_exposed_by_current_host"
                    tried = ", ".join(f"`{name}`" for name in tried_models)
                    result["message"] = (
                        f"Le modèle cloud-only `{requested_name or candidate_name}` n'est pas exposé par "
                        f"l'hôte local {normalized_host}: aucun alias runtime correspondant n'apparaît "
                        "dans `/api/tags`, le routage direct Ollama Cloud est inactif car "
                        "`OLLAMA_API_KEY` est absent du process courant, et les noms testés "
                        f"{tried} sont rejetés."
                    )
                    return result
                if requested_name != candidate_name:
                    result["status"] = "requested_name_rewritten_but_exact_rejected"
                    result["message"] = (
                        f"Le nom demandé `{requested_name}` a été réécrit en `{candidate_name}`, "
                        f"mais l'hôte {normalized_host} rejette aussi ce nom exact."
                    )
                else:
                    result["status"] = "exact_name_rejected_by_host"
                    result["message"] = (
                        f"L'hôte {normalized_host} est joignable, mais il rejette le nom exact `{candidate_name}`."
                    )
                return result

            if response.status_code == 403:
                result["status"] = "cloud_access_denied"
                try:
                    _err_detail = response.json().get("error", "")
                except Exception:  # noqa: BLE001
                    _err_detail = response.text[:200]
                _extra = f" Détail Ollama : {_err_detail}" if _err_detail else ""
                result["message"] = (
                    f"L'hôte {normalized_host} est joignable, mais le probe runtime sur `{candidate_name}` "
                    f"retourne status=403 : accès refusé au modèle cloud (volume élevé, abonnement requis ou "
                    f"modèle temporairement restreint).{_extra}"
                )
                return result
            result["status"] = "runtime_http_error"
            result["message"] = (
                f"L'hôte {normalized_host} est joignable, mais le probe runtime sur `{candidate_name}` "
                f"retourne status={response.status_code}."
            )
            return result

        return result
    except httpx.TimeoutException:
        # Pour un modèle local non-cloud avec un petit timeout initial, le premier
        # timeout peut indiquer que le modèle est en cours de chargement GPU (ex: 35B
        # après reboot). On retente une seule fois avec un délai et un timeout plus long.
        is_local_non_cloud = (
            _is_local_ollama_host(normalized_host)
            and not bool(request_ctx.get("direct_cloud"))
            and not is_cloud_only_model(result.get("resolved_model") or "")
            and timeout_s < 45.0
        )
        if is_local_non_cloud:
            import time as _time_mod  # noqa: PLC0415
            _time_mod.sleep(8)
            return probe_model_runtime_acceptance(
                model_name,
                requested_model=requested_model,
                ollama_host=ollama_host,
                tags_payload=tags_payload,
                tags_status_code=tags_status_code,
                tags_error=tags_error,
                timeout_s=max(60.0, timeout_s * 3),
            )
        result["status"] = "runtime_timeout"
        result["message"] = (
            f"L'hôte {normalized_host} est joignable, mais le probe runtime sur `{result['resolved_model']}` a expiré."
        )
        return result
    except Exception as exc:  # noqa: BLE001
        result["status"] = "runtime_error"
        result["message"] = (
            f"L'hôte {normalized_host} est joignable, mais le probe runtime sur `{result['resolved_model']}` a échoué: {exc}"
        )
        return result


# ==============================================================================
# GPU Memory Manager - Déchargement/Rechargement intelligent des LLM
# ==============================================================================


@dataclass
class LLMMemoryState:
    """État mémoire d'un modèle LLM."""

    model_name: str
    was_loaded: bool = False
    context_messages: list[dict] = field(default_factory=list)
    unload_time_ms: float = 0.0
    reload_time_ms: float = 0.0


class GPUMemoryManager:
    """Gestionnaire de mémoire GPU pour les LLM.

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
        ollama_host: str | None = None,
        warmup_prompt: str = "You are ready.",
        verbose: bool = True,
    ):
        """Initialise le gestionnaire.

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
        self._current_state: LLMMemoryState | None = None

    def is_model_loaded(self) -> bool:
        """Vérifie si le modèle est actuellement en mémoire GPU."""
        loaded, _ = is_model_loaded_in_memory(self.model_name, self.ollama_host, timeout_s=3.0)
        return loaded

    def unload(self, context_messages: list[dict] | None = None) -> LLMMemoryState:
        """Décharge le modèle du GPU.

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
            unload_model(self.model_name, ollama_host=self.ollama_host)
            state.unload_time_ms = (time.perf_counter() - start) * 1000
            if self.verbose:
                logger.info(
                    f"💾 LLM déchargé: {self.model_name} "
                    f"({state.unload_time_ms:.0f}ms) → GPU libre pour calculs",
                )
        elif self.verbose:
            logger.debug(f"📝 LLM {self.model_name} pas en mémoire, skip unload")

        self._current_state = state
        return state

    def reload(
        self,
        state: LLMMemoryState | None = None,
        restore_context: bool = True,
    ) -> bool:
        """Recharge le modèle dans le GPU.

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

        warmup_prompt = self.warmup_prompt
        if restore_context and state.context_messages:
            warmup_prompt = (
                f"Previous context summary: We were optimizing a trading strategy. "
                f"Last {len(state.context_messages)} messages exchanged. "
                f"Ready to continue."
            )

        ok, _ = warmup_model(
            self.model_name,
            self.ollama_host,
            keep_alive_minutes=10,
            timeout_s=120.0,
            prompt=warmup_prompt,
        )
        if ok:
            state.reload_time_ms = (time.perf_counter() - start) * 1000
            if self.verbose:
                logger.info(f"🔄 LLM rechargé: {self.model_name} ({state.reload_time_ms:.0f}ms)")
        else:
            logger.warning(f"⚠️ Échec rechargement LLM: {self.model_name}")
        return ok

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
    context_messages: list[dict] | None = None,
    verbose: bool = True,
) -> Generator[GPUMemoryManager, None, None]:
    """Context manager pour libérer le GPU pendant les calculs.

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
    ollama_host: str | None = None,
    *,
    gpu_target: str | None = None,
    model_name: str | None = None,
) -> tuple[bool, str]:
    """S'assure qu'Ollama est démarré et fonctionnel.

    Returns:
        tuple[bool, str]: (succès, message)

    """
    request_ctx = resolve_ollama_request_context(
        ollama_host,
        model_name=model_name,
    )
    ollama_host = str(request_ctx["effective_host"] or _get_ollama_host(ollama_host))

    # 1. Vérifier si Ollama répond
    payload, _status_code, _exc = _fetch_tags_payload(
        ollama_host,
        model_name=model_name,
        timeout_s=2.0,
        max_attempts=1,
    )
    normalized_host = _get_ollama_host(ollama_host)
    requested_visible_devices = _resolve_visible_devices_for_host(
        ollama_host,
        gpu_target,
    )
    if payload is not None:
        owned_record = _get_owned_ollama_process(normalized_host)
        local_host = _is_local_ollama_host(normalized_host)
        owned_visibility_mismatch = (
            owned_record is not None and owned_record.visible_devices != requested_visible_devices
        )
        env_forced_restart = (
            owned_record is None and _local_gpu_pinning_enabled() and _local_ollama_restart_enabled()
        )
        should_restart_for_pinning = (
            local_host
            and normalized_host not in _OLLAMA_PINNING_RESTARTED_HOSTS
            and (owned_visibility_mismatch or env_forced_restart)
        )
        if should_restart_for_pinning:
            logger.info(
                "♻️ Redémarrage Ollama local pour appliquer la visibilité GPU (%s)",
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
        return False, (f"❌ Ollama indisponible sur {ollama_host} (auto-start désactivé pour hôte distant)")

    # 2. Démarrer Ollama
    logger.info("🚀 Démarrage d'Ollama...")
    started_new_process = False
    try:
        is_windows = platform.system() == "Windows"
        env = _build_ollama_subprocess_env(ollama_host, gpu_target=gpu_target)
        visible_devices = _resolve_visible_devices_for_host(ollama_host, gpu_target)

        with _OWNED_OLLAMA_LOCK:
            payload, _status_code, _exc = _fetch_tags_payload(
                ollama_host,
                model_name=model_name,
                timeout_s=1.0,
                max_attempts=1,
            )
            if payload is not None:
                model_count = len(payload.get("models", []) or [])
                if model_count > 0:
                    return True, f"✅ Ollama actif ({ollama_host}) | {model_count} modele(s)"
                return True, f"⚠️ Ollama actif ({ollama_host}) mais aucun modele detecte"

            owned_record = _OWNED_OLLAMA_PROCESSES.get(normalized_host)
            if owned_record is not None and owned_record.process.poll() is not None:
                _OWNED_OLLAMA_PROCESSES.pop(normalized_host, None)
                owned_record = None

            if owned_record is None:
                process: subprocess.Popen
                if is_windows:
                    # Windows : daemon de fond sans nouvelle console visible.
                    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    process = subprocess.Popen(
                        ["ollama", "serve"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        env=env,
                        creationflags=creationflags,
                    )
                else:
                    process = subprocess.Popen(
                        ["ollama", "serve"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        env=env,
                    )

                _OWNED_OLLAMA_PROCESSES[normalized_host] = _OwnedOllamaProcess(
                    host=normalized_host,
                    process=process,
                    windows_job_bound=_bind_process_to_lifecycle(process),
                    visible_devices=visible_devices,
                )
                started_new_process = True

        # 3. Attendre qu'Ollama soit prêt (max 10s)
        for i in range(10):
            time.sleep(1)
            payload, _status_code, _exc = _fetch_tags_payload(
                ollama_host,
                model_name=model_name,
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
                return True, (f"✅ Ollama démarré ({i + 1}s) sur {ollama_host} | {model_count} modele(s){suffix}")

            logger.warning(
                "⚠️ Ollama démarré sur %s (après %ss) mais aucun modèle n'est détecté",
                ollama_host,
                i + 1,
            )
            suffix = f" | GPU {gpu_target}" if gpu_target else ""
            return True, (f"⚠️ Ollama démarré ({i + 1}s) sur {ollama_host} mais aucun modele detecte{suffix}")

        if started_new_process:
            stop_owned_local_ollama_server(ollama_host=ollama_host, timeout_s=2.0)
        return False, "⏱️ Timeout - Ollama n'a pas démarré en 10s"

    except FileNotFoundError:
        if started_new_process:
            stop_owned_local_ollama_server(ollama_host=ollama_host, timeout_s=2.0)
        return False, "❌ Ollama non trouvé (vérifiez l'installation)"
    except Exception as e:  # noqa: BLE001
        if started_new_process:
            stop_owned_local_ollama_server(ollama_host=ollama_host, timeout_s=2.0)
        return False, f"❌ Erreur: {e!s}"


def unload_model(model_name: str, ollama_host: str | None = None) -> bool:
    """Décharge un modèle Ollama de la mémoire GPU/RAM.

    Args:
        model_name: Nom du modèle (ex: "deepseek-r1:32b")

    Returns:
        bool: True si succès

    """
    request_ctx = resolve_ollama_request_context(
        ollama_host,
        model_name=model_name,
    )
    runtime_host = str(request_ctx["effective_host"] or _get_ollama_host(ollama_host))
    runtime_model = str(request_ctx["request_model"] or model_name).strip()
    generate_url = _ollama_url("/api/generate", runtime_host)
    try:
        request_kwargs: dict[str, Any] = {"timeout": 5.0}
        headers = dict(request_ctx.get("headers", {}) or {})
        if headers:
            request_kwargs["headers"] = headers
        response = httpx.post(
            generate_url,
            json={
                "model": runtime_model,
                "keep_alive": 0,  # 0 = décharger immédiatement
                "prompt": "",
            },
            **request_kwargs,
        )
        success = response.status_code == 200
        if success:
            logger.info(f"💾 Modèle {runtime_model} déchargé de la mémoire")
        return success
    except Exception as e:  # noqa: BLE001
        logger.warning(f"⚠️ Impossible de décharger {model_name}: {e}")
        return False


def _extract_model_size_b(model_name: str) -> float:
    normalized = normalize_model_name(str(model_name or "").strip())
    if not normalized:
        return -1.0
    import re

    match = re.search(r"(\d+(?:\.\d+)?)b", normalized.lower())
    if not match:
        return -1.0
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return -1.0


def _model_name_matches_runtime(loaded_name: str, requested_model: str) -> bool:
    loaded = normalize_model_name(str(loaded_name or "").strip())
    requested = normalize_model_name(str(requested_model or "").strip())
    if not loaded or not requested:
        return False
    if loaded == requested:
        return True

    loaded_base = loaded.split(":", 1)[0]
    requested_base = requested.split(":", 1)[0]
    if loaded_base != requested_base:
        return False

    loaded_size = _extract_model_size_b(loaded)
    requested_size = _extract_model_size_b(requested)
    if loaded_size > 0 and requested_size > 0 and loaded_size != requested_size:
        return False

    if loaded.endswith(":latest") and loaded[:-7] == requested:
        return True
    if requested.endswith(":latest") and requested[:-7] == loaded:
        return True

    return True


def is_model_loaded_in_memory(
    model_name: str,
    ollama_host: str | None = None,
    *,
    timeout_s: float = 6.0,
) -> tuple[bool, str]:
    """Vérifie via /api/ps si un modèle est déjà chargé en mémoire."""
    request_ctx = resolve_ollama_request_context(
        ollama_host,
        model_name=model_name,
    )
    runtime_host = str(request_ctx["effective_host"] or _get_ollama_host(ollama_host))
    runtime_model = str(request_ctx["request_model"] or model_name).strip()
    ps_url = _ollama_url("/api/ps", runtime_host)
    try:
        request_kwargs: dict[str, Any] = {"timeout": timeout_s}
        headers = dict(request_ctx.get("headers", {}) or {})
        if headers:
            request_kwargs["headers"] = headers
        response = httpx.get(ps_url, **request_kwargs)
        if response.status_code != 200:
            return False, f"/api/ps status={response.status_code}"

        payload = response.json() if response.content else {}
        models = payload.get("models", []) or []
        loaded_names = [
            str(item.get("name", "") or "").strip() for item in models if str(item.get("name", "") or "").strip()
        ]
        for loaded_name in loaded_names:
            if _model_name_matches_runtime(loaded_name, runtime_model):
                return True, f"modele deja charge (`{loaded_name}`)"

        if loaded_names:
            preview = ", ".join(loaded_names[:3])
            return False, f"modeles actifs: {preview}"
        return False, "aucun modele actif"
    except Exception as exc:  # noqa: BLE001
        return False, f"/api/ps inaccessible: {exc}"


def warmup_model(
    model_name: str,
    ollama_host: str | None = None,
    *,
    keep_alive_minutes: int = 10,
    timeout_s: float = 300.0,
    prompt: str = "Ready.",
) -> tuple[bool, str]:
    """Précharge un modèle Ollama en mémoire via un prompt court."""
    request_ctx = resolve_ollama_request_context(
        ollama_host,
        model_name=model_name,
    )
    runtime_host = str(request_ctx["effective_host"] or _get_ollama_host(ollama_host))
    runtime_model = str(request_ctx["request_model"] or model_name).strip()
    generate_url = _ollama_url("/api/generate", runtime_host)
    keep_alive = f"{max(1, int(keep_alive_minutes))}m"
    try:
        request_kwargs: dict[str, Any] = {"timeout": timeout_s}
        headers = dict(request_ctx.get("headers", {}) or {})
        if headers:
            request_kwargs["headers"] = headers
        response = httpx.post(
            generate_url,
            json={
                "model": runtime_model,
                "prompt": prompt,
                "keep_alive": keep_alive,
                "stream": False,
            },
            **request_kwargs,
        )
        if response.status_code == 200:
            detail = "warmup /api/generate status=200"
            try:
                payload = response.json() if response.content else {}
                done_reason = str(payload.get("done_reason", "") or "").strip()
                if done_reason:
                    detail += f", done_reason={done_reason}"
            except Exception:  # noqa: BLE001
                pass
            return True, detail

        body = str(getattr(response, "text", "") or "").strip().replace("\n", " ")
        if len(body) > 300:
            body = body[:300] + "..."
        loaded, loaded_detail = is_model_loaded_in_memory(
            runtime_model,
            ollama_host=runtime_host,
            timeout_s=min(timeout_s, 8.0),
        )
        if loaded:
            return True, f"warmup status={response.status_code} mais {loaded_detail}"
        return False, (f"warmup status={response.status_code}, body={body or '<vide>'}, ps={loaded_detail}")
    except httpx.TimeoutException:
        loaded, loaded_detail = is_model_loaded_in_memory(
            runtime_model,
            ollama_host=runtime_host,
            timeout_s=min(timeout_s, 8.0),
        )
        if loaded:
            return True, f"timeout warmup ({int(timeout_s)}s) mais {loaded_detail}"
        return False, f"timeout warmup ({int(timeout_s)}s), ps={loaded_detail}"
    except Exception as exc:
        loaded, loaded_detail = is_model_loaded_in_memory(
            runtime_model,
            ollama_host=runtime_host,
            timeout_s=min(timeout_s, 8.0),
        )
        if loaded:
            return True, f"erreur warmup ({exc}) mais {loaded_detail}"
        return False, f"erreur warmup ({exc}), ps={loaded_detail}"


def cleanup_all_models(ollama_host: str | None = None) -> int:
    """Décharge TOUS les modèles Ollama de la mémoire.

    Returns:
        int: Nombre de modèles déchargés

    """
    request_ctx = resolve_ollama_request_context(ollama_host)
    runtime_host = str(request_ctx["effective_host"] or _get_ollama_host(ollama_host))
    ps_url = _ollama_url("/api/ps", runtime_host)
    try:
        # Lister les modèles chargés
        request_kwargs: dict[str, Any] = {"timeout": 5.0}
        headers = dict(request_ctx.get("headers", {}) or {})
        if headers:
            request_kwargs["headers"] = headers
        response = httpx.get(ps_url, **request_kwargs)
        if response.status_code != 200:
            return 0

        models = response.json().get("models", [])
        count = 0

        for model in models:
            model_name = model.get("name", "")
            if model_name and unload_model(model_name, ollama_host=runtime_host):
                count += 1

        if count > 0:
            logger.info(f"🧹 {count} modèle(s) déchargé(s) de la mémoire")

        return count

    except Exception as e:  # noqa: BLE001
        logger.warning(f"⚠️ Erreur cleanup_all_models: {e}")
        return 0


def stop_local_ollama_server(
    ollama_host: str | None = None,
    *,
    force: bool = True,
    owned_only: bool = False,
    timeout_s: float = 3.0,
) -> int:
    """Arrête brutalement le daemon Ollama local écoutant sur l'hôte donné.

    Retourne le nombre de processus effectivement stoppés. Les hôtes distants
    sont ignorés volontairement.
    """
    if not _is_local_ollama_host(ollama_host):
        return 0

    owned_stopped = stop_owned_local_ollama_server(
        ollama_host=ollama_host,
        timeout_s=timeout_s,
    )
    if owned_stopped > 0 or owned_only:
        return owned_stopped

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
            stopped += _terminate_process_tree(proc, timeout_s=timeout_s, force=force)
        except (psutil.Error, OSError) as exc:
            logger.warning("⚠️ Impossible de terminer Ollama pid=%s: %s", proc.pid, exc)

    logger.warning(
        "🪓 Arrêt dur Ollama local sur %s (port %s): %d process arrêté(s)",
        _get_ollama_host(ollama_host),
        target_port,
        stopped,
    )
    return stopped


def list_ollama_models(ollama_host: str | None = None) -> list[str]:
    """Retourne la liste des modèles Ollama installés localement.

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

    names: list[str] = []
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


def is_ollama_available(ollama_host: str | None = None) -> bool:
    """Vérifie si Ollama est disponible.

    Returns:
        bool: True si Ollama répond

    """
    payload, _status_code, _exc = _fetch_tags_payload(
        ollama_host,
        timeout_s=2.0,
        max_attempts=1,
    )
    return payload is not None


def prepare_for_llm_run(ollama_host: str | None = None) -> tuple[bool, str]:
    """Prépare l'environnement pour un run LLM.

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
    return False, " | ".join(messages)


__all__ = [
    "ensure_ollama_running",
    "unload_model",
    "is_model_loaded_in_memory",
    "warmup_model",
    "cleanup_all_models",
    "stop_local_ollama_server",
    "stop_owned_local_ollama_server",
    "list_ollama_models",
    "probe_model_runtime_acceptance",
    "is_ollama_available",
    "prepare_for_llm_run",
    "resolve_ollama_request_context",
    "get_ollama_cloud_runtime_model_candidates",
    "is_ollama_model_not_found_response",
    "strip_ollama_cloud_model_alias",
    "is_ollama_cloud_model",
    # GPU Memory Management
    "GPUMemoryManager",
    "LLMMemoryState",
    "gpu_compute_context",
]
