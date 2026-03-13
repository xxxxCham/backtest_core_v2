from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_slope_trend_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'ema_period_20': 20,
         'ema_period_50': 50,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_period_20': ParameterSpec(
                name='ema_period_20',
                min_val=5,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'ema_period_50': ParameterSpec(
                name='ema_period_50',
                min_val=20,
                max_val=100,
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

        # wrap indicator arrays
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # slope and acceleration of EMA
        ema_diff = np.insert(np.diff(ema), 0, 0.0)
        ema_slope = ema_diff
        ema_accel = np.insert(np.diff(ema_slope), 0, 0.0)

        # long conditions
        long_cond = (
            (ema_slope > 0.0)
            & (ema_accel > 0.0)
            & (close > ema)
        )
        long_mask[long_cond] = True

        # short conditions
        short_cond = (
            (ema_slope < 0.0)
            & (ema_accel < 0.0)
            & (close < ema)
        )
        short_mask[short_cond] = True

        # exit conditions: close crosses EMA
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        cross_down = (close < ema) & (prev_close >= ema)
        cross_up = (close > ema) & (prev_close <= ema)

        # apply masks to signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[cross_down | cross_up] = 0.0

        # warmup protection
        signals.iloc[:warmup] = 0.0

        # write ATR based SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = signals == 1.0
        entry_short = signals == -1.0
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
