"""
Module-ID: agents.orchestrator

Purpose: Orchestrer le workflow multi-agents (Analyst/Strategist/Critic/Validator) et piloter la boucle d’optimisation.

Role in pipeline: orchestration

Key components: OrchestratorConfig, Orchestrator, StateMachine, ValidationResult, run_walk_forward_for_agent

Inputs: LLMConfig/clients, callbacks (on_backtest_needed), données (path/df), paramètres initiaux et contraintes

Outputs: Décision finale (APPROVED/REJECTED/FAILED), historiques d’itérations, logs/mémoire LLM, suivi paramètres

Dependencies: agents.state_machine, agents.*Agent, agents.integration, agents.model_config, utils.llm_memory, utils.session_param_tracker

Conventions: États INIT→ANALYZE→PROPOSE→CRITIQUE→VALIDATE→ITERATE; ABORT mappe sur FAILED; timestamps en UTC si utilisés.

Read-if: Vous touchez aux transitions, critères d’arrêt, mémoire/logs, ou au wiring des agents.

Skip-if: Vous ne modifiez qu’un agent isolé ou le moteur de backtest pur.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Optional

from utils.llm_memory import (
    MAX_INSIGHTS,
    append_history_entry,
    append_session_iteration,
    build_memory_summary,
    delete_session,
    extract_date_range,
    get_history_path,
    split_date_range,
    start_session,
)
from utils.observability import get_obs_logger
from utils.session_param_tracker import SessionParameterTracker

from .analyst import AnalystAgent
from .base_agent import AgentContext, AgentResult, BaseAgent, MetricsSnapshot, ParameterConfig
from .critic import CriticAgent
from .integration import run_walk_forward_for_agent
from .llm_client import LLMConfig, create_llm_client
from .llm_router import LLMTopologyConfig, ResolvedLLMRoute, build_phase1_topology
from .model_config import RoleModelConfig
from .state_machine import AgentState, StateMachine, ValidationResult
from .strategist import StrategistAgent
from .validator import ValidationDecision, ValidatorAgent

# Import optionnel de tqdm pour barres de progression
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    # Fallback: tqdm est une fonction identité

    def tqdm(iterable: Iterable[Any], **kwargs: Any) -> Iterable[Any]:
        return iterable

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

    from agents.integration import AgentBacktestMetrics


logger = get_obs_logger(__name__)


@dataclass
class OrchestratorConfig:
    """Configuration de l'Orchestrator."""

    # Stratégie
    strategy_name: str = ""
    strategy_description: str = ""

    # Données
    data_path: str = ""
    data: Optional["pd.DataFrame"] = None
    data_symbol: str = ""
    data_timeframe: str = ""
    data_date_range: str = ""
    comparison_context: Optional[Dict[str, Any]] = None

    # Paramètres initiaux
    initial_params: Dict[str, Any] = field(default_factory=dict)
    param_specs: List[ParameterConfig] = field(default_factory=list)

    # Objectifs d'optimisation
    optimization_target: str = "sharpe_ratio"
    min_sharpe: float = 1.0
    max_drawdown_limit: float = 0.20
    min_trades: int = 30
    max_overfitting_ratio: float = 1.5

    # Limites
    max_iterations: int = 10
    max_proposals_per_iteration: int = 5

    # Exécution
    n_workers: int = 1
    session_id: Optional[str] = None
    orchestration_logger: Optional[Any] = None

    # LLM
    llm_config: Optional[LLMConfig] = None
    role_model_config: Optional[RoleModelConfig] = None
    llm_topology_config: Optional[LLMTopologyConfig] = None
    max_consecutive_llm_failures: int = 3

    # Walk-forward
    use_walk_forward: bool = True
    walk_forward_windows: int = 5
    train_ratio: float = 0.7
    walk_forward_disabled_reason: Optional[str] = None  # Raison si désactivé automatiquement

    # Callbacks (optionnels)
    on_state_change: Optional[Callable[[AgentState, AgentState], None]] = None
    on_iteration_complete: Optional[Callable[[int, Dict[str, Any]], None]] = None
    on_backtest_needed: Optional[Callable[[Dict[str, Any]], "AgentBacktestMetrics"]] = None


