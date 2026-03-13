from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_bollinger_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'bollinger_period': 20,
         'bollinger_std': 2,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'bollinger_period': ParameterSpec(
                name='bollinger_period',
                min_val=10,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=10,
                max_val=30,
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
        bb = indicators['bollinger']
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])
        indicators['adx']['plus_di'] = np.nan_to_num(adx_d["plus_di"])
        indicators['adx']['minus_di'] = np.nan_to_num(adx_d["minus_di"])

        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values
        
        # Remove OBV usage since it's not in required_indicators
        # obv = np.nan_to_num(indicators['obv'])

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Define trend filter (ADX > 25)
        adx_threshold = 25
        adx_filter = adx > adx_threshold

        # Long entry: close crosses above upper band AND adx > 25
        prev_close = np.roll(close, 1)
        prev_upper = np.roll(upper, 1)
        prev_close[0] = np.nan
        prev_upper[0] = np.nan
        cross_above = (close > upper) & (prev_close <= prev_upper)
        long_entry = cross_above & adx_filter

        # Short entry: close crosses below lower band AND adx > 25
        prev_lower = np.roll(lower, 1)
        prev_lower[0] = np.nan
        cross_below = (close < lower) & (prev_close >= prev_lower)
        short_entry = cross_below & adx_filter

        # Exit conditions
        # Exit long: close crosses below middle band OR adx < 20
        adx_exit_threshold = 20
        adx_exit = adx < adx_exit_threshold
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        exit_long = (close < middle) & (prev_close >= prev_middle) | adx_exit

        # Exit short: close crosses above middle band OR adx < 20
        exit_short = (close > middle) & (prev_close <= prev_middle) | adx_exit

        # Set long and short masks
        long_mask = long_entry
        short_mask = short_entry

        # Apply exit signals
        # For long exit, find all long positions that are now exiting
        long_positions = np.zeros(n, dtype=bool)
        long_positions[long_mask] = True
        exit_long_mask = np.zeros(n, dtype=bool)
        exit_long_mask[exit_long] = True
        # Ensure we don't exit on the same bar as entry
        exit_long_mask[long_mask] = False
        long_mask = long_mask | (long_positions & exit_long_mask)

        # For short exit
        short_positions = np.zeros(n, dtype=bool)
        short_positions[short_mask] = True
        exit_short_mask = np.zeros(n, dtype=bool)
        exit_short_mask[exit_short] = True
        # Ensure we don't exit on the same bar as entry
        exit_short_mask[short_mask] = False
        short_mask = short_mask | (short_positions & exit_short_mask)

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals