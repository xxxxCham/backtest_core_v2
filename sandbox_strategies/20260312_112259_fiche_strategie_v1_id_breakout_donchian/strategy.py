from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='supertrend_rsi_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'leverage': 1,
            'rsi_period': 14,
            'stop_atr_mult': 2.0,
            'tp_atr_mult': 5.5,
            'warmup': 20
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
                max_val=10.0,
                default=5.5,
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

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any],
    ) -> pd.Series:
        n = len(df)
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        warmup = int(params.get('warmup', 20))

        # Extract indicator arrays
        close = df["close"].values
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        st = indicators['supertrend']
        supertrend_val = np.nan_to_num(st["supertrend"])
        direction = np.nan_to_num(st["direction"])

        # Helper cross functions that handle scalar thresholds
        def cross_up(x: np.ndarray, y: np.ndarray | float) -> np.ndarray:
            x_arr = np.asarray(x)
            if np.isscalar(y):
                y_arr = np.full_like(x_arr, y)
            else:
                y_arr = np.asarray(y)
            prev_x = np.roll(x_arr, 1)
            prev_y = np.roll(y_arr, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return (x_arr > y_arr) & (prev_x <= prev_y)

        def cross_down(x: np.ndarray, y: np.ndarray | float) -> np.ndarray:
            x_arr = np.asarray(x)
            if np.isscalar(y):
                y_arr = np.full_like(x_arr, y)
            else:
                y_arr = np.asarray(y)
            prev_x = np.roll(x_arr, 1)
            prev_y = np.roll(y_arr, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return (x_arr < y_arr) & (prev_x >= prev_y)

        # Long entry: close crosses above supertrend and rsi > 50
        long_mask = cross_up(close, supertrend_val) & (rsi > 50)

        # Short entry: close crosses below supertrend and rsi < 50
        short_mask = cross_down(close, supertrend_val) & (rsi < 50)

        # Exit masks
        rsi_cross_down_50 = cross_down(rsi, 50.0)
        rsi_cross_up_50 = cross_up(rsi, 50.0)

        # Long exit: rsi crosses below 50 or direction flips to -1
        long_exit = rsi_cross_down_50 | (direction == -1)

        # Short exit: rsi crosses above 50 or direction flips to 1
        short_exit = rsi_cross_up_50 | (direction == 1)

        # Apply entry signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exit signals
        signals[long_exit] = 0.0
        signals[short_exit] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP levels for entries
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 5.5))

        # Long positions
        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]

        # Short positions
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]

        return signals