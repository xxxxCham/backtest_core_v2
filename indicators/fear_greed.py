"""
Module-ID: indicators.fear_greed

Purpose: Index crypto Peur & Avidite - utilise série fournie + lissage optionnel.

Role in pipeline: technical indicator

Key components: FearGreedSettings, fear_greed()

Inputs: fear_greed_series, smoothing_window, smoothing_type

Outputs: numpy array fear/greed score

Dependencies: numpy, pandas, indicators.ema, indicators.registry

Conventions: EMA ou SMA lissage; normalisation 0-100

Read-if: Utiliser Fear/Greed index pour contexte marché.

Skip-if: Indicateur non utilisé.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from indicators.ema import ema, sma
from indicators.registry import register_indicator


@dataclass
class FearGreedSettings:
    """Settings for fear/greed index."""

    smooth_period: int = 0
    method: str = "sma"
    column: str = "fear_greed"

    def __post_init__(self) -> None:
        if self.smooth_period < 0:
            raise ValueError("smooth_period must be >= 0")
        if self.method not in ("ema", "sma"):
            raise ValueError("method must be 'ema' or 'sma'")


def fear_greed_index(
    values: pd.Series | np.ndarray,
    smooth_period: int = 0,
    method: str = "sma",
    settings: FearGreedSettings | None = None,
) -> np.ndarray:
    """
    Return a fear/greed series with optional smoothing.

    Args:
        values: Input series (0-100 index preferred)
        smooth_period: Optional smoothing period
        method: 'ema' or 'sma'
        settings: Optional settings override

    Returns:
        Smoothed or raw index values
    """
    if settings is not None:
        smooth_period = settings.smooth_period
        method = settings.method

    if isinstance(values, pd.Series):
        values = values.values

    values = np.asarray(values, dtype=np.float64)

    if smooth_period and smooth_period > 1:
        if method == "ema":
            return ema(values, int(smooth_period))
        return sma(values, int(smooth_period))

    return values


def calculate_fear_greed(df: pd.DataFrame, **params) -> np.ndarray:
    """
    Wrapper for registry calculation.

    Params:
        column: Column name to use (default: fear_greed)
        smooth_period: Optional smoothing period (default: 0)
        method: 'ema' or 'sma' (default: sma)
    """
    column = params.get("column", "fear_greed")
    if column not in df.columns:
        raise ValueError(f"Column not found for fear_greed: {column}")

    return fear_greed_index(
        df[column],
        smooth_period=int(params.get("smooth_period", 0)),
        method=params.get("method", "sma"),
    )


register_indicator(
    "fear_greed",
    calculate_fear_greed,
    settings_class=FearGreedSettings,
    required_columns=(),
    description="Crypto Fear & Greed - External sentiment index",
)


__all__ = [
    "fear_greed_index",
    "calculate_fear_greed",
    "FearGreedSettings",
]
