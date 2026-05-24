"""Module-ID: ui.components.model_selector

Purpose: Selecteur modeles LLM - query Ollama, fallback list, recommendations par role.
         Affichage riche avec details (VRAM, taille, categorie, backup path).

Role in pipeline: configuration

Key components: get_available_models_for_ui(), render_model_selector(), get_model_details()

Inputs: Ollama endpoint (optionnel), role (Analyst/Strategist/Critic/Validator)

Outputs: Model list [str], model details [dict], rendered selector widget

Dependencies: agents.ollama_manager (optionnel), utils.model_loader, httpx
"""

# pylint: disable=broad-exception-caught

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterable, Sequence
from typing import Any
from urllib.parse import urlparse

from agents.model_config import (
    backend_is_detectable,
    backend_is_selectable,
    get_model_selector_fallback_order,
    is_cloud_only_model,
    list_cloud_only_model_names,
)
from utils.log import get_logger
from utils.model_loader import (
    get_model_by_id,
    get_ollama_runtime_model_names,
)
from utils.model_loader import (
    normalize_model_name as normalize_catalog_model_name,
)

try:
    from agents.ollama_manager import is_ollama_available
except ImportError:

    def is_ollama_available(ollama_host: str | None = None) -> bool:
        del ollama_host
        return False


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helper cloud detection
# ---------------------------------------------------------------------------


def _is_cloud_model(name: str) -> bool:
    """Retourne True si le modèle est cloud-only (Ollama Cloud, crédits requis)."""
    return bool(is_cloud_only_model(str(name or "").strip()))


# Mapping categorie affichee -> use_case dans models.json
_CATEGORY_LABELS = {
    "Tous": None,
    "Raisonnement": "reasoning",
    "General": "general",
    "Finance": "reasoning_finance",
    "Code": "coding",
    "Instruction": "instruction",
    "Multimodal": "multimodal",
    "Securite": "safety",
    "☁\ufe0f Cloud": "__cloud__",
}


# ---------------------------------------------------------------------------
# Cache GPU info (ne change pas pendant une session)
# ---------------------------------------------------------------------------

_gpu_cache_state: dict[str, Any] = {"value": None, "ts": 0.0}


def _get_gpu_info() -> list[dict]:
    """Retourne les GPUs avec leur VRAM totale et libre (cache 60s)."""
    cached_value = _gpu_cache_state.get("value")
    cached_ts = float(_gpu_cache_state.get("ts", 0.0))
    if cached_value is not None and (time.time() - cached_ts) < 60:
        return list(cached_value)
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        gpus = []
        for line in result.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                gpus.append(
                    {
                        "name": parts[0],
                        "vram_total_mb": int(parts[1]),
                        "vram_free_mb": int(parts[2]),
                    },
                )
        _gpu_cache_state["value"] = gpus
        _gpu_cache_state["ts"] = time.time()
        return gpus
    except (OSError, subprocess.SubprocessError, ValueError):
        _gpu_cache_state["value"] = []
        _gpu_cache_state["ts"] = time.time()
        return []


def _get_total_vram_gb() -> float:
    """VRAM totale combinee de tous les GPUs en GB."""
    gpus = _get_gpu_info()
    return float(sum(float(g["vram_total_mb"]) for g in gpus)) / 1024.0


def _get_max_gpu_vram_gb() -> float:
    """VRAM totale du plus gros GPU local, utile pour un endpoint pinne sur une seule carte."""
    gpus = _get_gpu_info()
    if not gpus:
        return 0.0
    return max(float(g.get("vram_total_mb") or 0.0) for g in gpus) / 1024.0


# ---------------------------------------------------------------------------
# Cache inventaire Ollama
# ---------------------------------------------------------------------------

_ollama_inventory_cache: dict[str, dict[str, Any]] = {}


def _get_ollama_inventory_ttl_sec() -> float:
    raw_value = str(os.environ.get("BACKTEST_UI_OLLAMA_CACHE_TTL_SEC", "300") or "300").strip()
    try:
        return max(5.0, float(raw_value))
    except (TypeError, ValueError):
        return 300.0


