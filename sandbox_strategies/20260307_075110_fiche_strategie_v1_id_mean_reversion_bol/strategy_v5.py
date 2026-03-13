from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_adx')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'bollinger', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 4.0,
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
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=10.0,
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

        bollinger = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        adx = indicators['adx']

        close = df["close"].values

        long_condition = (close > indicators['bollinger']["upper"]) & (rsi > params["rsi_oversold"]) & (indicators['adx']["adx"] > 25)
        short_condition = (close < indicators['bollinger']["lower"]) & (rsi < params["rsi_overbought"]) & (indicators['adx']["adx"] > 25)

        long_mask = long_condition
        short_mask = short_condition

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based stop-loss and take-profit
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        entry_mask_long = signals == 1.0
        entry_mask_short = signals == -1.0

        df.loc[entry_mask_long, "bb_stop_long"] = close[entry_mask_long] - stop_atr_mult * atr[entry_mask_long]
        df.loc[entry_mask_long, "bb_tp_long"] = close[entry_mask_long] + tp_atr_mult * atr[entry_mask_long]

        df.loc[entry_mask_short, "bb_stop_short"] = close[entry_mask_short] + stop_atr_mult * atr[entry_mask_short]
        df.loc[entry_mask_short, "bb_tp_short"] = close[entry_mask_short] - tp_atr_mult * atr[entry_mask_short]
        signals.iloc[:warmup] = 0.0
        return signals
