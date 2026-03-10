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
                max_val=30,
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

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Extract indicators
        st = indicators['supertrend']
        momentum = np.nan_to_num(indicators['momentum'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Supertrend values
        supertrend_line = np.nan_to_num(st["supertrend"])
        direction = np.nan_to_num(st["direction"])

        # Create cross helpers
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_supertrend = np.roll(supertrend_line, 1)
        prev_supertrend[0] = np.nan
        prev_direction = np.roll(direction, 1)
        prev_direction[0] = 0  # Changed from np.nan to 0 to avoid integer conversion error

        # Entry conditions
        close_above_supertrend = (close > supertrend_line)
        close_below_supertrend = (close < supertrend_line)
        momentum_positive = (momentum > 0)
        momentum_negative = (momentum < 0)

        # Cross events
        cross_above = (close > supertrend_line) & (prev_close <= prev_supertrend)
        cross_below = (close < supertrend_line) & (prev_close >= prev_supertrend)

        # Long entry: close crosses above supertrend AND momentum > 0
        long_entry = cross_above & momentum_positive

        # Short entry: close crosses below supertrend AND momentum < 0
        short_entry = cross_below & momentum_negative

        # Exit conditions
        # Exit long: close crosses below supertrend OR momentum crosses below 0
        exit_long = (close < supertrend_line) | (momentum < 0)

        # Exit short: close crosses above supertrend OR momentum crosses above 0
        exit_short = (close > supertrend_line) | (momentum > 0)

        # Apply entries
        long_mask = long_entry
        short_mask = short_entry

        # Apply exits
        exit_long_mask = exit_long
        exit_short_mask = exit_short

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Handle exits (set to FLAT)
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Write SL/TP columns if using ATR-based risk management
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Set ATR-based stop-loss and take-profit levels for long entries
        entry_long_mask = (signals == 1.0)
        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]

        # Set ATR-based stop-loss and take-profit levels for short entries
        entry_short_mask = (signals == -1.0)
        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals