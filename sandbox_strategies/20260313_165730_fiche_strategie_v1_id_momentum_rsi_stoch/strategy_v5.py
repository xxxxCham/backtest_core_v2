from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="momentum_rsi_stochastic_ema_atr")

    @property
    def required_indicators(self) -> List[str]:
        return ["rsi", "stochastic", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "leverage": 1,
            "rsi_overbought": 80,
            "rsi_oversold": 20,
            "rsi_period": 7,
            "stop_atr_mult": 1.3,
            "tp_atr_mult": 2.8,
            "warmup": 50,
            "ema_short_period": 20,
            "ema_long_period": 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "rsi_period": ParameterSpec(
                name="rsi_period",
                min_val=5,
                max_val=20,
                default=7,
                param_type="int",
                step=1,
            ),
            "rsi_oversold": ParameterSpec(
                name="rsi_oversold",
                min_val=10,
                max_val=40,
                default=20,
                param_type="int",
                step=1,
            ),
            "rsi_overbought": ParameterSpec(
                name="rsi_overbought",
                min_val=60,
                max_val=90,
                default=80,
                param_type="int",
                step=1,
            ),
            "stop_atr_mult": ParameterSpec(
                name="stop_atr_mult",
                min_val=0.5,
                max_val=4.0,
                default=1.3,
                param_type="float",
                step=0.1,
            ),
            "tp_atr_mult": ParameterSpec(
                name="tp_atr_mult",
                min_val=2.0,
                max_val=5.0,
                default=2.8,
                param_type="float",
                step=0.1,
            ),
            "warmup": ParameterSpec(
                name="warmup",
                min_val=20,
                max_val=100,
                default=50,
                param_type="int",
                step=1,
            ),
            "ema_short_period": ParameterSpec(
                name="ema_short_period",
                min_val=10,
                max_val=30,
                default=20,
                param_type="int",
                step=1,
            ),
            "ema_long_period": ParameterSpec(
                name="ema_long_period",
                min_val=20,
                max_val=60,
                default=50,
                param_type="int",
                step=1,
            ),
            "leverage": ParameterSpec(
                name="leverage",
                min_val=1,
                max_val=2,
                default=1,
                param_type="int",
                step=1,
            ),
        }

    def generate_signals(
        self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]
    ) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get("warmup", 50))

        # Boolean masks for long and short signals
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Ensure initial signals are zero
        signals.iloc[:warmup] = 0.0

        # Retrieve indicator arrays and replace NaNs
        rsi = np.nan_to_num(indicators['rsi'])
        stoch_k = np.nan_to_num(indicators['stochastic']["stoch_k"])
        stoch_d = np.nan_to_num(indicators['stochastic']["stoch_d"])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Compute short and long EMAs directly from close prices
        ema_short = (
            df["close"]
            .ewm(span=params["ema_short_period"], adjust=False)
            .mean()
            .values
        )
        ema_long = (
            df["close"]
            .ewm(span=params["ema_long_period"], adjust=False)
            .mean()
            .values
        )

        # Entry conditions
        long_condition = (
            (rsi < params["rsi_oversold"])
            & (stoch_k < 20)
            & (stoch_d < 20)
            & (ema_short > ema_long)
        )
        short_condition = (
            (rsi > params["rsi_overbought"])
            & (stoch_k > 80)
            & (stoch_d > 80)
            & (ema_short < ema_long)
        )

        long_mask = long_condition
        short_mask = short_condition

        # Assign signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Prepare columns for stop and take‑profit
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        df.loc[long_mask, "bb_stop_long"] = (
            close[long_mask] - params["stop_atr_mult"] * atr[long_mask]
        )
        df.loc[long_mask, "bb_tp_long"] = (
            close[long_mask] + params["tp_atr_mult"] * atr[long_mask]
        )
        df.loc[short_mask, "bb_stop_short"] = (
            close[short_mask] + params["stop_atr_mult"] * atr[short_mask]
        )
        df.loc[short_mask, "bb_tp_short"] = (
            close[short_mask] - params["tp_atr_mult"] * atr[short_mask]
        )

        # Ensure warmup period remains zero
        signals.iloc[:warmup] = 0.0
        return signals