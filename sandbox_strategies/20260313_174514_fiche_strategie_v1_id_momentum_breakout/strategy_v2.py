from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_breakout_ichimoku_optimized')

    @property
    def required_indicators(self) -> List[str]:
        return ['ichimoku', 'volume_oscillator', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_threshold': 1.0,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 4.0,
         'warmup': 50}

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
                max_val=8.0,
                default=4.0,
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
            'atr_threshold': ParameterSpec(
                name='atr_threshold',
                min_val=0.5,
                max_val=3.0,
                default=1.0,
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

        # helper cross functions
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

        def cross_any(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            return cross_up(x, y) | cross_down(x, y)

        close = df["close"].values
        ichimoku = indicators['ichimoku']
        senkou_a = np.nan_to_num(indicators['ichimoku']["senkou_a"])
        senkou_b = np.nan_to_num(indicators['ichimoku']["senkou_b"])
        cloud_top = np.maximum(senkou_a, senkou_b)
        cloud_bottom = np.minimum(senkou_a, senkou_b)
        kijun = np.nan_to_num(indicators['ichimoku']["kijun"])
        volume_osc = np.nan_to_num(indicators['volume_oscillator'])
        atr = np.nan_to_num(indicators['atr'])

        atr_threshold = float(params.get("atr_threshold", 1.0))
        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 4.0))

        # Entry conditions
        long_mask = (close > cloud_top) & (volume_osc > 0.5) & (atr > atr_threshold)
        short_mask = (close < cloud_bottom) & (volume_osc < -0.5) & (atr > atr_threshold)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        exit_mask = (
            cross_down(close, kijun)
            | cross_any(volume_osc, np.zeros_like(volume_osc))
            | (atr < atr_threshold)
        )
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR-based SL/TP for long entries
        entry_long = signals == 1.0
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        # ATR-based SL/TP for short entries
        entry_short = signals == -1.0
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
