"""
Module-ID: backtest.errors

Purpose: Hiérarchie structurée d'exceptions pour distinguer erreurs utilisateur/système et messages UI cohérents.

Role in pipeline: error handling

Key components: BacktestError, UserInputError, DataError, BackendInternalError, LLMUnavailableError

Inputs: message, code, hint, details

Outputs: Exceptions sérialisables en dict (code, message, hint, details)

Dependencies: dataclasses, typing

Conventions: Codes error en UPPER_SNAKE_CASE; hints destinés utilisateurs (non techniques); details pour logs/debug; to_dict() pour sérialisation UI.

Read-if: Gestion erreurs backend/UI, codes erreur, ou messages utilisateur.

Skip-if: Vous n'ajoutez pas de nouveaux types d'erreurs.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class BacktestError(Exception):
    """
    Exception de base pour toutes les erreurs du moteur de backtest.

    Attributes:
        message: Message d'erreur
        code: Code d'erreur court (pour logs)
        hint: Suggestion de correction pour l'utilisateur
        details: Détails techniques (optionnel)
    """

    def __init__(
        self,
        message: str,
        code: str = "BACKTEST_ERROR",
        hint: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint
        self.details = details or {}

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise l'erreur en dict."""
        return {
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "details": self.details,
        }


class UserInputError(BacktestError):
    """
    Erreur due à une entrée utilisateur invalide.

    Exemples:
    - Paramètre hors limites
    - Stratégie inconnue
    - fast_period >= slow_period
    """

    def __init__(
        self,
        message: str,
        param_name: Optional[str] = None,
        expected: Optional[str] = None,
        got: Optional[Any] = None,
        hint: Optional[str] = None
    ):
        details = {}
        if param_name:
            details["param_name"] = param_name
        if expected:
            details["expected"] = expected
        if got is not None:
            details["got"] = got

        super().__init__(
            message=message,
            code="INVALID_INPUT",
            hint=hint,
            details=details
        )
        self.param_name = param_name
        self.expected = expected
        self.got = got


class DataError(BacktestError):
    """
    Erreur liée aux données OHLCV.

    Exemples:
    - Fichier non trouvé
    - Colonnes manquantes
    - Index invalide
    - Données corrompues
    """

    def __init__(
        self,
        message: str,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        missing_columns: Optional[list] = None,
        hint: Optional[str] = None
    ):
        details = {}
        if symbol:
            details["symbol"] = symbol
        if timeframe:
            details["timeframe"] = timeframe
        if missing_columns:
            details["missing_columns"] = missing_columns

        super().__init__(
            message=message,
            code="DATA_ERROR",
            hint=hint or "Vérifiez le format et l'emplacement des données",
            details=details
        )
        self.symbol = symbol
        self.timeframe = timeframe
        self.missing_columns = missing_columns


class InsufficientDataError(DataError):
    """
    Erreur lorsque les données sont insuffisantes pour le warmup des indicateurs.

    Exemples:
    - Fenêtre temporelle trop courte (49 barres < 200 requis)
    - Période d'indicateur > données disponibles
    """

    def __init__(
        self,
        message: str,
        available_bars: Optional[int] = None,
        required_bars: Optional[int] = None,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        hint: Optional[str] = None
    ):
        details = {}
        if available_bars is not None:
            details["available_bars"] = available_bars
        if required_bars is not None:
            details["required_bars"] = required_bars

        default_hint = "Utilisez une période plus longue ou vérifiez la disponibilité des données"

        super().__init__(
            message=message,
            symbol=symbol,
            timeframe=timeframe,
            hint=hint or default_hint
        )
        self.details.update(details)
        self.available_bars = available_bars
        self.required_bars = required_bars


class BackendInternalError(BacktestError):
    """
    Erreur interne du backend (bug).

    Ces erreurs ne devraient pas arriver en usage normal.
    Elles indiquent un problème dans le code du moteur.
    """

    def __init__(
        self,
        message: str,
        original_exception: Optional[Exception] = None,
        trace_id: Optional[str] = None
    ):
        details = {}
        if original_exception:
            details["original_type"] = type(original_exception).__name__
            details["original_message"] = str(original_exception)
        if trace_id:
            details["trace_id"] = trace_id

        super().__init__(
            message=message,
            code="INTERNAL_ERROR",
            hint="Contactez le support avec le trace_id",
            details=details
        )
        self.original_exception = original_exception
        self.trace_id = trace_id


class LLMUnavailableError(BacktestError):
    """
    Erreur lorsque le module LLM n'est pas disponible.

    Peut être causée par:
    - Import manquant
    - Ollama non démarré
    - Clé API invalide
    """

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        reason: Optional[str] = None
    ):
        details = {}
        if provider:
            details["provider"] = provider
        if reason:
            details["reason"] = reason

        hint = "Vérifiez l'installation des dépendances agents"
        if provider and provider.lower() == "ollama":
            hint = "Vérifiez que Ollama est installé et démarré (ollama serve)"
        elif provider and provider.lower() == "openai":
            hint = "Vérifiez votre clé API OpenAI"

        super().__init__(
            message=message,
            code="LLM_UNAVAILABLE",
            hint=hint,
            details=details
        )
        self.provider = provider
        self.reason = reason


class StrategyNotFoundError(UserInputError):
    """
    Erreur lorsqu'une stratégie n'existe pas.
    """

    def __init__(self, strategy_name: str, available: list = None):
        available_str = ", ".join(available) if available else "?"
        super().__init__(
            message=f"Stratégie '{strategy_name}' non trouvée",
            param_name="strategy",
            expected=f"Une parmi: {available_str}",
            got=strategy_name,
            hint=f"Stratégies disponibles: {available_str}"
        )
        self.strategy_name = strategy_name
        self.available = available or []


class ParameterValidationError(UserInputError):
    """
    Erreur de validation d'un paramètre spécifique.
    """

    def __init__(
        self,
        param_name: str,
        message: str,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
        current_value: Optional[Any] = None
    ):
        expected = None
        if min_value is not None and max_value is not None:
            expected = f"[{min_value}, {max_value}]"
        elif min_value is not None:
            expected = f">= {min_value}"
        elif max_value is not None:
            expected = f"<= {max_value}"

        super().__init__(
            message=message,
            param_name=param_name,
            expected=expected,
            got=current_value,
            hint=f"Ajustez '{param_name}' pour qu'il soit dans la plage valide"
        )


# Docstring update summary
# - Docstring de module normalisée (LLM-friendly) centrée sur hiérarchie d'exceptions
# - Conventions codes et sérialisation to_dict() explicitées
# - Read-if/Skip-if ajoutés pour tri rapide
        self.min_value = min_value
        self.max_value = max_value
        self.current_value = current_value
