from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_with_volatility_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr']

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
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Bollinger bands
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        # Compute previous values for crossovers
        prev_close = np.roll(close, 1)
        prev_upper = np.roll(upper, 1)
        prev_lower = np.roll(lower, 1)
        prev_middle = np.roll(middle, 1)
        prev_rsi = np.roll(rsi, 1)

        prev_close[0] = np.nan
        prev_upper[0] = np.nan
        prev_lower[0] = np.nan
        prev_middle[0] = np.nan
        prev_rsi[0] = np.nan

        # Entry conditions
        # Long entry: close crosses above upper band, rsi > 50, atr > atr.mean(20)
        cross_above_upper = (close > upper) & (prev_close <= prev_upper)
        rsi_long = rsi > params["rsi_overbought"]
        atr_long = atr > np.nanmean(atr, axis=0)
        long_entry = cross_above_upper & rsi_long & atr_long

        # Short entry: close crosses below lower band, rsi < 50, atr > atr.mean(20)
        cross_below_lower = (close < lower) & (prev_close >= prev_lower)
        rsi_short = rsi < params["rsi_oversold"]
        atr_short = atr > np.nanmean(atr, axis=0)
        short_entry = cross_below_lower & rsi_short & atr_short

        # Exit conditions
        # Exit long: close crosses below middle band, or rsi > 70, or rsi < 30
        cross_below_middle = (close < middle) & (prev_close >= prev_middle)
        rsi_exit_long = (rsi > params["rsi_overbought"]) | (rsi < params["rsi_oversold"])
        long_exit = cross_below_middle | rsi_exit_long

        # Exit short: close crosses above middle band, or rsi > 70, or rsi < 30
        cross_above_middle = (close > middle) & (prev_close <= prev_middle)
        rsi_exit_short = (rsi > params["rsi_overbought"]) | (rsi < params["rsi_oversold"])
        short_exit = cross_above_middle | rsi_exit_short

        # Set masks
        long_mask = long_entry
        short_mask = short_entry

        # Apply exit conditions
        # Long exit
        long_exit_mask = long_exit & (np.roll(signals, 1) == 1.0)
        long_mask = long_mask | long_exit_mask

        # Short exit
        short_exit_mask = short_exit & (np.roll(signals, 1) == -1.0)
        short_mask = short_mask | short_exit_mask

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set warmup period
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]

        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
