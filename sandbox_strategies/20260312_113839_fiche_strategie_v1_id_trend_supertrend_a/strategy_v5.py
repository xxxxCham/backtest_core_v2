from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_rsi_atr_trend')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'atr_vol_threshold_factor': 0.5,
         'ema_long_period': 50,
         'ema_short_period': 20,
         'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_short_period': ParameterSpec(
                name='ema_short_period',
                min_val=5,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
            ),
            'ema_long_period': ParameterSpec(
                name='ema_long_period',
                min_val=30,
                max_val=200,
                default=50,
                param_type='int',
                step=1,
            ),
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=50,
                default=14,
                param_type='int',
                step=1,
            ),
            'rsi_overbought': ParameterSpec(
                name='rsi_overbought',
                min_val=60,
                max_val=90,
                default=70,
                param_type='int',
                step=1,
            ),
            'rsi_oversold': ParameterSpec(
                name='rsi_oversold',
                min_val=10,
                max_val=40,
                default=30,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'atr_vol_threshold_factor': ParameterSpec(
                name='atr_vol_threshold_factor',
                min_val=0.1,
                max_val=1.0,
                default=0.5,
                param_type='float',
                step=0.1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=2.0,
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
        # Extract indicator arrays
        short_ema = indicators['ema']
        long_ema = indicators['ema']
        rsi_arr = indicators['rsi']
        atr_arr = indicators['atr']

        # Compute average ATR for threshold
        atr_avg = np.mean(atr_arr)

        # Identify EMA crossovers using roll to avoid explicit loops
        cross_above = (short_ema > long_ema) & (np.roll(short_ema, 1) <= np.roll(long_ema, 1))
        cross_below = (short_ema < long_ema) & (np.roll(short_ema, 1) >= np.roll(long_ema, 1))

        # Long condition: cross above, price above short EMA, RSI < 70, ATR > 0.5*avg
        long_mask = (
            cross_above
            & (df['close'].values > short_ema)
            & (rsi_arr < 70)
            & (atr_arr > 0.5 * atr_avg)
        )

        # Short condition: cross below, price below short EMA, RSI > 30, ATR > 0.5*avg
        short_mask = (
            cross_below
            & (df['close'].values < short_ema)
            & (rsi_arr > 30)
            & (atr_arr > 0.5 * atr_avg)
        )

        # Assign signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals
