from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='pivot_adx_atr_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['pivot_points', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'atr_period': 14,
         'leverage': 1,
         'stop_atr_mult': 1.0,
         'tp_atr_mult': 2.0,
         'warmup': 20}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=30,
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
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.0,
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

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        # boolean masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # warmup
        signals.iloc[:warmup] = 0.0

        # extract indicator arrays
        close = df["close"].values
        r1 = np.nan_to_num(indicators['pivot_points']["r1"])
        s1 = np.nan_to_num(indicators['pivot_points']["s1"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        atr = np.nan_to_num(indicators['atr'])

        # helper cross functions
        prev_close = np.roll(close, 1)
        prev_r1 = np.roll(r1, 1)
        prev_s1 = np.roll(s1, 1)
        prev_close[0] = np.nan
        prev_r1[0] = np.nan
        prev_s1[0] = np.nan

        cross_up_r1 = (close > r1) & (prev_close <= prev_r1)
        cross_down_s1 = (close < s1) & (prev_close >= prev_s1)

        # entry conditions
        adx_entry = adx_val > params.get("adx_entry_threshold", 25)
        long_mask = cross_up_r1 & adx_entry
        short_mask = cross_down_s1 & adx_entry

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # exit conditions
        cross_down_r1 = (close < r1) & (prev_close >= prev_r1)
        cross_up_s1 = (close > s1) & (prev_close <= prev_s1)
        adx_exit = adx_val < params.get("adx_exit_threshold", 20)

        exit_long_mask = cross_down_r1 | adx_exit
        exit_short_mask = cross_up_s1 | adx_exit

        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # compute SL/TP on entry bars
        stop_mult = params.get("stop_atr_mult", 1.0)
        tp_mult = params.get("tp_atr_mult", 2.0)

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_mult * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_mult * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
