from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_adx_breakout_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'momentum']

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
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        # LONG intent: close > indicators['donchian']['upper'] AND adx > 25 AND momentum > 100
        # SHORT intent: close < indicators['donchian']['lower'] AND adx > 25 AND momentum < -100

        close = df['close']
        indicators['donchian']['upper'] = indicators['donchian']['upper']
        indicators['donchian']['lower'] = indicators['donchian']['lower']

        prev_upper = np.roll(indicators['donchian']['upper'], 1)
        prev_lower = np.roll(indicators['donchian']['lower'], 1)

        long_condition1 = close > indicators['donchian']['upper']
        long_condition2 = indicators['adx']['adx'] > 25
        long_condition3 = indicators['momentum'] > 100

        short_condition1 = close < indicators['donchian']['lower']
        short_condition2 = indicators['adx']['adx'] > 25
        short_condition3 = indicators['momentum'] < -100

        # Combine conditions using bitwise AND
        long_signals = long_condition1 & long_condition2 & long_condition3
        short_signals = short_condition1 & short_condition2 & short_condition3

        # Assign signals based on the conditions
        signals[long_signals] = 1.0
        signals[short_signals] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals
