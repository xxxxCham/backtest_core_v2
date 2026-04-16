"""
Module-ID: ui.state

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
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from config.market_selection import (
    UNIVERSE_MODE_CANONICAL,
    UNIVERSE_MODE_OPTIONS,
    normalize_universe_mode,
)

try:
    from core.llm_multi import get_profile_role_pools
    from core.llm_multi.roles import SIMPLE_MULTI_LLM_ACTIVE_ROLES
except ImportError:
    get_profile_role_pools = None

BUILDER_PRELOAD_MODEL_DEFAULT = True
BUILDER_KEEP_ALIVE_MINUTES_DEFAULT = 20
BUILDER_UNLOAD_AFTER_RUN_DEFAULT = True
BUILDER_AUTO_START_OLLAMA_DEFAULT = True
BUILDER_MULTI_LLM_ACTIVE_ROLE_NAMES = (
    "idea_llm",
    "builder_llm",
    "critic_llm",
    "risk_llm",
)
BUILDER_EXECUTION_MODE_MONO = "mono_single_llm"
BUILDER_EXECUTION_MODE_EXPERT = "expert_multi_role"
BUILDER_EXECUTION_MODE_DUAL_LANE = "dual_lane_multi_gpu"
BUILDER_EXECUTION_MODE_OPTIONS = (
    BUILDER_EXECUTION_MODE_MONO,
    BUILDER_EXECUTION_MODE_EXPERT,
    BUILDER_EXECUTION_MODE_DUAL_LANE,
)
BUILDER_OPTIMIZATION_MODE = "🏗️ Strategy Builder"
BUILDER_UNIVERSE_MODE_CANONICAL = UNIVERSE_MODE_CANONICAL
BUILDER_UNIVERSE_MODE_OPTIONS = UNIVERSE_MODE_OPTIONS
_BUILDER_LAUNCH_STATE_KEYS = (
    "_builder_auto_bootstrap_symbol",
    "_builder_auto_bootstrap_timeframe",
    "_builder_startup_symbol",
    "_builder_startup_timeframe",
    "_builder_tf_usage",
    "builder_launch_pending",
)
_BUILDER_RUNTIME_STATE_KEYS = (
    "builder_session",
    "builder_runtime_diagnostic",
    "builder_autonomous_history",
    "builder_autonomous_supervisor",
    "_builder_objective_input_sync",
    "_builder_multi_llm_profile_sync",
    "_builder_multi_llm_profile_saved_notice",
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
        _state_get(session_state, _UI_EXECUTION_PHASE_KEY, "")
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
        session_state
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


def _normalize_model_pool(value: Any) -> List[str]:
    candidates: List[str] = []
    if isinstance(value, str):
        normalized = str(value or "").strip()
        if normalized:
            candidates.append(normalized)
    elif isinstance(value, (list, tuple, set)):
        for raw_candidate in value:
            normalized = str(raw_candidate or "").strip()
            if normalized:
                candidates.append(normalized)
    seen: set[str] = set()
    unique: List[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def normalize_builder_multi_llm_role_pool_overrides(
    raw_value: Any,
) -> Dict[str, List[str]]:
    if not isinstance(raw_value, dict):
        return {}
    normalized: Dict[str, List[str]] = {}
    for role in BUILDER_MULTI_LLM_ACTIVE_ROLE_NAMES:
        pool = _normalize_model_pool(raw_value.get(role))
        if pool:
            normalized[role] = pool
    return normalized


def normalize_builder_execution_mode(raw_value: Any) -> str:
    value = str(raw_value or "").strip()
    if value in BUILDER_EXECUTION_MODE_OPTIONS:
        return value
    return ""


def resolve_builder_execution_preferences(source: Any) -> Dict[str, Any]:
    """Normalise le mode d'execution Builder depuis session_state ou SidebarState."""

    def _read(name: str, default: Any) -> Any:
        if isinstance(source, dict):
            widget_key_overrides = {
                "builder_execution_mode": "builder_execution_mode_select",
                "builder_multi_llm_enabled": "builder_multi_llm_enabled_toggle",
            }
            widget_key = widget_key_overrides.get(name)
            if widget_key and widget_key in source:
                return source.get(widget_key, default)
            return source.get(name, default)
        return getattr(source, name, default)

    mode = normalize_builder_execution_mode(_read("builder_execution_mode", ""))
    if not mode:
        multi_llm_enabled = _coerce_bool(_read("builder_multi_llm_enabled", False), False)
        routing_mode = str(
            _read("builder_llm_routing_mode", "single_endpoint") or "single_endpoint"
        ).strip()
        if multi_llm_enabled and routing_mode == "cooperative_multi_gpu":
            mode = BUILDER_EXECUTION_MODE_DUAL_LANE
        elif multi_llm_enabled:
            mode = BUILDER_EXECUTION_MODE_EXPERT
        else:
            mode = BUILDER_EXECUTION_MODE_MONO

    return {
        "builder_execution_mode": mode,
        "builder_multi_llm_enabled": mode != BUILDER_EXECUTION_MODE_MONO,
        "builder_llm_routing_mode": (
            "cooperative_multi_gpu"
            if mode == BUILDER_EXECUTION_MODE_DUAL_LANE
            else "single_endpoint"
        ),
    }


