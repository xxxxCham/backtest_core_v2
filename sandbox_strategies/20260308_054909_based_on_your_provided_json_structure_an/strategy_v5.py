from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='rsi_bollinger_mean_reversion_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'bollinger', 'adx']

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
            'rsi_oversold': ParameterSpec(
                name='rsi_oversold',
                min_val=10,
                max_val=40,
                default=30,
                param_type='int',
                step=1,
            ),
            'rsi_overbought': ParameterSpec(
                name='rsi_overbought',
                min_val=60,
                max_val=90,
                default=70,
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
        rsi = np.nan_to_num(indicators['rsi'])
        bb = indicators['bollinger']
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])

        # Entry conditions
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]

        # Cross detection
        prev_bb_lower = np.roll(indicators['bollinger']['lower'], 1)
        prev_bb_lower[0] = np.nan
        prev_bb_upper = np.roll(indicators['bollinger']['upper'], 1)
        prev_bb_upper[0] = np.nan

        cross_above_lower = (df["close"].values > indicators['bollinger']['lower']) & (prev_bb_lower <= indicators['bollinger']['lower'])
        cross_below_upper = (df["close"].values < indicators['bollinger']['upper']) & (prev_bb_upper >= indicators['bollinger']['upper'])

        # Long entry: close crosses above lower band, RSI < 30, ADX > 25
        long_entry = cross_above_lower & (rsi < rsi_oversold) & (adx > 25)
        long_mask = long_entry

        # Short entry: close crosses below upper band, RSI > 70, ADX > 25
        short_entry = cross_below_upper & (rsi > rsi_overbought) & (adx > 25)
        short_mask = short_entry

        # Exit conditions
        # Close crosses middle band
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan
        cross_middle = (df["close"].values > indicators['bollinger']['middle']) & (prev_bb_middle <= indicators['bollinger']['middle'])
        cross_middle_short = (df["close"].values < indicators['bollinger']['middle']) & (prev_bb_middle >= indicators['bollinger']['middle'])

        # Exit for long positions
        long_exit = cross_middle
        # Exit for short positions
        short_exit = cross_middle_short

        # ADX trend filter for exit
        adx_exit = adx < 20

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set exit conditions
        exit_long_mask = long_exit | adx_exit
        exit_short_mask = short_exit | adx_exit

        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based stop loss and take profit
        # Ensure ATR is in indicators
        if 'atr' not in indicators:
            # Create a dummy ATR if not present (this should not happen in real backtests)
            atr = np.ones(len(df))
        else:
            atr = np.nan_to_num(indicators['atr'])
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        long_entry_mask = (signals == 1.0)
        if np.any(long_entry_mask):
            df.loc[long_entry_mask, "bb_stop_long"] = df.loc[long_entry_mask, "close"] - stop_atr_mult * atr[long_entry_mask]
            df.loc[long_entry_mask, "bb_tp_long"] = df.loc[long_entry_mask, "close"] + tp_atr_mult * atr[long_entry_mask]

        # Short entries
        short_entry_mask = (signals == -1.0)
        if np.any(short_entry_mask):
            df.loc[short_entry_mask, "bb_stop_short"] = df.loc[short_entry_mask, "close"] + stop_atr_mult * atr[short_entry_mask]
            df.loc[short_entry_mask, "bb_tp_short"] = df.loc[short_entry_mask, "close"] - tp_atr_mult * atr[short_entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals