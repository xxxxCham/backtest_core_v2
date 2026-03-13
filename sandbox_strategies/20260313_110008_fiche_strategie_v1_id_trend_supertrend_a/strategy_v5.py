from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_supertrend_filtered_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'bollinger', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 2.25, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.25,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
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
        # warmup protection
        signals.iloc[:warmup] = 0.0
        # extract indicators
        st = indicators['supertrend']
        direction = np.nan_to_num(st["direction"])
        bb = indicators['bollinger']
        upper = np.nan_to_num(bb["upper"])
        lower = np.nan_to_num(bb["lower"])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values
        # define cross helpers
        prev_direction = np.roll(direction, 1)
        prev_direction[0] = 0
        direction_change = (direction != prev_direction) & (direction != 0)
        # entry conditions
        close_above_upper = (close > upper) & (np.roll(close, 1) <= np.roll(upper, 1))
        close_below_lower = (close < lower) & (np.roll(close, 1) >= np.roll(lower, 1))
        long_entry = (direction == 1) & close_above_upper & (rsi > 50)
        short_entry = (direction == -1) & close_below_lower & (rsi < 50)
        long_mask[long_entry] = True
        short_mask[short_entry] = True
        # exit conditions
        rsi_cross_down = (rsi < 30) & (np.roll(rsi, 1) >= 30)
        rsi_cross_up = (rsi > 70) & (np.roll(rsi, 1) <= 70)
        exit_condition = direction_change | rsi_cross_down | rsi_cross_up
        # apply exits
        signals[exit_condition] = 0.0
        # apply entries
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        # ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 2.25)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)
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
