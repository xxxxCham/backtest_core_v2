from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_macd_v3')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 80,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 2.75,
         'tp_atr_mult': 4.0,
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
                default=2.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=8.0,
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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Extract indicators
        macd_d = indicators['macd']
        rsi = np.nan_to_num(indicators['rsi'])
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        # MACD values
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        signal_line = np.nan_to_num(macd_d["signal"])
        hist = np.nan_to_num(macd_d["histogram"])

        # ADX values
        adx = np.nan_to_num(adx_d["adx"])

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Cross detection
        prev_macd = np.roll(indicators['macd']['macd'], 1)
        prev_signal = np.roll(signal_line, 1)
        prev_macd[0] = np.nan
        prev_signal[0] = np.nan

        cross_up = (indicators['macd']['macd'] > signal_line) & (prev_macd <= prev_signal)
        cross_down = (indicators['macd']['macd'] < signal_line) & (prev_macd >= prev_signal)

        # Entry conditions
        adx_filter = adx > 25

        # Long entries
        long_entry_cond1 = cross_up
        long_entry_cond2 = (rsi > params["rsi_oversold"]) & (rsi < 80)
        long_mask = long_entry_cond1 & long_entry_cond2 & adx_filter

        # Short entries
        short_entry_cond1 = cross_down
        short_entry_cond2 = (rsi > 30) & (rsi < params["rsi_overbought"])
        short_mask = short_entry_cond1 & short_entry_cond2 & adx_filter

        # Exit conditions
        prev_hist = np.roll(hist, 1)
        prev_hist[0] = np.nan
        hist_change_sign = (hist * prev_hist) < 0

        rsi_exit_long = rsi > params["rsi_overbought"]
        rsi_exit_short = rsi < params["rsi_oversold"]

        exit_mask = hist_change_sign | rsi_exit_long | rsi_exit_short

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels for long entries
        close = df["close"].values
        entry_long = signals == 1.0
        if entry_long.any():
            df.loc[:, "bb_stop_long"] = np.nan
            df.loc[:, "bb_tp_long"] = np.nan
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]

        # Set SL/TP levels for short entries
        entry_short = signals == -1.0
        if entry_short.any():
            df.loc[:, "bb_stop_short"] = np.nan
            df.loc[:, "bb_tp_short"] = np.nan
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
