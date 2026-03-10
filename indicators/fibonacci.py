"""
Module-ID: indicators.fibonacci

Purpose: Niveaux Fibonacci retracement roulants basés fenetre high/low.

Role in pipeline: technical indicator

Key components: FibonacciSettings, fibonacci()

Inputs: [high, low], period, fibonacci_ratios

Outputs: dict {fib_0, fib_236, fib_382, fib_500, fib_618, fib_786, fib_1}

Dependencies: numpy, pandas, indicators.registry

Conventions: Niveaux standard 0%, 23.6%, 38.2%, 50%, 61.8%, 78.6%, 100%

Read-if: Utiliser Fibonacci pour niveaux support/resistance.

Skip-if: Indicateur non utilisé.
"""

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd

from indicators.registry import register_indicator


@dataclass
class FibonacciSettings:
    """Settings for Fibonacci levels."""

    period: int = 50
    levels: tuple[float, ...] = field(
        default_factory=lambda: (0.236, 0.382, 0.5, 0.618, 0.786)
    )

    def __post_init__(self) -> None:
        if self.period < 1:
            raise ValueError(f"period must be >= 1, got: {self.period}")


def fibonacci_levels(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    period: int = 50,
    levels: Iterable[float] | None = None,
    settings: FibonacciSettings | None = None,
) -> dict[str, np.ndarray]:
    """
    Compute rolling Fibonacci retracement levels.

    Args:
        high: High price series
        low: Low price series
        period: Lookback window for high/low
        levels: Iterable of retracement levels (0-1)
        settings: Optional settings override

    Returns:
        Dict of level arrays including high/low
    """
    if settings is not None:
        period = settings.period
        levels = settings.levels

    if levels is None:
        levels = (0.236, 0.382, 0.5, 0.618, 0.786)

    if isinstance(high, pd.Series):
        high = high.values
    if isinstance(low, pd.Series):
        low = low.values

    high_series = pd.Series(high, dtype="float64")
    low_series = pd.Series(low, dtype="float64")

    rolling_high = high_series.rolling(window=period, min_periods=period).max().values
    rolling_low = low_series.rolling(window=period, min_periods=period).min().values

    price_range = rolling_high - rolling_low

    results: dict[str, np.ndarray] = {
        "high": rolling_high,
        "low": rolling_low,
    }

    for level in levels:
        key = f"level_{int(round(level * 1000))}"
        results[key] = rolling_high - price_range * float(level)

    return results


def calculate_fibonacci_levels(df: pd.DataFrame, **params) -> dict[str, np.ndarray]:
    """
    Wrapper for registry calculation.

    Params:
        period: Lookback window (default: 50)
    """
    return fibonacci_levels(
        df["high"],
        df["low"],
        period=int(params.get("period", 50)),
    )


register_indicator(
    "fibonacci_levels",
    calculate_fibonacci_levels,
    settings_class=FibonacciSettings,
    required_columns=("high", "low"),
    description="Fibonacci Levels - Rolling retracement bands",
)


__all__ = [
    "fibonacci_levels",
    "calculate_fibonacci_levels",
    "FibonacciSettings",
]
