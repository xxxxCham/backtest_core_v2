from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='hmstrusdc_refined_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr', 'adx']

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
        # implement explicit LONG / SHORT / FLAT logic
        # warmup protection
        signals.iloc[:warmup] = 0.0

        # Extract indicators
        bb = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])

        # Prepare band arrays
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        # Entry conditions
        close = df["close"].values
        rsi_overbought = params.get("rsi_overbought", 70)
        rsi_oversold = params.get("rsi_oversold", 30)
        adx_threshold = 25

        # Cross detection
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_upper = np.roll(upper, 1)
        prev_upper[0] = np.nan
        prev_lower = np.roll(lower, 1)
        prev_lower[0] = np.nan
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan

        # Long entry: close crosses above upper band, rsi < 70, adx > 25
        cross_above_upper = (close > upper) & (prev_close <= prev_upper)
        long_entry_cond = (cross_above_upper) & (rsi < rsi_overbought) & (adx > adx_threshold)
        long_mask = long_entry_cond

        # Short entry: close crosses below lower band, rsi > 30, adx > 25
        cross_below_lower = (close < lower) & (prev_close >= prev_lower)
        short_entry_cond = (cross_below_lower) & (rsi > rsi_oversold) & (adx > adx_threshold)
        short_mask = short_entry_cond

        # Exit conditions
        # Exit long when close crosses below middle band
        cross_below_middle = (close < middle) & (prev_close >= prev_middle)
        long_exit_mask = cross_below_middle

        # Exit short when close crosses above middle band
        cross_above_middle = (close > middle) & (prev_close <= prev_middle)
        short_exit_mask = cross_above_middle

        # Adx filter for exit
        adx_exit_threshold = 20
        adx_weak = adx < adx_exit_threshold

        # Combine exit conditions
        long_exit_mask = long_exit_mask | adx_weak
        short_exit_mask = short_exit_mask | adx_weak

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set stop-loss and take-profit levels for long entries
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        entry_long = (signals == 1.0)
        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]

        # Set stop-loss and take-profit levels for short entries
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_short = (signals == -1.0)
        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
