from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_macd_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'macd_fast_period': 13,
         'macd_signal_period': 10,
         'macd_slow_period': 31,
         'rsi_overbought': 80,
         'rsi_oversold': 20,
         'rsi_period': 14,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 2.0,
         'warmup': 50}

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
                min_val=1.0,
                max_val=5.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.0,
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
        macd_d = indicators['macd']
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        signal_line = np.nan_to_num(macd_d["signal"])
        histogram = np.nan_to_num(macd_d["histogram"])
        prev_macd = np.roll(indicators['macd']['macd'], 1)
        prev_signal = np.roll(signal_line, 1)
        prev_histogram = np.roll(histogram, 1)
        prev_macd[0] = np.nan
        prev_signal[0] = np.nan
        prev_histogram[0] = np.nan
        cross_up_macd = (indicators['macd']['macd'] > signal_line) & (prev_macd <= prev_signal)
        cross_down_macd = (indicators['macd']['macd'] < signal_line) & (prev_macd >= prev_signal)
        cross_up_hist = (histogram > 0) & (prev_histogram <= 0)
        cross_down_hist = (histogram < 0) & (prev_histogram >= 0)
        long_entry = cross_up_hist & (rsi > 35) & (rsi < 60)
        short_entry = cross_down_hist & (rsi > 30) & (rsi < 60)
        exit_long = cross_up_hist | (rsi > params["rsi_overbought"]) | (rsi < params["rsi_oversold"])
        exit_short = cross_down_hist | (rsi > params["rsi_overbought"]) | (rsi < params["rsi_oversold"])
        long_mask = long_entry
        short_mask = short_entry
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals.iloc[:warmup] = 0.0
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
