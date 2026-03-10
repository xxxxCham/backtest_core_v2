"""
Module-ID: utils.circuit_breaker

Purpose: Circuit Breaker - protection contre cascades d'erreurs répétées.

Role in pipeline: resilience

Key components: CircuitBreaker, CircuitBreakerState, CircuitBreakerError

Inputs: Échecs threshold, success threshold, timeout

Outputs: Autorisation/blocage appels, notifications état

Dependencies: threading, time, dataclasses, Enum

Conventions: États CLOSED/OPEN/HALF_OPEN; exponential backoff; async-safe avec locks.

Read-if: Modification seuils d'erreur/succès, timeouts.

Skip-if: Vous utilisez juste CircuitBreaker.call().
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Type

from utils.log import get_logger

logger = get_logger(__name__)


class CircuitState(Enum):
    """États possibles du circuit breaker."""
    CLOSED = "closed"      # Normal, appels autorisés
    OPEN = "open"          # Bloqué, appels refusés
    HALF_OPEN = "half_open"  # Test de récupération


class CircuitBreakerError(Exception):
    """Exception levée quand le circuit est ouvert."""

    def __init__(self, breaker_name: str, message: str = ""):
        self.breaker_name = breaker_name
        super().__init__(
            f"Circuit '{breaker_name}' est OUVERT. {message}"
        )


@dataclass
class CircuitStats:
    """
    Statistiques du circuit breaker.

    Attributes:
        total_calls: Nombre total d'appels
        successful_calls: Appels réussis
        failed_calls: Appels échoués
        rejected_calls: Appels refusés (circuit ouvert)
        last_failure_time: Timestamp dernier échec
        last_success_time: Timestamp dernier succès
        consecutive_failures: Échecs consécutifs actuels
        state_changes: Historique des changements d'état
    """
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    consecutive_failures: int = 0
    state_changes: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Taux de succès."""
        if self.total_calls == 0:
            return 1.0
        return self.successful_calls / self.total_calls

    @property
    def failure_rate(self) -> float:
        """Taux d'échec."""
        if self.total_calls == 0:
            return 0.0
        return self.failed_calls / self.total_calls

    def record_success(self):
        """Enregistre un succès."""
        self.total_calls += 1
        self.successful_calls += 1
        self.last_success_time = datetime.now()
        self.consecutive_failures = 0

    def record_failure(self):
        """Enregistre un échec."""
        self.total_calls += 1
        self.failed_calls += 1
        self.last_failure_time = datetime.now()
        self.consecutive_failures += 1

    def record_rejection(self):
        """Enregistre un rejet (circuit ouvert)."""
        self.rejected_calls += 1

    def record_state_change(self, from_state: CircuitState, to_state: CircuitState):
        """Enregistre un changement d'état."""
        self.state_changes.append({
            "timestamp": datetime.now().isoformat(),
            "from": from_state.value,
            "to": to_state.value,
        })

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "rejected_calls": self.rejected_calls,
            "success_rate": round(self.success_rate, 4),
            "failure_rate": round(self.failure_rate, 4),
            "consecutive_failures": self.consecutive_failures,
            "last_failure": (
                self.last_failure_time.isoformat()
                if self.last_failure_time else None
            ),
            "last_success": (
                self.last_success_time.isoformat()
                if self.last_success_time else None
            ),
            "state_changes": len(self.state_changes),
        }


