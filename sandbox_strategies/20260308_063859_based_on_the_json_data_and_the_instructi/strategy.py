from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_filtered_bollinger_reversal')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'atr', 'adx', 'rsi']

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
        atr = np.nan_to_num(indicators['atr'])
        adx_d = indicators['adx']
        adx_val = np.nan_to_num(adx_d["adx"])
        rsi = np.nan_to_num(indicators['rsi'])

        # Prepare band values
        upper_band = np.nan_to_num(bb["upper"])
        lower_band = np.nan_to_num(bb["lower"])
        middle_band = np.nan_to_num(bb["middle"])

        # Prepare close prices
        close = df["close"].values

        # Cross detection helpers
        prev_upper = np.roll(upper_band, 1)
        prev_lower = np.roll(lower_band, 1)
        prev_middle = np.roll(middle_band, 1)
        prev_upper[0] = np.nan
        prev_lower[0] = np.nan
        prev_middle[0] = np.nan

        # Entry conditions
        # Long entry: close crosses above lower band AND adx > 25 AND rsi < 30
        cross_above_lower = (close > lower_band) & (prev_lower <= lower_band)
        adx_trend = adx_val > 25
        rsi_oversold = rsi < params["rsi_oversold"]
        long_entry = cross_above_lower & adx_trend & rsi_oversold

        # Short entry: close crosses below upper band AND adx > 25 AND rsi > 70
        cross_below_upper = (close < upper_band) & (prev_upper >= upper_band)
        rsi_overbought = rsi > params["rsi_overbought"]
        short_entry = cross_below_upper & adx_trend & rsi_overbought

        # Exit conditions
        # Exit long: close crosses below middle band OR adx < 20
        cross_below_middle = (close < middle_band) & (prev_middle >= middle_band)
        adx_weak = adx_val < 20
        long_exit = cross_below_middle | adx_weak

        # Exit short: close crosses above middle band OR adx < 20
        cross_above_middle = (close > middle_band) & (prev_middle <= middle_band)
        short_exit = cross_above_middle | adx_weak

        # Apply masks
        long_mask = long_entry
        short_mask = short_entry

        # Mark exits
        exit_long_mask = long_exit
        exit_short_mask = short_exit

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        entry_long_mask = (signals == 1.0)
        if np.any(entry_long_mask):
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]

        # Short entries
        entry_short_mask = (signals == -1.0)
        if np.any(entry_short_mask):
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals