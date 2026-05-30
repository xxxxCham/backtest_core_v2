"""
GRADUATED STRATEGY — promoted by catalog.graduation

  Session:    20260520_173440_strat_gie_de_multi_factor_sur_ordiusdc_1
  Origin:     success
  Best Score: 100.0
  Best Return: 1660.0%
  Contexts:   5/8
  Sweep:      100.0%
  WFA:        0.735 (strict)
  WFA robust: 8.517
"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ordiusdc_multi_factor_trend_follower')

    @property
    def required_indicators(self) -> List[str]:
        return ['directional_bias', 'adx', 'obv', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_threshold': 25,
         'leverage': 1,
         'stop_atr_mult': 2.2,
         'tp_atr_mult': 3.8,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'adx_threshold': ParameterSpec(
                name='adx_threshold',
                min_val=15,
                max_val=40,
                default=25,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=3.5,
                default=2.2,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=5.0,
                default=3.8,
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

    def get_indicator_params(self, indicator_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        static_params = {'adx': {'adx_threshold': 25},
         'atr': {'period': 14},
         'directional_bias': {'threshold': 0},
         'obv': {'obv_trend_period': 1}}
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
        bias = indicators['directional_bias']
        bull_score = np.nan_to_num(bias["bull_score"])
        bear_score = np.nan_to_num(bias["bear_score"])
        net_bias = np.nan_to_num(bias["net_bias"])
        directional_bias_data = bias
        directional_bias_bull_score = bull_score
        directional_bias_bear_score = bear_score
        directional_bias_net = net_bias
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])
        plus_di = np.nan_to_num(adx_d["plus_di"])
        minus_di = np.nan_to_num(adx_d["minus_di"])
        adx_data = adx_d
        adx_plus_di = plus_di
        adx_minus_di = minus_di
        obv = np.nan_to_num(indicators['obv'])
        obv_arr = obv
        obv_data = obv
        atr = np.nan_to_num(indicators['atr'])
        atr_arr = atr
        atr_data = atr
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        prev_obv = np.roll(indicators['obv'], 1)
        long_mask = (indicators['directional_bias']['net_bias'] > 0) & (indicators['adx']['adx'] > 25) & (indicators['obv'] > prev_obv)
        short_mask = (indicators['directional_bias']['net_bias'] < 0) & (indicators['adx']['adx'] > 25) & (indicators['obv'] < prev_obv)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        atr_val = indicators['atr']
        df['bb_stop_long'] = df['close'] - (atr_val * 2)
        df['bb_tp_long'] = df['close'] + (atr_val * 4)
        df['bb_stop_short'] = df['close'] + (atr_val * 2)
        df['bb_tp_short'] = df['close'] - (atr_val * 4)
        signals.iloc[:warmup] = 0.0
        return signals