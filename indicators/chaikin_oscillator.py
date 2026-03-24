"""
Module-ID: indicators.chaikin_oscillator

Purpose: Chaikin Oscillator.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class ChaikinOscillatorSettings:
    fast_period: int = 3
    slow_period: int = 10


def chaikin_oscillator(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    volume: pd.Series | np.ndarray,
    fast_period: int = 3,
    slow_period: int = 10,
) -> np.ndarray:
    high_series = pd.Series(np.asarray(high, dtype=np.float64))
    low_series = pd.Series(np.asarray(low, dtype=np.float64))
    close_series = pd.Series(np.asarray(close, dtype=np.float64))
    volume_series = pd.Series(np.asarray(volume, dtype=np.float64))

    denominator = (high_series - low_series).replace(0.0, np.nan)
    money_flow_multiplier = (
        ((close_series - low_series) - (high_series - close_series)) / denominator
    ).fillna(0.0)
    adl = (money_flow_multiplier * volume_series).cumsum()

    fast = adl.ewm(span=max(int(fast_period), 1), adjust=False).mean()
    slow = adl.ewm(span=max(int(slow_period), 1), adjust=False).mean()

    return (fast - slow).values


def calculate_chaikin_oscillator(df: pd.DataFrame, **params) -> np.ndarray:
    return chaikin_oscillator(
        df["high"],
        df["low"],
        df["close"],
        df["volume"],
        fast_period=int(params.get("fast_period", 3)),
        slow_period=int(params.get("slow_period", 10)),
    )


register_indicator(
    "chaikin_oscillator",
    calculate_chaikin_oscillator,
    settings_class=ChaikinOscillatorSettings,
    required_columns=("high", "low", "close", "volume"),
    description="Chaikin Oscillator",
)


__all__ = [
    "chaikin_oscillator",
    "calculate_chaikin_oscillator",
    "ChaikinOscillatorSettings",
]
