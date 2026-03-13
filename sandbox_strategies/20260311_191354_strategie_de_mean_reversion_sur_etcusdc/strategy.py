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
                signals.iloc[:params["warmup"]] = 0.0
                close = df["close"].values
                atr = np.nan_to_num(indicators['atr'])
                indicators['bollinger']['upper'] = np.nan_to_num(indicators['bollinger']["upper"])
                indicators['bollinger']['lower'] = np.nan_to_num(indicators['bollinger']["lower"])
                rsi = np.nan_to_num(indicators['rsi'])
                ema = np.nan_to_num(indicators['ema'])

                price_above_upper = close > indicators['bollinger']['upper']
                price_below_lower = close < indicators['bollinger']['lower']

                short_mask = price_above_upper & (rsi < 70)
                long_mask = price_below_lower & (rsi > 30)

                signals[short_mask] = -1.0
                signals[long_mask] = 1.0

                atr_values = np.zeros(n, dtype=float)
                entry_mask = (signals == 1.0) | (signals == -1.0)
                atr_values[entry_mask] = atr[entry_mask]

                df.loc[:, "sl_level"] = np.nan
                df.loc[:, "tp_level"] = np.nan
                df.loc[signals == -1.0, "sl_level"] = close[signals == -1.0] + params["stop_atr_mult"] * atr_values[signals == -1.0]
                df.loc[signals == -1.0, "tp_level"] = close[signals == -1.0] - params["take_profit_atr_mult"] * atr_values[signals == -1.0]
                df.loc[signals == 1.0, "sl_level"] = close[signals == 1.0] - params["stop_atr_mult"] * atr_values[signals == 1.0]
                df.loc[signals == 1.0, "tp_level"] = close[signals == 1.0] + params["take_profit_atr_mult"] * atr_values[signals == 1.0]

                return signals
        signals.iloc[:warmup] = 0.0
        return signals
