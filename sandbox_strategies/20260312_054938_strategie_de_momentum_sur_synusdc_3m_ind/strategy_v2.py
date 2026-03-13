from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_ema_atr_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'ema_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=1,
                param_type='int',
                step=1,
            ),
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=5,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
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
            'warmup': ParameterSpec(
                name='warmup',
                min_val=0,
                max_val=100,
                default=50,
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

        # Warmup period
        signals.iloc[:warmup] = 0.0

        # Get indicators
        ema_indicator = indicators['ema']
        atr_indicator = indicators['atr']

        # Calculate EMA difference
        close = df["close"].values
        ema_diff = close - ema_indicator

        # Get current and previous differences
        ema_diff_current = ema_diff[-n:]
        ema_diff_prev = np.roll(ema_diff_current, 1)
        ema_diff_prev[0] = 0  # Handle first element

        # Set long and short conditions
        long_mask = (ema_diff_current > 0) & (ema_diff_prev <= 0)
        short_mask = (ema_diff_current < 0) & (ema_diff_prev >= 0)

        # Warmup protection
        long_mask[:warmup] = False
        short_mask[:warmup] = False

        # Calculate stop levels using ATR
        stop_mult = params.get("stop_atr_mult", 2.0)
        if not np.all(np.isnan(atr_indicator)):
            df.loc[:, "bb_stop_long"] = np.nan
            df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_mult * atr_indicator[long_mask]
            df.loc[long_mask, "bb_tp_long"] = close[long_mask] + stop_mult * atr_indicator[long_mask]

        # Assign signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals