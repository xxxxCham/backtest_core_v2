from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_adx_rsi_breakout_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'donchian_period': 20,
         'leverage': 1,
         'rsi_period': 14,
         'stop_atr_mult': 2.5,
         'tp_atr_mult': 5.5,
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
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
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
                min_val=1.0,
                max_val=4.0,
                default=2.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=3.0,
                max_val=10.0,
                default=5.5,
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

        close = df["close"].values
        atr = np.nan_to_num(indicators['atr'])
        rsi = np.nan_to_num(indicators['rsi'])
        adx_val = np.nan_to_num(indicators['adx']["adx"])

        donch = indicators['donchian']
        upper = np.nan_to_num(donch["upper"])
        middle = np.nan_to_num(donch["middle"])
        lower = np.nan_to_num(donch["lower"])

        # Helper for cross_any
        def cross_any(x, y):
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return (x > y) & (prev_x <= prev_y) | (x < y) & (prev_x >= prev_y)

        # Entry conditions
        long_mask = (close > upper) & (adx_val > 20) & (rsi < 70)
        short_mask = (close < lower) & (adx_val > 20) & (rsi > 30)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        exit_mask = cross_any(close, middle) | (adx_val < 15)
        signals[exit_mask] = 0.0

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_mult = float(params.get("stop_atr_mult", 2.5))
        tp_mult = float(params.get("tp_atr_mult", 5.5))

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
