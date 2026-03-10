"""
Module-ID: backtest

Purpose: Moteur de backtesting (pipeline complet + optimisation + validation) avec API stable pour UI/agents.

Role in pipeline: core / orchestration

Key components: BacktestEngine, RunResult, OptunaOptimizer, SweepEngine, WalkForwardValidator, BackendFacade

Inputs: Données OHLCV, stratégies, paramètres, configurations

Outputs: Résultats de backtest structurés (trades, métriques, rapports)

Dependencies: Tous les modules backtest/*, strategies, indicators, data, utils, optionnel: optuna, tabulate

Conventions: Pipeline données→indicateurs→signaux→trades→métriques; erreurs structurées; réponses typées.

Read-if: Vous importez le moteur depuis UI/agents ou modifiez l'architecture.

Skip-if: Vous travaillez sur une seule strat/indicateur.
"""

from .engine import BacktestEngine, RunResult
from .walk_forward import (
    FoldResult,
    WalkForwardConfig,
    WalkForwardSummary,
    check_wfa_feasibility,
    run_walk_forward,
)
from .errors import (
    BackendInternalError,
    BacktestError,
    DataError,
    LLMUnavailableError,
    ParameterValidationError,
    StrategyNotFoundError,
    UserInputError,
)
from .facade import (
    BackendFacade,
    BackendResponse,
    BacktestRequest,
    ErrorCode,
    ErrorInfo,
    GridOptimizationRequest,
    GridOptimizationResponse,
    LLMOptimizationRequest,
    LLMOptimizationResponse,
    ResponseStatus,
    UIMetrics,
    UIPayload,
    get_facade,
    to_ui_payload,
)
from .performance import PerformanceCalculator, calculate_metrics
from .simulator import Trade, simulate_trades
from .storage import (
    ResultStorage,
    StoredResultMetadata,
    get_storage,
)

# Import conditionnel Optuna (peut ne pas être installé)
try:
    from .optuna_optimizer import (
        OPTUNA_AVAILABLE,
        MultiObjectiveResult,
        OptimizationResult,
        OptunaOptimizer,
        ParamSpec,
        quick_optimize,
        suggest_param_space,
    )
except ImportError:
    OPTUNA_AVAILABLE = False
    OptunaOptimizer = None
    ParamSpec = None
    OptimizationResult = None
    MultiObjectiveResult = None
    quick_optimize = None
    suggest_param_space = None

__all__ = [
    # Engine
    "BacktestEngine",
    "RunResult",
    # Walk-Forward
    "FoldResult",
    "WalkForwardConfig",
    "WalkForwardSummary",
    "check_wfa_feasibility",
    "run_walk_forward",
    # Performance
    "PerformanceCalculator",
    "calculate_metrics",
    # Simulator
    "simulate_trades",
    "Trade",
    # Errors
    "BacktestError",
    "UserInputError",
    "DataError",
    "BackendInternalError",
    "LLMUnavailableError",
    "StrategyNotFoundError",
    "ParameterValidationError",
    # Facade
    "BackendFacade",
    "BacktestRequest",
    "GridOptimizationRequest",
    "LLMOptimizationRequest",
    "BackendResponse",
    "GridOptimizationResponse",
    "LLMOptimizationResponse",
    "ResponseStatus",
    "ErrorCode",
    "UIMetrics",
    "UIPayload",
    "ErrorInfo",
    "get_facade",
    "to_ui_payload",
    # Storage
    "ResultStorage",
    "StoredResultMetadata",
    "get_storage",
    # Optuna (conditional)
    "OPTUNA_AVAILABLE",
    "OptunaOptimizer",
    "ParamSpec",
    "OptimizationResult",
    "MultiObjectiveResult",
    "quick_optimize",
    "suggest_param_space",
]
