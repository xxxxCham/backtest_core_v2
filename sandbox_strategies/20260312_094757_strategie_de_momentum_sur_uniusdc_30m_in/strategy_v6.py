from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='rsi_cross_sma_atr_short')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'atr', 'sma']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 10,
         'leverage': 1,
         'rsi_fast_period': 4,
         'rsi_slow_period': 12,
         'sma_period': 25,
         'stop_atr_mult': 1.2,
         'tp_atr_mult': 2.8,
         'warmup': 60}
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
            'sma_period': ParameterSpec(
                name='sma_period',
                min_val=10,
                max_val=50,
                default=20,
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
                max_val=4.0,
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
        # Prepare indicator arrays
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        sma = np.nan_to_num(indicators['sma'])
        close = df["close"].values

        # Compute fast RSI as a simple moving average of the slow RSI for illustration
        fast_period = int(params.get("rsi_fast_period", 5))
        slow_period = int(params.get("rsi_slow_period", 14))
        # Avoid division by zero
        kernel_fast = np.ones(fast_period) / fast_period
        kernel_slow = np.ones(slow_period) / slow_period
        fast_rsi = np.convolve(rsi, kernel_fast, mode="same")
        slow_rsi = np.convolve(rsi, kernel_slow, mode="same")

        # Helper cross functions
        prev_fast = np.roll(fast_rsi, 1)
        prev_slow = np.roll(slow_rsi, 1)
        prev_fast[0] = np.nan
        prev_slow[0] = np.nan
        cross_up = (fast_rsi > slow_rsi) & (prev_fast <= prev_slow)
        cross_down = (fast_rsi < slow_rsi) & (prev_fast >= prev_slow)

        # Long entry: fast RSI crosses above slow RSI AND close > SMA
        long_mask = cross_up & (close > sma)

        # Short entry: fast RSI crosses below slow RSI AND close < SMA
        short_mask = cross_down & (close < sma)

        # Exit long: fast RSI crosses below slow RSI OR close < SMA
        exit_long_mask = cross_down | (close < sma)

        # Exit short: fast RSI crosses above slow RSI OR close > SMA
        exit_short_mask = cross_up | (close > sma)

        # Apply warmup
        signals.iloc[:warmup] = 0.0

        # Set signal values
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_long_mask & (signals == 1.0)] = 0.0
        signals[exit_short_mask & (signals == -1.0)] = 0.0

        # ATR-based SL/TP for long entries
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))
        entry_long_mask = (signals == 1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        # ATR-based SL/TP for short entries
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        entry_short_mask = (signals == -1.0)
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
