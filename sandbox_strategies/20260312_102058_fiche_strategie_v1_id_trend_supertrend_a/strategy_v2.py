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
            'adx_period': 15,
            'leverage': 1,
            'rsi_period': 14,
            'stop_atr_mult': 1.25,
            'supertrend_multiplier': 3.0,
            'supertrend_period': 15,
            'tp_atr_mult': 3.0,
            'warmup': 30,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'supertrend_period': ParameterSpec(
                name='supertrend_period',
                min_val=5,
                max_val=30,
                default=15,
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
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=30,
                default=15,
                param_type='int',
                step=1,
            ),
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
                default=1.25,
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

        # Warm‑up period
        warmup = int(params.get('warmup', 50))

        # Unwrap indicator arrays and cast to float to preserve NaNs
        supertrend_dir = indicators['supertrend']["direction"].astype(float)
        adx_val = indicators['adx']["adx"].astype(float)
        rsi = indicators['rsi'].astype(float)
        atr = indicators['atr'].astype(float)
        close = df["close"].values.astype(float)

        # Entry masks
        long_mask = (supertrend_dir == 1) & (adx_val > 25) & (rsi > 50)
        short_mask = (supertrend_dir == -1) & (adx_val > 25) & (rsi < 50)

        # Exit masks
        prev_dir = np.roll(supertrend_dir, 1).astype(float)
        prev_dir[0] = np.nan
        dir_change = supertrend_dir != prev_dir

        prev_rsi = np.roll(rsi, 1).astype(float)
        prev_rsi[0] = np.nan
        cross_rsi = (
            (rsi > 50) & (prev_rsi <= 50)
        ) | ((rsi < 50) & (prev_rsi >= 50))

        adx_exit = adx_val < 20

        exit_mask = dir_change | cross_rsi | adx_exit

        # Apply warm‑up
        signals.iloc[:warmup] = 0.0

        # Apply exits first
        signals[exit_mask] = 0.0

        # Apply entries
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR‑based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 1.25))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        long_entries = signals == 1.0
        short_entries = signals == -1.0

        df.loc[long_entries, "bb_stop_long"] = close[long_entries] - stop_atr_mult * atr[long_entries]
        df.loc[long_entries, "bb_tp_long"] = close[long_entries] + tp_atr_mult * atr[long_entries]

        df.loc[short_entries, "bb_stop_short"] = close[short_entries] + stop_atr_mult * atr[short_entries]
        df.loc[short_entries, "bb_tp_short"] = close[short_entries] - tp_atr_mult * atr[short_entries]

        # Re‑apply warm‑up to ensure no signals before it
        signals.iloc[:warmup] = 0.0
        return signals