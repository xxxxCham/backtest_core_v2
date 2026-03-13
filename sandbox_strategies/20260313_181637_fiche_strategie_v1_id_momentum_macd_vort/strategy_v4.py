from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='macd_vortex_adx_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'vortex', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'leverage': 1,
            'stop_atr_mult': 2.0,
            'tp_atr_mult': 3.0,
            'warmup': 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'macd_fast_period': ParameterSpec(
                name='macd_fast_period',
                min_val=5,
                max_val=30,
                default=12,
                param_type='int',
                step=1,
            ),
            'macd_slow_period': ParameterSpec(
                name='macd_slow_period',
                min_val=10,
                max_val=40,
                default=26,
                param_type='int',
                step=1,
            ),
            'macd_signal_period': ParameterSpec(
                name='macd_signal_period',
                min_val=3,
                max_val=15,
                default=9,
                param_type='int',
                step=1,
            ),
            'vortex_period': ParameterSpec(
                name='vortex_period',
                min_val=5,
                max_val=20,
                default=14,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=20,
                default=14,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=6.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=1,
                param_type='int',
                step=1,
            ),
        }

    def generate_signals(
        self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]
    ) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Masks for long/short entries
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        signals.iloc[:warmup] = 0.0

        # MACD
        macd_dict = indicators['macd']
        macd_line = np.nan_to_num(macd_dict["macd"])
        signal_line = np.nan_to_num(macd_dict["signal"])

        # Vortex
        vip = np.nan_to_num(indicators['vortex']["vi_plus"])
        vim = np.nan_to_num(indicators['vortex']["vi_minus"])

        # ADX
        adx_val = np.nan_to_num(indicators['adx']["adx"])

        # ATR
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Previous values for cross detection
        prev_macd_line = np.roll(macd_line, 1)
        prev_macd_line[0] = np.nan
        prev_macd_signal = np.roll(signal_line, 1)
        prev_macd_signal[0] = np.nan

        cross_up = (macd_line > signal_line) & (prev_macd_line <= prev_macd_signal)
        cross_down = (macd_line < signal_line) & (prev_macd_line >= prev_macd_signal)

        adx_gt_25 = adx_val > 25
        adx_lt_20 = adx_val < 20

        long_mask = cross_up & (vip > vim) & adx_gt_25
        short_mask = cross_down & (vim > vip) & adx_gt_25

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        exit_long = (signals == 1.0) & (cross_down | adx_lt_20)
        exit_short = (signals == -1.0) & (cross_up | adx_lt_20)
        exit_mask = exit_long | exit_short
        signals[exit_mask] = 0.0

        # Risk management columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]

        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]

        signals.iloc[:warmup] = 0.0
        return signals