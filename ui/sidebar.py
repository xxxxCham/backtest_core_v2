"""
Module-ID: ui.sidebar

Purpose: Gère la configuration et les contrôles de la sidebar pour la sélection de stratégies et paramètres.

Role in pipeline: configuration / inputs

Key components: render_sidebar, gestion des paramètres

Inputs: Données disponibles, stratégies

Outputs: SidebarState configuré

Dependencies: ui.context, ui.constants

Conventions: Paramètres validés selon contraintes

Read-if: Configuration de l'interface utilisateur

Skip-if: Logique backend pure
"""

from __future__ import annotations

import logging
import json
import os
import random
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

from agents.llm_router import (
    LLMTopologyConfig,
    build_phase1_topology,
    build_single_host_topology,
)
from ui.constants import (
    build_strategy_options,
    get_strategy_description,
    get_strategy_ui_indicators,
)
from ui.context import (
    KNOWN_MODELS,
    LLM_AVAILABLE,
    LLM_IMPORT_ERROR,
    RECOMMENDED_FOR_STRATEGY,
    LLMConfig,
    LLMProvider,
    ModelCategory,
    compute_search_space_stats,
    discover_available_data,
    ensure_ollama_running,
    get_available_models_for_ui,
    get_global_model_config,
    get_model_info,
    get_storage,
    get_strategy,
    get_strategy_info,
    is_ollama_available,
    list_available_models,
    list_strategies,
    list_strategy_versions,
    load_strategy_version,
    resolve_latest_version,
    set_global_model_config,
)
from ui.helpers import (
    _data_cache_key,
    _find_saved_run_meta,
    _parse_run_timestamp,
    apply_versioned_preset,
    build_param_values,
    compute_global_granularity_percent,
    create_param_range_selector,
    granularity_transform,
    load_selected_data,
    render_multi_strategy_params,
    render_saved_runs_panel,
    validate_param,
)
from ui.state import SidebarState
from ui.components.strategy_catalog_panel import render_strategy_catalog_panel
from data.loader import is_valid_timeframe
from utils.observability import is_debug_enabled, set_log_level
from utils.parameters import normalize_param_ranges
from performance.parallel import get_recommended_worker_count

