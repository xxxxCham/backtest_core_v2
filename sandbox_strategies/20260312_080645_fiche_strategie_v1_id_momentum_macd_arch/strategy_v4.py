from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='macd_rsi_adx_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'leverage': 1,
            'rsi_period': 13,
            'stop_atr_mult': 2.5,
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
                default=13,
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
                min_val=1.5,
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

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any],
    ) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Extract indicator arrays
        macd_arr = np.nan_to_num(indicators['macd']["macd"])
        signal_arr = np.nan_to_num(indicators['macd']["signal"])
        macd_hist = np.nan_to_num(indicators['macd']["histogram"])
        rsi = np.nan_to_num(indicators['rsi'])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Cross helpers
        prev_macd = np.roll(macd_arr, 1)
        prev_signal = np.roll(signal_arr, 1)
        prev_macd[0] = np.nan
        prev_signal[0] = np.nan
        cross_up = (macd_arr > signal_arr) & (prev_macd <= prev_signal)
        cross_down = (macd_arr < signal_arr) & (prev_macd >= prev_signal)

        # Entry conditions
        adx_entry_threshold = 25  # constant as per strategy description
        long_mask = (
            cross_up
            & (rsi > 30)
            & (rsi < 70)
            & (adx_val > adx_entry_threshold)
        )
        short_mask = (
            cross_down
            & (rsi > 30)
            & (rsi < 70)
            & (adx_val > adx_entry_threshold)
        )

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        prev_hist = np.roll(macd_hist, 1)
        prev_hist[0] = np.nan
        hist_sign_change = (macd_hist * prev_hist) < 0
        adx_exit_threshold = 20  # constant as per strategy description
        exit_mask = (
            hist_sign_change
            | (rsi > 80)
            | (rsi < 20)
            | (adx_val < adx_exit_threshold)
        )
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP on entry bars
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - params["stop_atr_mult"] * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + params["tp_atr_mult"] * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + params["stop_atr_mult"] * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - params["tp_atr_mult"] * atr[short_mask]

        return signals