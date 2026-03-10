from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='adx_filtered_bollinger_rsi_v4')

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

        # Extract indicators
        bb = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Prepare arrays for cross detection
        upper_bb = np.nan_to_num(bb["upper"])
        lower_bb = np.nan_to_num(bb["lower"])
        middle_bb = np.nan_to_num(bb["middle"])
        adx_val = np.nan_to_num(adx_d["adx"])

        # Define masks for entry conditions
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]
        adx_threshold = 25
        adx_exit_threshold = 20

        # Long entry: close crosses above upper BB, RSI > 50, ADX > 25
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_upper_bb = np.roll(upper_bb, 1)
        prev_upper_bb[0] = np.nan

        cross_above = (close > upper_bb) & (prev_close <= prev_upper_bb)
        rsi_long = rsi > rsi_overbought
        adx_long = adx_val > adx_threshold

        long_mask = cross_above & rsi_long & adx_long

        # Short entry: close crosses below lower BB, RSI < 50, ADX > 25
        prev_lower_bb = np.roll(lower_bb, 1)
        prev_lower_bb[0] = np.nan

        cross_below = (close < lower_bb) & (prev_close >= prev_lower_bb)
        rsi_short = rsi < rsi_oversold
        adx_short = adx_val > adx_threshold

        short_mask = cross_below & rsi_short & adx_short

        # Exit conditions: close crosses middle BB or ADX < 20
        prev_middle_bb = np.roll(middle_bb, 1)
        prev_middle_bb[0] = np.nan
        prev_adx = np.roll(adx_val, 1)
        prev_adx[0] = np.nan

        exit_long = (close < middle_bb) & (prev_close >= prev_middle_bb)
        exit_short = (close > middle_bb) & (prev_close <= prev_middle_bb)

        # Exit based on ADX
        adx_exit_long = (adx_val < adx_exit_threshold) & long_mask
        adx_exit_short = (adx_val < adx_exit_threshold) & short_mask

        # Combine exit conditions
        exit_long = exit_long | adx_exit_long
        exit_short = exit_short | adx_exit_short

        # Apply exit signals to existing positions
        # We don't want to close a position that wasn't entered
        # So we only close if there was an entry signal before
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set exit signals to zero
        exit_long_mask = np.zeros(n, dtype=bool)
        exit_short_mask = np.zeros(n, dtype=bool)
        exit_long_mask[exit_long] = True
        exit_short_mask[exit_short] = True

        # Ensure we don't close a position on the same bar it was opened
        signals[exit_long_mask & (np.roll(signals, 1) == 1.0)] = 0.0
        signals[exit_short_mask & (np.roll(signals, 1) == -1.0)] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Write SL/TP columns into df if using ATR-based risk management
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = (signals == 1.0)
        entry_short = (signals == -1.0)

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
