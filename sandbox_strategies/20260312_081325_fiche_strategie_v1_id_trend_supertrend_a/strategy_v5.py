from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='supertrend_rsi_adx')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'adx_period': 20,
            'leverage': 1,
            'rsi_period': 14,
            'stop_atr_mult': 1.5,
            'supertrend_atr_period': 17,
            'supertrend_multiplier': 2.0,
            'tp_atr_mult': 4.5,
            'warmup': 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=50,
                default=14,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=10,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
            ),
            'supertrend_atr_period': ParameterSpec(
                name='supertrend_atr_period',
                min_val=10,
                max_val=30,
                default=17,
                param_type='int',
                step=1,
            ),
            'supertrend_multiplier': ParameterSpec(
                name='supertrend_multiplier',
                min_val=1.0,
                max_val=3.0,
                default=2.0,
                param_type='float',
                step=0.1,
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
                max_val=10.0,
                default=4.5,
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
        n = len(df)
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        # Warm‑up period
        warmup = int(params.get('warmup', 50))

        # Wrap indicator arrays as float to allow NaN handling
        st_dir = np.array(indicators['supertrend']["direction"], dtype=float)
        adx_val = np.array(indicators['adx']["adx"], dtype=float)
        rsi_val = np.array(indicators['rsi'], dtype=float)
        atr = np.array(indicators['atr'], dtype=float)
        close = df["close"].values

        # Entry logic
        long_mask = (st_dir == 1) & (adx_val > 25) & (rsi_val > 50)
        short_mask = (st_dir == -1) & (adx_val > 25) & (rsi_val < 50)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit logic: direction change or RSI crossing 50
        prev_dir = np.roll(st_dir, 1)
        prev_dir[0] = np.nan
        dir_change = (st_dir != prev_dir) & (~np.isnan(prev_dir))

        prev_rsi = np.roll(rsi_val, 1)
        prev_rsi[0] = np.nan
        rsi_cross_up = (rsi_val > 50) & (prev_rsi <= 50)
        rsi_cross_down = (rsi_val < 50) & (prev_rsi >= 50)
        rsi_cross = rsi_cross_up | rsi_cross_down

        exit_mask = dir_change | rsi_cross
        signals[exit_mask] = 0.0

        # Warm‑up protection
        signals.iloc[:warmup] = 0.0

        # ATR‑based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 4.5)

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]

        signals.iloc[:warmup] = 0.0
        return signals