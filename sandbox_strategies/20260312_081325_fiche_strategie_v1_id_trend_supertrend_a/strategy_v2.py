from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='supertrend_adx_ema_trend_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 4.5, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
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

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Indicator arrays (kept as floats to allow NaN handling)
        close = df["close"].values
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        direction = np.array(indicators['supertrend']["direction"], dtype=float)

        # Helper cross functions
        def cross_up(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            px = np.roll(x, 1)
            py = np.roll(y, 1)
            px[0] = np.nan
            py[0] = np.nan
            return (x > y) & (px <= py)

        def cross_down(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            px = np.roll(x, 1)
            py = np.roll(y, 1)
            px[0] = np.nan
            py[0] = np.nan
            return (x < y) & (px >= py)

        # Entry masks
        long_mask = (direction == 1) & (adx_val > 25) & (close > ema)
        short_mask = (direction == -1) & (adx_val > 25) & (close < ema)

        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit masks
        prev_dir = np.roll(direction, 1)
        prev_dir[0] = direction[0]  # avoid NaN
        dir_change = direction != prev_dir
        exit_long_mask = dir_change | (adx_val < 20) | cross_down(close, ema)
        exit_short_mask = dir_change | (adx_val < 20) | cross_up(close, ema)

        # Apply exits only to active positions
        signals[exit_long_mask & (signals == 1.0)] = 0.0
        signals[exit_short_mask & (signals == -1.0)] = 0.0

        # Warmup period
        signals.iloc[:warmup] = 0.0

        # Risk management columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_mult = params.get("stop_atr_mult", 1.5)
        tp_mult = params.get("tp_atr_mult", 4.5)

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_mult * atr[entry_short]

        return signals