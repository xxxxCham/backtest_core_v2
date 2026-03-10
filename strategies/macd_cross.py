"""
Module-ID: strategies.macd_cross

Purpose: Stratégie momentum basée sur croisement de MACD et signal line.

Role in pipeline: core

Key components: MACDCrossStrategy, fast_period, slow_period, signal_period

Inputs: DataFrame OHLCV avec colonne close

Outputs: StrategyResult (signaux 1/-1/0 sur croisements MACD/signal)

Dependencies: strategies.base, indicators.macd, utils.parameters, pandas, numpy

Conventions: fast < slow < signal obligatoires; histogram comme filtre optionnel; momentum validé.

Read-if: Modification logique croisement MACD, seuils, ou signal.

Skip-if: Vous ne changez que d'autres stratégies.
"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from strategies.base import StrategyBase, StrategyResult, register_strategy
from utils.parameters import ParameterSpec


@register_strategy("macd_cross")
class MACDCrossStrategy(StrategyBase):
    """
    Stratégie de croisement MACD.

    Signaux:
        - LONG (+1): MACD croise Signal vers le haut (golden cross)
        - SHORT (-1): MACD croise Signal vers le bas (death cross)

    Paramètres:
        - fast_period: Période EMA rapide (défaut: 12)
        - slow_period: Période EMA lente (défaut: 26)
        - signal_period: Période ligne signal (défaut: 9)
        - leverage: Multiplicateur de position (défaut: 1)
    """

    def __init__(self, name: str = "macd_cross"):
        super().__init__(name)

    @property
    def required_indicators(self) -> List[str]:
        """Indicateurs requis par la stratégie."""
        return ["macd"]

    @property
    def default_params(self) -> Dict[str, Any]:
        """Paramètres par défaut."""
        return {
            "fast_period": 12,
            "slow_period": 26,
            "signal_period": 9,
            "leverage": 1,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        """Spécifications des paramètres pour l'UI et l'optimisation."""
        return {
            "fast_period": ParameterSpec(
                name="fast_period",
                min_val=5,
                max_val=30,
                default=12,
                param_type="int",
                description="Période EMA rapide"
            ),
            "slow_period": ParameterSpec(
                name="slow_period",
                min_val=15,
                max_val=50,
                default=26,
                param_type="int",
                description="Période EMA lente"
            ),
            "signal_period": ParameterSpec(
                name="signal_period",
                min_val=5,
                max_val=20,
                default=9,
                param_type="int",
                description="Période ligne signal"
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
        if indicator_name == "macd":
            return {
                "fast_period": int(params.get("fast_period", 12)),
                "slow_period": int(params.get("slow_period", 26)),
                "signal_period": int(params.get("signal_period", 9)),
            }
        return super().get_indicator_params(indicator_name, params)

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any]
    ) -> pd.Series:
        """
        Génère les signaux de trading basés sur les croisements MACD.

        Args:
            df: DataFrame OHLCV
            indicators: Dictionnaire contenant 'macd' avec
                {macd, signal, histogram}
            params: Paramètres de la stratégie

        Returns:
            Series de signaux (-1, 0, +1)
        """
        signals = pd.Series(0.0, index=df.index)

        # Récupérer les données MACD
        if "macd" not in indicators or indicators["macd"] is None:
            return signals

        macd_data = indicators["macd"]

        # macd_data peut être un dict ou un tuple selon la version
        if isinstance(macd_data, dict):
            macd_line = macd_data.get("macd")
            signal_line = macd_data.get("signal")
        elif isinstance(macd_data, tuple) and len(macd_data) >= 2:
            macd_line = macd_data[0]
            signal_line = macd_data[1]
        else:
            return signals

        if macd_line is None or signal_line is None:
            return signals

        # BUGFIX CRITIQUE: Vérifier que les données ne sont pas toutes NaN
        if isinstance(macd_line, np.ndarray) and np.isnan(macd_line).all():
            return signals
        if isinstance(signal_line, np.ndarray) and np.isnan(signal_line).all():
            return signals

        # BUGFIX CRITIQUE: Vérifier que les données ne sont pas toutes NaN
        if isinstance(macd_line, np.ndarray) and np.isnan(macd_line).all():
            return signals
        if isinstance(signal_line, np.ndarray) and np.isnan(signal_line).all():
            return signals

        # Convertir en Series si nécessaire
        if isinstance(macd_line, np.ndarray):
            macd_line = pd.Series(macd_line, index=df.index)
        if isinstance(signal_line, np.ndarray):
            signal_line = pd.Series(signal_line, index=df.index)

        # Nettoyer les NaN qui peuvent causer des problèmes
        macd_line = macd_line.fillna(0.0)
        signal_line = signal_line.fillna(0.0)

        # Détecter les croisements
        # MACD au-dessus de Signal
        macd_above = macd_line > signal_line
        # Utiliser shift avec fill_value pour éviter FutureWarning
        macd_above_prev = macd_above.shift(1, fill_value=False)

        # Golden Cross: MACD passe au-dessus de Signal
        golden_cross = macd_above & ~macd_above_prev

        # Death Cross: MACD passe en dessous de Signal
        death_cross = ~macd_above & macd_above_prev

        signals[golden_cross] = 1.0
        signals[death_cross] = -1.0

        return signals

    def describe(self) -> str:
        """Description de la stratégie."""
        return (
            "MACD Cross Strategy: Génère des signaux sur les croisements "
            "entre la ligne MACD et la ligne Signal. "
            "Achat sur golden cross, vente sur death cross."
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
                "fast_period": params.get("fast_period", 12),
                "slow_period": params.get("slow_period", 26),
                "signal_period": params.get("signal_period", 9),
            }
        )

        return self._last_result
