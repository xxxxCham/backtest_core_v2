from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_rsi_adx')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr', 'adx']

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
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])

        # Prepare price arrays
        close = df["close"].values

        # Define thresholds
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        # Cross detection helpers
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        prev_adx = np.roll(adx, 1)
        prev_adx[0] = np.nan

        # Long entry: close crosses above lower band, RSI < oversold, ADX > 25
        close_above_lower = (close > np.nan_to_num(bb["lower"]))
        prev_close_below_lower = (prev_close <= np.nan_to_num(bb["lower"]))
        cross_above_lower = (close_above_lower) & (prev_close_below_lower)
        rsi_below_oversold = (rsi < rsi_oversold)
        adx_above_25 = (adx > 25)
        long_entry = cross_above_lower & rsi_below_oversold & adx_above_25

        # Short entry: close crosses below upper band, RSI > overbought, ADX > 25
        close_below_upper = (close < np.nan_to_num(bb["upper"]))
        prev_close_above_upper = (prev_close >= np.nan_to_num(bb["upper"]))
        cross_below_upper = (close_below_upper) & (prev_close_above_upper)
        rsi_above_overbought = (rsi > rsi_overbought)
        short_entry = cross_below_upper & rsi_above_overbought & adx_above_25

        # Exit conditions: close crosses below middle band or ADX < 20
        close_below_middle = (close < np.nan_to_num(bb["middle"]))
        prev_close_above_middle = (prev_close >= np.nan_to_num(bb["middle"]))
        cross_below_middle = (close_below_middle) & (prev_close_above_middle)
        adx_below_20 = (adx < 20)
        exit_condition = cross_below_middle | adx_below_20

        # Apply long and short masks
        long_mask = long_entry
        short_mask = short_entry

        # Apply exit condition
        exit_long_mask = exit_condition & (signals != 1.0)
        exit_short_mask = exit_condition & (signals != -1.0)

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Write ATR-based SL/TP levels
        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
