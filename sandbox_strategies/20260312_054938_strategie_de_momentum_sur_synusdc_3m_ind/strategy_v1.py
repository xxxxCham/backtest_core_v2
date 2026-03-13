from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_ema_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'ema_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=5,
                max_val=50,
                default=20,
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
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=1,
                param_type='int',
                step=1,
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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Warmup period
        signals.iloc[:warmup] = 0.0

        # Get EMA and ATR values
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Calculate momentum and EMA difference
        ema_diff = close - ema
        prev_ema_diff = np.roll(ema_diff, 1)
        prev_ema_diff[0] = 0.0  # Pad first value

        # Long signals based on positive momentum crossing above EMA
        long_condition = (ema_diff > 0) & (ema_diff > prev_ema_diff)
        long_mask = long_condition

        # Calculate stop and take-profit levels for long positions
        stop_level = close - params["stop_atr_mult"] * atr
        tp_level = close + params["tp_atr_mult"] * atr

        # Apply risk management values only on entry bars
        entry_mask = long_mask.copy()
        df.loc[entry_mask, "bb_stop_long"] = stop_level[entry_mask]
        df.loc[entry_mask, "bb_tp_long"] = tp_level[entry_mask]

        # Set signals
        signals[long_mask] = 1.0
        signals.iloc[:warmup] = 0.0
        return signals
