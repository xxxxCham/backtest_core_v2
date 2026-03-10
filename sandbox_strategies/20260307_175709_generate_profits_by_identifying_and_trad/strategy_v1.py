from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bb_macd_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'macd', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
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
                min_val=1.0,
                max_val=10.0,
                default=3.0,
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
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        macd_d = indicators['macd']
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        signal_line = np.nan_to_num(macd_d["signal"])

        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Create previous arrays for crossovers
        prev_upper = np.roll(upper, 1)
        prev_upper[0] = np.nan
        prev_lower = np.roll(lower, 1)
        prev_lower[0] = np.nan
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        prev_macd = np.roll(indicators['macd']['macd'], 1)
        prev_macd[0] = np.nan
        prev_signal = np.roll(signal_line, 1)
        prev_signal[0] = np.nan

        # Entry conditions
        # Long entry: close crosses above upper band AND macd > signal
        close_above_upper = (close > upper)
        prev_close_below_upper = (prev_upper >= close)
        long_entry = close_above_upper & prev_close_below_upper & (indicators['macd']['macd'] > signal_line)

        # Short entry: close crosses below lower band AND macd < signal
        close_below_lower = (close < lower)
        prev_close_above_lower = (prev_lower <= close)
        short_entry = close_below_lower & prev_close_above_lower & (indicators['macd']['macd'] < signal_line)

        # Exit conditions
        # Long exit: close crosses below middle band OR macd crosses below signal
        close_below_middle = (close < middle)
        prev_close_above_middle = (prev_middle >= close)
        long_exit = close_below_middle & prev_close_above_middle

        macd_cross_below_signal = (indicators['macd']['macd'] < signal_line) & (prev_macd >= prev_signal)
        long_exit |= macd_cross_below_signal

        # Short exit: close crosses above middle band OR macd crosses above signal
        close_above_middle = (close > middle)
        prev_close_below_middle = (prev_middle <= close)
        short_exit = close_above_middle & prev_close_below_middle

        macd_cross_above_signal = (indicators['macd']['macd'] > signal_line) & (prev_macd <= prev_signal)
        short_exit |= macd_cross_above_signal

        # Apply masks
        long_mask = long_entry
        short_mask = short_entry

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exit conditions
        exit_long_mask = long_exit
        exit_short_mask = short_exit

        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based stop-loss and take-profit
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
