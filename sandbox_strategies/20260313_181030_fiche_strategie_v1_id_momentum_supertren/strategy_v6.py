from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_rsi_supertrend')

    @property
    def required_indicators(self) -> List[str]:
        # ATR is required for risk management
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
                max_val=6.0,
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
        self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]
    ) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Extract indicator arrays with nan handling
        supertrend_line = np.nan_to_num(indicators['supertrend']["supertrend"])
        direction = np.nan_to_num(indicators['supertrend']["direction"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        rsi_val = np.nan_to_num(indicators['rsi'])
        atr_val = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Helper for cross detection
        def cross_any(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return ((x > y) & (prev_x <= prev_y)) | ((x < y) & (prev_x >= prev_y))

        # Entry conditions
        long_mask = (
            (close > supertrend_line)
            & (direction > 0)
            & (adx_val > 25)
            & (rsi_val > 50)
        )
        short_mask = (
            (close < supertrend_line)
            & (direction < 0)
            & (adx_val > 25)
            & (rsi_val < 50)
        )

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        exit_long_mask = (
            (cross_any(close, supertrend_line) | (adx_val < 20))
            & (signals.values == 1.0)
        )
        exit_short_mask = (
            (cross_any(close, supertrend_line) | (adx_val < 20))
            & (signals.values == -1.0)
        )
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Warmup period
        signals.iloc[:warmup] = 0.0

        # ATR‑based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_mult = params.get("stop_atr_mult", 1.5)
        tp_mult = params.get("tp_atr_mult", 3.0)

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_mult * atr_val[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_mult * atr_val[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_mult * atr_val[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_mult * atr_val[short_mask]

        return signals