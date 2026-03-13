from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_stoch_atr_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'stochastic', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_min': 0.01,
         'leverage': 1,
         'stoch_overbought': 80,
         'stoch_oversold': 20,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stoch_overbought': ParameterSpec(
                name='stoch_overbought',
                min_val=70,
                max_val=90,
                default=80,
                param_type='int',
                step=1,
            ),
            'stoch_oversold': ParameterSpec(
                name='stoch_oversold',
                min_val=10,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
            ),
            'atr_min': ParameterSpec(
                name='atr_min',
                min_val=0.001,
                max_val=0.05,
                default=0.01,
                param_type='float',
                step=0.1,
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
                max_val=5.0,
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

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        signals.iloc[:warmup] = 0.0

        # Extract indicator arrays
        bb = indicators['bollinger']
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        stoch = indicators['stochastic']
        k = np.nan_to_num(stoch["stoch_k"])

        atr = np.nan_to_num(indicators['atr'])

        close = df["close"].values

        stoch_overbought = float(params.get("stoch_overbought", 80))
        stoch_oversold = float(params.get("stoch_oversold", 20))
        atr_min = float(params.get("atr_min", 0.01))
        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        # Long breakout conditions
        long_cond = (close > upper) & (k > stoch_overbought) & (atr > atr_min)
        long_mask = long_cond

        # Short breakout conditions
        short_cond = (close < lower) & (k < stoch_oversold) & (atr > atr_min)
        short_mask = short_cond

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Prepare SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entry SL/TP
        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]

        # Short entry SL/TP
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
