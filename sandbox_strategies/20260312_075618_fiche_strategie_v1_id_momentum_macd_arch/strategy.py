from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='macd_rsi_adx_momentum')

    @property
    def required_indicators(self) -> List[str]:
        # ATR is required for sizing, so include it
        return ['macd', 'rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'leverage': 1,
            'rsi_overbought': 80,
            'rsi_oversold': 20,
            'stop_atr_mult': 2.0,
            'tp_atr_mult': 4.0,
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
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=10.0,
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

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # unwrap indicators
        macd_dict = indicators['macd']
        macd_vals = np.nan_to_num(macd_dict["macd"])
        signal_line = np.nan_to_num(macd_dict["signal"])
        hist = np.nan_to_num(macd_dict["histogram"])

        rsi = np.nan_to_num(indicators['rsi'])

        adx_dict = indicators['adx']
        adx_val = np.nan_to_num(adx_dict["adx"])

        atr = np.nan_to_num(indicators['atr'])

        # cross helpers
        prev_macd = np.roll(macd_vals, 1)
        prev_signal = np.roll(signal_line, 1)
        prev_macd[0] = np.nan
        prev_signal[0] = np.nan
        cross_up = (macd_vals > signal_line) & (prev_macd <= prev_signal)
        cross_down = (macd_vals < signal_line) & (prev_macd >= prev_signal)

        # entry conditions
        long_mask = (
            cross_up
            & (hist > 0)
            & (rsi > 40)
            & (rsi < 60)
            & (adx_val > params.get("adx_threshold", 25))
        )
        short_mask = (
            cross_down
            & (hist < 0)
            & (rsi > 40)
            & (rsi < 60)
            & (adx_val > params.get("adx_threshold", 25))
        )

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # exit conditions
        prev_hist = np.roll(hist, 1)
        prev_hist[0] = np.nan
        cross_any_hist0 = ((hist > 0) & (prev_hist <= 0)) | ((hist < 0) & (prev_hist >= 0))
        exit_mask = (
            cross_any_hist0
            | (rsi > params.get("rsi_overbought", 80))
            | (rsi < params.get("rsi_oversold", 20))
        )
        signals[exit_mask] = 0.0

        # warmup
        signals.iloc[:warmup] = 0.0

        # SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        close = df["close"].values
        entry_long = long_mask
        entry_short = short_mask

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]

        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]

        return signals