from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='supertrend_bollinger_rsi_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'bollinger', 'rsi', 'atr']

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
        # warmup protection
        signals.iloc[:warmup] = 0.0
        # Extract indicators
        close = df["close"].values
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        st = indicators['supertrend']
        supertrend_upper = np.nan_to_num(st["supertrend"])
        indicators['supertrend']['direction'] = np.nan_to_num(st["direction"])
        bb = indicators['bollinger']
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        # Entry conditions
        # Long entry: close crosses above supertrend upper AND close > bb.upper AND rsi > 50
        prev_supertrend_upper = np.roll(supertrend_upper, 1)
        prev_supertrend_upper[0] = 0.0
        cross_above_supertrend = (close > supertrend_upper) & (prev_supertrend_upper <= supertrend_upper)
        long_entry_condition = (close > indicators['bollinger']['upper']) & (rsi > 50)
        long_mask = cross_above_supertrend & long_entry_condition
        # Short entry: close crosses below supertrend lower AND close < bb.lower AND rsi < 50
        prev_supertrend_lower = np.roll(supertrend_upper, 1)
        prev_supertrend_lower[0] = 0.0
        cross_below_supertrend = (close < supertrend_upper) & (prev_supertrend_lower >= supertrend_upper)
        short_entry_condition = (close < indicators['bollinger']['lower']) & (rsi < 50)
        short_mask = cross_below_supertrend & short_entry_condition
        # Exit conditions
        # Exit long: close crosses below supertrend lower OR adx < 20
        # Exit short: close crosses above supertrend upper OR adx < 20
        # For simplicity, we'll just use supertrend direction for exit
        # Long exit: supertrend direction changes to down
        prev_direction = np.roll(indicators['supertrend']['direction'], 1)
        prev_direction[0] = 0.0
        long_exit = (indicators['supertrend']['direction'] < 1) & (prev_direction >= 1)
        # Short exit: supertrend direction changes to up
        short_exit = (indicators['supertrend']['direction'] > 1) & (prev_direction <= 1)
        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        # For ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        # On long entry bars only, compute ATR-based levels
        entry_long_mask = (signals == 1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]
        # On short entry bars only, compute ATR-based levels
        entry_short_mask = (signals == -1.0)
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        # Apply exit signals
        signals[long_exit] = 0.0
        signals[short_exit] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals