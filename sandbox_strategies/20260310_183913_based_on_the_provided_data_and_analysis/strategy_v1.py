from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='hmstrusdc_refined')

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
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        # Compute atr_mean for filtering
        atr_mean = np.nanmean(atr)

        # Entry conditions
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan

        # Cross up/down helpers
        prev_upper = np.roll(upper, 1)
        prev_upper[0] = np.nan
        cross_above_upper = (close > upper) & (prev_close <= prev_upper)

        prev_lower = np.roll(lower, 1)
        prev_lower[0] = np.nan
        cross_below_lower = (close < lower) & (prev_close >= prev_lower)

        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        cross_above_middle = (close > middle) & (prev_close <= prev_middle)
        cross_below_middle = (close < middle) & (prev_close >= prev_middle)

        # Long entry: close crosses above upper band AND rsi < 70 AND atr > atr_mean
        long_entry = cross_above_upper & (rsi < params["rsi_overbought"]) & (atr > atr_mean)

        # Short entry: close crosses below lower band AND rsi > 30 AND atr > atr_mean
        short_entry = cross_below_lower & (rsi > params["rsi_oversold"]) & (atr > atr_mean)

        # Exit conditions
        exit_long = cross_below_middle | (rsi > params["rsi_overbought"]) | (rsi < params["rsi_oversold"])
        exit_short = cross_above_middle | (rsi > params["rsi_overbought"]) | (rsi < params["rsi_oversold"])

        # Set masks
        long_mask = long_entry
        short_mask = short_entry

        # Apply exits
        exit_long_mask = exit_long
        exit_short_mask = exit_short

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels on entry bars
        entry_long_mask = long_mask
        entry_short_mask = short_mask

        if np.any(entry_long_mask):
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]

        if np.any(entry_short_mask):
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
