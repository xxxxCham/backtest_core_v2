"""Module-ID: indicators.vix

Purpose: VIX-style realized volatility proxy from OHLCV close prices.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class VIXSettings:
    """Settings for the VIX-style realized volatility proxy."""

    period: int = 20
    periods_per_year: float = 365.0

    def __post_init__(self) -> None:
        if self.period < 2:
            raise ValueError(f"period must be >= 2, got: {self.period}")
        if self.periods_per_year <= 0:
            raise ValueError(
                f"periods_per_year must be > 0, got: {self.periods_per_year}",
            )


def vix(
    close: pd.Series | np.ndarray,
    period: int = 20,
    periods_per_year: float = 365.0,
    settings: VIXSettings | None = None,
) -> np.ndarray:
    """Compute a VIX-style realized volatility proxy.

    This is not the external CBOE VIX feed. It is an OHLCV-only proxy based on
    rolling log-return volatility, annualized and expressed in percent.
    """
    if settings is not None:
        period = settings.period
        periods_per_year = settings.periods_per_year

    period = max(int(period), 2)
    periods_per_year = float(periods_per_year)

    if isinstance(close, pd.Series):
        close_values = close.astype("float64")
    else:
        close_values = pd.Series(np.asarray(close, dtype=np.float64))

    safe_close = close_values.where(close_values > 0.0)
    log_returns = np.log(safe_close / safe_close.shift(1))
    realized = log_returns.rolling(window=period, min_periods=period).std(ddof=0)
    return (realized * np.sqrt(periods_per_year) * 100.0).values


def calculate_vix(df: pd.DataFrame, **params) -> np.ndarray:
    return vix(
        df["close"],
        period=int(params.get("period", 20)),
        periods_per_year=float(params.get("periods_per_year", 365.0)),
    )


register_indicator(
    "vix",
    calculate_vix,
    settings_class=VIXSettings,
    required_columns=("close",),
    description="VIX-style realized volatility proxy from rolling log returns",
)


__all__ = ["VIXSettings", "calculate_vix", "vix"]
