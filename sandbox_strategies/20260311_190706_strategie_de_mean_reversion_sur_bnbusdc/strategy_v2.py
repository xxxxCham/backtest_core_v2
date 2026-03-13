from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='improved_mean_reversion_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'bollinger', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 1.0,
         'tp_atr_mult': 2.0,
         'warmup': 100}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=7,
                max_val=20,
                default=14,
                param_type='int',
                step=1,
            ),
            'rsi_oversold': ParameterSpec(
                name='rsi_oversold',
                min_val=20,
                max_val=50,
                default=30,
                param_type='int',
                step=1,
            ),
            'rsi_overbought': ParameterSpec(
                name='rsi_overbought',
                min_val=50,
                max_val=80,
                default=70,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=2.0,
                default=1.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=4.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=50,
                max_val=300,
                default=100,
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
        def generate_signals(
                self,
                df: pd.DataFrame,
                indicators: Dict[str, Any],
                params: Dict[str, Any],
            ) -> pd.Series:
                signals = pd.Series(0.0, index=df.index, dtype=np.float64)
                n = len(df)
                long_mask = np.zeros(n, dtype=bool)
                short_mask = np.zeros(n, dtype=bool)

                warmup = int(params.get("warmup", 50))
                if warmup > 0:
                    signals[:warmup] = 0.0
                    long_mask[:warmup] = False
                    short_mask[:warmup] = False

                rsi_values = np.nan_to_num(indicators['rsi'])
                atr_values = np.nan_to_num(indicators['atr'])
                close_prices = df["close"].values

                rsi_overbought = params.get("rsi_overbought", 70)
                rsi_oversold = params.get("rsi_oversold", 30)

                long_condition = (rsi_values > rsi_overbought) & (close_prices > indicators['bollinger']["upper"])
                short_condition = (rsi_values < rsi_oversold) & (close_prices < indicators['bollinger']["lower"])

                long_mask[long_condition] = True
                short_mask[short_condition] = True

                signals[long_mask] = 1.0
                signals[short_mask] = -1.0

                entry_mask_long = long_mask.copy()
                entry_mask_long &= ~long_condition
                entry_mask_long &= (signals[long_mask] == 0.0)

                atr_multiplier = params.get("stop_atr_mult", 1.0)
                tp_atr_mult = params.get("tp_atr_mult", 2.0)

                df.loc[entry_mask_long, "sl_level"] = close_prices[entry_mask_long] - atr_values[entry_mask_long] * atr_multiplier
                df.loc[entry_mask_long, "tp_level"] = close_prices[entry_mask_long] + atr_values[entry_mask_long] * tp_atr_mult

                return signals
        signals.iloc[:warmup] = 0.0
        return signals
