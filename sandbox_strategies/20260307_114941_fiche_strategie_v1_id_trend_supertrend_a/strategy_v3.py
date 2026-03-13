from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_supertrend_adx_v3')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 22,
         'atr_period': 6,
         'leverage': 1,
         'multiplier': 3.0,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=3,
                max_val=20,
                default=6,
                param_type='int',
                step=1,
            ),
            'multiplier': ParameterSpec(
                name='multiplier',
                min_val=1.5,
                max_val=4.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=10,
                max_val=30,
                default=22,
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
                min_val=2.0,
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

        supertrend = indicators['supertrend']
        adx = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Long signal: Supertrend direction is up AND ADX strength is above 25
        long_mask = (indicators['supertrend']["direction"] == 1) & (indicators['adx']["adx"] > 25)

        # Short signal: Supertrend direction is down AND ADX strength is above 25
        short_mask = (indicators['supertrend']["direction"] == -1) & (indicators['adx']["adx"] > 25)

        # Exit signal: Supertrend direction changes OR ADX strength falls below 20
        direction_change = np.roll(indicators['supertrend']["direction"], 1)
        direction_change[0] = 0  # Assign a valid value to avoid NaN
        exit_mask = (indicators['supertrend']["direction"] != direction_change) | (indicators['adx']["adx"] < 20)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # ATR-based stop-loss and take-profit
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Initialize SL/TP columns with NaN (no level = no stop)
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # On entry signal bars only, compute ATR-based levels:
        entry_long_mask = signals == 1.0
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        entry_short_mask = signals == -1.0
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals