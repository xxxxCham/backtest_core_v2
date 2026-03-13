from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_supertrend_ema_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.25, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.25,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
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
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Initialize signal series
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        # Indicator arrays
        close = df["close"].values
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])
        # Convert to float to allow NaN assignments
        super_dir = indicators['supertrend']["direction"].astype(float)
        adx_val = np.nan_to_num(indicators['adx']["adx"])

        # Entry masks
        long_mask = (
            (super_dir == 1) &
            (adx_val > 25) &
            (close > ema)
        )
        short_mask = (
            (super_dir == -1) &
            (adx_val > 25) &
            (close < ema)
        )

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        prev_dir = np.roll(super_dir, 1).astype(float)
        prev_dir[0] = np.nan
        dir_change = (super_dir != prev_dir)

        # Long exit: direction changes to -1 or close crosses below ema
        long_exit = (
            (dir_change & (super_dir == -1)) |
            (close < ema)
        )
        # Short exit: direction changes to 1 or close crosses above ema
        short_exit = (
            (dir_change & (super_dir == 1)) |
            (close > ema)
        )

        exit_mask = (long_exit | short_exit) & (signals != 0.0)
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 1.25))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        entry_long_mask = signals == 1.0
        entry_short_mask = signals == -1.0

        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]

        return signals