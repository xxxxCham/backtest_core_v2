"""
Module-ID: agents.state_machine

Purpose: Machine à états rigide pour le workflow LLM avec transitions validées et traçabilité.

Role in pipeline: orchestration

Key components: AgentState (enum), StateMachine, StateTransition, ValidationResult

Inputs: État courant, action demandée, validateurs optionnels

Outputs: Nouvel état, historique transitions, durées, erreurs

Dependencies: utils.log, dataclasses

Conventions: États INIT→ANALYZE→PROPOSE→CRITIQUE→VALIDATE→[APPROVED|REJECTED|ITERATE]; ITERATE reboucle à ANALYZE; *→FAILED sur erreur; iteration incrémenté sur transition ITERATE.

Read-if: Modification transitions, ajout états, ou intégration validateurs custom.

Skip-if: Vous ne touchez qu'aux agents isolés.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Set

from utils.observability import get_obs_logger

logger = get_obs_logger(__name__)


class AgentState(Enum):
    """États du workflow d'optimisation."""

    # États de travail
    INIT = auto()       # Initialisation
    ANALYZE = auto()    # Analyse en cours
    PROPOSE = auto()    # Proposition en cours
    CRITIQUE = auto()   # Critique en cours
    VALIDATE = auto()   # Validation en cours
    ITERATE = auto()    # Préparation itération suivante

    # États terminaux
    APPROVED = auto()   # ✅ Optimisation validée
    REJECTED = auto()   # ❌ Optimisation rejetée
    FAILED = auto()     # 💥 Erreur système

    def is_terminal(self) -> bool:
        """Vérifie si l'état est terminal."""
        return self in (AgentState.APPROVED, AgentState.REJECTED, AgentState.FAILED)

    def is_working(self) -> bool:
        """Vérifie si l'état est un état de travail."""
        return not self.is_terminal()


@dataclass
class ValidationResult:
    """Résultat de validation d'une transition."""

    is_valid: bool
    message: str = ""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, message: str = "OK", **data) -> ValidationResult:
        """Crée un résultat de succès."""
        return cls(is_valid=True, message=message, data=data)

    @classmethod
    def failure(cls, message: str, errors: List[str] = None) -> ValidationResult:
        """Crée un résultat d'échec."""
        return cls(is_valid=False, message=message, errors=errors or [message])

    def __bool__(self) -> bool:
        return self.is_valid


@dataclass
class StateTransition:
    """Définition d'une transition entre états."""

    from_state: AgentState
    to_state: AgentState
    condition: str  # Description de la condition
    validator: Optional[Callable[[Dict[str, Any]], ValidationResult]] = None

    def validate(self, context: Dict[str, Any]) -> ValidationResult:
        """Valide si la transition est permise."""
        if self.validator:
            return self.validator(context)
        return ValidationResult.success()


@dataclass
class StateHistoryEntry:
    """Entrée dans l'historique des états."""

    timestamp: datetime
    from_state: Optional[AgentState]
    to_state: AgentState
    validation: ValidationResult
    iteration: int
    duration_ms: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class StateMachine:
    """
    Machine à états pour le workflow d'optimisation.

    Garantit:
    - Transitions valides uniquement
    - Traçabilité complète
    - Gestion des erreurs
    - Pas de boucles infinies

    Example:
        >>> sm = StateMachine(max_iterations=10)
        >>> sm.transition_to(AgentState.ANALYZE, context)
        >>> if sm.can_transition_to(AgentState.PROPOSE):
        ...     sm.transition_to(AgentState.PROPOSE, context)
    """

    # Définition des transitions valides
    VALID_TRANSITIONS: Dict[AgentState, Set[AgentState]] = {
        AgentState.INIT: {AgentState.ANALYZE, AgentState.FAILED},
        AgentState.ANALYZE: {AgentState.PROPOSE, AgentState.VALIDATE, AgentState.FAILED},
        AgentState.PROPOSE: {AgentState.CRITIQUE, AgentState.FAILED},
        AgentState.CRITIQUE: {AgentState.VALIDATE, AgentState.FAILED},
        AgentState.VALIDATE: {AgentState.APPROVED, AgentState.REJECTED, AgentState.ITERATE, AgentState.FAILED},
        AgentState.ITERATE: {AgentState.ANALYZE, AgentState.REJECTED, AgentState.FAILED},
        # États terminaux - pas de transition sortante
        AgentState.APPROVED: set(),
        AgentState.REJECTED: set(),
        AgentState.FAILED: set(),
    }

    def __init__(
        self,
        max_iterations: int = 10,
        initial_state: AgentState = AgentState.INIT,
    ):
        """
        Initialise la machine à états.

        Args:
            max_iterations: Nombre maximum d'itérations (anti-boucle infinie)
            initial_state: État initial
        """
        self._current_state = initial_state
        self._max_iterations = max_iterations
        self._has_iteration_limit = max_iterations > 0
        self._current_iteration = 0
        self._history: List[StateHistoryEntry] = []
        self._context: Dict[str, Any] = {}
        self._transition_validators: Dict[tuple, Callable] = {}
        self._last_transition_time: Optional[datetime] = None

        # Enregistrer l'état initial
        self._record_transition(None, initial_state, ValidationResult.success("Initial state"))

        max_iter_label = "∞" if not self._has_iteration_limit else str(max_iterations)
        logger.info(f"StateMachine initialisée: état={initial_state.name}, max_iter={max_iter_label}")

    @property
    def current_state(self) -> AgentState:
        """État actuel."""
        return self._current_state

    @property
    def iteration(self) -> int:
        """Numéro d'itération actuel."""
        return self._current_iteration

    @property
    def is_terminal(self) -> bool:
        """Vérifie si l'état actuel est terminal."""
        return self._current_state.is_terminal()

    @property
    def history(self) -> List[StateHistoryEntry]:
        """Historique des transitions."""
        return self._history.copy()

    def register_validator(
        self,
        from_state: AgentState,
        to_state: AgentState,
        validator: Callable[[Dict[str, Any]], ValidationResult],
    ) -> None:
        """
        Enregistre un validateur pour une transition spécifique.

        Args:
            from_state: État source
            to_state: État destination
            validator: Fonction de validation
        """
        self._transition_validators[(from_state, to_state)] = validator

    def can_transition_to(self, target_state: AgentState) -> bool:
        """
        Vérifie si une transition vers l'état cible est possible.

        Args:
            target_state: État cible

        Returns:
            True si la transition est possible
        """
        # Vérifier si la transition est valide structurellement
        valid_targets = self.VALID_TRANSITIONS.get(self._current_state, set())
        if target_state not in valid_targets:
            return False

        # Vérifier le max iterations pour ITERATE → ANALYZE
        if self._current_state == AgentState.ITERATE and target_state == AgentState.ANALYZE:
            if self._has_iteration_limit and self._current_iteration >= self._max_iterations:
                return False

        return True

    def get_valid_transitions(self) -> Set[AgentState]:
        """Retourne les transitions valides depuis l'état actuel."""
        valid = self.VALID_TRANSITIONS.get(self._current_state, set())

        # Filtrer selon les contraintes
        result = set()
        for state in valid:
            if self.can_transition_to(state):
                result.add(state)

        return result

    def transition_to(
        self,
        target_state: AgentState,
        context: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> ValidationResult:
        """
        Effectue une transition vers un nouvel état.

        Args:
            target_state: État cible
            context: Contexte pour la validation
            force: Forcer la transition (ignorer validation)

        Returns:
            Résultat de la validation

        Raises:
            StateTransitionError: Si la transition est invalide
        """
        context = context or {}
        self._context.update(context)

        # Vérifier si déjà en état terminal
        if self.is_terminal:
            return ValidationResult.failure(
                f"Impossible de quitter l'état terminal {self._current_state.name}"
            )

        # Vérifier si la transition est structurellement valide
        if not self.can_transition_to(target_state) and not force:
            valid = self.get_valid_transitions()
            return ValidationResult.failure(
                f"Transition {self._current_state.name} → {target_state.name} invalide. "
                f"Transitions valides: {[s.name for s in valid]}"
            )

        # Exécuter le validateur spécifique si présent
        validator_key = (self._current_state, target_state)
        if validator_key in self._transition_validators and not force:
            validation = self._transition_validators[validator_key](self._context)
            if not validation.is_valid:
                logger.warning(
                    f"Validation échouée: {self._current_state.name} → {target_state.name}: "
                    f"{validation.message}"
                )
                return validation
        else:
            validation = ValidationResult.success()

        # Effectuer la transition
        old_state = self._current_state
        self._current_state = target_state

        # Incrémenter le compteur d'itération si on entre dans ANALYZE
        if target_state == AgentState.ANALYZE and old_state == AgentState.ITERATE:
            self._current_iteration += 1

        # Enregistrer dans l'historique
        self._record_transition(old_state, target_state, validation)

        logger.info(
            f"Transition: {old_state.name} → {target_state.name} "
            f"(iter={self._current_iteration})"
        )

        return validation

    def fail(self, error: str, exception: Optional[Exception] = None) -> None:
        """
        Transition vers l'état FAILED.

        Args:
            error: Message d'erreur
            exception: Exception optionnelle
        """
        validation = ValidationResult.failure(
            error,
            errors=[str(exception)] if exception else [error]
        )

        self._current_state = AgentState.FAILED
        self._record_transition(self._current_state, AgentState.FAILED, validation)

        logger.error(f"StateMachine FAILED: {error}")

    def _record_transition(
        self,
        from_state: Optional[AgentState],
        to_state: AgentState,
        validation: ValidationResult,
    ) -> None:
        """Enregistre une transition dans l'historique."""
        now = datetime.now()
        duration = None

        if self._last_transition_time:
            duration = (now - self._last_transition_time).total_seconds() * 1000

        entry = StateHistoryEntry(
            timestamp=now,
            from_state=from_state,
            to_state=to_state,
            validation=validation,
            iteration=self._current_iteration,
            duration_ms=duration,
        )

        self._history.append(entry)
        self._last_transition_time = now

    def get_summary(self) -> Dict[str, Any]:
        """Retourne un résumé de l'exécution."""
        total_duration = 0.0
        if len(self._history) >= 2:
            total_duration = (
                self._history[-1].timestamp - self._history[0].timestamp
            ).total_seconds()

        return {
            "current_state": self._current_state.name,
            "is_terminal": self.is_terminal,
            "iterations": self._current_iteration,
            "max_iterations": self._max_iterations,
            "total_transitions": len(self._history),
            "total_duration_s": total_duration,
            "history": [
                {
                    "from": e.from_state.name if e.from_state else None,
                    "to": e.to_state.name,
                    "iteration": e.iteration,
                    "valid": e.validation.is_valid,
                    "duration_ms": e.duration_ms,
                }
                for e in self._history
            ],
        }

    def reset(self) -> None:
        """Remet la machine à l'état initial."""
        self._current_state = AgentState.INIT
        self._current_iteration = 0
        self._history.clear()
        self._context.clear()
        self._last_transition_time = None

        self._record_transition(None, AgentState.INIT, ValidationResult.success("Reset"))
        logger.info("StateMachine reset")


class StateTransitionError(Exception):
    """Erreur de transition d'état."""

    def __init__(self, message: str, from_state: AgentState, to_state: AgentState):
        super().__init__(message)
        self.from_state = from_state
        self.to_state = to_state
