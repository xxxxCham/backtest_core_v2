from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='builder_strategy')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=1,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=2.0,
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

        signals.iloc[:warmup] = 0.0

        rsi_fast = np.nan_to_num(indicators['rsi'])
        rsi_slow = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = np.nan_to_num(df["close"])

        # Short signal: RSI(5) crosses below RSI(14)
        rsi_fast_period = params.get("rsi_fast_period", 5)
        rsi_slow_period = params.get("rsi_slow_period", 14)
        prev_rsi_fast = np.roll(rsi_fast, 1)
        prev_rsi_fast[0] = np.nan
        short_mask = (rsi_fast < rsi_slow) & (prev_rsi_fast >= rsi_slow)

        # Write SL/TP columns into df if using ATR-based risk management
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        entry_mask = (signals == 1.0)  # boolean mask of long entries
        df.loc[entry_mask, "bb_stop_long"] = close[entry_mask] - stop_atr_mult * atr[entry_mask]
        df.loc[entry_mask, "bb_tp_long"] = close[entry_mask] + tp_atr_mult * atr[entry_mask]

        signals[short_mask] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals
