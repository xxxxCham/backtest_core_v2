"""Module-ID: ui.exec_tabs — Tabs mode d'exécution (pilot v0)

Ce module rend les onglets de sélection du mode d'exécution dans la page
principale (hors sidebar). Il est appelé depuis app.py après
render_setup_previews() et avant render_main().
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import re

import streamlit as st

from agents.llm_router import (
    LLMTopologyConfig,
    build_phase1_topology,
    build_single_host_topology,
)
from ui.constants import MODE_OPTIONS, build_strategy_options
from ui.context import (
    KNOWN_MODELS,
    LLM_AVAILABLE,
    LLM_IMPORT_ERROR,
    LLMConfig,
    LLMProvider,
    ModelCategory,
    RECOMMENDED_FOR_STRATEGY,
    ensure_ollama_running,
    get_global_model_config,
    is_ollama_available,
    list_available_models,
    list_strategies,
    set_global_model_config,
)
from ui.components.model_selector import render_model_selector
from ui.state import SidebarState

try:
    from core.llm_multi import (
        DEFAULT_MULTI_LLM_PROFILE,
        discover_local_models,
        install_missing_models,
        list_profile_names,
        plan_missing_downloads,
        resolve_profile_assignments,
    )

    _MULTI_LLM_AVAILABLE = True
except ImportError:
    DEFAULT_MULTI_LLM_PROFILE = "24GB_balanced"
    _MULTI_LLM_AVAILABLE = False

try:
    from agents.strategy_builder import (
        generate_parametric_catalog,
        generate_random_objective,
        get_catalog_coverage,
        get_next_catalog_objective,
        get_parametric_catalog_stats,
        reset_catalog_exploration,
        reset_parametric_catalog,
    )
    _CATALOG_AVAILABLE = True
except ImportError:
    _CATALOG_AVAILABLE = False


def _ollama_is_available(ollama_host: str | None = None) -> bool:
    """Retourne l'etat Ollama de maniere defensive si helper optionnel absent."""
    if callable(is_ollama_available):
        try:
            return bool(is_ollama_available(ollama_host=ollama_host))
        except Exception:
            return False
    return False


def _ollama_start_if_needed(ollama_host: str | None = None) -> tuple[bool, str]:
    """Demarre Ollama via le helper UI quand disponible."""
    if callable(ensure_ollama_running):
        try:
            return ensure_ollama_running(ollama_host=ollama_host)
        except Exception as exc:
            return False, f"Erreur demarrage Ollama: {exc}"
    return False, "Helper ensure_ollama_running indisponible"


def _prime_multiselect_state(
    key: str,
    *,
    desired: list[str],
    options: list[str],
) -> None:
    valid_desired = [item for item in desired if item in options]
    current_raw = st.session_state.get(key)
    current = current_raw if isinstance(current_raw, list) else []
    valid_current = [item for item in current if item in options]

    if valid_current:
        if valid_current != current:
            st.session_state[key] = valid_current
        return

    if st.session_state.get(key) != valid_desired:
        st.session_state[key] = valid_desired


LLM_ROUTING_MODE_STANDARD = "single_endpoint"
LLM_ROUTING_MODE_COOPERATIVE = "cooperative_multi_gpu"
LLM_ROUTING_MODE_OPTIONS = [
    LLM_ROUTING_MODE_STANDARD,
    LLM_ROUTING_MODE_COOPERATIVE,
]
LLM_ROUTING_MODE_LABELS = {
    LLM_ROUTING_MODE_STANDARD: "Standard mono-endpoint",
    LLM_ROUTING_MODE_COOPERATIVE: "Cooperation multi-GPU",
}
LLM_ROUTING_MODE_HELP = {
    LLM_ROUTING_MODE_STANDARD: (
        "Conserve le comportement historique: tous les roles et phases utilisent "
        "le meme endpoint Ollama."
    ),
    LLM_ROUTING_MODE_COOPERATIVE: (
        "Active le routage productif/controle sur plusieurs instances Ollama avec "
        "preuve d'execution."
    ),
}


def _normalize_llm_routing_mode(raw_value: object) -> str:
    value = str(raw_value or "").strip()
    if value in LLM_ROUTING_MODE_OPTIONS:
        return value
    return LLM_ROUTING_MODE_STANDARD


def _current_llm_routing_mode() -> str:
    return _normalize_llm_routing_mode(
        st.session_state.get("exec_llm_routing_mode", LLM_ROUTING_MODE_STANDARD)
    )


def _render_global_llm_routing_mode_control() -> None:
    st.markdown("#### Routage LLM")
    st.caption(
        "Cette bascule s'applique aux modes Optimisation LLM et Strategy Builder."
    )
    st.radio(
        "Profil de routage",
        options=LLM_ROUTING_MODE_OPTIONS,
        index=LLM_ROUTING_MODE_OPTIONS.index(_current_llm_routing_mode()),
        format_func=lambda mode: LLM_ROUTING_MODE_LABELS.get(mode, mode),
        key="exec_llm_routing_mode",
        horizontal=True,
    )
    st.caption(LLM_ROUTING_MODE_HELP.get(_current_llm_routing_mode(), ""))


@st.cache_data(show_spinner=False, ttl=60)
def _discover_gpu_inventory() -> List[Dict[str, Any]]:
    inventory: List[Dict[str, Any]] = []
    if os.name == "nt":
        try:
            cmd = (
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            raw = str(result.stdout or "").strip()
            if raw:
                payload = json.loads(raw)
                records = payload if isinstance(payload, list) else [payload]
                for index, record in enumerate(records):
                    item = record or {}
                    name = str(item.get("Name", "") or "").strip()
                    try:
                        memory_bytes = int(item.get("AdapterRAM") or 0)
                    except (TypeError, ValueError):
                        memory_bytes = 0
                    inventory.append(
                        {
                            "id": f"GPU-{index}",
                            "name": name or f"GPU {index}",
                            "memory_bytes": memory_bytes,
                        }
                    )
        except Exception:
            inventory = []

    if inventory:
        return inventory

    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in str(result.stdout or "").splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 3:
                continue
            try:
                gpu_index = int(parts[0])
                memory_bytes = int(parts[2]) * 1024 * 1024
            except (TypeError, ValueError):
                continue
            inventory.append(
                {
                    "id": f"GPU-{gpu_index}",
                    "name": parts[1] or f"GPU {gpu_index}",
                    "memory_bytes": memory_bytes,
                }
            )
    except Exception:
        return []

    return inventory


def _gpu_rank(item: Dict[str, Any]) -> tuple[int, int, int]:
    name = str(item.get("name", "") or "").lower()
    memory_bytes = int(item.get("memory_bytes") or 0)
    model_score = 0
    match = re.search(r"(?:rtx|gtx|rx)\s*(\d{3,4})", name)
    if match:
        try:
            model_score = int(match.group(1))
        except (TypeError, ValueError):
            model_score = 0
    if any(token in name for token in ("nvidia", "geforce", "rtx", "gtx", "quadro", "tesla")):
        vendor_rank = 3
    elif any(token in name for token in ("radeon rx", "intel arc")):
        vendor_rank = 2
    elif "graphics" in name or "vega" in name or "uhd" in name or "iris" in name:
        vendor_rank = 0
    else:
        vendor_rank = 1
    return vendor_rank, model_score, memory_bytes


def _format_gpu_option_label(item: Dict[str, Any]) -> str:
    memory_bytes = int(item.get("memory_bytes") or 0)
    memory_gib = memory_bytes / float(1024**3) if memory_bytes > 0 else 0.0
    memory_suffix = f" ({memory_gib:.1f} GiB)" if memory_gib > 0 else ""
    return f"{item['id']} · {item['name']}{memory_suffix}"


def _recommended_gpu_targets() -> tuple[str, str]:
    inventory = _discover_gpu_inventory()
    if not inventory:
        return "GPU-0", "GPU-1"
    ranked = sorted(inventory, key=_gpu_rank, reverse=True)
    primary = str(ranked[0].get("id", "GPU-0") or "GPU-0")
    control = (
        str(ranked[1].get("id", primary) or primary)
        if len(ranked) > 1
        else primary
    )
    return primary, control


def _is_generic_gpu_target(value: str) -> bool:
    normalized = str(value or "").strip()
    return normalized in {"", "auto", "GPU-0", "GPU-1"}


def _render_gpu_target_selector(
    *,
    label: str,
    key: str,
    default_value: str,
    help_text: str,
) -> str:
    inventory = _discover_gpu_inventory()
    option_map = {
        str(item.get("id", "")): _format_gpu_option_label(item)
        for item in inventory
        if str(item.get("id", "")).strip()
    }
    options = list(option_map.keys())
    fallback_value = str(default_value or "").strip() or (options[0] if options else "GPU-0")
    if fallback_value not in option_map:
        option_map[fallback_value] = fallback_value
        options.insert(0, fallback_value)
    current_value = str(st.session_state.get(key, fallback_value) or fallback_value).strip()
    if current_value not in option_map:
        option_map[current_value] = current_value
        options.insert(0, current_value)
    if key not in st.session_state or st.session_state.get(key) not in options:
        st.session_state[key] = current_value if current_value in options else fallback_value
    if options:
        selected = st.selectbox(
            label,
            options,
            key=key,
            format_func=lambda value: option_map.get(value, value),
            help=help_text,
        )
        return str(selected or fallback_value)
    return st.text_input(
        label,
        value=fallback_value,
        key=key,
        help=help_text,
    ).strip()


def _get_phase1_topology_from_session(primary_host: str) -> LLMTopologyConfig:
    data = st.session_state.get("exec_llm_topology_config")
    if isinstance(data, LLMTopologyConfig):
        topology = data
    elif isinstance(data, dict):
        topology = LLMTopologyConfig.from_dict(data)
    else:
        topology = build_phase1_topology(primary_host=primary_host)

    primary_endpoint = topology.endpoints.get(
        "builder_primary",
        topology.endpoints.get("default"),
    )
    control_endpoint = topology.endpoints.get("control", topology.endpoints.get("default"))
    recommended_primary_gpu, recommended_control_gpu = _recommended_gpu_targets()

    primary_default = str(getattr(primary_endpoint, "gpu_target", "") or "").strip()
    if (
        "llm_topology_primary_gpu_target" not in st.session_state
        and _is_generic_gpu_target(primary_default)
    ):
        primary_default = recommended_primary_gpu
    control_default = str(getattr(control_endpoint, "gpu_target", "") or "").strip()
    if (
        "llm_topology_control_gpu_target" not in st.session_state
        and _is_generic_gpu_target(control_default)
    ):
        control_default = recommended_control_gpu

    control_host = str(
        st.session_state.get(
            "llm_topology_control_host",
            getattr(control_endpoint, "ollama_host", primary_host),
        )
        or primary_host
    ).strip()
    primary_gpu = str(
        st.session_state.get(
            "llm_topology_primary_gpu_target",
            primary_default or recommended_primary_gpu,
        )
        or recommended_primary_gpu
    ).strip()
    control_gpu = str(
        st.session_state.get(
            "llm_topology_control_gpu_target",
            control_default or recommended_control_gpu,
        )
        or recommended_control_gpu
    ).strip()
    trace_only = bool(
        st.session_state.get(
            "llm_topology_trace_only",
            getattr(topology, "trace_only", True),
        )
    )

    if _current_llm_routing_mode() == LLM_ROUTING_MODE_COOPERATIVE:
        return build_phase1_topology(
            primary_host=primary_host,
            control_host=control_host,
            primary_gpu_target=primary_gpu or recommended_primary_gpu,
            control_gpu_target=control_gpu or recommended_control_gpu,
            trace_only=trace_only,
        )
    return build_single_host_topology(
        primary_host=primary_host,
        primary_gpu_target=primary_gpu or recommended_primary_gpu,
        trace_only=trace_only,
    )


def _render_phase1_topology_editor(
    *,
    primary_host: str,
    primary_label: str,
) -> LLMTopologyConfig:
    topology = _get_phase1_topology_from_session(primary_host)
    primary_endpoint = topology.endpoints.get(
        "builder_primary",
        topology.endpoints.get("default"),
    )
    control_endpoint = topology.endpoints.get("control", topology.endpoints.get("default"))
    routing_mode = _current_llm_routing_mode()

    with st.expander("🧭 Topologie multi-host (Phase 1)", expanded=False):
        if routing_mode == LLM_ROUTING_MODE_COOPERATIVE:
            st.caption(
                "Phase 1: séparation des endpoints productif et de contrôle avec "
                "preuve d'exécution, sans changer la logique métier."
            )
        else:
            st.caption(
                "Mode standard: toutes les phases et tous les rôles reviennent "
                "sur le même endpoint Ollama."
            )
        st.caption(f"{primary_label}: `{primary_host}`")
        if routing_mode == LLM_ROUTING_MODE_COOPERATIVE:
            st.text_input(
                "Endpoint contrôle / critique",
                value=str(
                    st.session_state.get(
                        "llm_topology_control_host",
                        getattr(control_endpoint, "ollama_host", primary_host),
                    )
                ),
                key="llm_topology_control_host",
                help=(
                    "Endpoint Ollama dédié aux rôles de contrôle "
                    "(critic/validator/analysis)."
                ),
            )

        col_gpu_a, col_gpu_b = st.columns(2)
        with col_gpu_a:
            _render_gpu_target_selector(
                label="GPU cible productif",
                key="llm_topology_primary_gpu_target",
                default_value=str(getattr(primary_endpoint, "gpu_target", "") or ""),
                help_text="GPU visé pour l'endpoint productif.",
            )
        with col_gpu_b:
            if routing_mode == LLM_ROUTING_MODE_COOPERATIVE:
                _render_gpu_target_selector(
                    label="GPU cible contrôle",
                    key="llm_topology_control_gpu_target",
                    default_value=str(getattr(control_endpoint, "gpu_target", "") or ""),
                    help_text="GPU visé pour l'endpoint de contrôle.",
                )
            else:
                st.caption("GPU cible contrôle")
                st.code(str(getattr(primary_endpoint, "gpu_target", "GPU-0") or "GPU-0"))

        st.toggle(
            "Mode trace-only",
            value=bool(
                st.session_state.get(
                    "llm_topology_trace_only",
                    getattr(topology, "trace_only", True),
                )
            ),
            key="llm_topology_trace_only",
            help=(
                "Active l'observabilité/routage de phase 1 sans introduire de "
                "nouvelles décisions parallèles."
            ),
        )
        if routing_mode == LLM_ROUTING_MODE_COOPERATIVE:
            st.caption("Routage phase 1 par défaut:")
            st.caption("- Builder proposal/code -> endpoint productif")
            st.caption("- Builder analysis/pre_reflection -> endpoint contrôle")
            st.caption("- Orchestrateur analyst/strategist -> endpoint productif")
            st.caption("- Orchestrateur critic/validator -> endpoint contrôle")
        else:
            st.caption("Routage standard:")
            st.caption("- Tous les rôles et phases -> endpoint productif unique")

    topology = _get_phase1_topology_from_session(primary_host)
    st.session_state["exec_llm_topology_config"] = topology.to_dict()
    return topology


# ── Clés session_state exposées aux onglets (lues ensuite par sidebar.py) ──
EXEC_GRID_USE_OPTUNA = "exec_grid_use_optuna"
EXEC_GRID_N_TRIALS = "exec_grid_n_trials"
EXEC_GRID_SAMPLER = "exec_grid_sampler"
EXEC_GRID_METRIC = "exec_grid_metric"
EXEC_GRID_PRUNING = "exec_grid_pruning"
EXEC_GRID_EARLY_STOP = "exec_grid_early_stop"


def _init_exec_tabs_state() -> None:
    """Initialisation idempotente — sûre à appeler à chaque rerun."""
    defaults: dict = {
        "optimization_mode": "Grille de Paramètres",
        "grid_worker_threads": 1,
        "exec_llm_routing_mode": LLM_ROUTING_MODE_STANDARD,
        EXEC_GRID_USE_OPTUNA: False,
        EXEC_GRID_N_TRIALS: 200,
        EXEC_GRID_SAMPLER: "tpe",
        EXEC_GRID_METRIC: "sharpe_ratio",
        EXEC_GRID_PRUNING: True,
        EXEC_GRID_EARLY_STOP: 0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ─────────────────────────────────────────────────────────────────────────────
# Commit B — Onglet Backtest Simple
# ─────────────────────────────────────────────────────────────────────────────

def _render_backtest_tab(state: SidebarState) -> None:
    """Contenu de l'onglet Backtest Simple."""
    st.markdown("#### 📊 Backtest Simple")
    st.caption("Teste **1 combinaison** de paramètres — résultat immédiat, idéal pour valider une hypothèse.")

    if state.strategy_key:
        col1, col2, col3 = st.columns(3)
        col1.metric("Stratégie", state.strategy_key)
        col2.metric("Symbole", state.symbol or "—")
        col3.metric("Timeframe", state.timeframe or "—")

        with st.expander("Paramètres appliqués", expanded=False):
            st.json(state.params)

        if state.use_walk_forward:
            st.info(f"🔬 Walk-Forward actif — {state.wfa_n_folds} folds, train {state.wfa_train_ratio:.0%}")
    else:
        st.info("Sélectionnez une stratégie dans la sidebar pour commencer.")

    st.markdown("---")
    if st.button(
        "🚀 Lancer le Backtest",
        type="primary",
        key="run_btn_backtest_tab",
        disabled=st.session_state.get("is_running", False),
    ):
        st.session_state.run_backtest_requested = True
        st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Commit C — Onglet Grille / Optuna
# ─────────────────────────────────────────────────────────────────────────────

def _render_grid_tab(state: SidebarState) -> None:
    """Contenu de l'onglet Grille de Paramètres / Optuna.

    Widgets écrits dans session_state (via key=).  sidebar.py les lit ensuite
    pour alimenter SidebarState avant chaque run.
    """
    st.markdown("#### 🔢 Grille de Paramètres / Optuna")
    n_workers = int(st.session_state.get("ui_n_workers", 32))

    use_optuna = st.checkbox(
        "⚡ Utiliser Optuna (Bayésien)",
        key=EXEC_GRID_USE_OPTUNA,
        help="Explore intelligemment l'espace — 10‑100× plus rapide que la grille exhaustive.",
    )

    if use_optuna:
        st.caption("🎯 **Mode Bayésien** — exploration intelligente")
        col_a, col_b = st.columns(2)
        with col_a:
            st.number_input(
                "Nombre de trials",
                min_value=10,
                max_value=10_000,
                step=10,
                key=EXEC_GRID_N_TRIALS,
                help="Recommandé : 100-500",
            )
            st.selectbox(
                "Algorithme",
                ["tpe", "cmaes", "random"],
                key=EXEC_GRID_SAMPLER,
                help="TPE : rapide | CMA-ES : espaces continus | Random : baseline",
            )
        with col_b:
            st.selectbox(
                "Métrique à optimiser",
                ["sharpe_ratio", "sortino_ratio", "total_return_pct", "profit_factor", "calmar_ratio"],
                key=EXEC_GRID_METRIC,
            )
            st.checkbox(
                "Pruning ✂️ (arrêt précoce)",
                key=EXEC_GRID_PRUNING,
                help="Abandonne les trials peu prometteurs — accélère la recherche.",
            )
        n_trials_val = int(st.session_state.get(EXEC_GRID_N_TRIALS, 200))
        st.slider(
            "Early stop patience (0 = désactivé)",
            min_value=0,
            max_value=max(200, n_trials_val),
            key=EXEC_GRID_EARLY_STOP,
            help="Arrêt après N trials sans amélioration.",
        )
        st.caption(f"⚡ {n_trials_val} trials × {n_workers} workers")
    else:
        st.caption("🔢 **Mode Grille exhaustive** — explore tous les points min/max/step")
        st.markdown("---")
        # CRITICAL: key='grid_worker_threads' conservée verbatim — lue par render_main
        _default_threads = max(1, min(int(st.session_state.get("grid_worker_threads", 1)), 16))
        if "grid_worker_threads" not in st.session_state:
            st.session_state["grid_worker_threads"] = _default_threads
        worker_threads = st.slider(
            "Threads par worker (CPU/BLAS)",
            min_value=1,
            max_value=16,
            step=1,
            key="grid_worker_threads",
            help="Total ≈ workers × threads. Recommandé : 1 si beaucoup de workers.",
        )
        st.caption(f"Total théorique : ~{n_workers * worker_threads} threads")

    # ── Commit D — Run button câblé dans l'onglet ──
    st.markdown("---")
    if st.button(
        "🧪 Lancer le Sweep",
        type="primary",
        key="run_btn_grid_tab",
        disabled=st.session_state.get("is_running", False),
    ):
        st.session_state.run_backtest_requested = True
        st.rerun()


def _render_builder_tab(state: SidebarState) -> None:
    """Contenu de l'onglet Strategy Builder.

    Reprise stricte du bloc Builder historiquement en sidebar.
    """
    st.markdown("#### 🏗️ Strategy Builder")
    st.caption(
        "Routage actif: "
        f"**{LLM_ROUTING_MODE_LABELS.get(_current_llm_routing_mode(), _current_llm_routing_mode())}**"
    )

    builder_autonomous = st.toggle(
        "🔄 Mode autonome 24/24",
        value=st.session_state.get("builder_autonomous", False),
        help="Génère automatiquement des objectifs variés et lance le builder en boucle continue.",
        key="builder_autonomous_toggle",
    )
    st.session_state["builder_autonomous"] = builder_autonomous

    builder_auto_pause = 10
    builder_auto_use_llm = True
    builder_multi_llm_enabled = False
    builder_multi_llm_profile = str(
        st.session_state.get("builder_multi_llm_profile", DEFAULT_MULTI_LLM_PROFILE)
    )
    builder_use_parametric_catalog = False

    if builder_autonomous:
        st.caption("*Objectifs générés automatiquement*")
        builder_auto_pause = st.slider(
            "⏱️ Pause entre runs (s)",
            min_value=0,
            max_value=120,
            value=st.session_state.get("builder_auto_pause", 10),
            key="builder_auto_pause_slider",
            help="Délai en secondes entre chaque session autonome.",
        )
        st.session_state["builder_auto_pause"] = builder_auto_pause

        builder_auto_use_llm = st.toggle(
            "🧠 Objectifs par LLM",
            value=st.session_state.get("builder_auto_use_llm", True),
            key="builder_auto_use_llm_toggle",
            help="Si activé, le LLM génère des objectifs créatifs. Sinon, templates aléatoires (plus rapide).",
        )
        st.session_state["builder_auto_use_llm"] = builder_auto_use_llm

        builder_multi_llm_enabled = st.toggle(
            "🧩 Mode multi-LLM",
            value=st.session_state.get("builder_multi_llm_enabled", False),
            key="builder_multi_llm_enabled_toggle",
            help=(
                "Active l'orchestration idea/builder/critic/risk/router "
                "dans le mode autonome, sans modifier le Builder classique."
            ),
            disabled=not _MULTI_LLM_AVAILABLE,
        )
        st.session_state["builder_multi_llm_enabled"] = builder_multi_llm_enabled

        if not _MULTI_LLM_AVAILABLE:
            st.caption("Mode multi-LLM indisponible dans ce workspace.")
        else:
            profile_options = list_profile_names()
            default_profile = str(
                st.session_state.get(
                    "builder_multi_llm_profile",
                    DEFAULT_MULTI_LLM_PROFILE,
                )
            )
            if default_profile not in profile_options and profile_options:
                default_profile = profile_options[0]
            if builder_multi_llm_enabled and profile_options:
                builder_multi_llm_profile = st.selectbox(
                    "Profil multi-LLM",
                    options=profile_options,
                    index=profile_options.index(default_profile),
                    key="builder_multi_llm_profile_select",
                    help="Profil de roles applique au Builder autonome multi-LLM.",
                )
            else:
                builder_multi_llm_profile = default_profile
            st.session_state["builder_multi_llm_profile"] = builder_multi_llm_profile

        builder_use_parametric_catalog = st.toggle(
            "📐 Catalogue paramétrique",
            value=st.session_state.get("builder_use_parametric_catalog", False),
            key="builder_use_parametric_catalog_toggle",
            help=(
                "Génère automatiquement des fiches de stratégies paramétriques "
                "(archetypes × param_packs) et les injecte comme objectifs. "
                "Prioritaire sur les templates et le LLM."
            ),
        )
        st.session_state["builder_use_parametric_catalog"] = builder_use_parametric_catalog

        if builder_use_parametric_catalog and _CATALOG_AVAILABLE:
            try:
                pstats = get_parametric_catalog_stats()
                if pstats.get("generated"):
                    p_total = pstats.get("total", 0)
                    p_idx = pstats.get("index", 0)
                    p_pct = pstats.get("coverage_pct", 0.0)
                    st.caption(f"Fiches param.: {p_idx}/{p_total} ({p_pct:.0f}%)")
                    st.progress(min(p_pct / 100.0, 1.0))
                else:
                    st.caption("Fiches param.: non encore générées")
                if st.button(
                    "Reset fiches param.",
                    key="builder_reset_parametric",
                    help="Régénère immédiatement le catalogue paramétrique avec de nouvelles fiches aléatoires.",
                ):
                    reset_parametric_catalog()
                    import time
                    new_seed = int(time.time() * 1000) % 2**31
                    generate_parametric_catalog(seed=new_seed)
                    st.rerun()
            except Exception:
                pass

        if _CATALOG_AVAILABLE and not builder_use_parametric_catalog:
            try:
                cov = get_catalog_coverage()
                total = cov.get("total_objectives", 0)
                explored = cov.get("explored_count", 0)
                pct = cov.get("coverage_pct", 0.0)
                success_count = cov.get("success_count", 0)
                if total > 0:
                    cycles = explored // total if total else 0
                    pos_in_cycle = explored % total
                    if cycles > 0:
                        cycle_label = f"cycle {cycles + 1}, {pos_in_cycle}/{total}"
                    else:
                        cycle_label = f"{explored}/{total} ({pct:.0f}%)"
                    st.caption(f"Catalogue templates: {cycle_label} — {success_count} positifs")
                    st.progress(min((explored % total) / total, 1.0) if total else 0.0)
                    if st.button(
                        "Reset exploration",
                        key="builder_reset_catalog",
                        help="Re-shuffle et remet la couverture a zero.",
                    ):
                        reset_catalog_exploration()
                        st.rerun()
            except Exception:
                pass

    pending_objective_sync = st.session_state.pop(
        "_builder_objective_input_sync", None
    )
    if isinstance(pending_objective_sync, str):
        st.session_state["builder_objective_input"] = pending_objective_sync

    if not builder_autonomous and _CATALOG_AVAILABLE:
        if st.button(
            "🎲 Objectif aléatoire",
            key="builder_random_objective_btn",
            help="Pré-remplit avec un objectif du catalogue. Vous pouvez le modifier avant de lancer.",
        ):
            _sym = (
                st.session_state.get("selected_symbol")
                or "BTCUSDC"
            )
            _tf = (
                st.session_state.get("selected_timeframe")
                or "1h"
            )
            _cat = get_next_catalog_objective(symbol=_sym, timeframe=_tf)
            if _cat is not None:
                _rand_obj, _ = _cat
            else:
                _rand_obj = generate_random_objective(symbol=_sym, timeframe=_tf)
            st.session_state["builder_objective"] = _rand_obj
            st.session_state["builder_objective_input"] = _rand_obj
            st.rerun()

    builder_objective = st.text_area(
        "🎯 Objectif de la stratégie",
        value=st.session_state.get("builder_objective", ""),
        height=100,
        placeholder=(
            "Ex: Trend-following BTC 1h avec EMA + RSI.\n"
            "Mean reversion sur Bollinger bands + ATR filter.\n"
            "Scalping MACD cross avec stop ATR serré."
        ),
        help="Décrivez la stratégie que l'IA doit créer. Soyez précis sur les indicateurs, le style, et les objectifs.",
        key="builder_objective_input",
        disabled=builder_autonomous,
    )
    st.session_state["builder_objective"] = builder_objective

    _market_pick_default = st.session_state.get("builder_auto_market_pick", True)
    builder_auto_market_pick = st.toggle(
        "🧭 LLM choisit token/TF",
        value=_market_pick_default,
        key="builder_auto_market_pick_toggle",
        help=(
            "Avant chaque session Builder, le LLM sélectionne automatiquement "
            "le symbole et le timeframe les plus adaptés à l'objectif, puis "
            "charge les données correspondantes. "
            "Activé par défaut en mode autonome 24/24."
        ),
    )
    st.session_state["builder_auto_market_pick"] = builder_auto_market_pick

    with st.expander("💡 Exemple de format", expanded=False):
        st.markdown(
            "**Structure recommandée :**\n"
            "```\n"
            "[Style] sur [marché] [timeframe].\n"
            "Indicateurs : [ind1] + [ind2] + [ind3].\n"
            "Entrées : [conditions d'entrée].\n"
            "Sorties : [conditions de sortie].\n"
            "Risk management : [SL/TP/sizing].\n"
            "```\n\n"
            "**Exemple concret :**\n"
            "> Trend-following sur BTCUSDC 30m.\n"
            "> Utiliser EMA(20/50) + MACD + ATR.\n"
            "> Entrée long quand EMA rapide croise\n"
            "> au-dessus de la lente ET MACD > signal.\n"
            "> Stop-loss = 1.5x ATR, take-profit = 3x ATR."
        )

    builder_ollama_host = st.text_input(
        "URL Ollama (Builder)",
        value=str(
            st.session_state.get(
                "builder_ollama_host",
                os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
            )
        ),
        key="builder_ollama_host",
        help="Endpoint Ollama utilisé par le mode Strategy Builder.",
    ).strip()
    builder_topology = _render_phase1_topology_editor(
        primary_host=builder_ollama_host,
        primary_label="Endpoint productif Builder",
    )
    current_builder_model = str(
        st.session_state.get("builder_model_select")
        or st.session_state.get("builder_model")
        or "deepseek-r1:32b"
    ).strip()
    builder_model = render_model_selector(
        label="Modele LLM",
        key="builder_model_select",
        help_text=(
            "Modèles installés sur Ollama en priorité, puis catalogue local connu "
            "si l'inventaire serveur est incomplet. Aucun fallback silencieux n'est appliqué."
        ),
        show_details=True,
        compact=True,
        ollama_host=builder_ollama_host,
        include_library_models=True,
        current_value=current_builder_model,
    )
    st.session_state["builder_model"] = builder_model
    if builder_autonomous and builder_multi_llm_enabled:
        st.caption(
            "En mode multi-LLM, ce sélecteur sert uniquement de fallback mono-LLM; "
            "les rôles spécialisés restent pilotés par le profil actif."
        )

    if builder_autonomous and builder_multi_llm_enabled and _MULTI_LLM_AVAILABLE:
        with st.expander("🧩 Inventaire et roles multi-LLM", expanded=True):
            inventory = discover_local_models(
                ollama_host=builder_ollama_host,
                include_live_ollama=True,
            )
            require_live_ollama = bool(inventory.live_ollama_reachable)
            resolution = resolve_profile_assignments(
                builder_multi_llm_profile,
                inventory,
                require_live_ollama=require_live_ollama,
            )
            summary = inventory.summary()
            st.caption(
                f"Inventaire local: {summary['verified_models']} verifies / "
                f"{summary['total_models']} references | "
                f"backends: {summary['by_backend']}"
            )
            if require_live_ollama:
                st.caption(
                    f"Validation runtime active sur `{summary['live_ollama_host']}`."
                )
            else:
                st.warning(
                    "Validation runtime Ollama impossible pour le moment: "
                    "affichage basé sur l'inventaire local, pas sur l'hôte actif."
                )
            role_rows = [
                {
                    "role": assignment.role,
                    "demande": assignment.requested_model,
                    "resolu": assignment.resolved_model or "-",
                    "pret_runtime": assignment.available,
                    "visible_hote": assignment.live if assignment.backend == "ollama" else "-",
                    "source": assignment.source or "-",
                    "raison": assignment.reason or "-",
                }
                for assignment in resolution["assignments"]
            ]
            st.dataframe(role_rows, width="stretch")
            unavailable_roles = [
                assignment
                for assignment in resolution["assignments"]
                if not assignment.available
            ]
            missing_requests = plan_missing_downloads(
                builder_multi_llm_profile,
                inventory,
                require_live_ollama=require_live_ollama,
            )
            host_only_unavailable = [
                assignment.role
                for assignment in unavailable_roles
                if not assignment.install_required
            ]
            if host_only_unavailable:
                st.warning(
                    "Roles détectés localement mais non exposés par l'hôte Ollama actif: "
                    + ", ".join(host_only_unavailable)
                )
            if missing_requests:
                st.warning(
                    "Roles manquants: "
                    + ", ".join(request.role for request in missing_requests)
                )
                if st.button(
                    "⬇️ Installer les modeles manquants",
                    key="builder_multi_llm_install_missing",
                    help="Tente un ollama pull pour les roles manquants.",
                ):
                    results = install_missing_models(
                        missing_requests,
                        ollama_host=builder_ollama_host,
                    )
                    st.session_state["builder_multi_llm_install_results"] = [
                        result.to_dict() for result in results
                    ]
                    if all(result.success for result in results):
                        st.success("Installation terminee.")
                    else:
                        st.warning("Installation partielle ou echec sur certains roles.")
            elif not unavailable_roles:
                st.success("Tous les roles du profil sont resolus localement.")

            last_install_results = st.session_state.get(
                "builder_multi_llm_install_results",
                [],
            )
            if last_install_results:
                with st.expander("Derniers resultats d'installation", expanded=False):
                    st.json(last_install_results)
            with st.expander("Inventaire brut", expanded=False):
                st.json(inventory.to_dict())

    st.caption("**🔌 Chargement du modèle**")
    builder_auto_start_state = bool(st.session_state.get("builder_auto_start_ollama", True))
    builder_ollama_available = _ollama_is_available(builder_ollama_host)
    if builder_ollama_available:
        st.caption(f"🟢 Ollama connecté sur `{builder_ollama_host}`")
    else:
        st.warning(f"⚠️ Ollama non détecté sur `{builder_ollama_host}`")
    st.caption(
        "Démarrage auto local: "
        f"{'ON' if builder_auto_start_state else 'OFF'}"
    )
    builder_ollama_action_label = (
        "🧪 Tester Ollama" if builder_ollama_available else "🚀 Démarrer Ollama"
    )
    if st.button(builder_ollama_action_label, key="builder_start_ollama"):
        with st.spinner("Vérification / démarrage d'Ollama..."):
            success, msg = _ollama_start_if_needed(builder_ollama_host)
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    builder_auto_start_ollama = st.toggle(
        "Auto-démarrer Ollama (local)",
        value=st.session_state.get("builder_auto_start_ollama", True),
        key="builder_auto_start_ollama",
        help=(
            "Si URL locale (localhost/127.0.0.1), tente de démarrer Ollama "
            "automatiquement avant l'exécution."
        ),
    )
    builder_preload_model = st.toggle(
        "Précharger modèle avant run",
        value=st.session_state.get("builder_preload_model", True),
        key="builder_preload_model",
        help="Charge le modèle en mémoire avant les appels LLM du builder.",
    )
    builder_keep_alive_minutes = st.slider(
        "Keep-alive modèle (minutes)",
        min_value=1,
        max_value=120,
        value=int(st.session_state.get("builder_keep_alive_minutes", 20)),
        key="builder_keep_alive_minutes",
        help="Durée de maintien en mémoire du modèle après warmup.",
        disabled=not builder_preload_model,
    )
    builder_unload_after_run = st.toggle(
        "Décharger modèle après run",
        value=st.session_state.get("builder_unload_after_run", False),
        key="builder_unload_after_run",
        help="Libère la VRAM à la fin d'une session Builder.",
    )

    st.caption("**⚙️ Paramètres de construction**")
    builder_max_iterations = st.slider(
        "Itérations max",
        min_value=1,
        max_value=30,
        value=st.session_state.get("builder_max_iterations", 10),
        key="builder_max_iters_slider",
        help="Nombre maximum de tentatives pour améliorer la stratégie.",
    )
    builder_target_sharpe = st.number_input(
        "Sharpe cible",
        min_value=0.0,
        max_value=5.0,
        value=st.session_state.get("builder_target_sharpe", 1.0),
        step=0.1,
        key="builder_target_sharpe_input",
        help="Sharpe ratio minimum pour accepter automatiquement la stratégie.",
    )
    builder_capital = st.number_input(
        "Capital initial ($)",
        min_value=100.0,
        max_value=1_000_000.0,
        value=st.session_state.get("builder_capital", 10000.0),
        step=1000.0,
        key="builder_capital_input",
        format="%.0f",
    )

    try:
        from indicators.registry import list_indicators
        indicators = list_indicators()
        st.caption(f"📐 {len(indicators)} indicateurs disponibles")
        with st.expander("Voir la liste", expanded=False):
            st.write(", ".join(sorted(indicators)))
    except Exception:
        pass

    sandbox_root = Path(__file__).resolve().parent.parent / "sandbox_strategies"
    if sandbox_root.exists():
        sessions = sorted(
            [d.name for d in sandbox_root.iterdir() if d.is_dir() and d.name != ".gitkeep"],
            reverse=True,
        )
        if sessions:
            with st.expander(f"📁 Sessions précédentes ({len(sessions)})", expanded=False):
                for s in sessions[:10]:
                    st.caption(f"• {s}")

    # Garder des variables locales synchronisées pour debug lisible
    _ = (
        builder_ollama_host,
        builder_topology,
        builder_auto_start_ollama,
        builder_keep_alive_minutes,
        builder_unload_after_run,
        builder_max_iterations,
        builder_target_sharpe,
        builder_capital,
        builder_auto_pause,
        builder_auto_use_llm,
        builder_multi_llm_enabled,
        builder_multi_llm_profile,
        builder_use_parametric_catalog,
    )


def _render_llm_tab(state: SidebarState) -> None:
    """Contenu de l'onglet Optimisation LLM (migration depuis sidebar)."""
    st.markdown("#### 🤖 Optimisation LLM")
    st.caption("∞ Combinaisons LLM (non limitées)")
    st.caption(
        "Routage actif: "
        f"**{LLM_ROUTING_MODE_LABELS.get(_current_llm_routing_mode(), _current_llm_routing_mode())}**"
    )
    n_workers = int(st.session_state.get("ui_n_workers", 32))
    st.caption(f"🔧 Parallélisation: jusqu'à {n_workers} backtests simultanés")

    llm_config = None
    llm_model = None
    llm_use_multi_agent = False
    llm_max_iterations = 10
    llm_use_walk_forward = True
    llm_unload_during_backtest = bool(st.session_state.get("llm_unload_during_backtest", True))
    role_model_config = None

    llm_compare_enabled = False
    llm_compare_auto_run = True
    llm_compare_strategies: list[str] = []
    llm_compare_tokens: list[str] = []
    llm_compare_timeframes: list[str] = []
    llm_compare_metric = "sharpe_ratio"
    llm_compare_aggregate = "median"
    llm_compare_max_runs = 25
    llm_compare_use_preset = True
    llm_compare_generate_report = True

    available_strategies = list_strategies() if callable(list_strategies) else []
    strategy_options = build_strategy_options(available_strategies)
    strategy_name = state.strategy_name or next(iter(strategy_options.keys()), "")
    symbol = state.symbol
    timeframe = state.timeframe
    available_tokens = state.available_tokens
    available_timeframes = state.available_timeframes

    if not LLM_AVAILABLE:
        st.error("❌ Module LLM non disponible")
        st.caption(f"Erreur: {LLM_IMPORT_ERROR}")
    else:
        llm_provider = st.selectbox(
            "Provider LLM",
            ["Ollama (Local)", "OpenAI"],
            key="exec_llm_provider",
            help="Ollama = gratuit et local | OpenAI = API payante",
        )

        llm_use_multi_agent = st.checkbox(
            "Mode multi-agents 👥",
            value=bool(st.session_state.get("llm_use_multi_agent", False)),
            key="llm_use_multi_agent",
            help="Utiliser Analyst/Strategist/Critic/Validator",
        )

        def _extract_model_params_b(model_name: str) -> float | None:
            match = re.search(r"(\d+(?:\.\d+)?)b", model_name.lower())
            if match:
                return float(match.group(1))
            return None

        def _is_model_under_limit(model_name: str, limit: float) -> bool:
            size = _extract_model_params_b(model_name)
            return bool(size is not None and size < limit)

        def _is_model_over_limit(model_name: str, limit: float) -> bool:
            size = _extract_model_params_b(model_name)
            return bool(size is not None and size >= limit)

        if "Ollama" in llm_provider:
            ollama_host = st.text_input(
                "URL Ollama",
                value=str(
                    st.session_state.get(
                        "exec_llm_ollama_host",
                        os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
                    )
                ),
                key="exec_llm_ollama_host",
                help="Adresse du serveur Ollama",
            ).strip()
            llm_topology = _render_phase1_topology_editor(
                primary_host=ollama_host,
                primary_label="Endpoint productif orchestrateur",
            )
            exec_ollama_available = _ollama_is_available(ollama_host)
            if exec_ollama_available:
                st.caption(f"🟢 Ollama connecté sur `{ollama_host}`")
            else:
                st.warning(f"⚠️ Ollama non détecté sur `{ollama_host}`")
            exec_ollama_action_label = (
                "🧪 Tester Ollama" if exec_ollama_available else "🚀 Démarrer Ollama"
            )
            if st.button(exec_ollama_action_label, key="exec_start_ollama"):
                with st.spinner("Vérification / démarrage d'Ollama..."):
                    success, msg = _ollama_start_if_needed(ollama_host)
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

            llm_use_multi_model = False
            if llm_use_multi_agent:
                llm_use_multi_model = st.checkbox(
                    "Multi-modeles par role",
                    value=bool(st.session_state.get("llm_use_multi_model", False)),
                    key="llm_use_multi_model",
                    help="Assigner differents modeles a chaque role d'agent",
                )

            if llm_use_multi_model:
                available_models_list = list_available_models() if callable(list_available_models) else []
                available_model_names = [m.name for m in available_models_list]

                llm_limit_small_models = st.checkbox(
                    "Limiter selection aleatoire a <20B",
                    value=bool(st.session_state.get("llm_limit_small_models", True)),
                    key="llm_limit_small_models",
                    help="Filtre la liste par taille et exclut deepseek-r1:70b",
                )
                llm_limit_large_models = st.checkbox(
                    "Limiter selection aleatoire a >=20B",
                    value=bool(st.session_state.get("llm_limit_large_models", False)),
                    key="llm_limit_large_models",
                    help="Filtre la liste par taille (>=20B uniquement)",
                )

                effective_small_filter = llm_limit_small_models
                effective_large_filter = llm_limit_large_models
                if effective_small_filter and effective_large_filter:
                    st.warning("Filtres <20B et >=20B actifs: >=20B prioritaire.")
                    effective_small_filter = False

                excluded_models = set()
                if not effective_large_filter:
                    excluded_models = {"deepseek-r1:70b"}
                if excluded_models:
                    available_model_names = [m for m in available_model_names if m not in excluded_models]

                if effective_small_filter:
                    filtered = [m for m in available_model_names if _is_model_under_limit(m, 20)]
                    if filtered:
                        available_model_names = filtered
                    else:
                        st.warning("Aucun modele <20B detecte, filtre desactive.")

                if effective_large_filter:
                    filtered = [m for m in available_model_names if _is_model_over_limit(m, 20)]
                    if filtered:
                        available_model_names = filtered
                    else:
                        available_model_names = []
                        st.warning("Aucun modele >=20B detecte.")

                role_model_config = get_global_model_config() if callable(get_global_model_config) else None
                if role_model_config is None:
                    st.warning("Configuration multi-modeles indisponible, fallback en mode single-model.")
                    llm_use_multi_model = False
                    available_model_names = []

            if llm_use_multi_model and role_model_config is not None:

                def model_with_badge(name: str) -> str:
                    info = KNOWN_MODELS.get(name) if isinstance(KNOWN_MODELS, dict) else None
                    if info:
                        if info.category == ModelCategory.LIGHT:
                            return f"[L] {name}"
                        if info.category == ModelCategory.MEDIUM:
                            return f"[M] {name}"
                        return f"[H] {name}"
                    return name

                model_options_display = [model_with_badge(m) for m in available_model_names]
                name_to_display = {n: model_with_badge(n) for n in available_model_names}
                display_to_name = {v: k for k, v in name_to_display.items()}

                st.caption("**Modeles par role d'agent**")
                analyst_defaults = [
                    name_to_display.get(m, m)
                    for m in role_model_config.analyst.models
                    if m in available_model_names
                ]
                strategist_defaults = [
                    name_to_display.get(m, m)
                    for m in role_model_config.strategist.models
                    if m in available_model_names
                ]
                critic_defaults = [
                    name_to_display.get(m, m)
                    for m in role_model_config.critic.models
                    if m in available_model_names
                ]
                validator_defaults = [
                    name_to_display.get(m, m)
                    for m in role_model_config.validator.models
                    if m in available_model_names
                ]

                _prime_multiselect_state(
                    "analyst_models",
                    desired=analyst_defaults[:3] if analyst_defaults else model_options_display[:2],
                    options=model_options_display,
                )
                _prime_multiselect_state(
                    "strategist_models",
                    desired=strategist_defaults[:3] if strategist_defaults else model_options_display[:2],
                    options=model_options_display,
                )
                _prime_multiselect_state(
                    "critic_models",
                    desired=critic_defaults[:3] if critic_defaults else model_options_display[:2],
                    options=model_options_display,
                )
                _prime_multiselect_state(
                    "validator_models",
                    desired=validator_defaults[:3] if validator_defaults else model_options_display[:2],
                    options=model_options_display,
                )

                analyst_selection = st.multiselect(
                    "Modeles Analyst",
                    model_options_display,
                    key="analyst_models",
                )
                strategist_selection = st.multiselect(
                    "Modeles Strategist",
                    model_options_display,
                    key="strategist_models",
                )
                critic_selection = st.multiselect(
                    "Modeles Critic",
                    model_options_display,
                    key="critic_models",
                )
                validator_selection = st.multiselect(
                    "Modeles Validator",
                    model_options_display,
                    key="validator_models",
                )

                heavy_after_iter = st.number_input(
                    "Autoriser apres iteration N",
                    min_value=1,
                    max_value=20,
                    value=3,
                    key="exec_llm_heavy_after_iter",
                )

                def _normalize_selection(selection: list[str]) -> list[str]:
                    names = [display_to_name.get(m, m) for m in selection]
                    return [n for n in names if n in available_model_names]

                role_model_config.analyst.models = _normalize_selection(analyst_selection)
                role_model_config.strategist.models = _normalize_selection(strategist_selection)
                role_model_config.critic.models = _normalize_selection(critic_selection)
                role_model_config.validator.models = _normalize_selection(validator_selection)
                for assignment in [
                    role_model_config.analyst,
                    role_model_config.strategist,
                    role_model_config.critic,
                    role_model_config.validator,
                ]:
                    assignment.allow_heavy_after_iteration = heavy_after_iter

                if callable(set_global_model_config):
                    set_global_model_config(role_model_config)
                if role_model_config.analyst.models:
                    llm_model = role_model_config.analyst.models[0]
                elif available_model_names:
                    llm_model = available_model_names[0]
            else:
                current_exec_llm_model = str(
                    st.session_state.get("llm_model_select")
                    or st.session_state.get("exec_llm_model")
                    or st.session_state.get("llm_model")
                    or ""
                ).strip()
                llm_model = render_model_selector(
                    label="Modele Ollama",
                    key="llm_model_select",
                    preferred_order=RECOMMENDED_FOR_STRATEGY,
                    help_text=(
                        "Modèles installés sur Ollama en priorité, puis catalogue local connu "
                        "si l'inventaire serveur est incomplet. Aucun fallback silencieux n'est appliqué."
                    ),
                    show_details=True,
                    compact=True,
                    ollama_host=ollama_host,
                    include_library_models=True,
                    current_value=current_exec_llm_model,
                )
            if llm_model and callable(LLMConfig):
                llm_config = LLMConfig(
                    provider=LLMProvider.OLLAMA,
                    model=llm_model,
                    ollama_host=ollama_host,
                )
            st.session_state["exec_llm_topology_config"] = llm_topology.to_dict()
        else:
            openai_key = st.text_input(
                "Clé API OpenAI",
                type="password",
                key="exec_llm_openai_key",
                help="Votre clé API OpenAI",
            )
            llm_model = st.selectbox(
                "Modèle OpenAI",
                ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
                key="exec_llm_openai_model",
                help="gpt-4o-mini recommandé pour coût/performance",
            )
            if openai_key and callable(LLMConfig):
                llm_config = LLMConfig(
                    provider=LLMProvider.OPENAI,
                    model=llm_model,
                    api_key=openai_key,
                )
            else:
                st.warning("⚠️ Clé API requise")

        with st.expander("⚙️ Options d'optimisation LLM", expanded=False):
            llm_unlimited_iterations = st.checkbox(
                "Itérations illimitées",
                value=bool(st.session_state.get("llm_unlimited_iterations", True)),
                key="llm_unlimited_iterations",
            )

            if llm_unlimited_iterations:
                llm_max_iterations = 0
                st.caption("∞ itérations (arrêt manuel)")
            else:
                llm_max_iterations = st.slider(
                    "Max itérations",
                    min_value=3,
                    max_value=50,
                    value=int(st.session_state.get("exec_llm_max_iterations", 10)),
                    key="exec_llm_max_iterations",
                )

            walk_forward_enabled = True
            df_cached = st.session_state.get("ohlcv_df")
            if df_cached is not None and not df_cached.empty:
                data_duration_days = (df_cached.index[-1] - df_cached.index[0]).days
                if (data_duration_days / 30.44) < 6:
                    walk_forward_enabled = False

            llm_use_walk_forward = st.checkbox(
                "Walk-Forward Validation",
                value=bool(st.session_state.get("exec_llm_use_walk_forward", walk_forward_enabled)),
                disabled=not walk_forward_enabled,
                key="exec_llm_use_walk_forward",
            )

            llm_unload_during_backtest = st.checkbox(
                "Décharger LLM du GPU",
                value=bool(st.session_state.get("exec_llm_unload", llm_unload_during_backtest)),
                key="exec_llm_unload",
            )

        with st.expander("Comparaison multi-strategies", expanded=False):
            llm_compare_enabled = st.checkbox(
                "Comparer strategies (multi-tokens/timeframes)",
                value=bool(st.session_state.get("llm_compare_enabled", False)),
                key="llm_compare_enabled",
            )
            if llm_compare_enabled:
                llm_compare_auto_run = st.checkbox(
                    "Execution automatique",
                    value=bool(st.session_state.get("llm_compare_auto_run", True)),
                    key="llm_compare_auto_run",
                )
                _prime_multiselect_state(
                    "llm_compare_strategy_labels",
                    desired=[strategy_name] if strategy_name else [],
                    options=list(strategy_options.keys()),
                )
                compare_strategy_labels = st.multiselect(
                    "Strategies a comparer",
                    list(strategy_options.keys()),
                    key="llm_compare_strategy_labels",
                )
                llm_compare_strategies = [
                    strategy_options[label]
                    for label in compare_strategy_labels
                    if label in strategy_options
                ]
                _prime_multiselect_state(
                    "llm_compare_tokens",
                    desired=[symbol] if symbol else [],
                    options=available_tokens,
                )
                llm_compare_tokens = st.multiselect(
                    "Tokens",
                    available_tokens,
                    key="llm_compare_tokens",
                )
                _prime_multiselect_state(
                    "llm_compare_timeframes",
                    desired=[timeframe] if timeframe else [],
                    options=available_timeframes,
                )
                llm_compare_timeframes = st.multiselect(
                    "Timeframes",
                    available_timeframes,
                    key="llm_compare_timeframes",
                )
                llm_compare_metric = st.selectbox(
                    "Metrica principale",
                    ["sharpe_ratio", "total_return_pct", "max_drawdown", "win_rate"],
                    index=0,
                    key="llm_compare_metric",
                )
                llm_compare_aggregate = st.selectbox(
                    "Agregation",
                    ["median", "mean", "worst"],
                    index=0,
                    key="llm_compare_aggregate",
                )
                llm_compare_max_runs = int(st.number_input(
                    "Max runs comparaison",
                    min_value=1,
                    max_value=500,
                    value=int(st.session_state.get("llm_compare_max_runs", 25)),
                    step=1,
                    key="llm_compare_max_runs",
                ))
                llm_compare_use_preset = st.checkbox(
                    "Utiliser presets si disponibles",
                    value=bool(st.session_state.get("llm_compare_use_preset", True)),
                    key="llm_compare_use_preset",
                )
                llm_compare_generate_report = st.checkbox(
                    "Generer justification LLM",
                    value=bool(st.session_state.get("llm_compare_generate_report", True)),
                    key="llm_compare_generate_report",
                )

                if not llm_compare_auto_run:
                    if "llm_compare_run_now" not in st.session_state:
                        st.session_state["llm_compare_run_now"] = False
                    if st.button("Lancer comparaison", key="llm_compare_run_button"):
                        st.session_state["llm_compare_run_now"] = True
            else:
                if "llm_compare_run_now" in st.session_state:
                    st.session_state["llm_compare_run_now"] = False

    st.session_state["exec_llm_config_obj"] = llm_config
    st.session_state["exec_llm_model"] = llm_model
    st.session_state["exec_llm_use_multi_agent"] = llm_use_multi_agent
    st.session_state["exec_llm_role_model_config"] = role_model_config
    st.session_state["exec_llm_max_iterations"] = llm_max_iterations
    st.session_state["exec_llm_use_walk_forward"] = llm_use_walk_forward
    st.session_state["exec_llm_unload"] = llm_unload_during_backtest
    st.session_state["exec_llm_compare_enabled"] = llm_compare_enabled
    st.session_state["exec_llm_compare_auto_run"] = llm_compare_auto_run
    st.session_state["exec_llm_compare_strategies"] = llm_compare_strategies
    st.session_state["exec_llm_compare_tokens"] = llm_compare_tokens
    st.session_state["exec_llm_compare_timeframes"] = llm_compare_timeframes
    st.session_state["exec_llm_compare_metric"] = llm_compare_metric
    st.session_state["exec_llm_compare_aggregate"] = llm_compare_aggregate
    st.session_state["exec_llm_compare_max_runs"] = llm_compare_max_runs
    st.session_state["exec_llm_compare_use_preset"] = llm_compare_use_preset
    st.session_state["exec_llm_compare_generate_report"] = llm_compare_generate_report


def render_exec_tabs(state: SidebarState) -> None:
    """Affiche les onglets de mode d'exécution dans la page principale.

    Appelé depuis app.py APRÈS render_setup_previews(), AVANT render_main().
    Un clic sur un onglet inactif bascule le mode et relance un rerun.

    Args:
        state: État sidebar courant (lecture seule ici).
    """
    _init_exec_tabs_state()
    _render_global_llm_routing_mode_control()
    st.markdown("---")

    tab_labels = [f"{icon} {name}" for name, icon, _desc in MODE_OPTIONS]
    tabs = st.tabs(tab_labels)

    for i, ((mode_name, icon, desc), tab) in enumerate(zip(MODE_OPTIONS, tabs)):
        with tab:
            if state.optimization_mode != mode_name:
                if st.button(
                    f"→ Activer {icon} {mode_name}",
                    key=f"tab_activate_{i}",
                    help=desc,
                    disabled=st.session_state.get("is_running", False),
                ):
                    st.session_state.optimization_mode = mode_name
                    st.rerun()
            else:
                st.caption(f"✅ Mode actif — {desc}")
            # Contenu spécifique au mode actif
                if mode_name == "Backtest Simple":
                    _render_backtest_tab(state)
                elif mode_name == "Grille de Paramètres":
                    _render_grid_tab(state)
                elif mode_name == "🤖 Optimisation LLM":
                    _render_llm_tab(state)
                elif mode_name == "🏗️ Strategy Builder":
                    _render_builder_tab(state)
