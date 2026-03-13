from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="trend_supertrend_rsi_filter")

    @property
    def required_indicators(self) -> List[str]:
        return ["supertrend", "adx", "rsi", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "leverage": 1,
            "rsi_overbought": 70,
            "rsi_oversold": 30,
            "rsi_period": 14,
            "stop_atr_mult": 1.5,
            "tp_atr_mult": 4.5,
            "warmup": 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "rsi_period": ParameterSpec(
                name="rsi_period", min_val=5, max_val=50, default=14, param_type="int", step=1
            ),
            "rsi_overbought": ParameterSpec(
                name="rsi_overbought", min_val=60, max_val=80, default=70, param_type="int", step=1
            ),
            "rsi_oversold": ParameterSpec(
                name="rsi_oversold", min_val=20, max_val=40, default=30, param_type="int", step=1
            ),
            "stop_atr_mult": ParameterSpec(
                name="stop_atr_mult", min_val=0.5, max_val=4.0, default=1.5, param_type="float", step=0.1
            ),
            "tp_atr_mult": ParameterSpec(
                name="tp_atr_mult", min_val=2.0, max_val=10.0, default=4.5, param_type="float", step=0.1
            ),
            "leverage": ParameterSpec(
                name="leverage", min_val=1, max_val=2, default=1, param_type="int", step=1
            ),
        }

    def generate_signals(
        self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]
    ) -> pd.Series:
        n = len(df)
        warmup = int(params.get("warmup", 50))
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        # Indicator arrays (float to allow NaNs)
        rsi = np.nan_to_num(indicators['rsi'])
        direction = np.nan_to_num(indicators['supertrend']["direction"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        atr = np.nan_to_num(indicators['atr'])

        # Entry masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        long_cond = (direction == 1) & (adx_val > 25) & (rsi < params["rsi_overbought"])
        short_cond = (direction == -1) & (adx_val > 25) & (rsi > params["rsi_oversold"])

        long_mask[long_cond] = True
        short_mask[short_cond] = True

        # Warmup protection
        long_mask[:warmup] = False
        short_mask[:warmup] = False

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        prev_direction = np.roll(direction, 1).astype(float)
        prev_direction[0] = np.nan
        direction_change = (direction != prev_direction) & ~np.isnan(prev_direction)

        prev_adx = np.roll(adx_val, 1).astype(float)
        prev_adx[0] = np.nan
        adx_drop = (adx_val < 20) & ~np.isnan(prev_adx)

        exit_mask = direction_change | adx_drop
        exit_mask[:warmup] = False
        # Ensure exits do not override entries on the same bar
        signals[(exit_mask) & (~long_mask) & (~short_mask)] = 0.0

        # ATR-based SL/TP levels
        close = df["close"].values
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - params["stop_atr_mult"] * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + params["tp_atr_mult"] * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + params["stop_atr_mult"] * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - params["tp_atr_mult"] * atr[short_mask]

        signals.iloc[:warmup] = 0.0
        return signals