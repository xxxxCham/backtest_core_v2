from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='supertrend_filtered_cci_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'cci', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'cci_overbought': 100,
         'cci_oversold': -100,
         'cci_period': 14,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'cci_period': ParameterSpec(
                name='cci_period',
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
                min_val=2.0,
                max_val=5.0,
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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # warmup protection
        signals.iloc[:warmup] = 0.0
        # Extract indicators
        st = indicators['supertrend']
        cci = np.nan_to_num(indicators['cci'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values
        # Supertrend values
        supertrend_upper = np.nan_to_num(st["supertrend"])
        direction = np.nan_to_num(st["direction"])
        # CCI thresholds
        cci_overbought = params.get("cci_overbought", 100)
        cci_oversold = params.get("cci_oversold", -100)
        # Entry conditions
        # Long entry: close crosses above supertrend.upper AND cci > 100
        prev_close = np.roll(close, 1)
        prev_supertrend_upper = np.roll(supertrend_upper, 1)
        prev_close[0] = np.nan
        prev_supertrend_upper[0] = np.nan
        cross_above = (close > supertrend_upper) & (prev_close <= prev_supertrend_upper)
        long_entry = cross_above & (cci > cci_overbought)
        # Short entry: close crosses below supertrend.lower AND cci < -100
        prev_supertrend_lower = np.roll(supertrend_upper, 1)
        prev_supertrend_lower[0] = np.nan
        cross_below = (close < supertrend_upper) & (prev_close >= prev_supertrend_lower)
        short_entry = cross_below & (cci < cci_oversold)
        # Exit conditions
        # Exit long: close crosses below supertrend.middle OR cci crosses below -100
        exit_long = (close < supertrend_upper) | (cci < cci_oversold)
        # Exit short: close crosses above supertrend.middle OR cci crosses above 100
        exit_short = (close > supertrend_upper) | (cci > cci_overbought)
        # Apply long signals
        long_mask = long_entry
        signals[long_mask] = 1.0
        # Apply short signals
        short_mask = short_entry
        signals[short_mask] = -1.0
        # ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        # Long SL/TP
        entry_long = (signals == 1.0)
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]
        # Short SL/TP
        entry_short = (signals == -1.0)
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
