from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='keltner_rsi_mean_reversion_relaxed')

    @property
    def required_indicators(self) -> List[str]:
        return ['keltner', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

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
                max_val=4.5,
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
        # Masks for long and short entries
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Indicator arrays
        kelt = indicators['keltner']
        lower = np.nan_to_num(kelt["lower"])
        upper = np.nan_to_num(kelt["upper"])
        middle = np.nan_to_num(kelt["middle"])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Long entry conditions
        long_cond = (
            (close <= lower)
            & (rsi <= params["rsi_oversold"])
            & ((lower - close) < 0.15 * (upper - lower))
        )
        # Short entry conditions
        short_cond = (
            (close >= upper)
            & (rsi >= params["rsi_overbought"])
            & ((close - upper) < 0.15 * (upper - lower))
        )

        # Apply warmup
        long_cond[:warmup] = False
        short_cond[:warmup] = False

        long_mask = long_cond
        short_mask = short_cond

        # Assign signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit logic: close above middle or RSI > 50
        exit_cond = (close > middle) | (rsi > 50)
        exit_cond[:warmup] = False
        signals[exit_cond] = 0.0

        # Prepare SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long SL/TP
        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - params["stop_atr_mult"] * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + params["tp_atr_mult"] * atr[long_mask]

        # Short SL/TP
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + params["stop_atr_mult"] * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - params["tp_atr_mult"] * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