def resolve_builder_dual_lane_preferences(source: Any) -> Dict[str, str]:
    """Résout les deux modèles canonique du mode Dual Lane."""

    def _read(name: str, default: Any) -> Any:
        if isinstance(source, dict):
            widget_key_overrides = {
                "builder_dual_lane_primary_model": "builder_dual_lane_primary_model_select",
                "builder_dual_lane_critic_model": "builder_dual_lane_critic_model_select",
            }
            widget_key = widget_key_overrides.get(name)
            if widget_key and widget_key in source:
                return source.get(widget_key, default)
            return source.get(name, default)
        return getattr(source, name, default)

    raw_overrides = (
        source.get("builder_multi_llm_role_overrides", {})
        if isinstance(source, dict)
        else getattr(source, "builder_multi_llm_role_overrides", {})
    )
    overrides = normalize_builder_multi_llm_role_pool_overrides(raw_overrides)
    single_model_fallback = str(
        _read("builder_model_single_llm", "deepseek-r1:32b") or "deepseek-r1:32b"
    ).strip() or "deepseek-r1:32b"
    primary_fallback = str(
        (overrides.get("builder_llm") or [""])[0]
        or (overrides.get("idea_llm") or [""])[0]
        or single_model_fallback
    ).strip() or single_model_fallback
    critic_fallback = str(
        (overrides.get("critic_llm") or [""])[0]
        or (overrides.get("risk_llm") or [""])[0]
        or primary_fallback
    ).strip() or primary_fallback
    primary_model = str(
        _read("builder_dual_lane_primary_model", primary_fallback) or primary_fallback
    ).strip() or primary_fallback
    critic_model = str(
        _read("builder_dual_lane_critic_model", critic_fallback) or critic_fallback
    ).strip() or critic_fallback
    return {
        "builder_dual_lane_primary_model": primary_model,
        "builder_dual_lane_critic_model": critic_model,
    }


def resolve_builder_runtime_preferences(source: Any) -> Dict[str, Any]:
    """Normalise les préférences runtime Builder depuis session_state ou SidebarState."""

    def _read(name: str, default: Any) -> Any:
        if isinstance(source, dict):
            widget_key_overrides = {
                "builder_auto_start_ollama": "builder_auto_start_ollama_toggle",
                "builder_preload_model": "builder_preload_model_toggle",
                "builder_keep_alive_minutes": "builder_keep_alive_minutes_input",
                "builder_unload_after_run": "builder_unload_after_run_toggle",
            }
            widget_key = widget_key_overrides.get(name)
            if widget_key and widget_key in source:
                return source.get(widget_key, default)
            return source.get(name, default)
        return getattr(source, name, default)

    return {
        "builder_auto_start_ollama": _coerce_bool(
            _read("builder_auto_start_ollama", BUILDER_AUTO_START_OLLAMA_DEFAULT),
            BUILDER_AUTO_START_OLLAMA_DEFAULT,
        ),
        "builder_preload_model": _coerce_bool(
            _read("builder_preload_model", BUILDER_PRELOAD_MODEL_DEFAULT),
            BUILDER_PRELOAD_MODEL_DEFAULT,
        ),
        "builder_keep_alive_minutes": _coerce_non_negative_int(
            _read("builder_keep_alive_minutes", BUILDER_KEEP_ALIVE_MINUTES_DEFAULT),
            BUILDER_KEEP_ALIVE_MINUTES_DEFAULT,
        ),
        "builder_unload_after_run": _coerce_bool(
            _read("builder_unload_after_run", BUILDER_UNLOAD_AFTER_RUN_DEFAULT),
            BUILDER_UNLOAD_AFTER_RUN_DEFAULT,
        ),
    }


def _default_builder_flow_analysis_ablation() -> Dict[str, bool]:
    try:
        from agents.pipeline_instrumentation import AblationController

        return {
            step: True
            for step in sorted(AblationController.ABLATABLE_STEPS)
        }
    except Exception:
        return {}


def _normalize_builder_flow_analysis_ablation(
    raw_value: Any,
) -> Dict[str, bool]:
    normalized = _default_builder_flow_analysis_ablation()
    if not isinstance(raw_value, dict):
        return normalized
    for step in list(normalized.keys()):
        if step in raw_value:
            normalized[step] = _coerce_bool(raw_value.get(step), normalized[step])
    return normalized


def resolve_builder_flow_analysis_preferences(source: Any) -> Dict[str, Any]:
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

    enabled = _coerce_bool(_read("builder_flow_analysis_enabled", False), False)
    ablation = _normalize_builder_flow_analysis_ablation(
        _read("builder_flow_analysis_ablation", {})
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


def resolve_builder_multi_llm_preferences(source: Any) -> Dict[str, Any]:
    """Normalise le pilotage multi-LLM Builder depuis session_state ou SidebarState."""
    execution_preferences = resolve_builder_execution_preferences(source)
    execution_mode = execution_preferences["builder_execution_mode"]

    def _read(name: str, default: Any) -> Any:
        if isinstance(source, dict):
            widget_key_overrides = {
                "builder_multi_llm_enabled": "builder_multi_llm_enabled_toggle",
                "builder_multi_llm_profile": "builder_multi_llm_profile_select",
            }
            widget_key = widget_key_overrides.get(name)
            if widget_key and widget_key in source:
                return source.get(widget_key, default)
            return source.get(name, default)
        return getattr(source, name, default)

    enabled = bool(execution_preferences["builder_multi_llm_enabled"])
    profile_name = str(
        _read("builder_multi_llm_profile", "24GB_balanced") or "24GB_balanced"
    ).strip() or "24GB_balanced"
    applied_profile = ""
    if isinstance(source, dict):
        applied_profile = str(
            source.get("_builder_multi_llm_applied_profile", "") or ""
        ).strip()

    overrides: Dict[str, List[str]] = {}
    if execution_mode == BUILDER_EXECUTION_MODE_EXPERT:
        # Vérifier si le profil a changé
        profile_changed = bool(applied_profile) and applied_profile != profile_name

        if profile_changed:
            # Changement de profil -> charger les pools du nouveau profil, ignorer les anciens overrides
            if callable(get_profile_role_pools):
                try:
                    profile_pools = get_profile_role_pools(profile_name)
                    overrides.update(normalize_builder_multi_llm_role_pool_overrides(profile_pools))
                except Exception:
                    pass
        else:
            # Même profil -> lire les sélections manuelles actuelles des widgets
            manual_overrides: Dict[str, List[str]] = {}
            for role in SIMPLE_MULTI_LLM_ACTIVE_ROLES:
                widget_key = f"builder_multi_llm_role_override_select_{role}"
                if isinstance(source, dict) and widget_key in source:
                    widget_value = source.get(widget_key, [])
                    if widget_value and (isinstance(widget_value, list) and len(widget_value) > 0):
                        manual_overrides[role] = widget_value

            # Si sélections manuelles existent, les utiliser
            if manual_overrides:
                overrides.update(normalize_builder_multi_llm_role_pool_overrides(manual_overrides))
            else:
                # Sinon, utiliser builder_multi_llm_role_overrides (source de vérité par défaut)
                raw_overrides = (
                    source.get("builder_multi_llm_role_overrides", {})
                    if isinstance(source, dict)
                    else getattr(source, "builder_multi_llm_role_overrides", {})
                )
                overrides.update(normalize_builder_multi_llm_role_pool_overrides(raw_overrides))

        # Si toujours vide, initialiser avec les pools du profil.
        if not overrides and callable(get_profile_role_pools):
            try:
                overrides.update(
                    normalize_builder_multi_llm_role_pool_overrides(
                        get_profile_role_pools(profile_name)
                    )
                )
            except Exception:
                pass
    elif execution_mode == BUILDER_EXECUTION_MODE_DUAL_LANE:
        dual_lane_preferences = resolve_builder_dual_lane_preferences(source)
        primary_model = str(
            dual_lane_preferences["builder_dual_lane_primary_model"] or ""
        ).strip()
        critic_model = str(
            dual_lane_preferences["builder_dual_lane_critic_model"] or ""
        ).strip()
        if primary_model:
            overrides["idea_llm"] = [primary_model]
            overrides["builder_llm"] = [primary_model]
        if critic_model:
            overrides["critic_llm"] = [critic_model]
            overrides["risk_llm"] = [critic_model]

    return {
        "builder_execution_mode": execution_mode,
        "builder_multi_llm_enabled": enabled,
        "builder_multi_llm_profile": profile_name,
        "builder_multi_llm_role_overrides": overrides,
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
    start_date: Optional[date]
    end_date: Optional[date]
    available_tokens: List[str]
    available_timeframes: List[str]
    strategy_key: str
    strategy_name: str
    strategy_info: Optional["StrategyIndicators"]
    strategy_instance: Optional["StrategyBase"]
    params: Dict[str, float]
    param_ranges: Dict[str, Dict[str, float]]
    param_specs: Dict[str, "ParameterSpec"]
    active_indicators: List[str]
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
    symbols: List[str]  # Liste de symboles sélectionnés
    timeframes: List[str]  # Liste de timeframes sélectionnés
    strategy_keys: List[str]  # Liste de stratégies sélectionnées
    all_params: Dict[str, Dict[str, float]]  # Paramètres par stratégie
    all_param_ranges: Dict[str, Dict[str, Dict[str, float]]]  # Ranges par stratégie
    all_param_specs: Dict[str, Dict[str, "ParameterSpec"]]  # Specs par stratégie
    # Optuna config
    use_optuna: bool
    optuna_n_trials: int
    optuna_sampler: str
    optuna_pruning: bool
    optuna_metric: str
    optuna_early_stop: int
    # LLM config
    llm_config: Optional["LLMConfig"]
    llm_model: Optional[str]
    llm_use_multi_agent: bool
    role_model_config: Optional["RoleModelConfig"]
    llm_routing_mode: str
    llm_topology_config: Optional["LLMTopologyConfig"]
    llm_max_iterations: int
    llm_use_walk_forward: bool
    llm_unload_during_backtest: bool
    llm_compare_enabled: bool
    llm_compare_auto_run: bool
    llm_compare_strategies: List[str]
    llm_compare_tokens: List[str]
    llm_compare_timeframes: List[str]
    llm_compare_metric: str
    llm_compare_aggregate: str
    llm_compare_max_runs: int
    llm_compare_use_preset: bool
    llm_compare_generate_report: bool
    llm_inference_mode: str
    llm_inference_global_settings: Dict[str, Any]
    llm_inference_model_profiles: Dict[str, Dict[str, Any]]
    initial_capital: float
    leverage: float
    leverage_enabled: bool  # Si False, leverage=1 forcé
    disabled_params: List[str]  # Paramètres désactivés (utilisent valeur par défaut)
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
    builder_auto_pause: int       # Pause en secondes entre runs (0-120)
    builder_auto_use_llm: bool    # Compat: conserve l'état LLM-first côté reprise UI
    builder_execution_mode: str
    builder_dual_lane_primary_model: str
    builder_dual_lane_critic_model: str
    builder_multi_llm_enabled: bool
    builder_multi_llm_profile: str
    builder_multi_llm_role_overrides: Dict[str, List[str]]
    builder_flow_analysis_enabled: bool
    builder_flow_analysis_ablation: Dict[str, bool]
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
