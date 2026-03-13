from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_supertrend')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 12,
         'atr_period': 20,
         'leverage': 1,
         'multiplier': 3.5,
         'stop_atr_mult': 1.75,
         'tp_atr_mult': 4.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=10,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
            ),
            'multiplier': ParameterSpec(
                name='multiplier',
                min_val=2.0,
                max_val=5.0,
                default=3.5,
                param_type='float',
                step=0.1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=10,
                max_val=20,
                default=12,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=3.0,
                default=1.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=8.0,
                default=4.0,
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
        st = indicators['supertrend']
        direction = np.nan_to_num(st["direction"])
        adx_d = indicators['adx']
        adx_val = np.nan_to_num(adx_d["adx"])
        atr = np.nan_to_num(indicators['atr'])
        # Warmup
        signals.iloc[:warmup] = 0.0
        # Entry conditions
        long_entry = (direction == 1) & (adx_val > 20)
        short_entry = (direction == -1) & (adx_val > 20)
        long_mask[long_entry] = True
        short_mask[short_entry] = True
        # Exit conditions
        prev_direction = np.roll(direction, 1)
        prev_direction[0] = 0
        direction_change = (direction != prev_direction) & (prev_direction != 0)
        adx_weak = adx_val < 15
        exit_condition = direction_change | adx_weak
        # Apply exits
        exit_long = exit_condition & (direction == -1)
        exit_short = exit_condition & (direction == 1)
        signals[exit_long] = 0.0
        signals[exit_short] = 0.0
        # Apply entries
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        # ATR-based SL/TP
        close = df["close"].values
        stop_atr_mult = params.get("stop_atr_mult", 1.75)
        tp_atr_mult = params.get("tp_atr_mult", 4.0)
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        entry_long = (signals == 1.0)
        entry_short = (signals == -1.0)
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
