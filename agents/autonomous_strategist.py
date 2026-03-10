"""
Module-ID: agents.autonomous_strategist

Purpose: Optimiseur autonome piloté par LLM qui itère propose → backtest → analyse → décide.

Role in pipeline: orchestration

Key components: AutonomousStrategist, OptimizationSession, IterationDecision, create_autonomous_optimizer

Inputs: LLMClient/LLMConfig, BacktestExecutor/backtest_fn, DataFrame OHLCV, initial_params/param_bounds

Outputs: OptimizationSession (best_result/all_results/decisions), historique de BacktestResult

Dependencies: agents.backtest_executor, agents.base_agent, agents.llm_client, agents.ollama_manager, utils.parameters

Conventions: target_metric="sharpe_ratio"; max_time_seconds en secondes; stop si next_parameters vide; LLM déchargé GPU durant backtests.

Read-if: Vous modifiez/debuggez la boucle d'optimisation autonome ou son intégration d'exécution.

Skip-if: Vous utilisez uniquement le mode orchestré sans exécution de backtests.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from strategies.base import get_strategy_overview
from utils.observability import get_obs_logger
from utils.parameters import ParameterSpec, RangeProposal, compute_search_space_stats

from .backtest_executor import (
    BacktestExecutor,
    BacktestRequest,
    BacktestResult,
)
from .base_agent import AgentContext, AgentResult, AgentRole, BaseAgent
from .indicator_context import build_indicator_context
from .llm_client import LLMClient, LLMConfig
from .ollama_manager import GPUMemoryManager

logger = get_obs_logger(__name__)


@dataclass
class IterationDecision:
    """Décision du LLM après analyse d'un résultat."""

    action: str  # "continue", "accept", "stop", "change_direction", "sweep"
    confidence: float  # 0-1

    # Prochaine action si "continue"
    next_hypothesis: str = ""
    next_parameters: Dict[str, Any] = field(default_factory=dict)

    # Raison
    reasoning: str = ""

    # Insights accumulés
    insights: List[str] = field(default_factory=list)

    # Champs spécifiques au sweep
    ranges: Optional[Dict[str, Dict[str, float]]] = None
    rationale: str = ""  # Explication du sweep (différent de reasoning)
    optimize_for: str = "sharpe_ratio"
    max_combinations: int = 100


@dataclass
class OptimizationSession:
    """Session d'optimisation complète."""

    # Configuration
    strategy_name: str
    initial_params: Dict[str, Any]
    target_metric: str = "sharpe_ratio"

    # Contraintes
    max_iterations: int = 20
    min_improvement_threshold: float = 0.01
    max_time_seconds: float = 3600.0  # 1 heure max

    # État
    current_iteration: int = 0
    start_time: datetime = field(default_factory=datetime.now)

    # Résultats
    best_result: Optional[BacktestResult] = None
    all_results: List[BacktestResult] = field(default_factory=list)
    decisions: List[IterationDecision] = field(default_factory=list)

    # Status final
    final_status: str = ""  # "success", "max_iterations", "timeout", "no_improvement"
    final_reasoning: str = ""

    # Contexte indicateurs (calculé une fois par run)
    strategy_indicators_context: str = ""
    readonly_indicators_context: str = ""
    indicator_context_warnings: List[str] = field(default_factory=list)
    indicator_context_cached: bool = False
    comparison_context: Optional[Dict[str, Any]] = None


def _param_bounds_to_specs(
    param_bounds: Dict[str, tuple],
    defaults: Dict[str, Any]
) -> List[ParameterSpec]:
    """
    Convertit param_bounds en List[ParameterSpec] pour run_llm_sweep().

    Args:
        param_bounds: {param: (min, max) ou (min, max, step)}
        defaults: {param: default_value}

    Returns:
        List de ParameterSpec
    """
    specs = []
    for param_name, bound_spec in param_bounds.items():
        if isinstance(bound_spec, (tuple, list)) and len(bound_spec) >= 2:
            min_val = float(bound_spec[0])
            max_val = float(bound_spec[1])
            step = float(bound_spec[2]) if len(bound_spec) >= 3 else 1.0
        else:
            min_val = max_val = float(bound_spec)
            step = 1.0

        # Default: moyenne ou depuis defaults dict
        default = defaults.get(param_name, (min_val + max_val) / 2)

        # Détecter type: int si tous les bounds sont int
        is_int = all(isinstance(bound_spec[i], int) for i in range(min(2, len(bound_spec))))
        param_type = "int" if is_int else "float"

        specs.append(ParameterSpec(
            name=param_name,
            min_val=min_val,
            max_val=max_val,
            default=default,
            step=step,
            param_type=param_type
        ))

    return specs


