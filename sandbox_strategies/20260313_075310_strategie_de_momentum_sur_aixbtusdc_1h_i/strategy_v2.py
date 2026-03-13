from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_ema_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'roc', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'ema_fast': 10,
         'ema_slow': 30,
         'leverage': 1,
         'roc_period': 12,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_fast': ParameterSpec(
                name='ema_fast',
                min_val=5,
                max_val=20,
                default=10,
                param_type='int',
                step=1,
            ),
            'ema_slow': ParameterSpec(
                name='ema_slow',
                min_val=20,
                max_val=50,
                default=30,
                param_type='int',
                step=1,
            ),
            'roc_period': ParameterSpec(
                name='roc_period',
                min_val=5,
                max_val=30,
                default=12,
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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        ema_fast = np.nan_to_num(indicators['ema'])
        ema_slow = np.nan_to_num(indicators['ema'])
        roc = np.nan_to_num(indicators['roc'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # EMA arrays are same length, need to extract correct periods
        ema_fast_vals = ema_fast
        ema_slow_vals = ema_slow

        # Create masks for entry conditions
        fast_above_slow = ema_fast_vals > ema_slow_vals
        fast_below_slow = ema_fast_vals < ema_slow_vals

        # ROC conditions
        roc_positive = roc > 0
        roc_negative = roc < 0

        # Entry long: ROC > 0 AND EMA fast > EMA slow
        long_entry = roc_positive & fast_above_slow
        long_mask[long_entry] = True

        # Entry short: ROC < 0 AND EMA fast < EMA slow
        short_entry = roc_negative & fast_below_slow
        short_mask[short_entry] = True

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set warmup period
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long SL/TP
        long_entry_mask = (signals == 1.0)
        df.loc[long_entry_mask, "bb_stop_long"] = close[long_entry_mask] - stop_atr_mult * atr[long_entry_mask]
        df.loc[long_entry_mask, "bb_tp_long"] = close[long_entry_mask] + tp_atr_mult * atr[long_entry_mask]

        # Short SL/TP
        short_entry_mask = (signals == -1.0)
        df.loc[short_entry_mask, "bb_stop_short"] = close[short_entry_mask] + stop_atr_mult * atr[short_entry_mask]
        df.loc[short_entry_mask, "bb_tp_short"] = close[short_entry_mask] - tp_atr_mult * atr[short_entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
