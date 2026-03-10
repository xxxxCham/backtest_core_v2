"""
Module-ID: indicators.mfi

Purpose: Indicateur MFI (Money Flow Index) - RSI pondéré par volume.

Role in pipeline: data

Key components: mfi, MFISettings, calculate_mfi

Inputs: DataFrame avec high, low, close, volume; period (14)

Outputs: np.ndarray (0-100 oscillateur)

Dependencies: pandas, numpy, dataclasses

Conventions: Similaire RSI mais intègre volume; >80 suracheté, <20 survendu.

Read-if: Modification période, formule flux argent.

Skip-if: Vous utilisez juste calculate_indicator('mfi').
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MFISettings:
    """Paramètres Money Flow Index."""
    period: int = 14


def mfi(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    volume: pd.Series | np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """
    Calcule Money Flow Index.

    Args:
        high: Prix hauts
        low: Prix bas
        close: Prix de clôture
        volume: Volume
        period: Période (défaut: 14)

    Returns:
        MFI values (0-100)
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

    # Raw Money Flow
    raw_money_flow = typical_price * volume

    # Direction basée sur typical price
    tp_diff = np.diff(typical_price, prepend=typical_price[0])

    positive_flow = np.where(tp_diff > 0, raw_money_flow, 0)
    negative_flow = np.where(tp_diff < 0, raw_money_flow, 0)

    # Rolling sum
    pos_series = pd.Series(positive_flow)
    neg_series = pd.Series(negative_flow)

    positive_mf = pos_series.rolling(window=period).sum().values
    negative_mf = neg_series.rolling(window=period).sum().values

    # Money Flow Ratio
    mf_ratio = np.where(negative_mf != 0, positive_mf / negative_mf, 1.0)

    # MFI
    mfi_values = 100.0 - (100.0 / (1.0 + mf_ratio))

    return mfi_values


__all__ = ["mfi", "MFISettings"]
