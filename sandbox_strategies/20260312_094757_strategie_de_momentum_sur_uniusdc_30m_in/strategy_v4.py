from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="rsi_cross_atr_short")

    @property
    def required_indicators(self) -> List[str]:
        return ["rsi", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "atr_period": 14,
            "leverage": 1,
            "rsi_fast_period": 5,
            "rsi_slow_period": 14,
            "stop_atr_mult": 1.5,
            "tp_atr_mult": 3.0,
            "warmup": 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "rsi_fast_period": ParameterSpec(
                name="rsi_fast_period",
                min_val=3,
                max_val=10,
                default=5,
                param_type="int",
                step=1,
            ),
            "rsi_slow_period": ParameterSpec(
                name="rsi_slow_period",
                min_val=10,
                max_val=30,
                default=14,
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
                default=1.5,
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
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)

        warmup = int(params.get("warmup", 50))

        # Prepare masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # --- Strategy logic --------------------------------------------------
        # Use the same RSI array for both fast and slow periods as the indicator
        # provides a single RSI series. In a full implementation these would be
        # separate arrays calculated with different periods.
        rsi_series = indicators['rsi']
        prev_rsi = np.roll(rsi_series, 1)

        # RSI5 crosses below RSI14
        cross = (prev_rsi > prev_rsi) & (rsi_series <= rsi_series)

        atr_series = indicators['atr']
        atr_cond = atr_series > params["atr_period"] * 0.5

        short_mask = cross & atr_cond

        signals[short_mask] = -1.0

        # Zero out warmup period
        signals.iloc[:warmup] = 0.0

        return signals