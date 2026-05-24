"""Module-ID: ui.state

Purpose: Définit les structures de données pour l'état de l'interface utilisateur.

Role in pipeline: state management

Key components: SidebarState

Inputs: Paramètres utilisateur

Outputs: État structuré

Dependencies: dataclasses

Conventions: État immutable via dataclass

Read-if: Gestion d'état UI

Skip-if: Logique métier pure
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from config.market_selection import (
    UNIVERSE_MODE_CANONICAL,
    UNIVERSE_MODE_EXPLORATORY,
    UNIVERSE_MODE_OPTIONS,
    normalize_universe_mode,
)

BUILDER_PRELOAD_MODEL_DEFAULT = True
# 1440 minutes = 24h: garde le modele resident pendant une journee de travail
# sans avoir a passer par un keep_alive "-1" qui demanderait un patch d'Ollama.
BUILDER_KEEP_ALIVE_MINUTES_DEFAULT = 1440
BUILDER_UNLOAD_AFTER_RUN_DEFAULT = False
BUILDER_AUTO_START_OLLAMA_DEFAULT = True
BUILDER_MODEL_SINGLE_LLM_DEFAULT = "gemma4:26b"
BUILDER_MAX_ITERATIONS_DEFAULT = 5
BUILDER_TARGET_SHARPE_DEFAULT = 1.0
BUILDER_CAPITAL_DEFAULT = 10000.0
BUILDER_AUTO_MARKET_PICK_DEFAULT = True
BUILDER_AUTONOMOUS_DEFAULT = True
BUILDER_AUTO_PAUSE_DEFAULT = 2
BUILDER_FLOW_ANALYSIS_ENABLED_DEFAULT = False
BUILDER_EXECUTION_MODE_MONO = "mono_single_llm"
BUILDER_EXECUTION_MODE_OPTIONS = (BUILDER_EXECUTION_MODE_MONO,)
BUILDER_OPTIMIZATION_MODE = "🏗️ Strategy Builder"
BUILDER_UNIVERSE_MODE_CANONICAL = UNIVERSE_MODE_CANONICAL
BUILDER_UNIVERSE_MODE_DEFAULT = UNIVERSE_MODE_EXPLORATORY
BUILDER_UNIVERSE_MODE_OPTIONS = UNIVERSE_MODE_OPTIONS
_BUILDER_LAUNCH_STATE_KEYS = (
    "_builder_auto_bootstrap_symbol",
    "_builder_force_ollama_start_once",
    "_builder_reset_live_stream_on_launch",
    "_builder_auto_bootstrap_timeframe",
    "_builder_startup_symbol",
    "_builder_startup_timeframe",
    "_builder_tf_usage",
    "builder_launch_pending",
)
_BUILDER_RUNTIME_STATE_KEYS = (
    "builder_session",
    "builder_model_effective",
    "builder_runtime_diagnostic",
    "builder_autonomous_history",
    "builder_autonomous_supervisor",
    "_builder_objective_input_sync",
) + _BUILDER_LAUNCH_STATE_KEYS
_UI_EXECUTION_STATE_DEFAULTS = {
    "is_running": False,
    "stop_requested": False,
    "run_backtest_requested": False,
    "load_ohlcv_requested": False,
}
UI_EXECUTION_PHASE_IDLE = "idle"
UI_EXECUTION_PHASE_LAUNCH_PENDING = "launch_pending"
UI_EXECUTION_PHASE_RUNNING = "running"
UI_EXECUTION_PHASE_STOPPING = "stopping"
_UI_EXECUTION_PHASE_KEY = "ui_execution_phase"
_UI_EXECUTION_PHASE_OPTIONS = {
    UI_EXECUTION_PHASE_IDLE,
    UI_EXECUTION_PHASE_LAUNCH_PENDING,
    UI_EXECUTION_PHASE_RUNNING,
    UI_EXECUTION_PHASE_STOPPING,
}


def _state_get(container: Any, key: str, default: Any = None) -> Any:
    getter = getattr(container, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            pass
    try:
        return container[key]
    except Exception:
        return getattr(container, key, default)


def _state_contains(container: Any, key: str) -> bool:
    try:
        return key in container
    except Exception:
        return hasattr(container, key)


def _state_set(container: Any, key: str, value: Any) -> None:
    try:
        container[key] = value
        return
    except Exception:
        setattr(container, key, value)


def _state_pop(container: Any, key: str, default: Any = None) -> Any:
    popper = getattr(container, "pop", None)
    if callable(popper):
        try:
            return popper(key, default)
        except TypeError:
            pass
    if hasattr(container, key):
        value = getattr(container, key)
        try:
            delattr(container, key)
        except Exception:
            return value
        return value
    return default


def _normalize_ui_execution_phase(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _UI_EXECUTION_PHASE_OPTIONS:
        return normalized
    return ""


def _set_ui_execution_phase(session_state: Any, phase: str) -> str:
    normalized = _normalize_ui_execution_phase(phase) or UI_EXECUTION_PHASE_IDLE
    _state_set(session_state, _UI_EXECUTION_PHASE_KEY, normalized)
    return normalized


def _infer_ui_execution_phase(session_state: Any) -> str:
    explicit = _normalize_ui_execution_phase(
        _state_get(session_state, _UI_EXECUTION_PHASE_KEY, ""),
    )
    if explicit:
        return explicit
    if bool(_state_get(session_state, "stop_requested", False)):
        return UI_EXECUTION_PHASE_STOPPING
    if bool(_state_get(session_state, "run_backtest_requested", False)):
        return UI_EXECUTION_PHASE_LAUNCH_PENDING
    if bool(_state_get(session_state, "is_running", False)):
        return UI_EXECUTION_PHASE_RUNNING
    return UI_EXECUTION_PHASE_IDLE


def get_ui_execution_phase(session_state: Any) -> str:
    phase = _infer_ui_execution_phase(session_state)
    return _set_ui_execution_phase(session_state, phase)


def is_builder_optimization_mode(source: Any, fallback: str = "") -> bool:
    if isinstance(source, dict):
        mode = source.get("optimization_mode", fallback)
    else:
        mode = getattr(source, "optimization_mode", fallback)
    return str(mode or "").strip() == BUILDER_OPTIMIZATION_MODE


def has_pending_builder_launch(session_state: Any) -> bool:
    return bool(_state_get(session_state, "builder_launch_pending", False))


def should_preserve_builder_launch(source: Any, session_state: Any) -> bool:
    return is_builder_optimization_mode(source) and has_pending_builder_launch(
        session_state,
    )


def clear_builder_launch_state(session_state: Any) -> None:
    for key in _BUILDER_LAUNCH_STATE_KEYS:
        _state_pop(session_state, key, None)


def clear_builder_runtime_state(session_state: Any) -> None:
    for key in _BUILDER_RUNTIME_STATE_KEYS:
        _state_pop(session_state, key, None)


def consume_builder_launch_pending(session_state: Any) -> None:
    _state_pop(session_state, "builder_launch_pending", None)


def clear_execution_state(
    session_state: Any,
    *,
    clear_stop_requested: bool = True,
    clear_builder_launch: bool = False,
) -> None:
    _state_set(session_state, "is_running", False)
    _state_set(session_state, "run_backtest_requested", False)
    if clear_stop_requested:
        _state_set(session_state, "stop_requested", False)
        _set_ui_execution_phase(session_state, UI_EXECUTION_PHASE_IDLE)
    else:
        phase = (
            UI_EXECUTION_PHASE_STOPPING
            if bool(_state_get(session_state, "stop_requested", False))
            else UI_EXECUTION_PHASE_IDLE
        )
        _set_ui_execution_phase(session_state, phase)
    if clear_builder_launch:
        clear_builder_launch_state(session_state)


def ensure_ui_execution_state_defaults(session_state: Any) -> None:
    for key, value in _UI_EXECUTION_STATE_DEFAULTS.items():
        if not _state_contains(session_state, key):
            _state_set(session_state, key, value)
    get_ui_execution_phase(session_state)


def consume_ui_run_request(session_state: Any) -> bool:
    requested = bool(_state_get(session_state, "run_backtest_requested", False))
    if requested:
        phase = get_ui_execution_phase(session_state)
        _state_set(session_state, "run_backtest_requested", False)
        if phase == UI_EXECUTION_PHASE_LAUNCH_PENDING:
            _set_ui_execution_phase(session_state, UI_EXECUTION_PHASE_LAUNCH_PENDING)
    return requested


def arm_ui_load_request(session_state: Any) -> None:
    _state_set(session_state, "stop_requested", False)
    _state_set(session_state, "load_ohlcv_requested", True)
    _set_ui_execution_phase(session_state, UI_EXECUTION_PHASE_IDLE)


def arm_ui_run_request(session_state: Any, *, builder_mode: bool = False) -> None:
    if builder_mode:
        clear_builder_launch_state(session_state)
        _state_set(session_state, "builder_launch_pending", True)
        _state_set(session_state, "_builder_force_ollama_start_once", True)
        _state_set(session_state, "_builder_reset_live_stream_on_launch", True)
        _state_pop(session_state, "builder_model_effective", None)
    _state_set(session_state, "stop_requested", False)
    _state_set(session_state, "run_backtest_requested", True)
    _state_set(session_state, "is_running", True)
    _set_ui_execution_phase(session_state, UI_EXECUTION_PHASE_LAUNCH_PENDING)


def mark_ui_run_started(session_state: Any) -> None:
    _state_set(session_state, "is_running", True)
    _state_set(session_state, "stop_requested", False)
    _state_set(session_state, "run_backtest_requested", False)
    _set_ui_execution_phase(session_state, UI_EXECUTION_PHASE_RUNNING)


def mark_ui_stop_requested(session_state: Any) -> None:
    _state_set(session_state, "stop_requested", True)
    _state_set(session_state, "is_running", False)
    _state_set(session_state, "run_backtest_requested", False)
    _state_set(session_state, "load_ohlcv_requested", False)
    _set_ui_execution_phase(session_state, UI_EXECUTION_PHASE_STOPPING)


def persist_run_winner(
    session_state: Any,
    result: Any,
    params: Any,
    metrics: Any,
    origin: str,
    meta: Any,
) -> None:
    _state_set(session_state, "last_run_result", result)
    _state_set(session_state, "last_winner_params", params)
    _state_set(session_state, "last_winner_metrics", metrics)
    _state_set(session_state, "last_winner_origin", origin)
    _state_set(session_state, "last_winner_meta", meta)


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _coerce_non_negative_int(value: Any, default: int) -> int:
    try:
        resolved = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, resolved)


def normalize_builder_execution_mode(raw_value: Any) -> str:
    value = str(raw_value or "").strip()
    if value in BUILDER_EXECUTION_MODE_OPTIONS:
        return value
    return ""


def resolve_builder_execution_preferences(source: Any) -> dict[str, Any]:
    """Normalise le mode d'execution Builder depuis session_state ou SidebarState."""

    return {
        "builder_execution_mode": BUILDER_EXECUTION_MODE_MONO,
        "builder_llm_routing_mode": "single_endpoint",
    }


