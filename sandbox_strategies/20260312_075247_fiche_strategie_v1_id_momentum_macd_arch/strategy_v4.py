from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_trend_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 2.5, 'tp_atr_mult': 6.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=2.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=10.0,
                default=6.0,
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
        ema20 = indicators['ema']
        ema50 = indicators['ema']
        atr = indicators['atr']

        prev_ema20 = np.roll(ema20, 1)
        prev_ema50 = np.roll(ema50, 1)

        cross_above = (ema20 > ema50) & (prev_ema20 <= prev_ema50)
        cross_below = (ema20 < ema50) & (prev_ema20 >= prev_ema50)

        close = df['close'].values

        long_cond = cross_above & (close > ema20) & (atr > 0.0005)
        short_cond = cross_below & (close < ema20) & (atr > 0.0005)

        signals[long_cond] = 1.0
        signals[short_cond] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals
