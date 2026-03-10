"""
Module-ID: indicators.momentum

Purpose: Indicateur Momentum - taux changement prix simple.

Role in pipeline: data

Key components: momentum, MomentumSettings, calculate_momentum

Inputs: DataFrame avec close; period

Outputs: np.ndarray (différence close actuel - close n periodes avant)

Dependencies: pandas, numpy, dataclasses

Conventions: Momentum = Close - Close[n]; simple mais efficace accélération/décélération.

Read-if: Modification période.

Skip-if: Vous utilisez juste calculate_indicator('momentum').
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MomentumSettings:
    """Paramètres Momentum."""
    period: int = 14


def momentum(
    close: pd.Series | np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """
    Calcule Momentum.

    Args:
        close: Prix de clôture
        period: Période (défaut: 14)

    Returns:
        Différence de prix sur la période
    """
    if isinstance(close, pd.Series):
        close = close.values

    momentum_values = close - np.roll(close, period)
    momentum_values[:period] = np.nan

    return momentum_values


__all__ = ["momentum", "MomentumSettings"]
