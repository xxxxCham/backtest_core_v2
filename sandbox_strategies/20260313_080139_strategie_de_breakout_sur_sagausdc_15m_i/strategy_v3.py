from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='pivot_breakout_with_volume_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['pivot_points', 'obv', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
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
                min_val=1.0,
                max_val=6.0,
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
        pp = indicators['pivot_points']
        s1 = np.nan_to_num(pp["s1"])
        r1 = np.nan_to_num(pp["r1"])
        obv = np.nan_to_num(indicators['obv'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Volume trend
        obv_diff = np.insert(np.diff(obv), 0, 0.0)
        obv_positive = obv_diff > 0
        obv_negative = obv_diff < 0

        # Previous OBV for trend confirmation
        prev_obv = np.roll(obv, 1)
        prev_obv[0] = np.nan
        obv_increasing = obv > prev_obv
        obv_decreasing = obv < prev_obv

        # Close cross conditions
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        cross_above_s1 = (close > s1) & (prev_close <= s1)
        cross_below_s1 = (close < s1) & (prev_close >= s1)

        # Entry filters
        atr_filter = atr > 0.001

        # Long entry: close crosses above S1 with positive OBV and increasing volume
        long_entry = cross_above_s1 & obv_positive & obv_increasing & atr_filter
        long_mask = long_entry

        # Short entry: close crosses below S1 with negative OBV and decreasing volume
        short_entry = cross_below_s1 & obv_negative & obv_decreasing & atr_filter
        short_mask = short_entry

        # Exit conditions
        exit_long = (close < s1) | (close > r1)
        exit_short = (close > s1) | (close < r1)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long SL/TP
        entry_long = signals == 1.0
        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        # Short SL/TP
        entry_short = signals == -1.0
        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
