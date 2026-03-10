from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='supertrend_rsi_volatility_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'rsi', 'atr']

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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Extract indicators
        st = indicators['supertrend']
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values
        supertrend_upper = np.nan_to_num(st["supertrend"])
        supertrend_lower = np.nan_to_num(st["supertrend"])
        indicators['supertrend']['direction'] = np.nan_to_num(st["direction"])

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Entry conditions
        rsi_overbought = params.get("rsi_overbought", 70)
        rsi_oversold = params.get("rsi_oversold", 30)

        # Cross detection
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_supertrend_upper = np.roll(supertrend_upper, 1)
        prev_supertrend_upper[0] = np.nan
        prev_supertrend_lower = np.roll(supertrend_lower, 1)
        prev_supertrend_lower[0] = np.nan

        cross_above = (close > supertrend_upper) & (prev_close <= prev_supertrend_upper)
        cross_below = (close < supertrend_lower) & (prev_close >= prev_supertrend_lower)

        # Long entry: close crosses above supertrend.upper AND rsi < 50
        long_entry = cross_above & (rsi < rsi_oversold)
        long_mask[long_entry] = True

        # Short entry: close crosses below supertrend.lower AND rsi > 50
        short_entry = cross_below & (rsi > rsi_overbought)
        short_mask[short_entry] = True

        # Exit conditions
        # Close crosses supertrend.middle OR rsi > 70 OR rsi < 30
        rsi_exit_long = (rsi > rsi_overbought) | (rsi < rsi_oversold)
        rsi_exit_short = (rsi > rsi_overbought) | (rsi < rsi_oversold)

        # Exit long
        long_exit = (indicators['supertrend']['direction'] < 1) | rsi_exit_long
        signals[long_exit] = 0.0

        # Exit short
        short_exit = (indicators['supertrend']['direction'] > -1) | rsi_exit_short
        signals[short_exit] = 0.0

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = (signals == 1.0)
        entry_short = (signals == -1.0)

        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
