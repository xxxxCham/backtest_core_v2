"""Module-ID: indicators.elder_ray

Purpose: Elder Ray Index.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class ElderRaySettings:
    period: int = 13


def elder_ray(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    period: int = 13,
) -> dict[str, np.ndarray]:
    high_series = pd.Series(np.asarray(high, dtype=np.float64))
    low_series = pd.Series(np.asarray(low, dtype=np.float64))
    close_series = pd.Series(np.asarray(close, dtype=np.float64))
    ema_close = close_series.ewm(span=max(int(period), 1), adjust=False).mean()

    return {
        "bull_power": (high_series - ema_close).values,
        "bear_power": (low_series - ema_close).values,
    }


def calculate_elder_ray(df: pd.DataFrame, **params) -> dict[str, np.ndarray]:
    return elder_ray(
        df["high"],
        df["low"],
        df["close"],
        period=int(params.get("period", 13)),
    )


register_indicator(
    "elder_ray",
    calculate_elder_ray,
    settings_class=ElderRaySettings,
    required_columns=("high", "low", "close"),
    description="Elder Ray Index",
)


__all__ = ["ElderRaySettings", "calculate_elder_ray", "elder_ray"]
