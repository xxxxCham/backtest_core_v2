from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_ema_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'roc', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'ema_fast': 10,
         'ema_slow': 30,
         'leverage': 1,
         'roc_period': 12,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_fast': ParameterSpec(
                name='ema_fast',
                min_val=5,
                max_val=20,
                default=10,
                param_type='int',
                step=1,
            ),
            'ema_slow': ParameterSpec(
                name='ema_slow',
                min_val=20,
                max_val=50,
                default=30,
                param_type='int',
                step=1,
            ),
            'roc_period': ParameterSpec(
                name='roc_period',
                min_val=5,
                max_val=30,
                default=12,
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
        ema = indicators['ema']
        roc = indicators['roc']
        long_condition = (roc > 0) & (ema[0] > ema[1])
        short_condition = (roc < 0) & (ema[0] < ema[1])

        signals[long_condition] = 1.0
        signals[short_condition] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals