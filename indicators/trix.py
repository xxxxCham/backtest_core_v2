"""Module-ID: indicators.trix

Purpose: Triple-smoothed rate of change momentum oscillator (TRIX).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class TRIXSettings:
    """Settings for TRIX."""

    period: int = 18

    def __post_init__(self) -> None:
        if self.period < 1:
            raise ValueError(f"period must be >= 1, got: {self.period}")


def trix(
    close: pd.Series | np.ndarray,
    period: int = 18,
    settings: TRIXSettings | None = None,
) -> np.ndarray:
    """Compute TRIX as the percent ROC of a triple EMA."""
    if settings is not None:
        period = settings.period

    period = max(int(period), 1)
    values = pd.Series(close, dtype="float64")

    ema1 = values.ewm(span=period, adjust=False, min_periods=period).mean()
    ema2 = ema1.ewm(span=period, adjust=False, min_periods=period).mean()
    ema3 = ema2.ewm(span=period, adjust=False, min_periods=period).mean()

    prev = ema3.shift(1)
    out = np.full(len(values), np.nan, dtype=np.float64)
    np.divide(
        (ema3.values - prev.values) * 100.0,
        prev.values,
        out=out,
        where=np.isfinite(prev.values) & (prev.values != 0.0),
    )
    return out


def calculate_trix(df: pd.DataFrame, **params) -> np.ndarray:
    return trix(df["close"], period=int(params.get("period", 18)))


register_indicator(
    "trix",
    calculate_trix,
    settings_class=TRIXSettings,
    required_columns=("close",),
    description="TRIX - triple-smoothed momentum rate of change",
)


__all__ = ["TRIXSettings", "calculate_trix", "trix"]
