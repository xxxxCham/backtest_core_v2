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
        return ['atr', 'rsi']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

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
                max_val=2.5,
                default=1.5,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=20,
                max_val=200,
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
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        if warmup > 0:
            signals.iloc[:warmup] = 0.0

        long_condition = (close > np.roll(close, 1)) & (rsi > params["rsi_overbought"])
        short_condition = (close < np.roll(close, 1)) & (rsi < params["rsi_oversold"])

        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        prev_long = np.zeros(n, dtype=bool)
        prev_short = np.zeros(n, dtype=bool)

        long_mask[long_condition] = True
        short_mask[short_condition] = True

        if n > 0:
            long_mask[0] = False
            short_mask[0] = False

            long_mask = long_mask & ~prev_long
            short_mask = short_mask & ~prev_short

            prev_long = long_mask.copy()
            prev_short = short_mask.copy()

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        entry_mask_long = (signals == 1.0)
        entry_mask_short = (signals == -1.0)

        df.loc[entry_mask_long, "sl_level"] = close[entry_mask_long] - params["stop_atr_mult"] * atr[entry_mask_long]
        df.loc[entry_mask_long, "tp_level"] = close[entry_mask_long] + params["tp_atr_mult"] * atr[entry_mask_long]

        return signals.values
        signals.iloc[:warmup] = 0.0
        return signals
