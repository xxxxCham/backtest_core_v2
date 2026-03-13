from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_slope_momentum')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'ema_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 20}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=5,
                max_val=50,
                default=20,
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
                max_val=6.0,
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
        # Boolean masks initialization
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Wrap indicator arrays
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Compute EMA slope and its acceleration
        ema_slope = np.insert(np.diff(ema), 0, 0.0)
        ema_slope_diff = np.insert(np.diff(ema_slope), 0, 0.0)

        # Long entry: positive slope accelerating
        long_mask = (ema_slope > 0) & (ema_slope_diff > 0)
        # Short entry: negative slope accelerating
        short_mask = (ema_slope < 0) & (ema_slope_diff < 0)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions: slope crosses zero opposite direction
        prev_slope = np.roll(ema_slope, 1)
        prev_slope[0] = np.nan
        cross_up = (ema_slope > 0) & (prev_slope <= 0)
        cross_down = (ema_slope < 0) & (prev_slope >= 0)

        # For long positions, exit when slope turns negative
        exit_long_mask = cross_down
        # For short positions, exit when slope turns positive
        exit_short_mask = cross_up

        # Set flat signals on exit bars
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Prepare SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR-based stop and target levels
        stop_mult = params["stop_atr_mult"]
        tp_mult = params["tp_atr_mult"]

        long_entry = signals == 1.0
        short_entry = signals == -1.0

        df.loc[long_entry, "bb_stop_long"] = close[long_entry] - stop_mult * atr[long_entry]
        df.loc[long_entry, "bb_tp_long"] = close[long_entry] + tp_mult * atr[long_entry]
        df.loc[short_entry, "bb_stop_short"] = close[short_entry] + stop_mult * atr[short_entry]
        df.loc[short_entry, "bb_tp_short"] = close[short_entry] - tp_mult * atr[short_entry]
        signals.iloc[:warmup] = 0.0
        return signals
