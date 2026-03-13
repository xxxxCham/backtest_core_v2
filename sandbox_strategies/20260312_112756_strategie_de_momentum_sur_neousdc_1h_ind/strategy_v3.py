from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='neousdc_momentum_adx_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'adx', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_entry_threshold': 25,
         'adx_exit_threshold': 20,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
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
            'adx_entry_threshold': ParameterSpec(
                name='adx_entry_threshold',
                min_val=10,
                max_val=35,
                default=25,
                param_type='int',
                step=1,
            ),
            'adx_exit_threshold': ParameterSpec(
                name='adx_exit_threshold',
                min_val=10,
                max_val=35,
                default=20,
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

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        # Boolean masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Indicator arrays
        close = np.nan_to_num(df["close"].values)
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])

        macd_dict = indicators['macd']
        hist = np.nan_to_num(macd_dict["histogram"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])

        # Previous histogram for trend direction
        prev_hist = np.roll(hist, 1)
        prev_hist[0] = np.nan
        hist_increasing = hist > prev_hist
        hist_decreasing = hist < prev_hist

        # Entry conditions
        adx_entry_thr = params.get("adx_entry_threshold", 25.0)
        long_entry = (hist > 0.0) & hist_increasing & (adx_val > adx_entry_thr) & (close > ema)
        short_entry = (hist < 0.0) & hist_decreasing & (adx_val > adx_entry_thr) & (close < ema)

        long_mask[long_entry] = True
        short_mask[short_entry] = True

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        adx_exit_thr = params.get("adx_exit_threshold", 20.0)

        # cross_up of histogram over 0
        prev_hist_zero = np.roll(hist, 1)
        prev_hist_zero[0] = np.nan
        cross_up_hist0 = (hist > 0.0) & (prev_hist_zero <= 0.0)

        # positions to exit
        exit_mask = cross_up_hist0 | (adx_val < adx_exit_thr)

        # Set flat for positions that need to be exited
        signals[exit_mask] = 0.0

        # Warmup
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Long entry levels
        long_entry_mask = (signals == 1.0)
        df.loc[long_entry_mask, "bb_stop_long"] = close[long_entry_mask] - stop_atr_mult * atr[long_entry_mask]
        df.loc[long_entry_mask, "bb_tp_long"] = close[long_entry_mask] + tp_atr_mult * atr[long_entry_mask]

        # Short entry levels
        short_entry_mask = (signals == -1.0)
        df.loc[short_entry_mask, "bb_stop_short"] = close[short_entry_mask] + stop_atr_mult * atr[short_entry_mask]
        df.loc[short_entry_mask, "bb_tp_short"] = close[short_entry_mask] - tp_atr_mult * atr[short_entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