class AutonomousStrategist(BaseAgent):
    """
    Agent Strategist Autonome capable de lancer des backtests.

    Workflow:
    1. Analyser la configuration initiale
    2. Formuler une hypothèse d'amélioration
    3. Lancer un backtest
    4. Analyser les résultats
    5. Décider: continuer, accepter, ou changer de direction
    6. Répéter jusqu'à convergence ou limite

    GPU Memory Optimization:
    - Le LLM est déchargé du GPU avant chaque backtest
    - La VRAM est ainsi disponible pour les calculs NumPy
    - Le LLM est rechargé après le backtest pour l'analyse

    Example:
        >>> strategist = AutonomousStrategist(llm_client)
        >>> session = strategist.optimize(
        ...     executor=executor,
        ...     initial_params={"fast": 10, "slow": 21},
        ...     param_bounds={"fast": (5, 20), "slow": (15, 50)},
        ...     max_iterations=10
        ... )
        >>> print(f"Best Sharpe: {session.best_result.sharpe_ratio}")
    """

    @property
    def role(self) -> AgentRole:
        return AgentRole.STRATEGIST

    @property
    def system_prompt(self) -> str:
        return """You are an autonomous trading strategy optimizer with the ability to run backtests.

Your process:
1. ANALYZE current results and history
2. FORMULATE a hypothesis about what might improve performance
3. PROPOSE specific parameters to test OR request a grid search over ranges
4. After seeing results, DECIDE whether to continue, accept, or change direction

Key principles:
- Each experiment should test ONE clear hypothesis
- Learn from failures - don't repeat similar mistakes
- Balance exploration (trying new things) vs exploitation (refining what works)
- Watch for overfitting - prefer robust solutions over peak performance
- Consider parameter interactions (e.g., fast/slow periods should maintain ratio)
- Use grid search ("sweep") when you need to explore parameter correlations systematically
- Use "Strategy Indicators (modifiable)" for parameter changes; "Context Indicators (read-only)" are informational only

You will receive experiment history and must respond with a decision.

Response format (JSON):
{
    "action": "continue|accept|stop|change_direction|sweep",
    "confidence": 0.0 to 1.0,
    "reasoning": "Why this decision",
    "next_hypothesis": "What you want to test next (if continuing)",
    "next_parameters": {"param": value},
    "insights": ["insight1", "insight2"]
}

🚨 CRITICAL REQUIREMENT FOR "continue" / "change_direction":
- You MUST provide ALL parameters in "next_parameters" field
- DO NOT return empty {} or null for "next_parameters"
- Each parameter must have a concrete numeric value
- If you cannot decide on parameters, use action="stop" instead

✅ VALID EXAMPLE (continue with all parameters):
{
    "action": "continue",
    "confidence": 0.75,
    "next_hypothesis": "Testing slow=25 to capture longer trends",
    "next_parameters": {
        "fast": 10,
        "slow": 25,
        "k_sl": 1.5,
        "k_tp": 3.0
    },
    "reasoning": "Slow period correlates with Sharpe improvement in range 20-25",
    "insights": ["Higher slow periods reduce false signals", "Maintain fast/slow ratio ~1:2.5"]
}

❌ INVALID (will cause fallback to defaults):
{
    "action": "continue",
    "next_parameters": {}  # ← EMPTY, DO NOT DO THIS
}

❌ INVALID (missing parameters):
{
    "action": "continue",
    "next_parameters": {"fast": 10}  # ← INCOMPLETE, must include ALL params
}

🔍 GRID SEARCH ("sweep") - Use when exploring parameter interactions:

✅ VALID EXAMPLE (sweep):
{
    "action": "sweep",
    "confidence": 0.85,
    "ranges": {
        "bb_period": {"min": 20, "max": 25, "step": 1},
        "bb_std": {"min": 2.0, "max": 2.5, "step": 0.1}
    },
    "rationale": "Explore bb_period/bb_std correlation systematically",
    "optimize_for": "sharpe_ratio",
    "max_combinations": 50,
    "reasoning": "Grid search more efficient than sequential testing for parameter interactions",
    "insights": ["bb_period and bb_std appear correlated", "Need exhaustive search in narrow range"]
}

🚨 CRITICAL REQUIREMENTS FOR "sweep":
- You MUST provide "ranges" dict with format: {"param": {"min": x, "max": y, "step": z}}
- Each range must have min, max, and step
- "rationale" field is REQUIRED (explains why grid search is needed)
- "optimize_for" is optional (default: "sharpe_ratio")
- "max_combinations" is optional (default: 100, max: 200)
- Ranges will be clamped to parameter bounds automatically
- Grid search runs in parallel and returns top 10 configs + summary
- Use sweep when testing 2-3 parameter interactions, not for single params

When to use "sweep":
- Testing parameter correlations (e.g., fast/slow ratio, bb_period/bb_std)
- Exploring narrow ranges exhaustively after finding promising region
- When sequential testing is too slow for parameter interactions
- NOT for initial exploration - use "continue" first to narrow down ranges

Actions:
- "continue": Run another backtest with next_parameters (MUST provide all params)
- "accept": Accept current best as final solution
- "stop": Stop due to diminishing returns or constraints
- "change_direction": Abandon current approach, try something different (MUST provide all params)
- "sweep": Request grid search over parameter ranges (MUST provide ranges dict with min/max/step)"""

    def __init__(
        self,
        llm_client: LLMClient,
        verbose: bool = False,
        on_progress: Optional[Callable[[int, BacktestResult], None]] = None,
        unload_llm_during_backtest: Optional[bool] = None,
        comparison_context: Optional[Dict[str, Any]] = None,
        orchestration_logger: Optional[Any] = None,
    ):
        """
        Initialise le strategist autonome.

        Args:
            llm_client: Client LLM
            verbose: Afficher les logs détaillés
            on_progress: Callback appelé après chaque itération
            unload_llm_during_backtest: Si True, décharge le LLM du GPU pendant
                les calculs de backtest. Si None, utilise UNLOAD_LLM_DURING_BACKTEST
                env var (default: False pour CPU-only compatibility)
            comparison_context: Contexte multi-sweep pour enrichir les décisions LLM
            orchestration_logger: Logger pour enregistrer les actions d'orchestration
        """
        import os
        super().__init__(llm_client)
        self.verbose = verbose
        self.on_progress = on_progress
        self.orchestration_logger = orchestration_logger
        self.comparison_context = comparison_context

        # Lire depuis env var si non spécifié (default False pour CPU-only)
        if unload_llm_during_backtest is None:
            env_val = os.getenv('UNLOAD_LLM_DURING_BACKTEST', 'False')
            self.unload_llm_during_backtest = env_val.lower() in ('true', '1', 'yes')
        else:
            self.unload_llm_during_backtest = unload_llm_during_backtest

        # GPU Memory Manager - initialisé avec le modèle du client
        self._gpu_manager: Optional[GPUMemoryManager] = None
        self._conversation_context: List[dict] = []

    def _get_model_name(self) -> str:
        """Récupère le nom du modèle depuis le client LLM."""
        if hasattr(self.llm, 'config'):
            return self.llm.config.model
        return "unknown"

    def _ensure_gpu_manager(self) -> GPUMemoryManager:
        """Crée ou retourne le GPU manager."""
        if self._gpu_manager is None:
            self._gpu_manager = GPUMemoryManager(
                model_name=self._get_model_name(),
                verbose=self.verbose,
            )
        return self._gpu_manager

    def _run_backtest_with_gpu_optimization(
        self,
        executor: BacktestExecutor,
        request: BacktestRequest,
    ) -> BacktestResult:
        """
        Exécute un backtest avec optimisation mémoire GPU.

        1. Décharge le LLM du GPU
        2. Exécute le backtest (GPU libre)
        3. Recharge le LLM

        Args:
            executor: BacktestExecutor
            request: Requête de backtest

        Returns:
            Résultat du backtest
        """
        if not self.unload_llm_during_backtest:
            # Mode sans optimisation GPU
            return executor.run(request)

        manager = self._ensure_gpu_manager()

        # Décharger le LLM → GPU libre pour calculs
        state = manager.unload(self._conversation_context)

        try:
            # Calculs GPU intensifs (NumPy)
            result = executor.run(request)
        finally:
            # Recharger le LLM (toujours, même en cas d'erreur)
            manager.reload(state)

        # Stats pour debug
        if self.verbose:
            stats = manager.get_stats()
            if stats.get("was_loaded"):
                logger.debug(
                    f"⏱️ GPU swap: unload={stats['unload_time_ms']:.0f}ms, "
                    f"reload={stats['reload_time_ms']:.0f}ms"
                )

        return result

    def optimize(
        self,
        executor: BacktestExecutor,
        initial_params: Dict[str, Any],
        param_bounds: Dict[str, tuple],
        max_iterations: int = 20,
        target_metric: str = "sharpe_ratio",
        min_sharpe: float = 0.5,
        max_drawdown: float = 0.30,
        check_pause_callback: Optional[callable] = None,
    ) -> OptimizationSession:
        """
        Lance une session d'optimisation autonome.

        Args:
            executor: BacktestExecutor configuré
            initial_params: Paramètres de départ
            param_bounds: {param_name: (min, max)} pour chaque paramètre
            max_iterations: Maximum d'itérations
            target_metric: Métrique à optimiser
            min_sharpe: Sharpe minimum acceptable
            max_drawdown: Drawdown maximum acceptable
            check_pause_callback: Callback appelé à chaque itération qui retourne (is_paused, should_stop)

        Returns:
            OptimizationSession avec tous les résultats
        """
        session = OptimizationSession(
            strategy_name=executor.strategy_name,
            initial_params=initial_params,
            target_metric=target_metric,
            max_iterations=max_iterations,
            comparison_context=self.comparison_context,
        )

        # Tracker de ranges pour éviter boucles infinies
        from utils.session_ranges_tracker import SessionRangesTracker
        ranges_tracker = SessionRangesTracker(
            session_id=f"{session.strategy_name}_{session.start_time.strftime('%Y%m%d_%H%M%S')}"
        )

        max_iter_label = "∞" if max_iterations <= 0 else str(max_iterations)
        logger.info(
            f"Démarrage optimisation: {session.strategy_name} | "
            f"max_iter={max_iter_label}"
        )

        # Logger d'orchestration: début de l'optimisation
        if self.orchestration_logger:
            self.orchestration_logger.log_analysis_start(
                agent="AutonomousStrategist",
                details={
                    "strategy": session.strategy_name,
                    "initial_params": initial_params,
                }
            )

        # 1. Backtest initial
        initial_request = BacktestRequest(
            requested_by=self.role.value,
            hypothesis="Baseline: testing initial configuration",
            parameters=initial_params,
        )

        # Logger: lancement du backtest baseline
        if self.orchestration_logger:
            self.orchestration_logger.log_backtest_launch(
                agent="AutonomousStrategist",
                params=initial_params,
                combination_id=0,
                total_combinations=max_iterations,
            )

        baseline_result = self._run_backtest_with_gpu_optimization(executor, initial_request)
        session.all_results.append(baseline_result)
        session.best_result = baseline_result

        # Logger: résultat du backtest baseline
        if self.orchestration_logger:
            self.orchestration_logger.log_backtest_complete(
                agent="AutonomousStrategist",
                params=initial_params,
                results={
                    "pnl": baseline_result.total_return,
                    "sharpe": baseline_result.sharpe_ratio,
                    "return": baseline_result.total_return,
                },
                combination_id=0,
            )

        if self.on_progress:
            self.on_progress(0, baseline_result)

        logger.info(
            f"Baseline: Sharpe={baseline_result.sharpe_ratio:.3f}, "
            f"Return={baseline_result.total_return:.2%}"
        )

        # Contexte indicateurs (une seule fois par run)
        try:
            indicator_ctx = build_indicator_context(
                df=executor.data,
                strategy_name=session.strategy_name,
                params=initial_params,
            )
            session.strategy_indicators_context = indicator_ctx.get("strategy", "")
            session.readonly_indicators_context = indicator_ctx.get("read_only", "")
            session.indicator_context_warnings = indicator_ctx.get("warnings", [])
            session.indicator_context_cached = True
        except Exception as exc:
            logger.warning(f"Contexte indicateurs indisponible: {exc}")
            session.strategy_indicators_context = ""
            session.readonly_indicators_context = ""
            session.indicator_context_warnings = []
            session.indicator_context_cached = True

        if self.orchestration_logger and (
            session.strategy_indicators_context
            or session.readonly_indicators_context
            or session.indicator_context_warnings
        ):
            payload = {
                "event_type": "indicator_context",
                "timestamp": datetime.now().isoformat(),
                "agent": "AutonomousStrategist",
                "session_id": f"{session.strategy_name}_{session.start_time.strftime('%Y%m%d_%H%M%S')}",
                "iteration": session.current_iteration,
                "strategy_indicators_context": session.strategy_indicators_context,
                "readonly_indicators_context": session.readonly_indicators_context,
                "warnings": session.indicator_context_warnings,
            }
            try:
                if hasattr(self.orchestration_logger, "log"):
                    self.orchestration_logger.log("indicator_context", payload)
                elif hasattr(self.orchestration_logger, "add_event"):
                    self.orchestration_logger.add_event("indicator_context", payload)
                elif hasattr(self.orchestration_logger, "append"):
                    self.orchestration_logger.append(payload)
            except Exception:
                pass

        # 2. Boucle d'itération avec budget de combinaisons
        total_combinations_tested = 1  # Baseline = 1 combo
        sweeps_performed = 0
        max_sweeps_per_session = 3  # Limite de sweeps pour éviter l'abus

        if max_iterations <= 0:
            iteration_iter = itertools.count(1)
        else:
            iteration_iter = range(1, max_iterations + 1)

        for iteration in iteration_iter:
            session.current_iteration = iteration

            # Vérifier le budget de combinaisons testées
            if max_iterations > 0 and total_combinations_tested >= max_iterations:
                session.final_status = "max_iterations"
                session.final_reasoning = (
                    f"Budget épuisé: {total_combinations_tested} combinaisons testées "
                    f"(limite: {max_iterations})"
                )
                logger.warning(
                    f"⚠️ Budget épuisé: {total_combinations_tested} combos testées "
                    f"dont {sweeps_performed} sweeps"
                )
                break

            # Vérifier pause/stop si callback fourni
            if check_pause_callback:
                import time
                is_paused, should_stop = check_pause_callback()

                # Si stop demandé, sortir immédiatement
                if should_stop:
                    session.final_reasoning = "Arrêt demandé par l'utilisateur"
                    logger.info("Arrêt demandé - Fin de l'optimisation")
                    break

                # Si pause demandée, attendre
                while is_paused:
                    time.sleep(0.5)
                    is_paused, should_stop = check_pause_callback()
                    if should_stop:
                        session.final_reasoning = "Arrêt demandé par l'utilisateur"
                        logger.info("Arrêt demandé pendant la pause - Fin de l'optimisation")
                        break

                # Sortir de la boucle externe si stop pendant pause
                if should_stop:
                    break

            # Logger: nouvelle itération
            if self.orchestration_logger:
                self.orchestration_logger.next_iteration()

            # Générer le contexte pour le LLM
            context = self._build_iteration_context(
                executor, session, param_bounds, min_sharpe, max_drawdown
            )

            # Demander une décision au LLM
            decision = self._get_llm_decision(context, session)

            # VALIDATION STRICTE : Forcer STOP si next_parameters vide pour continue/change_direction
            if decision.action in ("continue", "change_direction"):
                if not decision.next_parameters or len(decision.next_parameters) == 0:
                    optim_id = f"{session.strategy_name}_{session.start_time.strftime('%Y%m%d_%H%M%S')}"
                    logger.error(
                        f"LLM_INVALID_DECISION optim_id={optim_id} iteration={session.current_iteration} "
                        f"action_original={decision.action} action_forced=stop "
                        f"reason=next_parameters_empty_or_missing"
                    )
                    # Forcer STOP au lieu d'utiliser defaults silencieusement
                    original_action = decision.action
                    decision.action = "stop"
                    decision.reasoning = (
                        f"LLM chose '{original_action}' but provided no parameters. "
                        f"Stopping to avoid using defaults silently. "
                        f"Original reasoning: {decision.reasoning}"
                    )

            session.decisions.append(decision)

            # Logger: décision prise
            if self.orchestration_logger:
                action_type = decision.action if decision.action in ("continue", "stop", "change_approach") else "continue"
                self.orchestration_logger.log_decision(
                    agent="AutonomousStrategist",
                    decision_type=action_type,
                    reason=decision.reasoning,
                    details={"next_params": decision.next_parameters, "confidence": decision.confidence},
                )

            # Logging détaillé de la décision (toujours actif pour actions critiques)
            if decision.action in ("stop", "accept"):
                logger.warning(
                    f"🤖 Iteration {iteration}/{max_iter_label}: ACTION CRITIQUE = '{decision.action.upper()}' | "
                    f"Confidence={decision.confidence:.2f} | Reasoning: {decision.reasoning}"
                )
            elif self.verbose:
                logger.info(
                    f"🤖 Iteration {iteration}/{max_iter_label}: action='{decision.action}' | "
                    f"confidence={decision.confidence:.2f} | reasoning={decision.reasoning[:80]}..."
                )
            else:
                # Log minimaliste pour continue/change_direction
                logger.info(f"Iteration {iteration}: {decision.action}")

            # Traiter la décision
            if decision.action == "accept":
                session.final_status = "success"
                session.final_reasoning = decision.reasoning
                logger.info(f"Optimisation acceptée: {decision.reasoning}")
                break

            elif decision.action == "stop":
                session.final_status = "no_improvement"
                session.final_reasoning = decision.reasoning
                logger.info(f"Arrêt: {decision.reasoning}")
                break

            elif decision.action == "sweep":
                # Vérifier la limite de sweeps
                if sweeps_performed >= max_sweeps_per_session:
                    logger.warning(
                        f"⚠️ Limite de sweeps atteinte ({max_sweeps_per_session}). "
                        f"Sweep request ignoré, continue avec proposals normales."
                    )
                    # Forcer l'action à "stop" pour éviter boucle infinie
                    decision.action = "stop"
                    decision.reasoning = (
                        f"Sweep limit reached ({sweeps_performed}/{max_sweeps_per_session}). "
                        f"Original rationale: {decision.rationale}"
                    )
                    session.final_status = "sweep_limit_reached"
                    session.final_reasoning = decision.reasoning
                    break

                # Grid search demandé par le LLM
                logger.warning(
                    f"🔍 Iteration {iteration}/{max_iter_label}: SWEEP REQUEST #{sweeps_performed + 1} | "
                    f"Ranges={list(decision.ranges.keys()) if decision.ranges else []} | "
                    f"Rationale: {decision.rationale[:80]}"
                )

                # Logger: lancement du sweep
                if self.orchestration_logger:
                    self.orchestration_logger.log_decision(
                        agent="AutonomousStrategist",
                        decision_type="sweep",
                        reason=decision.rationale,
                        details={
                            "ranges": decision.ranges,
                            "optimize_for": decision.optimize_for,
                            "max_combinations": decision.max_combinations,
                        },
                    )

                # Vérifier si ces ranges ont déjà été testées
                if ranges_tracker.was_tested(decision.ranges):
                    logger.warning(
                        f"⚠️ Ranges déjà testées dans cette session! | "
                        f"Params={list(decision.ranges.keys())} | "
                        f"Forcing diversification..."
                    )
                    # Forcer à stop pour éviter boucle infinie
                    decision.action = "stop"
                    decision.reasoning = (
                        f"Ranges already tested. Need different ranges. "
                        f"Original rationale: {decision.rationale}"
                    )
                    session.final_status = "ranges_already_tested"
                    session.final_reasoning = decision.reasoning
                    break

                try:
                    # Créer RangeProposal
                    range_proposal = RangeProposal(
                        ranges=decision.ranges,
                        rationale=decision.rationale,
                        optimize_for=decision.optimize_for,
                        max_combinations=decision.max_combinations,
                    )

                    # Convertir param_bounds en param_specs
                    param_specs = _param_bounds_to_specs(param_bounds, initial_params)

                    # Exécuter le sweep via run_llm_sweep()
                    from agents.integration import run_llm_sweep

                    sweep_results = run_llm_sweep(
                        range_proposal=range_proposal,
                        param_specs=param_specs,
                        data=executor.data,
                        strategy_name=executor.strategy_name,
                        initial_capital=10000.0,  # Default
                        n_workers=None,  # Auto-detect
                    )

                    # Incrémenter les compteurs de budget
                    n_combinations = sweep_results['n_combinations']
                    sweeps_performed += 1
                    total_combinations_tested += n_combinations

                    # Enregistrer les ranges testées dans le tracker
                    best_sharpe = sweep_results['best_metrics'].get('sharpe_ratio', 0)
                    ranges_tracker.register(
                        ranges=decision.ranges,
                        n_combinations=n_combinations,
                        best_sharpe=best_sharpe,
                        rationale=decision.rationale
                    )

                    logger.info(
                        f"✅ Sweep #{sweeps_performed} terminé: {n_combinations} combinaisons testées | "
                        f"Best {decision.optimize_for}={sweep_results['best_metrics'].get(decision.optimize_for, 0):.3f} | "
                        f"Budget: {total_combinations_tested}/{max_iter_label} combos"
                    )

                    # Logger: résultat du sweep
                    if self.orchestration_logger:
                        self.orchestration_logger.log_backtest_complete(
                            agent="AutonomousStrategist",
                            params=sweep_results['best_params'],
                            results={
                                "pnl": sweep_results['best_metrics'].get('total_return', 0),
                                "sharpe": sweep_results['best_metrics'].get('sharpe_ratio', 0),
                                "return": sweep_results['best_metrics'].get('total_return', 0),
                                "n_combinations": sweep_results['n_combinations'],
                            },
                            combination_id=iteration,
                        )

                    # Valider le meilleur config avec un backtest complet (déjà fait par sweep)
                    # On crée un BacktestResult artificiel depuis les métriques
                    best_params = sweep_results['best_params']
                    best_metrics = sweep_results['best_metrics']

                    # Créer BacktestRequest pour traçabilité
                    request = BacktestRequest(
                        requested_by=self.role.value,
                        hypothesis=f"Sweep best config: {decision.rationale}",
                        parameters=best_params,
                    )

                    # Créer BacktestResult artificiel (sweep a déjà exécuté le backtest)
                    result = BacktestResult(
                        request=request,
                        success=True,
                        sharpe_ratio=best_metrics.get('sharpe_ratio', 0),
                        total_return=best_metrics.get('total_return', 0),
                        max_drawdown=best_metrics.get('max_drawdown', 1),
                        win_rate=best_metrics.get('win_rate', 0),
                        total_trades=best_metrics.get('total_trades', 0),
                        overfitting_ratio=best_metrics.get('overfitting_ratio', 1.0),
                        execution_time_ms=0,
                    )

                    session.all_results.append(result)

                    # Mettre à jour le meilleur si applicable
                    if self._is_better(result, session.best_result, target_metric):
                        session.best_result = result
                        logger.info(
                            f"Nouveau meilleur trouvé par sweep! Sharpe={result.sharpe_ratio:.3f}"
                        )

                    if self.on_progress:
                        self.on_progress(iteration, result)

                except Exception as e:
                    logger.error(f"Erreur durant le sweep: {e}")
                    # Continuer l'optimisation malgré l'erreur
                    if self.orchestration_logger:
                        self.orchestration_logger.log_decision(
                            agent="AutonomousStrategist",
                            decision_type="sweep_failed",
                            reason=f"Sweep failed: {str(e)}",
                            details={},
                        )

            elif decision.action in ("continue", "change_direction"):
                # Valider et corriger les paramètres
                next_params = self._validate_parameters(
                    decision.next_parameters, param_bounds, initial_params, session
                )

                # Logger: changement de paramètres
                if self.orchestration_logger and next_params != session.best_result.request.parameters:
                    for param, new_value in next_params.items():
                        old_value = session.best_result.request.parameters.get(param)
                        if old_value != new_value:
                            self.orchestration_logger.log_indicator_values_change(
                                agent="AutonomousStrategist",
                                indicator=param,
                                old_values={"value": old_value},
                                new_values={"value": new_value},
                                reason=decision.next_hypothesis,
                            )

                # Créer la requête
                request = BacktestRequest(
                    requested_by=self.role.value,
                    hypothesis=decision.next_hypothesis,
                    parameters=next_params,
                )

                # Logger: lancement du backtest
                if self.orchestration_logger:
                    self.orchestration_logger.log_backtest_launch(
                        agent="AutonomousStrategist",
                        params=next_params,
                        combination_id=iteration,
                        total_combinations=max_iterations,
                    )

                # Exécuter le backtest (avec déchargement LLM si activé)
                result = self._run_backtest_with_gpu_optimization(executor, request)
                session.all_results.append(result)

                # Logger: résultat du backtest
                if self.orchestration_logger:
                    self.orchestration_logger.log_backtest_complete(
                        agent="AutonomousStrategist",
                        params=next_params,
                        results={
                            "pnl": result.total_return,
                            "sharpe": result.sharpe_ratio,
                            "return": result.total_return,
                        },
                        combination_id=iteration,
                    )

                # Mettre à jour le meilleur si applicable
                if self._is_better(result, session.best_result, target_metric):
                    session.best_result = result
                    logger.info(
                        f"Nouveau meilleur! Sharpe={result.sharpe_ratio:.3f}"
                    )

                # Incrémenter le compteur de budget (1 combo testée)
                total_combinations_tested += 1

                if self.on_progress:
                    self.on_progress(iteration, result)

        else:
            session.final_status = "max_iterations"
            session.final_reasoning = f"Reached {max_iterations} iterations"

        # Logger: fin de l'optimisation
        if self.orchestration_logger:
            self.orchestration_logger.log_analysis_complete(
                agent="AutonomousStrategist",
                results={
                    "status": session.final_status,
                    "reasoning": session.final_reasoning,
                    "best_sharpe": session.best_result.sharpe_ratio,
                    "iterations": session.current_iteration,
                },
            )

            # Forcer la sauvegarde finale des logs
            try:
                self.orchestration_logger.save_to_jsonl()
            except Exception as e:
                logger.warning(f"Échec de la sauvegarde finale des logs: {e}")

        logger.info(
            f"Optimisation terminée: {session.final_status} | "
            f"Meilleur Sharpe: {session.best_result.sharpe_ratio:.3f}"
        )

        return session

    def _build_iteration_context(
        self,
        executor: BacktestExecutor,
        session: OptimizationSession,
        param_bounds: Dict[str, tuple],
        min_sharpe: float,
        max_drawdown: float,
    ) -> str:
        """Construit le contexte pour le LLM."""
        def _format_items(items: Any) -> str:
            if isinstance(items, (list, tuple)):
                return ", ".join(str(item) for item in items) if items else "N/A"
            return str(items) if items else "N/A"

        def _format_float(value: Any, precision: int = 2) -> str:
            try:
                return f"{float(value):.{precision}f}"
            except Exception:
                return "N/A"

        max_iter_label = "∞" if session.max_iterations <= 0 else str(session.max_iterations)

        lines = [
            f"=== Optimization Session: {session.strategy_name} ===",
            f"Iteration: {session.current_iteration}/{max_iter_label}",
            f"Target: {session.target_metric}",
            "",
        ]

        context_block = executor.get_context_for_agent()
        if context_block:
            lines.extend([context_block, ""])

        if session.comparison_context:
            context_data = session.comparison_context
            lines.extend([
                "Multi-Sweep Context:",
                f"  Mode: {context_data.get('mode', 'N/A')}",
                f"  Strategies: {_format_items(context_data.get('strategies'))}",
                f"  Symbols: {_format_items(context_data.get('symbols'))}",
                f"  Timeframes: {_format_items(context_data.get('timeframes'))}",
                f"  Total combinations: {context_data.get('total_combinations', 0)}",
            ])

            if context_data.get("has_results"):
                lines.extend([
                    f"  Sweeps: {context_data.get('total_sweeps', 0)}",
                    f"  Profitable: {context_data.get('profitable_count', 0)}",
                    f"  Avg PnL: {_format_float(context_data.get('avg_pnl'), 2)}",
                    f"  Median PnL: {_format_float(context_data.get('median_pnl'), 2)}",
                    f"  Best Sharpe: {_format_float(context_data.get('best_sharpe'), 3)}",
                    f"  Avg Sharpe: {_format_float(context_data.get('avg_sharpe'), 3)}",
                ])

                best_overall = context_data.get("best_overall")
                if isinstance(best_overall, dict) and best_overall:
                    best_strategy = best_overall.get("strategy", "")
                    best_symbol = best_overall.get("symbol", "")
                    best_timeframe = best_overall.get("timeframe", "")
                    best_pnl = _format_float(best_overall.get("total_pnl", best_overall.get("pnl", 0)), 2)
                    best_sharpe = _format_float(best_overall.get("sharpe_ratio", best_overall.get("sharpe", 0)), 3)
                    label = "  Best Overall:"
                    if best_strategy or best_symbol or best_timeframe:
                        lines.append(
                            f"{label} {best_strategy} {best_symbol} {best_timeframe} | "
                            f"PnL={best_pnl} Sharpe={best_sharpe}"
                        )
                    else:
                        lines.append(f"{label} PnL={best_pnl} Sharpe={best_sharpe}")

            lines.append("")

        if not session.indicator_context_cached:
            try:
                indicator_ctx = build_indicator_context(
                    df=executor.data,
                    strategy_name=session.strategy_name,
                    params=session.best_result.request.parameters,
                )
                session.strategy_indicators_context = indicator_ctx.get("strategy", "")
                session.readonly_indicators_context = indicator_ctx.get("read_only", "")
                session.indicator_context_warnings = indicator_ctx.get("warnings", [])
            except Exception:
                session.strategy_indicators_context = ""
                session.readonly_indicators_context = ""
                session.indicator_context_warnings = []
            session.indicator_context_cached = True

        if session.strategy_indicators_context:
            lines.extend([
                "Strategy Indicators (modifiable):",
                session.strategy_indicators_context,
                "",
            ])
        if session.readonly_indicators_context:
            lines.extend([
                "Context Indicators (read-only):",
                session.readonly_indicators_context,
                "",
            ])
        if session.indicator_context_warnings:
            lines.append("Indicator Context Warnings:")
            for w in session.indicator_context_warnings:
                lines.append(f"  - {w}")
            lines.append("")

        lines.extend([
            "Indicator Usage Notes:",
            "  - Strategy indicators are tied to tunable parameters.",
            "  - Context indicators are read-only and for regime interpretation only.",
            "  - Indicator values are computed once per run (baseline snapshot).",
            "",
        ])

        lines.append("Parameter Bounds:")

        # Calculer les statistiques d'espace de recherche
        try:
            stats = compute_search_space_stats(param_bounds, max_combinations=100000)

            for param, (min_val, max_val) in param_bounds.items():
                current = session.best_result.request.parameters.get(param, "?")
                param_count = stats.per_param_counts.get(param, "?")
                lines.append(
                    f"  {param}: [{min_val}, {max_val}] "
                    f"(current: {current}, values: {param_count})"
                )

            # Ajouter le résumé de l'espace de recherche
            lines.extend([
                "",
                "Search Space:",
                f"  {stats.summary()}",
            ])

            if stats.warnings:
                lines.append(f"  Warnings: {', '.join(stats.warnings)}")

        except Exception as e:
            # Fallback si le calcul des stats échoue
            logger.warning(f"Failed to compute search space stats: {e}")
            for param, (min_val, max_val) in param_bounds.items():
                current = session.best_result.request.parameters.get(param, "?")
                lines.append(f"  {param}: [{min_val}, {max_val}] (current: {current})")

        lines.extend([
            "",
            "Constraints:",
            f"  Min Sharpe: {min_sharpe}",
            f"  Max Drawdown: {max_drawdown:.0%}",
        ])

        # Dernières décisions
        if session.decisions:
            lines.extend(["", "Recent Decisions:"])
            for i, dec in enumerate(session.decisions[-5:], 1):
                lines.append(f"  {i}. {dec.action}: {dec.reasoning[:60]}...")

        lines.extend([
            "",
            "What is your next action?",
            "Remember: respond in JSON format with action, reasoning, next_hypothesis, next_parameters.",
        ])

        return "\n".join(lines)

    def _get_llm_decision(self, context: str, session: OptimizationSession) -> IterationDecision:
        """Obtient une décision du LLM."""

        # Identifiant pour corrélation logs (optim_id = strategy + timestamp)
        import hashlib
        import time
        optim_id = f"{session.strategy_name}_{session.start_time.strftime('%Y%m%d_%H%M%S')}"

        # LLM_CALL_START
        # Récupérer config depuis le client LLM
        model_name = self.llm.config.model if hasattr(self.llm, 'config') else 'unknown'
        max_tokens = self.llm.config.max_tokens if hasattr(self.llm, 'config') else 0
        timeout = (
            getattr(self.llm.config, "timeout_seconds", 0)
            if hasattr(self.llm, "config")
            else 0
        )

        def _log_orchestration_event(event_type: str, **payload: Any) -> None:
            if not self.orchestration_logger:
                return
            entry = {
                "event_type": event_type,
                "timestamp": datetime.now().isoformat(),
                "session_id": getattr(self.orchestration_logger, "session_id", None),
                "iteration": session.current_iteration,
                "role": "autonomous_strategist",
                **payload,
            }
            try:
                if hasattr(self.orchestration_logger, "log"):
                    self.orchestration_logger.log(event_type, entry)
                elif hasattr(self.orchestration_logger, "add_event"):
                    self.orchestration_logger.add_event(event_type, entry)
                elif hasattr(self.orchestration_logger, "append"):
                    self.orchestration_logger.append(entry)
            except Exception:
                # Le tracking ne doit jamais interrompre l'optimisation.
                pass

        _log_orchestration_event(
            "agent_execute_start",
            model=model_name,
        )

        logger.info(
            f"LLM_CALL_START optim_id={optim_id} iteration={session.current_iteration} "
            f"model={model_name} temperature=0.5 "
            f"tokens_max={max_tokens} "
            f"timeout={timeout}"
        )

        # LLM_PROMPT_META
        context_hash = hashlib.sha256(context.encode()).hexdigest()[:8]
        logger.debug(
            f"LLM_PROMPT_META optim_id={optim_id} iteration={session.current_iteration} "
            f"prompt_hash={context_hash} prompt_chars={len(context)} "
            f"prompt_tokens={len(context.split())} template_version=v1.0"
        )

        # Appel LLM avec mesure latence
        start_time = time.time()
        response = self._call_llm(context, json_mode=True, temperature=0.5)
        latency = time.time() - start_time

        # LLM_RESPONSE_META
        tokens_out = len(response.content.split()) if response.content else 0
        logger.info(
            f"LLM_RESPONSE_META optim_id={optim_id} iteration={session.current_iteration} "
            f"latency_sec={latency:.2f} tokens_out={tokens_out} "
            f"finish_reason=complete"
        )

        if not response.content:
            _log_orchestration_event(
                "agent_execute_end",
                model=model_name,
                success=False,
                latency_ms=int(latency * 1000),
                error="empty_response",
            )
            logger.error("❌ LLM n'a pas répondu (response.content vide)")
            return IterationDecision(
                action="stop",
                confidence=0.0,
                reasoning="LLM did not respond",
            )

        data = response.parse_json()
        if data is None:
            _log_orchestration_event(
                "agent_execute_end",
                model=model_name,
                success=False,
                latency_ms=int(latency * 1000),
                error="parse_json_failed",
            )
            logger.error(
                f"❌ Échec parsing JSON de la réponse LLM. "
                f"Réponse brute (100 premiers chars): {response.content[:100]}"
            )
            return IterationDecision(
                action="stop",
                confidence=0.0,
                reasoning=f"Failed to parse LLM response: {response.content[:100]}",
            )

        # Log succès du parsing
        action = data.get("action", "stop")
        logger.debug(f"✅ Décision LLM parsée avec succès: action='{action}'")

        # Protection contre les valeurs None du LLM
        next_params = data.get("next_parameters", {})
        if next_params is None:
            next_params = {}

        insights = data.get("insights", [])
        if insights is None:
            insights = []

        # Extraction champs spécifiques au sweep
        ranges = data.get("ranges", None)
        rationale = data.get("rationale", "") or ""
        optimize_for = data.get("optimize_for", "sharpe_ratio")
        max_combinations = data.get("max_combinations", 100)

        # LLM_DECISION_PARSED
        reasoning_hash = hashlib.sha256(str(data.get("reasoning", "")).encode()).hexdigest()[:8]
        if action == "sweep":
            ranges_count = len(ranges) if ranges else 0
            logger.info(
                f"LLM_DECISION_PARSED optim_id={optim_id} iteration={session.current_iteration} "
                f"action={action} confidence={data.get('confidence', 0.5):.2f} "
                f"ranges_count={ranges_count} optimize_for={optimize_for} "
                f"max_combinations={max_combinations} reasoning_hash={reasoning_hash}"
            )
        else:
            logger.info(
                f"LLM_DECISION_PARSED optim_id={optim_id} iteration={session.current_iteration} "
                f"action={action} confidence={data.get('confidence', 0.5):.2f} "
                f"next_params_count={len(next_params) if next_params else 0} "
                f"next_params_keys={list(next_params.keys()) if next_params else []} "
                f"reasoning_hash={reasoning_hash}"
            )

        # LLM_FALLBACK_USED - Warning si next_parameters vide pour continue/change_direction
        if action in ("continue", "change_direction") and not next_params:
            logger.warning(
                f"LLM_FALLBACK_USED optim_id={optim_id} iteration={session.current_iteration} "
                f"action={action} fallback=will_use_defaults cause=next_params_empty"
            )

        # Validation sweep: ranges obligatoire si action == "sweep"
        if action == "sweep" and not ranges:
            _log_orchestration_event(
                "agent_execute_end",
                model=model_name,
                success=False,
                latency_ms=int(latency * 1000),
                error="sweep_ranges_missing",
            )
            logger.warning(
                f"LLM_INVALID_DECISION optim_id={optim_id} iteration={session.current_iteration} "
                f"action_original=sweep action_forced=stop reason=ranges_empty_or_missing"
            )
            return IterationDecision(
                action="stop",
                confidence=0.0,
                reasoning="LLM chose 'sweep' but provided no ranges. Stopping.",
            )

        _log_orchestration_event(
            "agent_execute_end",
            model=model_name,
            success=True,
            latency_ms=int(latency * 1000),
        )

        return IterationDecision(
            action=action,
            confidence=data.get("confidence", 0.5),
            reasoning=data.get("reasoning", "") or "",
            next_hypothesis=data.get("next_hypothesis", "") or "",
            next_parameters=next_params,
            insights=insights,
            ranges=ranges,
            rationale=rationale,
            optimize_for=optimize_for,
            max_combinations=max_combinations,
        )

    def _validate_parameters(
        self,
        params: Dict[str, Any],
        bounds: Dict[str, tuple],
        defaults: Dict[str, Any],
        session: OptimizationSession,
    ) -> Dict[str, Any]:
        """Valide et corrige les paramètres avec checks robustes."""

        # Identifiant pour corrélation logs
        optim_id = f"{session.strategy_name}_{session.start_time.strftime('%Y%m%d_%H%M%S')}"

        # VALIDATION_START
        logger.info(
            f"VALIDATION_START optim_id={optim_id} iteration={session.current_iteration} "
            f"validating=parameters proposed={params} bounds_count={len(bounds)}"
        )

        validated = {}
        used_defaults = []  # Track params qui utilisent defaults

        for param, bound_spec in bounds.items():
            try:
                # Extraire min/max selon le format des bounds
                # Peut être (min, max) ou (min, max, step) ou [min, max, ...]
                if isinstance(bound_spec, (tuple, list)) and len(bound_spec) >= 2:
                    min_val = float(bound_spec[0])
                    max_val = float(bound_spec[1])

                    # Validation: min < max
                    if min_val >= max_val:
                        logger.warning(f"Param {param}: min >= max ({min_val} >= {max_val}), swap")
                        min_val, max_val = max_val, min_val
                else:
                    # Valeur scalaire (cas edge)
                    min_val = max_val = float(bound_spec) if not isinstance(bound_spec, (tuple, list)) else float(bound_spec[0])

                value_proposed = params.get(param)
                value_default = defaults.get(param)
                value = value_proposed if value_proposed is not None else value_default

                if value is None:
                    value = (min_val + max_val) / 2
                    used_defaults.append(param)
                else:
                    value = float(value)

                value_before_clamp = value

                # Clamp dans les bornes
                value = max(min_val, min(max_val, value))

                # Arrondir si nécessaire (detect int bounds)
                if all(isinstance(bound_spec[i], int) for i in range(2) if i < len(bound_spec)):
                    value = int(round(value))

                validated[param] = value

                # VALIDATION_RULE_RESULT - Log détail validation
                status = "pass" if value_proposed is not None else "used_default"
                action = "clamped" if abs(value - value_before_clamp) > 1e-9 else "accepted"

                logger.debug(
                    f"VALIDATION_RULE_RESULT optim_id={optim_id} iteration={session.current_iteration} "
                    f"param={param} rule=bounds_check proposed={value_proposed} "
                    f"default={value_default} bounds=({min_val},{max_val}) "
                    f"final={value} status={status} action={action}"
                )

            except (ValueError, TypeError, IndexError) as e:
                logger.error(f"Param {param} validation failed: {e}, use default")
                validated[param] = defaults.get(param, 0)
                used_defaults.append(param)

        # VALIDATION_END
        logger.info(
            f"VALIDATION_END optim_id={optim_id} iteration={session.current_iteration} "
            f"validated={validated} used_defaults={used_defaults} verdict=accepted"
        )

        return validated

    def _is_better(
        self,
        new: BacktestResult,
        current: BacktestResult,
        metric: str,
    ) -> bool:
        """Détermine si un résultat est meilleur."""

        if not new.success:
            return False

        # Vérifier overfitting
        if new.overfitting_ratio > 1.5:
            return False

        # Comparer la métrique
        new_value = getattr(new, metric, 0)
        current_value = getattr(current, metric, 0)

        if metric in ("max_drawdown",):  # Métriques à minimiser
            return new_value < current_value
        else:  # Métriques à maximiser
            return new_value > current_value

    def execute(self, context: AgentContext) -> AgentResult:
        """
        Exécute une itération (pour compatibilité avec BaseAgent).

        Pour une optimisation complète, utilisez optimize() directement.
        """
        return AgentResult(
            success=True,
            agent_role=self.role,
            content="Use optimize() method for autonomous optimization",
            data={},
            execution_time_ms=0,
            tokens_used=0,
            llm_calls=0,
        )


