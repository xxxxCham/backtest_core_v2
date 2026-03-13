from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='neousdc_mean_reversion_rsi_ema_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'leverage': 1,
            'rsi_overbought': 75,
            'rsi_oversold': 25,
            'rsi_period': 14,
            'stop_atr_mult': 1.5,
            'tp_atr_mult': 3.0,
            'warmup': 50
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
                min_val=2.0,
                max_val=4.5,
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
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any]
    ) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Ensure arrays are numeric
        close = np.nan_to_num(df["close"].values)
        ema = np.nan_to_num(indicators['ema'])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Helper cross functions for two series
        def cross_up(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return (x > y) & (prev_x <= prev_y)

        def cross_down(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return (x < y) & (prev_x >= prev_y)

        # Long entry conditions
        long_cond = (
            (close < ema)
            & (rsi < params["rsi_oversold"])
            & (np.abs(close - ema) < 0.5 * atr)
        )
        # Short entry conditions
        short_cond = (
            (close > ema)
            & (rsi > params["rsi_overbought"])
            & (np.abs(close - ema) < 0.5 * atr)
        )

        signals[long_cond] = 1.0
        signals[short_cond] = -1.0

        # Exit conditions: close/ema cross or rsi crossing 50
        exit_mask = (
            cross_up(close, ema) | cross_down(close, ema)
            | ((rsi > 50) & (np.roll(rsi, 1) <= 50))
            | ((rsi < 50) & (np.roll(rsi, 1) >= 50))
        )
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        df.loc[long_cond, "bb_stop_long"] = close[long_cond] - params["stop_atr_mult"] * atr[long_cond]
        df.loc[long_cond, "bb_tp_long"] = close[long_cond] + params["tp_atr_mult"] * atr[long_cond]

        df.loc[short_cond, "bb_stop_short"] = close[short_cond] + params["stop_atr_mult"] * atr[short_cond]
        df.loc[short_cond, "bb_tp_short"] = close[short_cond] - params["tp_atr_mult"] * atr[short_cond]

        return signals