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
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from agents.ollama_manager import is_ollama_available, list_ollama_models
except ImportError:
    def list_ollama_models() -> List[str]:
        return []

    def is_ollama_available(ollama_host: Optional[str] = None) -> bool:
        return False
from utils.log import get_logger
from utils.model_loader import get_model_info_for_ui, get_ollama_model_names, load_models_json

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

FALLBACK_LLM_MODELS: List[str] = [
    "deepseek-r1:70b",
    "deepseek-r1:32b",
    "qwq:32b",
    "qwen2.5:32b",
    "mistral:22b",
    "gemma3:27b",
    "deepseek-r1-distill:14b",
    "gemma3:12b",
    "deepseek-r1:8b",
    "mistral:7b-instruct",
    "qwen3-coder:30b",
    "nemotron-3-nano:30b",
]

RECOMMENDED_FOR_ANALYSIS = ["deepseek-r1:32b", "qwq:32b", "qwen2.5:32b"]
RECOMMENDED_FOR_STRATEGY = ["deepseek-r1:70b", "deepseek-r1:32b", "qwq:32b"]
RECOMMENDED_FOR_CRITICISM = ["mistral:22b", "gemma3:27b", "qwen2.5:32b"]
RECOMMENDED_FOR_FAST = ["deepseek-r1:8b", "mistral:7b-instruct", "gemma3:12b"]

OPTIMAL_CONFIG_BY_ROLE = {
    "analyst": ["qwen2.5:32b"],
    "strategist": ["gemma3:27b"],
    "critic": ["llama3.3:70b-instruct-q4_K_M"],
    "validator": ["llama3.3:70b-instruct-q4_K_M"],
}

