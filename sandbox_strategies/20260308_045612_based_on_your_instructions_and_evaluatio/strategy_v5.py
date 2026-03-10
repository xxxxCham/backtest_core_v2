from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='adx_filtered_bollinger_rsi_v3')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

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
                max_val=4.5,
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

        # Extract and sanitize indicators
        bb = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Prepare band arrays
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        # Prepare ADX arrays
        adx_val = np.nan_to_num(adx_d["adx"])

        # Define entry conditions
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]
        adx_threshold = 25

        # Entry long: close crosses above upper band AND rsi < 70 AND adx > 25
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_upper = np.roll(upper, 1)
        prev_upper[0] = np.nan

        cross_above_upper = (close > upper) & (prev_close <= prev_upper)

        long_entry_condition = (cross_above_upper) & (rsi < rsi_overbought) & (adx_val > adx_threshold)
        long_mask = long_entry_condition

        # Entry short: close crosses below lower band AND rsi > 30 AND adx > 25
        prev_lower = np.roll(lower, 1)
        prev_lower[0] = np.nan

        cross_below_lower = (close < lower) & (prev_close >= prev_lower)

        short_entry_condition = (cross_below_lower) & (rsi > rsi_oversold) & (adx_val > adx_threshold)
        short_mask = short_entry_condition

        # Exit conditions: close crosses middle band OR adx < 20
        adx_exit_threshold = 20

        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        cross_middle = (close > middle) & (prev_close <= prev_middle) | (close < middle) & (prev_close >= prev_middle)
        adx_exit = adx_val < adx_exit_threshold

        # Apply exit signals
        exit_mask = cross_middle | adx_exit
        exit_long_mask = long_mask & exit_mask
        exit_short_mask = short_mask & exit_mask

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        long_entry_indices = np.where(long_mask)[0]
        if len(long_entry_indices) > 0:
            for i in long_entry_indices:
                df.loc[df.index[i], "bb_stop_long"] = close[i] - stop_atr_mult * atr[i]
                df.loc[df.index[i], "bb_tp_long"] = close[i] + tp_atr_mult * atr[i]

        # Short entries
        short_entry_indices = np.where(short_mask)[0]
        if len(short_entry_indices) > 0:
            for i in short_entry_indices:
                df.loc[df.index[i], "bb_stop_short"] = close[i] + stop_atr_mult * atr[i]
                df.loc[df.index[i], "bb_tp_short"] = close[i] - tp_atr_mult * atr[i]
        signals.iloc[:warmup] = 0.0
        return signals
