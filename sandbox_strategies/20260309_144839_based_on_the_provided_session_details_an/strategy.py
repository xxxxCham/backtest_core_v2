from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='rsi_bollinger_atr_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'bollinger', 'atr', 'adx']

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
        rsi = np.nan_to_num(indicators['rsi'])
        bb = indicators['bollinger']
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        atr = np.nan_to_num(indicators['atr'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])

        # Entry conditions
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]

        # Cross detection helpers
        prev_close = np.roll(df["close"].values, 1)
        prev_close[0] = np.nan
        prev_bb_lower = np.roll(indicators['bollinger']['lower'], 1)
        prev_bb_lower[0] = np.nan
        prev_bb_upper = np.roll(indicators['bollinger']['upper'], 1)
        prev_bb_upper[0] = np.nan
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan

        # Long entry: close crosses below bb.lower AND rsi < oversold AND adx > 25
        close_cross_below_bb_lower = (df["close"].values < indicators['bollinger']['lower']) & (prev_close >= prev_bb_lower)
        long_condition = (rsi < rsi_oversold) & (adx > 25) & close_cross_below_bb_lower
        long_mask = long_condition

        # Short entry: close crosses above bb.upper AND rsi > overbought AND adx > 25
        close_cross_above_bb_upper = (df["close"].values > indicators['bollinger']['upper']) & (prev_close <= prev_bb_upper)
        short_condition = (rsi > rsi_overbought) & (adx > 25) & close_cross_above_bb_upper
        short_mask = short_condition

        # Exit conditions
        # Exit long: close crosses above bb.middle
        close_cross_above_bb_middle = (df["close"].values > indicators['bollinger']['middle']) & (prev_close <= prev_bb_middle)
        exit_long_mask = close_cross_above_bb_middle

        # Exit short: close crosses below bb.middle
        close_cross_below_bb_middle = (df["close"].values < indicators['bollinger']['middle']) & (prev_close >= prev_bb_middle)
        exit_short_mask = close_cross_below_bb_middle

        # Combine exit conditions
        exit_mask = exit_long_mask | exit_short_mask

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # Set warmup period
        signals.iloc[:warmup] = 0.0

        # Write ATR-based SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        # Long entries
        long_entry_mask = (signals == 1.0)
        if long_entry_mask.any():
            close_vals = df["close"].values
            df.loc[long_entry_mask, "bb_stop_long"] = close_vals[long_entry_mask] - stop_atr_mult * atr[long_entry_mask]
            df.loc[long_entry_mask, "bb_tp_long"] = close_vals[long_entry_mask] + tp_atr_mult * atr[long_entry_mask]

        # Short entries
        short_entry_mask = (signals == -1.0)
        if short_entry_mask.any():
            close_vals = df["close"].values
            df.loc[short_entry_mask, "bb_stop_short"] = close_vals[short_entry_mask] + stop_atr_mult * atr[short_entry_mask]
            df.loc[short_entry_mask, "bb_tp_short"] = close_vals[short_entry_mask] - tp_atr_mult * atr[short_entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
