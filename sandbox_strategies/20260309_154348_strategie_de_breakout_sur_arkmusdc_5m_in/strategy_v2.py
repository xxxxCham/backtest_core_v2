from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='pivot_breakout_atr_adx_arkmusdc_5m')

    @property
    def required_indicators(self) -> List[str]:
        return ['pivot_points', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_exit_threshold': 20,
         'adx_period': 14,
         'adx_threshold': 25,
         'atr_min': 0.0005,
         'atr_period': 14,
         'leverage': 1,
         'stop_atr_mult': 1.0,
         'tp_atr_mult': 2.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=50,
                default=14,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=50,
                default=14,
                param_type='int',
                step=1,
            ),
            'adx_threshold': ParameterSpec(
                name='adx_threshold',
                min_val=10,
                max_val=50,
                default=25,
                param_type='float',
                step=0.1,
            ),
            'adx_exit_threshold': ParameterSpec(
                name='adx_exit_threshold',
                min_val=5,
                max_val=40,
                default=20,
                param_type='float',
                step=0.1,
            ),
            'atr_min': ParameterSpec(
                name='atr_min',
                min_val=0.0001,
                max_val=0.01,
                default=0.0005,
                param_type='float',
                step=0.1,
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
                min_val=0.5,
                max_val=6.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=3,
                default=1,
                param_type='int',
                step=1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=10,
                max_val=200,
                default=50,
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
        # Warmup protection
        warmup = int(params.get("warmup", 50))
        signals.iloc[:warmup] = 0.0

        # Extract indicator arrays with NaN handling
        close = df["close"].values

        pp_dict = indicators['pivot_points']
        pivot = np.nan_to_num(pp_dict["pivot"])
        r1 = np.nan_to_num(pp_dict["r1"])
        s1 = np.nan_to_num(pp_dict["s1"])

        adx_dict = indicators['adx']
        adx_val = np.nan_to_num(adx_dict["adx"])

        atr_arr = np.nan_to_num(indicators['atr'])

        # Parameters
        adx_thr = params.get("adx_threshold", 25)
        adx_exit_thr = params.get("adx_exit_threshold", 20)
        atr_min = params.get("atr_min", 0.0005)
        stop_mult = params.get("stop_atr_mult", 1.0)
        tp_mult = params.get("tp_atr_mult", 2.0)

        # Entry conditions
        long_entry = (close > r1) & (adx_val > adx_thr) & (atr_arr > atr_min)
        short_entry = (close < s1) & (adx_val > adx_thr) & (atr_arr > atr_min)

        # Populate entry masks
        long_mask[long_entry] = True
        short_mask[short_entry] = True

        # Exit conditions: price crossing pivot or ADX dropping below exit threshold
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_pivot = np.roll(pivot, 1)
        prev_pivot[0] = np.nan

        cross_up = (close > pivot) & (prev_close <= prev_pivot)
        cross_down = (close < pivot) & (prev_close >= prev_pivot)
        cross_any = cross_up | cross_down

        exit_mask = cross_any | (adx_val < adx_exit_thr)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Write ATR‑based stop‑loss and take‑profit on entry bars
        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_mult * atr_arr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_mult * atr_arr[long_mask]

        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_mult * atr_arr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_mult * atr_arr[short_mask]

        return signals
        signals.iloc[:warmup] = 0.0
        return signals
