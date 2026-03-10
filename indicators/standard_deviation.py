"""
Module-ID: indicators.standard_deviation

Purpose: Écart-type roulant d'une série de prix - mesure volatilité.

Role in pipeline: technical indicator

Key components: StandardDeviationSettings, standard_deviation()

Inputs: [close] ou [prix], period

Outputs: numpy array standard deviation

Dependencies: numpy, pandas, indicators.registry

Conventions: Été pondéré par défaut (ddof=0)

Read-if: Analyser volatilité prix.

Skip-if: Indicateur non utilisé.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from indicators.registry import register_indicator


@dataclass
class StandardDeviationSettings:
    """Settings for standard deviation."""

    period: int = 20

    def __post_init__(self) -> None:
        if self.period < 1:
            raise ValueError(f"period must be >= 1, got: {self.period}")


def standard_deviation(
    close: pd.Series | np.ndarray,
    period: int = 20,
    settings: StandardDeviationSettings | None = None,
) -> np.ndarray:
    """
    Compute rolling standard deviation.

    Args:
        close: Price series
        period: Rolling window length
        settings: Optional settings override

    Returns:
        Rolling standard deviation values
    """
    if settings is not None:
        period = settings.period

    if isinstance(close, pd.Series):
        close = close.values

    close_series = pd.Series(close, dtype="float64")
    std_values = close_series.rolling(window=period, min_periods=period).std(ddof=0)
    return std_values.values


def calculate_standard_deviation(df: pd.DataFrame, **params) -> np.ndarray:
    """
    Wrapper for registry calculation.

    Params:
        period: Rolling window length (default: 20)
    """
    return standard_deviation(
        df["close"],
        period=int(params.get("period", 20)),
    )


register_indicator(
    "standard_deviation",
    calculate_standard_deviation,
    settings_class=StandardDeviationSettings,
    required_columns=("close",),
    description="Standard Deviation - Rolling volatility of close",
)


__all__ = [
    "standard_deviation",
    "calculate_standard_deviation",
    "StandardDeviationSettings",
]
