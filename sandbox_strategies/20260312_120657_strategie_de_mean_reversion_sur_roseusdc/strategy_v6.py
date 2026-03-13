from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_rsi_atr_adx_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'leverage': 1,
            'rsi_overbought': 70,
            'rsi_oversold': 30,
            'rsi_period': 14,
            'stop_atr_mult': 1.0,
            'tp_atr_mult': 2.0,
            'warmup': 50,
            'adx_threshold': 20,  # weak trend threshold
            'adx_exit': 25        # strong trend exit threshold
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
                default=1.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=4.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=10,
                max_val=100,
                default=50,
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
            # ADX thresholds are fixed for this strategy, no need to expose as parameters
        }

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any]
    ) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Extract indicator arrays
        bb = indicators['bollinger']
        lower = np.nan_to_num(bb["lower"])
        middle = np.nan_to_num(bb["middle"])
        upper = np.nan_to_num(bb["upper"])

        rsi = np.nan_to_num(indicators['rsi'])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Long and short entry masks
        long_mask = (close < lower) & (rsi < params["rsi_oversold"]) & (adx_val < params["adx_threshold"])
        short_mask = (close > upper) & (rsi > params["rsi_overbought"]) & (adx_val < params["adx_threshold"])

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        exit_long_mask = (close > middle) | (adx_val > params["adx_exit"])
        exit_short_mask = (close < middle) | (adx_val > params["adx_exit"])
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Warmup period
        signals.iloc[:warmup] = 0.0

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR‑based SL/TP on entry bars
        entry_long_mask = signals == 1.0
        entry_short_mask = signals == -1.0
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]

        # Re‑apply warmup protection after SL/TP calculation
        signals.iloc[:warmup] = 0.0
        return signals