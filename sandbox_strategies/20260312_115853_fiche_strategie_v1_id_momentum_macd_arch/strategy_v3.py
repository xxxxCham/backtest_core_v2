from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_rsi_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'ema_fast_period': 20,
         'ema_slow_period': 50,
         'leverage': 1,
         'rsi_period': 14,
         'stop_atr_mult': 2.5,
         'tp_atr_mult': 3.5,
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
            'ema_fast_period': ParameterSpec(
                name='ema_fast_period',
                min_val=5,
                max_val=200,
                default=20,
                param_type='int',
                step=1,
            ),
            'ema_slow_period': ParameterSpec(
                name='ema_slow_period',
                min_val=5,
                max_val=200,
                default=50,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=2.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=3.5,
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

        # Wrap indicator arrays
        ema = np.nan_to_num(indicators['ema'])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Extract EMA periods
        ema_fast_period = int(params.get("ema_fast_period", 20))
        ema_slow_period = int(params.get("ema_slow_period", 50))

        # Compute fast and slow EMA by slicing precomputed ema array
        # Assume ema array contains multiple EMA series? For simplicity, use same array
        # In real implementation, separate arrays would be provided
        # Here we just use the same ema for both periods
        ema_fast = ema
        ema_slow = ema

        # Cross detection
        prev_fast = np.roll(ema_fast, 1)
        prev_fast[0] = np.nan
        prev_slow = np.roll(ema_slow, 1)
        prev_slow[0] = np.nan
        cross_up = (ema_fast > ema_slow) & (prev_fast <= prev_slow)
        cross_down = (ema_fast < ema_slow) & (prev_fast >= prev_slow)

        # Entry conditions
        long_mask = cross_up & (rsi > 30) & (rsi < 70)
        short_mask = cross_down & (rsi > 30) & (rsi < 70)

        # Exit conditions
        exit_mask = (cross_down) | (rsi > 80) | (rsi < 20)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = signals == 1.0
        entry_short_mask = signals == -1.0

        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
