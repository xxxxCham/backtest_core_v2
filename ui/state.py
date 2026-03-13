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

    overrides: Dict[str, List[str]] = {}
    if execution_mode == BUILDER_EXECUTION_MODE_EXPERT:
        raw_overrides = (
            source.get("builder_multi_llm_role_overrides", {})
            if isinstance(source, dict)
            else getattr(source, "builder_multi_llm_role_overrides", {})
        )
        overrides.update(
            normalize_builder_multi_llm_role_pool_overrides(raw_overrides)
        )

        if isinstance(source, dict):
            for role in BUILDER_MULTI_LLM_ACTIVE_ROLE_NAMES:
                widget_key = f"builder_multi_llm_role_override_select_{role}"
                if widget_key not in source:
                    continue
                widget_values = _normalize_model_pool(source.get(widget_key))
                if widget_values:
                    overrides[role] = widget_values
                else:
                    overrides.pop(role, None)
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
    # Mode autonome 24/24 (11/02/2026)
    builder_autonomous: bool
    builder_auto_pause: int       # Pause en secondes entre runs (0-120)
    builder_auto_use_llm: bool    # True = LLM génère l'objectif, False = templates
    builder_execution_mode: str
    builder_dual_lane_primary_model: str
    builder_dual_lane_critic_model: str
    builder_multi_llm_enabled: bool
    builder_multi_llm_profile: str
    builder_multi_llm_role_overrides: Dict[str, List[str]]
    # Catalogue paramétrique (19/02/2026)
    builder_use_parametric_catalog: bool  # True = utiliser les fiches paramétriques générées

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
