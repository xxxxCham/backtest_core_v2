from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr']

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
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Prepare cross detection
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan

        # Entry conditions
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])

        # Long entry: close crosses above lower band AND rsi < oversold
        long_entry_cross = (close > indicators['bollinger']['lower']) & (prev_close <= indicators['bollinger']['lower'])
        long_entry_rsi = rsi < params["rsi_oversold"]
        long_mask = long_entry_cross & long_entry_rsi

        # Short entry: close crosses below upper band AND rsi > overbought
        short_entry_cross = (close < indicators['bollinger']['upper']) & (prev_close >= indicators['bollinger']['upper'])
        short_entry_rsi = rsi > params["rsi_overbought"]
        short_mask = short_entry_cross & short_entry_rsi

        # Exit conditions
        exit_middle = (close > indicators['bollinger']['middle']) & (prev_close <= indicators['bollinger']['middle'])
        exit_rsi_long = (rsi > params["rsi_overbought"]) & (prev_rsi <= params["rsi_overbought"])
        exit_rsi_short = (rsi < params["rsi_oversold"]) & (prev_rsi >= params["rsi_oversold"])

        # Combine exit conditions
        exit_long = exit_middle | exit_rsi_long
        exit_short = exit_middle | exit_rsi_short

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Handle exits
        exit_long_mask = np.zeros(n, dtype=bool)
        exit_short_mask = np.zeros(n, dtype=bool)
        prev_signal = np.roll(signals, 1)
        prev_signal[0] = 0.0

        # Exit long positions
        exit_long_mask = (signals == 1.0) & (exit_long | (prev_signal == 0.0))
        signals[exit_long_mask] = 0.0

        # Exit short positions
        exit_short_mask = (signals == -1.0) & (exit_short | (prev_signal == 0.0))
        signals[exit_short_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Write SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
