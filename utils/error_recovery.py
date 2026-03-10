"""
Module-ID: utils.error_recovery

Purpose: Error Recovery - retry avec backoff exponentiel et classification erreurs.

Role in pipeline: resilience

Key components: RetryHandler, ErrorClassifier, RetryStrategy, TransientError

Inputs: Exception, max_retries, backoff_factor

Outputs: Succès après retry, ou final ErrorExhausted après N tentatives

Dependencies: functools, logging, time, traceback

Conventions: Backoff exponentiel optionnel; classification transitoire/permanent; callbacks setup/cleanup.

Read-if: Modification stratégies retry, classification erreurs.

Skip-if: Vous utilisez juste @retry_on_error decorator.
"""

from __future__ import annotations

import functools
import logging
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Catégorie d'erreur pour déterminer la stratégie de récupération."""
    TRANSIENT = "transient"      # Erreur temporaire, retry possible
    PERMANENT = "permanent"      # Erreur permanente, pas de retry
    RESOURCE = "resource"        # Erreur ressource (mémoire, disk)
    NETWORK = "network"          # Erreur réseau
    VALIDATION = "validation"    # Erreur de validation
    UNKNOWN = "unknown"          # Erreur inconnue


@dataclass
class ErrorInfo:
    """Informations sur une erreur capturée."""
    exception: Exception
    category: ErrorCategory
    timestamp: float
    context: Dict[str, Any] = field(default_factory=dict)
    traceback_str: str = ""
    attempt: int = 1

    def __post_init__(self):
        if not self.traceback_str:
            self.traceback_str = traceback.format_exc()


@dataclass
class RetryConfig:
    """Configuration du retry."""
    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True

    # Erreurs à retrier
    retry_exceptions: Tuple[Type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        OSError,
    )

    # Erreurs à ne jamais retrier
    no_retry_exceptions: Tuple[Type[Exception], ...] = (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    )


class ErrorClassifier:
    """Classifie les erreurs par catégorie."""

    # Mapping par défaut type d'exception -> catégorie
    DEFAULT_MAPPING: Dict[Type[Exception], ErrorCategory] = {
        ConnectionError: ErrorCategory.NETWORK,
        TimeoutError: ErrorCategory.NETWORK,
        MemoryError: ErrorCategory.RESOURCE,
        OSError: ErrorCategory.RESOURCE,
        ValueError: ErrorCategory.VALIDATION,
        TypeError: ErrorCategory.VALIDATION,
        KeyError: ErrorCategory.PERMANENT,
        AttributeError: ErrorCategory.PERMANENT,
    }

    def __init__(self, custom_mapping: Optional[Dict[Type[Exception], ErrorCategory]] = None):
        """
        Args:
            custom_mapping: Mapping personnalisé type -> catégorie
        """
        self.mapping = {**self.DEFAULT_MAPPING}
        if custom_mapping:
            self.mapping.update(custom_mapping)

    def classify(self, exc: Exception) -> ErrorCategory:
        """
        Classifie une exception.

        Args:
            exc: Exception à classifier

        Returns:
            Catégorie de l'erreur
        """
        # Vérifier le type exact
        exc_type = type(exc)
        if exc_type in self.mapping:
            return self.mapping[exc_type]

        # Vérifier les classes parentes
        for error_type, category in self.mapping.items():
            if isinstance(exc, error_type):
                return category

        # Heuristiques basées sur le message
        msg = str(exc).lower()

        if any(w in msg for w in ["timeout", "connection", "network", "refused"]):
            return ErrorCategory.NETWORK

        if any(w in msg for w in ["memory", "oom", "allocation", "out of memory"]):
            return ErrorCategory.RESOURCE

        if any(w in msg for w in ["invalid", "validation", "required"]):
            return ErrorCategory.VALIDATION

        return ErrorCategory.UNKNOWN

    def is_retryable(self, exc: Exception) -> bool:
        """Détermine si une erreur peut être retriée."""
        category = self.classify(exc)
        return category in (ErrorCategory.TRANSIENT, ErrorCategory.NETWORK, ErrorCategory.RESOURCE)


