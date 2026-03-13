from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_adx_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 10,
         'bollinger_period': 20,
         'bollinger_std_dev': 2,
         'leverage': 1,
         'stop_atr_mult': 2.5,
         'tp_atr_mult': 5.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'bollinger_period': ParameterSpec(
                name='bollinger_period',
                min_val=10,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=30,
                default=10,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=10.0,
                default=5.0,
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
        bb = indicators['bollinger']
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Prepare bands
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        # Prepare ADX
        adx_val = np.nan_to_num(adx_d["adx"])

        # Entry conditions
        # Long entry: close crosses below lower band and ADX > 25
        prev_close = np.roll(close, 1)
        prev_lower = np.roll(lower, 1)
        prev_close[0] = np.nan
        prev_lower[0] = np.nan
        cross_below_lower = (close < lower) & (prev_close >= prev_lower)
        long_entry = cross_below_lower & (adx_val > 25)

        # Short entry: close crosses above upper band and ADX > 25
        prev_upper = np.roll(upper, 1)
        prev_upper[0] = np.nan
        cross_above_upper = (close > upper) & (prev_close <= prev_upper)
        short_entry = cross_above_upper & (adx_val > 25)

        # Exit conditions
        # Close crosses middle band
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        cross_middle = (close > middle) & (prev_close <= prev_middle) | (close < middle) & (prev_close >= prev_middle)
        # ADX < 20
        adx_weak = adx_val < 20

        # Set long and short masks
        long_mask = long_entry
        short_mask = short_entry

        # Apply exits
        long_exit = cross_middle | adx_weak
        short_exit = cross_middle | adx_weak

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exit signals
        signals[long_exit] = 0.0
        signals[short_exit] = 0.0

        # Write ATR-based SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 2.5)
        tp_atr_mult = params.get("tp_atr_mult", 5.0)

        entry_long = (signals == 1.0)
        entry_short = (signals == -1.0)

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
