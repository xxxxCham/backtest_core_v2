from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_vwap_cci_volume_v2')

    @property
    def required_indicators(self) -> List[str]:
        # Include all indicators that are accessed in generate_signals
        return ['vwap', 'cci', 'volume_oscillator', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'atr_period': 14,
            'cci_period': 20,
            'leverage': 1,
            'stop_atr_mult': 1.5,
            'tp_atr_mult': 3.0,
            'volume_osc_long': 20,
            'volume_osc_short': 5,
            'vwap_period': 20,
            'warmup': 20
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'atr_period': ParameterSpec(
                name='atr_period',
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
                min_val=1.0,
                max_val=6.0,
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
        params: Dict[str, Any]
    ) -> pd.Series:
        n = len(df)
        warmup = int(params.get('warmup', 50))
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        close = df["close"].values
        vwap = np.nan_to_num(indicators['vwap'])
        cci = np.nan_to_num(indicators['cci'])
        vol_osc = np.nan_to_num(indicators['volume_oscillator'])
        atr = np.nan_to_num(indicators['atr'])

        # Helper for cross detection
        def cross_any(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return ((x > y) & (prev_x <= prev_y)) | ((x < y) & (prev_x >= prev_y))

        # Entry logic
        long_mask = (close > vwap + 0.5 * atr) & (cci > 70) & (vol_osc > 0)
        short_mask = (close < vwap - 0.5 * atr) & (cci < -70) & (vol_osc < 0)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit logic
        cross_vwap = cross_any(close, vwap)
        cross_cci_zero = cross_any(cci, np.zeros_like(cci))
        exit_mask = cross_vwap | cross_cci_zero
        signals[(signals == 1.0) & exit_mask] = 0.0
        signals[(signals == -1.0) & exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]

        signals.iloc[:warmup] = 0.0
        return signals