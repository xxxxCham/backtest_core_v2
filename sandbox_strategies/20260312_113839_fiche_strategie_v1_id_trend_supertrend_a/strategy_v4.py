from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_supertrend_adx_relaxed')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'adx_period': 10,
            'leverage': 1,
            'stop_atr_mult': 2.0,
            'supertrend_atr_period': 13,
            'supertrend_multiplier': 3.5,
            'tp_atr_mult': 3.0,
            'warmup': 20
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
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
                max_val=5.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=10,
                max_val=100,
                default=20,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=20,
                default=10,
                param_type='int',
                step=1,
            ),
            'supertrend_atr_period': ParameterSpec(
                name='supertrend_atr_period',
                min_val=5,
                max_val=20,
                default=13,
                param_type='int',
                step=1,
            ),
            'supertrend_multiplier': ParameterSpec(
                name='supertrend_multiplier',
                min_val=1.0,
                max_val=5.0,
                default=3.5,
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
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # unwrap indicators
        close = df["close"].values
        supertrend_val = np.nan_to_num(indicators['supertrend']["supertrend"]).astype(float)
        direction = np.nan_to_num(indicators['supertrend']["direction"]).astype(float)
        adx_val = np.nan_to_num(indicators['adx']["adx"]).astype(float)
        atr = np.nan_to_num(indicators['atr']).astype(float)

        # helper cross functions
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_st = np.roll(supertrend_val, 1)
        prev_st[0] = np.nan
        cross_up = (close > supertrend_val) & (prev_close <= prev_st)
        cross_down = (close < supertrend_val) & (prev_close >= prev_st)

        # entry conditions
        long_entry = cross_up & (direction == 1) & (adx_val > 20)
        short_entry = cross_down & (direction == -1) & (adx_val > 20)

        # exit conditions
        prev_dir = np.roll(direction, 1).astype(float)
        prev_dir[0] = np.nan
        direction_change = (direction != prev_dir) & (~np.isnan(prev_dir))
        exit_long = direction_change | (adx_val < 15) | cross_down
        exit_short = direction_change | (adx_val < 15) | cross_up

        # apply masks
        signals[long_entry] = 1.0
        signals[short_entry] = -1.0
        signals[exit_long] = 0.0
        signals[exit_short] = 0.0

        # warmup period
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[long_entry, "bb_stop_long"] = close[long_entry] - stop_atr_mult * atr[long_entry]
        df.loc[long_entry, "bb_tp_long"] = close[long_entry] + tp_atr_mult * atr[long_entry]
        df.loc[short_entry, "bb_stop_short"] = close[short_entry] + stop_atr_mult * atr[short_entry]
        df.loc[short_entry, "bb_tp_short"] = close[short_entry] - tp_atr_mult * atr[short_entry]

        return signals