"""Module-ID: indicators.force_index

Purpose: Force Index.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class ForceIndexSettings:
    period: int = 13


def force_index(
    close: pd.Series | np.ndarray,
    volume: pd.Series | np.ndarray,
    period: int = 13,
) -> np.ndarray:
    close_series = pd.Series(np.asarray(close, dtype=np.float64))
    volume_series = pd.Series(np.asarray(volume, dtype=np.float64))
    force = close_series.diff() * volume_series

    return force.ewm(span=max(int(period), 1), adjust=False).mean().values


def calculate_force_index(df: pd.DataFrame, **params) -> np.ndarray:
    return force_index(
        df["close"],
        df["volume"],
        period=int(params.get("period", 13)),
    )


register_indicator(
    "force_index",
    calculate_force_index,
    settings_class=ForceIndexSettings,
    required_columns=("close", "volume"),
    description="Force Index",
)


__all__ = ["ForceIndexSettings", "calculate_force_index", "force_index"]
