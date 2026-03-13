from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_rsi_obv_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'obv', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'atr_period': 14,
            'leverage': 1,
            'rsi_period': 14,
            'stop_atr_mult': 1.5,
            'tp_atr_mult': 3.0,
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
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=50,
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
                max_val=200,
                default=50,
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

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any],
    ) -> pd.Series:
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Initialize signal series
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        # Wrap indicator arrays
        rsi = np.nan_to_num(indicators['rsi'])
        obv = np.nan_to_num(indicators['obv'])
        atr = np.nan_to_num(indicators['atr'])

        # Lagged OBV for cross detection
        obv_prev = np.roll(obv, 1)
        obv_prev[0] = np.nan

        # Helper functions for cross detection
        def _prev(arr: np.ndarray) -> np.ndarray:
            prev = np.roll(arr, 1)
            prev[0] = np.nan
            return prev

        def cross_up(x: np.ndarray, y: Any) -> np.ndarray:
            if np.isscalar(y):
                y_arr = np.full_like(x, y, dtype=float)
                prev_y = np.full_like(x, y, dtype=float)
            else:
                y_arr = y
                prev_y = _prev(y)
            return (x > y_arr) & (_prev(x) <= prev_y)

        def cross_down(x: np.ndarray, y: Any) -> np.ndarray:
            if np.isscalar(y):
                y_arr = np.full_like(x, y, dtype=float)
                prev_y = np.full_like(x, y, dtype=float)
            else:
                y_arr = y
                prev_y = _prev(y)
            return (x < y_arr) & (_prev(x) >= prev_y)

        def cross_any(x: np.ndarray, y: Any) -> np.ndarray:
            return cross_up(x, y) | cross_down(x, y)

        # Entry conditions
        long_cond = (rsi < 30) & cross_up(rsi, 30) & (obv > obv_prev)
        short_cond = (rsi > 70) & cross_down(rsi, 70) & (obv < obv_prev)

        signals[long_cond] = 1.0
        signals[short_cond] = -1.0

        # Exit conditions
        exit_cond = cross_any(rsi, 50) | cross_any(obv, obv_prev)
        signals[exit_cond & (signals != 0.0)] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Risk management: ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        close = df["close"].values

        long_entry_mask = signals == 1.0
        short_entry_mask = signals == -1.0

        df.loc[long_entry_mask, "bb_stop_long"] = (
            close[long_entry_mask] - stop_atr_mult * atr[long_entry_mask]
        )
        df.loc[long_entry_mask, "bb_tp_long"] = (
            close[long_entry_mask] + tp_atr_mult * atr[long_entry_mask]
        )

        df.loc[short_entry_mask, "bb_stop_short"] = (
            close[short_entry_mask] + stop_atr_mult * atr[short_entry_mask]
        )
        df.loc[short_entry_mask, "bb_tp_short"] = (
            close[short_entry_mask] - tp_atr_mult * atr[short_entry_mask]
        )

        signals.iloc[:warmup] = 0.0
        return signals