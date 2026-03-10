"""
Module-ID: indicators.vwap

Purpose: Indicateur VWAP (prix moyen pondéré par volume) institutionnel.

Role in pipeline: data

Key components: vwap, VWAPSettings, calculate_vwap

Inputs: DataFrame avec high, low, close, volume; anchored, period flags

Outputs: np.ndarray (VWAP cumulatif ou glissant)

Dependencies: pandas, numpy, dataclasses

Conventions: VWAP = somme(prix*vol) / somme(vol); ancré ou glissant; prix institutionnel de ref.

Read-if: Modification ancrage, période glissante.

Skip-if: Vous utilisez juste calculate_indicator('vwap').
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class VWAPSettings:
    """Paramètres VWAP."""
    anchored: bool = False  # Si True, ancré au début des données
    period: Optional[int] = None  # Si fourni, VWAP glissant


def vwap(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    volume: pd.Series | np.ndarray,
    period: Optional[int] = None,
) -> np.ndarray:
    """
    Calcule VWAP (Volume Weighted Average Price).

    Args:
        high: Prix hauts
        low: Prix bas
        close: Prix de clôture
        volume: Volume
        period: Période glissante (None = ancré depuis début)

    Returns:
        Valeurs VWAP
    """
    if isinstance(high, pd.Series):
        high = high.values
    if isinstance(low, pd.Series):
        low = low.values
    if isinstance(close, pd.Series):
        close = close.values
    if isinstance(volume, pd.Series):
        volume = volume.values

    # Typical Price
    typical_price = (high + low + close) / 3.0
    tp_volume = typical_price * volume

    if period is None:
        # VWAP ancré (depuis début)
        cumulative_tp_volume = np.cumsum(tp_volume)
        cumulative_volume = np.cumsum(volume)
        vwap_values = np.empty_like(typical_price)
        mask = cumulative_volume != 0
        vwap_values[mask] = cumulative_tp_volume[mask] / cumulative_volume[mask]
        vwap_values[~mask] = typical_price[~mask]
    else:
        # VWAP glissant
        tp_series = pd.Series(tp_volume)
        vol_series = pd.Series(volume)
        rolling_tp = tp_series.rolling(window=period).sum().values
        rolling_vol = vol_series.rolling(window=period).sum().values
        vwap_values = np.empty_like(typical_price)
        mask = rolling_vol != 0
        vwap_values[mask] = rolling_tp[mask] / rolling_vol[mask]
        vwap_values[~mask] = typical_price[~mask]

    return vwap_values


__all__ = ["vwap", "VWAPSettings"]
