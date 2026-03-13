from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='builder_strategy')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=1,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=2.0,
                default=1.5,
                param_type='float',
                step=0.1,
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
        def generate_signals():
            # Generate signal 1: sine wave with slight frequency offset
            t1 = np.linspace(0, 10, 1000)
            frequency_offset = 0.1
            signal1 = np.sin(2 * np.pi * (5 + frequency_offset) * t1)

            # Generate signal 2: cosine wave
            signal2 = np.cos(2 * np.pi * 5 * t1)

            # Compute instantaneous phase using arctan2
            instantaneous_phase1 = np.arctan2(signal1, np.cos(2 * np.pi * 5 * t1))
            instantaneous_phase2 = np.arctan2(signal2, np.cos(2 * np.pi * 5 * t1))

            # Calculate phase difference
            phase_difference = instantaneous_phase1 - instantaneous_phase2

            # Normalize phase difference to [-1, 1]
            normalized_phase = (phase_difference + np.pi) % (2 * np.pi) - np.pi

            return signal1, signal2, normalized_phase
        signals.iloc[:warmup] = 0.0
        return signals
