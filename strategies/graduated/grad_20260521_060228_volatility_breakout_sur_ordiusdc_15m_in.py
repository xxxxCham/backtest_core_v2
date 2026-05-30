"""
GRADUATED STRATEGY — promoted by catalog.graduation

  Session:    20260521_060228_volatility_breakout_sur_ordiusdc_15m_in
  Origin:     success
  Best Score: 83.5
  Best Return: 124.7%
  Contexts:   5/8
  Sweep:      100.0%
  WFA:        0.729 (strict)
  WFA robust: 9.466
"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='volatility_breakout_vortex_obv_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['amplitude_hunter', 'vortex', 'obv', 'adx', 'directional_bias', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_threshold': 25,
         'amp_threshold': 2.0,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 4.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'amp_threshold': ParameterSpec(
                name='amp_threshold',
                min_val=1.0,
                max_val=4.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
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
                max_val=3.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=6.0,
                default=4.0,
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
        static_params = {'adx': {'adx_threshold': 25, 'period': 14},
         'amplitude_hunter': {'score_threshold': 2.0},
         'directional_bias': {'threshold': 0.1},
         'obv': {'slope_period': 5},
         'vortex': {'period': 14}}
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
        amp = indicators['amplitude_hunter']
        range_pct = np.nan_to_num(amp["range_pct"])
        score = np.nan_to_num(amp["score"])
        amplitude_hunter_data = amp
        amplitude_hunter_range_pct = range_pct
        amplitude_hunter_score = score
        vx = indicators['vortex']
        vi_plus = np.nan_to_num(vx["vi_plus"])
        vi_minus = np.nan_to_num(vx["vi_minus"])
        vortex_data = vx
        vortex_vi_plus = vi_plus
        vortex_vi_minus = vi_minus
        obv = np.nan_to_num(indicators['obv'])
        obv_arr = obv
        obv_data = obv
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])
        plus_di = np.nan_to_num(adx_d["plus_di"])
        minus_di = np.nan_to_num(adx_d["minus_di"])
        adx_data = adx_d
        adx_plus_di = plus_di
        adx_minus_di = minus_di
        bias = indicators['directional_bias']
        bull_score = np.nan_to_num(bias["bull_score"])
        bear_score = np.nan_to_num(bias["bear_score"])
        net_bias = np.nan_to_num(bias["net_bias"])
        directional_bias_data = bias
        directional_bias_bull_score = bull_score
        directional_bias_bear_score = bear_score
        directional_bias_net = net_bias
        atr = np.nan_to_num(indicators['atr'])
        atr_arr = atr
        atr_data = atr
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        # Initialize signals and masks
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Extract parameters
        adx_thresh = float(params.get("adx_threshold", 25.0))
        amp_thresh = float(params.get("amp_threshold", 2.0))
        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 4.0))
        warmup = int(params.get("warmup", 50))

        # Extract indicators with safety
        amp = indicators['amplitude_hunter']
        amp_score = np.nan_to_num(amp["score"])

        vx = indicators['vortex']
        vi_plus = np.nan_to_num(vx["vi_plus"])
        vi_minus = np.nan_to_num(vx["vi_minus"])

        obv = np.nan_to_num(indicators['obv'])
        obv_prev = np.roll(obv, 1)
        obv_prev[0] = np.nan
        obv_up = obv > obv_prev
        obv_down = obv < obv_prev

        adx_d = indicators['adx']
        adx_val = np.nan_to_num(adx_d["adx"])

        bias = indicators['directional_bias']
        net_bias = np.nan_to_num(bias["net_bias"])

        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Define Entry Conditions
        long_entry_cond = (
            (amp_score > amp_thresh) & 
            (vi_plus > vi_minus) & 
            (adx_val > adx_thresh) & 
            (net_bias > 0) &
            (obv_up)
        )

        short_entry_cond = (
            (amp_score > amp_thresh) & 
            (vi_minus > vi_plus) & 
            (adx_val > adx_thresh) & 
            (net_bias < 0) &
            (obv_down)
        )

        # Apply warmup constraint
        warmup_mask = np.arange(n) >= warmup
        long_mask = long_entry_cond & warmup_mask
        short_mask = short_entry_cond & warmup_mask

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Calculate ATR-based SL/TP for the engine
        # We only write these on entry bars
        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - (stop_atr_mult * atr[long_mask])
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + (tp_atr_mult * atr[long_mask])
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + (stop_atr_mult * atr[short_mask])
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - (tp_atr_mult * atr[short_mask])

        # Ensure signals[0:50] is zeroed to avoid NaN-driven false signals
        signals.iloc[:50] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals