from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_rsi_adx_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'leverage': 1,
            'rsi_overbought': 70,
            'rsi_oversold': 30,
            'rsi_period': 14,
            'stop_atr_mult': 2.5,
            'tp_atr_mult': 5.0,
            'warmup': 20
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

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any]
    ) -> pd.Series:
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Base signals series
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        # Indicator arrays (ensure numpy arrays)
        close = np.asarray(df["close"].values, dtype=np.float64)

        bb = indicators['bollinger']
        lower = np.nan_to_num(np.asarray(bb["lower"], dtype=np.float64))
        upper = np.nan_to_num(np.asarray(bb["upper"], dtype=np.float64))
        middle = np.nan_to_num(np.asarray(bb["middle"], dtype=np.float64))

        rsi = np.nan_to_num(np.asarray(indicators['rsi'], dtype=np.float64))
        adx = np.nan_to_num(np.asarray(indicators['adx']["adx"], dtype=np.float64))
        atr = np.nan_to_num(np.asarray(indicators['atr'], dtype=np.float64))

        # Helper for cross detection between two arrays
        def cross_any(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return ((x > y) & (prev_x <= prev_y)) | ((x < y) & (prev_x >= prev_y))

        # Helper for crossing a scalar threshold
        def cross_threshold(x: np.ndarray, thresh: float) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_x[0] = np.nan
            return ((x > thresh) & (prev_x <= thresh)) | ((x < thresh) & (prev_x >= thresh))

        # Entry conditions
        long_mask = (close < lower) & (rsi < params["rsi_oversold"]) & (adx < 20)
        short_mask = (close > upper) & (rsi > params["rsi_overbought"]) & (adx < 20)

        # Exit conditions
        exit_mask = cross_any(close, middle) | cross_threshold(rsi, 50.0)

        # Apply masks to signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # Ensure no signals during warmup
        signals.iloc[:warmup] = 0.0

        # ATR‑based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - params["stop_atr_mult"] * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + params["tp_atr_mult"] * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + params["stop_atr_mult"] * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - params["tp_atr_mult"] * atr[short_mask]

        return signals