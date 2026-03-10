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
from typing import TYPE_CHECKING, Dict, List, Optional

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
    builder_model: str
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
    builder_multi_llm_enabled: bool
    builder_multi_llm_profile: str
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
