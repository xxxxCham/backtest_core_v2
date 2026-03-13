from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_adx_trend')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 4.0, 'warmup': 50}

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
                max_val=6.0,
                default=4.0,
                param_type='float',
                step=0.1,
            ),
            'ema_short_period': ParameterSpec(
                name='ema_short_period',
                min_val=5,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'ema_long_period': ParameterSpec(
                name='ema_long_period',
                min_val=10,
                max_val=100,
                default=50,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
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

        # Extract indicator arrays
        # EMA may be a dict with ema_20 and ema_50 or a single array
        ema_ind = indicators['ema']
        if isinstance(ema_ind, dict):
            ema20 = np.nan_to_num(ema_ind.get("ema_20", ema_ind.get("ema20", ema_ind.get("ema_20", np.nan))))
            ema50 = np.nan_to_num(ema_ind.get("ema_50", ema_ind.get("ema50", ema_ind.get("ema_50", np.nan))))
        else:
            ema20 = np.nan_to_num(ema_ind)
            ema50 = ema20  # fallback if only one EMA is provided

        adx_val = np.nan_to_num(indicators['adx']["adx"])
        close_arr = df["close"].values
        atr = np.nan_to_num(indicators['atr'])

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
        long_mask = (
            (close_arr > ema20)
            & (adx_val > 25)
            & cross_up(ema20, ema50)
        )
        short_mask = (
            (close_arr < ema20)
            & (adx_val > 25)
            & cross_down(ema20, ema50)
        )

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        exit_long_mask = (cross_down(ema20, ema50)) | (adx_val < 20)
        exit_short_mask = (cross_up(ema20, ema50)) | (adx_val < 20)
        # Flatten positions when exit conditions met
        signals[exit_long_mask & (signals == 1.0)] = 0.0
        signals[exit_short_mask & (signals == -1.0)] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR-based SL/TP on entry bars
        stop_mult = params.get("stop_atr_mult", 1.5)
        tp_mult = params.get("tp_atr_mult", 4.0)

        df.loc[long_mask, "bb_stop_long"] = close_arr[long_mask] - stop_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close_arr[long_mask] + tp_mult * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close_arr[short_mask] + stop_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close_arr[short_mask] - tp_mult * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
