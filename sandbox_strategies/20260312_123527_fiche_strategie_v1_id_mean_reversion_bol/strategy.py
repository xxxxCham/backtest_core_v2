from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="bollinger_rsi_mean_reversion_with_adx")

    @property
    def required_indicators(self) -> List[str]:
        return ["bollinger", "rsi", "adx", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "leverage": 1,
            "rsi_overbought": 70,
            "rsi_oversold": 30,
            "rsi_period": 14,
            "stop_atr_mult": 2.25,
            "tp_atr_mult": 5.0,
            "warmup": 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "rsi_period": ParameterSpec(
                name="rsi_period",
                min_val=5,
                max_val=50,
                default=14,
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
        n = len(df)
        warmup = int(params.get("warmup", 50))
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        # Indicator arrays
        close = df["close"].values
        bb = indicators['bollinger']
        lower = np.nan_to_num(bb["lower"])
        middle = np.nan_to_num(bb["middle"])
        upper = np.nan_to_num(bb["upper"])
        rsi = np.nan_to_num(indicators['rsi'])
        adx = np.nan_to_num(indicators['adx']["adx"])
        atr = np.nan_to_num(indicators['atr'])

        # Helper for cross detection between two arrays
        def cross_any(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return ((x > y) & (prev_x <= prev_y)) | ((x < y) & (prev_x >= prev_y))

        # Entry conditions
        long_mask = (close < lower) & (rsi < params["rsi_oversold"]) & (adx < 20)
        short_mask = (close > upper) & (rsi > params["rsi_overbought"]) & (adx < 20)

        # Exit conditions
        close_cross_middle = cross_any(close, middle)
        # RSI crossing 50
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        rsi_cross_50 = ((rsi > 50) & (prev_rsi <= 50)) | ((rsi < 50) & (prev_rsi >= 50))
        exit_mask = close_cross_middle | rsi_cross_50 | (adx > 25)

        # Apply signals
        signals[exit_mask] = 0.0
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = long_mask
        entry_short_mask = short_mask

        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - (
            params["stop_atr_mult"] * atr[entry_long_mask]
        )
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + (
            params["tp_atr_mult"] * atr[entry_long_mask]
        )

        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + (
            params["stop_atr_mult"] * atr[entry_short_mask]
        )
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - (
            params["tp_atr_mult"] * atr[entry_short_mask]
        )

        return signals