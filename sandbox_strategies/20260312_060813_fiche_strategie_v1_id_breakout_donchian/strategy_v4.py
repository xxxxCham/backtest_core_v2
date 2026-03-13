from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_adx_breakout_v4')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 2, 'stop_atr_mult': 1.75, 'tp_atr_mult': 3.5, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=2,
                param_type='int',
                step=1,
            ),
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
            'warmup': ParameterSpec(
                name='warmup',
                min_val=0,
                max_val=100,
                default=50,
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
        
        # LONG SIGNALS
        # Donchian Breakout Long: Close > previous upper band and ADX > 25
        prev_upper = np.roll(indicators['donchian']["upper"], 1)
        close_prices = df['close'].values
        long_signals = (close_prices > prev_upper) & (indicators['adx']['adx'] > 25)

        # SHORT SIGNALS
        # Donchian Breakout Short: Close < previous lower band and ADX > 25
        prev_lower = np.roll(indicators['donchian']["lower"], 1)
        short_signals = (close_prices < prev_lower) & (indicators['adx']['adx'] > 25)

        # Assign signals
        signals[long_signals] = 1.0
        signals[short_signals] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals