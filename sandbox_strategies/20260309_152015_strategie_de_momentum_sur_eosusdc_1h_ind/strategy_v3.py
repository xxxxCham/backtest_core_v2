from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='macd_atr_momentum')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
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
                min_val=20,
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

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        # Initialize masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Extract indicators with NaN handling
        macd_dict = indicators['macd']
        macd_hist = np.nan_to_num(macd_dict["histogram"])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Zero-cross detection for MACD histogram
        prev_hist = np.roll(macd_hist, 1)
        prev_hist[0] = np.nan
        cross_up = (macd_hist > 0) & (prev_hist <= 0)
        cross_down = (macd_hist < 0) & (prev_hist >= 0)

        long_mask = cross_up
        short_mask = cross_down

        # Apply warmup protection
        if warmup > 0:
            signals.iloc[:warmup] = 0.0
            long_mask[:warmup] = False
            short_mask[:warmup] = False

        # Set signal values
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Prepare ATR‑based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_mult = float(params.get("stop_atr_mult", 1.5))
        tp_mult = float(params.get("tp_atr_mult", 3.0))

        # Long entry SL/TP
        if long_mask.any():
            entry_prices_long = close[long_mask]
            atr_long = atr[long_mask]
            df.loc[long_mask, "bb_stop_long"] = entry_prices_long - stop_mult * atr_long
            df.loc[long_mask, "bb_tp_long"] = entry_prices_long + tp_mult * atr_long

        # Short entry SL/TP
        if short_mask.any():
            entry_prices_short = close[short_mask]
            atr_short = atr[short_mask]
            df.loc[short_mask, "bb_stop_short"] = entry_prices_short + stop_mult * atr_short
            df.loc[short_mask, "bb_tp_short"] = entry_prices_short - tp_mult * atr_short
        signals.iloc[:warmup] = 0.0
        return signals