def resolve_builder_runtime_preferences(source: Any) -> dict[str, Any]:
    """Retourne le profil runtime Builder stable.

    Les anciens réglages avancés Streamlit ont été retirés de l'interface: ils
    ne doivent plus être réactivés par des clés de widgets persistées.
    """
    _ = source
    return {
        "builder_auto_start_ollama": False,
        "builder_preload_model": False,
        "builder_keep_alive_minutes": BUILDER_KEEP_ALIVE_MINUTES_DEFAULT,
        "builder_unload_after_run": False,
    }


def _default_builder_flow_analysis_ablation() -> dict[str, bool]:
    try:
        from agents.pipeline_instrumentation import AblationController

        return dict.fromkeys(sorted(AblationController.ABLATABLE_STEPS), True)
    except Exception:
        return {}


def _normalize_builder_flow_analysis_ablation(
    raw_value: Any,
) -> dict[str, bool]:
    normalized = _default_builder_flow_analysis_ablation()
    if not isinstance(raw_value, dict):
        return normalized
    for step in list(normalized.keys()):
        if step in raw_value:
            normalized[step] = _coerce_bool(raw_value.get(step), normalized[step])
    return normalized


def resolve_builder_flow_analysis_preferences(source: Any) -> dict[str, Any]:
    """Normalise l'analyse de flux Builder depuis session_state ou SidebarState."""

    def _read(name: str, default: Any) -> Any:
        if isinstance(source, dict):
            widget_key_overrides = {
                "builder_flow_analysis_enabled": "builder_flow_analysis_enabled_toggle",
            }
            widget_key = widget_key_overrides.get(name)
            if widget_key and widget_key in source:
                return source.get(widget_key, default)
            return source.get(name, default)
        return getattr(source, name, default)

    enabled = _coerce_bool(
        _read("builder_flow_analysis_enabled", BUILDER_FLOW_ANALYSIS_ENABLED_DEFAULT),
        BUILDER_FLOW_ANALYSIS_ENABLED_DEFAULT,
    )
    ablation = _normalize_builder_flow_analysis_ablation(
        _read("builder_flow_analysis_ablation", {}),
    )

    if isinstance(source, dict):
        disabled_steps = source.get("builder_flow_analysis_disabled_steps_multiselect")
        if isinstance(disabled_steps, (list, tuple, set)):
            ablation = _default_builder_flow_analysis_ablation()
            for step in disabled_steps:
                step_name = str(step or "").strip()
                if step_name in ablation:
                    ablation[step_name] = False

    return {
        "builder_flow_analysis_enabled": enabled,
        "builder_flow_analysis_ablation": ablation,
    }


