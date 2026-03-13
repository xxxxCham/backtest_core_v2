from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="trend_supertrend_v2")

    @property
    def required_indicators(self) -> List[str]:
        return ["supertrend", "adx", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "adx_period": 16,
            "atr_period": 14,
            "leverage": 1,
            "stop_atr_mult": 2.75,
            "supertrend_atr_period": 10,
            "supertrend_multiplier": 3.5,
            "tp_atr_mult": 5.0,
            "warmup": 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "supertrend_atr_period": ParameterSpec(
                name="supertrend_atr_period",
                min_val=5,
                max_val=20,
                default=10,
                param_type="int",
                step=1,
            ),
            "supertrend_multiplier": ParameterSpec(
                name="supertrend_multiplier",
                min_val=1.0,
                max_val=5.0,
                default=3.5,
                param_type="float",
                step=0.1,
            ),
            "adx_period": ParameterSpec(
                name="adx_period",
                min_val=10,
                max_val=30,
                default=16,
                param_type="int",
                step=1,
            ),
            "atr_period": ParameterSpec(
                name="atr_period",
                min_val=5,
                max_val=20,
                default=14,
                param_type="int",
                step=1,
            ),
            "stop_atr_mult": ParameterSpec(
                name="stop_atr_mult",
                min_val=0.5,
                max_val=4.0,
                default=2.75,
                param_type="float",
                step=0.1,
            ),
            "tp_atr_mult": ParameterSpec(
                name="tp_atr_mult",
                min_val=1.0,
                max_val=10.0,
                default=5.0,
                param_type="float",
                step=0.1,
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

        # unwrap indicators – keep NaNs as float
        st_dir = indicators['supertrend']["direction"].astype(float)
        adx_val = indicators['adx']["adx"].astype(float)
        atr_val = indicators['atr'].astype(float)
        close = df["close"].values

        # entry conditions
        long_mask = (st_dir == 1) & (adx_val > 25)
        short_mask = (st_dir == -1) & (adx_val > 25)

        # exit conditions – detect direction change
        prev_dir = np.roll(st_dir, 1).astype(float)
        prev_dir[0] = np.nan
        dir_change = (st_dir != prev_dir) & ~np.isnan(prev_dir)
        exit_mask = dir_change | (adx_val < 20)

        # warmup protection
        signals.iloc[:warmup] = 0.0

        # apply exit signals
        signals[exit_mask] = 0.0
        # apply entry signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 2.75)
        tp_atr_mult = params.get("tp_atr_mult", 5.0)

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr_val[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr_val[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr_val[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr_val[short_mask]

        signals.iloc[:warmup] = 0.0
        return signals