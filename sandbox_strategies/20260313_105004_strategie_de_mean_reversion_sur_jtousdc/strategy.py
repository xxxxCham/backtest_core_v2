from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_atr')

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
        close = df["close"].values
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Bollinger bands
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        # RSI thresholds
        rsi_overbought = params.get("rsi_overbought", 65)
        rsi_oversold = params.get("rsi_oversold", 35)

        # ATR multipliers
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Cross detection
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_upper = np.roll(upper, 1)
        prev_upper[0] = np.nan
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        prev_lower = np.roll(lower, 1)
        prev_lower[0] = np.nan

        # Entry conditions
        cross_below_upper = (close < upper) & (prev_close >= prev_upper)
        cross_above_lower = (close > lower) & (prev_close <= prev_lower)
        cross_above_middle = (close > middle) & (prev_close <= prev_middle)
        cross_below_middle = (close < middle) & (prev_close >= prev_middle)

        # Long entry: price crosses below lower band and RSI is not overbought
        long_entry = cross_below_upper & (rsi < rsi_overbought)
        long_mask[long_entry] = True

        # Short entry: price crosses above upper band and RSI is not oversold
        short_entry = cross_above_lower & (rsi > rsi_oversold)
        short_mask[short_entry] = True

        # Exit conditions
        exit_long = cross_above_middle
        exit_short = cross_below_middle

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels for longs
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        long_entries = signals == 1.0
        if np.any(long_entries):
            df.loc[long_entries, "bb_stop_long"] = close[long_entries] - stop_atr_mult * atr[long_entries]
            df.loc[long_entries, "bb_tp_long"] = close[long_entries] + tp_atr_mult * atr[long_entries]

        # Set SL/TP levels for shorts
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        short_entries = signals == -1.0
        if np.any(short_entries):
            df.loc[short_entries, "bb_stop_short"] = close[short_entries] + stop_atr_mult * atr[short_entries]
            df.loc[short_entries, "bb_tp_short"] = close[short_entries] - tp_atr_mult * atr[short_entries]
        signals.iloc[:warmup] = 0.0
        return signals
