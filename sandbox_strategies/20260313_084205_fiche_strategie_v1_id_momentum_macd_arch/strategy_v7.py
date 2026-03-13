from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_macd')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'fast_period': 14,
         'leverage': 1,
         'rsi_overbought': 80,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'signal_period': 10,
         'slow_period': 32,
         'stop_atr_mult': 2.75,
         'tp_atr_mult': 4.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'fast_period': ParameterSpec(
                name='fast_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'slow_period': ParameterSpec(
                name='slow_period',
                min_val=20,
                max_val=60,
                default=32,
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
                min_val=1.0,
                max_val=5.0,
                default=2.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=8.0,
                default=4.0,
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
        # warmup protection
        signals.iloc[:warmup] = 0.0
        # Extract indicators
        macd_d = indicators['macd']
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        signal_line = np.nan_to_num(macd_d["signal"])
        histogram = np.nan_to_num(macd_d["histogram"])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        # Cross detection
        prev_macd = np.roll(indicators['macd']['macd'], 1)
        prev_signal = np.roll(signal_line, 1)
        prev_macd[0] = np.nan
        prev_signal[0] = np.nan
        cross_up = (indicators['macd']['macd'] > signal_line) & (prev_macd <= prev_signal)
        cross_down = (indicators['macd']['macd'] < signal_line) & (prev_macd >= prev_signal)
        # Entry conditions
        long_entry = cross_up & (rsi > params["rsi_oversold"]) & (rsi < params["rsi_overbought"])
        short_entry = cross_down & (rsi > params["rsi_oversold"]) & (rsi < params["rsi_overbought"])
        # Exit conditions
        prev_histogram = np.roll(histogram, 1)
        prev_histogram[0] = np.nan
        sign_change = (histogram * prev_histogram) < 0
        rsi_exit_long = rsi > params["rsi_overbought"]
        rsi_exit_short = rsi < params["rsi_oversold"]
        exit_long = sign_change | rsi_exit_long
        exit_short = sign_change | rsi_exit_short
        # Set masks
        long_mask = long_entry
        short_mask = short_entry
        # Apply exits
        exit_long_mask = np.zeros(n, dtype=bool)
        exit_short_mask = np.zeros(n, dtype=bool)
        exit_long_mask[1:] = exit_long[1:]
        exit_short_mask[1:] = exit_short[1:]
        # Ensure no exit on entry bar
        exit_long_mask[long_mask] = False
        exit_short_mask[short_mask] = False
        # Apply exits to existing positions
        long_mask = long_mask | exit_long_mask
        short_mask = short_mask | exit_short_mask
        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        # Write SL/TP columns if using ATR-based risk management
        close = df["close"].values
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
