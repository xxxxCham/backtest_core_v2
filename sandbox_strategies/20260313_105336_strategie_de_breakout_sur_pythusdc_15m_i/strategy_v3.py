from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='pyth_usdc_mean_reversion_bollinger_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'atr', 'rsi']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 1.0,
         'tp_atr_mult': 2.0,
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
                default=1.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=6.0,
                default=2.0,
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

        # Extract indicators
        bb = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values
        open_ = df["open"].values

        # Prepare bands
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        # Prepare previous values for crossovers
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_upper = np.roll(upper, 1)
        prev_upper[0] = np.nan
        prev_lower = np.roll(lower, 1)
        prev_lower[0] = np.nan
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan

        # Entry conditions
        cross_above_lower = (close > lower) & (prev_close <= prev_lower)
        cross_below_upper = (close < upper) & (prev_close >= prev_upper)
        rsi_oversold = rsi < params["rsi_oversold"]
        rsi_overbought = rsi > params["rsi_overbought"]

        # Long entry: close crosses above lower band AND RSI < 30
        long_entry = cross_above_lower & rsi_oversold

        # Short entry: close crosses below upper band AND RSI > 70
        short_entry = cross_below_upper & rsi_overbought

        long_mask = long_entry
        short_mask = short_entry

        # Exit conditions
        cross_above_middle = (close > middle) & (prev_close <= prev_middle)
        cross_below_middle = (close < middle) & (prev_close >= prev_middle)
        exit_long = cross_above_middle
        exit_short = cross_below_middle

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels for long entries
        entry_long_mask = (signals == 1.0)
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]

        # Set SL/TP levels for short entries
        entry_short_mask = (signals == -1.0)
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
