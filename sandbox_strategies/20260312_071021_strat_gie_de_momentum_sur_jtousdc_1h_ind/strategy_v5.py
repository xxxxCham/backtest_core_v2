from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_rsi_momentum_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
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
        }

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        # Initialize masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Warmup period
        signals.iloc[:warmup] = 0.0

        # Get indicators
        ema = np.nan_to_num(indicators['ema'])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Close prices
        close = df["close"].values

        # Entry conditions
        long_entry = (close > ema) & (rsi < params["rsi_overbought"])
        short_entry = (close < ema) & (rsi > params["rsi_oversold"])

        # Exit conditions
        long_exit = (close < ema)
        short_exit = (close > ema)

        # Cross detection logic
        prev_close = np.roll(close, 1)
        prev_ema = np.roll(ema, 1)

        cross_up = (close > prev_ema) & (prev_close <= prev_ema)
        cross_down = (close < prev_ema) & (prev_close >= prev_ema)

        # Update masks with entry conditions
        long_mask[warmup:] = long_entry[warmup:]
        short_mask[warmup:] = short_entry[warmup:]

        # Apply exit conditions
        long_mask &= ~cross_down
        short_mask &= ~cross_up

        # Assign signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Risk management with ATR
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_mask = (signals == 1.0)
        exit_entry_mask = (signals == -1.0)

        # Set stop loss and take profit levels for long entries
        df.loc[entry_mask, "bb_stop_long"] = close[entry_mask] - 2 * atr[entry_mask]
        df.loc[entry_mask, "bb_tp_long"] = close[entry_mask] + 2 * atr[entry_mask]

        # Set stop loss and take profit levels for short entries
        df.loc[exit_entry_mask, "bb_stop_short"] = close[exit_entry_mask] + 2 * atr[exit_entry_mask]
        df.loc[exit_entry_mask, "bb_tp_short"] = close[exit_entry_mask] - 2 * atr[exit_entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
