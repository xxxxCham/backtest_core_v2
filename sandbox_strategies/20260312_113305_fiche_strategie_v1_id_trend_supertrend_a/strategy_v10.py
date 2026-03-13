from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="trend_supertrend_ema_filter")

    @property
    def required_indicators(self) -> List[str]:
        return ["supertrend", "adx", "ema", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {"leverage": 1, "stop_atr_mult": 2.25, "tp_atr_mult": 5.0, "warmup": 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "stop_atr_mult": ParameterSpec(
                name="stop_atr_mult",
                min_val=0.5,
                max_val=4.0,
                default=2.25,
                param_type="float",
                step=0.1,
            ),
            "tp_atr_mult": ParameterSpec(
                name="tp_atr_mult",
                min_val=2.0,
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

        # Extract indicator arrays
        close = df["close"].values
        ema = np.nan_to_num(indicators['ema'])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        direction = np.nan_to_num(indicators['supertrend']["direction"])
        atr = np.nan_to_num(indicators['atr'])

        # Entry conditions
        long_mask = (direction == 1) & (adx_val > 35) & (close > ema)
        short_mask = (direction == -1) & (adx_val > 35) & (close < ema)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        prev_dir = np.roll(direction, 1).astype(float)
        prev_dir[0] = np.nan
        dir_change = (direction != prev_dir) & (~np.isnan(prev_dir))

        adx_lt_20 = adx_val < 20
        cross_down = close < ema
        cross_up = close > ema

        exit_long = (dir_change & (prev_dir == 1)) | adx_lt_20 | cross_down
        exit_short = (dir_change & (prev_dir == -1)) | adx_lt_20 | cross_up

        signals[(exit_long | exit_short)] = 0.0

        # ATR-based SL/TP levels on entry bars
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 2.25))
        tp_atr_mult = float(params.get("tp_atr_mult", 5.0))

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]

        signals.iloc[:warmup] = 0.0
        return signals