if TYPE_CHECKING:
    from agents.llm_client import LLMConfig
    from agents.llm_router import LLMTopologyConfig
    from agents.model_config import RoleModelConfig
    from strategies.base import StrategyBase
    from strategies.indicators_mapping import StrategyIndicators
    from utils.parameters import ParameterSpec


@dataclass
class SidebarState:
    debug_enabled: bool
    symbol: str
    timeframe: str
    use_date_filter: bool
    start_date: date | None
    end_date: date | None
    available_tokens: list[str]
    available_timeframes: list[str]
    strategy_key: str
    strategy_name: str
    strategy_info: StrategyIndicators | None
    strategy_instance: StrategyBase | None
    params: dict[str, float]
    param_ranges: dict[str, dict[str, float]]
    param_specs: dict[str, ParameterSpec]
    active_indicators: list[str]
    optimization_mode: str
    max_combos: int
    n_workers: int
    # Stabilisation auto du marché (pré-filtre data) — 23/02/2026
    auto_stabilization_enabled: bool
    stabilization_method: str
    stabilization_window: int
    stabilization_volume_ratio_max: float
    stabilization_volatility_ratio_max: float
    stabilization_min_consecutive_bars: int
    stabilization_min_bars_keep: int
    # Multi-sweep config (20/01/2026 - support sélection multiple)
    symbols: list[str]  # Liste de symboles sélectionnés
    timeframes: list[str]  # Liste de timeframes sélectionnés
    strategy_keys: list[str]  # Liste de stratégies sélectionnées
    all_params: dict[str, dict[str, float]]  # Paramètres par stratégie
    all_param_ranges: dict[str, dict[str, dict[str, float]]]  # Ranges par stratégie
    all_param_specs: dict[str, dict[str, ParameterSpec]]  # Specs par stratégie
    # Optuna config
    use_optuna: bool
    optuna_n_trials: int
    optuna_sampler: str
    optuna_pruning: bool
    optuna_metric: str
    optuna_early_stop: int
    # LLM config
    llm_config: LLMConfig | None
    llm_model: str | None
    llm_use_multi_agent: bool
    role_model_config: RoleModelConfig | None
    llm_routing_mode: str
    llm_topology_config: LLMTopologyConfig | None
    llm_max_iterations: int
    llm_use_walk_forward: bool
    llm_unload_during_backtest: bool
    llm_compare_enabled: bool
    llm_compare_auto_run: bool
    llm_compare_strategies: list[str]
    llm_compare_tokens: list[str]
    llm_compare_timeframes: list[str]
    llm_compare_metric: str
    llm_compare_aggregate: str
    llm_compare_max_runs: int
    llm_compare_use_preset: bool
    llm_compare_generate_report: bool
    llm_inference_mode: str
    llm_inference_global_settings: dict[str, Any]
    llm_inference_model_profiles: dict[str, dict[str, Any]]
    initial_capital: float
    leverage: float
    leverage_enabled: bool  # Si False, leverage=1 forcé
    disabled_params: list[str]  # Paramètres désactivés (utilisent valeur par défaut)
    # Walk-Forward Analysis (WFA) — 10/02/2026
    use_walk_forward: bool
    wfa_n_folds: int
    wfa_train_ratio: float
    wfa_expanding: bool
    # Strategy Builder (10/02/2026)
    builder_objective: str
    builder_model_single_llm: str
    builder_max_iterations: int
    builder_target_sharpe: float
    builder_capital: float
    builder_ollama_host: str
    builder_preload_model: bool
    builder_keep_alive_minutes: int
    builder_unload_after_run: bool
    builder_auto_start_ollama: bool
    builder_auto_market_pick: bool
    builder_universe_mode: str
    # Mode autonome 24/24 (11/02/2026)
    builder_autonomous: bool
    builder_auto_pause: int  # Pause en secondes entre runs (0-120)
    builder_auto_use_llm: bool  # Compat: conserve l'état LLM-first côté reprise UI
    builder_execution_mode: str
    builder_flow_analysis_enabled: bool
    builder_flow_analysis_ablation: dict[str, bool]
    builder_use_parametric_catalog: bool  # Compat legacy, forcé à False dans l'UI Builder

    def __post_init__(self) -> None:
        if self.use_date_filter:
            assert self.start_date is not None
            assert self.end_date is not None
        assert self.max_combos >= 1
        assert self.n_workers >= 1
        assert self.stabilization_window >= 1
        assert self.stabilization_min_consecutive_bars >= 1
        assert self.stabilization_min_bars_keep >= 1
        assert self.llm_max_iterations >= 0
        assert self.initial_capital >= 0
        assert self.builder_keep_alive_minutes >= 0
        assert self.builder_execution_mode in BUILDER_EXECUTION_MODE_OPTIONS
        self.builder_universe_mode = normalize_universe_mode(
            self.builder_universe_mode,
            purpose="builder",
        )
        assert self.builder_universe_mode in BUILDER_UNIVERSE_MODE_OPTIONS
