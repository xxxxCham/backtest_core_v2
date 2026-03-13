from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="trend_supertrend_adx_ema")

    @property
    def required_indicators(self) -> List[str]:
        return ["supertrend", "adx", "ema", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "adx_threshold": 25,
            "ema_period": 50,
            "leverage": 1,
            "stop_atr_mult": 1.25,
            "tp_atr_mult": 3.0,
            "warmup": 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "ema_period": ParameterSpec(
                name="ema_period",
                min_val=10,
                max_val=200,
                default=50,
                param_type="int",
                step=1,
            ),
            "adx_threshold": ParameterSpec(
                name="adx_threshold",
                min_val=10,
                max_val=30,
                default=25,
                param_type="int",
                step=1,
            ),
            "stop_atr_mult": ParameterSpec(
                name="stop_atr_mult",
                min_val=0.5,
                max_val=4.0,
                default=1.25,
                param_type="float",
                step=0.1,
            ),
            "tp_atr_mult": ParameterSpec(
                name="tp_atr_mult",
                min_val=1.0,
                max_val=5.0,
                default=3.0,
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
        n = len(df)
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        warmup = int(params.get("warmup", 50))

        close = df["close"].values
        # Convert indicator arrays to float to safely handle NaNs
        st_dir = np.array(indicators['supertrend']["direction"], dtype=float)
        adx_val = np.array(indicators['adx']["adx"], dtype=float)
        ema_val = np.array(indicators['ema'], dtype=float)
        atr_val = np.array(indicators['atr'], dtype=float)

        # Entry conditions
        long_cond = (st_dir == 1) & (adx_val > params["adx_threshold"]) & (close > ema_val)
        short_cond = (st_dir == -1) & (adx_val > params["adx_threshold"]) & (close < ema_val)

        # Avoid duplicate consecutive entries
        prev_signals = np.roll(signals.values, 1)
        prev_signals[0] = 0.0
        long_mask = long_cond & (prev_signals != 1.0)
        short_mask = short_cond & (prev_signals != -1.0)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        prev_dir = np.roll(st_dir, 1).astype(float)
        prev_dir[0] = np.nan
        exit_long = (signals == 1.0) & ((st_dir != prev_dir) | (adx_val < 20))
        exit_short = (signals == -1.0) & ((st_dir != prev_dir) | (adx_val < 20))
        signals[exit_long | exit_short] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_mult = params["stop_atr_mult"]
        tp_mult = params["tp_atr_mult"]

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_mult * atr_val[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_mult * atr_val[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_mult * atr_val[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_mult * atr_val[short_mask]

        return signals