"""
Module-ID: indicators.volume_oscillator

Purpose: Oscillateur volume - compare MMA court vs long du volume.

Role in pipeline: technical indicator

Key components: VolumeOscillatorSettings, volume_oscillator()

Inputs: [volume], period_short, period_long, type (ema/sma)

Outputs: numpy array oscillateur (short_ma - long_ma)

Dependencies: numpy, pandas, indicators.ema, indicators.registry

Conventions: MA court < long pour divergences; EMA par défaut

Read-if: Analyser momentum volume.

Skip-if: Indicateur non utilisé.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from indicators.ema import ema, sma
from indicators.registry import register_indicator


@dataclass
class VolumeOscillatorSettings:
    """Settings for Volume Oscillator."""

    short_period: int = 14
    long_period: int = 28
    method: str = "ema"

    def __post_init__(self) -> None:
        if self.short_period < 1:
            raise ValueError(f"short_period must be >= 1, got: {self.short_period}")
        if self.long_period < 1:
            raise ValueError(f"long_period must be >= 1, got: {self.long_period}")
        if self.long_period <= self.short_period:
            raise ValueError("long_period must be > short_period")
        if self.method not in ("ema", "sma"):
            raise ValueError("method must be 'ema' or 'sma'")


def volume_oscillator(
    volume: pd.Series | np.ndarray,
    short_period: int = 14,
    long_period: int = 28,
    method: str = "ema",
    settings: VolumeOscillatorSettings | None = None,
) -> np.ndarray:
    """
    Compute the Volume Oscillator (percent).

    Args:
        volume: Volume series
        short_period: Short MA period
        long_period: Long MA period
        method: 'ema' or 'sma'
        settings: Optional settings override

    Returns:
        Oscillator values in percent
    """
    if settings is not None:
        short_period = settings.short_period
        long_period = settings.long_period
        method = settings.method

    if isinstance(volume, pd.Series):
        volume = volume.values

    if method == "ema":
        short_ma = ema(volume, short_period)
        long_ma = ema(volume, long_period)
    else:
        short_ma = sma(volume, short_period)
        long_ma = sma(volume, long_period)

    oscillator = np.where(long_ma != 0, (short_ma - long_ma) / long_ma * 100.0, 0.0)
    return oscillator


def calculate_volume_oscillator(df: pd.DataFrame, **params) -> np.ndarray:
    """
    Wrapper for registry calculation.

    Params:
        short_period: Short MA period (default: 14)
        long_period: Long MA period (default: 28)
        method: 'ema' or 'sma' (default: 'ema')
    """
    return volume_oscillator(
        df["volume"],
        short_period=int(params.get("short_period", 14)),
        long_period=int(params.get("long_period", 28)),
        method=params.get("method", "ema"),
    )


register_indicator(
    "volume_oscillator",
    calculate_volume_oscillator,
    settings_class=VolumeOscillatorSettings,
    required_columns=("volume",),
    description="Volume Oscillator - Short vs long volume MA",
)


__all__ = [
    "volume_oscillator",
    "calculate_volume_oscillator",
    "VolumeOscillatorSettings",
]
