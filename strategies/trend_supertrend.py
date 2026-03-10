from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase, register_strategy


@register_strategy('trend_supertrend')
class TrendSupertrendStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_supertrend_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "supertrend_atr_period": 10,
            "supertrend_multiplier": 3.0,
            "adx_period": 14,
            "atr_period": 14,
            'leverage': 1,
            'rsi_period': 14,
            "rsi_long_threshold": 50.0,
            "rsi_short_threshold": 50.0,
            "adx_entry_threshold": 30.0,
            "adx_exit_threshold": 25.0,
            'stop_atr_mult': 1.75,
            'tp_atr_mult': 4.5,
            'warmup': 50,
        }

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
            "supertrend_atr_period": ParameterSpec(
                name="supertrend_atr_period",
                min_val=5,
                max_val=50,
                default=10,
                param_type="int",
                step=1,
            ),
            "supertrend_multiplier": ParameterSpec(
                name="supertrend_multiplier",
                min_val=1.0,
                max_val=8.0,
                default=3.0,
                param_type="float",
                step=0.1,
            ),
            "adx_period": ParameterSpec(
                name="adx_period",
                min_val=7,
                max_val=35,
                default=14,
                param_type="int",
                step=1,
            ),
            "atr_period": ParameterSpec(
                name="atr_period",
                min_val=5,
                max_val=30,
                default=14,
                param_type="int",
                step=1,
            ),
            "adx_entry_threshold": ParameterSpec(
                name="adx_entry_threshold",
                min_val=10.0,
                max_val=50.0,
                default=30.0,
                param_type="float",
                step=0.5,
            ),
            "adx_exit_threshold": ParameterSpec(
                name="adx_exit_threshold",
                min_val=5.0,
                max_val=40.0,
                default=25.0,
                param_type="float",
                step=0.5,
            ),
            "rsi_long_threshold": ParameterSpec(
                name="rsi_long_threshold",
                min_val=40.0,
                max_val=70.0,
                default=50.0,
                param_type="float",
                step=0.5,
            ),
            "rsi_short_threshold": ParameterSpec(
                name="rsi_short_threshold",
                min_val=30.0,
                max_val=60.0,
                default=50.0,
                param_type="float",
                step=0.5,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=10.0,
                default=4.5,
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
                optimize=False,
            ),
        }

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # wrap indicators
        st = np.nan_to_num(indicators['supertrend']["direction"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values
        adx_entry_threshold = float(params.get("adx_entry_threshold", 30.0))
        adx_exit_threshold = float(params.get("adx_exit_threshold", 25.0))
        rsi_long_threshold = float(params.get("rsi_long_threshold", 50.0))
        rsi_short_threshold = float(params.get("rsi_short_threshold", 50.0))

        # entry logic
        long_mask = (st == 1) & (adx_val > adx_entry_threshold) & (rsi > rsi_long_threshold)
        short_mask = (st == -1) & (adx_val > adx_entry_threshold) & (rsi < rsi_short_threshold)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # exit logic
        prev_st = np.roll(st, 1)
        # avoid false change at the first element
        prev_st[0] = st[0]
        direction_change = (st != prev_st) & (np.arange(n) > 0)
        exit_mask = direction_change | (adx_val < adx_exit_threshold)
        signals[exit_mask] = 0.0

        # warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 1.75))
        tp_atr_mult = float(params.get("tp_atr_mult", 4.5))

        long_entry_mask = signals == 1.0
        short_entry_mask = signals == -1.0

        df.loc[long_entry_mask, "bb_stop_long"] = close[long_entry_mask] - stop_atr_mult * atr[long_entry_mask]
        df.loc[long_entry_mask, "bb_tp_long"] = close[long_entry_mask] + tp_atr_mult * atr[long_entry_mask]

        df.loc[short_entry_mask, "bb_stop_short"] = close[short_entry_mask] + stop_atr_mult * atr[short_entry_mask]
        df.loc[short_entry_mask, "bb_tp_short"] = close[short_entry_mask] - tp_atr_mult * atr[short_entry_mask]

        return signals
