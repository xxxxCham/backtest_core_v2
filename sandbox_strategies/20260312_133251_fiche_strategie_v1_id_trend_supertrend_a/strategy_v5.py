from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="trend_supertrend_bollinger_adx")

    @property
    def required_indicators(self) -> List[str]:
        return ["supertrend", "adx", "bollinger", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {"leverage": 1, "stop_atr_mult": 2.75, "tp_atr_mult": 5.0, "warmup": 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
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

        close = df["close"].values

        # Bollinger bands
        bb = indicators['bollinger']
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        # Supertrend
        st = indicators['supertrend']
        direction = st["direction"].astype(float)  # ensure float to allow NaN

        # ADX
        adx = indicators['adx']
        adx_val = np.nan_to_num(indicators['adx']["adx"])

        # ATR
        atr = np.nan_to_num(indicators['atr'])

        # Entry conditions
        long_mask = (close > upper) & (direction == 1) & (adx_val > 25)
        short_mask = (close < lower) & (direction == -1) & (adx_val > 25)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Detect direction change
        prev_dir = np.roll(direction, 1)
        prev_dir[0] = np.nan
        dir_change = direction != prev_dir

        # Detect middle band cross
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        cross_any_middle = (
            (close > middle) & (prev_close <= middle)
        ) | ((close < middle) & (prev_close >= middle))

        # Exit conditions
        exit_mask = cross_any_middle | (adx_val < 20) | dir_change
        signals[exit_mask] = 0.0

        # Warmup period
        signals.iloc[:warmup] = 0.0

        # Risk management columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 2.75))
        tp_atr_mult = float(params.get("tp_atr_mult", 5.0))

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]

        return signals