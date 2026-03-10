"""
Module-ID: indicators.obv

Purpose: Indicateur OBV (On-Balance Volume) - volume cumulatif directionnel.

Role in pipeline: data

Key components: obv, OBVSettings, calculate_obv

Inputs: DataFrame avec close, volume

Outputs: np.ndarray (volume cumulatif signé)

Dependencies: pandas, numpy, dataclasses

Conventions: Volume cumulé +/- selon direction prix; fluxargent raw.

Read-if: Modification logique accumulation volume.

Skip-if: Vous utilisez juste calculate_indicator('obv').
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class OBVSettings:
    """Paramètres OBV (pas de paramètres configurables)."""
    pass


def obv(
    close: pd.Series | np.ndarray,
    volume: pd.Series | np.ndarray,
) -> np.ndarray:
    """
    Calcule On-Balance Volume.

    Args:
        close: Prix de clôture
        volume: Volume

    Returns:
        OBV values (cumulatif)
    """
    if isinstance(close, pd.Series):
        close = close.values
    if isinstance(volume, pd.Series):
        volume = volume.values

    # Direction: +1 si close > close_prev, -1 si <, 0 si =
    close_diff = np.diff(close, prepend=close[0])
    direction = np.sign(close_diff)

    # OBV = cumsum de (direction * volume)
    obv_values = np.cumsum(direction * volume)

    return obv_values


__all__ = ["obv", "OBVSettings"]
