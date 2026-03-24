"""
Module-ID: indicators.cmf

Purpose: Chaikin Money Flow (CMF).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class CMFSettings:
    period: int = 20


def cmf(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    volume: pd.Series | np.ndarray,
    period: int = 20,
) -> np.ndarray:
    high_series = pd.Series(np.asarray(high, dtype=np.float64))
    low_series = pd.Series(np.asarray(low, dtype=np.float64))
    close_series = pd.Series(np.asarray(close, dtype=np.float64))
    volume_series = pd.Series(np.asarray(volume, dtype=np.float64))
    period = max(int(period), 1)

    denominator = (high_series - low_series).replace(0.0, np.nan)
    mfm = ((close_series - low_series) - (high_series - close_series)) / denominator
    mfv = mfm.fillna(0.0) * volume_series

    return (
        mfv.rolling(window=period, min_periods=period).sum()
        / volume_series.rolling(window=period, min_periods=period).sum()
    ).values


def calculate_cmf(df: pd.DataFrame, **params) -> np.ndarray:
    return cmf(
        df["high"],
        df["low"],
        df["close"],
        df["volume"],
        period=int(params.get("period", 20)),
    )


register_indicator(
    "cmf",
    calculate_cmf,
    settings_class=CMFSettings,
    required_columns=("high", "low", "close", "volume"),
    description="Chaikin Money Flow",
)


__all__ = ["cmf", "calculate_cmf", "CMFSettings"]
