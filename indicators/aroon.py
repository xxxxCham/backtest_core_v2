"""
Module-ID: indicators.aroon

Purpose: Indicateur Aroon (Aroon Up/Down) - temps depuis haut/bas.

Role in pipeline: data

Key components: aroon, AroonSettings, calculate_aroon, aroon_up, aroon_down

Inputs: DataFrame avec high, low; period

Outputs: Dict{aroon_up, aroon_down} ou Tuple

Dependencies: pandas, numpy, dataclasses

Conventions: Aroon Up = (period - bars_since_high) / period * 100; >70 tendance, <30 faible.

Read-if: Modification période, formule bars_since.

Skip-if: Vous utilisez juste calculate_indicator('aroon').
"""

from dataclasses import dataclass
from typing import Tuple

import numpy as np
import pandas as pd


@dataclass
class AroonSettings:
    """Paramètres Aroon."""
    period: int = 14


def aroon(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    period: int = 14,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Calcule Aroon Up/Down.

    Args:
        high: Prix hauts
        low: Prix bas
        period: Période (défaut: 14)

    Returns:
        Tuple (aroon_up, aroon_down) en pourcentage (0-100)
    """
    if isinstance(high, pd.Series):
        high = high.values
    if isinstance(low, pd.Series):
        low = low.values

    n = len(high)
    aroon_up = np.full(n, np.nan)
    aroon_down = np.full(n, np.nan)

    for i in range(period - 1, n):
        window_high = high[i - period + 1:i + 1]
        window_low = low[i - period + 1:i + 1]

        bars_since_high = period - 1 - int(np.argmax(window_high))
        bars_since_low = period - 1 - int(np.argmin(window_low))

        aroon_up[i] = 100.0 * (period - bars_since_high) / period
        aroon_down[i] = 100.0 * (period - bars_since_low) / period

    return aroon_up, aroon_down


__all__ = ["aroon", "AroonSettings"]
