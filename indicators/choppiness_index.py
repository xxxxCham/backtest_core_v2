"""Module-ID: indicators.choppiness_index

Purpose: Choppiness Index for range-vs-trend regime filtering.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class ChoppinessIndexSettings:
    """Settings for Choppiness Index."""

    period: int = 14

    def __post_init__(self) -> None:
        if self.period < 2:
            raise ValueError(f"period must be >= 2, got: {self.period}")


def choppiness_index(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    period: int = 14,
    settings: ChoppinessIndexSettings | None = None,
) -> np.ndarray:
    """Compute Choppiness Index.

    Higher values indicate choppy/ranging conditions; lower values indicate a
    more directional trend regime.
    """
    if settings is not None:
        period = settings.period

    period = max(int(period), 2)
    high_s = pd.Series(high, dtype="float64")
    low_s = pd.Series(low, dtype="float64")
    close_s = pd.Series(close, dtype="float64")
    prev_close = close_s.shift(1)

    true_range = pd.concat(
        [
            high_s - low_s,
            (high_s - prev_close).abs(),
            (low_s - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    tr_sum = true_range.rolling(window=period, min_periods=period).sum()
    rolling_high = high_s.rolling(window=period, min_periods=period).max()
    rolling_low = low_s.rolling(window=period, min_periods=period).min()
    range_span = rolling_high - rolling_low

    ratio = tr_sum / range_span.replace(0.0, np.nan)
    values = 100.0 * np.log10(ratio) / np.log10(float(period))
    return values.values


def calculate_choppiness_index(df: pd.DataFrame, **params) -> np.ndarray:
    return choppiness_index(
        df["high"],
        df["low"],
        df["close"],
        period=int(params.get("period", 14)),
    )


register_indicator(
    "choppiness_index",
    calculate_choppiness_index,
    settings_class=ChoppinessIndexSettings,
    required_columns=("high", "low", "close"),
    description="Choppiness Index - range versus trend regime filter",
)


__all__ = [
    "ChoppinessIndexSettings",
    "calculate_choppiness_index",
    "choppiness_index",
]
