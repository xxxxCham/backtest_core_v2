from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='macd_rsi_sma_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'rsi', 'sma', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'atr_period': 14,
            'leverage': 1,
            'macd_fast_period': 9,
            'macd_signal_period': 12,
            'macd_slow_period': 24,
            'rsi_period': 8,
            'sma_period': 50,
            'stop_atr_mult': 2.0,
            'tp_atr_mult': 3.5,
            'warmup': 50
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'macd_fast_period': ParameterSpec(
                name='macd_fast_period',
                min_val=5,
                max_val=20,
                default=9,
                param_type='int',
                step=1,
            ),
            'macd_slow_period': ParameterSpec(
                name='macd_slow_period',
                min_val=15,
                max_val=50,
                default=24,
                param_type='int',
                step=1,
            ),
            'macd_signal_period': ParameterSpec(
                name='macd_signal_period',
                min_val=5,
                max_val=20,
                default=12,
                param_type='int',
                step=1,
            ),
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=20,
                default=8,
                param_type='int',
                step=1,
            ),
            'sma_period': ParameterSpec(
                name='sma_period',
                min_val=20,
                max_val=200,
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
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.5,
                max_val=6.0,
                default=3.5,
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

        # Prepare indicator arrays
        macd_dict = indicators['macd']
        macd = np.nan_to_num(macd_dict["macd"])
        signal_line = np.nan_to_num(macd_dict["signal"])
        hist = np.nan_to_num(macd_dict["histogram"])

        rsi = np.nan_to_num(indicators['rsi'])
        sma = np.nan_to_num(indicators['sma'])
        close = df["close"].values
        atr = np.nan_to_num(indicators['atr'])

        # Cross helpers
        prev_macd = np.roll(macd, 1)
        prev_macd[0] = np.nan
        prev_signal = np.roll(signal_line, 1)
        prev_signal[0] = np.nan
        cross_up_macd = (macd > signal_line) & (prev_macd <= prev_signal)
        cross_down_macd = (macd < signal_line) & (prev_macd >= prev_signal)

        # Entry conditions
        long_mask = (
            cross_up_macd
            & (rsi > 45)
            & (rsi < 75)
            & (close > sma)
        )
        short_mask = (
            cross_down_macd
            & (rsi > 30)
            & (rsi < 60)
            & (close < sma)
        )

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        prev_hist = np.roll(hist, 1)
        prev_hist[0] = np.nan
        cross_any_hist = ((hist > 0) & (prev_hist <= 0)) | ((hist < 0) & (prev_hist >= 0))
        exit_mask = cross_any_hist | (rsi > 80) | (rsi < 20)
        signals[exit_mask] = 0.0

        # ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.5))

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]

        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]

        signals.iloc[:warmup] = 0.0
        return signals