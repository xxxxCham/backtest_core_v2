from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_rsi_adx_trend_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_exit_threshold': 20,
         'adx_threshold': 25,
         'leverage': 1,
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
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=4.5,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'adx_threshold': ParameterSpec(
                name='adx_threshold',
                min_val=15,
                max_val=40,
                default=25,
                param_type='int',
                step=1,
            ),
            'adx_exit_threshold': ParameterSpec(
                name='adx_exit_threshold',
                min_val=10,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
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
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Prepare arrays
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])
        adx = np.nan_to_num(adx_d["adx"])

        # Set warmup
        signals.iloc[:warmup] = 0.0

        # Define thresholds
        adx_threshold = params.get("adx_threshold", 25)
        adx_exit_threshold = params.get("adx_exit_threshold", 20)
        rsi_overbought = params.get("rsi_overbought", 70)
        rsi_oversold = params.get("rsi_oversold", 30)

        # Cross detection
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_upper = np.roll(upper, 1)
        prev_upper[0] = np.nan
        prev_lower = np.roll(lower, 1)
        prev_lower[0] = np.nan
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        prev_adx = np.roll(adx, 1)
        prev_adx[0] = np.nan

        cross_above_upper = (close > upper) & (prev_close <= prev_upper)
        cross_below_lower = (close < lower) & (prev_close >= prev_lower)
        cross_above_middle = (close > middle) & (prev_close <= prev_middle)
        cross_below_middle = (close < middle) & (prev_close >= prev_middle)

        # Entry conditions
        long_condition = cross_above_upper & (rsi > rsi_overbought) & (adx > adx_threshold)
        short_condition = cross_below_lower & (rsi < rsi_oversold) & (adx > adx_threshold)

        # Exit conditions
        exit_long = cross_below_middle | (adx < adx_exit_threshold)
        exit_short = cross_above_middle | (adx < adx_exit_threshold)

        # Apply masks
        long_mask = long_condition
        short_mask = short_condition

        # Avoid consecutive same signals
        prev_signal = np.roll(signals, 1)
        prev_signal[0] = 0.0
        long_mask = long_mask & ~(prev_signal == 1.0)
        short_mask = short_mask & ~(prev_signal == -1.0)

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit signals
        exit_long_mask = exit_long & (prev_signal == 1.0)
        exit_short_mask = exit_short & (prev_signal == -1.0)
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Set SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params.get("stop_atr_mult", 1.5) * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params.get("tp_atr_mult", 3.0) * atr[entry_long_mask]

        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params.get("stop_atr_mult", 1.5) * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params.get("tp_atr_mult", 3.0) * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
