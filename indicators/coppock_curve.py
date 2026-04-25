"""Module-ID: indicators.coppock_curve

Purpose: Coppock Curve.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class CoppockCurveSettings:
    long_roc: int = 14
    short_roc: int = 11
    period: int = 10


def coppock_curve(
    close: pd.Series | np.ndarray,
    long_roc: int = 14,
    short_roc: int = 11,
    period: int = 10,
) -> np.ndarray:
    close_series = pd.Series(np.asarray(close, dtype=np.float64))
    roc_long = close_series.pct_change(max(int(long_roc), 1)) * 100.0
    roc_short = close_series.pct_change(max(int(short_roc), 1)) * 100.0
    summed = roc_long + roc_short

    return summed.rolling(window=max(int(period), 1), min_periods=max(int(period), 1)).mean().values


def calculate_coppock_curve(df: pd.DataFrame, **params) -> np.ndarray:
    return coppock_curve(
        df["close"],
        long_roc=int(params.get("long_roc", 14)),
        short_roc=int(params.get("short_roc", 11)),
        period=int(params.get("period", 10)),
    )


register_indicator(
    "coppock_curve",
    calculate_coppock_curve,
    settings_class=CoppockCurveSettings,
    required_columns=("close",),
    description="Coppock Curve",
)


__all__ = ["CoppockCurveSettings", "calculate_coppock_curve", "coppock_curve"]
