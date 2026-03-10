"""
Module-ID: indicators.pivot_points

Purpose: Points pivot classiques - calculés depuis barre précédente.

Role in pipeline: technical indicator

Key components: PivotPointsSettings, pivot_points()

Inputs: [high, low, close], method (classic/fibonacci/demark/camarilla)

Outputs: dict {pivot, resistance1, resistance2, support1, support2}

Dependencies: numpy, pandas, indicators.registry

Conventions: Méthodes: classic, fibonacci, demark, camarilla

Read-if: Utiliser pivots pour niveaux support/resistance.

Skip-if: Indicateur non utilisé.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from indicators.registry import register_indicator


@dataclass
class PivotPointsSettings:
    """Settings for pivot points."""

    method: str = "classic"

    def __post_init__(self) -> None:
        if self.method not in ("classic", "fibonacci", "woodie"):
            raise ValueError("method must be classic, fibonacci, or woodie")


def pivot_points(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    method: str = "classic",
    settings: PivotPointsSettings | None = None,
) -> dict[str, np.ndarray]:
    """
    Compute pivot points using the previous bar values.

    Args:
        high: High series
        low: Low series
        close: Close series
        method: classic, fibonacci, or woodie
        settings: Optional settings override

    Returns:
        Dict with pivot, r1/r2/r3, s1/s2/s3
    """
    if settings is not None:
        method = settings.method

    if method not in ("classic", "fibonacci", "woodie"):
        raise ValueError("method must be classic, fibonacci, or woodie")

    if isinstance(high, pd.Series):
        high = high.values
    if isinstance(low, pd.Series):
        low = low.values
    if isinstance(close, pd.Series):
        close = close.values

    high = np.asarray(high, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    close = np.asarray(close, dtype=np.float64)

    prev_high = np.roll(high, 1)
    prev_low = np.roll(low, 1)
    prev_close = np.roll(close, 1)

    prev_high[0] = np.nan
    prev_low[0] = np.nan
    prev_close[0] = np.nan

    price_range = prev_high - prev_low

    if method == "woodie":
        pivot = (prev_high + prev_low + 2 * prev_close) / 4.0
    else:
        pivot = (prev_high + prev_low + prev_close) / 3.0

    if method == "fibonacci":
        r1 = pivot + 0.382 * price_range
        s1 = pivot - 0.382 * price_range
        r2 = pivot + 0.618 * price_range
        s2 = pivot - 0.618 * price_range
        r3 = pivot + 1.0 * price_range
        s3 = pivot - 1.0 * price_range
    else:
        r1 = 2 * pivot - prev_low
        s1 = 2 * pivot - prev_high
        r2 = pivot + price_range
        s2 = pivot - price_range
        r3 = prev_high + 2 * (pivot - prev_low)
        s3 = prev_low - 2 * (prev_high - pivot)

    return {
        "pivot": pivot,
        "r1": r1,
        "s1": s1,
        "r2": r2,
        "s2": s2,
        "r3": r3,
        "s3": s3,
    }


def _normalize_method(method: object) -> str:
    """Normalize method values coming from CLI/UI/sweep/optuna into a valid string."""
    method_map = {0: "classic", 1: "fibonacci", 2: "woodie"}

    if method is None:
        return "classic"

    if isinstance(method, str):
        m = method.strip().lower()
        if m.isdigit():
            return method_map.get(int(m), "classic")
        if m in ("classic", "fibonacci", "woodie"):
            return m
        return "classic"

    # Handle numpy scalars (np.int64, np.float64, etc.)
    if isinstance(method, np.generic):
        try:
            return _normalize_method(method.item())
        except Exception:
            return "classic"

    if isinstance(method, (int, np.integer)):
        return method_map.get(int(method), "classic")

    if isinstance(method, (float, np.floating)):
        try:
            if np.isnan(method):
                return "classic"
        except TypeError:
            return "classic"
        return method_map.get(int(method), "classic")

    return "classic"


def calculate_pivot_points(
    df: pd.DataFrame,
    **params,
) -> dict[str,  np.ndarray]:
    """
    Wrapper for registry calculation.

    Params:
        method: classic, fibonacci, or woodie (default: classic)
    """
    method = _normalize_method(params.get("method", "classic"))

    return pivot_points(
        df["high"],
        df["low"],
        df["close"],
        method=method,
    )


register_indicator(
    "pivot_points",
    calculate_pivot_points,
    settings_class=PivotPointsSettings,
    required_columns=("high", "low", "close"),
    description="Pivot Points - Classic support/resistance levels",
)


__all__ = [
    "pivot_points",
    "calculate_pivot_points",
    "PivotPointsSettings",
]
