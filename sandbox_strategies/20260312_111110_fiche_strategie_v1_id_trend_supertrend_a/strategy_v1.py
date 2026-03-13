from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_supertrend')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'adx_period': 10,
            'atr_period': 14,
            'leverage': 1,
            'stop_atr_mult': 2.25,
            'supertrend_atr_period': 11,
            'supertrend_multiplier': 3.0,
            'tp_atr_mult': 5.5,
            'warmup': 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'supertrend_atr_period': ParameterSpec(
                name='supertrend_atr_period',
                min_val=5,
                max_val=20,
                default=11,
                param_type='int',
                step=1,
            ),
            'supertrend_multiplier': ParameterSpec(
                name='supertrend_multiplier',
                min_val=1.0,
                max_val=5.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=20,
                default=10,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
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
                default=2.25,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=10.0,
                default=5.5,
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
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any],
    ) -> pd.Series:
        n = len(df)
        warmup = int(params.get('warmup', 50))
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        # unpack indicators
        dir_arr = np.nan_to_num(indicators['supertrend']["direction"])
        adx_arr = np.nan_to_num(indicators['adx']["adx"])
        atr_arr = np.nan_to_num(indicators['atr'])
        close_arr = df["close"].values

        # entry conditions
        long_mask = (dir_arr == 1) & (adx_arr > 30)
        short_mask = (dir_arr == -1) & (adx_arr > 30)

        # exit conditions
        prev_dir = np.roll(dir_arr, 1).astype(float)
        prev_dir[0] = np.nan
        direction_change = (dir_arr != prev_dir) & ~np.isnan(prev_dir)
        exit_mask = direction_change | (adx_arr < 20)

        # apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_mult = params.get("stop_atr_mult", 2.25)
        tp_mult = params.get("tp_atr_mult", 5.5)

        df.loc[long_mask, "bb_stop_long"] = close_arr[long_mask] - stop_mult * atr_arr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close_arr[long_mask] + tp_mult * atr_arr[long_mask]

        df.loc[short_mask, "bb_stop_short"] = close_arr[short_mask] + stop_mult * atr_arr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close_arr[short_mask] - tp_mult * atr_arr[short_mask]

        return signals