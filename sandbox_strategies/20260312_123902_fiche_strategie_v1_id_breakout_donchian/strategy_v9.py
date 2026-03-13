from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_adx_breakout_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 4.5, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
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
                max_val=6.0,
                default=4.5,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=10,
                max_val=100,
                default=50,
                param_type='int',
                step=10,
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
        # Boolean masks for long / short
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Extract indicator arrays
        close = df["close"].values
        dc = indicators['donchian']
        upper = np.nan_to_num(dc["upper"])
        lower = np.nan_to_num(dc["lower"])
        middle = np.nan_to_num(dc["middle"])
        adx_arr = np.nan_to_num(indicators['adx']["adx"])
        atr_arr = np.nan_to_num(indicators['atr'])

        # Helper cross functions
        def cross_up(x, y):
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return (x > y) & (prev_x <= prev_y)

        def cross_down(x, y):
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return (x < y) & (prev_x >= prev_y)

        def cross_any(x, y):
            return cross_up(x, y) | cross_down(x, y)

        # Entry conditions
        long_mask = cross_up(close, upper) & (adx_arr > 20)
        short_mask = cross_down(close, lower) & (adx_arr > 20)

        # Exit conditions
        exit_mask = cross_any(close, middle) | (adx_arr < 15)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # If exit condition triggered, flatten position
        signals[exit_mask] = 0.0

        # ATR based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 4.5)

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr_arr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr_arr[long_mask]

        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr_arr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr_arr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
