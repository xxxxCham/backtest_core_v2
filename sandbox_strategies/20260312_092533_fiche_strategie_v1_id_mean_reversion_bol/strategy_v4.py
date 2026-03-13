from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="mean_reversion_bollinger_rsi_adx_filter")

    @property
    def required_indicators(self) -> List[str]:
        return ["bollinger", "rsi", "adx", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "adx_period": 14,
            "atr_period": 14,
            "bollinger_period": 20,
            "bollinger_std_dev": 2,
            "leverage": 1,
            "rsi_period": 14,
            "stop_atr_mult": 1.0,
            "tp_atr_mult": 5.5,
            "warmup": 20,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "rsi_period": ParameterSpec(
                name="rsi_period", min_val=5, max_val=50, default=14, param_type="int", step=1
            ),
            "bollinger_period": ParameterSpec(
                name="bollinger_period", min_val=10, max_val=30, default=20, param_type="int", step=1
            ),
            "bollinger_std_dev": ParameterSpec(
                name="bollinger_std_dev", min_val=1.5, max_val=3.0, default=2.0, param_type="float", step=0.1
            ),
            "adx_period": ParameterSpec(
                name="adx_period", min_val=10, max_val=30, default=14, param_type="int", step=1
            ),
            "atr_period": ParameterSpec(
                name="atr_period", min_val=5, max_val=30, default=14, param_type="int", step=1
            ),
            "stop_atr_mult": ParameterSpec(
                name="stop_atr_mult", min_val=0.5, max_val=2.0, default=1.0, param_type="float", step=0.1
            ),
            "tp_atr_mult": ParameterSpec(
                name="tp_atr_mult", min_val=2.0, max_val=10.0, default=5.5, param_type="float", step=0.1
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

        # helper to detect crossings between two arrays
        def cross_any(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return ((x > y) & (prev_x <= prev_y)) | ((x < y) & (prev_x >= prev_y))

        # Extract indicator arrays
        close = df["close"].values
        bb = indicators['bollinger']
        lower = np.nan_to_num(bb["lower"])
        middle = np.nan_to_num(bb["middle"])
        upper = np.nan_to_num(bb["upper"])
        rsi = np.nan_to_num(indicators['rsi'])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        atr = np.nan_to_num(indicators['atr'])

        # Entry conditions
        long_mask = (close < lower) & (rsi < 30) & (adx_val < 25)
        short_mask = (close > upper) & (rsi > 70) & (adx_val < 25)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        # use cross_any for close vs middle
        exit_mask = cross_any(close, middle)

        # RSI crossing 50
        rsi_cross_up = (rsi > 50) & (np.roll(rsi, 1) <= 50)
        rsi_cross_down = (rsi < 50) & (np.roll(rsi, 1) >= 50)
        exit_mask = exit_mask | rsi_cross_up | rsi_cross_down

        signals[exit_mask] = 0.0

        # Apply warm‑up
        signals.iloc[:warmup] = 0.0

        # ATR based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 1.0)
        tp_atr_mult = params.get("tp_atr_mult", 5.5)

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]

        return signals