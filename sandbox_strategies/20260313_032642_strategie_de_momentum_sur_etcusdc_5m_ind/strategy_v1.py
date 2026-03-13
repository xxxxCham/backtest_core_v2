from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_macd_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'ema_period': 200,
         'fast_period': 12,
         'leverage': 1,
         'signal_period': 9,
         'slow_period': 26,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'fast_period': ParameterSpec(
                name='fast_period',
                min_val=5,
                max_val=50,
                default=12,
                param_type='int',
                step=1,
            ),
            'slow_period': ParameterSpec(
                name='slow_period',
                min_val=20,
                max_val=100,
                default=26,
                param_type='int',
                step=1,
            ),
            'signal_period': ParameterSpec(
                name='signal_period',
                min_val=5,
                max_val=50,
                default=9,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.5,
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

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        # Generate LONG signals
        long_entry = (indicators['macd']['macd'] > indicators['macd']['signal']) & (close > ema.ema_200)
        signals[long_entry] = 1.0

        # Generate SHORT signals
        short_entry = (indicators['macd']['macd'] < indicators['macd']['signal']) & (close < ema.ema_200) 
        signals[short_entry] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals
