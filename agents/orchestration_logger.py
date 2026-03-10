"""
Module-ID: agents.orchestration_logger

Purpose: Tracer toutes les actions des agents LLM en JSONL avec auto-save thread-safe et callback UI.

Role in pipeline: orchestration / monitoring

Key components: OrchestrationLogger, OrchestrationLogEntry, OrchestrationActionType, get_orchestration_logger

Inputs: action_type, données contexte, session_id

Outputs: Logs JSONL dans runs/<session>/trace.jsonl, callbacks UI optionnels

Dependencies: pathlib, json, threading, utils.log

Conventions: JSONL auto-flush toutes les N entrées; thread-safe via Lock; singleton global; timestamps UTC; callback optionnel pour UI temps réel.

Read-if: Ajout types actions, modification format JSONL, ou intégration UI.

Skip-if: Vous ne debuggez pas l'orchestration.
"""

# pylint: disable=logging-fstring-interpolation

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from utils.log import get_logger

logger = get_logger(__name__)


class OrchestrationActionType(Enum):
    """

Types d'actions d'orchestration."""

    # Cycle de vie orchestration
    RUN_START = "run_start"
    RUN_END = "run_end"
    PHASE_START = "phase_start"

    # Machine à états
    STATE_ENTER = "state_enter"
    STATE_CHANGE = "state_change"
    STATE_EXIT = "state_exit"

    # Agents LLM
    AGENT_EXECUTE_START = "agent_execute_start"
    AGENT_EXECUTE_END = "agent_execute_end"
    ANALYST_RESULT = "analyst_result"
    PROPOSALS_GENERATED = "proposals_generated"
    CRITIC_RESULT = "critic_result"
    VALIDATOR_DECISION = "validator_decision"

    # Propositions et tests
    PROPOSAL_TEST_STARTED = "proposal_test_started"
    PROPOSAL_TEST_ENDED = "proposal_test_ended"

    # Itérations
    ITERATION_RECORDED = "iteration_recorded"

    # Analyse
    ANALYSIS_START = "analysis_start"
    ANALYSIS_COMPLETE = "analysis_complete"
    RESULT_EVALUATION = "result_evaluation"

    # Stratégie
    STRATEGY_SELECTION = "strategy_selection"
    STRATEGY_MODIFICATION = "strategy_modification"
    STRATEGY_VALIDATION = "strategy_validation"

    # Indicateurs
    INDICATOR_VALUES_CHANGE = "indicator_values_change"
    INDICATOR_ADD = "indicator_add"
    INDICATOR_REMOVE = "indicator_remove"
    INDICATOR_VALIDATION = "indicator_validation"
    INDICATOR_CONTEXT = "indicator_context"

    # Tests
    BACKTEST_START = "backtest_start"
    BACKTEST_END = "backtest_end"
    BACKTEST_LAUNCH = "backtest_launch"
    BACKTEST_COMPLETE = "backtest_complete"
    BACKTEST_FAILED = "backtest_failed"

    # Walk-forward
    WALK_FORWARD_COMPUTED = "walk_forward_computed"

    # Décisions
    DECISION_CONTINUE = "decision_continue"
    DECISION_STOP = "decision_stop"
    DECISION_CHANGE_APPROACH = "decision_change_approach"

    # Agents (legacy)
    AGENT_ANALYST_ACTION = "agent_analyst"
    AGENT_STRATEGIST_ACTION = "agent_strategist"
    AGENT_CRITIC_ACTION = "agent_critic"
    AGENT_VALIDATOR_ACTION = "agent_validator"

    # Configuration et validation
    CONFIG_VALID = "config_valid"
    CONFIG_INVALID = "config_invalid"
    INITIAL_BACKTEST_DONE = "initial_backtest_done"

    # Warnings et erreurs
    WARNING = "warning"
    ERROR = "error"


class OrchestrationStatus(Enum):
    """Statuts d'une action d'orchestration."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    VALIDATED = "validated"
    REJECTED = "rejected"


@dataclass
class OrchestrationLogEntry:
    """Entrée de log d'orchestration."""

    timestamp: str
    action_type: OrchestrationActionType
    agent: Optional[str] = None  # Analyst, Strategist, Critic, Validator
    status: OrchestrationStatus = OrchestrationStatus.PENDING
    details: Dict[str, Any] = field(default_factory=dict)
    iteration: int = 0
    session_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire pour sérialisation."""
        return {
            "timestamp": self.timestamp,
            "action_type": self.action_type.value,
            "agent": self.agent,
            "status": self.status.value,
            "details": self.details,
            "iteration": self.iteration,
            "session_id": self.session_id,
        }

    def format_for_ui(self) -> str:
        """Formate pour affichage UI."""
        emoji = self._get_emoji()
        agent_str = f"[{self.agent}]" if self.agent else ""
        status_str = self._get_status_str()

        return f"{emoji} {agent_str} {self.action_type.value}: {status_str}"

    def _get_emoji(self) -> str:
        """Retourne l'emoji approprié."""
        if self.status == OrchestrationStatus.COMPLETED:
            return "✅"
        elif self.status == OrchestrationStatus.FAILED:
            return "❌"
        elif self.status == OrchestrationStatus.VALIDATED:
            return "✔️"
        elif self.status == OrchestrationStatus.REJECTED:
            return "❌"
        elif self.status == OrchestrationStatus.IN_PROGRESS:
            return "⏳"
        else:
            return "⏹️"

    def _get_status_str(self) -> str:
        """Retourne une chaîne de statut formatée."""
        if self.details:
            # Formater les détails importants
            if "strategy" in self.details:
                return f"Strategy={self.details['strategy']}"
            elif "indicator" in self.details:
                return f"Indicator={self.details['indicator']}"
            elif "params" in self.details:
                param_str = str(self.details['params'])[:50]
                return f"Params={param_str}..."
            elif "result" in self.details:
                result = self.details['result']
                if isinstance(result, dict) and 'sharpe' in result:
                    return f"Sharpe={result['sharpe']:.2f}"
        return self.status.value


