"""
Module-ID: ui.components.model_selector

Purpose: Selecteur modeles LLM - query Ollama, fallback list, recommendations par role.
         Affichage riche avec details (VRAM, taille, categorie, backup path).

Role in pipeline: configuration

Key components: get_available_models_for_ui(), render_model_selector(), get_model_details()

Inputs: Ollama endpoint (optionnel), role (Analyst/Strategist/Critic/Validator)

Outputs: Model list [str], model details [dict], rendered selector widget

Dependencies: agents.ollama_manager (optionnel), utils.model_loader, httpx
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

try:
    from agents.ollama_manager import is_ollama_available, list_ollama_models
except ImportError:
    def list_ollama_models() -> List[str]:
        return []

    def is_ollama_available(ollama_host: Optional[str] = None) -> bool:
        return False
from utils.log import get_logger
from utils.model_loader import (
    get_model_by_id,
    get_ollama_runtime_model_names,
    normalize_model_name as normalize_catalog_model_name,
)

try:
    from core.llm_multi import discover_local_models
except ImportError:
    discover_local_models = None

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Helper cloud detection
# ---------------------------------------------------------------------------

def _is_cloud_model(name: str) -> bool:
    """Retourne True si le modèle est cloud-only (Ollama Cloud, crédits requis)."""
    try:
        from agents.model_config import KNOWN_MODELS
        info = KNOWN_MODELS.get(str(name or "").strip())
        return bool(info and info.cloud_only)
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

FALLBACK_LLM_MODELS: List[str] = [
    # Local
    "gemma4:31b",
    "gemma4:26b",
    "qwen3.5:35b",
    "qwen3-vl:32b",
    "lfm2:24b",
    "devstral-small-2:24b",
    "qwen3-coder:30b",
    "deepseek-r1:70b",
    "deepseek-r1:32b",
    "qwq:32b",
    "qwen2.5:32b",
    "mistral:22b",
    "deepseek-r1-distill:14b",
    "deepseek-r1:8b",
    "mistral:7b-instruct",
    # Cloud (nécessite crédits Ollama)
    "deepseek-v3.2",
    "glm-5",
    "qwen3-coder:480b",
    "kimi-k2",
    "kimi-k2-thinking",
    "minimax-m2.7",
    "nemotron-3-super:120b",
    "devstral-2:123b",
    "qwen3.5:122b",
    # deepseek-r1:671b et deepseek-v3:671b : téléchargeables (non cloud), retirés d'ici
    "nemotron-3-nano:30b",
]

RECOMMENDED_FOR_ANALYSIS = ["gemma4:26b", "qwen3-vl:32b", "qwen3.5:35b"]
RECOMMENDED_FOR_STRATEGY = ["gemma4:26b", "gemma4:31b", "qwen3.5:35b"]
RECOMMENDED_FOR_CRITICISM = ["gemma4:31b", "qwen3.5:35b", "deepseek-r1:32b"]
RECOMMENDED_FOR_FAST = ["gemma4:26b", "lfm2:24b", "mistral:7b-instruct"]

OPTIMAL_CONFIG_BY_ROLE = {
    "analyst": ["gemma4:26b", "qwen3-vl:32b"],
    "strategist": ["gemma4:26b", "gemma4:31b"],
    "critic": ["gemma4:31b", "qwen3.5:35b"],
    "validator": ["gemma4:31b", "deepseek-r1:32b"],
}

OPTIMAL_CONFIG_FALLBACK = {
    "analyst": ["lfm2:24b", "gemma4:26b"],
    "strategist": ["qwen3-coder:30b", "devstral-small-2:24b"],
    "critic": ["gemma4:26b", "mistral:22b"],
    "validator": ["gemma4:26b", "qwq:32b"],
}

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

_gpu_cache: Optional[List[Dict]] = None
_gpu_cache_ts: float = 0.0


def _get_gpu_info() -> List[Dict]:
    """Retourne les GPUs avec leur VRAM totale et libre (cache 60s)."""
    global _gpu_cache, _gpu_cache_ts
    if _gpu_cache is not None and (time.time() - _gpu_cache_ts) < 60:
        return _gpu_cache
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        gpus = []
        for line in result.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                gpus.append({
                    "name": parts[0],
                    "vram_total_mb": int(parts[1]),
                    "vram_free_mb": int(parts[2]),
                })
        _gpu_cache = gpus
        _gpu_cache_ts = time.time()
        return gpus
    except Exception:
        _gpu_cache = []
        _gpu_cache_ts = time.time()
        return []


def _get_total_vram_gb() -> float:
    """VRAM totale combinee de tous les GPUs en GB."""
    gpus = _get_gpu_info()
    return sum(g["vram_total_mb"] for g in gpus) / 1024


# ---------------------------------------------------------------------------
# Cache inventaire Ollama
# ---------------------------------------------------------------------------

_ollama_inventory_cache: Dict[str, Dict[str, Any]] = {}


def _get_ollama_inventory_ttl_sec() -> float:
    raw_value = str(os.environ.get("BACKTEST_UI_OLLAMA_CACHE_TTL_SEC", "300") or "300").strip()
    try:
        return max(5.0, float(raw_value))
    except Exception:
        return 300.0


def _normalize_host(ollama_host: Optional[str] = None) -> str:
    host = str(
        ollama_host
        or os.environ.get("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).strip()
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host.rstrip("/")


def _is_local_ollama_host(ollama_host: Optional[str] = None) -> bool:
    """Indique si l'endpoint Ollama cible est local à cette machine."""
    host = _normalize_host(ollama_host)
    try:
        parsed = urlparse(host)
    except Exception:
        return False
    return (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def _resolve_selector_current_value(
    key: str,
    explicit_current_value: Optional[str] = None,
) -> str:
    import streamlit as st

    return str(
        st.session_state.get(key)
        or explicit_current_value
        or st.session_state.get(f"{key}_manual")
        or ""
    ).strip()


def _build_empty_models_warning(
    ollama_host: Optional[str],
    *,
    service_available: bool,
) -> str:
    host = _normalize_host(ollama_host)
    if service_available:
        return (
            f"Ollama répond sur `{host}`, mais aucun modèle installé n'a été détecté "
            "sur cette instance."
        )
    return (
        f"Aucun modèle Ollama détecté sur `{host}`. "
        "Le service est indisponible ou encore en démarrage."
    )


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


def _fetch_ollama_inventory(ollama_host: Optional[str] = None) -> Dict[str, Any]:
    """Charge une vue unifiée des modèles Ollama installés et de leurs détails."""
    host = _normalize_host(ollama_host)
    ttl_sec = _get_ollama_inventory_ttl_sec()
    cached = _ollama_inventory_cache.get(host)
    now = time.time()
    if cached is not None and (now - float(cached.get("ts", 0.0))) < ttl_sec:
        return cached

    inventory: Dict[str, Any] = {
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
        names: List[str] = []
        details_map: Dict[str, Dict[str, Any]] = {}
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
    except Exception:
        pass

    inventory["ts"] = time.time()
    _ollama_inventory_cache[host] = inventory
    return inventory


def _get_installed_ollama_models(ollama_host: Optional[str] = None) -> List[str]:
    """Retourne les noms de modèles installés à partir d'un inventaire cache unique."""
    inventory = _fetch_ollama_inventory(ollama_host)
    names = inventory.get("names", []) or []
    return [str(name) for name in names if str(name).strip()]


def _get_local_inventory_models(ollama_host: Optional[str] = None) -> List[str]:
    """Retourne les modèles locaux vérifiés via l'inventaire disque/manifests.

    Sert de secours quand Ollama n'a pas encore redémarré mais que les modèles
    sont toujours présents sur la machine.
    """
    if not callable(discover_local_models):
        return []
    try:
        inventory = discover_local_models(
            ollama_host=ollama_host,
            include_live_ollama=True,
        )
    except Exception as exc:
        logger.debug("Erreur lecture inventaire local modèles: %s", exc)
        return []

    names: List[str] = []
    for model in inventory.discovered_models:
        if model.backend != "ollama" or not model.verified_available:
            continue
        normalized = _normalize_model_name(model.name)
        if normalized:
            names.append(normalized)
    return sorted(set(names))


def _fetch_ollama_details(ollama_host: Optional[str] = None) -> Dict[str, Dict]:
    """Charge les détails des modèles Ollama depuis l'inventaire cache unique."""
    inventory = _fetch_ollama_inventory(ollama_host)
    return dict(inventory.get("details", {}) or {})


def _estimate_vram_gb(size_gb: float) -> float:
    """Estime la VRAM necessaire (taille disque + ~12% overhead KV cache)."""
    return round(size_gb * 1.12, 1)


# ---------------------------------------------------------------------------
# Enrichissement des infos modele
# ---------------------------------------------------------------------------

def get_model_details(model_name: str, ollama_host: Optional[str] = None) -> Dict:
    """
    Retourne des informations detaillees sur un modele.

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
    except Exception:
        json_data = {}

    size_gb = ollama_data.get("size_gb") or json_data.get("size_gb") or "?"
    vram_gb = _estimate_vram_gb(size_gb) if isinstance(size_gb, (int, float)) else "?"
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
        "parameters": ollama_data.get("parameters") or json_data.get("parameters", "?"),
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
    models: Iterable[str], preferred_order: Sequence[str]
) -> List[str]:
    preferred_index = {name: i for i, name in enumerate(preferred_order)}

    def sort_key(name: str) -> Tuple[int, ...]:
        if name in preferred_index:
            return (0, preferred_index[name])
        return (1, 0)

    unique = sorted(set(models), key=lambda n: (*sort_key(n), n))
    return unique


def _get_library_models() -> List[str]:
    try:
        return get_ollama_runtime_model_names()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Erreur lecture catalogue/manifests pour la liste UI: %s", exc)
        return []


def _normalize_model_name(name: str) -> str:
    return normalize_catalog_model_name(name)


def _get_cloud_only_models() -> List[str]:
    """Retourne la liste des modèles cloud-only définis dans KNOWN_MODELS."""
    try:
        from agents.model_config import KNOWN_MODELS
        return [name for name, info in KNOWN_MODELS.items() if info.cloud_only]
    except Exception:
        return []


def get_available_models_for_ui(
    preferred_order: Sequence[str] | None = None,
    fallback: Sequence[str] | None = None,
    ollama_host: Optional[str] = None,
    include_library_models: bool = False,
    current_value: Optional[str] = None,
) -> List[str]:
    """Retourne la liste des modèles LLM pour l'UI.

    Règle stricte : uniquement les modèles **installés localement** (détectés via
    Ollama /api/tags) + les modèles **cloud-only** (toujours affichés, crédits requis).
    Les modèles présents dans le catalogue mais non installés ne sont PAS affichés.
    """
    installed_runtime = [
        _normalize_model_name(n) for n in _get_installed_ollama_models(ollama_host) if n
    ]
    installed_inventory = _get_local_inventory_models(ollama_host)
    installed_catalog = [
        _normalize_model_name(name) for name in _get_library_models() if name
    ]
    installed = sorted(
        set(name for name in installed_runtime if name)
        | set(name for name in installed_catalog if name)
        | set(name for name in installed_inventory if name)
    )
    cloud_models = _get_cloud_only_models()

    # Fusionner : installés locaux + cloud (dédupliqués)
    available = sorted(set(installed) | set(cloud_models))

    if available:
        if preferred_order:
            return _sort_with_preferred(available, preferred_order)
        return available

    # Fallback ultime : si aucun modèle local n'est détecté,
    # on garde quand même les cloud-only + la valeur courante
    current_model = _normalize_model_name(str(current_value or "").strip())
    fallback_list: List[str] = list(cloud_models)
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


def get_optimal_config_for_role(
    role: str,
    available_models: List[str],
) -> List[str]:
    optimal_primary = OPTIMAL_CONFIG_BY_ROLE.get(role, [])
    available_set = set(available_models)
    optimal_available = [m for m in optimal_primary if m in available_set]
    if optimal_available:
        return optimal_available

    fallback_options = OPTIMAL_CONFIG_FALLBACK.get(role, [])
    fallback_available = [m for m in fallback_options if m in available_set]
    if fallback_available:
        return fallback_available[:1]

    return available_models[:1] if available_models else []


# ---------------------------------------------------------------------------
# Rendu Streamlit enrichi
# ---------------------------------------------------------------------------

def _vram_badge(fits_gpu: Optional[bool]) -> str:
    if fits_gpu is True:
        return "🟢"
    elif fits_gpu is False:
        return "🔴"
    return "⚪"


def _format_model_option(name: str, details: Dict) -> str:
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
    ollama_host: Optional[str] = None,
    include_library_models: bool = False,
    fallback: Sequence[str] | None = None,
    current_value: Optional[str] = None,
) -> str:
    """
    Selecteur de modele Streamlit avec affichage riche.

    Args:
        label: Label du selectbox
        key: Cle du state Streamlit
        preferred_order: Ordre prefere des modeles
        help_text: Texte d'aide optionnel
        show_details: Afficher la fiche detaillee sous le selecteur
        show_filter: Afficher le filtre par categorie
        compact: Mode compact (sidebar) - reduit les infos

    Returns:
        str: Nom du modele selectionne (nom Ollama exact)
    """
    import streamlit as st

    current_value = _resolve_selector_current_value(
        key,
        explicit_current_value=current_value,
    )
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

    selected = st.selectbox(
        label,
        models,
        key=key,
        help=help_text,
        format_func=lambda name: _format_model_option(name, details_map.get(name, {})),
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
                "Il sera utilisé tel quel, avec erreur explicite s'il est absent côté serveur."
            )

    return selected


def _render_model_card(
    d: Dict,
    compact: bool = False,
    ollama_host: Optional[str] = None,
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
            f"| | |",
            f"|---|---|",
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
            f"| | |",
            f"|---|---|",
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
    "FALLBACK_LLM_MODELS",
    "RECOMMENDED_FOR_ANALYSIS",
    "RECOMMENDED_FOR_STRATEGY",
    "RECOMMENDED_FOR_CRITICISM",
    "RECOMMENDED_FOR_FAST",
    "OPTIMAL_CONFIG_BY_ROLE",
    "OPTIMAL_CONFIG_FALLBACK",
    "get_available_models_for_ui",
    "get_model_info",
    "get_model_details",
    "get_optimal_config_for_role",
    "render_model_selector",
]
