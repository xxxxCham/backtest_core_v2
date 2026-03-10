"""
Module-ID: strategies.base

Purpose: Classe abstraite et contrat pour toutes les stratégies de trading.

Role in pipeline: core

Key components: StrategyBase (abstract), StrategyResult (dataclass), register_strategy (decorator)

Inputs: DataFrame OHLCV, paramètres utilisateur, indicateurs pré-calculés

Outputs: StrategyResult (signaux, prix, stop/target, metadata)

Dependencies: pandas, numpy, utils.parameters, dataclasses

Conventions: Signaux standardisés (1=long, -1=short, 0=flat); paramètres clampés aux bornes; indicateurs calculés ou fournis; preset/granularité support.

Read-if: Création nouvelle stratégie, modification interface ou patterns standards.

Skip-if: Vous ne changez qu'une stratégie spécifique.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Type

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec, Preset


@dataclass
class StrategyResult:
    """
    Résultat d'une exécution de stratégie.

    Attributes:
        signals: Série de signaux (1=long, -1=short, 0=flat)
        entry_prices: Prix d'entrée suggérés (optionnel)
        stop_losses: Niveaux de stop-loss (optionnel)
        take_profits: Niveaux de take-profit (optionnel)
        indicators: Dict des indicateurs calculés
        metadata: Informations additionnelles
        params_used: Paramètres utilisés pour l'exécution
    """
    signals: pd.Series
    entry_prices: Optional[np.ndarray] = None
    stop_losses: Optional[np.ndarray] = None
    take_profits: Optional[np.ndarray] = None
    indicators: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    params_used: Dict[str, Any] = field(default_factory=dict)


class StrategyBase(ABC):
    """
    Classe de base abstraite pour les stratégies de trading.

    Toute stratégie doit hériter de cette classe et implémenter:
    - required_indicators: liste des indicateurs nécessaires
    - generate_signals(): génération des signaux de trading

    Architecture conçue pour:
    1. Être utilisée de manière autonome par le moteur de backtest
    2. Permettre une future intégration avec des agents LLM
    3. Supporter différents styles de trading (trend, mean-reversion, etc.)

    Example:
        class MyStrategy(StrategyBase):
            @property
            def required_indicators(self):
                return ["bollinger", "rsi"]

            def generate_signals(self, df, indicators, params):
                # Logique de génération de signaux
                ...
    """

    def __init__(self, name: str = "BaseStrategy"):
        """
        Initialise la stratégie.

        Args:
            name: Nom identifiant la stratégie
        """
        self.name = name
        self._last_result: Optional[StrategyResult] = None

    @property
    @abstractmethod
    def required_indicators(self) -> List[str]:
        """
        Liste des indicateurs techniques requis par la stratégie.

        Le moteur de backtest utilisera cette liste pour calculer
        automatiquement les indicateurs nécessaires avant d'appeler
        generate_signals().

        Returns:
            Liste de noms d'indicateurs (ex: ["bollinger", "atr"])
        """
        pass

    @property
    def default_params(self) -> Dict[str, Any]:
        """
        Paramètres par défaut de la stratégie.

        Peut être surchargé par les classes filles pour définir
        des valeurs par défaut spécifiques.
        """
        return {}

    @property
    def param_ranges(self) -> Dict[str, tuple]:
        """
        Plages de paramètres pour l'optimisation.

        Format: {"param_name": (min_value, max_value)}
        Génère automatiquement depuis parameter_specs si disponible.
        Peut être surchargé par les classes filles.
        """
        return self.get_param_ranges()

    def _should_include_optional_params(
        self,
        override: Optional[bool] = None,
    ) -> bool:
        """Détermine si les paramètres optionnels (ex: leverage) sont inclus."""
        if override is not None:
            return bool(override)

        if getattr(self, "_include_optional_params", False):
            return True

        env_flag = os.getenv("BACKTEST_INCLUDE_OPTIONAL_PARAMS", "").strip().lower()
        return env_flag in {"1", "true", "yes", "on"}

    def get_param_ranges(self, include_optional: Optional[bool] = None) -> Dict[str, tuple]:
        """Retourne les plages en excluant les paramètres non optimisables par défaut."""
        include = self._should_include_optional_params(override=include_optional)

        if hasattr(self, 'parameter_specs') and self.parameter_specs:
            items = self.parameter_specs.items()
            if not include:
                items = (
                    (name, spec)
                    for name, spec in items
                    if getattr(spec, "optimize", True)
                )
            return {
                name: (spec.min_val, spec.max_val)
                for name, spec in items
            }
        return {}

    def get_indicator_params(
        self,
        indicator_name: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Retourne les parametres a passer a l'indicateur.

        Les strategies peuvent surcharger cette methode pour mapper leurs
        parametres internes vers ceux attendus par les indicateurs.
        """
        params = params or {}

        prefix_map = {
            "bollinger": ["bb_", "bollinger_"],
            "atr": ["atr_"],
            "rsi": ["rsi_"],
            "ema": ["ema_"],
            "macd": ["macd_"],
        }

        prefixes = prefix_map.get(indicator_name, [f"{indicator_name}_"])
        indicator_params: Dict[str, Any] = {}

        for key, value in params.items():
            for prefix in prefixes:
                if key.startswith(prefix):
                    param_name = key[len(prefix):]
                    indicator_params[param_name] = value
                    break

        if indicator_name == "bollinger" and "std" in indicator_params:
            indicator_params.setdefault("std_dev", indicator_params.pop("std"))

        direct_params = {
            "bollinger": ["period", "std_dev"],
            "atr": ["period", "method"],
            "rsi": ["period"],
            "ema": ["period"],
            "macd": ["fast_period", "slow_period", "signal_period"],
        }

        for param in direct_params.get(indicator_name, []):
            if param in params and param not in indicator_params:
                indicator_params[param] = params[param]

        return indicator_params

    @abstractmethod
    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any]
    ) -> pd.Series:
        """
        Génère les signaux de trading.

        Args:
            df: DataFrame OHLCV avec colonnes (open, high, low, close, volume)
            indicators: Dict des indicateurs précalculés
                       Ex: {"bollinger": (upper, middle, lower), "atr": atr_array}
            params: Paramètres de la stratégie
                   Ex: {"entry_z": 2.0, "k_sl": 1.5}

        Returns:
            pd.Series de signaux indexée par le temps:
            - 1: Signal d'achat (entrer long)
            - -1: Signal de vente (entrer short)
            - 0: Aucun signal (rester flat ou maintenir position)

        Notes:
            - La série retournée doit avoir le même index que df
            - Les signaux représentent des intentions d'entrée/sortie
            - La gestion des positions est faite par le moteur de backtest
        """
        pass

    def run(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None
    ) -> StrategyResult:
        """
        Exécute la stratégie et retourne le résultat complet.

        Cette méthode wrapper facilite l'utilisation et stocke
        le résultat pour inspection ultérieure.

        Args:
            df: DataFrame OHLCV
            indicators: Dict des indicateurs calculés
            params: Paramètres (utilise default_params si None)

        Returns:
            StrategyResult avec signaux et métadonnées
        """
        # Fusionner avec params par défaut
        final_params = {**self.default_params, **(params or {})}

        # Générer les signaux
        signals = self.generate_signals(df, indicators, final_params)

        # Construire le résultat
        result = StrategyResult(
            signals=signals,
            indicators=indicators,
            metadata={
                "strategy_name": self.name,
                "params": final_params,
                "n_signals_long": int((signals == 1).sum()),
                "n_signals_short": int((signals == -1).sum()),
                "period": f"{df.index[0]} → {df.index[-1]}"
            }
        )

        self._last_result = result
        return result

    def validate_params(self, params: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Valide les paramètres fournis.

        Peut être surchargé pour ajouter une validation spécifique.

        Args:
            params: Paramètres à valider

        Returns:
            Tuple (is_valid, list_of_errors)
        """
        errors = []

        # Validation de base (à surcharger)
        if params.get("leverage", 1) <= 0:
            errors.append("leverage doit être > 0")
        if params.get("leverage", 1) > 10:
            errors.append("leverage doit être <= 10")

        return len(errors) == 0, errors

    def describe(self) -> str:
        """
        Retourne une description de la stratégie.
        """
        return f"""
Strategy: {self.name}
Required Indicators: {', '.join(self.required_indicators)}
Default Parameters: {self.default_params}
"""

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}')>"

    # =========================================================================
    # HOOKS POUR INTÉGRATION FUTURE LLM
    # =========================================================================
    # Ces méthodes sont des points d'extension pour les agents LLM.
    # Elles ne font rien par défaut mais peuvent être surchargées
    # par des stratégies dynamiques générées par LLM.

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        """
        Spécifications détaillées des paramètres pour UI et optimisation.

        Surchargez cette propriété pour définir les bornes, types et
        descriptions de chaque paramètre. Utilisé par:
        - L'UI pour générer des sliders/inputs
        - L'optimiseur pour le sweep paramétrique
        - Les agents LLM pour proposer des modifications

        Returns:
            Dict[param_name, ParameterSpec]
        """
        return {}

    def get_preset(self) -> Optional[Preset]:
        """
        Retourne le preset associé à cette stratégie (si disponible).

        Returns:
            Preset ou None
        """
        return None

    def on_backtest_start(self, context: Dict[str, Any]) -> None:
        """
        Hook appelé au début du backtest.

        Point d'extension pour les agents LLM qui veulent
        initialiser un état ou modifier le contexte.

        Args:
            context: Contexte du backtest (symbol, timeframe, etc.)
        """
        pass

    def on_backtest_end(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Hook appelé à la fin du backtest.

        Point d'extension pour les agents LLM qui veulent
        analyser les résultats ou proposer des améliorations.

        Args:
            results: Résultats du backtest (métriques, trades, etc.)

        Returns:
            Résultats potentiellement enrichis avec des suggestions
        """
        return results

    def suggest_improvements(
        self,
        results: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Suggère des améliorations basées sur les résultats.

        Cette méthode sera utilisée par les agents LLM pour
        proposer des ajustements de paramètres ou de logique.
        Par défaut retourne None (pas de suggestion).

        Args:
            results: Résultats du backtest

        Returns:
            Dict de suggestions ou None
            Format attendu: {"params": {...}, "rationale": "..."}
        """
        return None

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "StrategyBase":
        """
        Factory method pour créer une stratégie depuis une config.

        Permet aux agents LLM de générer des configurations JSON
        qui seront instanciées en stratégies.

        Args:
            config: Configuration dict avec 'name', 'params', etc.

        Returns:
            Instance de stratégie
        """
        # Par défaut, retourne une instance simple
        # Les sous-classes peuvent surcharger pour une logique plus complexe
        return cls()


# =============================================================================
# REGISTRE DES STRATÉGIES
# =============================================================================

_STRATEGY_REGISTRY: Dict[str, Type[StrategyBase]] = {}


def register_strategy(name: str):
    """
    Décorateur pour enregistrer une stratégie dans le registre.

    Usage:
        @register_strategy("bollinger_atr")
        class BollingerATRStrategy(StrategyBase):
            ...
    """
    def decorator(cls: Type[StrategyBase]):
        _STRATEGY_REGISTRY[name] = cls
        return cls
    return decorator


def get_strategy(name: str) -> Type[StrategyBase]:
    """Récupère une classe de stratégie par son nom."""
    if name not in _STRATEGY_REGISTRY:
        available = ", ".join(_STRATEGY_REGISTRY.keys())
        raise ValueError(f"Stratégie '{name}' non trouvée. Disponibles: {available}")
    return _STRATEGY_REGISTRY[name]


def list_strategies() -> List[str]:
    """Liste les stratégies enregistrées."""
    return list(_STRATEGY_REGISTRY.keys())


def create_strategy(name: str, **kwargs) -> StrategyBase:
    """Crée une instance de stratégie par son nom."""
    strategy_cls = get_strategy(name)
    return strategy_cls(**kwargs)


def get_strategy_overview(name: str, max_chars: int = 1800) -> str:
    """
    Construit un résumé compact de la stratégie pour contexte LLM.

    Utilise describe() si disponible, puis docstring de classe et
    informations de base (indicateurs requis, paramètres par défaut).
    """
    strategy_cls = get_strategy(name)

    parts: List[str] = []
    strategy = None
    try:
        strategy = strategy_cls()
    except (TypeError, ValueError, AttributeError):
        strategy = None

    if strategy is not None:
        try:
            desc = strategy.describe()
            if desc:
                parts.append(str(desc).strip())
        except (AttributeError, TypeError):
            pass

        try:
            required = getattr(strategy, "required_indicators", [])
            if required:
                parts.append(f"Required Indicators: {', '.join(required)}")
        except (AttributeError, TypeError):
            pass

        try:
            defaults = getattr(strategy, "default_params", None)
            if defaults:
                parts.append(f"Default Params: {defaults}")
        except (AttributeError, TypeError):
            pass

    class_doc = (strategy_cls.__doc__ or "").strip()
    if class_doc and class_doc not in "\n".join(parts):
        parts.append(class_doc)

    overview = "\n\n".join([p for p in parts if p]).strip()
    if not overview:
        overview = f"Strategy: {strategy_cls.__name__}"

    if max_chars > 0 and len(overview) > max_chars:
        overview = overview[:max_chars].rstrip() + "\n...[truncated]"

    return overview


__all__ = [
    "StrategyBase",
    "StrategyResult",
    "register_strategy",
    "get_strategy",
    "list_strategies",
    "create_strategy",
    "get_strategy_overview",
]
