from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_with_atr_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'atr', 'rsi']

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
        close = df["close"].values

        # Compute rolling mean of ATR for filtering
        atr_mean = np.convolve(atr, np.ones(20)/20, mode='valid')
        atr_mean = np.pad(atr_mean, (19, 0), mode='constant', constant_values=np.nan)

        # Entry conditions
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        # Long entry: close crosses above lower Bollinger band, RSI < 30, ATR > ATR 20-period mean
        lower_bb = np.nan_to_num(bb["lower"])
        prev_lower_bb = np.roll(lower_bb, 1)
        prev_lower_bb[0] = np.nan
        close_above_lower = (close > lower_bb)
        prev_close_below_lower = (np.roll(close, 1) <= prev_lower_bb)
        long_entry = close_above_lower & prev_close_below_lower & (rsi < rsi_oversold) & (atr > atr_mean)

        # Short entry: close crosses below upper Bollinger band, RSI > 70, ATR > ATR 20-period mean
        upper_bb = np.nan_to_num(bb["upper"])
        prev_upper_bb = np.roll(upper_bb, 1)
        prev_upper_bb[0] = np.nan
        close_below_upper = (close < upper_bb)
        prev_close_above_upper = (np.roll(close, 1) >= prev_upper_bb)
        short_entry = close_below_upper & prev_close_above_upper & (rsi > rsi_overbought) & (atr > atr_mean)

        # Set masks
        long_mask = long_entry
        short_mask = short_entry

        # Exit conditions
        middle_bb = np.nan_to_num(bb["middle"])
        prev_middle_bb = np.roll(middle_bb, 1)
        prev_middle_bb[0] = np.nan
        close_crosses_middle_long = (close > middle_bb) & (np.roll(close, 1) <= prev_middle_bb)
        close_crosses_middle_short = (close < middle_bb) & (np.roll(close, 1) >= prev_middle_bb)
        rsi_crosses_50_long = (rsi > 50) & (np.roll(rsi, 1) <= 50)
        rsi_crosses_50_short = (rsi < 50) & (np.roll(rsi, 1) >= 50)

        # Exit signals
        long_exit = close_crosses_middle_long | rsi_crosses_50_long
        short_exit = close_crosses_middle_short | rsi_crosses_50_short

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set stop-loss and take-profit levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        if np.any(entry_long_mask):
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        if np.any(entry_short_mask):
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
