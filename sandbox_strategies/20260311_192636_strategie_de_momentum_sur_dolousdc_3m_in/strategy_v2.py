from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_ema_p_slope_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'adx_reversal_threshold': 20,
         'adx_trend_threshold': 25,
         'ema_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 20}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=10,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=50,
                default=14,
                param_type='int',
                step=1,
            ),
            'adx_trend_threshold': ParameterSpec(
                name='adx_trend_threshold',
                min_val=10,
                max_val=90,
                default=25,
                param_type='int',
                step=1,
            ),
            'adx_reversal_threshold': ParameterSpec(
                name='adx_reversal_threshold',
                min_val=0,
                max_val=40,
                default=20,
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
        # Config
        window = 21
        default_params = {"window": window, "leverage": 1.0}

        # Calculate indicators
        ema_slopes = indicators['ema']
        adx_values = indicators['adx']['adx']
        atr_values = indicators['atr']

        # Generate signals
        long_condition = (ema_slopes > 0) & (adx_values > 25)
        short_condition = (ema_slopes < 0) & (adx_values > 25)

        signals[long_condition] = 1.0
        signals[short_condition] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals
