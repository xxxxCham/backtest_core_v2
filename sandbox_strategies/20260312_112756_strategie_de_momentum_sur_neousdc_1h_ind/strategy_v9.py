from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='neousdc_1h_macd_atr_adx')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'atr_period': 10,
         'leverage': 1,
         'macd_fast_period': 10,
         'macd_signal_period': 9,
         'macd_slow_period': 28,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 30}
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
                min_val=20,
                max_val=40,
                default=26,
                param_type='int',
                step=1,
            ),
            'macd_signal_period': ParameterSpec(
                name='macd_signal_period',
                min_val=5,
                max_val=20,
                default=9,
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
            'adx_period': ParameterSpec(
                name='adx_period',
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
                default=1.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=10,
                max_val=50,
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
        # Masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Extract indicators
        macd_hist = np.nan_to_num(indicators['macd']["histogram"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        prev_hist = np.roll(macd_hist, 1)
        prev_hist[0] = np.nan

        # Entry conditions
        long_mask = (macd_hist > 0) & (macd_hist > prev_hist) & (adx_val > 25)
        short_mask = (macd_hist < 0) & (macd_hist < prev_hist) & (adx_val > 25)

        # Exit conditions
        cross_up = (macd_hist > 0) & (prev_hist <= 0)
        cross_down = (macd_hist < 0) & (prev_hist >= 0)
        exit_mask = cross_up | cross_down | (adx_val < 20)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:50] = 0.0  # ensure first 50 bars flat

        # ATR-based SL/TP levels
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Initialize columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entry levels
        long_entry = long_mask
        df.loc[long_entry, "bb_stop_long"] = close[long_entry] - params["stop_atr_mult"] * atr[long_entry]
        df.loc[long_entry, "bb_tp_long"] = close[long_entry] + params["tp_atr_mult"] * atr[long_entry]

        # Short entry levels
        short_entry = short_mask
        df.loc[short_entry, "bb_stop_short"] = close[short_entry] + params["stop_atr_mult"] * atr[short_entry]
        df.loc[short_entry, "bb_tp_short"] = close[short_entry] - params["tp_atr_mult"] * atr[short_entry]
        signals.iloc[:warmup] = 0.0
        return signals
