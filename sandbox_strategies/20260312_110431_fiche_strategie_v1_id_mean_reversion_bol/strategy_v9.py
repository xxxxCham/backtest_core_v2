from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_rsi_stoch_reversion')

    @property
    def required_indicators(self) -> List[str]:
        # ATR is required for risk‑management
        return ['bollinger', 'rsi', 'stoch_rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 4.0, 'warmup': 50}

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
            'bollinger_period': ParameterSpec(
                name='bollinger_period',
                min_val=10,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
            ),
            'bollinger_std_dev': ParameterSpec(
                name='bollinger_std_dev',
                min_val=1.5,
                max_val=3.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'stoch_rsi_period': ParameterSpec(
                name='stoch_rsi_period',
                min_val=5,
                max_val=20,
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
                max_val=6.0,
                default=4.0,
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
        params: Dict[str, Any],
    ) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # unpack indicators with nan_to_num
        bb = indicators['bollinger']
        lower = np.nan_to_num(bb["lower"])
        middle = np.nan_to_num(bb["middle"])
        upper = np.nan_to_num(bb["upper"])

        rsi = np.nan_to_num(indicators['rsi'])

        srsi = indicators['stoch_rsi']
        k_srsi = np.nan_to_num(srsi["k"])

        atr = np.nan_to_num(indicators['atr'])

        close = df["close"].values

        # helper cross detection
        def cross_any(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return ((x > y) & (prev_x <= prev_y)) | ((x < y) & (prev_x >= prev_y))

        # entry conditions
        long_mask = (close < lower) & (rsi < 30) & (k_srsi < 20)
        short_mask = (close > upper) & (rsi > 70) & (k_srsi > 80)

        # exit conditions: cross of price with middle band or StochRSI k crossing 50
        cross_k50 = ((k_srsi > 50) & (np.roll(k_srsi, 1) <= 50)) | (
            (k_srsi < 50) & (np.roll(k_srsi, 1) >= 50)
        )
        exit_mask = cross_any(close, middle) | cross_k50

        # apply warmup
        signals.iloc[:warmup] = 0.0

        # set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # ATR based SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 4.0))

        df.loc[signals == 1.0, "bb_stop_long"] = (
            close[signals == 1.0] - stop_atr_mult * atr[signals == 1.0]
        )
        df.loc[signals == 1.0, "bb_tp_long"] = (
            close[signals == 1.0] + tp_atr_mult * atr[signals == 1.0]
        )

        df.loc[signals == -1.0, "bb_stop_short"] = (
            close[signals == -1.0] + stop_atr_mult * atr[signals == -1.0]
        )
        df.loc[signals == -1.0, "bb_tp_short"] = (
            close[signals == -1.0] - tp_atr_mult * atr[signals == -1.0]
        )

        signals.iloc[:warmup] = 0.0
        return signals