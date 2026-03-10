from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_rsi_bollinger_atr')

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
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])
        atr = np.nan_to_num(indicators['atr'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])

        # Entry conditions
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        # Cross detection helpers
        prev_close = np.roll(df["close"].values, 1)
        prev_close[0] = np.nan
        prev_bb_lower = np.roll(indicators['bollinger']['lower'], 1)
        prev_bb_lower[0] = np.nan
        prev_bb_upper = np.roll(indicators['bollinger']['upper'], 1)
        prev_bb_upper[0] = np.nan
        prev_adx = np.roll(adx, 1)
        prev_adx[0] = np.nan

        # Long entry: close crosses above indicators['bollinger']['lower'] AND rsi < oversold AND adx > 25
        close_cross_above_lower = (df["close"].values > indicators['bollinger']['lower']) & (prev_close <= prev_bb_lower)
        rsi_oversold_condition = rsi < rsi_oversold
        adx_condition = adx > 25

        long_entry = close_cross_above_lower & rsi_oversold_condition & adx_condition
        long_mask = long_entry

        # Short entry: close crosses below indicators['bollinger']['upper'] AND rsi > overbought AND adx > 25
        close_cross_below_upper = (df["close"].values < indicators['bollinger']['upper']) & (prev_close >= prev_bb_upper)
        rsi_overbought_condition = rsi > rsi_overbought
        short_entry = close_cross_below_upper & rsi_overbought_condition & adx_condition
        short_mask = short_entry

        # Exit conditions
        # Exit long: close crosses above indicators['bollinger']['middle']
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan
        exit_long = (df["close"].values > indicators['bollinger']['middle']) & (prev_close <= prev_bb_middle)
        long_mask = long_mask & ~exit_long

        # Exit short: close crosses below indicators['bollinger']['middle']
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan
        exit_short = (df["close"].values < indicators['bollinger']['middle']) & (prev_close >= prev_bb_middle)
        short_mask = short_mask & ~exit_short

        # ADX-based exit
        adx_exit = adx < 20
        long_mask = long_mask & ~adx_exit
        short_mask = short_mask & ~adx_exit

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = (signals == 1.0)
        entry_short = (signals == -1.0)

        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = df.loc[entry_long, "close"] - stop_atr_mult * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = df.loc[entry_long, "close"] + tp_atr_mult * atr[entry_long]

        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = df.loc[entry_short, "close"] + stop_atr_mult * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = df.loc[entry_short, "close"] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals