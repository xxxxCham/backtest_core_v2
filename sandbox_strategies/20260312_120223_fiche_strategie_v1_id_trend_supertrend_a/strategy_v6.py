from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_supertrend_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'adx_period': 13,
            'atr_period': 14,
            'leverage': 1,
            'rsi_overbought': 70,
            'rsi_oversold': 30,
            'rsi_period': 14,
            'stop_atr_mult': 2.0,
            'supertrend_atr_period': 17,
            'supertrend_multiplier': 2.5,
            'tp_atr_mult': 2.0,
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
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=4.0,
                default=2.0,
                param_type='float',
                step=0.1,
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
                max_val=5.0,
                default=2.5,
                param_type='float',
                step=0.1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=10,
                max_val=20,
                default=13,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=10,
                max_val=30,
                default=14,
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
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        # Wrap indicator arrays
        close = df["close"].values
        supertrend_line = np.nan_to_num(indicators['supertrend']["supertrend"])
        direction = np.nan_to_num(indicators['supertrend']["direction"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Entry conditions
        long_mask = (close > supertrend_line) & (adx_val > 30) & (rsi > 50)
        short_mask = (close < supertrend_line) & (adx_val > 30) & (rsi < 50)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        prev_dir = np.roll(direction, 1).astype(float)
        prev_dir[0] = np.nan
        dir_change = (direction != prev_dir) & (~np.isnan(prev_dir))

        prev_rsi = np.roll(rsi, 1).astype(float)
        prev_rsi[0] = np.nan
        cross_up = (rsi > 50) & (prev_rsi <= 50)
        cross_down = (rsi < 50) & (prev_rsi >= 50)
        cross_any_rsi = cross_up | cross_down

        exit_mask = dir_change | cross_any_rsi
        signals[(signals != 0) & exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based stop‑loss and take‑profit
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 2.0)

        entry_long_mask = signals == 1.0
        entry_short_mask = signals == -1.0

        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]

        return signals