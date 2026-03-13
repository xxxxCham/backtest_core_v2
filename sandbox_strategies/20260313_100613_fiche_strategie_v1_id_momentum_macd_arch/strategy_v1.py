from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_macd')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'macd_fast': 10,
         'macd_signal': 7,
         'macd_slow': 26,
         'rsi_overbought': 80,
         'rsi_oversold': 30,
         'rsi_period': 8,
         'stop_atr_mult': 3.0,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=50,
                default=8,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=5.0,
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
        macd_d = indicators['macd']
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        indicators['macd']['signal'] = np.nan_to_num(macd_d["signal"])
        macd_hist = np.nan_to_num(macd_d["histogram"])

        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Cross detection
        prev_macd_line = np.roll(indicators['macd']['macd'], 1)
        prev_macd_signal = np.roll(indicators['macd']['signal'], 1)
        prev_macd_line[0] = np.nan
        prev_macd_signal[0] = np.nan

        cross_up = (indicators['macd']['macd'] > indicators['macd']['signal']) & (prev_macd_line <= prev_macd_signal)
        cross_down = (indicators['macd']['macd'] < indicators['macd']['signal']) & (prev_macd_line >= prev_macd_signal)

        # Entry conditions
        long_condition = cross_up & (rsi > 40) & (rsi < 70)
        short_condition = cross_down & (rsi > 30) & (rsi < 60)

        long_mask = long_condition
        short_mask = short_condition

        # Exit conditions
        prev_macd_hist = np.roll(macd_hist, 1)
        prev_macd_hist[0] = np.nan
        sign_change = (macd_hist * prev_macd_hist) < 0

        rsi_overbought = rsi > params["rsi_overbought"]
        rsi_oversold = rsi < params["rsi_oversold"]

        exit_long = sign_change | rsi_overbought | rsi_oversold
        exit_short = sign_change | rsi_overbought | rsi_oversold

        # Apply exit signals
        exit_long_mask = exit_long & (signals == 1.0)
        exit_short_mask = exit_short & (signals == -1.0)

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # ATR-based risk management
        close = df["close"].values
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        entry_long_mask = (signals == 1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        # Short entries
        entry_short_mask = (signals == -1.0)
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
