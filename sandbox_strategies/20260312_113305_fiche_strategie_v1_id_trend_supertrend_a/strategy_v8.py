from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="bollinger_rsi_adx_filter")

    @property
    def required_indicators(self) -> List[str]:
        return ["bollinger", "adx", "rsi", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "adx_period": 18,
            "atr_period": 14,
            "bollinger_period": 20,
            "bollinger_std_dev": 2,
            "leverage": 1,
            "rsi_overbought": 70,
            "rsi_oversold": 30,
            "rsi_period": 14,
            "stop_atr_mult": 2.0,
            "tp_atr_mult": 4.0,
            "warmup": 50,
            "adx_threshold": 25,
            "adx_exit_threshold": 20,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "bollinger_period": ParameterSpec(
                name="bollinger_period",
                min_val=10,
                max_val=30,
                default=20,
                param_type="int",
                step=1,
            ),
            "bollinger_std_dev": ParameterSpec(
                name="bollinger_std_dev",
                min_val=1.5,
                max_val=3.0,
                default=2.0,
                param_type="float",
                step=0.1,
            ),
            "adx_period": ParameterSpec(
                name="adx_period",
                min_val=10,
                max_val=30,
                default=18,
                param_type="int",
                step=1,
            ),
            "rsi_period": ParameterSpec(
                name="rsi_period",
                min_val=5,
                max_val=50,
                default=14,
                param_type="int",
                step=1,
            ),
            "rsi_overbought": ParameterSpec(
                name="rsi_overbought",
                min_val=60,
                max_val=80,
                default=70,
                param_type="int",
                step=1,
            ),
            "rsi_oversold": ParameterSpec(
                name="rsi_oversold",
                min_val=20,
                max_val=40,
                default=30,
                param_type="int",
                step=1,
            ),
            "atr_period": ParameterSpec(
                name="atr_period",
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
                default=2.0,
                param_type="float",
                step=0.1,
            ),
            "tp_atr_mult": ParameterSpec(
                name="tp_atr_mult",
                min_val=2.0,
                max_val=10.0,
                default=4.0,
                param_type="float",
                step=0.1,
            ),
            "warmup": ParameterSpec(
                name="warmup",
                min_val=20,
                max_val=100,
                default=50,
                param_type="int",
                step=1,
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
                max_val=40,
                default=25,
                param_type="int",
                step=1,
            ),
            "adx_exit_threshold": ParameterSpec(
                name="adx_exit_threshold",
                min_val=10,
                max_val=40,
                default=20,
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

        # Boolean masks for entries and exits
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Preserve warmup period
        signals.iloc[:warmup] = 0.0

        close = df["close"].values
        bb = indicators['bollinger']
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        adx_val = np.nan_to_num(indicators['adx']["adx"])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Entry conditions
        long_mask = (
            (close > upper)
            & (adx_val > params["adx_threshold"])
            & (rsi > params["rsi_overbought"])
        )
        short_mask = (
            (close < lower)
            & (adx_val > params["adx_threshold"])
            & (rsi < params["rsi_oversold"])
        )

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        exit_long_mask = (close < middle) | (adx_val < params["adx_exit_threshold"])
        exit_short_mask = (close > middle) | (adx_val < params["adx_exit_threshold"])
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # ATR-based stop‑loss and take‑profit levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        df.loc[long_mask, "bb_stop_long"] = (
            close[long_mask] - params["stop_atr_mult"] * atr[long_mask]
        )
        df.loc[long_mask, "bb_tp_long"] = (
            close[long_mask] + params["tp_atr_mult"] * atr[long_mask]
        )
        df.loc[short_mask, "bb_stop_short"] = (
            close[short_mask] + params["stop_atr_mult"] * atr[short_mask]
        )
        df.loc[short_mask, "bb_tp_short"] = (
            close[short_mask] - params["tp_atr_mult"] * atr[short_mask]
        )

        signals.iloc[:warmup] = 0.0
        return signals