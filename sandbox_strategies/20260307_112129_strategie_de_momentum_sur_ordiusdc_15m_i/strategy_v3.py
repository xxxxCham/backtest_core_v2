from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ordi_macd_atr_momentum_rev2')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'macd_fast_period': 12,
         'macd_signal_period': 9,
         'macd_slow_period': 26,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

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
                min_val=1.0,
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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        signals.iloc[:warmup] = 0.0
        macd = indicators['macd']
        atr = indicators['atr']
        macd_fast_line = np.nan_to_num(indicators['macd']["macd"])
        macd_slow_line = np.nan_to_num(indicators['macd']["signal"])
        close = df["close"].values

        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Long entry condition
        long_condition = np.logical_and(
            macd_fast_line > macd_slow_line,
            atr > 10
        )
        long_mask = long_condition

        # Short entry condition
        short_condition = np.logical_and(
            macd_fast_line < macd_slow_line,
            atr > 10
        )
        short_mask = short_condition

        # Assign signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based stop-loss and take-profit
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        long_entries = signals == 1.0
        if np.any(long_entries):
            df.loc[long_entries, "bb_stop_long"] = close[long_entries] - stop_atr_mult * atr[long_entries]
            df.loc[long_entries, "bb_tp_long"] = close[long_entries] + tp_atr_mult * atr[long_entries]
        signals.iloc[:warmup] = 0.0
        return signals
