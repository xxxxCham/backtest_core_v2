from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='supertrend_keltner_rsi_1h')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'keltner', 'rsi']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'leverage': 1,
            'rsi_period': 14,
            'stop_atr_mult': 1.5,
            'tp_atr_mult': 3.0,
            'warmup': 50,
        }

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
                max_val=5.0,
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

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any],
    ) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Extract indicator arrays
        close = df["close"].values
        atr = np.nan_to_num(indicators['supertrend'].get('atr', np.zeros(n)))
        supertrend_dir = np.nan_to_num(indicators['supertrend']["direction"])
        kelt = indicators['keltner']
        kelt_upper = np.nan_to_num(kelt["upper"])
        kelt_middle = np.nan_to_num(kelt["middle"])
        kelt_lower = np.nan_to_num(kelt["lower"])
        rsi = np.nan_to_num(indicators['rsi'])

        def cross_any(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return ((x > y) & (prev_x <= prev_y)) | ((x < y) & (prev_x >= prev_y))

        # Entry masks
        long_mask = (supertrend_dir == 1) & (close > kelt_upper) & (rsi > 50)
        short_mask = (supertrend_dir == -1) & (close < kelt_lower) & (rsi < 50)

        # Exit mask
        exit_cross = cross_any(close, kelt_middle)
        exit_mask = exit_cross | (rsi < 40) | (rsi > 60)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # Warmup
        signals.iloc[:warmup] = 0.0

        # ATR‑based SL/TP levels on entry bars
        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]

        return signals