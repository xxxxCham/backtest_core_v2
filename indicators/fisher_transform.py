"""
Module-ID: indicators.fisher_transform

Purpose: Fisher Transform.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class FisherTransformSettings:
    period: int = 10


def fisher_transform(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    period: int = 10,
) -> dict[str, np.ndarray]:
    high_series = pd.Series(np.asarray(high, dtype=np.float64))
    low_series = pd.Series(np.asarray(low, dtype=np.float64))
    period = max(int(period), 1)

    hl2 = (high_series + low_series) / 2.0
    rolling_low = hl2.rolling(window=period, min_periods=period).min()
    rolling_high = hl2.rolling(window=period, min_periods=period).max()
    denominator = (rolling_high - rolling_low).replace(0.0, np.nan)

    normalized = 2.0 * ((hl2 - rolling_low) / denominator - 0.5)
    normalized = normalized.clip(-0.999, 0.999)
    fisher = 0.5 * np.log((1.0 + normalized) / (1.0 - normalized))
    trigger = fisher.shift(1)

    return {
        "fisher": fisher.values,
        "trigger": trigger.values,
    }


def calculate_fisher_transform(df: pd.DataFrame, **params) -> dict[str, np.ndarray]:
    return fisher_transform(df["high"], df["low"], period=int(params.get("period", 10)))


register_indicator(
    "fisher_transform",
    calculate_fisher_transform,
    settings_class=FisherTransformSettings,
    required_columns=("high", "low"),
    description="Fisher Transform",
)


__all__ = [
    "fisher_transform",
    "calculate_fisher_transform",
    "FisherTransformSettings",
]
