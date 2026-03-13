from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_rsi_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

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
                min_val=1.0,
                max_val=10.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=20,
                max_val=100,
                default=50,
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

    def generate_signals(
        self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]
    ) -> pd.Series:
        n = len(df)
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        warmup = int(params.get('warmup', 50))

        # Extract indicator arrays as floats to allow NaN handling
        st_dir = np.asarray(indicators['supertrend']["direction"], dtype=float)
        adx_val = np.asarray(indicators['adx']["adx"], dtype=float)
        rsi_val = np.asarray(indicators['rsi'], dtype=float)
        atr_val = np.asarray(indicators['atr'], dtype=float)

        # Entry conditions
        long_mask = (st_dir == 1) & (adx_val > 30) & (rsi_val > 50)
        short_mask = (st_dir == -1) & (adx_val > 30) & (rsi_val < 50)

        # Apply warmup
        signals.iloc[:warmup] = 0.0

        # Set entry signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions: direction change or weak ADX
        prev_dir = np.roll(st_dir, 1).astype(float)
        prev_dir[0] = np.nan
        direction_change = st_dir != prev_dir
        weak_adx = adx_val < 20
        exit_mask = direction_change | weak_adx
        signals[exit_mask] = 0.0

        # ATR‑based SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        close = df["close"].values
        stop_mult = float(params.get("stop_atr_mult", 1.5))
        tp_mult = float(params.get("tp_atr_mult", 3.0))

        long_entry = signals == 1.0
        short_entry = signals == -1.0

        df.loc[long_entry, "bb_stop_long"] = close[long_entry] - stop_mult * atr_val[long_entry]
        df.loc[long_entry, "bb_tp_long"] = close[long_entry] + tp_mult * atr_val[long_entry]
        df.loc[short_entry, "bb_stop_short"] = close[short_entry] + stop_mult * atr_val[short_entry]
        df.loc[short_entry, "bb_tp_short"] = close[short_entry] - tp_mult * atr_val[short_entry]

        signals.iloc[:warmup] = 0.0
        return signals