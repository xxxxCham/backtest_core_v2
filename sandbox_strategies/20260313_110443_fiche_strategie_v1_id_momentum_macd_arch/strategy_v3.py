from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_macd_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 2.5, 'tp_atr_mult': 2.5, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=4.0,
                default=2.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=4.0,
                default=2.5,
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
        macd_d = indicators['macd']
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        indicators['macd']['signal'] = np.nan_to_num(macd_d["signal"])
        macd_hist = np.nan_to_num(macd_d["histogram"])

        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Entry conditions
        # Long entry: MACD cross above signal, RSI between 35 and 60
        prev_macd_line = np.roll(indicators['macd']['macd'], 1)
        prev_macd_signal = np.roll(indicators['macd']['signal'], 1)
        prev_macd_line[0] = np.nan
        prev_macd_signal[0] = np.nan
        cross_up_macd = (indicators['macd']['macd'] > indicators['macd']['signal']) & (prev_macd_line <= prev_macd_signal)

        long_entry = cross_up_macd & (rsi > 35) & (rsi < 60)
        long_mask = long_entry

        # Short entry: MACD cross below signal, RSI between 30 and 60
        cross_down_macd = (indicators['macd']['macd'] < indicators['macd']['signal']) & (prev_macd_line >= prev_macd_signal)

        short_entry = cross_down_macd & (rsi > 30) & (rsi < 60)
        short_mask = short_entry

        # Exit conditions
        # Exit on histogram sign change, or RSI overbought/oversold
        prev_macd_hist = np.roll(macd_hist, 1)
        prev_macd_hist[0] = np.nan
        hist_sign_change = (macd_hist * prev_macd_hist < 0)

        rsi_exit_long = (rsi > 80) | (rsi < 20)
        rsi_exit_short = (rsi > 80) | (rsi < 20)

        exit_long = hist_sign_change | rsi_exit_long
        exit_short = hist_sign_change | rsi_exit_short

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set exit signals (FLAT)
        exit_long_mask = np.zeros(n, dtype=bool)
        exit_long_mask[1:] = exit_long[:-1]  # shift to next bar
        signals[exit_long_mask] = 0.0

        exit_short_mask = np.zeros(n, dtype=bool)
        exit_short_mask[1:] = exit_short[:-1]  # shift to next bar
        signals[exit_short_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based risk management
        stop_atr_mult = params.get("stop_atr_mult", 2.5)
        tp_atr_mult = params.get("tp_atr_mult", 2.5)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