class RetryHandler:
    """
    Gestionnaire de retry avec exponential backoff.

    Example:
        >>> handler = RetryHandler(max_attempts=3)
        >>>
        >>> @handler.retry
        >>> def unstable_function():
        >>>     ...
        >>>
        >>> # Ou manuellement:
        >>> result = handler.execute(unstable_function, arg1, arg2)
    """

    def __init__(
        self,
        config: Optional[RetryConfig] = None,
        classifier: Optional[ErrorClassifier] = None,
        on_retry: Optional[Callable[[ErrorInfo], None]] = None,
        on_failure: Optional[Callable[[ErrorInfo], None]] = None,
    ):
        """
        Args:
            config: Configuration du retry
            classifier: Classifier d'erreurs
            on_retry: Callback appelé avant chaque retry
            on_failure: Callback appelé après échec final
        """
        self.config = config or RetryConfig()
        self.classifier = classifier or ErrorClassifier()
        self.on_retry = on_retry
        self.on_failure = on_failure

        self._errors: List[ErrorInfo] = []

    def _calculate_delay(self, attempt: int) -> float:
        """Calcule le délai avant le prochain retry."""
        delay = self.config.initial_delay * (self.config.exponential_base ** (attempt - 1))
        delay = min(delay, self.config.max_delay)

        if self.config.jitter:
            import random
            delay *= (0.5 + random.random())

        return delay

    def _should_retry(self, exc: Exception, attempt: int) -> bool:
        """Détermine si on doit retrier."""
        # Limite d'attempts
        if attempt >= self.config.max_attempts:
            return False

        # Vérifier si exception dans no_retry
        if isinstance(exc, self.config.no_retry_exceptions):
            return False

        # Vérifier si exception retryable
        if isinstance(exc, self.config.retry_exceptions):
            return True

        # Utiliser le classifier
        return self.classifier.is_retryable(exc)

    def execute(
        self,
        func: Callable,
        *args,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Any:
        """
        Exécute une fonction avec retry.

        Args:
            func: Fonction à exécuter
            *args: Arguments positionnels
            context: Contexte pour le logging
            **kwargs: Arguments nommés

        Returns:
            Résultat de la fonction

        Raises:
            Exception: Dernière exception si tous les retries échouent
        """
        context = context or {}
        attempt = 0
        last_error: Optional[ErrorInfo] = None

        while attempt < self.config.max_attempts:
            attempt += 1

            try:
                return func(*args, **kwargs)

            except Exception as exc:
                error_info = ErrorInfo(
                    exception=exc,
                    category=self.classifier.classify(exc),
                    timestamp=time.time(),
                    context=context,
                    attempt=attempt,
                )
                self._errors.append(error_info)
                last_error = error_info

                logger.warning(
                    f"Attempt {attempt}/{self.config.max_attempts} failed: {exc}"
                )

                if not self._should_retry(exc, attempt):
                    logger.error(f"Error not retryable: {error_info.category}")
                    if self.on_failure:
                        self.on_failure(error_info)
                    raise

                # Callback before retry
                if self.on_retry:
                    self.on_retry(error_info)

                # Attendre avant retry
                if attempt < self.config.max_attempts:
                    delay = self._calculate_delay(attempt)
                    logger.info(f"Retrying in {delay:.2f}s...")
                    time.sleep(delay)

        # Tous les retries ont échoué
        if self.on_failure and last_error:
            self.on_failure(last_error)

        raise last_error.exception if last_error else RuntimeError("No attempts made")

    def retry(self, func: Callable) -> Callable:
        """
        Décorateur pour ajouter retry à une fonction.

        Example:
            >>> @retry_handler.retry
            >>> def my_function():
            >>>     ...
        """
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return self.execute(func, *args, **kwargs)
        return wrapper

    def get_errors(self) -> List[ErrorInfo]:
        """Retourne l'historique des erreurs."""
        return list(self._errors)

    def clear_errors(self):
        """Efface l'historique des erreurs."""
        self._errors.clear()


class RecoveryStrategy:
    """
    Stratégie de récupération pour erreurs spécifiques.

    Définit des actions de récupération personnalisées.
    """

    def __init__(self):
        """Initialise les stratégies."""
        self._strategies: Dict[ErrorCategory, Callable[[ErrorInfo], bool]] = {}
        self._setup_defaults()

    def _setup_defaults(self):
        """Configure les stratégies par défaut."""

        def handle_resource(error: ErrorInfo) -> bool:
            """Gère les erreurs de ressources."""
            import gc
            gc.collect()

            logger.info("Memory cleared for recovery")
            return True

        def handle_network(error: ErrorInfo) -> bool:
            """Gère les erreurs réseau."""
            # Attendre un peu avant retry
            time.sleep(2.0)
            return True

        def handle_permanent(error: ErrorInfo) -> bool:
            """Gère les erreurs permanentes."""
            logger.error(f"Permanent error, no recovery: {error.exception}")
            return False

        self._strategies[ErrorCategory.RESOURCE] = handle_resource
        self._strategies[ErrorCategory.NETWORK] = handle_network
        self._strategies[ErrorCategory.PERMANENT] = handle_permanent

    def register(
        self,
        category: ErrorCategory,
        handler: Callable[[ErrorInfo], bool]
    ):
        """
        Enregistre une stratégie de récupération.

        Args:
            category: Catégorie d'erreur
            handler: Fonction de récupération (retourne True si récupéré)
        """
        self._strategies[category] = handler

    def recover(self, error: ErrorInfo) -> bool:
        """
        Tente de récupérer d'une erreur.

        Args:
            error: Information sur l'erreur

        Returns:
            True si récupération réussie
        """
        handler = self._strategies.get(error.category)

        if handler:
            try:
                return handler(error)
            except Exception as e:
                logger.error(f"Recovery handler failed: {e}")
                return False

        return False


# Décorateurs utilitaires

def with_retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable] = None,
):
    """
    Décorateur pour ajouter retry à une fonction.

    Args:
        max_attempts: Nombre max de tentatives
        delay: Délai initial entre retries
        exceptions: Types d'exceptions à retrier
        on_retry: Callback appelé avant retry

    Example:
        >>> @with_retry(max_attempts=3, delay=1.0)
        >>> def unstable_api_call():
        >>>     ...
    """
    config = RetryConfig(
        max_attempts=max_attempts,
        initial_delay=delay,
        retry_exceptions=exceptions,
    )
    handler = RetryHandler(config=config, on_retry=on_retry)

    def decorator(func: Callable) -> Callable:
        return handler.retry(func)

    return decorator


def retry_on_memory_error(func: Callable) -> Callable:
    """Décorateur spécifique pour les erreurs mémoire."""
    config = RetryConfig(
        max_attempts=3,
        initial_delay=2.0,
        retry_exceptions=(MemoryError,),
    )

    def on_retry(error: ErrorInfo):
        import gc
        gc.collect()

    handler = RetryHandler(config=config, on_retry=on_retry)
    return handler.retry(func)


__all__ = [
    "ErrorCategory",
    "ErrorInfo",
    "RetryConfig",
    "ErrorClassifier",
    "RetryHandler",
    "RecoveryStrategy",
    "with_retry",
    "retry_on_memory_error",
]
