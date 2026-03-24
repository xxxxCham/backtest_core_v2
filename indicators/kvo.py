"""
Module-ID: indicators.kvo

Purpose: Klinger Volume Oscillator (KVO).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class KVOSettings:
    short_period: int = 34
    long_period: int = 55
    signal_period: int = 13


def kvo(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    volume: pd.Series | np.ndarray,
    short_period: int = 34,
    long_period: int = 55,
    signal_period: int = 13,
) -> dict[str, np.ndarray]:
    high_series = pd.Series(np.asarray(high, dtype=np.float64))
    low_series = pd.Series(np.asarray(low, dtype=np.float64))
    close_series = pd.Series(np.asarray(close, dtype=np.float64))
    volume_series = pd.Series(np.asarray(volume, dtype=np.float64))

    dm = (high_series - low_series).replace(0.0, np.nan)
    close_diff = close_series.diff()
    trend = pd.Series(np.where(close_diff >= 0.0, 1.0, -1.0), index=close_series.index)
    vf = (volume_series * trend * dm / dm).fillna(0.0)
    vf = (vf * close_diff.abs().fillna(0.0)).fillna(0.0)

    short_period = max(int(short_period), 1)
    long_period = max(int(long_period), 1)
    signal_period = max(int(signal_period), 1)

    kvo_line = vf.ewm(span=short_period, adjust=False).mean() - vf.ewm(
        span=long_period,
        adjust=False,
    ).mean()
    signal = kvo_line.ewm(span=signal_period, adjust=False).mean()

    return {
        "kvo": kvo_line.values,
        "signal": signal.values,
    }


def calculate_kvo(df: pd.DataFrame, **params) -> dict[str, np.ndarray]:
    return kvo(
        df["high"],
        df["low"],
        df["close"],
        df["volume"],
        short_period=int(params.get("short_period", 34)),
        long_period=int(params.get("long_period", 55)),
        signal_period=int(params.get("signal_period", 13)),
    )


register_indicator(
    "kvo",
    calculate_kvo,
    settings_class=KVOSettings,
    required_columns=("high", "low", "close", "volume"),
    description="Klinger Volume Oscillator",
)


__all__ = ["kvo", "calculate_kvo", "KVOSettings"]
