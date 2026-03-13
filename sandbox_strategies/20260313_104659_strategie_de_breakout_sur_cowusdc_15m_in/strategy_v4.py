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
        return ['pivot_points', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_threshold': 25,
         'leverage': 1,
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
            'adx_threshold': ParameterSpec(
                name='adx_threshold',
                min_val=10,
                max_val=50,
                default=25,
                param_type='int',
                step=1,
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
        close = df["close"].values
        atr = np.nan_to_num(indicators['atr'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])

        # Warmup
        signals.iloc[:warmup] = 0.0

        # Previous close
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan

        # Previous pivot values
        prev_r1 = np.roll(r1, 1)
        prev_r1[0] = np.nan
        prev_s1 = np.roll(s1, 1)
        prev_s1[0] = np.nan

        # Cross up/down conditions
        close_above_r1 = (close > r1)
        prev_below_r1 = (prev_close <= prev_r1)
        close_below_s1 = (close < s1)
        prev_above_s1 = (prev_close >= prev_s1)

        # Long entry conditions
        adx_condition = (adx > params["adx_threshold"])
        atr_condition = (atr > 0.001)
        long_entry = close_above_r1 & prev_below_r1 & adx_condition & atr_condition

        # Short entry conditions
        short_entry = close_below_s1 & prev_above_s1 & adx_condition & atr_condition

        # Set masks
        long_mask = long_entry
        short_mask = short_entry

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Write SL/TP columns for long entries
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        if long_mask.any():
            df.loc[long_mask, "bb_stop_long"] = close[long_mask] - params["stop_atr_mult"] * atr[long_mask]
            df.loc[long_mask, "bb_tp_long"] = close[long_mask] + params["tp_atr_mult"] * atr[long_mask]

        # Write SL/TP columns for short entries
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        if short_mask.any():
            df.loc[short_mask, "bb_stop_short"] = close[short_mask] + params["stop_atr_mult"] * atr[short_mask]
            df.loc[short_mask, "bb_tp_short"] = close[short_mask] - params["tp_atr_mult"] * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
