"""
Module-ID: indicators.eom

Purpose: Ease of Movement (EOM).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class EOMSettings:
    period: int = 14


def eom(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    volume: pd.Series | np.ndarray,
    period: int = 14,
) -> np.ndarray:
    high_series = pd.Series(np.asarray(high, dtype=np.float64))
    low_series = pd.Series(np.asarray(low, dtype=np.float64))
    volume_series = pd.Series(np.asarray(volume, dtype=np.float64))
    period = max(int(period), 1)

    distance = ((high_series + low_series) / 2.0).diff()
    box_ratio = volume_series / (high_series - low_series).replace(0.0, np.nan)
    eom_raw = distance / box_ratio.replace(0.0, np.nan)

    return eom_raw.rolling(window=period, min_periods=period).mean().values


def calculate_eom(df: pd.DataFrame, **params) -> np.ndarray:
    return eom(
        df["high"],
        df["low"],
        df["volume"],
        period=int(params.get("period", 14)),
    )


register_indicator(
    "eom",
    calculate_eom,
    settings_class=EOMSettings,
    required_columns=("high", "low", "volume"),
    description="Ease of Movement",
)


__all__ = ["eom", "calculate_eom", "EOMSettings"]