OPTIMAL_CONFIG_FALLBACK = {
    "analyst": ["deepseek-r1:8b", "gemma3:12b"],
    "strategist": ["gemma3:27b", "mistral:22b"],
    "critic": ["deepseek-r1:32b", "qwq:32b"],
    "validator": ["deepseek-r1:32b", "qwq:32b"],
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
# Cache Ollama model details
# ---------------------------------------------------------------------------

_ollama_details_cache: Optional[Dict[Tuple[str, str], Dict]] = None
_ollama_details_ts: float = 0.0


def _normalize_host(ollama_host: Optional[str] = None) -> str:
    host = str(
        ollama_host
        or os.environ.get("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).strip()
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host.rstrip("/")


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


def _fetch_ollama_details(ollama_host: Optional[str] = None) -> Dict[str, Dict]:
    """Charge les details de tous les modeles Ollama (cache 30s)."""
    global _ollama_details_cache, _ollama_details_ts
    host = _normalize_host(ollama_host)
    if _ollama_details_cache is not None and (time.time() - _ollama_details_ts) < 30:
        cached = _ollama_details_cache.get((host, "details"))
        if cached is not None:
            return cached
    try:
        import httpx
        resp = httpx.get(f"{host}/api/tags", timeout=3)
        data = resp.json()
        result = {}
        for m in data.get("models", []):
            name = m["name"]
            if name.endswith(":latest"):
                name = name[:-7]
            details = m.get("details", {})
            result[name] = {
                "size_bytes": m.get("size", 0),
                "size_gb": round(m.get("size", 0) / (1024**3), 1),
                "parameters": details.get("parameter_size", "?"),
                "quantization": details.get("quantization_level", "?"),
                "family": details.get("family", "?"),
                "format": details.get("format", "?"),
            }
        if _ollama_details_cache is None:
            _ollama_details_cache = {}
        _ollama_details_cache[(host, "details")] = result
        _ollama_details_ts = time.time()
        return result
    except Exception:
        if _ollama_details_cache is None:
            _ollama_details_cache = {}
        _ollama_details_cache[(host, "details")] = {}
        _ollama_details_ts = time.time()
        return {}


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
    ollama_data = _fetch_ollama_details(ollama_host).get(model_name, {})

    # Chercher dans models.json
    json_data = {}
    try:
        models_json = load_models_json()
        for m in models_json.get("ollama_models", []):
            ollama_nm = m.get("ollama_name", "")
            if ollama_nm.endswith(":latest"):
                ollama_nm = ollama_nm[:-7]
            if ollama_nm == model_name:
                json_data = m
                break
    except Exception:
        pass

    size_gb = ollama_data.get("size_gb") or json_data.get("size_gb") or "?"
    vram_gb = _estimate_vram_gb(size_gb) if isinstance(size_gb, (int, float)) else "?"
    total_vram = _get_total_vram_gb()

    if isinstance(vram_gb, (int, float)) and total_vram > 0:
        fits_gpu = vram_gb <= total_vram
    else:
        fits_gpu = None

    return {
        "name": model_name,
        "size_gb": size_gb,
        "vram_gb": vram_gb,
        "parameters": ollama_data.get("parameters") or json_data.get("parameters", "?"),
        "quantization": ollama_data.get("quantization") or json_data.get("quantization", "?"),
        "family": ollama_data.get("family", "?"),
        "use_case": json_data.get("use_case", "general"),
        "description": json_data.get("description", ""),
        "backup_path": json_data.get("backup_path", ""),
        "context_length": json_data.get("context_length", 0),
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
        return get_ollama_model_names()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Erreur lecture models.json pour la liste UI: %s", exc)
        return []


def _normalize_model_name(name: str) -> str:
    if name.endswith(":latest"):
        return name.rsplit(":", 1)[0]
    return name


def get_available_models_for_ui(
    preferred_order: Sequence[str] | None = None,
    fallback: Sequence[str] | None = None,
    ollama_host: Optional[str] = None,
    include_library_models: bool = False,
    current_value: Optional[str] = None,
) -> List[str]:
    """Retourne la liste dedupliquee des modeles LLM pour l'UI."""
    installed = [
        _normalize_model_name(n) for n in list_ollama_models(ollama_host) if n
    ]
    library_models = _get_library_models() if include_library_models else []
    available = sorted(set(installed) | set(library_models))

    if available:
        if preferred_order:
            return _sort_with_preferred(available, preferred_order)
        return available

    current_model = _normalize_model_name(str(current_value or "").strip())
    if current_model:
        logger.warning(
            "Ollama ne renvoie aucun modele sur %s, conservation de la valeur courante UI: %s",
            _normalize_host(ollama_host),
            current_model,
        )
        return [current_model]

    models = list(fallback or [])
    if models:
        logger.warning("Ollama ne renvoie aucun modele, fallback UI explicite: %s", models[:3])
    return models


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
    """Formate le nom affiche dans le selectbox avec taille et badge GPU."""
    size = details.get("size_gb", "?")
    params = details.get("parameters", "?")
    badge = _vram_badge(details.get("fits_gpu"))
    size_str = f"{size}G" if isinstance(size, (int, float)) else "?"
    return f"{badge} {name}  [{params} / {size_str}]"


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
        for name in list_ollama_models(ollama_host)
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
        if use_case_filter:
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
        _render_model_card(d, compact=compact)
        if include_library_models and selected not in installed_models:
            st.caption(
                "ℹ️ Modèle issu du catalogue local, non vérifié sur l'instance Ollama courante. "
                "Il sera utilisé tel quel, avec erreur explicite s'il est absent côté serveur."
            )

    return selected


def _render_model_card(d: Dict, compact: bool = False) -> None:
    """Affiche la fiche d'un modele sous le selecteur."""
    import streamlit as st

    name = d["name"]
    size_gb = d["size_gb"]
    vram_gb = d["vram_gb"]
    params = d["parameters"]
    quant = d["quantization"]
    family = d["family"]
    desc = d["description"]
    backup = d.get("backup_path", "")
    ctx = d.get("context_length", 0)
    fits = d.get("fits_gpu")

    # GPU info
    gpus = _get_gpu_info()
    total_vram = _get_total_vram_gb()

    if compact:
        # Mode sidebar : une ligne markdown
        badge = _vram_badge(fits)
        size_str = f"{size_gb}G" if isinstance(size_gb, (int, float)) else "?"
        vram_str = f"{vram_gb}G" if isinstance(vram_gb, (int, float)) else "?"
        st.caption(f"{badge} **{params}** {quant} | Disque {size_str} | VRAM ~{vram_str}")
        if desc:
            st.caption(f"_{desc}_")
        return

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
