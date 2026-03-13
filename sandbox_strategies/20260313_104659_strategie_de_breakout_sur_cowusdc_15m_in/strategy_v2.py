from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='pivot_breakout_atr_filtered')

    @property
    def required_indicators(self) -> List[str]:
        return ['pivot_points', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'pivot_period': 1,
         'stop_atr_mult': 1.0,
         'tp_atr_mult': 2.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'pivot_period': ParameterSpec(
                name='pivot_period',
                min_val=1,
                max_val=10,
                default=1,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=3.0,
                default=1.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.0,
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
        r1 = np.nan_to_num(pp["r1"])
        s1 = np.nan_to_num(pp["s1"])
        close = np.nan_to_num(df["close"].values)
        atr = np.nan_to_num(indicators['atr'])

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Entry conditions with ATR filter
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_r1 = np.roll(r1, 1)
        prev_r1[0] = np.nan
        prev_s1 = np.roll(s1, 1)
        prev_s1[0] = np.nan

        # Long entry: close crosses above R1 and ATR > 0.001
        long_condition = (close > r1) & (prev_close <= prev_r1) & (atr > 0.001)
        long_mask = long_condition

        # Short entry: close crosses below S1 and ATR > 0.001
        short_condition = (close < s1) & (prev_close >= prev_s1) & (atr > 0.001)
        short_mask = short_condition

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Write ATR-based SL/TP levels
        stop_atr_mult = params.get("stop_atr_mult", 1.0)
        tp_atr_mult = params.get("tp_atr_mult", 2.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = (signals == 1.0)
        entry_short = (signals == -1.0)

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
