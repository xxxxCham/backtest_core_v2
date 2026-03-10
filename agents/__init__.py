"""
Backtest Core - Agents LLM Module
=================================

Système d'optimisation autonome par agents LLM.

Architecture:
- Orchestrator: State machine du workflow multi-agents
- 4 Agents specialises: Analyst, Strategist, Critic, Validator
- AutonomousStrategist: agent autonome capable de lancer des backtests
- BacktestExecutor: interface pour executer des backtests depuis les agents
- State Machine: transitions validees a chaque etape

Workflows:

1. Mode Orchestre (multi-agents, backtests si callback fourni):
    INIT -> ANALYZE -> PROPOSE -> CRITIQUE -> VALIDATE -> ITERATE -> ...
    Terminaison: APPROVED / REJECTED / FAILED

2. Mode Autonome (avec backtests réels):
    >>> strategist.optimize(executor, params, bounds) → OptimizationSession

Usage Mode Autonome (RECOMMANDÉ):
    >>> from agents import create_autonomous_optimizer
    >>> from agents.llm_client import LLMConfig, LLMProvider
    >>>
    >>> config = LLMConfig(provider=LLMProvider.OLLAMA, model="llama3.2")
    >>> strategist, executor = create_autonomous_optimizer(
    ...     llm_config=config,
    ...     backtest_fn=my_backtest_function,
    ...     strategy_name="ema_cross",
    ...     data=ohlcv_df,
    ... )
    >>>
    >>> session = strategist.optimize(
    ...     executor=executor,
    ...     initial_params={"fast": 10, "slow": 21},
    ...     param_bounds={"fast": (5, 20), "slow": (15, 50)},
    ...     max_iterations=10,
    ... )
    >>> print(f"Best: {session.best_result.sharpe_ratio}")

Usage Mode Orchestre (analysis-only si aucun callback de backtest):
    >>> from agents import Orchestrator, OrchestratorConfig
    >>>
    >>> config = OrchestratorConfig(
    ...     strategy_name="ema_cross",
    ...     data_path="data/BTCUSDT_1h.parquet",
    ...     on_backtest_needed=my_backtest_callback,
    ...     max_iterations=10,
    ... )
    >>> orchestrator = Orchestrator(config)
    >>> result = orchestrator.run()
"""

from __future__ import annotations

import logging
import os
import sys


def _configure_agents_logger() -> None:
    """
    Force un handler stdout dédié pour les logs des agents afin de contourner
    une configuration du logger racine trop restrictive.
    """
    if os.getenv("AGENTS_FORCE_STDOUT", "1") == "0":
        return

    level_name = os.getenv("AGENTS_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger("agents")

    # Éviter les handlers en double si déjà configuré
    if any(getattr(h, "_agents_force_stdout", False) for h in logger.handlers):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(
        "[AGENTS] %(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    handler._agents_force_stdout = True  # type: ignore[attr-defined]

    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


_configure_agents_logger()

from .analyst import AnalystAgent  # noqa: E402
from .autonomous_strategist import (  # noqa: E402
    AutonomousStrategist,
    IterationDecision,
    OptimizationSession,
    create_autonomous_optimizer,
)
from .backtest_executor import (  # noqa: E402
    BacktestExecutor,
    BacktestRequest,
    BacktestResult,
    ExperimentHistory,
)
from .base_agent import AgentContext, AgentResult, BaseAgent  # noqa: E402
from .critic import CriticAgent  # noqa: E402
from .integration import (  # noqa: E402
    create_optimizer_from_engine,
    create_orchestrator_with_backtest,
    get_strategy_param_bounds,
    get_strategy_param_space,
    quick_optimize,
    run_backtest_for_agent,
    run_walk_forward_for_agent,
)
from .llm_client import (  # noqa: E402
    LLMClient,
    LLMConfig,
    LLMProvider,
    LLMResponse,
    OllamaClient,
    OpenAIClient,
    create_llm_client,
)
from .model_config import (  # noqa: E402
    KNOWN_MODELS,
    ModelCategory,
    ModelInfo,
    RoleModelAssignment,
    RoleModelConfig,
    get_global_model_config,
    get_models_by_category,
    list_available_models,
    set_global_model_config,
)
from .ollama_manager import (  # noqa: E402
    # GPU Memory Management
    GPUMemoryManager,
    LLMMemoryState,
    cleanup_all_models,
    ensure_ollama_running,
    gpu_compute_context,
    is_ollama_available,
    list_ollama_models,
    prepare_for_llm_run,
    unload_model,
)
from .orchestrator import Orchestrator, OrchestratorConfig, OrchestratorResult  # noqa: E402
from .state_machine import (  # noqa: E402
    AgentState,
    StateMachine,
    StateTransition,
    ValidationResult,
)
from .strategist import StrategistAgent  # noqa: E402
from .strategy_builder import (  # noqa: E402
    BuilderIteration,
    BuilderSession,
    StrategyBuilder,
    validate_generated_code,
)
from .validator import ValidatorAgent  # noqa: E402

__all__ = [
    # State Machine
    "AgentState",
    "StateTransition",
    "StateMachine",
    "ValidationResult",
    # LLM
    "LLMClient",
    "LLMConfig",
    "LLMResponse",
    "LLMProvider",
    "OllamaClient",
    "OpenAIClient",
    "create_llm_client",
    # Agents
    "BaseAgent",
    "AgentContext",
    "AgentResult",
    "AnalystAgent",
    "StrategistAgent",
    "CriticAgent",
    "ValidatorAgent",
    # Autonomous Mode (RECOMMENDED)
    "AutonomousStrategist",
    "BacktestExecutor",
    "BacktestRequest",
    "BacktestResult",
    "ExperimentHistory",
    "IterationDecision",
    "OptimizationSession",
    "create_autonomous_optimizer",
    # Integration (FULL STACK)
    "run_backtest_for_agent",
    "run_walk_forward_for_agent",
    "create_optimizer_from_engine",
    "get_strategy_param_bounds",
    "get_strategy_param_space",
    "quick_optimize",
    "create_orchestrator_with_backtest",
    # Orchestrator (Static Mode)
    "Orchestrator",
    "OrchestratorConfig",
    "OrchestratorResult",
    # Ollama Manager
    "ensure_ollama_running",
    "unload_model",
    "cleanup_all_models",
    "list_ollama_models",
    "is_ollama_available",
    "prepare_for_llm_run",
    # GPU Memory Management
    "GPUMemoryManager",
    "LLMMemoryState",
    "gpu_compute_context",
    # Multi-Model Configuration
    "ModelCategory",
    "ModelInfo",
    "RoleModelAssignment",
    "RoleModelConfig",
    "KNOWN_MODELS",
    "list_available_models",
    "get_models_by_category",
    "get_global_model_config",
    "set_global_model_config",
    # Strategy Builder
    "StrategyBuilder",
    "BuilderSession",
    "BuilderIteration",
    "validate_generated_code",
]