def _normalize_host(ollama_host: str | None = None) -> str:
    host = str(
        ollama_host or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434",
    ).strip()
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host.rstrip("/")


def _is_local_ollama_host(ollama_host: str | None = None) -> bool:
    """Indique si l'endpoint Ollama cible est local à cette machine."""
    host = _normalize_host(ollama_host)
    try:
        parsed = urlparse(host)
    except (TypeError, ValueError):
        return False
    return (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def _resolve_selector_current_value(
    key: str,
    explicit_current_value: str | None = None,
) -> str:
    import streamlit as st

    return str(
        st.session_state.get(key) or explicit_current_value or st.session_state.get(f"{key}_manual") or "",
    ).strip()


def _build_empty_models_warning(
    ollama_host: str | None,
    *,
    service_available: bool,
) -> str:
    host = _normalize_host(ollama_host)
    if service_available:
        return f"Ollama répond sur `{host}`, mais aucun modèle installé n'a été détecté sur cette instance."
    return f"Aucun modèle Ollama détecté sur `{host}`. Le service est indisponible ou encore en démarrage."


def _resolve_selectbox_value(
    models: Sequence[str],
    current_value: str,
    stored_value: str,
) -> str:
    normalized_current = _normalize_model_name(str(current_value or "").strip())
    normalized_stored = _normalize_model_name(str(stored_value or "").strip())

    for candidate in models:
        normalized_candidate = _normalize_model_name(str(candidate))
        if normalized_candidate == normalized_current and normalized_current:
            return str(candidate)
    for candidate in models:
        normalized_candidate = _normalize_model_name(str(candidate))
        if normalized_candidate == normalized_stored and normalized_stored:
            return str(candidate)
    return str(models[0]) if models else ""


def _fetch_ollama_inventory(ollama_host: str | None = None) -> dict[str, Any]:
    """Charge une vue unifiée des modèles Ollama installés et de leurs détails."""
    host = _normalize_host(ollama_host)
    ttl_sec = _get_ollama_inventory_ttl_sec()
    cached = _ollama_inventory_cache.get(host)
    now = time.time()
    if cached is not None and (now - float(cached.get("ts", 0.0))) < ttl_sec:
        return cached

    inventory: dict[str, Any] = {
        "names": [],
        "details": {},
        "service_available": False,
        "ts": now,
    }
    try:
        import httpx

        resp = httpx.get(f"{host}/api/tags", timeout=3)
        if resp.status_code == 200:
            inventory["service_available"] = True
        data = resp.json() if resp.status_code == 200 else {}
        names: list[str] = []
        details_map: dict[str, dict[str, Any]] = {}
        for m in data.get("models", []):
            name = normalize_catalog_model_name(m["name"])
            names.append(name)
            details = m.get("details", {})
            details_map[name] = {
                "size_bytes": m.get("size", 0),
                "size_gb": round(m.get("size", 0) / (1024**3), 1),
                "parameters": details.get("parameter_size", "?"),
                "quantization": details.get("quantization_level", "?"),
                "family": details.get("family", "?"),
                "format": details.get("format", "?"),
            }
        inventory["names"] = names
        inventory["details"] = details_map
    except (httpx.HTTPError, OSError, ValueError, KeyError, AttributeError):
        pass

    inventory["ts"] = time.time()
    _ollama_inventory_cache[host] = inventory
    return inventory


def _get_installed_ollama_models(ollama_host: str | None = None) -> list[str]:
    """Retourne les noms de modèles installés à partir d'un inventaire cache unique."""
    inventory = _fetch_ollama_inventory(ollama_host)
    names = inventory.get("names", []) or []
    return [str(name) for name in names if str(name).strip()]


def _get_local_inventory_snapshot(ollama_host: str | None = None) -> Any:
    del ollama_host
    return None


def _get_local_inventory_models(ollama_host: str | None = None) -> list[str]:
    """Retourne les modèles locaux vérifiés via l'inventaire disque/manifests.

    Sert de secours quand Ollama n'a pas encore redémarré mais que les modèles
    sont toujours présents sur la machine.
    """
    inventory = _get_local_inventory_snapshot(ollama_host)
    if inventory is None:
        return []

    names: list[str] = []
    for model in inventory.discovered_models:
        if not model.verified_available or not backend_is_selectable(model.backend):
            continue
        normalized = _normalize_model_name(model.name)
        if normalized:
            names.append(normalized)
    return sorted(set(names))


def _get_local_non_ollama_inventory_models(ollama_host: str | None = None) -> list[dict[str, str]]:
    inventory = _get_local_inventory_snapshot(ollama_host)
    if inventory is None:
        return []

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for model in inventory.discovered_models:
        if not model.verified_available or not backend_is_detectable(model.backend):
            continue
        if backend_is_selectable(model.backend):
            continue
        name = str(model.name or "").strip()
        backend = str(model.backend or "").strip()
        if not name or not backend:
            continue
        key = (name.lower(), backend.lower())
        if key in seen:
            continue
        seen.add(key)
        rows.append({"name": name, "backend": backend})
    return sorted(rows, key=lambda item: (item["backend"], item["name"].lower()))


def _render_non_ollama_inventory_notice(
    models: Sequence[dict[str, str]],
    *,
    compact: bool = False,
) -> None:
    if not models:
        return

    import streamlit as st

    preview = ", ".join(f"{item['name']} ({item['backend']})" for item in models[:3])
    if len(models) > 3:
        preview = f"{preview}, +{len(models) - 3} autres"
    message = (
        "Autres modèles locaux détectés hors de ce sélecteur LLM: "
        f"{preview}. Ils ne sont pas sélectionnables ici tant que le runtime "
        "reste limité aux backends LLM Ollama/OpenAI."
    )
    if compact:
        st.caption(message)
    else:
        st.info(message)


def _fetch_ollama_details(ollama_host: str | None = None) -> dict[str, dict]:
    """Charge les détails des modèles Ollama depuis l'inventaire cache unique."""
    inventory = _fetch_ollama_inventory(ollama_host)
    return dict(inventory.get("details", {}) or {})


def _estimate_vram_gb(size_gb: float) -> float:
    """Estime la VRAM necessaire (taille disque + ~12% overhead KV cache)."""
    return round(size_gb * 1.12, 1)


# ---------------------------------------------------------------------------
# Enrichissement des infos modele
# ---------------------------------------------------------------------------


def get_model_details(model_name: str, ollama_host: str | None = None) -> dict:
    """Retourne des informations detaillees sur un modele.

    Fusionne: Ollama API + models.json + estimation VRAM.

    Returns:
        Dict avec: name, size_gb, vram_gb, parameters, quantization,
                   family, use_case, description, backup_path, fits_gpu

    """
    normalized_model_name = _normalize_model_name(model_name)
    ollama_data = _fetch_ollama_details(ollama_host).get(normalized_model_name, {})

    # Chercher dans models.json via la resolution d'alias centrale
    json_data = {}
    try:
        json_data = get_model_by_id(model_name) or {}
    except Exception:  # noqa: BLE001
        json_data = {}

    size_gb = ollama_data.get("size_gb") or json_data.get("size_gb") or "?"

    # Fallback 3 : KNOWN_MODELS — utilisé quand Ollama est hors ligne et que
    # models.json ne connaît pas le modèle.  On estime la taille disque depuis
    # params_billions (Q4_K_M empirique : ~0.55 GB / milliard de paramètres).
    _known_info = None
    if size_gb == "?":
        try:
            from agents.model_config import KNOWN_MODELS

            _known_info = KNOWN_MODELS.get(normalized_model_name) or KNOWN_MODELS.get(
                _normalize_model_name(model_name),
            )
            if _known_info and getattr(_known_info, "params_billions", 0) > 0:
                size_gb = round(_known_info.params_billions * 0.55, 1)
        except Exception:  # noqa: BLE001
            pass

    # Fallback 4 : extraction du count depuis le nom (ex: "fin-o1:14b-q6_k", "model:33b").
    # Couvre les modèles locaux installés mais absents de KNOWN_MODELS et de models.json.
    if size_gb == "?" and not _is_cloud_model(normalized_model_name or model_name):
        import re as _re

        _m = _re.search(r"[:\-_\.](\d+\.?\d*)b", (normalized_model_name or model_name), _re.IGNORECASE)
        if _m:
            _approx_params = float(_m.group(1))
            if 0.5 <= _approx_params <= 500:
                size_gb = round(_approx_params * 0.55, 1)

    vram_gb = _estimate_vram_gb(size_gb) if isinstance(size_gb, (int, float)) else "?"
    # On utilise la VRAM totale combinée (tous les GPUs) car Ollama distribue
    # automatiquement la charge. Le badge répond à "peut tourner sur cette machine ?".
    # La logique de pinning mono-GPU reste gérée séparément dans ollama_manager.
    total_vram = _get_total_vram_gb() if _is_local_ollama_host(ollama_host) else 0.0

    if isinstance(vram_gb, (int, float)) and total_vram > 0:
        fits_gpu = vram_gb <= total_vram
    else:
        fits_gpu = None

    return {
        "name": normalized_model_name or model_name,
        "display_name": json_data.get("name") or normalized_model_name or model_name,
        "size_gb": size_gb,
        "vram_gb": vram_gb,
        "parameters": (
            ollama_data.get("parameters")
            or json_data.get("parameters")
            or (
                f"{_known_info.params_billions:.0f}B"
                if _known_info and getattr(_known_info, "params_billions", 0) > 0
                else "?"
            )
        ),
        "quantization": ollama_data.get("quantization") or json_data.get("quantization", "?"),
        "family": ollama_data.get("family", "?"),
        "use_case": json_data.get("use_case", "general"),
        "description": json_data.get("description", ""),
        "backup_path": json_data.get("backup_path", ""),
        "context_length": json_data.get("context_length", 0),
        "aliases": list(json_data.get("aliases", []) or []),
        "fits_gpu": fits_gpu,
    }


# ---------------------------------------------------------------------------
# Fonctions publiques (inchangees pour compatibilite)
# ---------------------------------------------------------------------------


def _sort_with_preferred(
    models: Iterable[str],
    preferred_order: Sequence[str],
) -> list[str]:
    preferred_index = {name: i for i, name in enumerate(preferred_order)}

    def sort_key(name: str) -> tuple[int, ...]:
        if name in preferred_index:
            return (0, preferred_index[name])
        return (1, 0)

    unique = sorted(set(models), key=lambda n: (*sort_key(n), n))
    return unique


def _get_library_models() -> list[str]:
    try:
        return get_ollama_runtime_model_names()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Erreur lecture catalogue/manifests pour la liste UI: %s", exc)
        return []


def _normalize_model_name(name: str) -> str:
    return normalize_catalog_model_name(name)


def _get_cloud_only_models() -> list[str]:
    """Retourne la liste des modèles cloud-only sélectionnables (Free uniquement).

    Exclut les modèles Pro/Max payants — ils ne sont pas servis sur le plan Free et
    retournent HTTP 403 en runtime, donc ne doivent pas apparaître dans le sélecteur UI.
    """
    return list_cloud_only_model_names(include_subscription=False)


def get_available_models_for_ui(
    preferred_order: Sequence[str] | None = None,
    fallback: Sequence[str] | None = None,
    ollama_host: str | None = None,
    include_library_models: bool = False,
    current_value: str | None = None,
) -> list[str]:
    """Retourne la liste des modèles LLM pour l'UI.

    Règle stricte : uniquement les modèles **installés localement** (détectés via
    Ollama /api/tags) + les modèles **cloud-only** (toujours affichés, crédits requis).
    Les modèles présents dans le catalogue mais non installés ne sont PAS affichés.
    """
    installed_runtime = [_normalize_model_name(n) for n in _get_installed_ollama_models(ollama_host) if n]
    installed_inventory = _get_local_inventory_models(ollama_host)
    library_models = [_normalize_model_name(name) for name in _get_library_models() if name]
    installed_catalog = (
        library_models
        if include_library_models
        else []
    )
    installed = sorted(
        set(name for name in installed_runtime if name)
        | set(name for name in installed_catalog if name)
        | set(name for name in installed_inventory if name),
    )
    cloud_models = _get_cloud_only_models()
    fallback_order = [
        _normalize_model_name(name)
        for name in (fallback or get_model_selector_fallback_order())
        if _normalize_model_name(name)
    ]

    # Fusionner : installés locaux + cloud (dédupliqués)
    available = sorted(set(installed) | set(cloud_models))

    if installed:
        ordering = list(preferred_order or fallback_order)
        if ordering:
            return _sort_with_preferred(available, ordering)
        return available

    # Fallback ultime : si aucun modèle local n'est détecté,
    # on garde quand même les cloud-only + la valeur courante
    current_model = _normalize_model_name(str(current_value or "").strip())
    fallback_list: list[str] = []
    if not include_library_models:
        for model_name in _sort_with_preferred(library_models, fallback_order):
            if model_name not in fallback_list:
                fallback_list.append(model_name)
    for model_name in [name for name in fallback_order if name in cloud_models]:
        if model_name not in fallback_list:
            fallback_list.append(model_name)
    for model_name in cloud_models:
        if model_name not in fallback_list:
            fallback_list.append(model_name)
    if current_model and current_model not in fallback_list:
        fallback_list.insert(0, current_model)
    if fallback_list:
        logger.warning(
            "Aucun modèle local détecté sur %s — affichage limité aux modèles cloud.",
            _normalize_host(ollama_host),
        )
        return fallback_list

    return []


def get_model_info(model_name: str) -> dict:
    """Compatibilite: retourne {name, size_gb, description}."""
    details = get_model_details(model_name)
    return {
        "name": details["name"],
        "size_gb": details["size_gb"],
        "description": details["description"] or "Modele LLM",
    }


# ---------------------------------------------------------------------------
# Rendu Streamlit enrichi
# ---------------------------------------------------------------------------


def _vram_badge(fits_gpu: bool | None) -> str:
    if fits_gpu is True:
        return "🟢"
    if fits_gpu is False:
        return "🔴"
    return "⚪"


def _format_model_option(name: str, details: dict) -> str:
    """Formate le nom affiché dans le selectbox avec taille et badge GPU ou \u2601\ufe0f."""
    display_name = str(details.get("display_name") or name or "").strip() or name
    size = details.get("size_gb", "?")
    params = details.get("parameters", "?")
    if _is_cloud_model(name):
        badge = "\u2601\ufe0f"
        size_str = "Cloud"
    else:
        badge = _vram_badge(details.get("fits_gpu"))
        size_str = f"{size}G" if isinstance(size, (int, float)) else "?"
    label = display_name if display_name == name else f"{display_name} | {name}"
    return f"{badge} {label}  [{params} / {size_str}]"


def render_model_selector(
    label: str = "Modele LLM",
    key: str = "llm_model",
    preferred_order: Sequence[str] | None = None,
    help_text: str | None = None,
    show_details: bool = True,
    show_filter: bool = False,
    compact: bool = False,
    ollama_host: str | None = None,
    include_library_models: bool = False,
    fallback: Sequence[str] | None = None,
    current_value: str | None = None,
    display_mode: str = "selectbox",
) -> str:
    """Selecteur de modele Streamlit avec affichage riche.

    Args:
        label: Label du selectbox
        key: Cle du state Streamlit
        preferred_order: Ordre prefere des modeles
        help_text: Texte d'aide optionnel
        show_details: Afficher la fiche detaillee sous le selecteur
        show_filter: Afficher le filtre par categorie
        compact: Mode compact (sidebar) - reduit les infos
        display_mode: "selectbox" pour un menu compact, "radio" pour afficher
            toutes les options directement dans la page.

    Returns:
        str: Nom du modele selectionne (nom Ollama exact)

    """
    import streamlit as st

    current_value = _resolve_selector_current_value(
        key,
        explicit_current_value=current_value,
    )
    non_ollama_inventory_models = _get_local_non_ollama_inventory_models(ollama_host)
    installed_models = {
        _normalize_model_name(str(name or "").strip())
        for name in _get_installed_ollama_models(ollama_host)
        if str(name or "").strip()
    }
    models = get_available_models_for_ui(
        preferred_order=preferred_order,
        fallback=fallback,
        ollama_host=ollama_host,
        include_library_models=include_library_models,
        current_value=current_value,
    )

    if not models:
        service_available = False
        try:
            service_available = bool(is_ollama_available(ollama_host))
        except Exception:
            service_available = False
        manual_key = f"{key}_manual"
        selected = st.text_input(
            label,
            value=current_value,
            key=manual_key,
            help=(
                help_text
                or (
                    "Ollama répond mais aucun modèle installé n'a été détecté. "
                    "Saisissez le nom exact si vous voulez quand même le tenter."
                    if service_available
                    else "Aucun modele Ollama detecte. Saisissez le nom exact si vous voulez le tenter manuellement."
                )
            ),
        ).strip()
        st.warning(_build_empty_models_warning(ollama_host, service_available=service_available))
        st.caption("La valeur saisie n'est pas verifiee localement.")
        _render_non_ollama_inventory_notice(non_ollama_inventory_models, compact=compact)
        return selected

    # Filtre par categorie
    if show_filter and not compact:
        filter_key = f"{key}_category_filter"
        category = st.radio(
            "Categorie",
            list(_CATEGORY_LABELS.keys()),
            horizontal=True,
            key=filter_key,
            label_visibility="collapsed",
        )
        use_case_filter = _CATEGORY_LABELS.get(category)
        if use_case_filter == "__cloud__":
            filtered = [m for m in models if _is_cloud_model(m)]
            if filtered:
                models = filtered
        elif use_case_filter:
            filtered = []
            for m in models:
                d = get_model_details(m, ollama_host=ollama_host)
                if d["use_case"] == use_case_filter:
                    filtered.append(m)
            if filtered:
                models = filtered

    # Pre-charger les details pour le format_func
    details_map = {m: get_model_details(m, ollama_host=ollama_host) for m in models}

    if not help_text:
        help_text = "Selectionnez un modele LLM Ollama"

    desired_value = _resolve_selectbox_value(
        models,
        current_value=current_value,
        stored_value=str(st.session_state.get(key, "") or "").strip(),
    )
    if desired_value and st.session_state.get(key) != desired_value:
        st.session_state[key] = desired_value

    option_formatter = lambda name: _format_model_option(name, details_map.get(name, {}))
    if display_mode == "radio":
        selected = st.radio(
            label,
            models,
            key=key,
            help=help_text,
            format_func=option_formatter,
            horizontal=False,
        )
    else:
        selected = st.selectbox(
            label,
            models,
            key=key,
            help=help_text,
            format_func=option_formatter,
        )

    # Fiche detaillee
    if selected and show_details:
        d = details_map.get(selected) or get_model_details(selected, ollama_host=ollama_host)
        if _is_cloud_model(selected):
            st.info(
                "☁️ **Modèle Cloud Ollama** — Ce modèle s'exécute sur l'infrastructure Ollama Cloud. "
                "Il **nécessite des crédits Ollama**. Il ne sera pas téléchargé sur votre machine.",
                icon="☁️",
            )
        _render_model_card(d, compact=compact, ollama_host=ollama_host)
        if include_library_models and selected not in installed_models:
            st.caption(
                "ℹ️ Modèle issu du catalogue local, non vérifié sur l'instance Ollama courante. "
                "Il sera utilisé tel quel, avec erreur explicite s'il est absent côté serveur.",
            )

    _render_non_ollama_inventory_notice(non_ollama_inventory_models, compact=compact)

    return selected


def _render_model_card(
    d: dict,
    compact: bool = False,
    ollama_host: str | None = None,
) -> None:
    """Affiche la fiche d'un modele sous le selecteur."""
    import streamlit as st

    name = d["name"]
    display_name = str(d.get("display_name") or name or "").strip() or name
    size_gb = d["size_gb"]
    vram_gb = d["vram_gb"]
    params = d["parameters"]
    quant = d["quantization"]
    family = d["family"]
    desc = d["description"]
    backup = d.get("backup_path", "")
    aliases = list(d.get("aliases", []) or [])
    ctx = d.get("context_length", 0)
    fits = d.get("fits_gpu")

    # GPU info
    is_local_host = _is_local_ollama_host(ollama_host)
    gpus = _get_gpu_info() if is_local_host else []
    total_vram = _get_total_vram_gb() if is_local_host else 0.0

    if compact:
        # Mode sidebar : une ligne markdown
        badge = _vram_badge(fits)
        size_str = f"{size_gb}G" if isinstance(size_gb, (int, float)) else "?"
        vram_str = f"{vram_gb}G" if isinstance(vram_gb, (int, float)) else "?"
        if display_name != name:
            st.caption(f"**{display_name}**")
            st.caption(f"`{name}`")
        st.caption(f"{badge} **{params}** {quant} | Disque {size_str} | VRAM ~{vram_str}")
        if desc:
            st.caption(f"_{desc}_")
        return

    if display_name != name:
        st.markdown(f"**{display_name}**")
        st.caption(f"Identifiant runtime: `{name}`")
    if aliases:
        st.caption("Alias connus : " + ", ".join(f"`{alias}`" for alias in aliases[:2]))

    # Mode complet : tableau structuree
    col1, col2 = st.columns([1, 1])

    with col1:
        lines = [
            "| | |",
            "|---|---|",
            f"| **Parametres** | {params} |",
            f"| **Quantization** | {quant} |",
            f"| **Famille** | {family} |",
        ]
        if ctx:
            lines.append(f"| **Contexte** | {ctx:,} tokens |")
        st.markdown("\n".join(lines))

    with col2:
        size_str = f"{size_gb} GB" if isinstance(size_gb, (int, float)) else "?"
        vram_str = f"{vram_gb} GB" if isinstance(vram_gb, (int, float)) else "?"

        badge = _vram_badge(fits)
        if fits is True:
            gpu_status = f"{badge} Tient en VRAM ({total_vram:.0f} GB dispo)"
        elif fits is False:
            gpu_status = f"{badge} Depasse la VRAM ({total_vram:.0f} GB dispo)"
        elif not is_local_host:
            gpu_status = f"{badge} VRAM de l'hote distant inconnue"
        else:
            gpu_status = f"{badge} GPU non detecte"

        lines2 = [
            "| | |",
            "|---|---|",
            f"| **Taille disque** | {size_str} |",
            f"| **VRAM estimee** | ~{vram_str} |",
            f"| **GPU** | {gpu_status} |",
        ]
        if backup:
            lines2.append(f"| **Backup GGUF** | `{backup}` |")
        st.markdown("\n".join(lines2))

    if desc:
        st.caption(f"_{desc}_")

    # GPU details (expander)
    if gpus:
        with st.expander("Details GPU", expanded=False):
            for i, g in enumerate(gpus):
                total = g["vram_total_mb"] / 1024
                free = g["vram_free_mb"] / 1024
                used = total - free
                pct = (used / total * 100) if total > 0 else 0
                st.progress(
                    min(pct / 100, 1.0),
                    text=f"GPU {i}: {g['name']} - {used:.1f}/{total:.1f} GB ({pct:.0f}%)",
                )


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "get_available_models_for_ui",
    "get_model_details",
    "get_model_info",
    "render_model_selector",
]