class OrchestrationLogger:
    """Logger centralisé pour l'orchestration LLM avec persistance JSONL."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        auto_save: bool = True,
        save_path: Optional[Path] = None,
        on_event: Optional[Callable] = None,
    ):
        """
        Initialize le logger d'orchestration.

        Args:
            session_id: ID unique de session (généré auto si None)
            auto_save: Si True, sauvegarde auto toutes les 10 entrées
            save_path: Chemin personnalisé pour les logs (défaut: runs/{session_id}/trace.jsonl)
            on_event: Callback appelé à chaque nouvel événement (pour UI temps réel)
        """
        self.session_id = session_id or self._generate_session_id()
        self.logs: List[OrchestrationLogEntry] = []
        self.current_iteration = 0
        self._lock = threading.Lock()
        self._auto_save = auto_save
        self._save_path = save_path or Path("runs") / self.session_id / "trace.jsonl"
        self._save_counter = 0
        self._save_interval = 10  # Sauvegarder tous les 10 événements
        self._on_event_callback = on_event  # Callback pour mise à jour live

        # Créer le répertoire si nécessaire
        if self._auto_save:
            self._save_path.parent.mkdir(parents=True, exist_ok=True)

    def set_on_event_callback(self, callback: Callable) -> None:
        """Définit le callback appelé à chaque nouvel événement."""
        self._on_event_callback = callback

    def _notify_event(self, entry: OrchestrationLogEntry) -> None:
        """Notifie le callback si défini."""
        if self._on_event_callback:
            try:
                self._on_event_callback(entry)
            except Exception as e:
                logger.debug(f"Event callback error (ignored): {e}")

    def _generate_session_id(self) -> str:
        """Génère un ID de session unique."""
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _now(self) -> str:
        """Timestamp actuel."""
        return datetime.now().isoformat()

    def _add_entry(self, entry: OrchestrationLogEntry) -> None:
        """Ajoute une entrée et notifie le callback."""
        with self._lock:
            self.logs.append(entry)
            # Garder current_iteration cohérent (utile si l'appelant passe iteration)
            try:
                self.current_iteration = max(self.current_iteration, int(entry.iteration))
            except Exception:
                pass
        self._notify_event(entry)
        self._maybe_auto_save()

    def log_analysis_start(self, agent: str, details: Optional[Dict] = None):
        """Log le début d'une analyse."""
        entry = OrchestrationLogEntry(
            timestamp=self._now(),
            action_type=OrchestrationActionType.ANALYSIS_START,
            agent=agent,
            status=OrchestrationStatus.IN_PROGRESS,
            details=details or {},
            iteration=self.current_iteration,
            session_id=self.session_id
        )
        self._add_entry(entry)
        logger.info(f"[{agent}] Analysis started - Iteration {self.current_iteration}")

    def log_analysis_complete(
        self,
        agent: str,
        results: Dict[str, Any],
        status: OrchestrationStatus = OrchestrationStatus.COMPLETED
    ):
        """Log la fin d'une analyse."""
        entry = OrchestrationLogEntry(
            timestamp=self._now(),
            action_type=OrchestrationActionType.ANALYSIS_COMPLETE,
            agent=agent,
            status=status,
            details={"results": results},
            iteration=self.current_iteration,
            session_id=self.session_id
        )
        self._add_entry(entry)
        logger.info(f"[{agent}] Analysis complete - Status: {status.value}")

    def log_strategy_selection(
        self,
        agent: str,
        strategy_name: str,
        reason: str
    ):
        """Log la sélection d'une stratégie."""
        entry = OrchestrationLogEntry(
            timestamp=self._now(),
            action_type=OrchestrationActionType.STRATEGY_SELECTION,
            agent=agent,
            status=OrchestrationStatus.COMPLETED,
            details={"strategy": strategy_name, "reason": reason},
            iteration=self.current_iteration,
            session_id=self.session_id
        )
        self._add_entry(entry)
        logger.info(f"[{agent}] Strategy selected: {strategy_name} - {reason}")

    def log_strategy_modification(
        self,
        agent: str,
        old_strategy: str,
        new_strategy: str,
        reason: str,
        status: OrchestrationStatus = OrchestrationStatus.PENDING
    ):
        """Log une modification de stratégie."""
        entry = OrchestrationLogEntry(
            timestamp=self._now(),
            action_type=OrchestrationActionType.STRATEGY_MODIFICATION,
            agent=agent,
            status=status,
            details={
                "old_strategy": old_strategy,
                "new_strategy": new_strategy,
                "reason": reason
            },
            iteration=self.current_iteration,
            session_id=self.session_id
        )
        self._add_entry(entry)
        logger.info(f"[{agent}] Strategy changed: {old_strategy} → {new_strategy}")

    def log_indicator_values_change(
        self,
        agent: str,
        indicator: str,
        old_values: Dict[str, Any],
        new_values: Dict[str, Any],
        reason: str
    ):
        """Log un changement de valeurs d'indicateurs."""
        entry = OrchestrationLogEntry(
            timestamp=self._now(),
            action_type=OrchestrationActionType.INDICATOR_VALUES_CHANGE,
            agent=agent,
            status=OrchestrationStatus.COMPLETED,
            details={
                "indicator": indicator,
                "old_values": old_values,
                "new_values": new_values,
                "reason": reason
            },
            iteration=self.current_iteration,
            session_id=self.session_id
        )
        self._add_entry(entry)
        logger.info(f"[{agent}] Indicator {indicator} values changed")

    def log_indicator_add(
        self,
        agent: str,
        indicator: str,
        params: Dict[str, Any],
        reason: str,
        status: OrchestrationStatus = OrchestrationStatus.PENDING
    ):
        """Log l'ajout d'un nouvel indicateur."""
        entry = OrchestrationLogEntry(
            timestamp=self._now(),
            action_type=OrchestrationActionType.INDICATOR_ADD,
            agent=agent,
            status=status,
            details={
                "indicator": indicator,
                "params": params,
                "reason": reason
            },
            iteration=self.current_iteration,
            session_id=self.session_id
        )
        self._add_entry(entry)
        logger.info(f"[{agent}] New indicator proposed: {indicator}")

    def log_indicator_validation(
        self,
        agent: str,
        indicator: str,
        is_valid: bool,
        message: str
    ):
        """Log la validation d'un indicateur."""
        status = OrchestrationStatus.VALIDATED if is_valid else OrchestrationStatus.REJECTED
        entry = OrchestrationLogEntry(
            timestamp=self._now(),
            action_type=OrchestrationActionType.INDICATOR_VALIDATION,
            agent=agent,
            status=status,
            details={
                "indicator": indicator,
                "is_valid": is_valid,
                "message": message
            },
            iteration=self.current_iteration,
            session_id=self.session_id
        )
        self._add_entry(entry)
        logger.info(f"[{agent}] Indicator {indicator} validation: {is_valid}")

    def log_backtest_launch(
        self,
        agent: str,
        params: Dict[str, Any],
        combination_id: int,
        total_combinations: int
    ):
        """Log le lancement d'un backtest."""
        entry = OrchestrationLogEntry(
            timestamp=self._now(),
            action_type=OrchestrationActionType.BACKTEST_LAUNCH,
            agent=agent,
            status=OrchestrationStatus.IN_PROGRESS,
            details={
                "params": params,
                "combination_id": combination_id,
                "total_combinations": total_combinations
            },
            iteration=self.current_iteration,
            session_id=self.session_id
        )
        self._add_entry(entry)
        logger.info(f"[{agent}] Backtest launched: {combination_id}/{total_combinations}")

    def log_backtest_complete(
        self,
        agent: str,
        params: Dict[str, Any],
        results: Dict[str, Any],
        combination_id: int
    ):
        """Log la fin d'un backtest."""
        entry = OrchestrationLogEntry(
            timestamp=self._now(),
            action_type=OrchestrationActionType.BACKTEST_COMPLETE,
            agent=agent,
            status=OrchestrationStatus.COMPLETED,
            details={
                "params": params,
                "results": results,
                "combination_id": combination_id
            },
            iteration=self.current_iteration,
            session_id=self.session_id
        )
        self._add_entry(entry)

        # Extraire métriques clés
        pnl = results.get('pnl', 0)
        sharpe = results.get('sharpe', 0)
        logger.info(f"[{agent}] Backtest #{combination_id} complete - PnL: {pnl:.2f}, Sharpe: {sharpe:.2f}")

    def log_backtest_failed(
        self,
        agent: str,
        params: Dict[str, Any],
        error: str,
        combination_id: int
    ):
        """Log l'échec d'un backtest."""
        entry = OrchestrationLogEntry(
            timestamp=self._now(),
            action_type=OrchestrationActionType.BACKTEST_FAILED,
            agent=agent,
            status=OrchestrationStatus.FAILED,
            details={
                "params": params,
                "error": error,
                "combination_id": combination_id
            },
            iteration=self.current_iteration,
            session_id=self.session_id
        )
        self._add_entry(entry)
        logger.error(f"[{agent}] Backtest #{combination_id} failed: {error}")

    def log_decision(
        self,
        agent: str,
        decision_type: str,  # "continue", "stop", "change_approach"
        reason: str,
        details: Optional[Dict] = None
    ):
        """Log une décision d'agent."""
        action_map = {
            "continue": OrchestrationActionType.DECISION_CONTINUE,
            "stop": OrchestrationActionType.DECISION_STOP,
            "change_approach": OrchestrationActionType.DECISION_CHANGE_APPROACH,
        }

        entry = OrchestrationLogEntry(
            timestamp=self._now(),
            action_type=action_map.get(decision_type, OrchestrationActionType.DECISION_CONTINUE),
            agent=agent,
            status=OrchestrationStatus.COMPLETED,
            details={"reason": reason, **(details or {})},
            iteration=self.current_iteration,
            session_id=self.session_id
        )
        self._add_entry(entry)
        logger.info(f"[{agent}] Decision: {decision_type} - {reason}")

    def next_iteration(self):
        """Passe à l'itération suivante."""
        self.current_iteration += 1
        logger.info(f"=== Iteration {self.current_iteration} START ===")

    def log(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        API générique pour logger un événement (compatible avec orchestrator).

        Args:
            event_type: Type d'événement (str)
            data: Données de l'événement incluant tous les champs
        """
        # Essayer de mapper le type à un enum
        try:
            action_type = OrchestrationActionType(event_type)
        except ValueError:
            # Si non reconnu, utiliser WARNING avec le type en détail
            action_type = OrchestrationActionType.WARNING
            data = {"original_event_type": event_type, **data}

        entry = OrchestrationLogEntry(
            timestamp=data.get("timestamp", self._now()),
            action_type=action_type,
            agent=data.get("role") or data.get("agent"),
            status=OrchestrationStatus.COMPLETED,  # Par défaut
            details=data,
            iteration=data.get("iteration", self.current_iteration),
            session_id=data.get("session_id", self.session_id),
        )
        self._add_entry(entry)

    def add_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Alias pour log() (API alternative)."""
        self.log(event_type, data)

    def append(self, data: Dict[str, Any]) -> None:
        """Alias pour log() qui extrait event_type du dict."""
        event_type = data.get("event_type", "warning")
        self.log(event_type, data)

    def _maybe_auto_save(self) -> None:
        """Sauvegarde automatiquement si le seuil est atteint."""
        if not self._auto_save:
            return
        with self._lock:
            self._save_counter += 1
            should_save = self._save_counter >= self._save_interval
        if should_save:
            try:
                self.save_to_jsonl(self._save_path)
                with self._lock:
                    self._save_counter = 0
            except Exception as e:
                logger.debug(f"Auto-save failed: {e}")

    def get_logs_for_iteration(self, iteration: int) -> List[OrchestrationLogEntry]:
        """Récupère les logs d'une itération spécifique."""
        return [log for log in self.logs if log.iteration == iteration]

    def get_logs_by_agent(self, agent: str) -> List[OrchestrationLogEntry]:
        """Récupère tous les logs d'un agent spécifique."""
        return [log for log in self.logs if log.agent == agent]

    def get_logs_by_type(self, action_type: OrchestrationActionType) -> List[OrchestrationLogEntry]:
        """Récupère tous les logs d'un type d'action."""
        return [log for log in self.logs if log.action_type == action_type]

    def save_to_file(self, filepath: Optional[Path] = None):
        """
        Sauvegarde les logs dans un fichier JSON (legacy, préférer save_to_jsonl).

        Args:
            filepath: Chemin du fichier JSON (défaut: orchestration_logs_{session}.json)
        """
        if filepath is None:
            filepath = Path(f"orchestration_logs_{self.session_id}.json")

        data = {
            "session_id": self.session_id,
            "total_iterations": self.current_iteration,
            "total_logs": len(self.logs),
            "logs": [log.to_dict() for log in self.logs]
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Logs saved to {filepath}")

    def save_to_jsonl(self, filepath: Optional[Path] = None):
        """
        Sauvegarde les logs en format JSONL (une ligne par événement).

        Args:
            filepath: Chemin du fichier JSONL (défaut: runs/{session}/trace.jsonl)
        """
        if filepath is None:
            filepath = self._save_path

        # Créer le répertoire si nécessaire
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            logs_snapshot = list(self.logs)
            current_iteration = int(self.current_iteration)
            total_logs = len(logs_snapshot)

        with open(filepath, "w", encoding="utf-8") as f:
            header = {
                "event_type": "session_header",
                "session_id": self.session_id,
                "total_iterations": current_iteration,
                "total_logs": total_logs,
                "timestamp": self._now(),
            }
            f.write(json.dumps(header, ensure_ascii=False) + "\n")

            for log in logs_snapshot:
                f.write(json.dumps(log.to_dict(), ensure_ascii=False) + "\n")

        logger.debug(f"Logs saved to {filepath} ({total_logs} entries)")

    @classmethod
    def load_from_file(cls, filepath: Path) -> "OrchestrationLogger":
        """
        Charge les logs depuis un fichier JSON ou JSONL.

        Args:
            filepath: Chemin vers le fichier JSON/JSONL

        Returns:
            Instance OrchestrationLogger avec les logs chargés
        """
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        # Détecter le format
        with open(filepath, "r", encoding="utf-8") as f:
            first_line = f.readline().strip()

        if filepath.suffix == ".jsonl" or first_line.startswith('{"event_type"'):
            return cls._load_from_jsonl(filepath)
        else:
            return cls._load_from_json(filepath)

    @classmethod
    def _load_from_jsonl(cls, filepath: Path) -> "OrchestrationLogger":
        """Charge depuis un fichier JSONL."""
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if not lines:
            raise ValueError("Empty JSONL file")

        # Première ligne = header
        header = json.loads(lines[0])
        session_id = header.get("session_id", "unknown")

        instance = cls(session_id=session_id, auto_save=False)
        instance.current_iteration = header.get("total_iterations", 0)

        # Charger les événements
        for line in lines[1:]:
            if not line.strip():
                continue
            data = json.loads(line)
            entry = OrchestrationLogEntry(
                timestamp=data["timestamp"],
                action_type=OrchestrationActionType(data["action_type"]),
                agent=data.get("agent"),
                status=OrchestrationStatus(data["status"]),
                details=data.get("details", {}),
                iteration=data.get("iteration", 0),
                session_id=data.get("session_id"),
            )
            instance.logs.append(entry)

        logger.info(f"Loaded {len(instance.logs)} logs from {filepath}")
        return instance

    @classmethod
    def _load_from_json(cls, filepath: Path) -> "OrchestrationLogger":
        """Charge depuis un fichier JSON (legacy)."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        session_id = data.get("session_id", "unknown")
        instance = cls(session_id=session_id, auto_save=False)
        instance.current_iteration = data.get("total_iterations", 0)

        for log_data in data.get("logs", []):
            entry = OrchestrationLogEntry(
                timestamp=log_data["timestamp"],
                action_type=OrchestrationActionType(log_data["action_type"]),
                agent=log_data.get("agent"),
                status=OrchestrationStatus(log_data["status"]),
                details=log_data.get("details", {}),
                iteration=log_data.get("iteration", 0),
                session_id=log_data.get("session_id"),
            )
            instance.logs.append(entry)

        logger.info(f"Loaded {len(instance.logs)} logs from {filepath}")
        return instance

    def generate_summary(self) -> str:
        """Génère un résumé textuel des logs."""
        lines = ["=" * 80]
        lines.append(f"ORCHESTRATION LOG SUMMARY - Session: {self.session_id}")
        lines.append("=" * 80)
        lines.append(f"Total Iterations: {self.current_iteration}")
        lines.append(f"Total Log Entries: {len(self.logs)}")
        lines.append("")

        # Compter par type d'action
        action_counts = {}
        for log in self.logs:
            action_type = log.action_type.value
            action_counts[action_type] = action_counts.get(action_type, 0) + 1

        lines.append("Actions Count:")
        for action, count in sorted(action_counts.items()):
            lines.append(f"  - {action}: {count}")
        lines.append("")

        # Compter par agent
        agent_counts = {}
        for log in self.logs:
            if log.agent:
                agent_counts[log.agent] = agent_counts.get(log.agent, 0) + 1

        lines.append("Agent Activity:")
        for agent, count in sorted(agent_counts.items()):
            lines.append(f"  - {agent}: {count} actions")

        lines.append("")
        lines.append("=" * 80)

        return "\n".join(lines)


# Instance globale (optionnelle)
_global_logger: Optional[OrchestrationLogger] = None


def generate_session_id() -> str:
    """Génère un ID de session unique."""
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def get_orchestration_logger(session_id: Optional[str] = None) -> OrchestrationLogger:
    """Récupère ou crée le logger d'orchestration global."""
    global _global_logger
    if _global_logger is None:
        _global_logger = OrchestrationLogger(session_id=session_id)
    return _global_logger


def reset_orchestration_logger():
    """Réinitialise le logger d'orchestration global."""
    global _global_logger
    _global_logger = None


__all__ = [
    "OrchestrationActionType",
    "OrchestrationStatus",
    "OrchestrationLogEntry",
    "OrchestrationLogger",
    "generate_session_id",
    "get_orchestration_logger",
    "reset_orchestration_logger",
]
