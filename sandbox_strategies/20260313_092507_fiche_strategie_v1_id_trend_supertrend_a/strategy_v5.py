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
        return {'leverage': 1, 'stop_atr_mult': 3.0, 'tp_atr_mult': 3.5, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=2.0,
                max_val=5.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=3.0,
                max_val=6.0,
                default=3.5,
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

        # Get arrays
        direction = np.nan_to_num(st["direction"])
        adx = np.nan_to_num(adx_d["adx"])
        close = df["close"].values

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Entry conditions
        long_condition = (direction == 1) & (adx > 30)
        short_condition = (direction == -1) & (adx > 30)

        # Exit conditions
        prev_direction = np.roll(direction, 1)
        prev_direction[0] = 0
        direction_change = (direction != prev_direction)
        adx_exit = (adx < 15)
        exit_condition = direction_change | adx_exit

        # Set long/short masks
        long_mask = long_condition
        short_mask = short_condition

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exit conditions
        exit_long_mask = (signals == 1.0) & exit_condition
        exit_short_mask = (signals == -1.0) & exit_condition
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Set SL/TP levels for ATR-based risk management
        stop_atr_mult = params.get("stop_atr_mult", 3.0)
        tp_atr_mult = params.get("tp_atr_mult", 3.5)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        long_entry_mask = (signals == 1.0)
        df.loc[long_entry_mask, "bb_stop_long"] = close[long_entry_mask] - stop_atr_mult * atr[long_entry_mask]
        df.loc[long_entry_mask, "bb_tp_long"] = close[long_entry_mask] + tp_atr_mult * atr[long_entry_mask]

        # Short entries
        short_entry_mask = (signals == -1.0)
        df.loc[short_entry_mask, "bb_stop_short"] = close[short_entry_mask] + stop_atr_mult * atr[short_entry_mask]
        df.loc[short_entry_mask, "bb_tp_short"] = close[short_entry_mask] - tp_atr_mult * atr[short_entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
