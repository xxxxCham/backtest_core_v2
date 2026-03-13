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
        return {'leverage': 1,
         'macd_fast_period': 13,
         'macd_signal_period': 10,
         'macd_slow_period': 31,
         'rsi_overbought': 80,
         'rsi_oversold': 20,
         'rsi_period': 14,
         'stop_atr_mult': 2.0,
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
                min_val=1.0,
                max_val=5.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
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
        macd_d = indicators['macd']
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        indicators['macd']['signal'] = np.nan_to_num(macd_d["signal"])
        macd_hist = np.nan_to_num(macd_d["histogram"])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Entry conditions
        # Long entry: histogram positive, rsi < 70, atr > atr.mean(20)
        long_entry_condition = (macd_hist > 0) & (rsi < 70)
        # Short entry: histogram negative, rsi > 30, atr > atr.mean(20)
        short_entry_condition = (macd_hist < 0) & (rsi > 30)

        # Apply entry conditions
        long_mask = long_entry_condition
        short_mask = short_entry_condition

        # Exit conditions
        # Cross zero of histogram or RSI overbought/oversold
        prev_macd_hist = np.roll(macd_hist, 1)
        prev_macd_hist[0] = np.nan
        hist_cross_zero = (macd_hist > 0) & (prev_macd_hist <= 0) | (macd_hist < 0) & (prev_macd_hist >= 0)

        rsi_exit = (rsi > params["rsi_overbought"]) | (rsi < params["rsi_oversold"])

        exit_condition = hist_cross_zero | rsi_exit

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exit condition to existing positions
        long_positions = (signals == 1.0)
        short_positions = (signals == -1.0)

        # Reset signals to flat on exit
        signals[long_positions & exit_condition] = 0.0
        signals[short_positions & exit_condition] = 0.0

        # ATR-based SL/TP logic
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        close = df["close"].values
        entry_long = signals == 1.0
        entry_short = signals == -1.0

        if np.any(entry_long):
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]

        if np.any(entry_short):
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
