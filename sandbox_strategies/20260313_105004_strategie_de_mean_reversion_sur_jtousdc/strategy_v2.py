from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_atr_with_rsi_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'atr', 'rsi', 'adx']

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
        bb = indicators['bollinger']
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])
        atr = np.nan_to_num(indicators['atr'])
        rsi = np.nan_to_num(indicators['rsi'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Define entry conditions
        # Entry long: close crosses above middle AND rsi < 50 AND adx > 25
        prev_close = np.roll(df["close"].values, 1)
        prev_close[0] = np.nan
        close = df["close"].values
        cross_above_middle = (close > middle) & (prev_close <= middle)
        rsi_filter_long = rsi < params["rsi_oversold"]
        adx_filter_long = adx > 25
        long_entry = cross_above_middle & rsi_filter_long & adx_filter_long

        # Entry short: close crosses below middle AND rsi > 50 AND adx > 25
        cross_below_middle = (close < middle) & (prev_close >= middle)
        rsi_filter_short = rsi > params["rsi_overbought"]
        adx_filter_short = adx > 25
        short_entry = cross_below_middle & rsi_filter_short & adx_filter_short

        # Define exit conditions
        # Exit long/short when price crosses middle
        exit_long = cross_below_middle
        exit_short = cross_above_middle

        # Exit when adx < 20
        adx_filter_exit = adx < 20
        exit_long &= ~adx_filter_exit
        exit_short &= ~adx_filter_exit

        # Mark entries and exits
        long_mask = long_entry
        short_mask = short_entry

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels for long entries
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        entry_long_mask = signals == 1.0
        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]

        # Set SL/TP levels for short entries
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_short_mask = signals == -1.0
        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals