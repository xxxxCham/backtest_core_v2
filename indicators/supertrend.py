"""
Module-ID: indicators.supertrend

Purpose: Indicateur SuperTrend - suivi tendance basé ATR (très populaire).

Role in pipeline: data

Key components: supertrend, SuperTrendSettings, calculate_supertrend

Inputs: DataFrame avec high, low, close; atr_period, atr_mult

Outputs: Dict{supertrend, direction} ou Tuple

Dependencies: pandas, numpy, atr, dataclasses

Conventions: bandes = hl_avg +/- ATR*mult; direction 1/-1; support/résistance dynamique.

Read-if: Modification ATR params, output format.

Skip-if: Vous utilisez juste calculate_indicator('supertrend').
"""

from dataclasses import dataclass
from typing import Tuple

import numpy as np
import pandas as pd

from .atr import atr


@dataclass
class SuperTrendSettings:
    """Paramètres SuperTrend."""
    atr_period: int = 10
    multiplier: float = 3.0


def supertrend(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    atr_period: int = 10,
    multiplier: float = 3.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Calcule SuperTrend.

    Args:
        high: Prix hauts
        low: Prix bas
        close: Prix de clôture
        atr_period: Période ATR (défaut: 10)
        multiplier: Multiplicateur ATR (défaut: 3.0)

    Returns:
        Tuple (supertrend_values, trend_direction)
        - trend_direction: 1 = haussier, -1 = baissier
    """
    if isinstance(high, pd.Series):
        high = high.values
    if isinstance(low, pd.Series):
        low = low.values
    if isinstance(close, pd.Series):
        close = close.values

    # ATR
    atr_values = atr(high, low, close, period=atr_period)

    # Basic bands
    hl_avg = (high + low) / 2.0
    basic_upper = hl_avg + multiplier * atr_values
    basic_lower = hl_avg - multiplier * atr_values

    n = len(close)

    # Final bands (state machine)
    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()

    for i in range(1, n):
        # Upper band
        if basic_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i - 1]

        # Lower band
        if basic_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = final_lower[i - 1]

    # SuperTrend et direction
    supertrend_values = np.empty(n)
    trend_direction = np.empty(n, dtype=int)

    # Initialisation
    if close[0] <= final_upper[0]:
        supertrend_values[0] = final_upper[0]
        trend_direction[0] = -1
    else:
        supertrend_values[0] = final_lower[0]
        trend_direction[0] = 1

    for i in range(1, n):
        prev_trend = trend_direction[i - 1]

        if prev_trend == 1:  # Was bullish
            if close[i] <= final_lower[i]:
                trend_direction[i] = -1
                supertrend_values[i] = final_upper[i]
            else:
                trend_direction[i] = 1
                supertrend_values[i] = final_lower[i]
        else:  # Was bearish
            if close[i] >= final_upper[i]:
                trend_direction[i] = 1
                supertrend_values[i] = final_lower[i]
            else:
                trend_direction[i] = -1
                supertrend_values[i] = final_upper[i]

    return supertrend_values, trend_direction


__all__ = ["supertrend", "SuperTrendSettings"]
