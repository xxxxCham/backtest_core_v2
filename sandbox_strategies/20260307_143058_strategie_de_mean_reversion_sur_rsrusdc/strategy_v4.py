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
                default=2.0,
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
        close = df["close"].values
        # Entry conditions
        rsi_overbought = params.get("rsi_overbought", 65)
        rsi_oversold = params.get("rsi_oversold", 35)
        # Short entry: close > upper AND rsi > overbought
        short_entry = (close > upper) & (rsi > rsi_overbought)
        short_mask = short_entry
        # Long entry: close < lower AND rsi < oversold
        long_entry = (close < lower) & (rsi < rsi_oversold)
        long_mask = long_entry
        # Exit conditions
        # Exit short on cross below middle or RSI < oversold
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        cross_below_middle = (close < middle) & (prev_middle >= middle)
        exit_short = cross_below_middle | (rsi < rsi_oversold)
        # Exit long on cross above middle or RSI > overbought
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        cross_above_middle = (close > middle) & (prev_middle <= middle)
        exit_long = cross_above_middle | (rsi > rsi_overbought)
        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        # Set exit signals to flat
        signals[exit_long] = 0.0
        signals[exit_short] = 0.0
        # Warmup protection
        signals.iloc[:warmup] = 0.0
        # ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 1.0)
        tp_atr_mult = params.get("tp_atr_mult", 2.0)
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
