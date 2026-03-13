from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_trend_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'leverage': 1,
         'macd_fast': 12,
         'macd_signal': 9,
         'macd_slow': 26,
         'stop_atr_mult': 1.25,
         'tp_atr_mult': 5.5,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'macd_fast': ParameterSpec(
                name='macd_fast',
                min_val=5,
                max_val=30,
                default=12,
                param_type='int',
                step=1,
            ),
            'macd_slow': ParameterSpec(
                name='macd_slow',
                min_val=20,
                max_val=60,
                default=26,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
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
                default=1.25,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=10.0,
                default=5.5,
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
        # Warmup protection
        signals.iloc[:warmup] = 0.0
        # Extract indicators
        macd_d = indicators['macd']
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        indicators['macd']['signal'] = np.nan_to_num(macd_d["signal"])
        macd_hist = np.nan_to_num(macd_d["histogram"])
        adx_d = indicators['adx']
        adx_val = np.nan_to_num(adx_d["adx"])
        atr = np.nan_to_num(indicators['atr'])
        # Compute crosses
        prev_macd_line = np.roll(indicators['macd']['macd'], 1)
        prev_macd_signal = np.roll(indicators['macd']['signal'], 1)
        prev_macd_line[0] = np.nan
        prev_macd_signal[0] = np.nan
        cross_up = (indicators['macd']['macd'] > indicators['macd']['signal']) & (prev_macd_line <= prev_macd_signal)
        cross_down = (indicators['macd']['macd'] < indicators['macd']['signal']) & (prev_macd_line >= prev_macd_signal)
        # Entry conditions
        adx_filter = adx_val > 25
        long_entry = cross_up & adx_filter
        short_entry = cross_down & adx_filter
        long_mask[long_entry] = True
        short_mask[short_entry] = True
        # Exit conditions
        prev_macd_hist = np.roll(macd_hist, 1)
        prev_macd_hist[0] = np.nan
        hist_change_sign = (macd_hist > 0) & (prev_macd_hist <= 0) | (macd_hist < 0) & (prev_macd_hist >= 0)
        adx_trend_weak = adx_val < 20
        exit_long = hist_change_sign | adx_trend_weak
        exit_short = hist_change_sign | adx_trend_weak
        # Apply exits
        exit_long_mask = np.zeros(n, dtype=bool)
        exit_long_mask[exit_long] = True
        exit_short_mask = np.zeros(n, dtype=bool)
        exit_short_mask[exit_short] = True
        # Combine masks
        long_mask &= ~exit_long_mask
        short_mask &= ~exit_short_mask
        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        # Write SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        close = df["close"].values
        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)
        if np.any(entry_long_mask):
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]
        if np.any(entry_short_mask):
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
