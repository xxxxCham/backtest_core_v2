from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_macd_mid_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'macd_fast': 15,
         'macd_signal': 10,
         'macd_slow': 22,
         'rsi_overbought': 55,
         'rsi_oversold': 45,
         'rsi_period': 14,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 2.5,
         'warmup': 30}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=50,
                default=14,
                param_type='int',
                step=1,
            ),
            'rsi_oversold': ParameterSpec(
                name='rsi_oversold',
                min_val=30,
                max_val=50,
                default=45,
                param_type='int',
                step=1,
            ),
            'rsi_overbought': ParameterSpec(
                name='rsi_overbought',
                min_val=50,
                max_val=70,
                default=55,
                param_type='int',
                step=1,
            ),
            'macd_fast': ParameterSpec(
                name='macd_fast',
                min_val=5,
                max_val=30,
                default=15,
                param_type='int',
                step=1,
            ),
            'macd_slow': ParameterSpec(
                name='macd_slow',
                min_val=10,
                max_val=50,
                default=22,
                param_type='int',
                step=1,
            ),
            'macd_signal': ParameterSpec(
                name='macd_signal',
                min_val=5,
                max_val=20,
                default=10,
                param_type='int',
                step=1,
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
                default=2.5,
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
        macd_vals = indicators['macd']['macd']
        signal_vals = indicators['macd']['signal']
        prev_macd = np.roll(macd_vals, 1)
        prev_signal = np.roll(signal_vals, 1)

        rsi_vals = indicators['rsi']
        rsi_range = (rsi_vals > 45) & (rsi_vals < 55)

        # MACD cross conditions
        macd_cross_above = (macd_vals > signal_vals) & (prev_macd <= prev_signal)
        macd_cross_below = (macd_vals < signal_vals) & (prev_macd >= prev_signal)

        # Ensure no signal on the first bar due to roll wrap-around
        macd_cross_above[0] = False
        macd_cross_below[0] = False

        # Long and short signals
        long_mask = macd_cross_above & rsi_range
        short_mask = macd_cross_below & rsi_range

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals
