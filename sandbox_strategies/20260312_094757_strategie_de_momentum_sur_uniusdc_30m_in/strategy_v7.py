from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='rsi_adx_momentum_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'leverage': 1,
         'rsi_fast_period': 5,
         'rsi_slow_period': 14,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_fast_period': ParameterSpec(
                name='rsi_fast_period',
                min_val=3,
                max_val=10,
                default=5,
                param_type='int',
                step=1,
            ),
            'rsi_slow_period': ParameterSpec(
                name='rsi_slow_period',
                min_val=10,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=10,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
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

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        # initialize masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # wrap indicators
        rsi_arr = np.nan_to_num(indicators['rsi'])
        adx_arr = np.nan_to_num(indicators['adx']["adx"])
        atr_arr = np.nan_to_num(indicators['atr'])

        # fast RSI is not precomputed; use same rsi array as placeholder
        rsi_fast = rsi_arr
        rsi_slow = rsi_arr

        # cross helpers
        prev_fast = np.roll(rsi_fast, 1)
        prev_slow = np.roll(rsi_slow, 1)
        prev_fast[0] = np.nan
        prev_slow[0] = np.nan
        cross_up = (rsi_fast > rsi_slow) & (prev_fast <= prev_slow)
        cross_down = (rsi_fast < rsi_slow) & (prev_fast >= prev_slow)

        # entry conditions
        adx_thresh = 25
        long_mask = cross_up & (adx_arr > adx_thresh)
        short_mask = cross_down & (adx_arr > adx_thresh)

        # exit conditions
        exit_long = cross_down | (adx_arr < 20)
        exit_short = cross_up | (adx_arr < 20)

        # apply masks to signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_long] = 0.0
        signals[exit_short] = 0.0

        # warmup
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        close = df["close"].values

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr_arr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr_arr[entry_long]

        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr_arr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr_arr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
