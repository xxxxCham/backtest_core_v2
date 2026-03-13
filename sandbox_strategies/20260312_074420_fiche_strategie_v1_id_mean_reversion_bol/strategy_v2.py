from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="mean_reversion_bollinger_rsi_tight")

    @property
    def required_indicators(self) -> List[str]:
        return ["bollinger", "rsi", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "leverage": 1,
            "rsi_overbought": 80,
            "rsi_oversold": 20,
            "rsi_period": 18,
            "stop_atr_mult": 2.25,
            "tp_atr_mult": 4.0,
            "warmup": 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "rsi_period": ParameterSpec(
                name="rsi_period", min_val=5, max_val=50, default=18, param_type="int", step=1
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
                max_val=6.0,
                default=4.0,
                param_type="float",
                step=0.1,
            ),
            "rsi_oversold": ParameterSpec(
                name="rsi_oversold",
                min_val=10,
                max_val=35,
                default=20,
                param_type="int",
                step=1,
            ),
            "rsi_overbought": ParameterSpec(
                name="rsi_overbought",
                min_val=65,
                max_val=90,
                default=80,
                param_type="int",
                step=1,
            ),
            "warmup": ParameterSpec(
                name="warmup", min_val=20, max_val=100, default=50, param_type="int", step=1
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

        # ---- Indicator values ----
        close = df["close"].values
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        bb = indicators['bollinger']
        lower = np.nan_to_num(bb["lower"])
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])

        # ---- Entry conditions ----
        long_mask = (close < lower) & (rsi < params["rsi_oversold"])
        short_mask = (close > upper) & (rsi > params["rsi_overbought"])

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR based SL/TP levels for entries
        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - (
            params["stop_atr_mult"] * atr[long_mask]
        )
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + (
            params["tp_atr_mult"] * atr[long_mask]
        )
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + (
            params["stop_atr_mult"] * atr[short_mask]
        )
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - (
            params["tp_atr_mult"] * atr[short_mask]
        )

        # Helper to detect any cross between two series or a series and a constant
        def cross_any(x: np.ndarray, y: np.ndarray | float) -> np.ndarray:
            if np.isscalar(y):
                y_arr = np.full_like(x, y, dtype=float)
            else:
                y_arr = np.nan_to_num(y)
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y_arr, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            cross_up = (x > y_arr) & (prev_x <= prev_y)
            cross_down = (x < y_arr) & (prev_x >= prev_y)
            return cross_up | cross_down

        # ---- Exit conditions ----
        exit_mask_long = (
            (signals == 1.0) & (cross_any(close, middle) | cross_any(rsi, 50))
        )
        exit_mask_short = (
            (signals == -1.0) & (cross_any(close, middle) | cross_any(rsi, 50))
        )

        signals[exit_mask_long] = 0.0
        signals[exit_mask_short] = 0.0

        # Zero out warmup period
        signals.iloc[:warmup] = 0.0
        return signals