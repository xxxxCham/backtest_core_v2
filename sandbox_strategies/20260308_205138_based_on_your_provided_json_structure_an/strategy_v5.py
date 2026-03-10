from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='adx_filtered_bollinger_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr', 'adx']

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
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=1,
                param_type='int',
                step=1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=4.5,
                default=3.0,
                param_type='float',
                step=0.1,
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

        # Extract indicators
        bb = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])

        # Bollinger bands
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        # RSI parameters
        rsi_overbought = params.get("rsi_overbought", 70)
        rsi_oversold = params.get("rsi_oversold", 30)

        # ATR-based risk management
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Entry conditions
        # Long entry: close crosses above upper band, RSI < 70, ADX > 25
        prev_close = np.roll(df["close"].values, 1)
        prev_close[0] = np.nan
        prev_upper = np.roll(upper, 1)
        prev_upper[0] = np.nan
        cross_above_upper = (df["close"].values > upper) & (prev_close <= prev_upper)

        long_entry_condition = (cross_above_upper) & (rsi < rsi_overbought) & (adx > 25)
        long_mask = long_entry_condition

        # Short entry: close crosses below lower band, RSI > 30, ADX > 25
        prev_lower = np.roll(lower, 1)
        prev_lower[0] = np.nan
        cross_below_lower = (df["close"].values < lower) & (prev_close >= prev_lower)

        short_entry_condition = (cross_below_lower) & (rsi > rsi_oversold) & (adx > 25)
        short_mask = short_entry_condition

        # Exit conditions
        # Exit long: close crosses below middle band OR ADX < 20
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        cross_below_middle = (df["close"].values < middle) & (prev_close >= prev_middle)

        long_exit_condition = cross_below_middle | (adx < 20)
        long_exit_mask = long_exit_condition

        # Exit short: close crosses above middle band OR ADX < 20
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        cross_above_middle = (df["close"].values > middle) & (prev_close <= prev_middle)

        short_exit_condition = cross_above_middle | (adx < 20)
        short_exit_mask = short_exit_condition

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Update SL/TP columns for long entries
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        entry_mask = (signals == 1.0)
        if entry_mask.any():
            df.loc[entry_mask, "bb_stop_long"] = df["close"].values[entry_mask] - stop_atr_mult * atr[entry_mask]
            df.loc[entry_mask, "bb_tp_long"] = df["close"].values[entry_mask] + tp_atr_mult * atr[entry_mask]

        # Update SL/TP columns for short entries
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        short_entry_mask = (signals == -1.0)
        if short_entry_mask.any():
            df.loc[short_entry_mask, "bb_stop_short"] = df["close"].values[short_entry_mask] + stop_atr_mult * atr[short_entry_mask]
            df.loc[short_entry_mask, "bb_tp_short"] = df["close"].values[short_entry_mask] - tp_atr_mult * atr[short_entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