def create_autonomous_optimizer(
    llm_config: LLMConfig,
    backtest_fn: Callable,
    strategy_name: str,
    data: pd.DataFrame,
    validation_fn: Optional[Callable] = None,
) -> tuple[AutonomousStrategist, BacktestExecutor]:
    """
    Factory pour créer un optimiseur autonome complet.

    Args:
        llm_config: Configuration LLM
        backtest_fn: Fonction de backtest (strategy, params, data) -> metrics
        strategy_name: Nom de la stratégie
        data: DataFrame OHLCV
        validation_fn: Fonction walk-forward optionnelle

    Returns:
        (AutonomousStrategist, BacktestExecutor) prêts à l'emploi

    Example:
        >>> from agents.llm_client import LLMConfig, LLMProvider
        >>>
        >>> config = LLMConfig(provider=LLMProvider.OLLAMA, model="llama3.2")
        >>> strategist, executor = create_autonomous_optimizer(
        ...     llm_config=config,
        ...     backtest_fn=run_backtest,
        ...     strategy_name="ema_cross",
        ...     data=ohlcv_df,
        ... )
        >>>
        >>> session = strategist.optimize(
        ...     executor=executor,
        ...     initial_params={"fast": 10, "slow": 21},
        ...     param_bounds={"fast": (5, 20), "slow": (15, 50)},
        ... )
    """
    from .llm_client import create_llm_client

    llm_client = create_llm_client(llm_config)

    strategy_overview = get_strategy_overview(strategy_name)
    executor = BacktestExecutor(
        backtest_fn=backtest_fn,
        strategy_name=strategy_name,
        data=data,
        validation_fn=validation_fn,
        strategy_description=strategy_overview,
    )

    strategist = AutonomousStrategist(llm_client, verbose=True)

    return strategist, executor


# Docstring update summary
# - Docstring de module structurée et scannable (LLM-friendly)
# - Conventions explicitées (métrique, unités, critères d'arrêt, GPU unload)
# - Read-if/Skip-if ajoutés pour tri rapide