class CircuitBreaker:
    """
    Circuit Breaker pour protéger les appels à des composants externes.

    Example:
        >>> breaker = CircuitBreaker("backtest", failure_threshold=3)
        >>>
        >>> @breaker
        >>> def run_backtest(params):
        ...     return engine.run(params)
        >>>
        >>> # Ou manuellement:
        >>> with breaker:
        ...     result = engine.run(params)
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
        excluded_exceptions: Optional[List[Type[Exception]]] = None,
    ):
        """
        Initialise le circuit breaker.

        Args:
            name: Nom du circuit (pour logging)
            failure_threshold: Nombre d'échecs avant ouverture
            recovery_timeout: Secondes avant tentative de récupération
            half_open_max_calls: Appels autorisés en half-open
            excluded_exceptions: Exceptions qui ne comptent pas comme échec
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.excluded_exceptions = excluded_exceptions or []

        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._opened_at: Optional[float] = None
        self._half_open_calls = 0
        self._lock = threading.RLock()

        logger.debug(f"CircuitBreaker '{name}' créé (threshold={failure_threshold})")

    @property
    def state(self) -> CircuitState:
        """État actuel du circuit."""
        with self._lock:
            self._check_state_transition()
            return self._state

    @property
    def stats(self) -> CircuitStats:
        """Statistiques du circuit."""
        return self._stats

    @property
    def is_closed(self) -> bool:
        """True si le circuit est fermé (normal)."""
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """True si le circuit est ouvert (bloqué)."""
        return self.state == CircuitState.OPEN

    def _check_state_transition(self):
        """Vérifie si une transition d'état est nécessaire."""
        if self._state == CircuitState.OPEN and self._opened_at:
            elapsed = time.time() - self._opened_at
            if elapsed >= self.recovery_timeout:
                self._transition_to(CircuitState.HALF_OPEN)

    def _transition_to(self, new_state: CircuitState):
        """Effectue une transition d'état."""
        if self._state == new_state:
            return

        old_state = self._state
        self._state = new_state
        self._stats.record_state_change(old_state, new_state)

        if new_state == CircuitState.OPEN:
            self._opened_at = time.time()
            logger.warning(
                f"CircuitBreaker '{self.name}' OUVERT "
                f"(échecs consécutifs: {self._stats.consecutive_failures})"
            )
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            logger.info(f"CircuitBreaker '{self.name}' en HALF_OPEN (test récupération)")
        elif new_state == CircuitState.CLOSED:
            self._opened_at = None
            logger.info(f"CircuitBreaker '{self.name}' FERMÉ (récupération réussie)")

    def _handle_success(self):
        """Gère un appel réussi."""
        with self._lock:
            self._stats.record_success()

            if self._state == CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.CLOSED)

    def _handle_failure(self, exc: Exception):
        """Gère un appel échoué."""
        # Vérifier si l'exception est exclue
        if any(isinstance(exc, e) for e in self.excluded_exceptions):
            return

        with self._lock:
            self._stats.record_failure()

            if self._state == CircuitState.HALF_OPEN:
                # Retour immédiat à OPEN
                self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED:
                if self._stats.consecutive_failures >= self.failure_threshold:
                    self._transition_to(CircuitState.OPEN)

    def _can_execute(self) -> bool:
        """Vérifie si un appel peut être exécuté."""
        with self._lock:
            self._check_state_transition()

            if self._state == CircuitState.CLOSED:
                return True
            elif self._state == CircuitState.OPEN:
                self._stats.record_rejection()
                return False
            elif self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                self._stats.record_rejection()
                return False
        return False

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Exécute une fonction à travers le circuit breaker.

        Args:
            func: Fonction à exécuter
            *args, **kwargs: Arguments de la fonction

        Returns:
            Résultat de la fonction

        Raises:
            CircuitBreakerError: Si le circuit est ouvert
        """
        if not self._can_execute():
            raise CircuitBreakerError(
                self.name,
                f"Réessayez dans {self.recovery_timeout}s"
            )

        try:
            result = func(*args, **kwargs)
            self._handle_success()
            return result
        except Exception as e:
            self._handle_failure(e)
            raise

    def __call__(self, func: Callable) -> Callable:
        """
        Décorateur pour protéger une fonction.

        Example:
            >>> @breaker
            >>> def my_function():
            ...     pass
        """
        @wraps(func)
        def wrapper(*args, **kwargs):
            return self.call(func, *args, **kwargs)
        return wrapper

    def __enter__(self):
        """Context manager - vérifie si exécution autorisée."""
        if not self._can_execute():
            raise CircuitBreakerError(self.name)
        return self

    def __exit__(self, exc_type, exc_val, _exc_tb):
        """Context manager - enregistre succès/échec."""
        if exc_type is None:
            self._handle_success()
        else:
            if exc_val is not None:
                self._handle_failure(exc_val)
        return False  # Ne pas supprimer l'exception

    def reset(self):
        """Réinitialise le circuit breaker."""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)
            self._stats = CircuitStats()
            self._opened_at = None
            self._half_open_calls = 0
            logger.info(f"CircuitBreaker '{self.name}' réinitialisé")

    def force_open(self):
        """Force l'ouverture du circuit (maintenance)."""
        with self._lock:
            self._transition_to(CircuitState.OPEN)

    def force_close(self):
        """Force la fermeture du circuit."""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)


class CircuitBreakerRegistry:
    """
    Registre central des circuit breakers.

    Permet de gérer plusieurs circuits et d'obtenir des stats globales.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._breakers: Dict[str, CircuitBreaker] = {}
        return cls._instance

    def get_or_create(
        self,
        name: str,
        **kwargs
    ) -> CircuitBreaker:
        """
        Récupère ou crée un circuit breaker.

        Args:
            name: Nom du circuit
            **kwargs: Arguments pour CircuitBreaker si création

        Returns:
            CircuitBreaker existant ou nouveau
        """
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, **kwargs)
        return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Récupère un circuit breaker par son nom."""
        return self._breakers.get(name)

    def list_all(self) -> List[str]:
        """Liste tous les circuits enregistrés."""
        return list(self._breakers.keys())

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Récupère les stats de tous les circuits."""
        return {
            name: {
                "state": breaker.state.value,
                **breaker.stats.to_dict()
            }
            for name, breaker in self._breakers.items()
        }

    def reset_all(self):
        """Réinitialise tous les circuits."""
        for breaker in self._breakers.values():
            breaker.reset()

    def clear(self):
        """Supprime tous les circuits (pour tests)."""
        self._breakers.clear()


# Singleton global
_registry = CircuitBreakerRegistry()


def get_circuit_breaker(name: str, **kwargs) -> CircuitBreaker:
    """
    Raccourci pour récupérer/créer un circuit breaker.

    Args:
        name: Nom du circuit
        **kwargs: Arguments pour CircuitBreaker

    Returns:
        CircuitBreaker
    """
    return _registry.get_or_create(name, **kwargs)


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    **kwargs
) -> Callable:
    """
    Décorateur pour protéger une fonction avec un circuit breaker.

    Example:
        >>> @circuit_breaker("backtest", failure_threshold=3)
        >>> def run_backtest(params):
        ...     return engine.run(params)
    """
    breaker = get_circuit_breaker(
        name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        **kwargs
    )
    return breaker
