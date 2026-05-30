"""Sentinel strategies and tiny datasets for the MVP backtest audit."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from strategies.base import StrategyBase, register_strategy
from utils.parameters import ParameterSpec


def make_sentinel_ohlcv(kind: str = "trend", periods: int = 12) -> pd.DataFrame:
    """Build deterministic OHLCV data for audit tests."""
    index = pd.date_range("2024-01-01", periods=periods, freq="h", tz="UTC")
    if kind == "flat":
        close = np.full(periods, 100.0, dtype=np.float64)
        high = close + 0.2
        low = close - 0.2
    elif kind == "stop":
        close = np.array([100.0, 99.7, 99.5, 99.4, 99.3, 99.2, 99.1, 99.0, 98.9, 98.8, 98.7, 98.6])[:periods]
        high = close + 0.2
        low = close - 0.6
    elif kind == "tp":
        close = np.array([100.0, 100.4, 100.6, 100.7, 100.8, 100.9, 101.0, 101.1, 101.2, 101.3, 101.4, 101.5])[
            :periods
        ]
        high = close + 0.8
        low = close - 0.2
    else:
        close = np.linspace(100.0, 111.0, periods, dtype=np.float64)
        high = close + 0.4
        low = close - 0.4
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(periods, 1000.0, dtype=np.float64),
        },
        index=index,
    )


def _common_specs() -> dict[str, ParameterSpec]:
    return {
        "leverage": ParameterSpec("leverage", 1, 10, 1, step=1, param_type="int", optimize=False),
        "fees_bps": ParameterSpec("fees_bps", 0, 2000, 0, step=1, param_type="float", optimize=False),
        "slippage_bps": ParameterSpec("slippage_bps", 0, 1000, 0, step=1, param_type="float", optimize=False),
        "warmup": ParameterSpec("warmup", 0, 20, 0, step=1, param_type="int", optimize=False),
        "k_sl": ParameterSpec("k_sl", 0.01, 99.0, 50.0, step=0.01, param_type="float", optimize=False),
    }


class _AuditSentinelBase(StrategyBase):
    @property
    def required_indicators(self) -> list[str]:
        return []

    @property
    def default_params(self) -> dict[str, Any]:
        return {
            "leverage": 1,
            "fees_bps": 0.0,
            "slippage_bps": 0.0,
            "warmup": 0,
            "k_sl": 50.0,
        }

    @property
    def parameter_specs(self) -> dict[str, ParameterSpec]:
        return _common_specs()


@register_strategy("always_long")
class AlwaysLongSentinel(_AuditSentinelBase):
    def __init__(self):
        super().__init__(name="always_long")

    def generate_signals(self, df: pd.DataFrame, indicators: dict[str, Any], params: dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64, name="signals")
        warmup = max(0, int(params.get("warmup", 0)))
        if warmup < len(signals):
            signals.iloc[warmup] = 1.0
        return signals


@register_strategy("never_trade")
class NeverTradeSentinel(_AuditSentinelBase):
    def __init__(self):
        super().__init__(name="never_trade")

    def generate_signals(self, df: pd.DataFrame, indicators: dict[str, Any], params: dict[str, Any]) -> pd.Series:
        return pd.Series(0.0, index=df.index, dtype=np.float64, name="signals")


@register_strategy("stop_near")
class StopNearSentinel(_AuditSentinelBase):
    def __init__(self):
        super().__init__(name="stop_near")

    @property
    def default_params(self) -> dict[str, Any]:
        params = super().default_params
        params["k_sl"] = 50.0
        return params

    def generate_signals(self, df: pd.DataFrame, indicators: dict[str, Any], params: dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64, name="signals")
        if len(signals) > 0:
            signals.iloc[0] = 1.0
        return signals


@register_strategy("tp_near")
class TakeProfitNearSentinel(_AuditSentinelBase):
    def __init__(self):
        super().__init__(name="tp_near")

    @property
    def default_params(self) -> dict[str, Any]:
        params = super().default_params
        params["take_profit_pct"] = 999.0
        return params

    @property
    def parameter_specs(self) -> dict[str, ParameterSpec]:
        specs = super().parameter_specs
        specs["take_profit_pct"] = ParameterSpec(
            "take_profit_pct",
            0.01,
            1000.0,
            999.0,
            step=0.01,
            param_type="float",
            optimize=False,
        )
        return specs

    def generate_signals(self, df: pd.DataFrame, indicators: dict[str, Any], params: dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64, name="signals")
        if len(signals) == 0:
            return signals
        signals.iloc[0] = 1.0
        take_profit_pct = float(params.get("take_profit_pct", 999.0))
        entry_price = float(df["close"].iloc[0])
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        df.loc[df.index[0], "bb_tp_long"] = entry_price * (1.0 + take_profit_pct * 0.01)
        return signals


@register_strategy("fees_slippage")
class FeesSlippageSentinel(_AuditSentinelBase):
    def __init__(self):
        super().__init__(name="fees_slippage")

    @property
    def default_params(self) -> dict[str, Any]:
        params = super().default_params
        params["direction"] = "long_short"
        return params

    @property
    def parameter_specs(self) -> dict[str, ParameterSpec]:
        return super().parameter_specs

    def generate_signals(self, df: pd.DataFrame, indicators: dict[str, Any], params: dict[str, Any]) -> pd.Series:
        direction = str(params.get("direction", "long_short"))
        signals = pd.Series(0.0, index=df.index, dtype=np.float64, name="signals")
        warmup = max(0, int(params.get("warmup", 0)))
        side = 1.0
        for idx in range(warmup, len(signals), 2):
            if direction == "long_only":
                signals.iloc[idx] = 1.0
            elif direction == "short_only":
                signals.iloc[idx] = -1.0
            else:
                signals.iloc[idx] = side
                side *= -1.0
        return signals


__all__ = [
    "AlwaysLongSentinel",
    "FeesSlippageSentinel",
    "NeverTradeSentinel",
    "StopNearSentinel",
    "TakeProfitNearSentinel",
    "make_sentinel_ohlcv",
]

