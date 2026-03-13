from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='supertrend_adx_rsi_trend')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
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
                max_val=6.0,
                default=3.0,
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

        # Prepare output series
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        # Wrap indicators with explicit float conversion to avoid integer NaN assignment
        direction = indicators['supertrend']["direction"].astype(float)
        adx_val = indicators['adx']["adx"].astype(float)
        rsi = indicators['rsi'].astype(float)
        atr = indicators['atr'].astype(float)
        close = df["close"].values

        # Entry conditions
        long_mask = (direction == 1) & (adx_val > 25) & (rsi > 50)
        short_mask = (direction == -1) & (adx_val > 25) & (rsi < 50)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions (direction change or RSI crossing 50)
        prev_dir = np.roll(direction, 1)
        prev_dir[0] = np.nan
        dir_change = (direction != prev_dir) & (~np.isnan(prev_dir))

        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        rsi_cross_up = (rsi > 50) & (prev_rsi <= 50)
        rsi_cross_down = (rsi < 50) & (prev_rsi >= 50)
        rsi_cross_any = rsi_cross_up | rsi_cross_down

        exit_mask = dir_change | rsi_cross_any
        # Ensure signals revert to 0 when an exit condition is met
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]

        return signals