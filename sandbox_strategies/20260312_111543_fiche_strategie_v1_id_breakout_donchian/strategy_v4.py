from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="supertrend_adx_trend_following")

    @property
    def required_indicators(self) -> List[str]:
        return ["supertrend", "adx", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "adx_period": 14,
            "leverage": 1,
            "stop_atr_mult": 1.5,
            "supertrend_multiplier": 3,
            "supertrend_period": 10,
            "tp_atr_mult": 3.0,
            "warmup": 50,
            # default threshold for ADX used in entry logic
            "adx_threshold": 20,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "supertrend_period": ParameterSpec(
                name="supertrend_period",
                min_val=5,
                max_val=20,
                default=10,
                param_type="int",
                step=1,
            ),
            "supertrend_multiplier": ParameterSpec(
                name="supertrend_multiplier",
                min_val=1,
                max_val=5,
                default=3,
                param_type="float",
                step=0.1,
            ),
            "adx_period": ParameterSpec(
                name="adx_period",
                min_val=5,
                max_val=30,
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
                max_val=6.0,
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
            "adx_threshold": ParameterSpec(
                name="adx_threshold",
                min_val=10,
                max_val=30,
                default=20,
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

        # Ensure masks are defined
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        signals.iloc[:warmup] = 0.0

        close = df["close"].values
        atr = np.nan_to_num(indicators['atr'])

        st = indicators['supertrend']
        supertrend = np.nan_to_num(st["supertrend"])
        adx = indicators['adx']
        adx_val = np.nan_to_num(indicators['adx']["adx"])

        # Entry conditions
        threshold = params.get("adx_threshold", 20)
        long_mask = (close > supertrend) & (adx_val > threshold)
        short_mask = (close < supertrend) & (adx_val > threshold)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Risk management: ATR based SL/TP
        df.loc[:, "sl_level"] = np.nan
        df.loc[:, "tp_level"] = np.nan

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        df.loc[entry_long, "sl_level"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
        df.loc[entry_long, "tp_level"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]

        df.loc[entry_short, "sl_level"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
        df.loc[entry_short, "tp_level"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]

        signals.iloc[:warmup] = 0.0
        return signals