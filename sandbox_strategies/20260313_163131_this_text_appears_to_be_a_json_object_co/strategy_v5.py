from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='shibusdc_bollinger_adx_rsi_rev')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'bollinger', 'atr', 'adx']

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
                max_val=6.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'adx_threshold': ParameterSpec(
                name='adx_threshold',
                min_val=15,
                max_val=40,
                default=25,
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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        signals.iloc[:warmup] = 0.0

        rsi = np.nan_to_num(indicators['rsi'])
        bollinger = indicators['bollinger']
        adx = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        long_mask = (close > indicators['bollinger']["upper"]) & (rsi > params["rsi_oversold"]) & (indicators['adx']["adx"] > params["rsi_period"])
        short_mask = (close < indicators['bollinger']["lower"]) & (rsi < params["rsi_overbought"]) & (indicators['adx']["adx"] > params["rsi_period"])

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based risk management
        entry_mask_long = signals == 1.0
        if np.any(entry_mask_long):
            df.loc[entry_mask_long, "bb_stop_long"] = close[entry_mask_long] - params["stop_atr_mult"] * atr[entry_mask_long]
            df.loc[entry_mask_long, "bb_tp_long"] = close[entry_mask_long] + params["tp_atr_mult"] * atr[entry_mask_long]
        else:
            df.loc[entry_mask_long, "bb_stop_long"] = np.nan
            df.loc[entry_mask_long, "bb_tp_long"] = np.nan
        signals.iloc[:warmup] = 0.0
        return signals
