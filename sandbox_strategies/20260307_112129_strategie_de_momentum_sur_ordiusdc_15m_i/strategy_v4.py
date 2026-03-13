from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ordi_macd_atr_momentum_rev3')

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
            'macd_fast_period': ParameterSpec(
                name='macd_fast_period',
                min_val=5,
                max_val=30,
                default=12,
                param_type='int',
                step=1,
            ),
            'macd_signal_period': ParameterSpec(
                name='macd_signal_period',
                min_val=5,
                max_val=30,
                default=9,
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
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=1,
                param_type='int',
                step=1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=4.5,
                default=3.0,
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

        signals.iloc[:warmup] = 0.0

        macd = indicators['macd']
        macd_fast_line = np.nan_to_num(indicators['macd']["macd"])
        macd_slow_line = np.nan_to_num(indicators['macd']["signal"])
        atr = np.nan_to_num(indicators['atr'])

        fast_above_slow = macd_fast_line > macd_slow_line
        atr_above_threshold = atr > 10

        long_mask = np.logical_and(fast_above_slow, atr_above_threshold)
        short_mask = np.logical_and(macd_fast_line < macd_slow_line, atr_above_threshold)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based risk management
        close = df["close"].values
        entry_mask_long = signals == 1.0
        entry_mask_short = signals == -1.0

        df.loc[entry_mask_long, "bb_stop_long"] = close[entry_mask_long] - params["stop_atr_mult"] * atr[entry_mask_long]
        df.loc[entry_mask_long, "bb_tp_long"] = close[entry_mask_long] + params["tp_atr_mult"] * atr[entry_mask_long]

        df.loc[entry_mask_short, "bb_stop_short"] = close[entry_mask_short] + params["stop_atr_mult"] * atr[entry_mask_short]
        df.loc[entry_mask_short, "bb_tp_short"] = close[entry_mask_short] - params["tp_atr_mult"] * atr[entry_mask_short]
        signals.iloc[:warmup] = 0.0
        return signals
