"""
GRADUATED STRATEGY — promoted by catalog.graduation

  Session:    20260522_021658_objective_cette_strat_gie_de_regime_ada
  Origin:     failed
  Best Score: 88.5
  Best Return: 34.3%
  Contexts:   3/8
  Sweep:      100.0%
  WFA:        0.695 (low_confidence)
  WFA robust: 22.254
"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='choppiness_cmf_keltner_trend')

    @property
    def required_indicators(self) -> List[str]:
        return ['choppiness_index', 'cmf', 'keltner', 'atr', 'momentum']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'choppiness_threshold': 38.2,
         'cmf_zero_line': 0,
         'keltner_multiplier': 2.0,
         'keltner_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'trailing_atr_mult': 1.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'choppiness_threshold': ParameterSpec(
                name='choppiness_threshold',
                min_val=20,
                max_val=50,
                default=38.2,
                param_type='float',
                step=0.1,
            ),
            'keltner_multiplier': ParameterSpec(
                name='keltner_multiplier',
                min_val=1.0,
                max_val=3.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=3.0,
                default=1.5,
                param_type='float',
                step=0.1,
            ),
            'trailing_atr_mult': ParameterSpec(
                name='trailing_atr_mult',
                min_val=0.5,
                max_val=2.0,
                default=1.0,
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
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=4.5,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
        }

    def get_indicator_params(self, indicator_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        static_params = {'atr': {'period': 14},
         'choppiness_index': {'period': 14},
         'cmf': {'period': 20},
         'keltner': {'multiplier': 2.0, 'period': 20}}
        key = str(indicator_name or '').strip().lower()
        base_params = super().get_indicator_params(indicator_name, params)
        merged = dict(static_params.get(key, {}))
        merged.update(base_params)
        return merged

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        choppiness_index = np.nan_to_num(indicators['choppiness_index'])
        choppiness_index_arr = choppiness_index
        choppiness_index_data = choppiness_index
        cmf = np.nan_to_num(indicators['cmf'])
        cmf_arr = cmf
        cmf_data = cmf
        kelt = indicators['keltner']
        upper = np.nan_to_num(kelt["upper"])
        middle = np.nan_to_num(kelt["middle"])
        lower = np.nan_to_num(kelt["lower"])
        keltner_data = kelt
        keltner_upper = upper
        keltner_middle = middle
        keltner_lower = lower
        atr = np.nan_to_num(indicators['atr'])
        atr_arr = atr
        atr_data = atr
        momentum = np.nan_to_num(indicators['momentum'])
        momentum_arr = momentum
        momentum_data = momentum
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        chop_thresh = params.get("chop_threshold", 38.2)
        cmf_thresh = params.get("cmf_threshold", 0.15)
        mom_thresh = params.get("momentum_threshold", 0.0)
        stop_mult = params.get("stop_atr_mult", 2.0)
        tp_mult = params.get("tp_atr_mult", 4.0)

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Extract indicators
        chop = np.nan_to_num(indicators['choppiness_index'])
        cmf = np.nan_to_num(indicators['cmf'])
        kelt = indicators['keltner']
        kelt_upper = np.nan_to_num(kelt["upper"])
        kelt_lower = np.nan_to_num(kelt["lower"])
        kelt_middle = np.nan_to_num(kelt["middle"])
        atr = np.nan_to_num(indicators['atr'])
        momentum = np.nan_to_num(indicators['momentum'])
        close = df["close"].values

        # 1. Regime Filter: Only trade when market is NOT choppy (Trending)
        # Choppiness Index < 38.2 indicates a trend.
        is_trending = chop < chop_thresh

        # 2. Long Conditions
        # - Trending market
        # - Price breaks above Keltner Upper (Breakout)
        # - CMF is positive and above threshold (Volume confirmation)
        # - Momentum is positive (Trend strength)
        # - Price > Middle Band (Optional, ensures we are in upper half)

        # Breakout logic: ((Close > Upper) & (np.roll(Close, 1) <= np.roll(Upper, 1)))
        prev_close = np.roll(close, 1)
        prev_upper = np.roll(kelt_upper, 1)
        prev_close[0] = np.nan
        prev_upper[0] = np.nan
        breakout_up = (close > kelt_upper) & (prev_close <= prev_upper)

        # Volume Confirmation
        cmf_confirmed = cmf > cmf_thresh

        # Momentum Confirmation
        mom_confirmed = momentum > mom_thresh

        # Long Entry Mask
        long_conditions = (
            is_trending &
            breakout_up &
            cmf_confirmed &
            mom_confirmed
        )

        # 3. Short Conditions
        # - Trending market
        # - Price breaks below Keltner Lower (Breakdown)
        # - CMF is negative and below -threshold (Volume confirmation)
        # - Momentum is negative (Trend strength)

        # Breakdown logic: ((Close < Lower) & (np.roll(Close, 1) >= np.roll(Lower, 1)))
        prev_lower = np.roll(kelt_lower, 1)
        prev_lower[0] = np.nan
        breakout_down = (close < kelt_lower) & (prev_close >= prev_lower)

        # Volume Confirmation
        cmf_confirmed_short = cmf < -cmf_thresh

        # Momentum Confirmation
        mom_confirmed_short = momentum < mom_thresh

        # Short Entry Mask
        short_conditions = (
            is_trending &
            breakout_down &
            cmf_confirmed_short &
            mom_confirmed_short
        )

        # Apply masks
        long_mask = long_conditions
        short_mask = short_conditions

        # Apply warmup
        long_mask[:warmup] = False
        short_mask[:warmup] = False

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP for Long entries
        entry_long = signals == 1.0
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_mult * atr[entry_long]

        # Set SL/TP for Short entries
        entry_short = signals == -1.0
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals