from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='vwap_volume_adx_breakout')

    @property
    def required_indicators(self) -> List[str]:
        # ATR is required for risk management
        return ['vwap', 'volume_oscillator', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'adx_period': 14,
            'atr_period': 14,
            'leverage': 1,
            'stop_atr_mult': 1.5,
            'tp_atr_mult': 3.0,
            'volume_osc_long_period': 20,
            'volume_osc_short_period': 5,
            'vwap_period': 20,
            'warmup': 20,
            # Optional thresholds (defaults are provided in generate_signals)
            'adx_threshold': 25,
            'adx_exit_threshold': 20,
        }

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

        # Extract indicator arrays
        close_arr = df["close"].values
        vwap_arr = np.nan_to_num(indicators['vwap'])
        volume_osc_arr = np.nan_to_num(indicators['volume_oscillator'])
        atr_arr = np.nan_to_num(indicators['atr'])
        adx_arr = np.nan_to_num(indicators['adx']["adx"])

        # Long and short entry masks
        adx_threshold = params.get("adx_threshold", 25)
        long_mask = (
            (close_arr > vwap_arr)
            & (volume_osc_arr > 0)
            & (adx_arr > adx_threshold)
        )
        short_mask = (
            (close_arr < vwap_arr)
            & (volume_osc_arr < 0)
            & (adx_arr > adx_threshold)
        )

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Cross detection helper
        prev_close = np.roll(close_arr, 1)
        prev_vwap = np.roll(vwap_arr, 1)
        prev_close[0] = np.nan
        prev_vwap[0] = np.nan
        cross_up = (close_arr > vwap_arr) & (prev_close <= prev_vwap)
        cross_down = (close_arr < vwap_arr) & (prev_close >= prev_vwap)
        cross_any = cross_up | cross_down

        # Exit condition: cross or weak trend
        adx_exit_threshold = params.get("adx_exit_threshold", 20)
        exit_condition = cross_any | (adx_arr < adx_exit_threshold)
        exit_mask = exit_condition & (~(long_mask | short_mask))
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR-based SL/TP for long entries
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)
        df.loc[long_mask, "bb_stop_long"] = (
            close_arr[long_mask] - stop_atr_mult * atr_arr[long_mask]
        )
        df.loc[long_mask, "bb_tp_long"] = (
            close_arr[long_mask] + tp_atr_mult * atr_arr[long_mask]
        )

        # ATR-based SL/TP for short entries
        df.loc[short_mask, "bb_stop_short"] = (
            close_arr[short_mask] + stop_atr_mult * atr_arr[short_mask]
        )
        df.loc[short_mask, "bb_tp_short"] = (
            close_arr[short_mask] - tp_atr_mult * atr_arr[short_mask]
        )

        return signals