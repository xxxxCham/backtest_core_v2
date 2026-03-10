from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='macd_rsi_atr_momentum')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'leverage': 1,
            'macd_fast': 8,
            'macd_signal': 10,
            'macd_slow': 35,
            'rsi_period': 14,
            'stop_atr_mult': 1.5,
            'tp_atr_mult': 4.0,
            'warmup': 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'macd_fast': ParameterSpec(
                name='macd_fast',
                min_val=5,
                max_val=15,
                default=8,
                param_type='int',
                step=1,
            ),
            'macd_slow': ParameterSpec(
                name='macd_slow',
                min_val=20,
                max_val=50,
                default=35,
                param_type='int',
                step=1,
            ),
            'macd_signal': ParameterSpec(
                name='macd_signal',
                min_val=5,
                max_val=15,
                default=10,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=3.0,
                default=1.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=6.0,
                default=4.0,
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
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any],
    ) -> pd.Series:
        # Ensure required default parameters are present
        params.setdefault('leverage', 1)

        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Extract indicator arrays
        macd_vals = indicators['macd']['macd']
        macd_sig = indicators['macd']['signal']
        rsi_vals = indicators['rsi']
        atr_vals = indicators['atr']

        # MACD crossovers
        macd_cross_up = (macd_vals > macd_sig) & (
            np.roll(macd_vals, 1) <= np.roll(macd_sig, 1)
        )
        macd_cross_down = (macd_vals < macd_sig) & (
            np.roll(macd_vals, 1) >= np.roll(macd_sig, 1)
        )
        macd_cross_up[0] = False
        macd_cross_down[0] = False

        # Entry conditions
        long_mask = macd_cross_up & (rsi_vals > 55) & (rsi_vals < 80)
        short_mask = macd_cross_down & (rsi_vals < 45) & (rsi_vals > 20)

        # Assign signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Risk management – ATR based stops / take‑profits
        stop_mult = float(params.get('stop_atr_mult', 1.5))
        tp_mult = float(params.get('tp_atr_mult', 4.0))

        df.loc[long_mask, 'bb_stop_long'] = df['close'] - atr_vals * stop_mult
        df.loc[long_mask, 'bb_tp_long'] = df['close'] + atr_vals * tp_mult
        df.loc[short_mask, 'bb_stop_short'] = df['close'] + atr_vals * stop_mult
        df.loc[short_mask, 'bb_tp_short'] = df['close'] - atr_vals * tp_mult

        # Zero out signals during warm‑up period
        signals.iloc[:warmup] = 0.0

        return signals