from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='vwap_volume_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['vwap', 'volume_oscillator', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 3.0,
         'volume_osc_long_period': 20,
         'volume_osc_short_period': 5,
         'vwap_period': 20,
         'warmup': 20}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'vwap_period': ParameterSpec(
                name='vwap_period',
                min_val=5,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'volume_osc_short_period': ParameterSpec(
                name='volume_osc_short_period',
                min_val=3,
                max_val=10,
                default=5,
                param_type='int',
                step=1,
            ),
            'volume_osc_long_period': ParameterSpec(
                name='volume_osc_long_period',
                min_val=10,
                max_val=30,
                default=20,
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
            'warmup': ParameterSpec(
                name='warmup',
                min_val=10,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Wrap indicator arrays
        vwap_arr = np.nan_to_num(indicators['vwap'])
        vol_osc_arr = np.nan_to_num(indicators['volume_oscillator'])
        atr_arr = np.nan_to_num(indicators['atr'])
        close_arr = df["close"].values

        # Helper for cross_any
        def cross_any(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return ((x > y) & (prev_x <= prev_y)) | ((x < y) & (prev_x >= prev_y))

        # Entry logic
        long_mask = (close_arr > vwap_arr) & (vol_osc_arr > 0) & (atr_arr > 0.01 * close_arr)
        short_mask = (close_arr < vwap_arr) & (vol_osc_arr < 0) & (atr_arr > 0.01 * close_arr)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit logic
        exit_cross_close_vwap = cross_any(close_arr, vwap_arr)
        exit_cross_vol_osc_zero = cross_any(vol_osc_arr, np.zeros_like(vol_osc_arr))
        exit_condition = exit_cross_close_vwap | exit_cross_vol_osc_zero

        exit_long_mask = (signals == 1.0) & exit_condition
        exit_short_mask = (signals == -1.0) & exit_condition
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Warmup protection
        signals.iloc[:50] = 0.0

        # SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        # Long entries
        entry_long_mask = long_mask
        df.loc[entry_long_mask, "bb_stop_long"] = close_arr[entry_long_mask] - stop_atr_mult * atr_arr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close_arr[entry_long_mask] + tp_atr_mult * atr_arr[entry_long_mask]

        # Short entries
        entry_short_mask = short_mask
        df.loc[entry_short_mask, "bb_stop_short"] = close_arr[entry_short_mask] + stop_atr_mult * atr_arr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close_arr[entry_short_mask] - tp_atr_mult * atr_arr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
