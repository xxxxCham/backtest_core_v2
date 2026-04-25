"""Module-ID: indicators.tsi

Purpose: True Strength Index (TSI).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class TSISettings:
    long_period: int = 25
    short_period: int = 13


def tsi(
    data: pd.Series | np.ndarray,
    long_period: int = 25,
    short_period: int = 13,
) -> np.ndarray:
    if isinstance(data, pd.Series):
        data = data.values
    values = np.asarray(data, dtype=np.float64)
    long_period = max(int(long_period), 1)
    short_period = max(int(short_period), 1)

    diff = np.diff(values, prepend=values[0] if len(values) else 0.0)
    abs_diff = np.abs(diff)

    momentum = pd.Series(diff)
    abs_momentum = pd.Series(abs_diff)

    momentum_ema = momentum.ewm(span=long_period, adjust=False).mean()
    abs_momentum_ema = abs_momentum.ewm(span=long_period, adjust=False).mean()
    momentum_double = momentum_ema.ewm(span=short_period, adjust=False).mean().values
    abs_momentum_double = abs_momentum_ema.ewm(span=short_period, adjust=False).mean().values

    tsi_values = np.zeros(len(values), dtype=np.float64)
    np.divide(
        100.0 * momentum_double,
        abs_momentum_double,
        out=tsi_values,
        where=abs_momentum_double != 0.0,
    )
    return tsi_values


def calculate_tsi(df: pd.DataFrame, **params) -> np.ndarray:
    return tsi(
        df["close"],
        long_period=int(params.get("long_period", 25)),
        short_period=int(params.get("short_period", 13)),
    )


register_indicator(
    "tsi",
    calculate_tsi,
    settings_class=TSISettings,
    required_columns=("close",),
    description="True Strength Index",
)


__all__ = ["TSISettings", "calculate_tsi", "tsi"]
