from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_adx_sma_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'sma', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 2.0, 'tp_atr_mult': 5.5, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=10.0,
                default=5.5,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=20,
                max_val=100,
                default=50,
                param_type='int',
                step=10,
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
        close = np.nan_to_num(df["close"].values)
        sma = np.nan_to_num(indicators['sma'])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        dc = indicators['donchian']
        upper = np.nan_to_num(dc["upper"])
        middle = np.nan_to_num(dc["middle"])
        lower = np.nan_to_num(dc["lower"])
        atr = np.nan_to_num(indicators['atr'])

        # Cross helpers
        def cross_up(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1); prev_y = np.roll(y, 1)
            prev_x[0] = np.nan; prev_y[0] = np.nan
            return (x > y) & (prev_x <= prev_y)

        def cross_down(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1); prev_y = np.roll(y, 1)
            prev_x[0] = np.nan; prev_y[0] = np.nan
            return (x < y) & (prev_x >= prev_y)

        def cross_any(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            return cross_up(x, y) | cross_down(x, y)

        # Entry conditions
        long_mask = (close > upper) & (close > sma) & (adx_val > 30)
        short_mask = (close < lower) & (close < sma) & (adx_val > 30)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        long_exit = cross_down(close, sma) | (adx_val < 20) | cross_any(close, middle)
        short_exit = cross_up(close, sma) | (adx_val < 20) | cross_any(close, middle)

        # Apply exits only when in a position
        in_long = signals == 1.0
        in_short = signals == -1.0
        signals[in_long & long_exit] = 0.0
        signals[in_short & short_exit] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 5.5))

        # Long entry levels
        entry_long = (signals == 1.0)
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        # Short entry levels
        entry_short = (signals == -1.0)
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
