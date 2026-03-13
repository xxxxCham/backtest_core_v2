from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_sma_atr_trend')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'sma', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.0, 'tp_atr_mult': 2.0, 'warmup': 30}
    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=3.0,
                default=1.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.0,
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
        ema_arr = indicators['ema']
        sma_arr = indicators['sma']
        close_arr = df['close'].values

        # EMA crosses above SMA and close > EMA
        cross_up = (ema_arr > sma_arr) & (np.roll(ema_arr, 1) <= np.roll(sma_arr, 1))
        long_cond = cross_up & (close_arr > ema_arr)

        # EMA crosses below SMA and close < EMA
        cross_down = (ema_arr < sma_arr) & (np.roll(ema_arr, 1) >= np.roll(sma_arr, 1))
        short_cond = cross_down & (close_arr < ema_arr)

        signals[long_cond] = 1.0
        signals[short_cond] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals
