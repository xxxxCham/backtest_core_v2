from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='supertrend_adx_price_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 2.25, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'supertrend_atr_period': ParameterSpec(
                name='supertrend_atr_period',
                min_val=5,
                max_val=20,
                default=18,
                param_type='int',
                step=1,
            ),
            'supertrend_multiplier': ParameterSpec(
                name='supertrend_multiplier',
                min_val=0.5,
                max_val=5.0,
                default=4.0,
                param_type='float',
                step=0.1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=20,
                default=10,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=20,
                default=14,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=4.0,
                default=2.25,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
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
        # boolean masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # unwrap indicators
        st = indicators['supertrend']
        direction = np.nan_to_num(st["direction"])
        st_line = np.nan_to_num(st["supertrend"])

        adx_val = np.nan_to_num(indicators['adx']["adx"])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # entry logic
        long_mask = (close > st_line) & (direction == 1) & (adx_val > 30)
        short_mask = (close < st_line) & (direction == -1) & (adx_val > 30)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # exit logic: direction change or weak ADX
        prev_dir = np.roll(direction, 1)
        prev_dir[0] = 0
        dir_change = (direction != prev_dir) & (prev_dir != 0)
        weak_adx = adx_val < 20
        exit_mask = dir_change | weak_adx

        signals[exit_mask] = 0.0

        # warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_mult = float(params.get("stop_atr_mult", 2.25))
        tp_mult = float(params.get("tp_atr_mult", 3.0))

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_mult * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_mult * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
