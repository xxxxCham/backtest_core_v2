from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_rsi_adx_momentum')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'bollinger', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 2.5,
         'tp_atr_mult': 4.5,
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
                min_val=1.0,
                max_val=5.0,
                default=2.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=6.0,
                default=4.5,
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

        close = np.nan_to_num(df["close"])
        bollinger = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        adx = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        # Long entry
        long_mask = (close > indicators['bollinger']["upper"]) & (rsi > params["rsi_oversold"]) & (indicators['adx']["adx"] > params["rsi_period"])

        # Short entry
        short_mask = (close < indicators['bollinger']["lower"]) & (rsi < params["rsi_overbought"]) & (indicators['adx']["adx"] > params["rsi_period"])

        # Exit conditions
        exit_mask = (close > indicators['bollinger']["middle"]) | (indicators['adx']["adx"] < 20)

        # Combine entry and exit conditions
        long_signals = 1.0
        short_signals = -1.0
        flat_signals = 0.0

        signals[long_mask & ~exit_mask] = long_signals
        signals[short_mask & ~exit_mask] = short_signals
        signals[exit_mask] = 0.0

        # ATR-based stop loss and take profit
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        entry_mask_long = signals == 1.0
        entry_mask_short = signals == -1.0

        df.loc[entry_mask_long, "bb_stop_long"] = close[entry_mask_long] - stop_atr_mult * atr[entry_mask_long]
        df.loc[entry_mask_long, "bb_tp_long"] = close[entry_mask_long] + tp_atr_mult * atr[entry_mask_long]
        signals.iloc[:warmup] = 0.0
        return signals
