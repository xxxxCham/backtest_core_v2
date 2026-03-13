from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_breakout_ichimoku_filtered')

    @property
    def required_indicators(self) -> List[str]:
        return ['ichimoku', 'volume_oscillator', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_threshold': 1.5,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 4.0,
         'volume_threshold': 0.5,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'atr_threshold': ParameterSpec(
                name='atr_threshold',
                min_val=0.5,
                max_val=3.0,
                default=1.5,
                param_type='float',
                step=0.1,
            ),
            'volume_threshold': ParameterSpec(
                name='volume_threshold',
                min_val=0.1,
                max_val=1.0,
                default=0.5,
                param_type='float',
                step=0.1,
            ),
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

        # Extract indicators safely
        ich = indicators['ichimoku']
        tenkan = np.nan_to_num(ich["tenkan"])
        kijun = np.nan_to_num(ich["kijun"])
        senkou_a = np.nan_to_num(ich["senkou_a"])
        senkou_b = np.nan_to_num(ich["senkou_b"])
        cloud_top = np.maximum(senkou_a, senkou_b)
        cloud_bottom = np.minimum(senkou_a, senkou_b)

        volume = np.nan_to_num(indicators['volume_oscillator'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Helper for cross detection
        def cross_any(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return ((x > y) & (prev_x <= prev_y)) | ((x < y) & (prev_x >= prev_y))

        # Entry conditions
        long_mask = (
            (close > cloud_top)
            & (volume > params["volume_threshold"])
            & (close > kijun)
            & (atr > params["atr_threshold"])
        )
        short_mask = (
            (close < cloud_bottom)
            & (volume < -params["volume_threshold"])
            & (close < kijun)
            & (atr > params["atr_threshold"])
        )

        # Exit conditions
        exit_mask = (
            cross_any(close, kijun)
            | cross_any(volume, np.zeros_like(volume))
            | (atr < 1.0)
        )

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR-based SL/TP for entries
        entry_long = signals == 1.0
        entry_short = signals == -1.0
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
