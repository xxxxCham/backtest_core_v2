from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_momentum_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'momentum', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 30}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
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
            'warmup': ParameterSpec(
                name='warmup',
                min_val=10,
                max_val=50,
                default=30,
                param_type='int',
                step=5,
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

        # Wrap indicator arrays
        ema = np.nan_to_num(indicators['ema'])
        momentum = np.nan_to_num(indicators['momentum'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Helper cross functions
        def cross_up(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return (x > y) & (prev_x <= prev_y)

        def cross_down(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return (x < y) & (prev_x >= prev_y)

        # Entry conditions
        long_mask = (close > ema) & (momentum > 0)
        short_mask = (close < ema) & (momentum < 0)

        # Exit conditions (set to 0 by leaving signals unchanged for flat)
        # For long positions: exit when close crosses below ema or momentum falls below zero
        # For short positions: exit when close crosses above ema or momentum rises above zero
        # These exits are handled by the engine; signals only indicate entries

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup protection: zero out first 50 bars
        signals.iloc[:50] = 0.0

        # ATR based SL/TP levels
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
