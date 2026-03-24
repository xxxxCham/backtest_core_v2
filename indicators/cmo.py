"""
Module-ID: indicators.cmo

Purpose: Chande Momentum Oscillator (CMO).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class CMOSettings:
    period: int = 14


def cmo(data: pd.Series | np.ndarray, period: int = 14) -> np.ndarray:
    if isinstance(data, pd.Series):
        data = data.values
    values = np.asarray(data, dtype=np.float64)
    period = max(int(period), 1)

    diff = np.diff(values, prepend=values[0] if len(values) else 0.0)
    gains = np.where(diff > 0.0, diff, 0.0)
    losses = np.where(diff < 0.0, -diff, 0.0)

    sum_up = pd.Series(gains).rolling(window=period, min_periods=period).sum().values
    sum_down = pd.Series(losses).rolling(window=period, min_periods=period).sum().values
    denom = sum_up + sum_down

    return np.where(denom != 0.0, 100.0 * (sum_up - sum_down) / denom, 0.0)


def calculate_cmo(df: pd.DataFrame, **params) -> np.ndarray:
    return cmo(df["close"], period=int(params.get("period", 14)))


register_indicator(
    "cmo",
    calculate_cmo,
    settings_class=CMOSettings,
    required_columns=("close",),
    description="Chande Momentum Oscillator",
)


__all__ = ["cmo", "calculate_cmo", "CMOSettings"]
