from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='supertrend_momentum_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'momentum', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'momentum_period': 10,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'momentum_period': ParameterSpec(
                name='momentum_period',
                min_val=5,
                max_val=20,
                default=10,
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

        # Extract indicators
        st = indicators['supertrend']
        supertrend_upper = st["supertrend"]
        direction = st["direction"]

        momentum = indicators['momentum']

        atr = indicators['atr']
        close = df["close"].values

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Define entry conditions
        # Long entry: close crosses above supertrend upper AND momentum > 0
        prev_supertrend_upper = np.roll(supertrend_upper, 1)
        prev_supertrend_upper[0] = supertrend_upper[0]
        close_above_upper = (close > supertrend_upper) & (prev_supertrend_upper <= supertrend_upper)
        long_entry = close_above_upper & (momentum > 0)

        # Short entry: close crosses below supertrend lower AND momentum < 0
        prev_supertrend_lower = np.roll(supertrend_upper, 1)
        prev_supertrend_lower[0] = supertrend_upper[0]
        close_below_upper = (close < supertrend_upper) & (prev_supertrend_lower >= supertrend_upper)
        short_entry = close_below_upper & (momentum < 0)

        # Set long and short masks
        long_mask = long_entry
        short_mask = short_entry

        # Exit conditions: close crosses below or above supertrend middle
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        prev_direction = np.roll(direction, 1)
        prev_direction[0] = direction[0]

        # Exit long when close crosses below supertrend middle
        exit_long = (close < supertrend_upper) & (prev_close >= prev_supertrend_upper)
        long_mask = long_mask & ~exit_long

        # Exit short when close crosses above supertrend middle
        exit_short = (close > supertrend_upper) & (prev_close <= prev_supertrend_upper)
        short_mask = short_mask & ~exit_short

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set ATR-based stop-loss and take-profit
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
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