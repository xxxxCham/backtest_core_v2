from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_donchian_adx_4')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'capital': 10000,
         'fees': 10,
         'leverage': 1,
         'slippage': 5,
         'stop_atr_mult': 2.75,
         'tp_atr_mult': 4.5,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=5.0,
                default=2.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=6.0,
                default=4.5,
                param_type='float',
                step=0.1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=50,
                default=19,
                param_type='int',
                step=1,
            ),
            'donchian_period': ParameterSpec(
                name='donchian_period',
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
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        # LONG SIGNALS
        long_condition_1 = df['close'] > np.roll(indicators['donchian']["upper"], 1)
        long_condition_2 = indicators['adx']['adx'] > 25

        long_signals = long_condition_1 & long_condition_2

        # SHORT SIGNALS
        short_condition_1 = df['close'] < np.roll(indicators['donchian']["lower"], 1)
        short_condition_2 = indicators['adx']['adx'] > 25

        short_signals = short_condition_1 & short_condition_2

        # ASSIGN SIGNALS
        signals[long_signals] = 1.0
        signals[short_signals] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals
