from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='rsi_adx_atr_momentum')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'atr_period': 14,
         'leverage': 1,
         'rsi_fast_period': 5,
         'rsi_slow_period': 14,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_fast_period': ParameterSpec(
                name='rsi_fast_period',
                min_val=3,
                max_val=10,
                default=5,
                param_type='int',
                step=1,
            ),
            'rsi_slow_period': ParameterSpec(
                name='rsi_slow_period',
                min_val=10,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=7,
                max_val=21,
                default=14,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=20,
                default=14,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=3.0,
                default=1.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
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

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        signals.iloc[:warmup] = 0.0

        # Wrap indicator arrays
        rsi_raw = np.nan_to_num(indicators['rsi'])
        adx_raw = np.nan_to_num(indicators['adx']["adx"])
        atr_raw = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Compute fast RSI as a simple rolling mean of the raw RSI
        rsi_fast_period = int(params.get("rsi_fast_period", 5))
        kernel = np.ones(rsi_fast_period) / rsi_fast_period
        rsi_fast = np.convolve(rsi_raw, kernel, mode="valid")
        rsi_fast = np.concatenate([np.full(rsi_fast_period - 1, np.nan), rsi_fast])

        # Slow RSI is the raw RSI (period 14)
        rsi_slow = rsi_raw

        # Helper cross functions
        def cross_up(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return (x > y) & (prev_x <= prev_y)

        def cross_down(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return (x < y) & (prev_x >= prev_y)

        # Entry conditions
        long_mask = cross_up(rsi_fast, rsi_slow) & (adx_raw > 25)
        short_mask = cross_down(rsi_fast, rsi_slow) & (adx_raw > 25)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        entry_long_mask = signals == 1.0
        entry_short_mask = signals == -1.0

        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr_raw[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr_raw[entry_long_mask]

        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr_raw[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr_raw[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
