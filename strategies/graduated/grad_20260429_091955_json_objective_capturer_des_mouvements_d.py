"""
GRADUATED STRATEGY — promoted by catalog.graduation

  Session:    20260429_091955_json_objective_capturer_des_mouvements_d
  Origin:     saved_run
  Best Score: 0.0
  Best Return: 113.4%
  Contexts:   3/8
  Sweep:      100.0%
  WFA:        0.638 (low_confidence)
  WFA robust: 10.584
"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='volatility_adaptive_fvg_ichimoku_v5')

    @property
    def required_indicators(self) -> List[str]:
        return ['atr', 'ichimoku', 'fvg', 'directional_bias']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_percentile_high': 60,
         'atr_percentile_low': 40,
         'directional_bias_threshold': 0.1,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=2.0,
                default=1.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=4.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'atr_percentile_high': ParameterSpec(
                name='atr_percentile_high',
                min_val=55,
                max_val=65,
                default=60,
                param_type='int',
                step=1,
            ),
            'atr_percentile_low': ParameterSpec(
                name='atr_percentile_low',
                min_val=35,
                max_val=45,
                default=40,
                param_type='int',
                step=1,
            ),
            'directional_bias_threshold': ParameterSpec(
                name='directional_bias_threshold',
                min_val=0.05,
                max_val=0.2,
                default=0.1,
                param_type='float',
                step=0.05,
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
        atr = np.nan_to_num(indicators['atr'])
        atr_arr = atr
        atr_data = atr
        ich = indicators['ichimoku']
        tenkan = np.nan_to_num(ich["tenkan"])
        kijun = np.nan_to_num(ich["kijun"])
        ichimoku_data = ich
        ichimoku_tenkan = tenkan
        ichimoku_kijun = kijun
        fvg = indicators['fvg']
        bull_gap = np.nan_to_num(indicators['fvg']["fvg_bullish"]).astype(bool)
        fvg_bullish_gap = bull_gap
        bias = indicators['directional_bias']
        bull_score = np.nan_to_num(bias["bull_score"])
        bear_score = np.nan_to_num(bias["bear_score"])
        net_bias = np.nan_to_num(bias["net_bias"])
        directional_bias_data = bias
        directional_bias_bull_score = bull_score
        directional_bias_bear_score = bear_score
        directional_bias_net = net_bias
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        signals.iloc[:warmup] = 0.0

        close = df["close"].values
        high = df["high"].values
        low = df["low"].values

        atr = np.nan_to_num(indicators['atr'])
        ich = indicators['ichimoku']
        tenkan = np.nan_to_num(ich["tenkan"])
        kijun = np.nan_to_num(ich["kijun"])
        senkou_a = np.nan_to_num(ich["senkou_a"])
        senkou_b = np.nan_to_num(ich["senkou_b"])
        cloud_position = np.nan_to_num(ich["cloud_position"])

        fvg = indicators['fvg']
        bull_gap = np.nan_to_num(indicators['fvg']["fvg_bullish"]).astype(bool)
        bear_gap = np.nan_to_num(indicators['fvg']["fvg_bearish"]).astype(bool)

        bias = indicators['directional_bias']
        net_bias = np.nan_to_num(bias["net_bias"])

        atr_percentile_high = params.get("atr_percentile_high", 60)
        atr_percentile_low = params.get("atr_percentile_low", 40)
        directional_bias_threshold = params.get("directional_bias_threshold", 0.1)

        atr_window = 20
        atr_percentiles = np.nanpercentile(atr, [atr_percentile_low, atr_percentile_high], axis=0)
        atr_low_threshold = atr_percentiles[0]
        atr_high_threshold = atr_percentiles[1]

        atr_in_range = (atr >= atr_low_threshold) & (atr <= atr_high_threshold)

        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_high = np.roll(high, 1)
        prev_high[0] = np.nan
        prev_low = np.roll(low, 1)
        prev_low[0] = np.nan

        prev_prev_close = np.roll(close, 2)
        prev_prev_close[:2] = np.nan
        prev_prev_high = np.roll(high, 2)
        prev_prev_high[:2] = np.nan
        prev_prev_low = np.roll(low, 2)
        prev_prev_low[:2] = np.nan

        prev_prev_prev_close = np.roll(close, 3)
        prev_prev_prev_close[:3] = np.nan
        prev_prev_prev_high = np.roll(high, 3)
        prev_prev_prev_high[:3] = np.nan
        prev_prev_prev_low = np.roll(low, 3)
        prev_prev_prev_low[:3] = np.nan

        fvg_bull_partial_fill_30 = (
            bull_gap &
            (close <= (prev_high - 0.3 * (prev_high - prev_low))) &
            (close >= (prev_high - 0.5 * (prev_high - prev_low)))
        )
        fvg_bull_partial_fill_50 = (
            bull_gap &
            (prev_close <= (prev_high - 0.3 * (prev_high - prev_low))) &
            (prev_close >= (prev_high - 0.5 * (prev_high - prev_low)))
        )
        fvg_bull_partial_fill_70 = (
            bull_gap &
            (prev_prev_close <= (prev_high - 0.3 * (prev_high - prev_low))) &
            (prev_prev_close >= (prev_high - 0.5 * (prev_high - prev_low)))
        )

        fvg_bear_partial_fill_30 = (
            bear_gap &
            (close >= (prev_low + 0.3 * (prev_high - prev_low))) &
            (close <= (prev_low + 0.5 * (prev_high - prev_low)))
        )
        fvg_bear_partial_fill_50 = (
            bear_gap &
            (prev_close >= (prev_low + 0.3 * (prev_high - prev_low))) &
            (prev_close <= (prev_low + 0.5 * (prev_high - prev_low)))
        )
        fvg_bear_partial_fill_70 = (
            bear_gap &
            (prev_prev_close >= (prev_low + 0.3 * (prev_high - prev_low))) &
            (prev_prev_close <= (prev_low + 0.5 * (prev_high - prev_low)))
        )

        bullish_fvg_confirmed = fvg_bull_partial_fill_30 | fvg_bull_partial_fill_50 | fvg_bull_partial_fill_70
        bearish_fvg_confirmed = fvg_bear_partial_fill_30 | fvg_bear_partial_fill_50 | fvg_bear_partial_fill_70

        above_cloud = cloud_position > 0
        below_cloud = cloud_position < 0

        long_entry = (
            above_cloud &
            bullish_fvg_confirmed &
            atr_in_range &
            (net_bias > directional_bias_threshold)
        )

        short_entry = (
            below_cloud &
            bearish_fvg_confirmed &
            atr_in_range &
            (net_bias < -directional_bias_threshold)
        )

        long_mask[long_entry] = True
        short_mask[short_entry] = True

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]

        prev_net_bias = np.roll(net_bias, 1)
        prev_net_bias[0] = np.nan
        prev_prev_net_bias = np.roll(net_bias, 2)
        prev_prev_net_bias[:2] = np.nan

        net_bias_reversal_down = (net_bias < -directional_bias_threshold) & (prev_net_bias > -directional_bias_threshold)
        net_bias_reversal_up = (net_bias > directional_bias_threshold) & (prev_net_bias < directional_bias_threshold)

        consecutive_negative_bias = (net_bias < 0) & (prev_net_bias < 0)
        consecutive_positive_bias = (net_bias > 0) & (prev_net_bias > 0)

        atr_above_80 = atr > np.nanpercentile(atr, 80)
        atr_below_20 = atr < np.nanpercentile(atr, 20)

        long_exit = (
            (close < kijun) |
            atr_above_80 |
            atr_below_20 |
            consecutive_negative_bias
        )

        short_exit = (
            (close > kijun) |
            atr_above_80 |
            atr_below_20 |
            consecutive_positive_bias
        )

        signals[(signals == 1.0) & long_exit] = 0.0
        signals[(signals == -1.0) & short_exit] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals