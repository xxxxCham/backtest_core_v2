"""
GRADUATED STRATEGY — promoted by catalog.graduation

  Session:    20260429_210138_objective_filtrer_les_faux_signaux_de_m
  Origin:     saved_run
  Best Score: 0.0
  Best Return: 304.1%
  Contexts:   4/8
  Sweep:      100.0%
  WFA:        0.691 (low_confidence)
  WFA robust: 26.571
"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='coppock_momentum_reversal')

    @property
    def required_indicators(self) -> List[str]:
        return ['momentum', 'coppock_curve', 'volume_oscillator', 'directional_bias', 'atr', 'pivot_points', 'smart_legs']

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
                max_val=5.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=20,
                max_val=100,
                default=50,
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
        momentum = np.nan_to_num(indicators['momentum'])
        momentum_arr = momentum
        momentum_data = momentum
        coppock_curve = np.nan_to_num(indicators['coppock_curve'])
        coppock_curve_arr = coppock_curve
        coppock_curve_data = coppock_curve
        volume_oscillator = np.nan_to_num(indicators['volume_oscillator'])
        volume_oscillator_arr = volume_oscillator
        volume_oscillator_data = volume_oscillator
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
        pp = indicators['pivot_points']
        pivot = np.nan_to_num(pp["pivot"])
        r1 = np.nan_to_num(pp["r1"])
        pivot_points_data = pp
        pivot_points_pivot = pivot
        pivot_points_r1 = r1
        legs = indicators['smart_legs']
        bull_leg = np.nan_to_num(legs["smart_leg_bullish"]).astype(bool)
        smart_legs_data = legs
        smart_legs_bull_leg = bull_leg
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Warmup protection
        if warmup >= n:
            pass

        # Extract and sanitize indicators
        coppock = np.nan_to_num(indicators['coppock_curve'], nan=0.0)
        rsi = np.nan_to_num(indicators['momentum'], nan=50.0)  # momentum is RSI
        vol_osc = np.nan_to_num(indicators['volume_oscillator'], nan=0.0)
        atr = np.nan_to_num(indicators['atr'], nan=0.0)
        close = df["close"].values

        # Smart legs
        smart_legs = indicators['smart_legs']
        bull_leg_prob = np.nan_to_num(smart_legs.get("smart_leg_bullish", np.zeros(n)), nan=0.0)
        smart_leg_conf = params.get("smart_leg_confidence", 0.5)

        # Coppock threshold
        coppock_thresh = params.get("coppock_threshold", 0.0)
        rsi_thresh = params.get("rsi_threshold", 30.0)
        vol_thresh = params.get("volume_threshold", 0.0)

        # Condition 1: Coppock is positive and rising (crossed above threshold)
        # We use a simple threshold cross: Coppock > threshold AND previous Coppock <= threshold
        prev_coppock = np.roll(coppock, 1)
        prev_coppock[0] = np.nan
        coppock_cross_up = (coppock > coppock_thresh) & (prev_coppock <= coppock_thresh)

        # Condition 2: RSI is oversold (below threshold)
        rsi_oversold = rsi < rsi_thresh

        # Condition 3: Volume oscillator is positive (confirmation)
        vol_positive = vol_osc > vol_thresh

        # Condition 4: Smart legs bullish confidence
        smart_bull = bull_leg_prob > smart_leg_conf

        # Combine conditions with OR logic to reduce false negatives
        # Primary trigger: Coppock cross up + RSI oversold
        primary_long = coppock_cross_up & rsi_oversold

        # Secondary trigger: Coppock positive + RSI oversold + Volume confirmation
        secondary_long = (coppock > coppock_thresh) & rsi_oversold & vol_positive & smart_bull

        # Final long signal: either primary or secondary
        long_mask = primary_long | secondary_long

        # Ensure warmup bars are 0
        long_mask[:warmup] = False

        # Apply signals
        signals[long_mask] = 1.0

        # Write SL/TP levels for long entries
        sl_atr_mult = params.get("sl_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 4.0)

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        # Apply ATR-based SL/TP only on entry bars
        entry_bars = long_mask
        if np.any(entry_bars):
            df.loc[entry_bars, "bb_stop_long"] = close[entry_bars] - sl_atr_mult * atr[entry_bars]
            df.loc[entry_bars, "bb_tp_long"] = close[entry_bars] + tp_atr_mult * atr[entry_bars]
        signals.iloc[:warmup] = 0.0
        return signals