try:
    from agents.strategy_builder import (
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

logger = logging.getLogger(__name__)

POTENTIAL_TOKENS = [
    "BTCUSDC",   # Bitcoin - Référence marché
    "ETHUSDC",   # Ethereum - Leader DeFi
    "BNBUSDC",   # Binance Coin - Plateforme CEX
    "SOLUSDC",   # Solana - Haute vitesse
    "XRPUSDC",   # Ripple - Paiements cross-border
    "AVAXUSDC",  # Avalanche - DeFi concurrente
    "LINKUSDC",  # Chainlink - Oracle leader
    "ADAUSDC",   # Cardano - Approche académique
    "DOTUSDC",   # Polkadot - Interopérabilité
    "ATOMUSDC",  # Cosmos - Hub inter-chaînes
    "MATICUSDC",  # Polygon - Layer 2 Ethereum
    "NEARUSDC",  # NEAR Protocol - Sharding
    "FILUSDC",   # Filecoin - Stockage décentralisé
    "APTUSDC",   # Aptos - Move VM
    "ARBUSDC",   # Arbitrum - L2 Optimistic
    "OPUSDC",    # Optimism - L2 Optimistic
    "INJUSDC",   # Injective - DeFi derivatives
    "SUIUSDC",   # Sui - Move VM haute perf
    "LTCUSDC",   # Litecoin - Digital silver
    "TRXUSDC",   # TRON - Stablecoins hub
]

SIDEBAR_STYLE_CSS = """
<style>
[data-testid="stSidebar"] {
    color-scheme: dark;
    --bc-text: #e6edf6;
    --bc-muted: #9eb0c6;
    --bc-border: #33465f;
    --bc-surface: #0f1726;
    --bc-soft: #172437;
}
[data-testid="stSidebar"] > div:first-child {
    background: linear-gradient(180deg, #0a1221 0%, #0d1b31 45%, #13233f 100%);
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] li,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] span,
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] label {
    color: var(--bc-text) !important;
}
[data-testid="stSidebar"] [data-testid="stAlertContainer"] p {
    color: #e8f1ff !important;
}
[data-testid="stSidebar"] .bc-sidebar-title {
    font-size: 1.15rem;
    font-weight: 700;
    letter-spacing: 0.01em;
    margin-bottom: 0.2rem;
    color: var(--bc-text);
}
[data-testid="stSidebar"] .bc-sidebar-section {
    margin-top: 0.7rem;
    margin-bottom: 0.15rem;
    font-size: 0.92rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: #b8cae4;
}
[data-testid="stSidebar"] .bc-sidebar-card {
    border: 1px solid #395373;
    border-radius: 12px;
    padding: 0.6rem 0.7rem;
    background: rgba(16, 31, 51, 0.86);
    color: var(--bc-text);
}
[data-testid="stSidebar"] .bc-sidebar-card strong {
    color: #f0f7ff;
}
[data-testid="stSidebar"] .stButton > button {
    border-radius: 10px;
    border: 1px solid var(--bc-border);
    font-weight: 600;
    color: #eff6ff;
    background: #1a2a45;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 55%, #3b82f6 100%);
    border: 1px solid #3b82f6;
    color: #ffffff !important;
    box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.25), 0 10px 24px rgba(30, 64, 175, 0.35);
}
[data-testid="stSidebar"] .stButton > button[kind="secondary"] {
    background: #1a2a45;
    border: 1px solid #314766;
    color: #dce9fb !important;
}
[data-testid="stSidebar"] .stSelectbox > div > div,
[data-testid="stSidebar"] .stTextInput > div > div > input,
[data-testid="stSidebar"] .stNumberInput > div > div > input {
    border-radius: 8px;
    color: var(--bc-text) !important;
}
[data-testid="stSidebar"] div[data-baseweb="select"] > div,
[data-testid="stSidebar"] div[data-baseweb="input"] > div,
[data-testid="stSidebar"] div[data-baseweb="textarea"] > div {
    background: var(--bc-surface);
    border-color: var(--bc-border);
}
[data-testid="stSidebar"] div[data-baseweb="tag"] {
    background: #17346d !important;
    color: #e9f3ff !important;
    border: 1px solid #3b82f6 !important;
}
[data-testid="stSidebar"] div[data-baseweb="tag"] span {
    color: #e9f3ff !important;
}
[data-testid="stSidebar"] [data-testid="stMultiSelect"] svg,
[data-testid="stSidebar"] [data-testid="stSelectbox"] svg {
    color: #b3c7e5 !important;
}
[data-testid="stSidebar"] .streamlit-expanderHeader {
    font-weight: 600;
    color: var(--bc-text) !important;
}
[data-testid="stSidebar"] .stExpander {
    border: 1px solid #2e4461;
    border-radius: 12px;
    background: rgba(13, 24, 40, 0.9);
}
[data-testid="stSidebar"] [data-testid="stSlider"] p {
    color: var(--bc-muted) !important;
}
[data-testid="stSidebar"] [data-testid="stCheckbox"] label p,
[data-testid="stSidebar"] [data-testid="stToggle"] label p {
    color: var(--bc-text) !important;
}
[data-testid="stSidebar"] hr {
    border-color: #2a3f5b;
}
</style>
"""


def _inject_sidebar_styles() -> None:
    st.markdown(SIDEBAR_STYLE_CSS, unsafe_allow_html=True)


def _sidebar_section(title: str) -> None:
    st.sidebar.markdown(f'<div class="bc-sidebar-section">{title}</div>', unsafe_allow_html=True)


def _stable_shuffled_options(session_key: str, options: List[str]) -> List[str]:
    """Mélange les options une fois par session, puis conserve l'ordre."""
    cleaned = [str(opt).strip() for opt in options if str(opt).strip()]
    if len(cleaned) <= 1:
        return cleaned

    cached = st.session_state.get(session_key)
    if isinstance(cached, list):
        ordered = [str(opt) for opt in cached if str(opt) in cleaned]
        missing = [opt for opt in cleaned if opt not in ordered]
        if missing:
            random.shuffle(missing)
            ordered.extend(missing)
        if ordered:
            st.session_state[session_key] = ordered
            return ordered

    shuffled = cleaned.copy()
    random.shuffle(shuffled)
    st.session_state[session_key] = shuffled
    return shuffled


def _render_sidebar_summary_card(
    optimization_mode: str,
    strategy_names: List[str],
    symbols: List[str],
    timeframes: List[str],
    use_date_filter: bool,
) -> None:
    st.sidebar.markdown(
        (
            "<div class='bc-sidebar-card'>"
            "<strong>Résumé configuration</strong><br/>"
            f"<span>Mode: <strong>{optimization_mode}</strong></span><br/>"
            f"<span>Stratégies: <strong>{len(strategy_names)}</strong> • "
            f"Tokens: <strong>{len(symbols)}</strong> • "
            f"TF: <strong>{len(timeframes)}</strong></span><br/>"
            f"<span>Filtre dates: <strong>{'Oui' if use_date_filter else 'Non'}</strong></span>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _normalize_signature_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize_signature_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_signature_value(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_normalize_signature_value(v) for v in value)
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _get_padded_date_range(
    start_ts: Optional[pd.Timestamp],
    end_ts: Optional[pd.Timestamp],
    pad_days: int = 1,
) -> Tuple[Optional[object], Optional[object]]:
    if start_ts is None or end_ts is None:
        return None, None
    start_date = start_ts.date()
    end_date = end_ts.date()
    if pad_days <= 0:
        return start_date, end_date
    padded_start = (start_ts + pd.Timedelta(days=pad_days)).date()
    padded_end = (end_ts - pd.Timedelta(days=pad_days)).date()
    if padded_start < padded_end:
        return padded_start, padded_end
    return start_date, end_date


def _get_timeframe_fallback_period(
    timeframe_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Construit une période de repli pour l'affichage par timeframe.

    Utilisé lorsque la période "optimale commune" est introuvable (intersection vide
    entre tokens), mais que des données existent quand même pour ce timeframe.
    """
    availability_result = timeframe_data.get("availability")
    if availability_result is None:
        return None

    availability_map = getattr(availability_result, "availability", {}) or {}
    if not availability_map:
        return None

    valid_ranges: List[Tuple[str, pd.Timestamp, pd.Timestamp, int]] = []
    for key, date_range in availability_map.items():
        if not date_range or len(date_range) != 2:
            continue
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        symbol, _ = key
        start_ts, end_ts = date_range
        if start_ts is None or end_ts is None or start_ts >= end_ts:
            continue
        duration_days = (end_ts - start_ts).days
        valid_ranges.append((str(symbol), start_ts, end_ts, duration_days))

    if not valid_ranges:
        return None

    best_symbol, best_start, best_end, best_duration = max(
        valid_ranges,
        key=lambda item: item[3],
    )
    earliest_start = min(item[1] for item in valid_ranges)
    latest_end = max(item[2] for item in valid_ranges)

    tokens_with_data = len(valid_ranges)
    tokens_total = len(getattr(availability_result, "rows", [])) or tokens_with_data
    coverage_ratio = tokens_with_data / max(tokens_total, 1)
    score = max(1, best_duration) * coverage_ratio

    return {
        "best_symbol": best_symbol,
        "best_start": best_start,
        "best_end": best_end,
        "best_duration_days": best_duration,
        "earliest_start": earliest_start,
        "latest_end": latest_end,
        "tokens_with_data": tokens_with_data,
        "tokens_total": tokens_total,
        "score": score,
    }


def _extract_llm_signature(llm_config: Optional[Any]) -> Optional[Dict[str, Any]]:
    if llm_config is None:
        return None
    provider = getattr(llm_config.provider, "value", str(llm_config.provider))
    return {
        "provider": provider,
        "model": getattr(llm_config, "model", None),
        "ollama_host": getattr(llm_config, "ollama_host", None),
        "openai_base_url": getattr(llm_config, "openai_base_url", None),
        "openai_key_set": bool(getattr(llm_config, "openai_api_key", None)),
        "temperature": getattr(llm_config, "temperature", None),
        "max_tokens": getattr(llm_config, "max_tokens", None),
        "top_p": getattr(llm_config, "top_p", None),
        "timeout_seconds": getattr(llm_config, "timeout_seconds", None),
        "max_retries": getattr(llm_config, "max_retries", None),
        "retry_delay_seconds": getattr(llm_config, "retry_delay_seconds", None),
    }


def _extract_role_model_signature(role_model_config: Any) -> Optional[Dict[str, Any]]:
    if role_model_config is None:
        return None

    def _role_payload(role: Any) -> Dict[str, Any]:
        return {
            "models": list(getattr(role, "models", []) or []),
            "allow_heavy_after_iteration": getattr(role, "allow_heavy_after_iteration", None),
        }

    return {
        "analyst": _role_payload(getattr(role_model_config, "analyst", None)),
        "strategist": _role_payload(getattr(role_model_config, "strategist", None)),
        "critic": _role_payload(getattr(role_model_config, "critic", None)),
        "validator": _role_payload(getattr(role_model_config, "validator", None)),
    }


def _extract_llm_topology_signature(llm_topology_config: Any) -> Optional[Dict[str, Any]]:
    if llm_topology_config is None:
        return None
    if hasattr(llm_topology_config, "to_dict"):
        try:
            return llm_topology_config.to_dict()
        except Exception:
            return None
    if isinstance(llm_topology_config, dict):
        return llm_topology_config
    return None


def _build_config_signature(state: SidebarState) -> str:
    """Construit une signature stable de la configuration appliquée."""
    payload = {
        "debug_enabled": state.debug_enabled,
        "symbol": state.symbol,
        "timeframe": state.timeframe,
        "use_date_filter": state.use_date_filter,
        "start_date": state.start_date,
        "end_date": state.end_date,
        "symbols": sorted(state.symbols or []),
        "timeframes": sorted(state.timeframes or []),
        "strategy_key": state.strategy_key,
        "strategy_keys": sorted(state.strategy_keys or []),
        "params": state.params,
        "param_ranges": state.param_ranges,
        "all_params": state.all_params,
        "all_param_ranges": state.all_param_ranges,
        "active_indicators": sorted(state.active_indicators or []),
        "optimization_mode": state.optimization_mode,
        "max_combos": state.max_combos,
        "n_workers": state.n_workers,
        "use_optuna": state.use_optuna,
        "optuna_n_trials": state.optuna_n_trials,
        "optuna_sampler": state.optuna_sampler,
        "optuna_pruning": state.optuna_pruning,
        "optuna_metric": state.optuna_metric,
        "optuna_early_stop": state.optuna_early_stop,
        "llm": _extract_llm_signature(state.llm_config),
        "llm_model": state.llm_model,
        "llm_use_multi_agent": state.llm_use_multi_agent,
        "role_model_config": _extract_role_model_signature(state.role_model_config),
        "llm_routing_mode": state.llm_routing_mode,
        "llm_topology_config": _extract_llm_topology_signature(
            state.llm_topology_config
        ),
        "llm_max_iterations": state.llm_max_iterations,
        "llm_use_walk_forward": state.llm_use_walk_forward,
        "llm_unload_during_backtest": state.llm_unload_during_backtest,
        "llm_compare_enabled": state.llm_compare_enabled,
        "llm_compare_auto_run": state.llm_compare_auto_run,
        "llm_compare_strategies": sorted(state.llm_compare_strategies or []),
        "llm_compare_tokens": sorted(state.llm_compare_tokens or []),
        "llm_compare_timeframes": sorted(state.llm_compare_timeframes or []),
        "llm_compare_metric": state.llm_compare_metric,
        "llm_compare_aggregate": state.llm_compare_aggregate,
        "llm_compare_max_runs": state.llm_compare_max_runs,
        "llm_compare_use_preset": state.llm_compare_use_preset,
        "llm_compare_generate_report": state.llm_compare_generate_report,
        "initial_capital": state.initial_capital,
        "leverage": state.leverage,
        "leverage_enabled": state.leverage_enabled,
        "disabled_params": sorted(state.disabled_params or []),
        # Strategy Builder
        "builder_objective": state.builder_objective,
        "builder_model": state.builder_model,
        "builder_max_iterations": state.builder_max_iterations,
        "builder_target_sharpe": state.builder_target_sharpe,
        "builder_capital": state.builder_capital,
        "builder_ollama_host": state.builder_ollama_host,
        "builder_preload_model": state.builder_preload_model,
        "builder_keep_alive_minutes": state.builder_keep_alive_minutes,
        "builder_unload_after_run": state.builder_unload_after_run,
        "builder_auto_start_ollama": state.builder_auto_start_ollama,
        "builder_auto_market_pick": state.builder_auto_market_pick,
        "builder_autonomous": state.builder_autonomous,
        "builder_auto_pause": state.builder_auto_pause,
        "builder_auto_use_llm": state.builder_auto_use_llm,
        "builder_multi_llm_enabled": state.builder_multi_llm_enabled,
        "builder_multi_llm_profile": state.builder_multi_llm_profile,
        "builder_use_parametric_catalog": state.builder_use_parametric_catalog,
    }

    normalized = _normalize_signature_value(payload)
    return json.dumps(normalized, sort_keys=True, default=str)


def _env_int(key: str, default: Optional[int]) -> Optional[int]:
    try:
        if default is None:
            raw = os.getenv(key)
            return int(raw) if raw is not None else None
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _resolve_default_cpu_workers(max_cap: int = 32) -> int:
    """Résout un nombre de workers CPU sans dépendre des réglages GPU."""

    explicit_max = _env_int("BACKTEST_MAX_WORKERS", None)
    explicit_cpu = _env_int("BACKTEST_WORKERS_CPU_OPTIMIZED", None)

    for candidate in (explicit_max, explicit_cpu):
        if candidate is not None and candidate > 0:
            return max(1, min(int(candidate), int(max_cap)))

    try:
        recommended = int(get_recommended_worker_count(max_cap=max_cap))
    except Exception:
        recommended = int(os.cpu_count() or 1)
    return max(1, min(recommended, int(max_cap)))


def _apply_catalog_replay_request_to_state(
    session_state: Dict[str, Any],
    replay_request: Dict[str, Any],
    strategy_options: Dict[str, str],
) -> tuple[bool, str, bool]:
    """Applique un replay catalogue sur un état sidebar-like mutable."""

    strategy_key = str(replay_request.get("strategy_key", "") or "").strip()
    symbol = str(replay_request.get("symbol", "") or "").strip().upper()
    timeframe = str(replay_request.get("timeframe", "") or "").strip()
    if not strategy_key or not symbol or not timeframe:
        return False, "Replay catalogue incomplet.", False

    strategy_label = str(strategy_options.get(strategy_key) or strategy_key)
    params = dict(replay_request.get("params", {}) or {})

    session_state["optimization_mode"] = "Backtest Simple"
    session_state["strategy_selection_mode"] = "📋 Classique"
    session_state["symbols_select"] = [symbol]
    session_state["timeframes_select"] = [timeframe]
    session_state["strategies_select"] = [strategy_label]
    session_state["selected_symbol"] = symbol
    session_state["selected_timeframe"] = timeframe
    session_state["selected_strategy"] = strategy_label

    for param_name, param_value in params.items():
        if param_name == "leverage":
            session_state["trading_leverage"] = param_value
            session_state["leverage_enabled"] = bool(float(param_value) != 1.0)
            continue
        session_state[f"{strategy_key}_{param_name}"] = param_value

    if "initial_capital" in replay_request:
        session_state["initial_capital_input"] = replay_request["initial_capital"]

    start_date = replay_request.get("start_date")
    end_date = replay_request.get("end_date")
    if start_date or end_date:
        session_state["use_date_filter"] = True
        if start_date:
            session_state["start_date_input"] = pd.Timestamp(start_date).date()
        if end_date:
            session_state["end_date_input"] = pd.Timestamp(end_date).date()

    auto_run = bool(replay_request.get("auto_run", False))
    if auto_run:
        session_state["run_backtest_requested"] = True

    source_run_id = str(replay_request.get("source_run_id", "") or "").strip()
    msg = (
        f"Replay catalogue prêt depuis {source_run_id}."
        if source_run_id
        else "Replay catalogue prêt."
    )
    return True, msg, True


def _env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


def _apply_config_guard(draft_state: SidebarState) -> SidebarState:
    draft_signature = _build_config_signature(draft_state)
    applied_signature = st.session_state.get("applied_config_signature")
    applied_state = st.session_state.get("applied_sidebar_state")

    if applied_signature is None or applied_state is None:
        st.session_state["applied_config_signature"] = draft_signature
        st.session_state["applied_sidebar_state"] = draft_state
        applied_state = draft_state
        pending = False
    else:
        mode_switched = (
            getattr(applied_state, "optimization_mode", None)
            != draft_state.optimization_mode
        )
        if mode_switched:
            st.session_state["applied_config_signature"] = draft_signature
            st.session_state["applied_sidebar_state"] = draft_state
            applied_state = draft_state
            pending = False
        else:
            pending = draft_signature != applied_signature

    st.session_state["config_pending_changes"] = pending
    st.session_state["draft_config_signature"] = draft_signature

    return applied_state


def get_final_market_selection(
    *,
    ui_symbols: List[str],
    ui_timeframes: List[str],
    available_tokens: List[str],
    available_timeframes: List[str],
    auto_market_pick: bool,
    llm_override: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, str, str]:
    """
    SOURCE DE VÉRITÉ UNIQUE pour la sélection finale du marché (token × timeframe).

    Centralise la logique de décision entre sélection UI, override LLM, et fallbacks.

    Args:
        ui_symbols: Symboles sélectionnés manuellement dans la sidebar
        ui_timeframes: Timeframes sélectionnés manuellement dans la sidebar
        available_tokens: Univers des tokens disponibles (données présentes)
        available_timeframes: Univers des timeframes disponibles
        auto_market_pick: True si le LLM doit override la sélection UI
        llm_override: Résultat de recommend_market_context() si activé

    Returns:
        Tuple (final_symbol, final_timeframe, source, reason)

    source:
        - "llm_override" : Sélection LLM a écrasé la sélection UI
        - "ui_manual" : Sélection manuelle respectée
        - "ui_random" : Sélection aléatoire (bouton 🎲)
        - "fallback" : Univers vide ou sélection UI manquante

    reason:
        Description textuelle de la décision (pour logs + UI feedback)
    """
    # Import config centralisée
    from config.market_selection import get_default_symbol, get_default_timeframe

    # 1. Override LLM prioritaire (si auto_market_pick activé)
    if llm_override and auto_market_pick:
        llm_symbol = str(llm_override.get("symbol", "")).strip().upper()
        llm_timeframe = str(llm_override.get("timeframe", "")).strip()
        llm_reason = str(llm_override.get("reason", "Recommandation LLM")).strip()
        llm_source = str(llm_override.get("source", "llm_recommendation")).strip()

        if llm_symbol and llm_timeframe:
            # Vérifier si c'est un override de la sélection UI
            ui_symbol_first = ui_symbols[0] if ui_symbols else ""
            ui_tf_first = ui_timeframes[0] if ui_timeframes else ""

            if (
                ui_symbol_first
                and ui_tf_first
                and (llm_symbol != ui_symbol_first or llm_timeframe != ui_tf_first)
            ):
                reason = (
                    f"Override UI ({ui_symbol_first} {ui_tf_first} → {llm_symbol} {llm_timeframe}). "
                    f"Raison: {llm_reason}"
                )
                return (llm_symbol, llm_timeframe, "llm_override", reason)
            else:
                # LLM a choisi le même couple que l'UI (ou UI vide)
                return (llm_symbol, llm_timeframe, llm_source, llm_reason)

    # 2. Sélection UI manuelle (prioritaire si auto_market_pick=OFF)
    if ui_symbols and ui_timeframes:
        symbol = ui_symbols[0]
        timeframe = ui_timeframes[0]

        # Détection sélection aléatoire (marqueur session_state)
        if st.session_state.get("_random_market_applied", False):
            return (symbol, timeframe, "ui_random", "Sélection aléatoire (bouton 🎲)")
        else:
            return (symbol, timeframe, "ui_manual", "Sélection manuelle utilisateur")

    # 3. Fallback : Defaults depuis config ou univers disponible
    default_symbol = get_default_symbol()
    default_timeframe = get_default_timeframe()

    # Valider que les defaults sont dans l'univers disponible
    if default_symbol not in available_tokens and available_tokens:
        default_symbol = available_tokens[0]

    if default_timeframe not in available_timeframes and available_timeframes:
        default_timeframe = available_timeframes[0]

    # Fallback ultime hardcodé si univers complètement vide
    if not default_symbol:
        default_symbol = "BTCUSDC"
    if not default_timeframe:
        default_timeframe = "1h"

    reason = "Fallback : Univers vide ou sélection UI manquante"
    return (default_symbol, default_timeframe, "fallback", reason)


def render_sidebar() -> SidebarState:
    _inject_sidebar_styles()
    st.sidebar.markdown('<div class="bc-sidebar-title">⚙️ Configuration</div>', unsafe_allow_html=True)
    st.sidebar.caption("Réglages centralisés du backtest, sweep et builder.")
    st.sidebar.caption("Parcours: Données → Stratégies → Mode → Exécution → Paramètres → Presets")

    with st.sidebar.expander("🔧 Debug", expanded=False):
        debug_enabled = st.checkbox(
            "Mode DEBUG",
            value=is_debug_enabled(),
            key="debug_toggle",
        )
        if debug_enabled:
            set_log_level("DEBUG")
            st.caption("🟢 Logs détaillés activés")
        else:
            set_log_level("INFO")

    _sidebar_section("📊 Données")

    # Filtre UI des TF:
    # - exclure 1m (non utilisé dans ce setup)
    # - exclure les TF mensuels multi-mois (3M, 6M, ...)
    def _is_ui_supported_timeframe(tf: str) -> bool:
        match_month = re.fullmatch(r"(\d+)M", str(tf or "").strip())
        if match_month:
            return int(match_month.group(1)) <= 1
        return True

    data_status = st.sidebar.empty()
    try:
        available_tokens, available_timeframes = discover_available_data()
        if not available_tokens:
            available_tokens = ["BTCUSDC", "ETHUSDC"]
            data_status.warning("Aucune donnée trouvée, utilisation des défauts")
        else:
            data_status.success(f"✅ {len(available_tokens)} symboles disponibles")

        if not available_timeframes:
            available_timeframes = ["1h", "4h", "1d"]

        available_timeframes = [tf for tf in available_timeframes if _is_ui_supported_timeframe(tf)]

        # Nettoyer les valeurs de session invalides (bug fix 23/01/2026)
        if "symbol_select" in st.session_state:
            if st.session_state["symbol_select"] not in available_tokens:
                del st.session_state["symbol_select"]

        if "timeframe_select" in st.session_state:
            if not is_valid_timeframe(st.session_state["timeframe_select"]) or \
               st.session_state["timeframe_select"] not in available_timeframes:
                del st.session_state["timeframe_select"]

    except Exception as exc:
        available_tokens = ["BTCUSDC", "ETHUSDC"]
        available_timeframes = ["1h", "4h", "1d"]
        data_status.error(f"Erreur scan: {exc}")

    pending_meta = None
    pending_run_id = st.session_state.get("pending_run_load_id")
    if pending_run_id:
        try:
            storage = get_storage()
            pending_meta = _find_saved_run_meta(storage, pending_run_id)
        except Exception as exc:
            st.session_state["saved_runs_status"] = f"Pending load failed: {exc}"
            pending_meta = None

    if pending_meta is not None:
        # Valider que symbol et timeframe sont valides avant de les ajouter
        if pending_meta.symbol and pending_meta.symbol not in available_tokens:
            # Vérifier que le symbol est valide (lettres et chiffres seulement)
            if pending_meta.symbol.replace("_", "").replace("-", "").isalnum():
                available_tokens = [pending_meta.symbol] + available_tokens

        if pending_meta.timeframe and pending_meta.timeframe not in available_timeframes:
            # Valider format timeframe (ex: 1m, 5m, 1h, 4h, 1d)
            if (
                is_valid_timeframe(pending_meta.timeframe)
                and _is_ui_supported_timeframe(pending_meta.timeframe)
            ):
                available_timeframes = [pending_meta.timeframe] + available_timeframes

        if pending_meta.symbol:
            st.session_state["symbol_select"] = pending_meta.symbol
        if pending_meta.timeframe and _is_ui_supported_timeframe(pending_meta.timeframe):
            st.session_state["timeframe_select"] = pending_meta.timeframe
        # Activer le filtre de dates seulement si des dates spécifiques sont définies
        start_ts = _parse_run_timestamp(pending_meta.period_start)
        end_ts = _parse_run_timestamp(pending_meta.period_end)
        if start_ts is not None and end_ts is not None:
            st.session_state["use_date_filter"] = True
            # Initialiser seulement si pas déjà défini (évite conflit avec widget)
            if "start_date" not in st.session_state:
                st.session_state["start_date"] = start_ts.date()
            if "end_date" not in st.session_state:
                st.session_state["end_date"] = end_ts.date()

    # Initialisation propre au démarrage de session:
    # évite de conserver des sélections marché "collées" d'une ancienne session/rerun.
    if "_market_selection_initialized_v1" not in st.session_state:
        if pending_meta is None:
            st.session_state["symbols_select"] = []
            st.session_state["timeframes_select"] = []
        st.session_state["_market_selection_initialized_v1"] = True

    # === NETTOYAGE SESSION STATE ===
    # Nettoyer les clés de session obsolètes ou invalides
    # IMPORTANT: Ne supprimer QUE les tokens/timeframes vraiment invalides
    # Ne PAS réinitialiser si certains sont encore valides
    session_keys_to_clean = [
        "symbols_select", "timeframes_select", "symbol_select", "timeframe_select"
    ]
    for key in session_keys_to_clean:
        if key in st.session_state:
            if "symbol" in key:
                if isinstance(st.session_state[key], list):
                    current = st.session_state[key]
                    # Ne rien faire si la liste est déjà vide (choix utilisateur)
                    if current:
                        valid_symbols = [s for s in current if s in available_tokens]
                        if valid_symbols != current:
                            st.session_state[key] = valid_symbols
                elif st.session_state[key] not in available_tokens:
                    del st.session_state[key]
            elif "timeframe" in key:
                if isinstance(st.session_state[key], list):
                    current = st.session_state[key]
                    # Ne rien faire si la liste est déjà vide (choix utilisateur)
                    if current:
                        valid_timeframes = [tf for tf in current if tf in available_timeframes]
                        if valid_timeframes != current:
                            st.session_state[key] = valid_timeframes
                elif st.session_state[key] not in available_timeframes:
                    del st.session_state[key]

    available_strategies = list_strategies()
    strategy_options = build_strategy_options(available_strategies)

    keep_current_strategy = st.sidebar.checkbox(
        "Conserver stratégie (🎲)",
        value=st.session_state.get("keep_strategy_on_random_selection", True),
        key="keep_strategy_on_random_selection",
        help="Si activé, le bouton 🎲 randomise seulement token + timeframe quand une stratégie est déjà sélectionnée.",
    )

    # Appliquer une sélection aléatoire (1 token + 1 TF + 1 stratégie)
    if st.session_state.get("_apply_random_market_selection", False):
        random_symbol = random.choice(available_tokens) if available_tokens else ""
        random_timeframe = random.choice(available_timeframes) if available_timeframes else ""
        strategy_labels = list(strategy_options.keys())
        current_strategy_labels = st.session_state.get("strategies_select", [])

        random_strategy = ""
        strategy_mode = "aléatoire"
        if keep_current_strategy and current_strategy_labels:
            random_strategy = current_strategy_labels[0]
            strategy_mode = "conservée"
        elif strategy_labels:
            random_strategy = random.choice(strategy_labels)

        st.session_state["symbols_select"] = [random_symbol] if random_symbol else []
        st.session_state["timeframes_select"] = [random_timeframe] if random_timeframe else []
        if random_strategy:
            st.session_state["strategies_select"] = [random_strategy]

        # Marqueur pour détection dans get_final_market_selection
        st.session_state["_random_market_applied"] = True

        st.session_state["_random_market_selection_summary"] = (
            f"🎲 Aléatoire: {random_symbol or '-'} | {random_timeframe or '-'} | "
            f"stratégie {strategy_mode}: {random_strategy or '-'}"
        )

        # Log structuré permanent (caption UI disparaît au rerun)
        logger.info(
            "Market selection: source=ui_random, symbol=%s, timeframe=%s, strategy=%s (%s), reason=Bouton 🎲",
            random_symbol or "NONE",
            random_timeframe or "NONE",
            random_strategy or "NONE",
            strategy_mode,
        )

        del st.session_state["_apply_random_market_selection"]

    # === MULTI-SÉLECTION TOKENS (multiselect) ===

    # Aucun token sélectionné par défaut — l'utilisateur choisit
    default_symbols: List[str] = []

    # Appliquer la sélection des tokens potentiels avant la création du widget
    if st.session_state.get("_apply_potential_tokens", False):
        valid_potential = [t for t in POTENTIAL_TOKENS if t in available_tokens]
        current_symbols = st.session_state.get("symbols_select", default_symbols)
        merged_symbols = list(current_symbols)
        added_tokens = []
        for token in valid_potential:
            if token not in merged_symbols:
                merged_symbols.append(token)
                added_tokens.append(token)

        st.session_state["symbols_select"] = merged_symbols or default_symbols

        # Log structuré : ajout de tokens potentiels
        logger.info(
            "Market selection: source=ui_potential_tokens, added_count=%d, tokens=%s, reason=Bouton 🎯 (tokens à potentiel)",
            len(added_tokens),
            ", ".join(added_tokens) if added_tokens else "NONE_NEW",
        )

        del st.session_state["_apply_potential_tokens"]

    # Détection mode Builder
    _is_builder = st.session_state.get("optimization_mode") == "🏗️ Strategy Builder"
    _builder_autonomous = st.session_state.get("builder_autonomous", False)
    _builder_auto_market = st.session_state.get("builder_auto_market_pick", False)
    # Les sélecteurs marché restent visibles/clickables dans tous les modes.
    symbol_options_ui = _stable_shuffled_options(
        "_symbols_options_order_v1",
        available_tokens,
    )
    col1, col2, col3 = st.sidebar.columns([3, 1, 1])
    with col1:
        # Initialiser si non existant (l'initialisation principale est ligne 724)
        if "symbols_select" not in st.session_state:
            st.session_state["symbols_select"] = default_symbols

        symbols = st.multiselect(
            label="Symbole(s)",
            options=symbol_options_ui,
            key="symbols_select",
            help="Sélectionnez un ou plusieurs tokens à analyser",
        )
    with col2:
        st.write("")  # Espacement pour aligner avec le multiselect
        if st.button("🎯", key="select_potential_tokens", help="Sélectionner tokens à potentiel"):
            st.session_state["_apply_potential_tokens"] = True
            st.rerun()
    with col3:
        st.write("")  # Espacement pour aligner avec le multiselect
        if st.button(
            "🎲",
            key="select_random_market_selection",
            help="Sélection aléatoire de token/TF (et stratégie selon l'option 'Conserver stratégie')."
        ):
            st.session_state["_apply_random_market_selection"] = True
            st.rerun()

    random_selection_summary = st.session_state.pop("_random_market_selection_summary", "")
    if random_selection_summary:
        st.sidebar.caption(random_selection_summary)

    if not symbols and not _is_builder:
        st.sidebar.info("Sélectionnez au moins un symbole pour commencer.")
    symbol = symbols[0] if symbols else ""  # Compatibilité rétro

    # === MULTI-SÉLECTION TIMEFRAMES (multiselect) ===
    # Aucun timeframe sélectionné par défaut — l'utilisateur choisit
    default_timeframes: List[str] = []

    timeframe_options_ui = _stable_shuffled_options(
        "_timeframes_options_order_v1",
        available_timeframes,
    )
    # Initialiser si non existant (l'initialisation principale est ligne 725)
    if "timeframes_select" not in st.session_state:
        st.session_state["timeframes_select"] = default_timeframes

    timeframes = st.sidebar.multiselect(
        "Timeframe(s)",
        timeframe_options_ui,
        key="timeframes_select",
        help="Sélectionnez un ou plusieurs timeframes",
    )

    if not timeframes and not _is_builder:
        st.sidebar.info("Sélectionnez au moins un timeframe pour commencer.")
    timeframe = timeframes[0] if timeframes else ""  # Compatibilité rétro

    selected_strategy_preview = (st.session_state.get("strategies_select") or [""])[0]
    if _is_builder:
        llm_note = " (LLM peut override en auto-marché)" if (_builder_autonomous or _builder_auto_market) else ""
        st.sidebar.caption(f"🎯 Sélection active : {symbol or '—'} | {timeframe or '—'}{llm_note}")
    else:
        st.sidebar.caption(
            f"🎯 Sélection active : {symbol or '—'} | {timeframe or '—'} | {selected_strategy_preview or '—'}"
        )

    # Info multi-sweep si plusieurs sélections (tokens/timeframes uniquement à ce stade)
    if len(symbols) > 1 or len(timeframes) > 1:
        total_combos = len(symbols) * len(timeframes)
        st.sidebar.info(f"🔄 Mode multi-sweep: {len(symbols)} token(s) × {len(timeframes)} TF(s) = {total_combos} combinaison(s)")

    # Analyse des données disponibles pour validation (toujours nécessaire)
    from data.config import scan_data_availability
    availability_result = scan_data_availability(symbols, timeframes)

    # Avertir si certaines combinaisons token/TF n'ont pas de données
    if availability_result.missing_data:
        n_missing = len(availability_result.missing_data)
        n_total = len(symbols) * len(timeframes)
        # Afficher les 5 premières combos manquantes
        examples = availability_result.missing_data[:5]
        more = f" ... +{n_missing - 5}" if n_missing > 5 else ""
        st.sidebar.warning(
            f"⚠️ **{n_missing}/{n_total}** combo(s) sans données: "
            f"{', '.join(examples)}{more}. "
            f"Ces combinaisons seront ignorées automatiquement."
        )

    use_date_filter = st.sidebar.checkbox(
        "Filtrer par dates",
        value=False,
        help="Désactivé = utilise toutes les données disponibles (recommandé)",
        key="use_date_filter",
    )
    if use_date_filter:
        if not symbols or not timeframes:
            st.sidebar.warning("Sélectionnez au moins un symbole et un timeframe pour activer le filtre dates.")
            use_date_filter = False

    if use_date_filter:
        # === ANALYSE PAR CATÉGORIE DE TIMEFRAME ===
        from data.config import analyze_by_timeframe

        # Analyse par timeframe (plage commune par TF)
        timeframe_analysis = analyze_by_timeframe(symbols, timeframes)

        # Interface de sélection par timeframe
        with st.sidebar.expander("🎯 **Analyse par Timeframe**", expanded=True):
            if len(timeframes) > 1:
                analysis_mode = st.radio(
                    "Mode d'analyse",
                    ["Période harmonisée", "Périodes indépendantes par timeframe"],
                    help="Harmonisée = même période pour tous. Indépendantes = période optimale par timeframe",
                )
            else:
                analysis_mode = "Période harmonisée"  # Auto si un seul timeframe

            st.caption(
                "Harmonisée = une seule période commune (comparaisons strictes). "
                "Indépendantes = meilleure période par TF (comparaisons plus souples)."
            )

            available_start = None
            available_end = None
            default_start = None
            default_end = None

            if analysis_mode == "Période harmonisée":
                if availability_result.has_common_range:
                    common_start = availability_result.common_start
                    common_end = availability_result.common_end
                    duration = (common_end - common_start).days

                    st.success(f"✅ **Période harmonisée**: {common_start.strftime('%d/%m/%Y')} → {common_end.strftime('%d/%m/%Y')} ({duration}j)")
                    st.caption(
                        f"💡 Plage commune stricte (max début, min fin) sur "
                        f"{len(symbols)} token(s) × {len(timeframes)} TF(s)"
                    )

                    available_start = common_start.date()
                    available_end = common_end.date()
                    default_start, default_end = _get_padded_date_range(common_start, common_end)
                else:
                    st.warning("⚠️ Impossible de trouver une période commune (intersection vide)")
                    default_start = pd.Timestamp("2023-01-01").date()
                    default_end = pd.Timestamp.now().date()
                    available_start = default_start
                    available_end = default_end

            else:
                st.info("📊 **Périodes optimales par timeframe**:")

                best_timeframe = None
                best_score = 0.0
                best_period_ref = None
                fallback_timeframe = None
                fallback_period_ref = None
                fallback_score = 0.0

                for tf, data in timeframe_analysis.items():
                    st.write(f"**{tf}**")

                    if data['optimal_periods']:
                        best_period = data['optimal_periods'][0]
                        start_fr = best_period.start_date.strftime("%d/%m/%Y")
                        end_fr = best_period.end_date.strftime("%d/%m/%Y")
                        duration = (best_period.end_date - best_period.start_date).days

                        st.write(f"- 🎯 {start_fr} → {end_fr} ({duration}j)")
                        st.caption(
                            f"  Score: {best_period.completeness_score:.0f}%, "
                            f"Gap toléré: {data['gap_tolerance']:.0f}%"
                        )

                        for recommendation in data['recommendations']:
                            st.caption(f"  {recommendation}")

                        combined_score = best_period.completeness_score * best_period.avg_data_density
                        if combined_score > best_score:
                            best_score = combined_score
                            best_timeframe = tf
                            best_period_ref = best_period
                    else:
                        fallback_period = _get_timeframe_fallback_period(data)
                        if fallback_period:
                            fallback_start = fallback_period["best_start"].strftime("%d/%m/%Y")
                            fallback_end = fallback_period["best_end"].strftime("%d/%m/%Y")
                            fallback_duration = fallback_period["best_duration_days"]

                            st.write(
                                f"- ℹ️ Référence {fallback_period['best_symbol']}: "
                                f"{fallback_start} → {fallback_end} ({fallback_duration}j)"
                            )

                            if fallback_period["score"] > fallback_score:
                                fallback_score = fallback_period["score"]
                                fallback_timeframe = tf
                                fallback_period_ref = fallback_period
                        else:
                            st.write("- ❌ Aucune donnée disponible")

                if best_timeframe and best_period_ref:
                    available_start = best_period_ref.start_date.date()
                    available_end = best_period_ref.end_date.date()
                    default_start, default_end = _get_padded_date_range(
                        best_period_ref.start_date,
                        best_period_ref.end_date,
                    )
                    st.success(f"🏆 **Défaut basé sur {best_timeframe}** (meilleur score: {best_score:.1f})")
                elif fallback_timeframe and fallback_period_ref:
                    fallback_start_ts = fallback_period_ref["best_start"]
                    fallback_end_ts = fallback_period_ref["best_end"]
                    available_start = fallback_start_ts.date()
                    available_end = fallback_end_ts.date()
                    default_start, default_end = _get_padded_date_range(
                        fallback_start_ts,
                        fallback_end_ts,
                    )
                    st.info(
                        f"ℹ️ Aucun intervalle commun strict. Défaut basé sur "
                        f"{fallback_timeframe} ({fallback_period_ref['best_symbol']})."
                    )
                else:
                    st.warning("⚠️ Aucune période optimale trouvée pour les timeframes sélectionnés")
                    default_start = pd.Timestamp("2023-01-01").date()
                    default_end = pd.Timestamp.now().date()
                    available_start = default_start
                    available_end = default_end

            st.markdown("---")
            st.caption("📅 **Période d'analyse** (format: DD/MM/YYYY)")

            # Auto-aligner les dates sur la plage commune si hors limites.
            if default_start and default_end and available_start and available_end:
                selection_key = (
                    tuple(sorted(symbols)),
                    tuple(sorted(timeframes)),
                    analysis_mode,
                )
                if st.session_state.get("_date_range_selection_key") != selection_key:
                    st.session_state["start_date"] = default_start
                    st.session_state["end_date"] = default_end
                    st.session_state["_date_range_selection_key"] = selection_key

                start_state = st.session_state.get("start_date")
                end_state = st.session_state.get("end_date")
                if start_state and (start_state < available_start or start_state > available_end):
                    st.session_state["start_date"] = default_start
                if end_state and (end_state < available_start or end_state > available_end):
                    st.session_state["end_date"] = default_end

                if st.session_state.get("start_date") and st.session_state.get("end_date"):
                    if st.session_state["start_date"] >= st.session_state["end_date"]:
                        st.session_state["start_date"] = default_start
                        st.session_state["end_date"] = default_end

            col1, col2 = st.sidebar.columns(2)
            with col1:
                start_date = st.date_input(
                    "Date début 📅",
                    key="start_date",
                    format="DD/MM/YYYY",
                    help="Date de début de la période d'analyse"
                )
            with col2:
                end_date = st.date_input(
                    "Date fin 📅",
                    key="end_date",
                    format="DD/MM/YYYY",
                    help="Date de fin de la période d'analyse"
                )

            # Validation que start_date < end_date
            if start_date and end_date and start_date >= end_date:
                st.sidebar.error("⚠️ La date de début doit être antérieure à la date de fin")

            # Affichage de la durée sélectionnée
            if start_date and end_date and start_date < end_date:
                selected_days = (end_date - start_date).days
                st.sidebar.caption(f"📊 Durée sélectionnée: **{selected_days} jours**")

            # Validation de la période par rapport à la plage commune
            if availability_result.has_common_range and start_date and end_date:
                common_start = availability_result.common_start
                common_end = availability_result.common_end
                common_start_date = common_start.date()
                common_end_date = common_end.date()

                if analysis_mode == "Période harmonisée":
                    if end_date < common_start_date:
                        st.sidebar.error(
                            f"⚠️ Période demandée ({start_date.strftime('%d/%m/%Y')} → {end_date.strftime('%d/%m/%Y')}) est AVANT "
                            f"la plage commune ({common_start_date.strftime('%d/%m/%Y')})"
                        )
                    elif start_date > common_end_date:
                        st.sidebar.error(
                            f"⚠️ Période demandée ({start_date.strftime('%d/%m/%Y')} → {end_date.strftime('%d/%m/%Y')}) est APRÈS "
                            f"la plage commune ({common_end_date.strftime('%d/%m/%Y')})"
                        )
                    elif start_date < common_start_date:
                        st.sidebar.warning(
                            f"⚠️ Début demandé ({start_date.strftime('%d/%m/%Y')}) est AVANT la plage commune. "
                            f"Données réelles à partir de **{common_start_date.strftime('%d/%m/%Y')}**"
                        )
                    elif end_date > common_end_date:
                        st.sidebar.warning(
                            f"⚠️ Fin demandée ({end_date.strftime('%d/%m/%Y')}) est APRÈS la plage commune. "
                            f"Données réelles jusqu'à **{common_end_date.strftime('%d/%m/%Y')}**"
                        )
                else:
                    if start_date < common_start_date or end_date > common_end_date:
                        st.sidebar.info(
                            f"ℹ️ Plage commune globale: {common_start_date.strftime('%d/%m/%Y')} → {common_end_date.strftime('%d/%m/%Y')}. "
                            "En mode indépendant, certaines combinaisons peuvent être tronquées."
                        )

            st.markdown("---")
            with st.sidebar.expander("🔍 Analyse détaillée des données", expanded=False):
                if availability_result.rows:
                    df_analysis = pd.DataFrame(availability_result.rows)
                    st.dataframe(
                        df_analysis,
                        width="stretch",
                        column_config={
                            "Token": st.column_config.TextColumn("Token", width="small"),
                            "TF": st.column_config.TextColumn("TF", width="small"),
                            "Début": st.column_config.TextColumn("Début", width="medium"),
                            "Fin": st.column_config.TextColumn("Fin", width="medium"),
                            "Jours": st.column_config.NumberColumn("Jours", width="small"),
                            "Plage commune %": st.column_config.NumberColumn("Plage commune %", format="%.1f%%", width="small"),
                            "Couverture %": st.column_config.NumberColumn("Couverture %", format="%.1f%%", width="small"),
                            "Manquant %": st.column_config.NumberColumn("Manquant %", format="%.1f%%", width="small"),
                            "Jours manquants": st.column_config.NumberColumn("Jours manquants", format="%.1f", width="small"),
                            "Status": st.column_config.TextColumn("Status", width="small"),
                            "Détails": st.column_config.TextColumn("Détails", width="large")
                        }
                    )

                    total_combos = len(df_analysis)
                    complete_combos = len(df_analysis[df_analysis["Status"] == "✅"])
                    incomplete_combos = len(df_analysis[df_analysis["Status"] == "⚠️"])
                    missing_combos = len(df_analysis[df_analysis["Status"] == "❌"])

                    st.markdown("**Résumé qualité des données (gaps)**")
                    st.caption(
                        "✅ = couverture correcte (<10% de gaps) • ⚠️ = gaps significatifs • ❌ = fichier manquant."
                    )
                    st.markdown(
                        f"- ✅ Complètes : {complete_combos}/{total_combos}\n"
                        f"- ⚠️ Incomplètes : {incomplete_combos}/{total_combos}\n"
                        f"- ❌ Manquantes : {missing_combos}/{total_combos}"
                    )

                    if hasattr(availability_result, 'optimal_periods') and availability_result.optimal_periods:
                        st.markdown(
                            "💡 **Conseil :** Les périodes optimales ci-dessus évitent automatiquement les zones avec trop de données manquantes."
                        )
    else:
        start_date = None
        end_date = None

    current_data_key = _data_cache_key(symbol, timeframe, start_date, end_date)
    if st.session_state.get("ohlcv_cache_key") != current_data_key:
        st.session_state["ohlcv_cache_key"] = current_data_key
        st.session_state["ohlcv_df"] = None
        # FIX 04/01/2026: NE PAS effacer les résultats quand les données changent
        # Les résultats d'un backtest/grid peuvent être visualisés indépendamment
        # des données OHLCV actuellement chargées. Effacer les résultats causait
        # la perte de tous les résultats après un grid search lors du prochain rerun.
        # st.session_state["last_run_result"] = None
        # st.session_state["last_winner_params"] = None
        # st.session_state["last_winner_metrics"] = None
        # st.session_state["last_winner_origin"] = None
        # st.session_state["last_winner_meta"] = None

    pending_run_id = st.session_state.get("pending_run_load_id")
    if pending_run_id:
        try:
            storage = get_storage()
            result = storage.load_result(pending_run_id)
            st.session_state["last_run_result"] = result
            st.session_state["last_winner_params"] = result.meta.get("params", {})
            st.session_state["last_winner_metrics"] = result.metrics
            st.session_state["last_winner_origin"] = "storage"
            st.session_state["last_winner_meta"] = result.meta
            if st.session_state.get("pending_run_load_data", True):
                df_loaded, msg = load_selected_data(
                    symbol,
                    timeframe,
                    start_date,
                    end_date,
                )
                if df_loaded is None:
                    st.session_state["saved_runs_status"] = f"Data load failed: {msg}"
                else:
                    st.session_state["saved_runs_status"] = f"Run loaded with data: {msg}"
            else:
                st.session_state["saved_runs_status"] = f"Run loaded: {pending_run_id}"
        except Exception as exc:
            st.session_state["saved_runs_status"] = f"Load failed: {exc}"
        st.session_state.pop("pending_run_load_id", None)
        st.session_state.pop("pending_run_load_data", None)

    if st.session_state.get("ohlcv_df") is None:
        if not _is_builder:
            st.sidebar.info("Donnees non chargees.")
    else:
        cached_msg = st.session_state.get("ohlcv_status_msg", "")
        if cached_msg:
            st.sidebar.caption(f"Cache: {cached_msg}")

    # Lire le mode actif depuis session_state (défini plus bas ou lors d'un rerun précédent)
    _current_mode = st.session_state.get("optimization_mode", "Grille de Paramètres")

    # En mode Builder, le sélecteur de stratégie n'a pas de sens (le builder crée des stratégies)
    if _current_mode != "🏗️ Strategy Builder":
        _sidebar_section("🎯 Stratégie")

        # Mode de sélection : Classique vs Catalogue
        strategy_selection_mode = st.sidebar.radio(
            "Mode de sélection",
            ["📋 Classique", "🗂️ Catalogue"],
            key="strategy_selection_mode",
            horizontal=True,
            help="Classique = liste complète | Catalogue = filtré par catégories"
        )

        # Appliquer la sélection pending du catalogue (si disponible)
        if st.session_state.get("_catalog_strategy_selection_pending"):
            labels_to_apply = st.session_state.pop("_catalog_strategy_selection_pending", [])
            skipped = st.session_state.pop("_catalog_strategy_selection_skipped", 0)
            st.session_state["strategies_select"] = labels_to_apply
            if skipped > 0:
                st.sidebar.warning(f"⚠️ {skipped} stratégie(s) non exécutable(s) ignorée(s)")
            if labels_to_apply:
                st.sidebar.success(f"✅ {len(labels_to_apply)} stratégie(s) sélectionnée(s) depuis le catalogue")

        if strategy_selection_mode == "📋 Classique":
            # === MODE CLASSIQUE : MULTI-SÉLECTION STRATÉGIES (multiselect) ===
            strategy_labels_ui = _stable_shuffled_options(
                "_strategies_options_order_v1",
                list(strategy_options.keys()),
            )
            # Streamlit: ne pas combiner `default` avec un widget piloté via `key`.
            if "strategies_select" not in st.session_state:
                st.session_state["strategies_select"] = []
            strategy_names = st.sidebar.multiselect(
                "Stratégie(s)",
                strategy_labels_ui,
                key="strategies_select",
                help="Sélectionnez une ou plusieurs stratégies",
            )

            if not strategy_names:
                st.sidebar.info("Sélectionnez au moins une stratégie pour commencer.")

        else:
            # === MODE CATALOGUE : Utilise les stratégies déjà sélectionnées ===
            # Le catalogue gère sa propre UI en bas de page
            strategy_names = st.session_state.get("strategies_select", [])

            if strategy_names:
                st.sidebar.success(f"✅ {len(strategy_names)} stratégie(s) du catalogue")
                st.sidebar.caption(
                    "💡 Utilisez le panel **Strategy Catalog** en bas de page "
                    "pour filtrer et sélectionner vos stratégies"
                )
            else:
                st.sidebar.info(
                    "📂 Aucune stratégie sélectionnée.\n\n"
                    "Utilisez le panel **Strategy Catalog** en bas de page "
                    "pour sélectionner vos stratégies par catégorie."
                )

        # Info multi-stratégies si plusieurs sélections
        if len(strategy_names) > 1:
            st.sidebar.info(
                f"📋 **{len(strategy_names)} stratégies sélectionnées**\n\n"
                f"Paramètres configurables pour: **{strategy_names[0]}**\n\n"
                f"Autres stratégies utiliseront leurs paramètres par défaut."
            )

        # Compatibilité rétro: première stratégie pour l'affichage des paramètres
        strategy_name = strategy_names[0] if strategy_names else ""
        strategy_key = strategy_options.get(strategy_name, "") if strategy_name else ""

        # Message multi-sweep global (stratégies + tokens + timeframes)
        if len(strategy_names) > 1 or len(symbols) > 1 or len(timeframes) > 1:
            total_combos = len(strategy_names) * len(symbols) * len(timeframes)
            parts = []
            if len(strategy_names) > 1:
                parts.append(f"{len(strategy_names)} stratégie(s)")
            if len(symbols) > 1:
                parts.append(f"{len(symbols)} token(s)")
            if len(timeframes) > 1:
                parts.append(f"{len(timeframes)} TF(s)")

            if len(parts) > 1:  # Seulement si au moins 2 dimensions multiples
                st.sidebar.success(f"🔄 **Multi-sweep total**: {' × '.join(parts)} = **{total_combos} backtests**")

        strategy_info = None
        if strategy_key:
            st.sidebar.caption(get_strategy_description(strategy_key))

            try:
                strategy_info = get_strategy_info(strategy_key)

                if strategy_info.required_indicators:
                    indicators_list = ", ".join(
                        [f"**{ind.upper()}**" for ind in strategy_info.required_indicators]
                    )
                    st.sidebar.info(f"📊 Indicateurs requis: {indicators_list}")
                else:
                    st.sidebar.info("📊 Indicateurs: Calculés internement")

                if strategy_info.internal_indicators:
                    internal_list = ", ".join(
                        [f"{ind.upper()}" for ind in strategy_info.internal_indicators]
                    )
                    st.sidebar.caption(f"_Calculés: {internal_list}_")

            except KeyError:
                st.sidebar.warning(f"⚠️ Indicateurs non définis pour '{strategy_key}'")

        _sidebar_section("📈 Indicateurs")
        available_indicators = get_strategy_ui_indicators(strategy_key) if strategy_key else []
        # Tous les indicateurs sont toujours affichés
        active_indicators: List[str] = available_indicators if available_indicators else []

        if available_indicators:
            st.sidebar.caption(f"📊 {len(available_indicators)} indicateur(s) : {', '.join(available_indicators)}")
        elif strategy_key:
            st.sidebar.caption("Aucun indicateur disponible.")
    else:
        # Mode Builder : pas de sélection de stratégie (le builder les crée)
        strategy_names = []
        strategy_name = ""
        strategy_key = ""
        strategy_info = None
        available_indicators = []
        active_indicators = []

    # (Versioned Presets moved to bottom)

    _sidebar_section("🔄 Mode d'exécution")

    if "optimization_mode" not in st.session_state:
        st.session_state.optimization_mode = "Grille de Paramètres"
    if "run_backtest_requested" not in st.session_state:
        st.session_state.run_backtest_requested = False
    if "is_running" not in st.session_state:
        st.session_state.is_running = False

    if st.session_state.get("is_running", False):
        st.sidebar.warning("⏳ Exécution en cours (UI temporairement restreinte).")
        if st.sidebar.button(
            "🔓 Forcer le déverrouillage UI",
            key="force_unlock_ui",
            help="Réinitialise les verrous d'exécution si l'interface reste bloquée.",
        ):
            st.session_state.is_running = False
            st.session_state.run_backtest_requested = False
            st.sidebar.success("UI déverrouillée.")
            st.rerun()

    if "default_preset_applied" not in st.session_state:
        st.session_state["ui_n_workers"] = 32
        st.session_state["grid_worker_threads"] = 1
        st.session_state["gpu_n_workers"] = 1
        st.session_state["gpu_worker_threads"] = 1
        os.environ["BACKTEST_WORKER_THREADS"] = "1"
        st.session_state["default_preset_applied"] = True

    optimization_mode = st.session_state.optimization_mode

    # Defaults partagés (doivent être initialisés avant tout usage UI)
    unlimited_max_combos = 1_000_000_000_000
    default_workers_cpu = _env_int("BACKTEST_MAX_WORKERS", None)
    if default_workers_cpu is None:
        default_workers_cpu = _env_int("BACKTEST_WORKERS_CPU_OPTIMIZED", None)
    if default_workers_cpu is None:
        default_workers_cpu = _env_int("BACKTEST_WORKERS_GPU_OPTIMIZED", 32)
    default_workers_cpu = max(1, min(default_workers_cpu, 32))
    default_llm_unload = _env_bool("UNLOAD_LLM_DURING_BACKTEST", True)

    max_combos = unlimited_max_combos
    n_workers = default_workers_cpu

    st.sidebar.caption(f"📌 Mode : **{optimization_mode}**")

    if optimization_mode in {"Grille de Paramètres", "🤖 Optimisation LLM"}:
        st.sidebar.markdown("---")
        _sidebar_section("⚙️ Exécution")

        if "ui_n_workers" not in st.session_state:
            st.session_state["ui_n_workers"] = default_workers_cpu
        else:
            try:
                st.session_state["ui_n_workers"] = max(
                    1,
                    min(int(st.session_state["ui_n_workers"]), 32),
                )
            except (TypeError, ValueError):
                st.session_state["ui_n_workers"] = default_workers_cpu

        n_workers = st.sidebar.slider(
            "Workers parallèles (CPU)",
            min_value=1,
            max_value=32,
            value=int(st.session_state["ui_n_workers"]),
            key="ui_n_workers",
            help="Réglage global CPU partagé entre Grille, Optuna et LLM.",
        )
        st.session_state["grid_n_workers"] = n_workers
        st.session_state["llm_n_workers"] = n_workers

    action_slot = st.sidebar.container()

    # Bridge session_state ← exec_tabs (Grille de Paramètres / Optuna)
    use_optuna = st.session_state.get("exec_grid_use_optuna", False)
    optuna_n_trials = st.session_state.get("exec_grid_n_trials", 100)
    optuna_sampler = st.session_state.get("exec_grid_sampler", "tpe")
    optuna_pruning = st.session_state.get("exec_grid_pruning", True)
    optuna_metric = st.session_state.get("exec_grid_metric", "sharpe_ratio")
    optuna_early_stop = st.session_state.get("exec_grid_early_stop", 0)
    llm_config = None
    llm_max_iterations = 10
    llm_use_walk_forward = True
    role_model_config = None
    llm_topology_config = None
    llm_compare_enabled = False
    llm_compare_auto_run = True
    llm_compare_strategies: List[str] = []
    llm_compare_tokens: List[str] = []
    llm_compare_timeframes: List[str] = []
    llm_compare_metric = "sharpe_ratio"
    llm_compare_aggregate = "median"
    llm_compare_max_runs = 25
    llm_compare_use_preset = True
    llm_compare_generate_report = True
    llm_use_multi_agent = False
    llm_unload_during_backtest = default_llm_unload
    llm_model = None
    llm_routing_mode = str(
        st.session_state.get("exec_llm_routing_mode", "single_endpoint")
        or "single_endpoint"
    )

    # ── Strategy Builder defaults ──
    builder_objective = ""
    builder_model = "deepseek-r1:32b"
    builder_max_iterations = 10
    builder_target_sharpe = 1.0
    builder_capital = 10000.0
    builder_ollama_host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    builder_preload_model = True
    builder_keep_alive_minutes = 20
    builder_unload_after_run = False
    builder_auto_start_ollama = True
    builder_auto_market_pick = False
    builder_autonomous = False
    builder_auto_pause = 10
    builder_auto_use_llm = True
    builder_multi_llm_enabled = False
    builder_multi_llm_profile = "24GB_balanced"
    builder_use_parametric_catalog = False
    topology_data = st.session_state.get("exec_llm_topology_config")
    if isinstance(topology_data, LLMTopologyConfig):
        llm_topology_config = topology_data
    elif isinstance(topology_data, dict):
        llm_topology_config = LLMTopologyConfig.from_dict(topology_data)
    elif llm_routing_mode == "cooperative_multi_gpu":
        llm_topology_config = build_phase1_topology(
            primary_host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        )
    else:
        llm_topology_config = build_single_host_topology(
            primary_host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        )

    if optimization_mode == "🏗️ Strategy Builder":
        # UI Builder déplacée dans ui.exec_tabs._render_builder_tab()
        # Ici, on lit uniquement l'état pour alimenter SidebarState sans dupliquer les widgets.
        builder_autonomous = bool(st.session_state.get("builder_autonomous", False))
        builder_auto_pause = int(st.session_state.get("builder_auto_pause", 10))
        builder_auto_use_llm = bool(st.session_state.get("builder_auto_use_llm", True))
        builder_use_parametric_catalog = bool(st.session_state.get("builder_use_parametric_catalog", False))
        builder_objective = str(st.session_state.get("builder_objective", ""))
        builder_auto_market_pick = bool(st.session_state.get("builder_auto_market_pick", True))
        builder_model = str(st.session_state.get("builder_model", "deepseek-r1:32b"))
        builder_multi_llm_enabled = bool(
            st.session_state.get("builder_multi_llm_enabled", False)
        )
        builder_multi_llm_profile = str(
            st.session_state.get("builder_multi_llm_profile", "24GB_balanced")
        )
        builder_ollama_host = str(
            st.session_state.get(
                "builder_ollama_host",
                os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
            )
        )
        builder_auto_start_ollama = bool(st.session_state.get("builder_auto_start_ollama", True))
        builder_preload_model = bool(st.session_state.get("builder_preload_model", True))
        builder_keep_alive_minutes = int(st.session_state.get("builder_keep_alive_minutes", 20))
        builder_unload_after_run = bool(st.session_state.get("builder_unload_after_run", False))
        builder_max_iterations = int(st.session_state.get("builder_max_iters_slider", 10))
        builder_target_sharpe = float(st.session_state.get("builder_target_sharpe_input", 1.0))
        builder_capital = float(st.session_state.get("builder_capital_input", 10000.0))

        st.sidebar.caption("⚙️ Configuration Builder déplacée dans l'onglet principal Strategy Builder")

    elif optimization_mode == "🤖 Optimisation LLM":
        max_combos = unlimited_max_combos
        llm_config = st.session_state.get("exec_llm_config_obj")
        llm_model = st.session_state.get("exec_llm_model")
        llm_use_multi_agent = bool(st.session_state.get("exec_llm_use_multi_agent", False))
        role_model_config = st.session_state.get("exec_llm_role_model_config")
        llm_routing_mode = str(
            st.session_state.get("exec_llm_routing_mode", llm_routing_mode)
            or llm_routing_mode
        )
        topology_data = st.session_state.get("exec_llm_topology_config")
        if isinstance(topology_data, LLMTopologyConfig):
            llm_topology_config = topology_data
        elif isinstance(topology_data, dict):
            llm_topology_config = LLMTopologyConfig.from_dict(topology_data)
        llm_max_iterations = int(st.session_state.get("exec_llm_max_iterations", 10))
        llm_use_walk_forward = bool(st.session_state.get("exec_llm_use_walk_forward", True))
        llm_unload_during_backtest = bool(st.session_state.get("exec_llm_unload", default_llm_unload))
        llm_compare_enabled = bool(st.session_state.get("exec_llm_compare_enabled", False))
        llm_compare_auto_run = bool(st.session_state.get("exec_llm_compare_auto_run", True))
        llm_compare_strategies = list(st.session_state.get("exec_llm_compare_strategies", []))
        llm_compare_tokens = list(st.session_state.get("exec_llm_compare_tokens", []))
        llm_compare_timeframes = list(st.session_state.get("exec_llm_compare_timeframes", []))
        llm_compare_metric = str(st.session_state.get("exec_llm_compare_metric", "sharpe_ratio"))
        llm_compare_aggregate = str(st.session_state.get("exec_llm_compare_aggregate", "median"))
        llm_compare_max_runs = int(st.session_state.get("exec_llm_compare_max_runs", 25))
        llm_compare_use_preset = bool(st.session_state.get("exec_llm_compare_use_preset", True))
        llm_compare_generate_report = bool(st.session_state.get("exec_llm_compare_generate_report", True))

        st.sidebar.caption("⚙️ Configuration LLM déplacée dans l'onglet principal Optimisation LLM")

    # ======================== GPU ACCELERATION ========================
    st.sidebar.markdown("---")
    _sidebar_section("⚡ Accélération GPU")
    st.sidebar.caption("Mode CPU-only: GPU désactivé.")
    st.sidebar.caption("• Numba JIT + cache RAM utilisés • VRAM libérée pour autres usages")
    os.environ["BACKTEST_USE_GPU"] = "0"
    os.environ["BACKTEST_GPU_QUEUE_ENABLED"] = "0"

    param_mode = "range" if optimization_mode == "Grille de Paramètres" else "single"
    granularity_key = "granularity_global_pct"
    granularity_prev_key = "granularity_global_prev_pct"
    granularity_requested_key = "granularity_global_requested_pct"
    granularity_is_internal_update_key = "granularity_is_internal_update"
    granularity_delta = 0.0
    granularity_direction: Optional[str] = None

    if granularity_key not in st.session_state:
        st.session_state[granularity_key] = 0.0
    if granularity_prev_key not in st.session_state:
        st.session_state[granularity_prev_key] = float(st.session_state.get(granularity_key, 0.0))
    if granularity_requested_key not in st.session_state:
        st.session_state[granularity_requested_key] = float(st.session_state.get(granularity_key, 0.0))

    current_granularity_pct = float(st.session_state.get(granularity_key, 0.0))
    previous_granularity_pct = float(st.session_state.get(granularity_prev_key, current_granularity_pct))
    granularity_diff = current_granularity_pct - previous_granularity_pct
    if abs(granularity_diff) > 1e-12:
        granularity_delta = min(abs(granularity_diff) / 100.0, 1.0)
        granularity_direction = "increase" if granularity_diff > 0 else "decrease"
        st.session_state[granularity_requested_key] = current_granularity_pct

    params: Dict[str, Any] = {}
    param_ranges: Dict[str, Any] = {}
    param_specs: Dict[str, Any] = {}
    strategy_class = get_strategy(strategy_key) if strategy_key else None
    strategy_instance = None
    granularity_slot = None

    # En mode Builder, pas de section paramètres (le builder gère ses propres params)
    if optimization_mode != "🏗️ Strategy Builder":
        _sidebar_section("🔧 Paramètres")
        granularity_slot = st.sidebar.empty()

    if strategy_class:
        temp_strategy = strategy_class()
        strategy_instance = temp_strategy
        param_specs = temp_strategy.parameter_specs or {}
        label_overrides: Dict[str, str] = {}

        if strategy_key == "bollinger_best_longe_3i":
            label_overrides = {
                "entry_level": "Entrée",
                "tp_level": "Sortie_gagnante",
                "sl_level": "Stop-loss",
                "bb_std": "Bollinger_amplitude",
                "bb_period": "Bollinger_signal",
            }

        if param_specs:
            validation_errors = []

            if (
                param_mode == "single"
                and granularity_direction in {"increase", "decrease"}
                and granularity_delta > 0
                and len(strategy_names) <= 1
            ):
                current_values: Dict[str, Any] = {}
                for param_name, spec in param_specs.items():
                    if not getattr(spec, "optimize", True):
                        continue
                    widget_key = f"{strategy_key}_{param_name}"
                    if widget_key not in st.session_state:
                        st.session_state[widget_key] = getattr(spec, "default", None)
                    current_values[param_name] = st.session_state.get(
                        widget_key,
                        getattr(spec, "default", None),
                    )

                transformed_values = granularity_transform(
                    params=current_values,
                    param_specs=param_specs,
                    delta=granularity_delta,
                    direction=granularity_direction,
                )
                for param_name, new_value in transformed_values.items():
                    st.session_state[f"{strategy_key}_{param_name}"] = new_value
            elif (
                param_mode == "range"
                and granularity_direction in {"increase", "decrease"}
                and granularity_delta > 0
                and len(strategy_names) <= 1
            ):
                for param_name, spec in param_specs.items():
                    if not getattr(spec, "optimize", True):
                        continue

                    min_key = f"{strategy_key}_{param_name}_min"
                    max_key = f"{strategy_key}_{param_name}_max"

                    if min_key not in st.session_state:
                        st.session_state[min_key] = getattr(spec, "min_val", None)
                    if max_key not in st.session_state:
                        st.session_state[max_key] = getattr(spec, "max_val", None)

                    current_min = st.session_state.get(min_key, getattr(spec, "min_val", None))
                    current_max = st.session_state.get(max_key, getattr(spec, "max_val", None))
                    updated_max = granularity_transform(
                        params={param_name: current_max},
                        param_specs={param_name: spec},
                        delta=granularity_delta,
                        direction=granularity_direction,
                    ).get(param_name, current_max)

                    try:
                        if float(updated_max) < float(current_min):
                            updated_max = current_min
                    except (TypeError, ValueError):
                        pass

                    st.session_state[max_key] = updated_max

            for param_name, spec in param_specs.items():
                if not getattr(spec, "optimize", True):
                    continue

                if param_mode == "single":
                    value = create_param_range_selector(
                        param_name,
                        strategy_key,
                        mode="single",
                        spec=spec,
                        label=label_overrides.get(param_name),
                    )
                    if value is not None:
                        params[param_name] = value

                        is_valid, error = validate_param(param_name, value)
                        if not is_valid:
                            validation_errors.append(error)
                else:
                    range_data = create_param_range_selector(
                        param_name,
                        strategy_key,
                        mode="range",
                        spec=spec,
                        label=label_overrides.get(param_name),
                    )
                    if range_data is not None:
                        param_ranges[param_name] = range_data
                        if spec is not None:
                            params[param_name] = spec.default
                        else:
                            params[param_name] = getattr(spec, "default", params.get(param_name))
                        logger.debug("Sidebar param range generated - %s: %s", param_name, range_data)

            if validation_errors:
                for err in validation_errors:
                    st.sidebar.error(err)

            logger.debug("Sidebar param ranges final keys: %s", list(param_ranges.keys()))
            logger.debug(
                "Sidebar optimizable parameter count: %s",
                sum(1 for s in param_specs.values() if getattr(s, "optimize", True)),
            )

            normalized_ranges = param_ranges
            range_warnings: List[str] = []

            if param_mode == "range" and param_ranges:
                try:
                    normalized_ranges, range_warnings = normalize_param_ranges(
                        param_specs,
                        param_ranges,
                    )
                    param_ranges = normalized_ranges
                except ValueError as exc:
                    st.sidebar.error(f"Plage invalide: {exc}")

            if range_warnings:
                for warning in range_warnings:
                    st.sidebar.warning(f"⚠️ {warning}")

            if param_mode == "range" and param_ranges:
                st.sidebar.markdown("---")
                stats = compute_search_space_stats(
                    param_ranges,
                    max_combinations=max_combos,
                )

                if stats.is_continuous:
                    st.sidebar.info("ℹ️ Espace continu détecté")
                elif stats.has_overflow:
                    st.sidebar.warning(
                        f"⚠️ {stats.total_combinations:,} combinaisons (limite: {max_combos:,})"
                    )
                    st.sidebar.caption("Réduisez les plages ou augmentez le step")
                else:
                    st.sidebar.success(
                        f"✅ {stats.total_combinations:,} combinaisons à tester"
                    )

                with st.sidebar.expander("📊 Détail par paramètre"):
                    for pname, pcount in stats.per_param_counts.items():
                        st.caption(f"• {pname}: {pcount} valeurs")
            else:
                st.sidebar.caption("📊 Mode simple: 1 combinaison")
    elif strategy_key:
        st.sidebar.error(f"Stratégie '{strategy_key}' non trouvée")

    _sidebar_section("💰 Trading")

    # Checkbox pour activer/désactiver le leverage
    leverage_enabled = st.sidebar.checkbox(
        "Activer le leverage",
        value=False,  # Désactivé par défaut = leverage forcé à 1
        key="leverage_enabled",
        help="Si décoché, leverage=1 (sans effet de levier). Recommandé pour tests sûrs.",
    )

    if leverage_enabled:
        leverage = create_param_range_selector("leverage", "trading", mode="single")
        params["leverage"] = leverage
    else:
        leverage = 1.0
        params["leverage"] = 1.0
        st.sidebar.caption("_Leverage désactivé → forcé à 1×_")

    initial_capital = st.sidebar.number_input(
        "Capital Initial ($)",
        min_value=1000,
        max_value=1000000,
        value=10000,
        step=1000,
        help="Capital de départ (1,000 - 1,000,000)",
    )

    # Liste des paramètres désactivés (pour transmission au backtest)
    disabled_params: List[str] = []
    if not leverage_enabled:
        disabled_params.append("leverage")

    # Ajouter les indicateurs non cochés à disabled_params (info seulement)
    if available_indicators:
        unchecked_indicators = [ind for ind in available_indicators if ind not in active_indicators]
        if unchecked_indicators:
            st.sidebar.caption(f"_Indicateurs masqués: {', '.join(unchecked_indicators)}_")

    # =========================================================================
    # Walk-Forward Analysis (WFA) — 10/02/2026
    # =========================================================================
    _sidebar_section("🔬 Walk-Forward Analysis")

    use_walk_forward = st.sidebar.checkbox(
        "Activer la validation Walk-Forward",
        value=False,
        key="use_walk_forward",
        help=(
            "Découpe les données en folds train/test séquentiels pour valider "
            "la robustesse hors-échantillon. Désactivé par défaut."
        ),
    )
    wfa_n_folds = 5
    wfa_train_ratio = 0.7
    wfa_expanding = False

    if use_walk_forward:
        wfa_n_folds = st.sidebar.slider(
            "Nombre de folds",
            min_value=2,
            max_value=10,
            value=5,
            key="wfa_n_folds",
            help="Nombre de fenêtres train/test glissantes.",
        )
        wfa_train_ratio = st.sidebar.slider(
            "Ratio train (%)",
            min_value=50,
            max_value=90,
            value=70,
            step=5,
            key="wfa_train_ratio",
            help="Proportion des données allouées à l'entraînement par fold.",
        ) / 100.0
        wfa_expanding = st.sidebar.checkbox(
            "Mode expanding (ancré au début)",
            value=False,
            key="wfa_expanding",
            help=(
                "Si coché, chaque fold inclut toutes les données depuis le début "
                "(anchored). Sinon, fenêtre glissante (rolling)."
            ),
        )
        st.sidebar.caption(
            f"📐 {wfa_n_folds} folds × {wfa_train_ratio:.0%} train "
            f"| {'expanding' if wfa_expanding else 'rolling'}"
        )

    _sidebar_section("💾 Versioned Presets")

    versioned_presets = list_strategy_versions(strategy_key)

    if "_sync_preset_version" in st.session_state:
        st.session_state["versioned_preset_version"] = st.session_state.pop(
            "_sync_preset_version"
        )
    if "_sync_preset_name" in st.session_state:
        st.session_state["versioned_preset_name"] = st.session_state.pop(
            "_sync_preset_name"
        )

    last_saved = st.session_state.pop("versioned_preset_last_saved", None)
    if last_saved:
        st.sidebar.success(f"Preset saved: {last_saved}")

    if versioned_presets:
        versions = []
        for preset in versioned_presets:
            meta = preset.metadata or {}
            version = meta.get("version")
            if version and version not in versions:
                versions.append(version)

        default_version = resolve_latest_version(strategy_key)
        if default_version in versions:
            default_index = versions.index(default_version)
        else:
            default_index = 0

        if (
            "versioned_preset_version" in st.session_state
            and st.session_state["versioned_preset_version"] not in versions
        ):
            del st.session_state["versioned_preset_version"]

        selected_version = st.sidebar.selectbox(
            "Preset version",
            versions,
            index=default_index,
            key="versioned_preset_version",
        )

        presets_for_version = [
            p for p in versioned_presets if (p.metadata or {}).get("version") == selected_version
        ]
        preset_names = [p.name for p in presets_for_version]

        if (
            "versioned_preset_name" in st.session_state
            and st.session_state["versioned_preset_name"] not in preset_names
        ):
            del st.session_state["versioned_preset_name"]

        selected_preset_name = st.sidebar.selectbox(
            "Preset",
            preset_names,
            key="versioned_preset_name",
        )

        selected_preset = next(
            (p for p in presets_for_version if p.name == selected_preset_name),
            None,
        )

        if selected_preset is not None:
            meta = selected_preset.metadata or {}
            created_at = meta.get("created_at", "")
            if created_at:
                st.sidebar.caption(f"Created: {created_at}")

            indicators = selected_preset.indicators or []
            if indicators:
                st.sidebar.caption(f"Indicators: {', '.join(indicators)}")

            params_values = selected_preset.get_default_values()
            if params_values:
                st.sidebar.json(params_values)

            metrics = meta.get("metrics") or {}
            summary_keys = [
                "sharpe_ratio",
                "total_return_pct",
                "max_drawdown",
                "win_rate",
            ]
            summary = {k: metrics.get(k) for k in summary_keys if k in metrics}
            if summary:
                st.sidebar.json(summary)

        if st.sidebar.button("⬇️ Charger versioned preset", key="load_versioned_preset"):
            try:
                loaded_preset = load_strategy_version(
                    strategy_name=strategy_key,
                    version=selected_version,
                    preset_name=selected_preset_name,
                )
                apply_versioned_preset(loaded_preset, strategy_key)
                st.session_state["loaded_versioned_preset"] = loaded_preset.to_dict()
                st.sidebar.success("Versioned preset loaded")
                st.rerun()
            except Exception as exc:
                st.sidebar.error(f"Failed to load preset: {exc}")
    else:
        st.sidebar.caption("No versioned presets found.")

    render_saved_runs_panel(
        st.session_state.get("last_run_result"),
        strategy_key,
        symbol,
        timeframe,
    )

    # Multi-sweep lists (symbols et timeframes déjà définis par multiselect)
    # strategy_keys et all_params/ranges/specs pour toutes les stratégies sélectionnées
    strategy_keys = [strategy_options[name] for name in strategy_names]
    all_params: Dict[str, Dict[str, Any]] = {}
    all_param_ranges: Dict[str, Dict[str, Any]] = {}
    all_param_specs: Dict[str, Dict[str, Any]] = {}

    # Gestion multi-stratégies : afficher les widgets pour CHAQUE stratégie sélectionnée
    if len(strategy_names) > 1:
        all_params, all_param_ranges, all_param_specs = render_multi_strategy_params(
            strategy_keys=strategy_keys,
            strategy_names=strategy_names,
            param_mode=param_mode,
            granularity_delta=granularity_delta,
            granularity_direction=granularity_direction,
        )
    else:
        # Mode stratégie unique : comportement actuel (widgets existants)
        if strategy_key:
            all_params[strategy_key] = params
            all_param_ranges[strategy_key] = param_ranges
            all_param_specs[strategy_key] = param_specs

    if optimization_mode != "🏗️ Strategy Builder":
        granularity_source_params: Dict[str, Dict[str, Any]] = all_params
        if param_mode == "range":
            range_based_params: Dict[str, Dict[str, Any]] = {}
            for strat_key, specs in all_param_specs.items():
                strat_ranges = all_param_ranges.get(strat_key) or {}
                strat_values: Dict[str, Any] = {}
                for pname, spec in specs.items():
                    if not getattr(spec, "optimize", True):
                        continue
                    range_data = strat_ranges.get(pname)
                    if not isinstance(range_data, dict):
                        continue
                    if range_data.get("max") is not None:
                        strat_values[pname] = range_data.get("max")
                    elif range_data.get("min") is not None:
                        strat_values[pname] = range_data.get("min")
                if strat_values:
                    range_based_params[strat_key] = strat_values
            if range_based_params:
                granularity_source_params = range_based_params

        granularity_summary = compute_global_granularity_percent(
            all_params=granularity_source_params,
            all_param_specs=all_param_specs,
        )

        if granularity_summary is None:
            granularity_summary = float(st.session_state.get(granularity_key, 0.0))
        granularity_summary = max(0.0, min(100.0, float(granularity_summary)))

        granularity_is_internal_update = (
            abs(float(st.session_state.get(granularity_key, 0.0)) - granularity_summary) > 1e-9
        )
        if granularity_is_internal_update and abs(granularity_diff) <= 1e-12:
            st.session_state[granularity_requested_key] = granularity_summary
        if granularity_is_internal_update:
            st.session_state[granularity_key] = granularity_summary

        requested_value = float(
            st.session_state.get(
                granularity_requested_key,
                st.session_state.get(granularity_key, granularity_summary),
            )
        )

        if granularity_slot is not None:
            with granularity_slot.container():
                st.markdown("---")
                st.caption("**Granularité globale (indicateurs)**")
                granularity_value = st.slider(
                    "Granularité globale (%)",
                    min_value=0.0,
                    max_value=100.0,
                    value=float(st.session_state.get(granularity_key, granularity_summary)),
                    step=0.05,
                    key=granularity_key,
                    help=(
                        "Résumé moyen des paramètres normalisés. "
                        "Modifier ce curseur rapproche/éloigne automatiquement les paramètres de leur max/min "
                        "sans toucher min/max/step."
                    ),
                )
                st.caption(
                    f"Demandé: {requested_value:.2f}% | "
                    f"Effectif (après snap): {granularity_summary:.2f}%"
                )
        else:
            st.sidebar.markdown("---")
            st.sidebar.caption("**Granularité globale (indicateurs)**")
            granularity_value = st.sidebar.slider(
                "Granularité globale (%)",
                min_value=0.0,
                max_value=100.0,
                value=float(st.session_state.get(granularity_key, granularity_summary)),
                step=0.05,
                key=granularity_key,
                help=(
                    "Résumé moyen des paramètres normalisés. "
                    "Modifier ce curseur rapproche/éloigne automatiquement les paramètres de leur max/min "
                    "sans toucher min/max/step."
                ),
            )
            st.sidebar.caption(
                f"Demandé: {requested_value:.2f}% | "
                f"Effectif (après snap): {granularity_summary:.2f}%"
            )
        st.session_state[granularity_prev_key] = float(granularity_value)
        st.session_state[granularity_is_internal_update_key] = granularity_is_internal_update

    if param_mode == "range" and len(strategy_names) > 1:
        st.sidebar.markdown("---")
        _sidebar_section("📌 Combinaisons multi-stratégies")
        total_per_sweep = 0
        for strat_key in strategy_keys:
            ranges = all_param_ranges.get(strat_key) or {}
            stats = compute_search_space_stats(
                ranges,
                max_combinations=max_combos,
            )
            if stats.is_continuous:
                st.sidebar.caption(f"• {strat_key}: continu")
            else:
                total_per_sweep += stats.total_combinations
                st.sidebar.caption(f"• {strat_key}: {stats.total_combinations:,} combinaisons")

        total_runs = total_per_sweep * max(1, len(symbols)) * max(1, len(timeframes))
        st.sidebar.info(
            f"Total estimé (somme stratégies × tokens × TF): {total_runs:,} runs"
        )

    st.sidebar.markdown("---")
    _render_sidebar_summary_card(
        optimization_mode=optimization_mode,
        strategy_names=strategy_names,
        symbols=symbols,
        timeframes=timeframes,
        use_date_filter=use_date_filter,
    )

    draft_state = SidebarState(
        debug_enabled=debug_enabled,
        symbol=symbol,
        timeframe=timeframe,
        use_date_filter=use_date_filter,
        start_date=start_date,
        end_date=end_date,
        available_tokens=available_tokens,
        available_timeframes=available_timeframes,
        strategy_key=strategy_key,
        strategy_name=strategy_name,
        strategy_info=strategy_info,
        strategy_instance=strategy_instance,
        params=params,
        param_ranges=param_ranges,
        param_specs=param_specs,
        active_indicators=active_indicators,
        optimization_mode=optimization_mode,
        max_combos=max_combos,
        n_workers=n_workers,
        # Stabilisation auto du marché (désactivée par défaut)
        auto_stabilization_enabled=False,
        stabilization_method="combined",
        stabilization_window=20,
        stabilization_volume_ratio_max=3.0,
        stabilization_volatility_ratio_max=2.5,
        stabilization_min_consecutive_bars=3,
        stabilization_min_bars_keep=100,
        # Multi-sweep lists
        symbols=symbols,
        timeframes=timeframes,
        strategy_keys=strategy_keys,
        all_params=all_params,
        all_param_ranges=all_param_ranges,
        all_param_specs=all_param_specs,
        # Optuna
        use_optuna=use_optuna,
        optuna_n_trials=optuna_n_trials,
        optuna_sampler=optuna_sampler,
        optuna_pruning=optuna_pruning,
        optuna_metric=optuna_metric,
        optuna_early_stop=optuna_early_stop,
        llm_config=llm_config,
        llm_model=llm_model,
        llm_use_multi_agent=llm_use_multi_agent,
        role_model_config=role_model_config,
        llm_routing_mode=llm_routing_mode,
        llm_topology_config=llm_topology_config,
        llm_max_iterations=llm_max_iterations,
        llm_use_walk_forward=llm_use_walk_forward,
        llm_unload_during_backtest=llm_unload_during_backtest,
        llm_compare_enabled=llm_compare_enabled,
        llm_compare_auto_run=llm_compare_auto_run,
        llm_compare_strategies=llm_compare_strategies,
        llm_compare_tokens=llm_compare_tokens,
        llm_compare_timeframes=llm_compare_timeframes,
        llm_compare_metric=llm_compare_metric,
        llm_compare_aggregate=llm_compare_aggregate,
        llm_compare_max_runs=llm_compare_max_runs,
        llm_compare_use_preset=llm_compare_use_preset,
        llm_compare_generate_report=llm_compare_generate_report,
        initial_capital=initial_capital,
        leverage=leverage,
        leverage_enabled=leverage_enabled,
        disabled_params=disabled_params,
        # Walk-Forward Analysis
        use_walk_forward=use_walk_forward,
        wfa_n_folds=wfa_n_folds,
        wfa_train_ratio=wfa_train_ratio,
        wfa_expanding=wfa_expanding,
        # Strategy Builder
        builder_objective=builder_objective,
        builder_model=builder_model,
        builder_max_iterations=builder_max_iterations,
        builder_target_sharpe=builder_target_sharpe,
        builder_capital=builder_capital,
        builder_ollama_host=builder_ollama_host,
        builder_preload_model=builder_preload_model,
        builder_keep_alive_minutes=builder_keep_alive_minutes,
        builder_unload_after_run=builder_unload_after_run,
        builder_auto_start_ollama=builder_auto_start_ollama,
        builder_auto_market_pick=builder_auto_market_pick,
        # Mode autonome
        builder_autonomous=builder_autonomous,
        builder_auto_pause=builder_auto_pause,
        builder_auto_use_llm=builder_auto_use_llm,
        builder_multi_llm_enabled=builder_multi_llm_enabled,
        builder_multi_llm_profile=builder_multi_llm_profile,
        # Catalogue paramétrique
        builder_use_parametric_catalog=builder_use_parametric_catalog,
    )

    applied_state = _apply_config_guard(draft_state)
    pending = st.session_state.get("config_pending_changes", False)

    run_label_map = {
        "Backtest Simple": "🚀 Lancer le Backtest",
        "Grille de Paramètres": "🧪 Lancer le Sweep",
        "🤖 Optimisation LLM": "🧠 Lancer l'itération LLM",
        "🏗️ Strategy Builder": "🏗️ Lancer le Builder",
    }
    run_label = run_label_map.get(
        st.session_state.optimization_mode,
        "🚀 Lancer le Backtest",
    )

    def _apply_pending_config() -> None:
        st.session_state["applied_config_signature"] = st.session_state.get(
            "draft_config_signature"
        )
        st.session_state["applied_sidebar_state"] = draft_state
        st.session_state["config_pending_changes"] = False

    with action_slot:
        st.markdown("---")
        _sidebar_section("▶ Actions")

        col_load, col_run = st.columns(2)
        with col_load:
            if st.button(
                "⬇️ Charger données",
                key="load_ohlcv_action",
                disabled=st.session_state.is_running,
                width="stretch",
            ):
                if pending:
                    _apply_pending_config()
                is_builder_autonomous = (
                    st.session_state.get("optimization_mode") == "🏗️ Strategy Builder"
                    and bool(st.session_state.get("builder_autonomous", False))
                )
                if is_builder_autonomous and (not symbol or not timeframe):
                    st.session_state["ohlcv_df"] = None
                    st.session_state["ohlcv_status_msg"] = (
                        "Mode autonome actif: aucune présélection requise."
                    )
                    st.info(
                        "Mode autonome actif: aucun token/timeframe n'est requis. "
                        "Le Builder choisira un marché valide au lancement."
                    )
                else:
                    df_loaded, msg = load_selected_data(
                        symbol, timeframe, start_date, end_date
                    )
                    if df_loaded is None:
                        if is_builder_autonomous:
                            st.session_state["ohlcv_df"] = None
                            st.session_state["ohlcv_status_msg"] = (
                                f"Présélection ignorée: {msg}"
                            )
                            st.warning(
                                f"Présélection {symbol or '—'} {timeframe or '—'} rejetée: {msg}. "
                                "Le Builder autonome choisira un autre marché valide au lancement."
                            )
                        else:
                            st.error(f"Erreur chargement: {msg}")
                    else:
                        st.success(f"Données chargées: {msg}")

        with col_run:
            if st.button(
                run_label,
                key="run_sidebar_action",
                type="primary",
                disabled=st.session_state.is_running,
                width="stretch",
            ):
                if pending:
                    _apply_pending_config()
                if st.session_state.get("optimization_mode") == "🏗️ Strategy Builder":
                    # Évite un ancrage persistant du bootstrap marché entre deux lancements Builder.
                    for key in (
                        "_builder_auto_bootstrap_symbol",
                        "_builder_auto_bootstrap_timeframe",
                        "_builder_startup_symbol",
                        "_builder_startup_timeframe",
                        "_builder_tf_usage",
                    ):
                        st.session_state.pop(key, None)
                st.session_state.run_backtest_requested = True
                st.rerun()

        if pending:
            st.caption(
                "⚠️ Modifications non appliquées (application au lancement/chargement)"
            )
        else:
            st.caption("✅ Configuration prête.")

    # === PANEL CATALOGUE DE STRATÉGIES ===
    # Afficher uniquement en mode Catalogue et hors mode Builder
    if (
        _current_mode != "🏗️ Strategy Builder"
        and st.session_state.get("strategy_selection_mode") == "🗂️ Catalogue"
    ):
        render_strategy_catalog_panel(strategy_options)

    return applied_state
