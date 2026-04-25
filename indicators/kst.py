"""Module-ID: indicators.kst

Purpose: Know Sure Thing (KST) oscillator.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class KSTSettings:
    roc1: int = 10
    roc2: int = 15
    roc3: int = 20
    roc4: int = 30
    ma1: int = 10
    ma2: int = 10
    ma3: int = 10
    ma4: int = 15


def kst(
    data: pd.Series | np.ndarray,
    roc1: int = 10,
    roc2: int = 15,
    roc3: int = 20,
    roc4: int = 30,
    ma1: int = 10,
    ma2: int = 10,
    ma3: int = 10,
    ma4: int = 15,
) -> np.ndarray:
    if isinstance(data, pd.Series):
        data = data.values
    values = np.asarray(data, dtype=np.float64)
    series = pd.Series(values)

    roc1v = series.pct_change(max(int(roc1), 1)) * 100.0
    roc2v = series.pct_change(max(int(roc2), 1)) * 100.0
    roc3v = series.pct_change(max(int(roc3), 1)) * 100.0
    roc4v = series.pct_change(max(int(roc4), 1)) * 100.0

    return (
        roc1v.rolling(window=max(int(ma1), 1), min_periods=max(int(ma1), 1)).mean()
        + 2.0 * roc2v.rolling(window=max(int(ma2), 1), min_periods=max(int(ma2), 1)).mean()
        + 3.0 * roc3v.rolling(window=max(int(ma3), 1), min_periods=max(int(ma3), 1)).mean()
        + 4.0 * roc4v.rolling(window=max(int(ma4), 1), min_periods=max(int(ma4), 1)).mean()
    ).values


def calculate_kst(df: pd.DataFrame, **params) -> np.ndarray:
    return kst(df["close"], **params)


register_indicator(
    "kst",
    calculate_kst,
    settings_class=KSTSettings,
    required_columns=("close",),
    description="Know Sure Thing oscillator",
)


__all__ = ["KSTSettings", "calculate_kst", "kst"]
