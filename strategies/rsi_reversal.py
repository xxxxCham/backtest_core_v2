"""
Module-ID: strategies.rsi_reversal

Purpose: Stratégie mean-reversion basée sur seuils surédapte/survente RSI.

Role in pipeline: core

Key components: RSIReversalStrategy, rsi_period, overbought_threshold, oversold_threshold

Inputs: DataFrame OHLCV avec colonne close

Outputs: StrategyResult (signaux 1/-1/0 sur seuils RSI)

Dependencies: strategies.base, indicators.rsi, utils.parameters, pandas, numpy

Conventions: oversold < 50 < overbought; RSI période standard 14; signaux confirmés.

Read-if: Modification seuils RSI, période, ou logique renversement.

Skip-if: Vous ne changez que d'autres stratégies.
"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from strategies.base import StrategyBase, StrategyResult, register_strategy
from utils.parameters import ParameterSpec


@register_strategy("rsi_reversal")
class RSIReversalStrategy(StrategyBase):
    """
    Stratégie RSI de renversement.

    Signaux:
        - LONG (+1): RSI < oversold_level (survente → achat)
        - SHORT (-1): RSI > overbought_level (surachat → vente)

    Paramètres:
        - rsi_period: Période du RSI (défaut: 14)
        - oversold_level: Seuil de survente (défaut: 30)
        - overbought_level: Seuil de surachat (défaut: 70)
        - leverage: Multiplicateur de position (défaut: 1)
    """

    def __init__(self, name: str = "rsi_reversal"):
        super().__init__(name)

    @property
    def required_indicators(self) -> List[str]:
        """Indicateurs requis par la stratégie."""
        return ["rsi"]

    @property
    def default_params(self) -> Dict[str, Any]:
        """Paramètres par défaut."""
        return {
            "rsi_period": 14,
            "oversold_level": 30,
            "overbought_level": 70,
            "leverage": 1,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        """Spécifications des paramètres pour l'UI et l'optimisation."""
        return {
            "rsi_period": ParameterSpec(
                name="rsi_period",
                min_val=5,
                max_val=30,
                default=14,
                param_type="int",
                description="Période du RSI"
            ),
            "oversold_level": ParameterSpec(
                name="oversold_level",
                min_val=10,
                max_val=40,
                default=30,
                param_type="int",
                description="Seuil de survente"
            ),
            "overbought_level": ParameterSpec(
                name="overbought_level",
                min_val=60,
                max_val=90,
                default=70,
                param_type="int",
                description="Seuil de surachat"
            ),
            "leverage": ParameterSpec(
                name="leverage",
                min_val=1,
                max_val=10,
                default=1,
                param_type="int",
                description="Levier de trading",
                optimize=False,
            ),
        }

    def get_indicator_params(
        self,
        indicator_name: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Mappe les parametres de la strategie vers les indicateurs."""
        if indicator_name == "rsi":
            return {"period": int(params.get("rsi_period", 14))}
        return super().get_indicator_params(indicator_name, params)

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any]
    ) -> pd.Series:
        """
        Génère les signaux de trading basés sur les niveaux RSI.

        Args:
            df: DataFrame OHLCV
            indicators: Dictionnaire contenant 'rsi'
            params: Paramètres de la stratégie

        Returns:
            Series de signaux (-1, 0, +1)
        """
        signals = pd.Series(0.0, index=df.index)

        # Récupérer le RSI
        if "rsi" not in indicators or indicators["rsi"] is None:
            return signals

        rsi_values = indicators["rsi"]

        # Convertir en Series si nécessaire
        if isinstance(rsi_values, np.ndarray):
            rsi_values = pd.Series(rsi_values, index=df.index)

        oversold = params.get("oversold_level", 30)
        overbought = params.get("overbought_level", 70)

        # Signaux
        # LONG quand RSI passe sous le niveau de survente
        # Utiliser fill_value=50 (neutre) pour éviter les NaN au début
        rsi_prev = rsi_values.shift(1, fill_value=50.0)
        long_signal = (rsi_values < oversold) & (rsi_prev >= oversold)

        # SHORT quand RSI passe au-dessus du niveau de surachat
        short_signal = (rsi_values > overbought) & (rsi_prev <= overbought)

        signals[long_signal] = 1.0
        signals[short_signal] = -1.0

        return signals

    def describe(self) -> str:
        """Description de la stratégie."""
        return (
            "RSI Reversal Strategy: Génère des signaux basés sur les "
            "niveaux de surachat/survente du RSI. "
            "Achat en survente, vente en surachat."
        )

    def run(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any] = None
    ) -> StrategyResult:
        """
        Exécute la stratégie.

        Args:
            df: DataFrame OHLCV
            indicators: Dictionnaire d'indicateurs pré-calculés
            params: Paramètres (optionnel, utilise default_params sinon)

        Returns:
            StrategyResult avec signaux et métadonnées
        """
        if params is None:
            params = self.default_params

        signals = self.generate_signals(df, indicators, params)

        # Compter les signaux
        n_long = (signals == 1).sum()
        n_short = (signals == -1).sum()

        self._last_result = StrategyResult(
            signals=signals,
            params_used=params,
            metadata={
                "strategy": self.name,
                "total_signals": n_long + n_short,
                "long_signals": int(n_long),
                "short_signals": int(n_short),
                "rsi_period": params.get("rsi_period", 14),
                "oversold_level": params.get("oversold_level", 30),
                "overbought_level": params.get("overbought_level", 70),
            }
        )

        return self._last_result
