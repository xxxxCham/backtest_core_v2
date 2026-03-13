from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='keltner_mean_reversion_buffer')

    @property
    def required_indicators(self) -> List[str]:
        return ['keltner', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
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
                min_val=0.5,
                max_val=4.0,
                default=1.5,
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
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=4.5,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
        }

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        # Boolean masks for entries and exits
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Warmup
        signals.iloc[:warmup] = 0.0

        # Extract indicator arrays
        close = df["close"].values
        kelt = indicators['keltner']
        upper = np.nan_to_num(kelt["upper"])
        middle = np.nan_to_num(kelt["middle"])
        lower = np.nan_to_num(kelt["lower"])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Entry conditions
        long_threshold = lower + 0.5 * (upper - lower)
        short_threshold = upper - 0.5 * (upper - lower)

        long_mask = (close <= long_threshold) & (rsi <= params["rsi_oversold"])
        short_mask = (close >= short_threshold) & (rsi >= params["rsi_overbought"])

        # Exit condition: close crosses middle band
        prev_close = np.roll(close, 1)
        prev_mid = np.roll(middle, 1)
        prev_close[0] = np.nan
        prev_mid[0] = np.nan
        cross_up = (close > middle) & (prev_close <= prev_mid)
        cross_down = (close < middle) & (prev_close >= prev_mid)
        exit_mask = cross_up | cross_down

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        long_entry = signals == 1.0
        short_entry = signals == -1.0

        df.loc[long_entry, "bb_stop_long"] = close[long_entry] - stop_atr_mult * atr[long_entry]
        df.loc[long_entry, "bb_tp_long"] = close[long_entry] + tp_atr_mult * atr[long_entry]
        df.loc[short_entry, "bb_stop_short"] = close[short_entry] + stop_atr_mult * atr[short_entry]
        df.loc[short_entry, "bb_tp_short"] = close[short_entry] - tp_atr_mult * atr[short_entry]
        signals.iloc[:warmup] = 0.0
        return signals
