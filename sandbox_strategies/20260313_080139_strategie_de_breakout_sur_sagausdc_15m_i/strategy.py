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

        # Volume comparison
        prev_obv = np.roll(obv, 1)
        prev_obv[0] = np.nan
        obv_up = (obv > 0) & (prev_obv < obv)
        obv_down = (obv < 0) & (prev_obv > obv)

        # Cross detection
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        cross_above_s1 = (close > s1) & (prev_close <= s1)
        cross_below_s1 = (close < s1) & (prev_close >= s1)

        # Long entry: close crosses above S1 with positive volume
        long_entry = cross_above_s1 & obv_up
        long_mask = long_entry

        # Short entry: close crosses below S1 with negative volume
        short_entry = cross_below_s1 & obv_down
        short_mask = short_entry

        # Exit conditions
        exit_long = (close < s1) | (close > r1)
        exit_short = (close > s1) | (close < r1)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels for long entries
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        entry_mask = (signals == 1.0)
        if np.any(entry_mask):
            df.loc[entry_mask, "bb_stop_long"] = close[entry_mask] - stop_atr_mult * atr[entry_mask]
            df.loc[entry_mask, "bb_tp_long"] = close[entry_mask] + tp_atr_mult * atr[entry_mask]

        # Set SL/TP levels for short entries
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        short_entry_mask = (signals == -1.0)
        if np.any(short_entry_mask):
            df.loc[short_entry_mask, "bb_stop_short"] = close[short_entry_mask] + stop_atr_mult * atr[short_entry_mask]
            df.loc[short_entry_mask, "bb_tp_short"] = close[short_entry_mask] - tp_atr_mult * atr[short_entry_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
