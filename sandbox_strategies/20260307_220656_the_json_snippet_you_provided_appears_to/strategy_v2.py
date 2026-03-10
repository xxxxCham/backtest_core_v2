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
        adx = indicators['adx']
        close = df["close"].values

        # Bollinger bands
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])

        # RSI thresholds
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]

        # ATR-based SL/TP multipliers
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        # Entry conditions
        # Long entry: close crosses above bb.lower AND rsi < oversold AND adx > 25
        prev_close = np.roll(close, 1)
        prev_bb_lower = np.roll(indicators['bollinger']['lower'], 1)
        prev_rsi = np.roll(rsi, 1)

        prev_close[0] = np.nan
        prev_bb_lower[0] = np.nan
        prev_rsi[0] = np.nan

        cross_above_lower = (close > indicators['bollinger']['lower']) & (prev_close <= prev_bb_lower)
        rsi_condition_long = rsi < rsi_oversold
        adx_condition_long = np.nan_to_num(indicators['adx']["adx"]) > 25

        long_entry = cross_above_lower & rsi_condition_long & adx_condition_long

        # Short entry: close crosses below bb.upper AND rsi > overbought AND adx > 25
        prev_bb_upper = np.roll(indicators['bollinger']['upper'], 1)
        prev_bb_upper[0] = np.nan

        cross_below_upper = (close < indicators['bollinger']['upper']) & (prev_close >= prev_bb_upper)
        rsi_condition_short = rsi > rsi_overbought
        adx_condition_short = np.nan_to_num(indicators['adx']["adx"]) > 25

        short_entry = cross_below_upper & rsi_condition_short & adx_condition_short

        # Exit conditions
        # Exit long: close crosses below bb.middle OR rsi > overbought OR rsi < oversold
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan

        cross_below_middle = (close < indicators['bollinger']['middle']) & (prev_close >= prev_bb_middle)
        exit_long = cross_below_middle | (rsi > rsi_overbought) | (rsi < rsi_oversold)

        # Exit short: close crosses above bb.middle OR rsi > overbought OR rsi < oversold
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan

        cross_above_middle = (close > indicators['bollinger']['middle']) & (prev_close <= prev_bb_middle)
        exit_short = cross_above_middle | (rsi > rsi_overbought) | (rsi < rsi_oversold)

        # Apply entry signals
        long_mask = long_entry
        short_mask = short_entry

        # Apply exit signals
        exit_long_mask = exit_long
        exit_short_mask = exit_short

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels for long entries
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        entry_long_mask = long_mask
        if np.any(entry_long_mask):
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        # Set SL/TP levels for short entries
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_short_mask = short_mask
        if np.any(entry_short_mask):
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals