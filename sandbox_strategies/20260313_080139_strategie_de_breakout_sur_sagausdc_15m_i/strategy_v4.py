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

        # Volume trend helpers
        obv_diff = np.insert(np.diff(obv), 0, 0.0)
        obv_trend = obv_diff > 0

        # Cross detection
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        close_above_s1 = (close > s1) & (prev_close <= s1)
        close_below_s1 = (close < s1) & (prev_close >= s1)

        # Entry conditions
        long_condition = close_above_s1 & (obv < 0) & (obv_trend)
        short_condition = close_below_s1 & (obv > 0) & (~obv_trend)

        long_mask = long_condition
        short_mask = short_condition

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        exit_long = close_below_s1 | (close > r1)
        exit_short = close_above_s1 | (close < r1)

        # Apply exit signals
        signals[exit_long & (signals == 1.0)] = 0.0
        signals[exit_short & (signals == -1.0)] = 0.0

        # ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        if np.any(entry_long_mask):
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        if np.any(entry_short_mask):
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
