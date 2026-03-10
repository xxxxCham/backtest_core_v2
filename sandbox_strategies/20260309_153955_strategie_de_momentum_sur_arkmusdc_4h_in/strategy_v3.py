from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='macd_adx_atr_momentum')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'atr_period': 14,
         'leverage': 1,
         'macd_fast_period': 12,
         'macd_signal_period': 9,
         'macd_slow_period': 26,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'macd_fast_period': ParameterSpec(
                name='macd_fast_period',
                min_val=5,
                max_val=20,
                default=12,
                param_type='int',
                step=1,
            ),
            'macd_slow_period': ParameterSpec(
                name='macd_slow_period',
                min_val=15,
                max_val=40,
                default=26,
                param_type='int',
                step=1,
            ),
            'macd_signal_period': ParameterSpec(
                name='macd_signal_period',
                min_val=5,
                max_val=15,
                default=9,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=7,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=7,
                max_val=30,
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
                min_val=1.0,
                max_val=6.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=5,
                default=1,
                param_type='int',
                step=1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=10,
                max_val=200,
                default=50,
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
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)

        # Initialize masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Warmup protection
        warmup = int(params.get("warmup", 50))
        signals.iloc[:warmup] = 0.0

        # Extract indicators with NaN handling
        macd_dict = indicators['macd']
        macd_hist = np.nan_to_num(macd_dict["histogram"])

        adx_dict = indicators['adx']
        adx_val = np.nan_to_num(adx_dict["adx"])

        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Previous histogram for momentum check
        prev_hist = np.roll(macd_hist, 1)
        prev_hist[0] = np.nan

        # Parameters for filters and risk
        adx_entry_thr = float(params.get("adx_entry_threshold", 25))
        adx_exit_thr = float(params.get("adx_exit_threshold", 20))
        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        # Long entry: MACD histogram positive, increasing, ADX strong
        long_mask = (macd_hist > 0) & (macd_hist > prev_hist) & (adx_val > adx_entry_thr)

        # Short entry: MACD histogram negative, decreasing, ADX strong
        short_mask = (macd_hist < 0) & (macd_hist < prev_hist) & (adx_val > adx_entry_thr)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions (override signals to flat on exit bars)
        exit_mask = (np.sign(macd_hist) != np.sign(prev_hist)) | (adx_val < adx_exit_thr)
        signals[exit_mask] = 0.0

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Compute SL/TP levels for long entries
        if long_mask.any():
            stop_long = close - stop_atr_mult * atr
            tp_long = close + tp_atr_mult * atr
            df.loc[long_mask, "bb_stop_long"] = stop_long[long_mask]
            df.loc[long_mask, "bb_tp_long"] = tp_long[long_mask]

        # Compute SL/TP levels for short entries
        if short_mask.any():
            stop_short = close + stop_atr_mult * atr
            tp_short = close - tp_atr_mult * atr
            df.loc[short_mask, "bb_stop_short"] = stop_short[short_mask]
            df.loc[short_mask, "bb_tp_short"] = tp_short[short_mask]

        return signals
        signals.iloc[:warmup] = 0.0
        return signals
