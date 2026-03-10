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

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Extract indicators
        dc = indicators['donchian']
        macd_d = indicators['macd']
        atr = np.nan_to_num(indicators['atr'])

        close = np.nan_to_num(df["close"].values)
        indicators['donchian']['upper'] = np.nan_to_num(dc["upper"])
        indicators['donchian']['lower'] = np.nan_to_num(dc["lower"])
        indicators['donchian']['middle'] = np.nan_to_num(dc["middle"])
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        indicators['macd']['signal'] = np.nan_to_num(macd_d["signal"])

        # Create lagged arrays for crossovers
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_donchian_upper = np.roll(indicators['donchian']['upper'], 1)
        prev_donchian_upper[0] = np.nan
        prev_donchian_lower = np.roll(indicators['donchian']['lower'], 1)
        prev_donchian_lower[0] = np.nan
        prev_macd_line = np.roll(indicators['macd']['macd'], 1)
        prev_macd_line[0] = np.nan
        prev_macd_signal = np.roll(indicators['macd']['signal'], 1)
        prev_macd_signal[0] = np.nan

        # Entry conditions
        # Long entry: close crosses above indicators['donchian']['upper'] AND macd.macos > macd.macosignal
        cross_above_upper = (close > indicators['donchian']['upper']) & (prev_close <= prev_donchian_upper)
        macd_long_condition = (indicators['macd']['macd'] > indicators['macd']['signal']) & (prev_macd_line <= prev_macd_signal)
        long_entry = cross_above_upper & macd_long_condition

        # Short entry: close crosses below indicators['donchian']['lower'] AND macd.macos < macd.macosignal
        cross_below_lower = (close < indicators['donchian']['lower']) & (prev_close >= prev_donchian_lower)
        macd_short_condition = (indicators['macd']['macd'] < indicators['macd']['signal']) & (prev_macd_line >= prev_macd_signal)
        short_entry = cross_below_lower & macd_short_condition

        # Exit conditions
        # Exit long: close crosses below indicators['donchian']['middle'] OR macd.macos crosses below macd.macosignal
        cross_below_middle = (close < indicators['donchian']['middle']) & (prev_close >= indicators['donchian']['middle'])
        macd_exit_long = (indicators['macd']['macd'] < indicators['macd']['signal']) & (prev_macd_line >= prev_macd_signal)
        long_exit = cross_below_middle | macd_exit_long

        # Exit short: close crosses above indicators['donchian']['middle'] OR macd.macos crosses above macd.macosignal
        cross_above_middle = (close > indicators['donchian']['middle']) & (prev_close <= indicators['donchian']['middle'])
        macd_exit_short = (indicators['macd']['macd'] > indicators['macd']['signal']) & (prev_macd_line <= prev_macd_signal)
        short_exit = cross_above_middle | macd_exit_short

        # Apply signals
        long_mask = long_entry
        short_mask = short_entry

        # Apply exits
        long_exit_mask = long_exit & (np.roll(signals, 1) == 1.0)
        short_exit_mask = short_exit & (np.roll(signals, 1) == -1.0)

        # Clear signals on exit
        signals[long_exit_mask] = 0.0
        signals[short_exit_mask] = 0.0

        # Set new signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based risk management
        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Set ATR-based SL/TP for long entries
        entry_long_mask = (signals == 1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        # Set ATR-based SL/TP for short entries
        entry_short_mask = (signals == -1.0)
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
