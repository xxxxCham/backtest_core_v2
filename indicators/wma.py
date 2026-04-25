"""Module-ID: indicators.wma

Purpose: Weighted Moving Average (WMA).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class WMASettings:
    period: int = 14


def wma(data: pd.Series | np.ndarray, period: int = 14) -> np.ndarray:
    if isinstance(data, pd.Series):
        data = data.values
    values = np.asarray(data, dtype=np.float64)
    period = max(int(period), 1)

    if len(values) < period:
        return np.full(len(values), np.nan)

    weights = np.arange(1, period + 1, dtype=np.float64)
    weights /= weights.sum()

    return (
        pd.Series(values)
        .rolling(window=period, min_periods=period)
        .apply(
            lambda x: float(np.dot(x, weights)),
            raw=True,
        )
        .values
    )


def calculate_wma(df: pd.DataFrame, **params) -> np.ndarray:
    return wma(df["close"], period=int(params.get("period", 14)))


register_indicator(
    "wma",
    calculate_wma,
    settings_class=WMASettings,
    required_columns=("close",),
    description="Weighted Moving Average",
)


__all__ = ["WMASettings", "calculate_wma", "wma"]
