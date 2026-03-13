from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_rsi_adx_mean_reversion')

    @property
    def required_indicators(self) -> List[str]:
        # ATR is required for stop/TP calculations
        return ['bollinger', 'rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'adx_period': 14,
            'leverage': 1,
            'rsi_overbought': 70,
            'rsi_oversold': 30,
            'rsi_period': 14,
            'stop_atr_mult': 1.5,
            'tp_atr_mult': 3.0,
            'warmup': 50,
            # default threshold for weak trend
            'adx_threshold': 20,
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
                max_val=10.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=10,
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
            'adx_threshold': ParameterSpec(
                name='adx_threshold',
                min_val=0,
                max_val=100,
                default=20,
                param_type='float',
                step=1,
            ),
        }

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any],
    ) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Wrap indicator arrays
        close = df["close"].values
        bb = indicators['bollinger']
        lower = np.nan_to_num(bb["lower"])
        middle = np.nan_to_num(bb["middle"])
        upper = np.nan_to_num(bb["upper"])
        rsi = np.nan_to_num(indicators['rsi'])
        adx = np.nan_to_num(indicators['adx']["adx"])
        atr = np.nan_to_num(indicators['atr'])

        # Long / short entry masks
        long_mask = (
            (close < lower)
            & (rsi < params.get("rsi_oversold", 30))
            & (adx < params.get("adx_threshold", 20))
        )
        short_mask = (
            (close > upper)
            & (rsi > params.get("rsi_overbought", 70))
            & (adx < params.get("adx_threshold", 20))
        )

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR‑based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        long_entries = signals == 1.0
        short_entries = signals == -1.0

        df.loc[long_entries, "bb_stop_long"] = (
            close[long_entries] - params["stop_atr_mult"] * atr[long_entries]
        )
        df.loc[long_entries, "bb_tp_long"] = (
            close[long_entries] + params["tp_atr_mult"] * atr[long_entries]
        )

        df.loc[short_entries, "bb_stop_short"] = (
            close[short_entries] + params["stop_atr_mult"] * atr[short_entries]
        )
        df.loc[short_entries, "bb_tp_short"] = (
            close[short_entries] - params["tp_atr_mult"] * atr[short_entries]
        )

        signals.iloc[:warmup] = 0.0
        return signals