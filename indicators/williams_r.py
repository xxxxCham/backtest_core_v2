"""
Module-ID: indicators.williams_r

Purpose: Indicateur Williams %R - oscillateur momentum surachat/survente.

Role in pipeline: data

Key components: williams_r, WilliamsRSettings, calculate_williams_r

Inputs: DataFrame avec high, low, close; period

Outputs: np.ndarray (-100 à 0)

Dependencies: pandas, numpy, dataclasses

Conventions: >-20 surachat, <-80 survente; inverse de %K Stochastic.

Read-if: Modification période, interprétation seuils.

Skip-if: Vous utilisez juste calculate_indicator('williams_r').
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class WilliamsRSettings:
    """Paramètres Williams %R."""
    period: int = 14


def williams_r(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """
    Calcule Williams %R.

    Formula: %R = (Highest High - Close) / (Highest High - Lowest Low) * -100

    Args:
        high: Prix hauts
        low: Prix bas
        close: Prix de clôture
        period: Période (défaut: 14)

    Returns:
        Valeurs entre -100 (survente) et 0 (surachat)
    """
    if isinstance(high, pd.Series):
        high_series = high
    else:
        high_series = pd.Series(high)

    if isinstance(low, pd.Series):
        low_series = low
    else:
        low_series = pd.Series(low)

    if isinstance(close, pd.Series):
        close = close.values

    highest_high = high_series.rolling(window=period).max().values
    lowest_low = low_series.rolling(window=period).min().values

    range_hl = highest_high - lowest_low

    williams_values = np.where(
        range_hl != 0,
        ((highest_high - close) / range_hl) * -100.0,
        -50.0
    )

    return williams_values


__all__ = ["williams_r", "WilliamsRSettings"]
