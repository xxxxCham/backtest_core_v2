"""
Module-ID: indicators.mass_index

Purpose: Mass Index.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class MassIndexSettings:
    period: int = 9
    ema_period: int = 25


def mass_index(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    period: int = 9,
    ema_period: int = 25,
) -> np.ndarray:
    high_series = pd.Series(np.asarray(high, dtype=np.float64))
    low_series = pd.Series(np.asarray(low, dtype=np.float64))
    period = max(int(period), 1)
    ema_period = max(int(ema_period), 1)

    high_low_range = high_series - low_series
    ema1 = high_low_range.ewm(span=ema_period, adjust=False).mean()
    ema2 = ema1.ewm(span=ema_period, adjust=False).mean()
    ratio = ema1 / ema2.replace(0.0, np.nan)

    return ratio.rolling(window=period, min_periods=period).sum().values


def calculate_mass_index(df: pd.DataFrame, **params) -> np.ndarray:
    return mass_index(
        df["high"],
        df["low"],
        period=int(params.get("period", 9)),
        ema_period=int(params.get("ema_period", 25)),
    )


register_indicator(
    "mass_index",
    calculate_mass_index,
    settings_class=MassIndexSettings,
    required_columns=("high", "low"),
    description="Mass Index",
)


__all__ = ["mass_index", "calculate_mass_index", "MassIndexSettings"]
