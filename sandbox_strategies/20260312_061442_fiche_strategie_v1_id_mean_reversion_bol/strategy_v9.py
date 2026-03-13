from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_rsi_reversion')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'capital': 10000.0,
         'fees': 10.0,
         'leverage': 1,
         'slippage': 5.0,
         'stop_atr_mult': 2.25,
         'tp_atr_mult': 4.5,
         'warmup': 50}
    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'capital': ParameterSpec(
                name='capital',
                min_val=1000,
                max_val=100000,
                default=10000.0,
                param_type='float',
                step=0.1,
            ),
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=10,
                default=1,
                param_type='int',
                step=1,
            ),
            'fees': ParameterSpec(
                name='fees',
                min_val=5,
                max_val=20,
                default=10.0,
                param_type='float',
                step=0.1,
            ),
            'slippage': ParameterSpec(
                name='slippage',
                min_val=1,
                max_val=10,
                default=5.0,
                param_type='float',
                step=0.1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=2.25,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=4.5,
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
        
        close = df['close']  # Define close from the DataFrame
        rsi = indicators['rsi']  # Access RSI values
        
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        # LONG: close < indicators['bollinger']['lower'] AND rsi < 25
        long_entry = (close < indicators['bollinger']['lower']) & (rsi < 25)
        signals[long_entry] = 1.0

        # SHORT: close > indicators['bollinger']['upper'] AND rsi > 80
        short_entry = (close > indicators['bollinger']['upper']) & (rsi > 80)
        signals[short_entry] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals