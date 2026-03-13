from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='supertrend_adx_ema_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'adx_period': 11,
            'atr_period': 14,
            'ema_period': 20,
            'leverage': 1,
            'stop_atr_mult': 1.5,
            'supertrend_atr_period': 8,
            'supertrend_multiplier': 3.0,
            'tp_atr_mult': 3.0,
            'warmup': 50
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=3,
                default=1,
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
                min_val=2.0,
                max_val=10.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=10,
                max_val=100,
                default=50,
                param_type='int',
                step=1,
            ),
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=10,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=30,
                default=11,
                param_type='int',
                step=1,
            ),
            'supertrend_atr_period': ParameterSpec(
                name='supertrend_atr_period',
                min_val=5,
                max_val=20,
                default=8,
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
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=10,
                max_val=20,
                default=14,
                param_type='int',
                step=1,
            ),
        }

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        n = len(df)
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        warmup = int(params.get('warmup', 50))

        # Wrap indicator arrays
        close = df["close"].values
        # Ensure direction is float to allow NaN assignment
        direction = np.array(indicators['supertrend']["direction"], dtype=float)
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        ema_val = np.nan_to_num(indicators['ema'])
        atr_val = np.nan_to_num(indicators['atr'])

        # Cross detection between close and ema
        prev_close = np.roll(close, 1)
        prev_ema = np.roll(ema_val, 1)
        prev_close[0] = np.nan
        prev_ema[0] = np.nan
        cross_up = (close > ema_val) & (prev_close <= prev_ema)
        cross_down = (close < ema_val) & (prev_close >= prev_ema)
        cross_any = cross_up | cross_down

        # Supertrend direction change
        prev_dir = np.roll(direction, 1)
        prev_dir[0] = np.nan
        dir_change = (direction != prev_dir)

        # Exit conditions
        exit_mask = cross_any | dir_change | (adx_val < 20)

        # Entry conditions
        long_mask = (direction == 1) & (adx_val > 25) & (close > ema_val)
        short_mask = (direction == -1) & (adx_val > 25) & (close < ema_val)

        # Apply signals
        signals[exit_mask] = 0.0
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Prepare SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR-based SL/TP for long entries
        stop_mult = params.get("stop_atr_mult", 1.5)
        tp_mult = params.get("tp_atr_mult", 3.0)
        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_mult * atr_val[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_mult * atr_val[long_mask]

        # ATR-based SL/TP for short entries
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_mult * atr_val[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_mult * atr_val[short_mask]

        signals.iloc[:warmup] = 0.0
        return signals