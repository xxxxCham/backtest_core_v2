from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='obv_ema_atr_volatility_v3')

    @property
    def required_indicators(self) -> List[str]:
        return ['obv', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'ema_period': 20,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 5.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=10,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=10,
                max_val=20,
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
        # Boolean masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Indicator arrays
        close = df["close"].values
        obv = np.nan_to_num(indicators['obv'])
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])

        # Shifted arrays for comparisons
        obv_prev = np.roll(obv, 1); obv_prev[0] = np.nan
        obv_prev2 = np.roll(obv, 2); obv_prev2[0:2] = np.nan
        atr_prev = np.roll(atr, 1); atr_prev[0] = np.nan

        # Cross down helper for exit
        def cross_down(x, y):
            prev_x = np.roll(x, 1); prev_x[0] = np.nan
            prev_y = np.roll(y, 1); prev_y[0] = np.nan
            return (x < y) & (prev_x >= prev_y)

        # Long entry conditions
        long_cond = (
            (close > ema)
            & (obv > obv_prev)
            & ((obv - obv_prev) > 0.5 * atr)
            & (atr > atr_prev)
        )
        long_mask = long_cond

        # Short entry conditions
        short_cond = (
            (close < ema)
            & (obv < obv_prev)
            & ((obv_prev - obv) > 0.5 * atr)
            & (atr > atr_prev)
        )
        short_mask = short_cond

        # Exit conditions
        exit_cond = (
            cross_down(close, ema)
            | (obv_prev < obv_prev2)
            | (atr < atr_prev)
        )

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_cond] = 0.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 5.0))

        # Long entries
        long_entries = signals == 1.0
        df.loc[long_entries, "bb_stop_long"] = close[long_entries] - stop_atr_mult * atr[long_entries]
        df.loc[long_entries, "bb_tp_long"] = close[long_entries] + tp_atr_mult * atr[long_entries]

        # Short entries
        short_entries = signals == -1.0
        df.loc[short_entries, "bb_stop_short"] = close[short_entries] + stop_atr_mult * atr[short_entries]
        df.loc[short_entries, "bb_tp_short"] = close[short_entries] - tp_atr_mult * atr[short_entries]
        signals.iloc[:warmup] = 0.0
        return signals
