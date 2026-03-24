"""
Module-ID: indicators.ultimate_oscillator

Purpose: Ultimate Oscillator.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class UltimateOscillatorSettings:
    period1: int = 7
    period2: int = 14
    period3: int = 28


def ultimate_oscillator(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    period1: int = 7,
    period2: int = 14,
    period3: int = 28,
) -> np.ndarray:
    high_series = pd.Series(np.asarray(high, dtype=np.float64))
    low_series = pd.Series(np.asarray(low, dtype=np.float64))
    close_series = pd.Series(np.asarray(close, dtype=np.float64))

    prev_close = close_series.shift(1)
    true_low = np.minimum(low_series, prev_close)
    true_high = np.maximum(high_series, prev_close)

    bp = close_series - true_low
    tr = (true_high - true_low).replace(0.0, np.nan)

    avg1 = bp.rolling(window=max(int(period1), 1), min_periods=max(int(period1), 1)).sum() / tr.rolling(
        window=max(int(period1), 1), min_periods=max(int(period1), 1)
    ).sum()
    avg2 = bp.rolling(window=max(int(period2), 1), min_periods=max(int(period2), 1)).sum() / tr.rolling(
        window=max(int(period2), 1), min_periods=max(int(period2), 1)
    ).sum()
    avg3 = bp.rolling(window=max(int(period3), 1), min_periods=max(int(period3), 1)).sum() / tr.rolling(
        window=max(int(period3), 1), min_periods=max(int(period3), 1)
    ).sum()

    return (100.0 * (4.0 * avg1 + 2.0 * avg2 + avg3) / 7.0).values


def calculate_ultimate_oscillator(df: pd.DataFrame, **params) -> np.ndarray:
    return ultimate_oscillator(
        df["high"],
        df["low"],
        df["close"],
        period1=int(params.get("period1", 7)),
        period2=int(params.get("period2", 14)),
        period3=int(params.get("period3", 28)),
    )


register_indicator(
    "ultimate_oscillator",
    calculate_ultimate_oscillator,
    settings_class=UltimateOscillatorSettings,
    required_columns=("high", "low", "close"),
    description="Ultimate Oscillator",
)


__all__ = [
    "ultimate_oscillator",
    "calculate_ultimate_oscillator",
    "UltimateOscillatorSettings",
]
