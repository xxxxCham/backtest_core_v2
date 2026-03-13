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
        return ['supertrend', 'momentum', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'momentum_period': 10,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 4.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'momentum_period': ParameterSpec(
                name='momentum_period',
                min_val=5,
                max_val=30,
                default=10,
                param_type='int',
                step=1,
            ),
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
        momentum_val = np.nan_to_num(indicators['momentum'])
        atr = np.nan_to_num(indicators['atr'])

        # Compute moving average of ATR for volatility filter
        atr_mean = np.convolve(atr, np.ones(20)/20, mode='valid')
        atr_mean = np.pad(atr_mean, (19, 0), mode='constant', constant_values=np.nan)

        # Entry conditions
        long_condition = (direction == 1) & (momentum_val > 0) & (atr > atr_mean)
        short_condition = (direction == -1) & (momentum_val < 0) & (atr > atr_mean)

        # Exit conditions
        prev_direction = np.roll(direction, 1)
        prev_direction[0] = 0
        direction_change = (direction != prev_direction) & (direction != 0)

        momentum_cross_down = (momentum_val < 0) & (np.roll(momentum_val, 1) >= 0)
        volatility_filter = atr < atr_mean

        exit_long = direction_change | momentum_cross_down | volatility_filter
        exit_short = direction_change | (~momentum_cross_down) | volatility_filter

        # Boolean masks
        long_mask = long_condition
        short_mask = short_condition

        # Apply exit signals
        exit_long_mask = exit_long
        exit_short_mask = exit_short

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        close = df["close"].values
        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 4.0)

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
