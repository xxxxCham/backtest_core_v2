"""Module-ID: indicators.tma

Purpose: Triangular Moving Average (TMA).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class TMASettings:
    period: int = 20


def tma(data: pd.Series | np.ndarray, period: int = 20) -> np.ndarray:
    if isinstance(data, pd.Series):
        data = data.values
    values = np.asarray(data, dtype=np.float64)
    period = max(int(period), 1)

    if len(values) < period:
        return np.full(len(values), np.nan)

    first = pd.Series(values).rolling(window=period, min_periods=period).mean()
    return first.rolling(window=period, min_periods=period).mean().values


def calculate_tma(df: pd.DataFrame, **params) -> np.ndarray:
    return tma(df["close"], period=int(params.get("period", 20)))


register_indicator(
    "tma",
    calculate_tma,
    settings_class=TMASettings,
    required_columns=("close",),
    description="Triangular Moving Average",
)


__all__ = ["TMASettings", "calculate_tma", "tma"]
