from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_rsi_atr_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr']

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
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Previous ATR for filtering
        prev_atr = np.roll(atr, 1)
        prev_atr[0] = np.nan

        # Cross calculations
        close = df["close"].values
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan

        # Long entry: close crosses above upper band, RSI > 50, ATR increasing
        cross_above = (close > upper) & (prev_close <= np.roll(upper, 1))
        long_condition = (cross_above) & (rsi > 50) & (atr > prev_atr)
        long_mask = long_condition

        # Short entry: close crosses below lower band, RSI < 50, ATR increasing
        cross_below = (close < lower) & (prev_close >= np.roll(lower, 1))
        short_condition = (cross_below) & (rsi < 50) & (atr > prev_atr)
        short_mask = short_condition

        # Exit conditions
        exit_long = (close < middle) | (rsi < 50) | (atr < prev_atr)
        exit_short = (close > middle) | (rsi > 50) | (atr < prev_atr)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels for long entries
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        entry_mask = (signals == 1.0)
        if entry_mask.any():
            stop_mult = params["stop_atr_mult"]
            tp_mult = params["tp_atr_mult"]
            df.loc[entry_mask, "bb_stop_long"] = close[entry_mask] - stop_mult * atr[entry_mask]
            df.loc[entry_mask, "bb_tp_long"] = close[entry_mask] + tp_mult * atr[entry_mask]

        # Set SL/TP levels for short entries
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        short_entry_mask = (signals == -1.0)
        if short_entry_mask.any():
            stop_mult = params["stop_atr_mult"]
            tp_mult = params["tp_atr_mult"]
            df.loc[short_entry_mask, "bb_stop_short"] = close[short_entry_mask] + stop_mult * atr[short_entry_mask]
            df.loc[short_entry_mask, "bb_tp_short"] = close[short_entry_mask] - tp_mult * atr[short_entry_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
