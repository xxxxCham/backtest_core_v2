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
        close = np.nan_to_num(df["close"].values)

        # Volume trend
        obv_prev = np.roll(obv, 1)
        obv_prev[0] = np.nan
        obv_trend_up = (obv > 0) & (obv > obv_prev)
        obv_trend_down = (obv < 0) & (obv < obv_prev)

        # Cross detection
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        cross_above_s1 = (close > s1) & (prev_close <= s1)
        cross_below_s1 = (close < s1) & (prev_close >= s1)

        # Long entry: close crosses above S1 AND OBV positive and increasing
        long_mask = cross_above_s1 & obv_trend_up

        # Short entry: close crosses below S1 AND OBV negative and decreasing
        short_mask = cross_below_s1 & obv_trend_down

        # Exit conditions
        cross_above_r1 = (close > r1) & (prev_close <= r1)
        cross_below_r1 = (close < r1) & (prev_close >= r1)
        exit_long = cross_below_s1 | cross_above_r1
        exit_short = cross_above_s1 | cross_below_r1

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set stop-loss and take-profit levels
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        entry_long = (signals == 1.0)
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        # Short entries
        entry_short = (signals == -1.0)
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals