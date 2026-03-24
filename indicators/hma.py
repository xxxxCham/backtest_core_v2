"""
Module-ID: indicators.hma

Purpose: Hull Moving Average (HMA).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator
from .wma import wma


@dataclass
class HMASettings:
    period: int = 20


def hma(data: pd.Series | np.ndarray, period: int = 20) -> np.ndarray:
    if isinstance(data, pd.Series):
        data = data.values
    values = np.asarray(data, dtype=np.float64)
    period = max(int(period), 1)

    half_period = max(period // 2, 1)
    sqrt_period = max(int(np.sqrt(period)), 1)

    wma_half = wma(values, half_period)
    wma_full = wma(values, period)
    raw = 2.0 * wma_half - wma_full

    return wma(raw, sqrt_period)


def calculate_hma(df: pd.DataFrame, **params) -> np.ndarray:
    return hma(df["close"], period=int(params.get("period", 20)))


register_indicator(
    "hma",
    calculate_hma,
    settings_class=HMASettings,
    required_columns=("close",),
    description="Hull Moving Average",
)


__all__ = ["hma", "calculate_hma", "HMASettings"]
