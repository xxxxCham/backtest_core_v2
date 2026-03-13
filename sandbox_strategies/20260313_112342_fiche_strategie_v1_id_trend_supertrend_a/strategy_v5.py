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
        return {'leverage': 1, 'stop_atr_mult': 1.25, 'tp_atr_mult': 4.5, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=3.0,
                default=1.25,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=8.0,
                default=4.5,
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

        # Get direction and ADX values
        direction = np.nan_to_num(st["direction"])
        adx = np.nan_to_num(adx_d["adx"])

        # Entry conditions
        long_condition = (direction == 1) & (adx > 25)
        short_condition = (direction == -1) & (adx > 25)

        # Exit conditions
        prev_direction = np.roll(direction, 1)
        prev_direction[0] = 0
        direction_change = (direction != prev_direction) & (direction != 0)
        adx_exit = adx < 15

        # Combine exit conditions
        exit_condition = direction_change | adx_exit

        # Initialize masks
        long_mask = long_condition
        short_mask = short_condition

        # Apply exit conditions
        # For long exits, we need to identify when the direction changes or ADX drops
        exit_long_mask = np.zeros(n, dtype=bool)
        exit_long_mask[1:] = (direction_change[1:] & (direction[1:] == -1)) | (adx_exit[1:] & (direction[1:] == 1))
        exit_long_mask[0] = False  # No exit on first bar

        # For short exits
        exit_short_mask = np.zeros(n, dtype=bool)
        exit_short_mask[1:] = (direction_change[1:] & (direction[1:] == 1)) | (adx_exit[1:] & (direction[1:] == -1))
        exit_short_mask[0] = False  # No exit on first bar

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exit conditions to signals
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Write SL/TP columns into df if using ATR-based risk management
        close = df["close"].values
        stop_atr_mult = params.get("stop_atr_mult", 1.25)
        tp_atr_mult = params.get("tp_atr_mult", 4.5)

        # Initialize SL/TP columns with NaN
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Compute ATR-based levels only on entry bars
        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
