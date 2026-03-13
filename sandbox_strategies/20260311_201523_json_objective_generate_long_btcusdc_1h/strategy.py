from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='rsi_ema_mean_reversion')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'ema', 'atr']

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

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Extract indicators
        rsi = np.nan_to_num(indicators['rsi'])
        ema = np.nan_to_num(indicators['ema'])
        close = df["close"].values
        atr = np.nan_to_num(indicators['atr'])

        # Compute previous values for crossovers
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        prev_ema = np.roll(ema, 1)
        prev_ema[0] = np.nan

        # Define crossovers
        rsi_cross_up = (rsi > prev_rsi) & (prev_rsi <= params.get("rsi_oversold", 30))
        rsi_cross_down = (rsi < prev_rsi) & (prev_rsi >= params.get("rsi_overbought", 70))

        # Long signal: RSI crosses above oversold and price is above EMA
        long_mask = (rsi_cross_up) & (close > ema)

        # Short signal: RSI crosses below overbought and price is below EMA
        short_mask = (rsi_cross_down) & (close < ema)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based SL/TP
        stop_atr_mult = 1.5
        tp_atr_mult = 2.0

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        entry_mask = (signals == 1.0)
        df.loc[entry_mask, "bb_stop_long"] = close[entry_mask] - stop_atr_mult * atr[entry_mask]
        df.loc[entry_mask, "bb_tp_long"] = close[entry_mask] + tp_atr_mult * atr[entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
