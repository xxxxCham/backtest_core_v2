"""
Module-ID: indicators.amplitude_hunter

Purpose: Score l'extrémité plage intrabar vs baseline roulante - détecte amp volatilé.

Role in pipeline: technical indicator

Key components: AmplitudeHunterSettings, amplitude_hunter()

Inputs: [high, low], period, threshold

Outputs: numpy array scores [0, 1]

Dependencies: numpy, pandas, indicators.registry

Conventions: Score normalize [0, 1]; settings dataclass

Read-if: Utiliser amplitude hunter pour signaux volatilté.

Skip-if: Indicateur non utilisé.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from indicators.registry import register_indicator


@dataclass
class AmplitudeHunterSettings:
    """Settings for amplitude hunter."""

    period: int = 20

    def __post_init__(self) -> None:
        if self.period < 1:
            raise ValueError("period must be >= 1")


def amplitude_hunter(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    period: int = 20,
    settings: AmplitudeHunterSettings | None = None,
) -> dict[str, np.ndarray]:
    """
    Compute amplitude score based on range percent and rolling z-score.

    Returns:
        Dict with range_pct and score
    """
    if settings is not None:
        period = settings.period

    if isinstance(high, pd.Series):
        high = high.values
    if isinstance(low, pd.Series):
        low = low.values
    if isinstance(close, pd.Series):
        close = close.values

    high = np.asarray(high, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    close = np.asarray(close, dtype=np.float64)

    range_pct = np.where(close != 0, (high - low) / close * 100.0, 0.0)

    range_series = pd.Series(range_pct, dtype="float64")
    mean = range_series.rolling(window=period, min_periods=period).mean()
    std = range_series.rolling(window=period, min_periods=period).std(ddof=0)

    std_values = std.values
    mean_values = mean.values

    score = np.where(std_values != 0, (range_pct - mean_values) / std_values, 0.0)

    return {
        "range_pct": range_pct,
        "score": score,
    }


def calculate_amplitude_hunter(df: pd.DataFrame, **params) -> dict[str, np.ndarray]:
    """
    Wrapper for registry calculation.

    Params:
        period: Rolling window length (default: 20)
    """
    return amplitude_hunter(
        df["high"],
        df["low"],
        df["close"],
        period=int(params.get("period", 20)),
    )


register_indicator(
    "amplitude_hunter",
    calculate_amplitude_hunter,
    settings_class=AmplitudeHunterSettings,
    required_columns=("high", "low", "close"),
    description="Amplitude Hunter Score - Range z-score",
)


__all__ = [
    "amplitude_hunter",
    "calculate_amplitude_hunter",
    "AmplitudeHunterSettings",
]
