from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bb_macd_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'macd', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'bollinger_period': 20,
         'bollinger_std': 2,
         'leverage': 1,
         'macd_fast': 12,
         'macd_signal': 9,
         'macd_slow': 26,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'bollinger_period': ParameterSpec(
                name='bollinger_period',
                min_val=10,
                max_val=50,
                default=20,
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
        # Initialize signals
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        # Get indicator values
        close = df['close']
        indicators['bollinger']['upper'] = indicators['bollinger']['upper']
        indicators['bollinger']['lower'] = indicators['bollinger']['lower']
        macd_macd = indicators['macd']['macd']
        indicators['macd']['signal'] = indicators['macd']['signal']
        atr_value = indicators['atr']

        # Long signals
        long_condition = (
            (close > indicators['bollinger']['upper']) &
            (macd_macd > indicators['macd']['signal'])
        )
        signals[long_condition] = 1.0

        # Short signals
        short_condition = (
            (close < indicators['bollinger']['lower']) &
            (macd_macd < indicators['macd']['signal'])
        )
        signals[short_condition] = -1.0

        # Set default params
        default_params = {'leverage': 1}
        signals.iloc[:warmup] = 0.0
        return signals
