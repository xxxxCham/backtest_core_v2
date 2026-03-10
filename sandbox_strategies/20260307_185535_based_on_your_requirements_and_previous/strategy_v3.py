from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_macd_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'macd', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'donchian_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'donchian_period': ParameterSpec(
                name='donchian_period',
                min_val=10,
                max_val=50,
                default=20,
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
        dc = indicators['donchian']
        macd_d = indicators['macd']
        atr = np.nan_to_num(indicators['atr'])

        close = df["close"].values
        donchian_period = int(params.get("donchian_period", 20))

        # Compute Donchian bands
        upper = np.nan_to_num(dc["upper"])
        middle = np.nan_to_num(dc["middle"])
        lower = np.nan_to_num(dc["lower"])

        # Compute MACD lines
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        signal_line = np.nan_to_num(macd_d["signal"])

        # Compute previous values for crossovers
        prev_upper = np.roll(upper, 1)
        prev_lower = np.roll(lower, 1)
        prev_middle = np.roll(middle, 1)
        prev_macd = np.roll(indicators['macd']['macd'], 1)
        prev_signal = np.roll(signal_line, 1)

        # Set first values to NaN
        prev_upper[0] = np.nan
        prev_lower[0] = np.nan
        prev_middle[0] = np.nan
        prev_macd[0] = np.nan
        prev_signal[0] = np.nan

        # Entry conditions
        # Long entry: close crosses above upper band AND macd > signal
        long_entry = (close > upper) & (prev_upper <= upper) & (indicators['macd']['macd'] > signal_line) & (prev_macd <= signal_line)

        # Short entry: close crosses below lower band AND macd < signal
        short_entry = (close < lower) & (prev_lower >= lower) & (indicators['macd']['macd'] < signal_line) & (prev_macd >= signal_line)

        # Exit conditions
        # Long exit: close crosses below middle band OR macd crosses below signal
        long_exit = (close < middle) & (prev_middle >= middle) | (indicators['macd']['macd'] < signal_line) & (prev_macd >= signal_line)

        # Short exit: close crosses above middle band OR macd crosses above signal
        short_exit = (close > middle) & (prev_middle <= middle) | (indicators['macd']['macd'] > signal_line) & (prev_macd <= signal_line)

        # Set masks
        long_mask = long_entry
        short_mask = short_entry

        # Apply exits
        exit_long_mask = long_exit
        exit_short_mask = short_exit

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exits
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Write SL/TP levels for long entries
        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        entry_long_mask = long_mask
        if np.any(entry_long_mask):
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        # Write SL/TP levels for short entries
        entry_short_mask = short_mask
        if np.any(entry_short_mask):
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
