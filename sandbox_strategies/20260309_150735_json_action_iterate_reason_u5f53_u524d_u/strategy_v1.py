from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_rsi_trend_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'adx', 'atr']

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
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])
        close = np.nan_to_num(df["close"].values)
        atr = np.nan_to_num(indicators['atr'])

        # Define thresholds
        rsi_overbought = params.get("rsi_overbought", 70)
        rsi_oversold = params.get("rsi_oversold", 30)
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Prepare band values
        upper_band = np.nan_to_num(bb["upper"])
        lower_band = np.nan_to_num(bb["lower"])
        middle_band = np.nan_to_num(bb["middle"])

        # Cross detection
        prev_upper_band = np.roll(upper_band, 1)
        prev_lower_band = np.roll(lower_band, 1)
        prev_middle_band = np.roll(middle_band, 1)
        prev_upper_band[0] = np.nan
        prev_lower_band[0] = np.nan
        prev_middle_band[0] = np.nan

        # Entry conditions
        # Long entry: close crosses above upper band, rsi < 70, adx > 25
        cross_above_upper = (close > upper_band) & (prev_upper_band <= upper_band)
        rsi_condition_long = rsi < rsi_overbought
        adx_condition_long = adx > 25
        long_entry = cross_above_upper & rsi_condition_long & adx_condition_long

        # Short entry: close crosses below lower band, rsi > 30, adx > 25
        cross_below_lower = (close < lower_band) & (prev_lower_band >= lower_band)
        rsi_condition_short = rsi > rsi_oversold
        adx_condition_short = adx > 25
        short_entry = cross_below_lower & rsi_condition_short & adx_condition_short

        # Exit conditions
        # Exit long: close crosses below middle band OR adx < 20
        cross_below_middle = (close < middle_band) & (prev_middle_band >= middle_band)
        adx_condition_exit = adx < 20
        long_exit = cross_below_middle | adx_condition_exit

        # Exit short: close crosses above middle band OR adx < 20
        cross_above_middle = (close > middle_band) & (prev_middle_band <= middle_band)
        short_exit = cross_above_middle | adx_condition_exit

        # Set masks
        long_mask = long_entry
        short_mask = short_entry

        # Apply exits
        # Create a mask of currently open long positions
        long_positions = np.zeros(n, dtype=bool)
        long_positions[long_mask] = True
        # Find when long positions should close
        long_exit_mask = np.zeros(n, dtype=bool)
        long_exit_mask[long_exit] = True
        # Combine exit conditions for longs
        long_exit_mask = long_exit_mask & long_positions
        # Similarly for shorts
        short_positions = np.zeros(n, dtype=bool)
        short_positions[short_mask] = True
        short_exit_mask = np.zeros(n, dtype=bool)
        short_exit_mask[short_exit] = True
        short_exit_mask = short_exit_mask & short_positions

        # Update signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[long_exit_mask] = 0.0
        signals[short_exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based stop loss and take profit
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals