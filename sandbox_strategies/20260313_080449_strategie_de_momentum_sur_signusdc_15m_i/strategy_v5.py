from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='rsi_bollinger_atr_momentum')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'bollinger', 'atr']

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
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=4.5,
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
        rsi = np.nan_to_num(indicators['rsi'])
        bb = indicators['bollinger']
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Cross detection helpers
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        rsi_cross_up = (rsi > 30) & (prev_rsi <= 30)
        rsi_cross_down = (rsi < 70) & (prev_rsi >= 70)

        # Entry conditions
        long_condition = (close > indicators['bollinger']['middle']) & (rsi < 50) & rsi_cross_up
        short_condition = (close < indicators['bollinger']['middle']) & (rsi > 50) & rsi_cross_down

        long_mask = long_condition
        short_mask = short_condition

        # Exit conditions
        exit_long = (close < indicators['bollinger']['middle']) | (rsi > 70) | (rsi < 30)
        exit_short = (close > indicators['bollinger']['middle']) | (rsi > 70) | (rsi < 30)

        # Apply exits
        exit_long_mask = np.zeros(n, dtype=bool)
        exit_short_mask = np.zeros(n, dtype=bool)
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan

        # Long exit conditions
        long_exit_cross = (close < indicators['bollinger']['middle']) & (prev_close >= prev_bb_middle)
        long_exit_rsi = (rsi > 70) | (rsi < 30)
        exit_long_mask = long_exit_cross | long_exit_rsi

        # Short exit conditions
        short_exit_cross = (close > indicators['bollinger']['middle']) & (prev_close <= prev_bb_middle)
        short_exit_rsi = (rsi > 70) | (rsi < 30)
        exit_short_mask = short_exit_cross | short_exit_rsi

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels for long entries
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        entry_mask = (signals == 1.0)
        if entry_mask.any():
            df.loc[entry_mask, "bb_stop_long"] = close[entry_mask] - params["stop_atr_mult"] * atr[entry_mask]
            df.loc[entry_mask, "bb_tp_long"] = close[entry_mask] + params["tp_atr_mult"] * atr[entry_mask]

        # Set SL/TP levels for short entries
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        short_entry_mask = (signals == -1.0)
        if short_entry_mask.any():
            df.loc[short_entry_mask, "bb_stop_short"] = close[short_entry_mask] + params["stop_atr_mult"] * atr[short_entry_mask]
            df.loc[short_entry_mask, "bb_tp_short"] = close[short_entry_mask] - params["tp_atr_mult"] * atr[short_entry_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
