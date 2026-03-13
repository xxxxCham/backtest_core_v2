from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_adx_ema_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'atr_period': 14,
         'donchian_period': 30,
         'ema_period': 50,
         'leverage': 1,
         'stop_atr_mult': 2.5,
         'tp_atr_mult': 5.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'donchian_period': ParameterSpec(
                name='donchian_period',
                min_val=10,
                max_val=60,
                default=30,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=10,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=10,
                max_val=200,
                default=50,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=2.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=10.0,
                default=5.0,
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

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Extract indicator arrays
        close = df["close"].values
        atr = np.nan_to_num(indicators['atr'])
        ema = np.nan_to_num(indicators['ema'])
        adx_arr = np.nan_to_num(indicators['adx']["adx"])
        donch = indicators['donchian']
        donch_upper = np.nan_to_num(donch["upper"])
        donch_lower = np.nan_to_num(donch["lower"])

        # Entry conditions
        long_mask = (close > donch_upper) & (adx_arr > 30) & (close > ema)
        short_mask = (close < donch_lower) & (adx_arr > 30) & (close < ema)

        # Exit conditions: cross below ema or adx < 20
        prev_close = np.roll(close, 1)
        prev_ema = np.roll(ema, 1)
        prev_close[0] = np.nan
        prev_ema[0] = np.nan
        cross_down = (close < ema) & (prev_close >= prev_ema)
        exit_mask = cross_down | (adx_arr < 20)

        # Assign signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_mult = params.get("stop_atr_mult", 2.5)
        tp_mult = params.get("tp_atr_mult", 5.0)

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_mult * atr[long_mask]

        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_mult * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
