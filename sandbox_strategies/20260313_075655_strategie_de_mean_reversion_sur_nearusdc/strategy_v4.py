from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 1.0,
         'tp_atr_mult': 2.0,
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
                default=1.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=6.0,
                default=2.0,
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
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Bollinger Bands
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])

        # RSI levels
        rsi_overbought = params.get("rsi_overbought", 70)
        rsi_oversold = params.get("rsi_oversold", 30)

        # ATR-based parameters
        stop_atr_mult = params.get("stop_atr_mult", 1.0)
        tp_atr_mult = params.get("tp_atr_mult", 2.0)

        # Entry conditions
        # Long entry: close crosses above lower band AND RSI < oversold
        prev_close = np.roll(close, 1)
        prev_bb_lower = np.roll(indicators['bollinger']['lower'], 1)
        prev_rsi = np.roll(rsi, 1)

        prev_close[0] = np.nan
        prev_bb_lower[0] = np.nan
        prev_rsi[0] = np.nan

        long_entry = (close > indicators['bollinger']['lower']) & (prev_close <= prev_bb_lower) & (rsi < rsi_oversold)

        # Short entry: close crosses below upper band AND RSI > overbought
        prev_bb_upper = np.roll(indicators['bollinger']['upper'], 1)
        prev_bb_upper[0] = np.nan

        short_entry = (close < indicators['bollinger']['upper']) & (prev_close >= prev_bb_upper) & (rsi > rsi_overbought)

        # Exit conditions
        # Exit long: close crosses above middle band
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan

        long_exit = (close < indicators['bollinger']['middle']) & (prev_close >= prev_bb_middle)

        # Exit short: close crosses below middle band
        short_exit = (close > indicators['bollinger']['middle']) & (prev_close <= prev_bb_middle)

        # Set masks
        long_mask = long_entry
        short_mask = short_entry

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set exit signals
        exit_long_mask = long_exit
        exit_short_mask = short_exit

        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Write SL/TP levels for long entries
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        entry_long_mask = (signals == 1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        # Write SL/TP levels for short entries
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_short_mask = (signals == -1.0)
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
