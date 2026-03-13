from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_adx_breakout_v3')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 2, 'stop_atr_mult': 1.75, 'tp_atr_mult': 3.5, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=3.5,
                param_type='float',
                step=0.1,
            ),
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=2,
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
        
        # Extract close prices
        close = df['close'].values
        
        # Get Donchian indicators
        donchian_upper = indicators['donchian']['upper']
        donchian_lower = indicators['donchian']['lower']
        prev_upper = np.roll(donchian_upper, 1)
        prev_lower = np.roll(donchian_lower, 1)
        
        # LONG SIGNALS
        signals[close > prev_upper] = 1.0
        
        # SHORT SIGNALS
        signals[close < prev_lower] = -1.0
        
        # Set warmup period to 0
        signals.iloc[:warmup] = 0.0
        
        return signals