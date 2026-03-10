"""
Module-ID: strategies.ema_cross

Purpose: Stratégie de suivi de tendance par croisement de deux EMAs (Golden/Death Cross).

Role in pipeline: core

Key components: EMACrossStrategy, fast_period, slow_period, leverage

Inputs: DataFrame OHLCV avec colonnes close, optionnel volume

Outputs: StrategyResult (signaux 1/-1/0 sur croisements EMA)

Dependencies: strategies.base, utils.parameters, pandas, numpy

Conventions: fast_period < slow_period obligatoire; EMA calculées internement; leverage appliqué après signaux.

Read-if: Modification logique croisement, seuils entrée, ou preset.

Skip-if: Vous ne changez que d'autres stratégies.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from utils.parameters import EMA_CROSS_PRESET, ParameterSpec, Preset

from .base import StrategyBase, register_strategy


@register_strategy("ema_cross")
class EMACrossStrategy(StrategyBase):
    """
    Stratégie EMA Crossover (Trend Following).

    Stratégie classique de suivi de tendance utilisant deux moyennes
    mobiles exponentielles de périodes différentes.

    Paramètres:
        fast_period: Période de l'EMA rapide (défaut: 12)
        slow_period: Période de l'EMA lente (défaut: 26)
        leverage: Levier de trading (défaut: 1)

    Signaux:
        +1 (Long): EMA fast croise EMA slow à la hausse
        -1 (Short): EMA fast croise EMA slow à la baisse
        0: Sinon
    """

    def __init__(self):
        super().__init__(name="EMACross")

    @property
    def required_indicators(self) -> List[str]:
        """Cette stratégie calcule ses propres EMAs."""
        return []

    @property
    def default_params(self) -> Dict[str, Any]:
        """Paramètres par défaut."""
        return {
            "fast_period": 12,
            "slow_period": 26,
            "leverage": 1,  # Fixé à 1 - ne pas optimiser
            "k_sl": 2.0,  # Stop loss en % du prix
            "fees_bps": 10,
            "slippage_bps": 5
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        """Spécifications des paramètres."""
        return {
            "fast_period": ParameterSpec(
                name="fast_period",
                min_val=5, max_val=20, default=12,
                param_type="int",
                description="Période EMA rapide"
            ),
            "slow_period": ParameterSpec(
                name="slow_period",
                min_val=20, max_val=50, default=26,
                param_type="int",
                description="Période EMA lente"
            ),
            "k_sl": ParameterSpec(
                name="k_sl",
                min_val=1.0, max_val=5.0, default=2.0,
                param_type="float",
                description="Stop-loss en %"
            ),
            "leverage": ParameterSpec(
                name="leverage",
                min_val=1, max_val=10, default=1,
                param_type="int",
                description="Levier de trading (non optimisé)",
                optimize=False,
            ),
        }

    def get_preset(self) -> Optional[Preset]:
        """Retourne le preset EMA Cross."""
        return EMA_CROSS_PRESET

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any]
    ) -> pd.Series:
        """
        Génère les signaux de croisement EMA.

        Note: Cette stratégie calcule ses propres EMAs car elle a besoin
        de deux périodes spécifiques. Le registre d'indicateurs standard
        ne gère qu'une période à la fois.
        """
        # Initialiser signaux
        signals = pd.Series(0.0, index=df.index, dtype=np.float64, name="signals")

        close = df["close"]
        fast_period = int(params.get("fast_period", 12))
        slow_period = int(params.get("slow_period", 26))

        # Calculer les EMAs
        ema_fast = close.ewm(span=fast_period, adjust=True, min_periods=fast_period).mean()
        ema_slow = close.ewm(span=slow_period, adjust=True, min_periods=slow_period).mean()

        # Détecter les croisements
        # Fast au-dessus de slow
        fast_above = ema_fast > ema_slow
        # Utiliser shift avec fill_value pour éviter FutureWarning
        fast_above_prev = fast_above.shift(1, fill_value=False)

        # Golden Cross: fast passe au-dessus de slow
        golden_cross = fast_above & ~fast_above_prev

        # Death Cross: fast passe en dessous de slow
        death_cross = ~fast_above & fast_above_prev

        signals[golden_cross] = 1.0
        signals[death_cross] = -1.0

        return signals

    def describe(self) -> str:
        """Description de la stratégie."""
        return """
EMA Crossover Strategy (Trend Following)
========================================

Cette stratégie génère des signaux basés sur le croisement de deux EMAs:

LONG Signal:
  - L'EMA rapide croise l'EMA lente à la hausse (Golden Cross)
  - Indique un potentiel début de tendance haussière

SHORT Signal:
  - L'EMA rapide croise l'EMA lente à la baisse (Death Cross)
  - Indique un potentiel début de tendance baissière

Paramètres optimaux typiques:
  - Crypto court terme: fast=9, slow=21
  - Crypto moyen terme: fast=12, slow=26 (MACD standard)
  - Crypto long terme: fast=20, slow=50

Notes:
  - Fonctionne bien en marché tendanciel
  - Génère des faux signaux en marché range (whipsaw)
  - Combine bien avec un filtre de tendance (ADX, ATR)
"""


__all__ = ["EMACrossStrategy"]
