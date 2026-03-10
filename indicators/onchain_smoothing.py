"""
Module-ID: indicators.onchain_smoothing

Purpose: Lissage générique on-chain - applique EMA/SMA à colonne quelconque.

Role in pipeline: technical indicator

Key components: OnchainSmoothingSettings, onchain_smoothing()

Inputs: [on_chain_series] ou colonne quelconque, period, type (ema/sma)

Outputs: numpy array lissée

Dependencies: numpy, pandas, indicators.ema, indicators.registry

Conventions: Type: ema ou sma; fleuriste EMA

Read-if: Lisser données on-chain ou custom.

Skip-if: Indicateur non utilisé.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from indicators.ema import ema, sma
from indicators.registry import register_indicator


@dataclass
class OnchainSmoothingSettings:
    """Settings for on-chain smoothing."""

    period: int = 14
    method: str = "ema"
    column: str = "close"

    def __post_init__(self) -> None:
        if self.period < 1:
            raise ValueError(f"period must be >= 1, got: {self.period}")
        if self.method not in ("ema", "sma"):
            raise ValueError("method must be 'ema' or 'sma'")


def onchain_smoothing(
    values: pd.Series | np.ndarray,
    period: int = 14,
    method: str = "ema",
    settings: OnchainSmoothingSettings | None = None,
) -> np.ndarray:
    """
    Smooth a series with EMA or SMA.

    Args:
        values: Input series
        period: Smoothing period
        method: 'ema' or 'sma'
        settings: Optional settings override

    Returns:
        Smoothed series
    """
    if settings is not None:
        period = settings.period
        method = settings.method

    if isinstance(values, pd.Series):
        values = values.values

    if method == "ema":
        return ema(values, period)
    return sma(values, period)


def calculate_onchain_smoothing(df: pd.DataFrame, **params) -> np.ndarray:
    """
    Wrapper for registry calculation.

    Params:
        column: Column name to smooth (default: close)
        period: Smoothing period (default: 14)
        method: 'ema' or 'sma' (default: ema)
    """
    column = params.get("column", "close")
    if column not in df.columns:
        raise ValueError(f"Column not found for onchain_smoothing: {column}")

    return onchain_smoothing(
        df[column],
        period=int(params.get("period", 14)),
        method=params.get("method", "ema"),
    )


register_indicator(
    "onchain_smoothing",
    calculate_onchain_smoothing,
    settings_class=OnchainSmoothingSettings,
    required_columns=("close",),
    description="On-chain Smoothing - EMA/SMA of a selected column",
)


__all__ = [
    "onchain_smoothing",
    "calculate_onchain_smoothing",
    "OnchainSmoothingSettings",
]
