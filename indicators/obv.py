"""Module-ID: indicators.obv

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


def obv(
    close: pd.Series | np.ndarray,
    volume: pd.Series | np.ndarray,
) -> np.ndarray:
    """Calcule On-Balance Volume.

    Args:
        close: Prix de clôture
        volume: Volume

    Returns:
        OBV values (cumulatif)

    """
    if isinstance(close, pd.Series):
        close = close.to_numpy()
    if isinstance(volume, pd.Series):
        volume = volume.to_numpy()

    close_array = np.asarray(close, dtype=np.float64)
    volume_array = np.asarray(volume, dtype=np.float64)

    if close_array.ndim != 1 or volume_array.ndim != 1:
        raise ValueError("close and volume must be 1D arrays")
    if close_array.size != volume_array.size:
        raise ValueError("close and volume must have the same length")
    if close_array.size == 0:
        return np.array([], dtype=np.float64)

    # Direction: +1 si close > close_prev, -1 si <, 0 si =
    close_diff = np.diff(close_array, prepend=close_array[0])
    direction = np.sign(np.nan_to_num(close_diff, nan=0.0))

    # OBV = cumsum de (direction * volume)
    obv_values = np.cumsum(direction * np.nan_to_num(volume_array, nan=0.0), dtype=np.float64)

    return obv_values


__all__ = ["OBVSettings", "obv"]
