from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_adx_trend_follow')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_exit_threshold': 20,
         'adx_threshold': 25,
         'ema_long_period': 50,
         'ema_short_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.25,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_short_period': ParameterSpec(
                name='ema_short_period',
                min_val=5,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
            ),
            'ema_long_period': ParameterSpec(
                name='ema_long_period',
                min_val=30,
                max_val=100,
                default=50,
                param_type='int',
                step=1,
            ),
            'adx_threshold': ParameterSpec(
                name='adx_threshold',
                min_val=10,
                max_val=40,
                default=25,
                param_type='int',
                step=1,
            ),
            'adx_exit_threshold': ParameterSpec(
                name='adx_exit_threshold',
                min_val=5,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.25,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.5,
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
        # Boolean masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Warmup
        signals.iloc[:warmup] = 0.0

        # Extract indicator arrays
        close = df["close"].values
        atr = np.nan_to_num(indicators['atr'])
        adx = np.nan_to_num(indicators['adx']["adx"])

        # EMA arrays – assume ema indicator provides dict with two periods
        ema_dict = indicators['ema']
        if isinstance(ema_dict, dict):
            ema_short = np.nan_to_num(ema_dict.get("ema_short", np.zeros(n)))
            ema_long = np.nan_to_num(ema_dict.get("ema_long", np.zeros(n)))
        else:
            ema_short = ema_long = np.nan_to_num(ema_dict)

        # Cross helper
        def cross_up(x, y):
            px = np.roll(x, 1)
            py = np.roll(y, 1)
            px[0] = np.nan
            py[0] = np.nan
            return (x > y) & (px <= py)

        def cross_down(x, y):
            px = np.roll(x, 1)
            py = np.roll(y, 1)
            px[0] = np.nan
            py[0] = np.nan
            return (x < y) & (px >= py)

        # Entry conditions
        long_mask = (
            (close > ema_long)
            & cross_up(ema_short, ema_long)
            & (adx > params["adx_threshold"])
        )
        short_mask = (
            (close < ema_short)
            & cross_down(ema_short, ema_long)
            & (adx > params["adx_threshold"])
        )

        # Assign signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        exit_mask = (
            cross_down(ema_short, ema_long)
            | (adx < params["adx_exit_threshold"])
        )
        signals[exit_mask] = 0.0

        # ATR-based SL/TP levels
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
