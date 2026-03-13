from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_donchian_adx_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 2.75, 'tp_atr_mult': 4.5, 'warmup': 50}

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
                max_val=8.0,
                default=4.5,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=10,
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
        # Get Donchian upper and lower bands
        indicators['donchian']['upper'] = indicators['donchian']['upper']
        indicators['donchian']['lower'] = indicators['donchian']['lower']

        # Use shifted (previous period) Donchian bands for breakout detection
        prev_upper = np.roll(indicators['donchian']['upper'], 1)
        prev_lower = np.roll(indicators['donchian']['lower'], 1)

        # Get ADX values
        adx_values = indicators['adx']['adx']
        indicators['adx']['plus_di'] = indicators['adx']['plus_di']
        indicators['adx']['minus_di'] = indicators['adx']['minus_di']

        # LONG signal conditions
        long_condition = (df['close'] > prev_upper) & (adx_values > 25)
        signals[long_condition] = 1.0

        # SHORT signal conditions
        short_condition = (df['close'] < prev_lower) & (adx_values > 25)
        signals[short_condition] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals
