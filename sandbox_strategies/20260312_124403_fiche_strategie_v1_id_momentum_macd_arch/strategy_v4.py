from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_rsi_adx_trend')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'leverage': 1,
            'rsi_period': 14,
            'stop_atr_mult': 1.5,
            'tp_atr_mult': 3.0,
            'warmup': 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=50,
                default=14,
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
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=10.0,
                default=3.0,
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

    def generate_signals(
        self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]
    ) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Ensure masks are initialized
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Pull indicator arrays directly (they are numpy arrays)
        close = df['close'].values
        boll_upper = indicators['bollinger']['upper']
        boll_lower = indicators['bollinger']['lower']
        rsi = indicators['rsi']
        adx = indicators['adx']['adx']

        # Long and short entry conditions
        long_mask = (close > boll_upper) & (rsi > 50) & (adx > 25)
        short_mask = (close < boll_lower) & (rsi < 50) & (adx > 25)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based stop and take profit
        atr = indicators['atr']
        df.loc[long_mask, 'bb_stop_long'] = close[long_mask] - 2 * atr[long_mask]
        df.loc[long_mask, 'bb_tp_long'] = close[long_mask] + 2 * atr[long_mask]
        df.loc[short_mask, 'bb_stop_short'] = close[short_mask] + 2 * atr[short_mask]
        df.loc[short_mask, 'bb_tp_short'] = close[short_mask] - 2 * atr[short_mask]

        # Apply warmup period
        signals.iloc[:warmup] = 0.0
        return signals