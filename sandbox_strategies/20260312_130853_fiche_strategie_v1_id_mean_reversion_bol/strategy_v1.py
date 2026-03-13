from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="mean_reversion_bollinger_rsi")

    @property
    def required_indicators(self) -> List[str]:
        return ["bollinger", "rsi", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "leverage": 1,
            "rsi_overbought": 65,
            "rsi_oversold": 30,
            "rsi_period": 18,
            "stop_atr_mult": 2.25,
            "tp_atr_mult": 2.5,
            "warmup": 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "rsi_period": ParameterSpec(
                name="rsi_period",
                min_val=5,
                max_val=50,
                default=18,
                param_type="int",
                step=1,
            ),
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
                min_val=1.0,
                max_val=5.0,
                default=2.5,
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
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        bb = indicators['bollinger']
        lower = np.nan_to_num(bb["lower"])
        middle = np.nan_to_num(bb["middle"])
        upper = np.nan_to_num(bb["upper"])

        # Entry conditions
        long_mask = (close < lower) & (rsi < params["rsi_oversold"])
        short_mask = (close > upper) & (rsi > params["rsi_overbought"])

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Helper to detect a cross between two series or a series and a constant
        def cross_any(x: np.ndarray, y: np.ndarray | float) -> np.ndarray:
            if np.isscalar(y):
                y_arr = np.full_like(x, y)
            else:
                y_arr = y
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y_arr, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return ((x > y_arr) & (prev_x <= prev_y)) | ((x < y_arr) & (prev_x >= prev_y))

        # Exit conditions: cross close with middle band or rsi with 50
        exit_mask = cross_any(close, middle) | cross_any(rsi, 50.0)
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = signals == 1.0
        entry_short_mask = signals == -1.0

        df.loc[entry_long_mask, "bb_stop_long"] = (
            close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
        )
        df.loc[entry_long_mask, "bb_tp_long"] = (
            close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]
        )

        df.loc[entry_short_mask, "bb_stop_short"] = (
            close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
        )
        df.loc[entry_short_mask, "bb_tp_short"] = (
            close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        )

        return signals