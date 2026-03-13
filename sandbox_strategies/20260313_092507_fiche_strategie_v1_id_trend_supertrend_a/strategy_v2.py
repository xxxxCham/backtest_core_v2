from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_supertrend_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'ema_period': 21,
         'leverage': 1,
         'stop_atr_mult': 3.0,
         'tp_atr_mult': 3.5,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=10,
                max_val=50,
                default=21,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=6.0,
                default=3.5,
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
        close = df['close'].values
        ema = indicators['ema']
        atr = indicators['atr']
        long_condition = (close > ema) & (np.roll(close, 1) <= np.roll(ema, 1)) & (indicators['adx']["adx"] > 25) & (atr > np.roll(atr, 1))
        short_condition = (close < ema) & (np.roll(close, 1) >= np.roll(ema, 1)) & (indicators['adx']["adx"] > 25) & (atr > np.roll(atr, 1))

        signals[long_condition] = 1.0
        signals[short_condition] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals