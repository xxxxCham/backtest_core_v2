from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_macd_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'macd', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'donchian_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'donchian_period': ParameterSpec(
                name='donchian_period',
                min_val=10,
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
        close = df['close'].values
        macd = indicators['macd']
        signals[close > indicators['donchian']["upper"]] = 1.0
        signals[close < indicators['donchian']["lower"]] = -1.0
        signals[macd['macd'] > indicators['macd']["signal"]] = 1.0
        signals[macd['macd'] < indicators['macd']["signal"]] = -1.0
        signals[(close > indicators['donchian']["upper"]) & (indicators['macd']["macd"] > indicators['macd']["signal"])] = 1.0
        signals[(close < indicators['donchian']["lower"]) & (indicators['macd']["macd"] < indicators['macd']["signal"])] = -1.0
        signals[(close > np.roll(indicators['donchian']["upper"], 1)) & (indicators['macd']["macd"] > indicators['macd']["signal"])] = 1.0
        signals[(close < np.roll(indicators['donchian']["lower"], 1)) & (indicators['macd']["macd"] < indicators['macd']["signal"])] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals