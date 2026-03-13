from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='macd_atr_momentum_short')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
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
                max_val=6.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'macd_fast': ParameterSpec(
                name='macd_fast',
                min_val=5,
                max_val=30,
                default=12,
                param_type='int',
                step=1,
            ),
            'macd_slow': ParameterSpec(
                name='macd_slow',
                min_val=20,
                max_val=50,
                default=26,
                param_type='int',
                step=1,
            ),
            'macd_signal': ParameterSpec(
                name='macd_signal',
                min_val=5,
                max_val=20,
                default=9,
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
        # Extract MACD components
        macd_vals = indicators['macd']['macd']
        signal_vals = indicators['macd']['signal']
        hist_vals = indicators['macd']['histogram']

        # Long and short entry conditions
        long_cond = (macd_vals > signal_vals) & (hist_vals > 0)
        short_cond = (macd_vals < signal_vals) & (hist_vals < 0)

        # Assign signals
        signals[long_cond] = 1.0
        signals[short_cond] = -1.0

        # ATR-based stop and take‑profit (example: 2×ATR)
        atr_vals = indicators['atr']
        df['bb_stop_long'] = np.nan
        df['bb_tp_long'] = np.nan
        df['bb_stop_short'] = np.nan
        df['bb_tp_short'] = np.nan

        df.loc[signals == 1.0, 'bb_stop_long'] = df['close'] - 2 * atr_vals
        df.loc[signals == 1.0, 'bb_tp_long'] = df['close'] + 2 * atr_vals
        df.loc[signals == -1.0, 'bb_stop_short'] = df['close'] + 2 * atr_vals
        df.loc[signals == -1.0, 'bb_tp_short'] = df['close'] - 2 * atr_vals
        signals.iloc[:warmup] = 0.0
        return signals
