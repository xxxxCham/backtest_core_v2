"""
Module-ID: indicators.dpo

Purpose: Detrended Price Oscillator (DPO).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class DPOSettings:
    period: int = 20


def dpo(close: pd.Series | np.ndarray, period: int = 20) -> np.ndarray:
    close_series = pd.Series(np.asarray(close, dtype=np.float64))
    period = max(int(period), 1)
    shift = period // 2 + 1
    sma = close_series.rolling(window=period, min_periods=period).mean()

    return (close_series.shift(shift) - sma).values


def calculate_dpo(df: pd.DataFrame, **params) -> np.ndarray:
    return dpo(df["close"], period=int(params.get("period", 20)))


register_indicator(
    "dpo",
    calculate_dpo,
    settings_class=DPOSettings,
    required_columns=("close",),
    description="Detrended Price Oscillator",
)


__all__ = ["dpo", "calculate_dpo", "DPOSettings"]
