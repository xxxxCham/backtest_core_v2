from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_rsi_filtered')

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
        # Warmup protection
        signals.iloc[:warmup] = 0.0
        # Extract indicators
        rsi = np.nan_to_num(indicators['rsi'])
        bb = indicators['bollinger']
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        atr = np.nan_to_num(indicators['atr'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])
        # Define entry conditions
        rsi_overbought = params.get("rsi_overbought", 70)
        rsi_oversold = params.get("rsi_oversold", 30)
        adx_threshold = 25
        # Long entry: close < lower bollinger, rsi < oversold, adx > threshold
        long_condition = (df["close"].values < indicators['bollinger']['lower']) & (rsi < rsi_oversold) & (adx > adx_threshold)
        long_mask = long_condition
        # Short entry: close > upper bollinger, rsi > overbought, adx > threshold
        short_condition = (df["close"].values > indicators['bollinger']['upper']) & (rsi > rsi_overbought) & (adx > adx_threshold)
        short_mask = short_condition
        # Exit conditions: cross middle bollinger or adx < 20
        prev_close = np.roll(df["close"].values, 1)
        prev_close[0] = np.nan
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan
        cross_up_bb = (df["close"].values > indicators['bollinger']['middle']) & (prev_close <= prev_bb_middle)
        cross_down_bb = (df["close"].values < indicators['bollinger']['middle']) & (prev_close >= prev_bb_middle)
        cross_any_bb = cross_up_bb | cross_down_bb
        adx_exit_threshold = 20
        adx_cross_down = (adx < adx_exit_threshold) & (np.roll(adx, 1) >= adx_exit_threshold)
        adx_cross_down[0] = False
        exit_condition = cross_any_bb | adx_cross_down
        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        # Handle exits
        exit_long_mask = long_mask & exit_condition
        exit_short_mask = short_mask & exit_condition
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0
        # ATR-based SL/TP levels
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        # Long entries
        entry_long_mask = (signals == 1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = df.loc[entry_long_mask, "close"] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = df.loc[entry_long_mask, "close"] + tp_atr_mult * atr[entry_long_mask]
        # Short entries
        entry_short_mask = (signals == -1.0)
        df.loc[entry_short_mask, "bb_stop_short"] = df.loc[entry_short_mask, "close"] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = df.loc[entry_short_mask, "close"] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
