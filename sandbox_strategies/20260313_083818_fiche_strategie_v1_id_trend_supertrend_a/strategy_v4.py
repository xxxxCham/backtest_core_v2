from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_supertrend_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 2.0, 'tp_atr_mult': 6.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=3.0,
                max_val=10.0,
                default=6.0,
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
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        # Ensure all arrays are same length
        direction = np.nan_to_num(st["direction"])
        adx = np.nan_to_num(adx_d["adx"])

        # Warmup period
        signals.iloc[:warmup] = 0.0

        # Entry conditions
        long_entry = (direction == 1) & (adx > 30)
        short_entry = (direction == -1) & (adx > 30)

        # Exit conditions
        prev_direction = np.roll(direction, 1)
        prev_direction[0] = 0
        direction_change = (direction != prev_direction)
        adx_weak = (adx < 20)
        exit_condition = direction_change | adx_weak

        # Initialize masks
        long_mask = long_entry
        short_mask = short_entry

        # Apply exit conditions
        # For longs, exit when direction changes or adx weakens
        long_exit_mask = np.zeros(n, dtype=bool)
        long_exit_mask[1:] = (direction_change[1:] & (direction[1:] == -1)) | adx_weak[1:]
        long_mask = long_mask & ~long_exit_mask

        # For shorts, exit when direction changes or adx weakens
        short_exit_mask = np.zeros(n, dtype=bool)
        short_exit_mask[1:] = (direction_change[1:] & (direction[1:] == 1)) | adx_weak[1:]
        short_mask = short_mask & ~short_exit_mask

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based stop-loss and take-profit
        close = df["close"].values
        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 6.0)

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        entry_long_mask = (signals == 1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        # Short entries
        entry_short_mask = (signals == -1.0)
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
