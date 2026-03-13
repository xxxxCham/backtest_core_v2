from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="trend_supertrend_adx_relaxed")

    @property
    def required_indicators(self) -> List[str]:
        return ["supertrend", "adx", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {"leverage": 1, "stop_atr_mult": 1.5, "tp_atr_mult": 4.5, "warmup": 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "stop_atr_mult": ParameterSpec(
                name="stop_atr_mult",
                min_val=0.5,
                max_val=4.0,
                default=1.5,
                param_type="float",
                step=0.1,
            ),
            "tp_atr_mult": ParameterSpec(
                name="tp_atr_mult",
                min_val=1.0,
                max_val=10.0,
                default=4.5,
                param_type="float",
                step=0.1,
            ),
            "warmup": ParameterSpec(
                name="warmup",
                min_val=10,
                max_val=100,
                default=50,
                param_type="int",
                step=5,
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
        n = len(df)
        warmup = int(params.get("warmup", 50))

        # initialise signals
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        # indicator arrays
        st_dir = np.array(indicators['supertrend']["direction"], dtype=float)
        adx_val = np.array(indicators['adx']["adx"], dtype=float)
        atr_arr = np.array(indicators['atr'], dtype=float)
        close_arr = df["close"].values

        # Entry conditions
        long_mask = (st_dir == 1.0) & (adx_val > 20.0)
        short_mask = (st_dir == -1.0) & (adx_val > 20.0)

        # Exit conditions
        prev_dir = np.roll(st_dir, 1)
        prev_dir[0] = np.nan
        dir_change = (st_dir != prev_dir) & (~np.isnan(prev_dir))
        exit_long_mask = dir_change & (st_dir == -1.0) & (prev_dir == 1.0)
        exit_short_mask = dir_change & (st_dir == 1.0) & (prev_dir == -1.0)
        exit_adx_mask = adx_val < 15.0
        exit_mask = exit_long_mask | exit_short_mask | exit_adx_mask

        # apply exits first
        signals[exit_mask] = 0.0
        # then entries
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # enforce warmup period
        signals.iloc[:warmup] = 0.0

        # risk management columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 4.5))

        # ATR-based SL/TP for long entries
        df.loc[long_mask, "bb_stop_long"] = (
            close_arr[long_mask] - stop_atr_mult * atr_arr[long_mask]
        )
        df.loc[long_mask, "bb_tp_long"] = (
            close_arr[long_mask] + tp_atr_mult * atr_arr[long_mask]
        )

        # ATR-based SL/TP for short entries
        df.loc[short_mask, "bb_stop_short"] = (
            close_arr[short_mask] + stop_atr_mult * atr_arr[short_mask]
        )
        df.loc[short_mask, "bb_tp_short"] = (
            close_arr[short_mask] - tp_atr_mult * atr_arr[short_mask]
        )

        return signals