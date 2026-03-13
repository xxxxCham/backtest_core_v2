from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='vol_amplitude_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['amplitude_hunter', 'donchian', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'amplitude_hunter_period': 9,
            'atr_period': 14,
            'donchian_period': 45,
            'leverage': 1,
            'stop_atr_mult': 2.0,
            'tp_atr_mult': 6.0,
            'warmup': 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'amplitude_hunter_period': ParameterSpec(
                name='amplitude_hunter_period',
                min_val=5,
                max_val=20,
                default=9,
                param_type='int',
                step=1,
            ),
            'donchian_period': ParameterSpec(
                name='donchian_period',
                min_val=20,
                max_val=100,
                default=45,
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
                min_val=1.0,
                max_val=10.0,
                default=6.0,
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

        # Warmup protection
        warmup = int(params.get('warmup', 50))
        signals.iloc[:warmup] = 0.0

        # Extract indicator arrays
        # amplitude_hunter may be a dict with key 'score'
        amp_raw = indicators['amplitude_hunter']
        if isinstance(amp_raw, dict):
            amp = np.nan_to_num(amp_raw.get('score', np.full(n, np.nan)))
        else:
            amp = np.nan_to_num(amp_raw)

        atr = np.nan_to_num(indicators['atr'])
        dc = indicators['donchian']
        upper = np.nan_to_num(dc["upper"])
        middle = np.nan_to_num(dc["middle"])
        lower = np.nan_to_num(dc["lower"])
        close = df["close"].values

        # Volatility filter
        vol_filter = atr > (upper - lower) / 2.0

        # Entry conditions
        long_cond = (amp > 0.9) & (close > upper) & vol_filter
        short_cond = (amp > 0.9) & (close < lower) & vol_filter

        # Apply signals
        signals[long_cond] = 1.0
        signals[short_cond] = -1.0

        # Exit conditions
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        cross_up = (close > middle) & (prev_close <= prev_middle)
        cross_down = (close < middle) & (prev_close >= prev_middle)
        cross_any = cross_up | cross_down
        exit_cond = (amp < 0.2) | cross_any

        # Flatten positions on exit
        in_long = signals == 1.0
        in_short = signals == -1.0
        signals[(in_long | in_short) & exit_cond] = 0.0

        # ATR-based SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 6.0))

        # Long entries
        df.loc[long_cond, "bb_stop_long"] = close[long_cond] - stop_atr_mult * atr[long_cond]
        df.loc[long_cond, "bb_tp_long"] = close[long_cond] + tp_atr_mult * atr[long_cond]

        # Short entries
        df.loc[short_cond, "bb_stop_short"] = close[short_cond] + stop_atr_mult * atr[short_cond]
        df.loc[short_cond, "bb_tp_short"] = close[short_cond] - tp_atr_mult * atr[short_cond]

        signals.iloc[:warmup] = 0.0
        return signals