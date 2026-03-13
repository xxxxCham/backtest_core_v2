from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="momentum_macd_vortex_atr")

    @property
    def required_indicators(self) -> List[str]:
        return ["macd", "vortex", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "atr_period": 14,
            "leverage": 1,
            "macd_fast_period": 12,
            "macd_signal_period": 9,
            "macd_slow_period": 26,
            "stop_atr_mult": 2.0,
            "tp_atr_mult": 3.0,
            "vortex_period": 14,
            "warmup": 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "macd_fast_period": ParameterSpec(
                name="macd_fast_period",
                min_val=5,
                max_val=30,
                default=12,
                param_type="int",
                step=1,
            ),
            "macd_slow_period": ParameterSpec(
                name="macd_slow_period",
                min_val=10,
                max_val=40,
                default=26,
                param_type="int",
                step=1,
            ),
            "macd_signal_period": ParameterSpec(
                name="macd_signal_period",
                min_val=3,
                max_val=15,
                default=9,
                param_type="int",
                step=1,
            ),
            "vortex_period": ParameterSpec(
                name="vortex_period",
                min_val=5,
                max_val=20,
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
                default=2.0,
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
            "warmup": ParameterSpec(
                name="warmup",
                min_val=10,
                max_val=200,
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
        }

    def generate_signals(
        self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]
    ) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get("warmup", 50))

        # Initialize masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Retrieve indicator arrays
        macd = np.nan_to_num(indicators['macd']["macd"])
        signal = np.nan_to_num(indicators['macd']["signal"])
        vi_plus = np.nan_to_num(indicators['vortex']["vi_plus"])
        vi_minus = np.nan_to_num(indicators['vortex']["vi_minus"])
        atr = np.nan_to_num(indicators['atr'])

        # Detect MACD crossovers
        prev_macd = np.roll(macd, 1)
        prev_signal = np.roll(signal, 1)
        prev_macd[0] = np.nan
        prev_signal[0] = np.nan
        cross_up = (macd > signal) & (prev_macd <= prev_signal)
        cross_down = (macd < signal) & (prev_macd >= prev_signal)

        # Long entry: MACD cross up AND vortex indicates upward bias
        long_mask = cross_up & (vi_plus > vi_minus)

        # Short entry: MACD cross down AND vortex indicates downward bias
        short_mask = cross_down & (vi_minus > vi_plus)

        # Assign signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup period: no signals
        signals.iloc[:warmup] = 0.0

        # Prepare ATR-based stop/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        close = df["close"].values
        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        # Long ATR levels
        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]

        # Short ATR levels
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]

        return signals