@dataclass
class OrchestratorResult:
    """Résultat final de l'orchestration."""

    success: bool
    final_state: AgentState
    decision: str  # APPROVE, REJECT, ABORT

    # Configuration finale
    final_params: Dict[str, Any] = field(default_factory=dict)
    final_metrics: Optional[MetricsSnapshot] = None

    # Métriques d'exécution
    total_iterations: int = 0
    total_backtests: int = 0
    total_time_s: float = 0.0
    total_llm_tokens: int = 0
    total_llm_calls: int = 0

    # Historique
    iteration_history: List[Dict[str, Any]] = field(default_factory=list)
    state_history: List[Dict[str, Any]] = field(default_factory=list)

    # Rapport
    final_report: str = ""
    recommendations: List[str] = field(default_factory=list)

    # Erreurs
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class Orchestrator:
    """
    Orchestrator - Coordonne le workflow d'optimisation LLM.

    Garanties:
    - Transitions validées via State Machine
    - Pas de boucles infinies (max_iterations)
    - Traçabilité complète
    - Gestion des erreurs gracieuse

    Example:
        >>> config = OrchestratorConfig(
        ...     strategy_name="ema_cross",
        ...     data_path="data/BTCUSDT_1h.parquet",
        ...     initial_params={"fast_period": 12, "slow_period": 26},
        ...     param_specs=[...],
        ... )
        >>> orchestrator = Orchestrator(config)
        >>> result = orchestrator.run()
        >>> if result.success:
        ...     print(f"Optimized params: {result.final_params}")
    """

    def __init__(self, config: OrchestratorConfig) -> None:
        """
        Initialise l'Orchestrator.

        Args:
            config: Configuration complète
        """
        self.config = config
        if config.session_id:
            self.session_id = str(config.session_id)
        elif config.orchestration_logger is not None and hasattr(config.orchestration_logger, "session_id"):
            self.session_id = str(getattr(config.orchestration_logger, "session_id"))
        else:
            self.session_id = str(uuid.uuid4())[:8]

        # State Machine
        self.state_machine = StateMachine(max_iterations=config.max_iterations)
        self._unlimited_iterations = config.max_iterations <= 0
        self._max_iter_label = "∞" if self._unlimited_iterations else str(config.max_iterations)

        # LLM Client
        llm_config = config.llm_config or LLMConfig.from_env()
        self.llm_client = create_llm_client(llm_config)

        # Agents
        self.analyst = AnalystAgent(self.llm_client)
        self.strategist = StrategistAgent(self.llm_client)
        self.critic = CriticAgent(self.llm_client)
        self.validator = ValidatorAgent(self.llm_client)

        # Context partagé
        self.context = self._create_initial_context()

        # Tracking
        self._start_time: Optional[float] = None
        self._backtests_count = 0
        self._total_combinations_tested = 0  # Compteur de budget (sweep + individual)
        self._sweeps_performed = 0
        self._max_sweeps_per_session = 3  # Limite de sweeps pour éviter l'abus
        self._errors: List[str] = []
        self._warnings: List[str] = []
        self._indicator_context_cached = False
        self._consecutive_llm_failures = 0

        # Tracker de ranges pour éviter boucles infinies
        from utils.session_ranges_tracker import SessionRangesTracker
        self._ranges_tracker = SessionRangesTracker(session_id=self.session_id)
        self._memory_session_path: Optional[Path] = None
        self._last_validation_data: Optional[Dict[str, Any]] = None
        self._last_validator_summary: str = ""
        self._role_models: Dict[str, str] = {}
        self._role_routes: Dict[str, ResolvedLLMRoute] = {}

        # Session Parameter Tracker - empêche les LLMs de retester les mêmes paramètres
        self.param_tracker = SessionParameterTracker(session_id=self.session_id)

        # Données chargées (pour walk-forward)
        self._loaded_data: Optional["pd.DataFrame"] = getattr(config, "data", None)

        # Orchestration logger (optionnel, non bloquant)
        self._orch_logger: Any = None
        self._init_orchestration_logger()
        self.llm_topology_config = config.llm_topology_config or build_phase1_topology(
            primary_host=getattr(self.llm_client.config, "ollama_host", None)
        )

        logger.info(
            f"Orchestrator initialisé: session={self.session_id}, "
            f"strategy={config.strategy_name}, max_iter={self._max_iter_label}"
        )

    def _create_initial_context(self) -> AgentContext:
        """Crée le contexte initial."""
        return AgentContext(
            session_id=self.session_id,
            iteration=0,
            strategy_name=self.config.strategy_name,
            strategy_description=self.config.strategy_description,
            current_params=self.config.initial_params.copy(),
            param_specs=self.config.param_specs,
            data_path=self.config.data_path,
            data_symbol=self.config.data_symbol,
            data_timeframe=self.config.data_timeframe,
            data_date_range=self.config.data_date_range,
            comparison_context=self.config.comparison_context,
            optimization_target=self.config.optimization_target,
            min_sharpe=self.config.min_sharpe,
            max_drawdown_limit=self.config.max_drawdown_limit,
            min_trades=self.config.min_trades,
            max_overfitting_ratio=self.config.max_overfitting_ratio,
        )

    def _init_orchestration_logger(self) -> None:
        """Initialise un logger d'orchestration s'il est disponible (non bloquant)."""
        # Utilise un logger fourni dans la config si présent
        if getattr(self.config, "orchestration_logger", None) is not None:
            self._orch_logger = self.config.orchestration_logger
            return
        # Tentative de création depuis le module dédié (si disponible)
        try:
            from .orchestration_logger import OrchestrationLogger  # type: ignore
            self._orch_logger = OrchestrationLogger(session_id=self.session_id)
        except Exception:
            self._orch_logger = None  # Mode dégradé: aucune trace persistée

    def _log_event(self, event_type: str, **payload: Any) -> None:
        """
        Ajoute un événement d'orchestration de manière non bloquante.
        Supporte plusieurs API possibles (log/add_event/append).
        """
        if not self._orch_logger:
            return
        try:
            entry = {
                "event_type": event_type,
                "timestamp": datetime.now().isoformat(),
                "session_id": self.session_id,
                "iteration": getattr(self.state_machine, "iteration", 0),
                **payload,
            }
            if hasattr(self._orch_logger, "log"):
                self._orch_logger.log(event_type, entry)  # type: ignore[attr-defined]
            elif hasattr(self._orch_logger, "add_event"):
                self._orch_logger.add_event(event_type, entry)  # type: ignore[attr-defined]
            elif hasattr(self._orch_logger, "append"):
                self._orch_logger.append(entry)  # type: ignore[attr-defined]
        except Exception as e:
            # Ne jamais bloquer le flux pour la traçabilité
            logger.debug("Orchestration log failed: %s", e)

    def _handle_llm_failure(self, result: AgentResult, role: str) -> bool:
        if result.success:
            self._consecutive_llm_failures = 0
            return False

        raw = result.raw_llm_response
        llm_error = False
        parse_error = ""

        if raw and not raw.content and raw.parse_error:
            llm_error = True
            parse_error = raw.parse_error

        if any("LLM n'a pas retourné de réponse" in err for err in result.errors):
            llm_error = True

        if not llm_error:
            return False

        self._consecutive_llm_failures += 1
        self._log_event(
            "llm_failure",
            role=role,
            count=self._consecutive_llm_failures,
            message=parse_error or "; ".join(result.errors),
        )

        if self._consecutive_llm_failures >= self.config.max_consecutive_llm_failures:
            reason = (
                "LLM indisponible ou en erreur répétée "
                f"({self._consecutive_llm_failures} échecs)"
            )
            self._errors.append(reason)
            self._log_event("llm_abort", role=role, reason=reason)
            self.state_machine.fail(reason)
            return True

        return False

    def _resolve_role_route(self, role: str) -> ResolvedLLMRoute:
        return self.llm_topology_config.resolve_role_route(
            role,
            fallback_host=getattr(self.llm_client.config, "ollama_host", None),
        )

    def _get_role_route_payload(self, role: str) -> Dict[str, Any]:
        route = self._role_routes.get(role) or self._resolve_role_route(role)
        self._role_routes[role] = route
        return {
            "route_name": route.route_name,
            "host": route.ollama_host,
            "gpu_target": route.gpu_target,
            "route_fallback_used": route.fallback_used,
        }

    def _apply_role_model(self, role: str) -> Optional[str]:
        """Select and apply a model for the given role if configured."""
        route = self._resolve_role_route(role)
        self._role_routes[role] = route
        client_config = getattr(self.llm_client, "config", None)
        if client_config is not None and route.ollama_host:
            client_config.ollama_host = route.ollama_host
        config = self.config.role_model_config
        if not config:
            model_name = self.llm_client.config.model
            self._role_models[role] = model_name
            return model_name

        iteration = max(1, self.state_machine.iteration)
        model_name = config.get_model(
            role=role,
            iteration=iteration,
            random_selection=True,
        )
        if model_name and self.llm_client.config.model != model_name:
            self.llm_client.config.model = model_name
            logger.info("Role %s model set to %s", role, model_name)
        model_name = self.llm_client.config.model
        self._role_models[role] = model_name
        return model_name

    def _get_memory_identifiers(self) -> tuple[str, str, str]:
        strategy = self.config.strategy_name or self.context.strategy_name
        symbol = self.config.data_symbol or self.context.data_symbol or "unknown"
        timeframe = self.config.data_timeframe or self.context.data_timeframe or "unknown"
        return strategy, symbol, timeframe

    def _resolve_data_info(self) -> tuple[str, str, int]:
        data_rows = self.context.data_rows
        if not data_rows and self._loaded_data is not None:
            try:
                data_rows = len(self._loaded_data)
            except Exception:
                data_rows = 0

        period_start, period_end = extract_date_range(self._loaded_data)
        if not period_start and not period_end:
            period_start, period_end = split_date_range(self.context.data_date_range)

        if not self.context.data_date_range and (period_start or period_end):
            if period_start and period_end:
                self.context.data_date_range = f"{period_start} -> {period_end}"
            else:
                self.context.data_date_range = period_start or period_end

        return period_start, period_end, data_rows

    def _init_memory_session(self) -> None:
        strategy, symbol, timeframe = self._get_memory_identifiers()
        period_start, period_end, data_rows = self._resolve_data_info()
        model = self.llm_client.config.model

        try:
            self._memory_session_path = start_session(
                session_id=self.session_id,
                strategy=strategy,
                symbol=symbol,
                timeframe=timeframe,
                period_start=period_start,
                period_end=period_end,
                model=model,
                data_rows=data_rows,
            )
        except Exception as exc:
            logger.warning("LLM memory session init failed: %s", exc)
            self._memory_session_path = None

        try:
            self.context.memory_summary = build_memory_summary(
                strategy=strategy,
                symbol=symbol,
                timeframe=timeframe,
            )
        except Exception as exc:
            logger.debug("LLM memory summary failed: %s", exc)
            self.context.memory_summary = ""

    def _append_memory_iteration(self, entry: Dict[str, Any]) -> None:
        if not self._memory_session_path:
            return
        try:
            append_session_iteration(self._memory_session_path, entry)
        except Exception as exc:
            logger.debug("LLM memory session update failed: %s", exc)

    def _collect_insights(self) -> List[str]:
        insights: List[str] = []
        if self._last_validator_summary:
            insights.append(self._last_validator_summary)

        if self._last_validation_data:
            approved = self._last_validation_data.get("approved_config", {})
            if isinstance(approved, dict):
                for key in ("deployment_notes", "monitoring_recommendations"):
                    items = approved.get(key, [])
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, str) and item:
                                insights.append(item)

        unique: List[str] = []
        seen = set()
        for item in insights:
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)
        return unique[:MAX_INSIGHTS]

    def _build_history_entry(self, result: OrchestratorResult) -> Optional[Dict[str, Any]]:
        strategy, symbol, timeframe = self._get_memory_identifiers()
        period_start, period_end, data_rows = self._resolve_data_info()
        metrics = self.context.best_metrics or self.context.current_metrics
        if metrics is None:
            return None

        metrics_payload = {
            "sharpe_ratio": metrics.sharpe_ratio,
            "total_return_pct": metrics.total_return * 100.0,
            "max_drawdown_pct": metrics.max_drawdown * 100.0,
            "win_rate_pct": metrics.win_rate * 100.0,
            "total_trades": metrics.total_trades,
        }

        params = self.context.best_params or self.context.current_params
        model = self._role_models.get("validator") or self.llm_client.config.model
        insights = self._collect_insights()
        if not insights:
            insights = [
                (
                    f"Sharpe {metrics.sharpe_ratio:.2f}, "
                    f"return {metrics.total_return * 100.0:.1f}%, "
                    f"drawdown {metrics.max_drawdown * 100.0:.1f}%."
                )
            ]

        entry = {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "session_id": self.session_id,
            "strategy": strategy,
            "symbol": symbol,
            "timeframe": timeframe,
            "period_start": period_start,
            "period_end": period_end,
            "data_rows": data_rows,
            "model": model,
            "metrics": metrics_payload,
            "params": params,
            "insights": insights[:MAX_INSIGHTS],
            "decision": result.decision,
        }
        if self._last_validation_data:
            entry["validator_confidence"] = self._last_validation_data.get("confidence")

        return entry

    def _finalize_memory(self, result: OrchestratorResult) -> None:
        if result.decision == "APPROVE":
            history_entry = self._build_history_entry(result)
            if history_entry:
                strategy, symbol, timeframe = self._get_memory_identifiers()
                history_path = get_history_path(strategy, symbol, timeframe)
                try:
                    append_history_entry(history_path, history_entry)
                except Exception as exc:
                    logger.warning("LLM memory history update failed: %s", exc)

        if self._memory_session_path:
            delete_session(self._memory_session_path)
            self._memory_session_path = None

    def run(self) -> OrchestratorResult:
        """
        Exécute le workflow d'optimisation complet.

        Returns:
            Résultat de l'orchestration
        """
        self._start_time = time.time()
        self._log_event(
            "run_start",
            strategy=self.config.strategy_name,
            max_iterations=self.config.max_iterations,
            data_path=bool(self.config.data_path),
        )
        logger.info(f"=== Démarrage orchestration {self.session_id} ===")

        self._init_memory_session()

        try:
            # Transition vers INIT → ANALYZE
            self._run_workflow()

        except Exception as e:
            logger.error(f"Erreur orchestration: {e}", exc_info=True)
            self._log_event("error", scope="orchestration", message=str(e))
            self.state_machine.fail(str(e), e)
            self._errors.append(str(e))

        # Construire le résultat final
        result = self._build_result()
        self._log_event(
            "run_end",
            success=result.success,
            decision=result.decision,
            total_iterations=result.total_iterations,
            total_backtests=result.total_backtests,
            total_time_s=result.total_time_s,
            total_llm_calls=result.total_llm_calls,
            total_llm_tokens=result.total_llm_tokens,
            errors=len(result.errors),
            warnings=len(result.warnings),
        )

        # Forcer la sauvegarde finale des logs
        if self.config.orchestration_logger:
            try:
                self.config.orchestration_logger.save_to_jsonl()
            except Exception as e:
                logger.warning(f"Échec de la sauvegarde finale des logs: {e}")

        self._finalize_memory(result)

        return result

        # Docstring update summary
        # - Docstring de module normalisée (LLM-friendly) et orientée orchestration
        # - Conventions d’états/terminaison explicitées pour éviter les ambiguïtés
        # - Read-if/Skip-if ajoutés pour accélérer le tri des fichiers

    def _run_workflow(self) -> None:
        """Exécute la boucle principale du workflow."""

        while not self.state_machine.is_terminal:
            current = self.state_machine.current_state
            self._log_event("state_enter", state=current.name)
            logger.info(f"État actuel: {current.name}")

            # Dispatch selon l'état
            if current == AgentState.INIT:
                self._handle_init()
            elif current == AgentState.ANALYZE:
                self._handle_analyze()
            elif current == AgentState.PROPOSE:
                self._handle_propose()
            elif current == AgentState.CRITIQUE:
                self._handle_critique()
            elif current == AgentState.VALIDATE:
                self._handle_validate()
            elif current == AgentState.ITERATE:
                self._handle_iterate()
            else:
                logger.error(f"État non géré: {current}")
                self.state_machine.fail(f"État non géré: {current}")
                break

            # Callback + log de transition
            if self.config.on_state_change:
                self.config.on_state_change(current, self.state_machine.current_state)
            self._log_event(
                "state_change",
                state_from=current.name,
                state_to=self.state_machine.current_state.name,
            )

    def _handle_init(self) -> None:
        """Gère l'état INIT - Initialisation et validation."""
        self._log_event("phase_start", phase="INIT")
        logger.info("Phase INIT: Validation configuration et backtest initial")

        # Valider la configuration
        validation = self._validate_config()
        if not validation.is_valid:
            self._log_event("config_invalid", errors=validation.errors or [], message=validation.message)
            self.state_machine.fail(f"Configuration invalide: {validation.message}")
            return
        self._log_event("config_valid")

        # Exécuter le backtest initial
        initial_metrics = None
        try:
            initial_metrics = self._run_backtest(self.context.current_params)
            if initial_metrics:
                self.context.current_metrics = initial_metrics
                self.context.best_metrics = initial_metrics
                self.context.best_params = self.context.current_params.copy()
                self._log_event(
                    "initial_backtest_done",
                    sharpe=initial_metrics.sharpe_ratio,
                    total_return=initial_metrics.total_return,
                    max_drawdown=initial_metrics.max_drawdown,
                )
                logger.info(
                    f"Backtest initial: Sharpe={initial_metrics.sharpe_ratio:.3f}, "
                    f"Return={initial_metrics.total_return:.2%}"
                )
            else:
                self._warnings.append("Backtest initial sans métriques")
                self._log_event("warning", message="Backtest initial sans métriques")
        except Exception as e:
            self._warnings.append(f"Erreur backtest initial: {e}")
            self._log_event("warning", message=f"Erreur backtest initial: {e}")
            logger.error(f"Erreur backtest initial: {e}", exc_info=True)

        # Fallback: créer des métriques à zéro si le backtest a échoué
        if initial_metrics is None:
            logger.warning("Backtest initial échoué, utilisation de métriques par défaut (zéro)")
            initial_metrics = MetricsSnapshot(
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                total_return=0.0,
                max_drawdown=0.0,
                win_rate=0.0,
                profit_factor=0.0,
                total_trades=0,
            )
            self.context.current_metrics = initial_metrics
            self._warnings.append("Utilisation de métriques par défaut (backtest échoué)")
            self._log_event("warning", message="Métriques par défaut utilisées")

        # Calculer les métriques walk-forward si données disponibles
        self._compute_walk_forward_metrics()

        # Contexte indicateurs (une seule fois par run)
        if not self._indicator_context_cached and self._loaded_data is not None:
            try:
                from .indicator_context import build_indicator_context
                indicator_ctx = build_indicator_context(
                    df=self._loaded_data,
                    strategy_name=self.context.strategy_name,
                    params=self.context.current_params,
                )
                self.context.strategy_indicators_context = indicator_ctx.get("strategy", "")
                self.context.readonly_indicators_context = indicator_ctx.get("read_only", "")
                self.context.indicator_context_warnings = indicator_ctx.get("warnings", [])
                self._indicator_context_cached = True
                self._log_event(
                    "indicator_context",
                    strategy_indicators_context=self.context.strategy_indicators_context,
                    readonly_indicators_context=self.context.readonly_indicators_context,
                    warnings=self.context.indicator_context_warnings,
                )
            except Exception as exc:
                self._warnings.append(f"Contexte indicateurs indisponible: {exc}")
                self.context.strategy_indicators_context = ""
                self.context.readonly_indicators_context = ""
                self.context.indicator_context_warnings = []
                self._indicator_context_cached = True

        # Transition vers ANALYZE
        self.state_machine.transition_to(AgentState.ANALYZE)

    def _handle_analyze(self) -> None:
        """Gère l'état ANALYZE - Exécution de l'Agent Analyst."""
        self._log_event("phase_start", phase="ANALYZE")
        logger.info("Phase ANALYZE: Exécution Agent Analyst")

        # Mettre à jour l'itération dans le contexte
        self.context.iteration = self.state_machine.iteration

        # Ajouter le résumé du tracker de session pour informer l'Analyst
        if hasattr(self, 'param_tracker'):
            # Ajouter dynamiquement au contexte (pour ne pas modifier base_agent.py)
            setattr(
                self.context,
                'session_params_summary',
                self.param_tracker.get_summary()
            )

        # Contexte indicateurs (stratégie vs lecture seule) - calculé une seule fois par run
        if not self._indicator_context_cached and self._loaded_data is not None:
            try:
                from .indicator_context import build_indicator_context
                indicator_ctx = build_indicator_context(
                    df=self._loaded_data,
                    strategy_name=self.context.strategy_name,
                    params=self.context.current_params,
                )
                self.context.strategy_indicators_context = indicator_ctx.get("strategy", "")
                self.context.readonly_indicators_context = indicator_ctx.get("read_only", "")
                self.context.indicator_context_warnings = indicator_ctx.get("warnings", [])
                self._indicator_context_cached = True
                self._log_event(
                    "indicator_context",
                    strategy_indicators_context=self.context.strategy_indicators_context,
                    readonly_indicators_context=self.context.readonly_indicators_context,
                    warnings=self.context.indicator_context_warnings,
                )
            except Exception as exc:
                self._warnings.append(f"Contexte indicateurs indisponible: {exc}")
                self.context.strategy_indicators_context = ""
                self.context.readonly_indicators_context = ""
                self.context.indicator_context_warnings = []
                self._indicator_context_cached = True

        # Exécuter l'Analyst
        self._apply_role_model("analyst")
        self._log_event(
            "agent_execute_start",
            role="analyst",
            model=self.llm_client.config.model,
            **self._get_role_route_payload("analyst"),
        )
        t0 = time.time()
        result = self.analyst.execute(self.context)
        dt = int((time.time() - t0) * 1000)
        self._log_event(
            "agent_execute_end",
            role="analyst",
            model=self.llm_client.config.model,
            success=result.success,
            latency_ms=dt,
            **self._get_role_route_payload("analyst"),
        )

        if self._handle_llm_failure(result, "analyst"):
            return

        if not result.success:
            logger.error(f"Analyst échoué: {result.errors}")
            self._log_event("error", scope="analyst", message=str(result.errors))
            self._errors.extend(result.errors)
            # Continuer quand même - l'analyse n'est pas bloquante
            self.context.analyst_report = "Analyse non disponible"
        else:
            # Stocker le rapport
            self.context.analyst_report = result.content

            # Vérifier si on doit continuer l'optimisation
            proceed = result.data.get("proceed_to_optimization", True)
            self._log_event("analyst_result", proceed=bool(proceed))
            if not proceed:
                logger.info("Analyst recommande de ne pas optimiser")
                transition = self.state_machine.transition_to(AgentState.VALIDATE)
                if not transition.is_valid:
                    logger.warning(
                        "Transition ANALYZE -> VALIDATE refusee: %s",
                        transition.message,
                    )
                    self.state_machine.transition_to(AgentState.VALIDATE, force=True)
                return

        # Transition vers PROPOSE
        self.state_machine.transition_to(AgentState.PROPOSE)

    def _handle_propose(self) -> None:
        """Gère l'état PROPOSE - Exécution de l'Agent Strategist."""
        self._log_event("phase_start", phase="PROPOSE")
        logger.info("Phase PROPOSE: Exécution Agent Strategist")

        # Ajouter le résumé du tracker de session pour informer le Strategist
        if hasattr(self, 'param_tracker'):
            setattr(
                self.context,
                'session_params_summary',
                self.param_tracker.get_summary()
            )

        # Exécuter le Strategist
        self._apply_role_model("strategist")
        self._log_event(
            "agent_execute_start",
            role="strategist",
            model=self.llm_client.config.model,
            **self._get_role_route_payload("strategist"),
        )
        t0 = time.time()
        result = self.strategist.execute(self.context)
        dt = int((time.time() - t0) * 1000)
        self._log_event(
            "agent_execute_end",
            role="strategist",
            model=self.llm_client.config.model,
            success=result.success,
            latency_ms=dt,
            **self._get_role_route_payload("strategist"),
        )

        if self._handle_llm_failure(result, "strategist"):
            return

        if not result.success:
            logger.error(f"Strategist échoué: {result.errors}")
            self._log_event("error", scope="strategist", message=str(result.errors))
            self._errors.extend(result.errors)
            # Sans propositions, on va directement à la validation
            self.context.strategist_proposals = []
            self.state_machine.transition_to(AgentState.VALIDATE)
            return

        # Détecter si Strategist demande un sweep au lieu de proposals
        sweep_request = result.data.get("sweep", None)
        if sweep_request:
            logger.info("🔍 Strategist demande un grid search (sweep)")
            self._handle_sweep_proposal(sweep_request)
            return

        # Stocker les propositions
        proposals = result.data.get("proposals", [])
        proposals = proposals[:self.config.max_proposals_per_iteration]

        # Filtrer les propositions déjà testées dans cette session
        filtered_proposals = []
        duplicates_count = 0
        for proposal in proposals:
            params = proposal.get("parameters", {})
            if not params:
                continue

            # Vérifier si déjà testé
            if self.param_tracker.was_tested(params):
                duplicates_count += 1
                logger.info(
                    f"  ⚠️ Proposition ignorée (déjà testée): {proposal.get('name', 'N/A')}"
                )
                continue

            filtered_proposals.append(proposal)

        self.context.strategist_proposals = filtered_proposals
        self._log_event(
            "proposals_generated",
            count=len(self.context.strategist_proposals),
            duplicates_filtered=duplicates_count
        )
        logger.info(
            f"Strategist: {len(proposals)} propositions générées, "
            f"{duplicates_count} duplications filtrées, "
            f"{len(filtered_proposals)} nouvelles"
        )

        # Si toutes les propositions étaient des duplications
        if proposals and not filtered_proposals:
            logger.warning("Toutes les propositions sont des duplications - passage à VALIDATE")
            self.state_machine.transition_to(AgentState.VALIDATE)
            return

        # Transition vers CRITIQUE
        self.state_machine.transition_to(AgentState.CRITIQUE)

    def _handle_sweep_proposal(self, sweep_request: Dict[str, Any]) -> None:
        """
        Gère un sweep request du Strategist (grid search).

        Args:
            sweep_request: Dict avec ranges, rationale, optimize_for, max_combinations
        """
        self._log_event("sweep_request", details=sweep_request)
        logger.info(f"  Sweep rationale: {sweep_request.get('rationale', 'N/A')}")

        # Vérifier la limite de sweeps
        if self._sweeps_performed >= self._max_sweeps_per_session:
            logger.warning(
                f"⚠️ Limite de sweeps atteinte ({self._max_sweeps_per_session}). "
                f"Sweep request ignoré."
            )
            self._warnings.append(
                f"Sweep limit reached ({self._sweeps_performed}/{self._max_sweeps_per_session})"
            )
            # Passer à VALIDATE sans proposals
            self.context.strategist_proposals = []
            self.state_machine.transition_to(AgentState.VALIDATE)
            return

        # Vérifier si ces ranges ont déjà été testées
        ranges = sweep_request.get("ranges", {})
        if self._ranges_tracker.was_tested(ranges):
            logger.warning(
                f"⚠️ Ranges déjà testées dans cette session! | "
                f"Params={list(ranges.keys())} | "
                f"Forcing diversification..."
            )
            self._warnings.append(
                f"Ranges already tested: {list(ranges.keys())}"
            )
            # Passer à VALIDATE sans proposals
            self.context.strategist_proposals = []
            self.state_machine.transition_to(AgentState.VALIDATE)
            return

        try:
            # Importer run_llm_sweep
            from utils.parameters import RangeProposal

            from .integration import run_llm_sweep

            # Créer RangeProposal depuis sweep_request
            range_proposal = RangeProposal(
                ranges=sweep_request.get("ranges", {}),
                rationale=sweep_request.get("rationale", ""),
                optimize_for=sweep_request.get("optimize_for", "sharpe_ratio"),
                max_combinations=sweep_request.get("max_combinations", 100),
            )

            # Extraire param_specs depuis le contexte
            param_specs = []
            if hasattr(self.context, 'param_specs'):
                param_specs = self.context.param_specs
            elif hasattr(self.context, 'parameter_configs'):
                # Convertir ParameterConfig → ParameterSpec
                from utils.parameters import ParameterSpec
                for pc in self.context.parameter_configs:
                    param_specs.append(ParameterSpec(
                        name=pc.name,
                        min_val=pc.bounds[0],
                        max_val=pc.bounds[1],
                        default=pc.current_value,
                        step=pc.step,
                        param_type="int" if pc.value_type == "int" else "float"
                    ))

            if not param_specs:
                raise RuntimeError("Impossible d'extraire param_specs du contexte")

            # Récupérer les données
            if self._loaded_data is None:
                logger.error("sweep_impossible reason=no_data")
                raise RuntimeError("Données non disponibles pour sweep")

            # Exécuter le sweep
            logger.info(
                f"  Lancement sweep: {len(range_proposal.ranges)} paramètres, "
                f"max {range_proposal.max_combinations} combinaisons"
            )
            self._log_event("sweep_start", n_params=len(range_proposal.ranges))

            sweep_results = run_llm_sweep(
                range_proposal=range_proposal,
                param_specs=param_specs,
                data=self._loaded_data,
                strategy_name=self.context.strategy_name,
                initial_capital=10000.0,  # Utiliser capital depuis contexte si disponible
                n_workers=None,  # Auto-detect
            )

            # Incrémenter les compteurs de budget
            n_combinations = sweep_results['n_combinations']
            self._sweeps_performed += 1
            self._total_combinations_tested += n_combinations

            # Enregistrer les ranges testées dans le tracker
            best_sharpe = sweep_results['best_metrics'].get('sharpe_ratio', 0)
            self._ranges_tracker.register(
                ranges=range_proposal.ranges,
                n_combinations=n_combinations,
                best_sharpe=best_sharpe,
                rationale=range_proposal.rationale
            )

            logger.info(
                f"✅ Sweep #{self._sweeps_performed} terminé: {n_combinations} combinaisons testées | "
                f"Best {range_proposal.optimize_for}={sweep_results['best_metrics'].get(range_proposal.optimize_for, 0):.3f} | "
                f"Budget: {self._total_combinations_tested}/{self._max_iter_label} combos"
            )
            self._log_event(
                "sweep_complete",
                n_combinations=n_combinations,
                sweeps_performed=self._sweeps_performed,
                total_combinations_tested=self._total_combinations_tested,
                best_metrics=sweep_results['best_metrics']
            )

            # Stocker les résultats dans le contexte
            self.context.sweep_results = sweep_results
            self.context.sweep_summary = sweep_results['summary']

            # Créer une proposition artificielle depuis le meilleur config
            best_proposal = {
                "id": 1,
                "name": f"Sweep Best Config ({range_proposal.optimize_for}={sweep_results['best_metrics'].get(range_proposal.optimize_for, 0):.3f})",
                "priority": "HIGH",
                "risk_level": "LOW",
                "parameters": sweep_results['best_params'],
                "rationale": f"Best config from grid search: {range_proposal.rationale}",
                "expected_impact": sweep_results['best_metrics'],
                "risks": ["Config from grid search, may not generalize"],
            }

            self.context.strategist_proposals = [best_proposal]
            logger.info(f"  Meilleurs paramètres: {sweep_results['best_params']}")

            # Transition vers CRITIQUE pour valider le meilleur config
            self.state_machine.transition_to(AgentState.CRITIQUE)

        except Exception as e:
            logger.error(f"Erreur durant le sweep: {e}")
            self._log_event("sweep_failed", error=str(e))
            self._errors.append(f"Sweep failed: {str(e)}")

            # En cas d'erreur, passer à VALIDATE sans proposals
            self.context.strategist_proposals = []
            self.state_machine.transition_to(AgentState.VALIDATE)

    def _handle_critique(self) -> None:
        """Gère l'état CRITIQUE - Exécution de l'Agent Critic."""
        self._log_event("phase_start", phase="CRITIQUE")
        logger.info("Phase CRITIQUE: Exécution Agent Critic")

        if not self.context.strategist_proposals:
            logger.warning("Aucune proposition à critiquer")
            self._log_event("warning", message="Aucune proposition à critiquer")
            self.state_machine.transition_to(AgentState.VALIDATE)
            return

        # Exécuter le Critic
        self._apply_role_model("critic")
        self._log_event(
            "agent_execute_start",
            role="critic",
            model=self.llm_client.config.model,
            **self._get_role_route_payload("critic"),
        )
        t0 = time.time()
        result = self.critic.execute(self.context)
        dt = int((time.time() - t0) * 1000)
        self._log_event(
            "agent_execute_end",
            role="critic",
            model=self.llm_client.config.model,
            success=result.success,
            latency_ms=dt,
            **self._get_role_route_payload("critic"),
        )

        if self._handle_llm_failure(result, "critic"):
            return

        if not result.success:
            logger.error(f"Critic échoué: {result.errors}")
            self._log_event("error", scope="critic", message=str(result.errors))
            self._errors.extend(result.errors)
            # Continuer avec les propositions non filtrées
            self.context.critic_concerns = []
        else:
            # Mettre à jour avec les propositions filtrées
            approved = result.data.get("approved_proposals", [])
            if approved:
                self.context.strategist_proposals = approved

            self.context.critic_assessment = result.content
            self.context.critic_concerns = result.data.get("concerns", [])
            self._log_event(
                "critic_result",
                approved_count=len(approved),
                concerns_count=len(self.context.critic_concerns),
            )
            logger.info(
                f"Critic: {len(approved)} propositions approuvées, "
                f"{len(self.context.critic_concerns)} concerns"
            )

        # Tester les propositions approuvées
        self._test_proposals()

        # Transition vers VALIDATE
        self.state_machine.transition_to(AgentState.VALIDATE)

    def _handle_validate(self) -> None:
        """Gère l'état VALIDATE - Exécution de l'Agent Validator."""
        self._log_event("phase_start", phase="VALIDATE")
        logger.info("Phase VALIDATE: Exécution Agent Validator")

        # Exécuter le Validator
        self._apply_role_model("validator")
        self._log_event(
            "agent_execute_start",
            role="validator",
            model=self.llm_client.config.model,
            **self._get_role_route_payload("validator"),
        )
        t0 = time.time()
        result = self.validator.execute(self.context)
        dt = int((time.time() - t0) * 1000)
        self._log_event(
            "agent_execute_end",
            role="validator",
            model=self.llm_client.config.model,
            success=result.success,
            latency_ms=dt,
            **self._get_role_route_payload("validator"),
        )

        if self._handle_llm_failure(result, "validator"):
            return

        if not result.success:
            logger.error(f"Validator échoué: {result.errors}")
            self._log_event("error", scope="validator", message=str(result.errors))
            self._errors.extend(result.errors)
            # Par défaut, on itère si le validator échoue
            decision = ValidationDecision.ITERATE
            self._last_validation_data = None
            self._last_validator_summary = ""
        else:
            decision_str = result.data.get("decision", "ITERATE")
            try:
                decision = ValidationDecision(decision_str)
            except ValueError:
                decision = ValidationDecision.ITERATE
            self._last_validation_data = result.data
            self._last_validator_summary = result.content or ""

        logger.info(f"Validator décision: {decision.value}")
        self._log_event("validator_decision", decision=decision.value)

        # Enregistrer l'historique de l'itération
        self._record_iteration(decision.value)

        # Transition selon la décision
        if decision == ValidationDecision.APPROVE:
            self.state_machine.transition_to(AgentState.APPROVED)
        elif decision == ValidationDecision.REJECT:
            self.state_machine.transition_to(AgentState.REJECTED)
        elif decision == ValidationDecision.ABORT:
            self.state_machine.fail("Validator a décidé ABORT")
        else:  # ITERATE
            # Vérifier si on peut encore itérer
            if self.state_machine.can_transition_to(AgentState.ITERATE):
                self.state_machine.transition_to(AgentState.ITERATE)
            else:
                logger.info("Max iterations atteint, passage en REJECTED")
                self.state_machine.transition_to(AgentState.REJECTED)

    def _handle_iterate(self) -> None:
        """Gère l'état ITERATE - Préparation de l'itération suivante."""
        self._log_event("phase_start", phase="ITERATE")
        logger.info("Phase ITERATE: Préparation itération suivante")

        # Sélectionner la meilleure configuration testée
        best_tested = self._get_best_tested_config()
        if best_tested:
            self.context.current_params = best_tested["params"]
            if best_tested.get("metrics"):
                self.context.current_metrics = best_tested["metrics"]

                # Mettre à jour le best si meilleur
                if (
                    self.context.best_metrics is None
                    or best_tested["metrics"].sharpe_ratio
                    > self.context.best_metrics.sharpe_ratio
                ):
                    self.context.best_metrics = best_tested["metrics"]
                    self.context.best_params = best_tested["params"].copy()

        # Nettoyer les propositions
        self.context.strategist_proposals = []
        self.context.critic_concerns = []

        # Callback itération complète
        if self.config.on_iteration_complete:
            self.config.on_iteration_complete(
                self.state_machine.iteration,
                {"metrics": self.context.current_metrics, "params": self.context.current_params}
            )

        # Vérifier le budget de combinaisons testées avant la prochaine itération
        if (not self._unlimited_iterations) and self._total_combinations_tested >= self.config.max_iterations:
            logger.warning(
                f"⚠️ Budget épuisé: {self._total_combinations_tested} combos testées "
                f"(limite: {self.config.max_iterations}, dont {self._sweeps_performed} sweeps)"
            )
            self._warnings.append(
                f"Budget épuisé: {self._total_combinations_tested}/{self.config.max_iterations} combos"
            )
            # Transition vers REJECTED car budget épuisé
            self.state_machine.transition_to(AgentState.REJECTED)
            return

        # Transition vers ANALYZE
        self.state_machine.transition_to(AgentState.ANALYZE)

    def _validate_config(self) -> ValidationResult:
        """Valide la configuration initiale."""
        errors = []

        if not self.config.strategy_name:
            errors.append("strategy_name requis")

        if self.config.data_path:
            if not Path(self.config.data_path).exists():
                errors.append(f"data_path n'existe pas: {self.config.data_path}")
        elif self.config.on_backtest_needed is None:
            errors.append("data_path requis")

        if not self.config.param_specs:
            errors.append("param_specs requis (au moins un paramètre)")

        if errors:
            return ValidationResult.failure("; ".join(errors), errors)

        return ValidationResult.success()

    def _run_backtest(self, params: Dict[str, Any]) -> Optional[MetricsSnapshot]:
        """
        Exécute un backtest avec les paramètres donnés.

        Utilise le callback on_backtest_needed si fourni,
        sinon retourne None.
        """
        self._backtests_count += 1
        self._total_combinations_tested += 1  # Compter cette combinaison vers le budget
        self._log_event("backtest_start", source="orchestrator", params=params)

        if self.config.on_backtest_needed:
            try:
                result = self.config.on_backtest_needed(params)
                if result:
                    metrics = MetricsSnapshot.from_dict(result)
                    self._log_event(
                        "backtest_end",
                        success=True,
                        sharpe=metrics.sharpe_ratio,
                        total_return=metrics.total_return,
                        max_drawdown=metrics.max_drawdown,
                    )
                    return metrics
            except Exception as e:
                logger.error(f"Erreur backtest: {e}")
                self._warnings.append(f"Backtest échoué: {e}")
                self._log_event("backtest_end", success=False, error=str(e))

        return None

    def _compute_walk_forward_metrics(self) -> None:
        """
        Calcule les métriques de walk-forward validation et met à jour le contexte.

        Charge les données si nécessaire et exécute une validation walk-forward
        pour détecter l'overfitting avec les métriques robustes.
        """
        # Si on a déjà des données en mémoire (UI), on les utilise.
        if self._loaded_data is not None:
            data_df = self._loaded_data
            try:
                self.context.data_rows = len(data_df)
            except Exception:
                pass

            try:
                wf_metrics = run_walk_forward_for_agent(
                    strategy_name=self.config.strategy_name,
                    params=self.context.current_params,
                    data=data_df,
                    n_windows=6,
                    train_ratio=0.75,
                    n_workers=self.config.n_workers,
                )

                self.context.overfitting_ratio = wf_metrics["overfitting_ratio"]
                self.context.classic_ratio = wf_metrics["classic_ratio"]
                self.context.degradation_pct = wf_metrics["degradation_pct"]
                self.context.test_stability_std = wf_metrics["test_stability_std"]
                self.context.n_valid_folds = wf_metrics["n_valid_folds"]
                self.context.walk_forward_windows = 6

                self._log_event(
                    "walk_forward_computed",
                    overfitting_ratio=float(wf_metrics["overfitting_ratio"]),
                    classic_ratio=float(wf_metrics["classic_ratio"]),
                    degradation_pct=float(wf_metrics["degradation_pct"]),
                    test_stability_std=float(wf_metrics["test_stability_std"]),
                    n_valid_folds=int(wf_metrics["n_valid_folds"]),
                )
            except Exception as e:
                logger.warning(f"Échec du calcul des métriques walk-forward: {e}")
                self._warnings.append(f"Walk-forward échoué: {e}")
                self._log_event("warning", message=f"Walk-forward échoué: {e}")

            return

        # Vérifier si un chemin de données est fourni
        if not self.config.data_path:
            logger.debug("Pas de data/data_path configuré, skip walk-forward metrics")
            return

        data_path = Path(self.config.data_path)
        if not data_path.exists():
            logger.warning(f"Fichier de données introuvable: {data_path}")
            return

        try:
            # Charger les données si pas déjà fait
            if self._loaded_data is None:
                logger.info(f"Chargement des données depuis {data_path}")
                import pandas as pd

                # Charger selon l'extension
                if data_path.suffix == '.csv':
                    self._loaded_data = pd.read_csv(data_path)
                elif data_path.suffix == '.parquet':
                    self._loaded_data = pd.read_parquet(data_path)
                else:
                    logger.warning(f"Format non supporté pour walk-forward: {data_path.suffix}")
                    return

                logger.info(f"  Données chargées: {len(self._loaded_data)} lignes")

            # Mettre à jour le contexte avec les infos sur les données
            self.context.data_rows = len(self._loaded_data)

            # Extraire la plage de dates si disponible
            if 'timestamp' in self._loaded_data.columns or 'date' in self._loaded_data.columns:
                date_col = 'timestamp' if 'timestamp' in self._loaded_data.columns else 'date'
                try:
                    import pandas as pd
                    dates = pd.to_datetime(self._loaded_data[date_col])
                    self.context.data_date_range = f"{dates.min()} → {dates.max()}"
                except Exception:
                    pass

            # Exécuter la validation walk-forward
            logger.info("Exécution de la validation walk-forward...")
            wf_metrics = run_walk_forward_for_agent(
                strategy_name=self.config.strategy_name,
                params=self.context.current_params,
                data=self._loaded_data,
                n_windows=6,
                train_ratio=0.75,
                n_workers=self.config.n_workers,
            )

            # Mettre à jour le contexte avec les métriques
            self.context.overfitting_ratio = wf_metrics["overfitting_ratio"]
            self.context.classic_ratio = wf_metrics["classic_ratio"]
            self.context.degradation_pct = wf_metrics["degradation_pct"]
            self.context.test_stability_std = wf_metrics["test_stability_std"]
            self.context.n_valid_folds = wf_metrics["n_valid_folds"]
            self.context.walk_forward_windows = 6

            logger.info(
                f"Walk-forward terminé: "
                f"overfitting_ratio={wf_metrics['overfitting_ratio']:.3f}, "
                f"degradation={wf_metrics['degradation_pct']:.1f}%, "
                f"stability_std={wf_metrics['test_stability_std']:.3f}"
            )

            # Journaliser l'événement
            self._log_event(
                "walk_forward_computed",
                overfitting_ratio=float(wf_metrics["overfitting_ratio"]),
                classic_ratio=float(wf_metrics["classic_ratio"]),
                degradation_pct=float(wf_metrics["degradation_pct"]),
                test_stability_std=float(wf_metrics["test_stability_std"]),
                n_valid_folds=int(wf_metrics["n_valid_folds"]),
            )

        except Exception as e:
            logger.warning(f"Échec du calcul des métriques walk-forward: {e}")
            self._warnings.append(f"Walk-forward échoué: {e}")
            self._log_event("warning", message=f"Walk-forward échoué: {e}")

    def _test_proposals(self) -> None:
        """Teste les propositions approuvées via backtest."""
        proposals = list(self.context.strategist_proposals or [])
        if not proposals:
            return

        def _eval_one(proposal: Dict[str, Any]) -> tuple[Dict[str, Any], Optional[MetricsSnapshot]]:
            params = proposal.get("parameters", {})
            if not params:
                return proposal, None
            return proposal, self._run_backtest(params)

        n_workers = int(getattr(self.config, "n_workers", 1) or 1)

        # Séquentiel par défaut
        if n_workers <= 1 or len(proposals) <= 1:
            # Barre de progression pour les tests de propositions
            proposal_iterator = tqdm(
                proposals,
                desc="Testing proposals",
                unit="proposal",
                disable=not TQDM_AVAILABLE,
                leave=False
            ) if len(proposals) > 1 else proposals

            for proposal in proposal_iterator:
                params = proposal.get("parameters", {})
                if not params:
                    continue

                self._log_event(
                    "proposal_test_started",
                    proposal_id=proposal.get("id"),
                    proposal_name=proposal.get("name"),
                )
                logger.info(f"Test proposition {proposal.get('id')}: {proposal.get('name')}")

                metrics = self._run_backtest(params)
                if metrics:
                    proposal["tested_metrics"] = metrics.to_dict()
                    proposal["tested"] = True

                    # Enregistrer dans le tracker de session
                    self.param_tracker.register(
                        params=params,
                        sharpe_ratio=metrics.sharpe_ratio,
                        total_return=metrics.total_return
                    )

                    self._log_event(
                        "proposal_test_ended",
                        proposal_id=proposal.get("id"),
                        tested=True,
                        sharpe=metrics.sharpe_ratio,
                        total_return=metrics.total_return,
                    )
                else:
                    proposal["tested"] = False
                    self._log_event(
                        "proposal_test_ended",
                        proposal_id=proposal.get("id"),
                        tested=False,
                    )
            return

        # Parallèle: le slider workers a enfin un effet réel en multi-agents
        from concurrent.futures import ThreadPoolExecutor, as_completed

        for proposal in proposals:
            if proposal.get("parameters", {}):
                self._log_event(
                    "proposal_test_started",
                    proposal_id=proposal.get("id"),
                    proposal_name=proposal.get("name"),
                )

        futures = {}
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            for proposal in proposals:
                if not proposal.get("parameters", {}):
                    continue
                futures[pool.submit(_eval_one, proposal)] = proposal

            for fut in as_completed(futures):
                proposal = futures[fut]
                try:
                    _, metrics = fut.result()
                except Exception as e:
                    metrics = None
                    self._warnings.append(f"Backtest proposition échoué: {e}")
                    self._log_event(
                        "proposal_test_ended",
                        proposal_id=proposal.get("id"),
                        tested=False,
                        error=str(e),
                    )
                    continue

                if metrics:
                    proposal["tested_metrics"] = metrics.to_dict()
                    proposal["tested"] = True

                    # Enregistrer dans le tracker de session
                    self.param_tracker.register(
                        params=proposal.get("parameters", {}),
                        sharpe_ratio=metrics.sharpe_ratio,
                        total_return=metrics.total_return
                    )

                    self._log_event(
                        "proposal_test_ended",
                        proposal_id=proposal.get("id"),
                        tested=True,
                        sharpe=metrics.sharpe_ratio,
                        total_return=metrics.total_return,
                    )
                else:
                    proposal["tested"] = False
                    self._log_event(
                        "proposal_test_ended",
                        proposal_id=proposal.get("id"),
                        tested=False,
                    )

    def _get_best_tested_config(self) -> Optional[Dict[str, Any]]:
        """Retourne la meilleure configuration testée."""
        best = None
        best_sharpe = float("-inf")

        for proposal in self.context.strategist_proposals:
            if not proposal.get("tested"):
                continue

            metrics_dict = proposal.get("tested_metrics", {})
            sharpe = metrics_dict.get("sharpe_ratio", 0)

            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best = {
                    "params": proposal.get("parameters", {}),
                    "metrics": MetricsSnapshot.from_dict(metrics_dict),
                }

        return best

    def _record_iteration(self, decision: Optional[str] = None) -> None:
        """Enregistre l'itération actuelle dans l'historique."""
        entry = {
            "iteration": self.state_machine.iteration,
            "timestamp": datetime.now().isoformat(),
            "params": self.context.current_params.copy(),
        }

        if self.context.current_metrics:
            entry.update({
                "sharpe_ratio": self.context.current_metrics.sharpe_ratio,
                "total_return": self.context.current_metrics.total_return,
                "max_drawdown": self.context.current_metrics.max_drawdown,
            })

        entry["proposals_count"] = len(self.context.strategist_proposals)
        entry["concerns_count"] = len(self.context.critic_concerns)
        if decision:
            entry["decision"] = decision

        self.context.iteration_history.append(entry)

        # Journalisation non bloquante
        self._log_event(
            "iteration_recorded",
            iteration=entry["iteration"],
            sharpe=entry.get("sharpe_ratio"),
            total_return=entry.get("total_return"),
            max_drawdown=entry.get("max_drawdown"),
            proposals_count=entry.get("proposals_count", 0),
            concerns_count=entry.get("concerns_count", 0),
            decision=decision,
        )
        self._append_memory_iteration(entry)

    def _generate_final_report(self) -> str:
        """Génère un rapport final détaillé incluant les statistiques du tracker."""
        lines = [
            "=" * 80,
            "📊 RAPPORT FINAL D'OPTIMISATION MULTI-AGENTS",
            "=" * 80,
            "",
            f"🔖 Session ID: {self.session_id}",
            f"📈 Stratégie: {self.config.strategy_name}",
            f"🔄 Itérations totales: {self.state_machine.iteration}",
            f"🧪 Backtests exécutés: {self._backtests_count}",
            f"🤖 Combinaisons testées: {self._total_combinations_tested}",
            f"🔍 Sweeps effectués: {self._sweeps_performed}/{self._max_sweeps_per_session}",
            "",
        ]

        # État final de la machine à états
        final_state = self.state_machine.current_state
        lines.extend([
            "📌 DÉCISION FINALE:",
            f"  État: {final_state.name}",
            f"  Décision: {'✅ APPROUVÉ' if final_state == AgentState.APPROVED else '❌ REJETÉ' if final_state == AgentState.REJECTED else '⚠️ AVORTÉ'}",
            "",
        ])

        # Walk-forward validation status
        if self.config.walk_forward_disabled_reason:
            lines.extend([
                "⚠️ WALK-FORWARD VALIDATION:",
                "  Status: DÉSACTIVÉ AUTOMATIQUEMENT",
                f"  Raison: {self.config.walk_forward_disabled_reason}",
                "",
            ])
        elif self.config.use_walk_forward:
            lines.extend([
                "✅ WALK-FORWARD VALIDATION:",
                "  Status: ACTIVÉ",
                f"  Windows: {self.config.walk_forward_windows}",
                f"  Train ratio: {self.config.train_ratio:.0%}",
                "",
            ])

        # Résultats finaux
        if self.context.best_metrics:
            lines.extend([
                "🏆 MEILLEURS RÉSULTATS OBTENUS:",
                f"  📊 Sharpe Ratio: {self.context.best_metrics.sharpe_ratio:.3f}",
                f"  💰 Total Return: {self.context.best_metrics.total_return:.2%}",
                f"  📉 Max Drawdown: {self.context.best_metrics.max_drawdown:.2%}",
                f"  🎯 Win Rate: {self.context.best_metrics.win_rate:.1%}" if hasattr(self.context.best_metrics, 'win_rate') else "",
                f"  🔢 Total Trades: {self.context.best_metrics.total_trades}",
                "",
                "⚙️  Paramètres optimaux:",
            ])
            for k, v in (self.context.best_params or {}).items():
                if isinstance(v, float):
                    lines.append(f"    • {k}: {v:.4f}")
                else:
                    lines.append(f"    • {k}: {v}")
            lines.append("")

        # Activité des agents multi-agents
        lines.extend([
            "=" * 80,
            "🤖 ACTIVITÉ DES AGENTS",
            "=" * 80,
            "",
        ])

        # Statistiques par agent
        def _get_agent_stats(agent: BaseAgent, name: str) -> List[str]:
            stats = getattr(agent, "stats", {})
            tokens = stats.get("total_tokens", 0)
            calls = stats.get("execution_count", 0)
            return [
                f"🔹 {name}:",
                f"    Appels LLM: {calls}",
                f"    Tokens utilisés: {tokens:,}",
            ]

        lines.extend(_get_agent_stats(self.analyst, "Agent Analyst"))
        lines.extend(_get_agent_stats(self.strategist, "Agent Strategist"))
        lines.extend(_get_agent_stats(self.critic, "Agent Critic"))
        lines.extend(_get_agent_stats(self.validator, "Agent Validator"))
        lines.append("")

        # Historique des itérations
        if self.context.iteration_history:
            lines.extend([
                "=" * 80,
                "📜 HISTORIQUE DES ITÉRATIONS",
                "=" * 80,
                "",
            ])
            for i, hist in enumerate(self.context.iteration_history[-10:], 1):  # Dernières 10
                iter_num = hist.get("iteration", i)
                sharpe = hist.get("sharpe_ratio", 0)
                ret = hist.get("total_return", 0)
                params = hist.get("params", {})
                decision = hist.get("decision", "N/A")

                lines.extend([
                    f"Itération #{iter_num}:",
                    f"  Sharpe: {sharpe:.3f} | Return: {ret:.2%}",
                    f"  Décision: {decision}",
                ])
                if params and len(params) <= 5:  # Afficher params si peu nombreux
                    param_str = ", ".join(f"{k}={v}" for k, v in params.items())
                    lines.append(f"  Params: {param_str}")
                lines.append("")

        # Statistiques de sweep (si utilisés)
        if self._sweeps_performed > 0:
            lines.extend([
                "=" * 80,
                "🔍 STATISTIQUES GRID SEARCH (SWEEPS)",
                "=" * 80,
                "",
                f"  Nombre de sweeps: {self._sweeps_performed}",
                f"  Limite par session: {self._max_sweeps_per_session}",
                f"  Combinaisons testées via sweeps: {self._total_combinations_tested - self._backtests_count}",
                "",
            ])

            # Ranges testées (si tracker disponible)
            if hasattr(self, '_ranges_tracker'):
                ranges_summary = self._ranges_tracker.get_summary(max_ranges=5)
                if ranges_summary != "Aucune range testée dans cette session.":
                    lines.extend([
                        "Ranges explorées:",
                        ranges_summary,
                        "",
                    ])

        # Statistiques du tracker de paramètres
        if hasattr(self, 'param_tracker'):
            lines.extend([
                "=" * 80,
                "📊 STATISTIQUES DE SESSION",
                "=" * 80,
                "",
                f"  ✅ Tests uniques: {self.param_tracker.get_tested_count()}",
                f"  🔄 Duplications évitées: {self.param_tracker.get_duplicates_prevented()}",
                "",
            ])

            # Meilleurs paramètres selon le tracker
            best_sharpe = self.param_tracker.get_best_params("sharpe_ratio")
            if best_sharpe:
                lines.extend([
                    "🏅 Meilleur Sharpe Ratio testé:",
                    f"    Valeur: {best_sharpe.sharpe_ratio:.3f}",
                    f"    Return: {best_sharpe.total_return:.2%}" if hasattr(best_sharpe, 'total_return') and best_sharpe.total_return else "",
                    "    Paramètres:",
                ])
                for k, v in best_sharpe.params.items():
                    if isinstance(v, float):
                        lines.append(f"      • {k}: {v:.4f}")
                    else:
                        lines.append(f"      • {k}: {v}")
                lines.append("")

        # Warnings et erreurs
        if self._warnings or self._errors:
            lines.extend([
                "=" * 80,
                "⚠️  AVERTISSEMENTS ET ERREURS",
                "=" * 80,
                "",
            ])
            if self._warnings:
                lines.extend([
                    "Avertissements:",
                    *[f"  ⚠️  {w}" for w in self._warnings],
                    "",
                ])
            if self._errors:
                lines.extend([
                    "Erreurs:",
                    *[f"  ❌ {e}" for e in self._errors],
                    "",
                ])

        lines.append("=" * 80)
        return "\n".join(lines)

    def _build_result(self) -> OrchestratorResult:
        """Construit le résultat final."""
        elapsed = time.time() - self._start_time if self._start_time else 0

        # Déterminer la décision finale
        final_state = self.state_machine.current_state
        if final_state == AgentState.APPROVED:
            decision = "APPROVE"
            success = True
        elif final_state == AgentState.REJECTED:
            decision = "REJECT"
            success = False
        else:
            decision = "ABORT"
            success = False

        # Statistiques LLM (avec fallback si agent n'a pas de stats)
        def _get_agent_stats(agent: BaseAgent) -> Dict[str, int]:
            """Récupère les stats d'un agent de manière sûre."""
            stats = getattr(agent, "stats", {})
            return {
                "total_tokens": stats.get("total_tokens", 0),
                "execution_count": stats.get("execution_count", 0),
            }

        agents = [self.analyst, self.strategist, self.critic, self.validator]
        total_tokens = sum(_get_agent_stats(a)["total_tokens"] for a in agents)
        total_calls = sum(_get_agent_stats(a)["execution_count"] for a in agents)

        # Générer le rapport final avec statistiques du tracker
        final_report = self._generate_final_report()

        # Recommandations basées sur le tracker
        recommendations = []
        if hasattr(self, 'param_tracker'):
            duplicates = self.param_tracker.get_duplicates_prevented()
            if duplicates > 0:
                recommendations.append(
                    f"✅ {duplicates} duplications de paramètres évitées durant la session"
                )
            if self.param_tracker.get_tested_count() > 0:
                recommendations.append(
                    f"📊 {self.param_tracker.get_tested_count()} combinaisons uniques testées"
                )

        return OrchestratorResult(
            success=success,
            final_state=final_state,
            decision=decision,
            final_params=self.context.best_params or self.context.current_params,
            final_metrics=self.context.best_metrics,
            total_iterations=self.state_machine.iteration,
            total_backtests=self._backtests_count,
            total_time_s=elapsed,
            total_llm_tokens=total_tokens,
            total_llm_calls=total_calls,
            iteration_history=self.context.iteration_history,
            state_history=self.state_machine.get_summary()["history"],
            final_report=final_report,
            recommendations=recommendations,
            errors=self._errors,
            warnings=self._warnings,
        )
