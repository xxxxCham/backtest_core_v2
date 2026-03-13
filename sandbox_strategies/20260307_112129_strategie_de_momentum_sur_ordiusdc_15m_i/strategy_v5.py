from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ordi_macd_atr_trend_follow')

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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        signals.iloc[:warmup] = 0.0
        macd = indicators['macd']
        atr = indicators['atr']
        macd_fast_line = np.nan_to_num(indicators['macd']["macd"])
        macd_slow_line = np.nan_to_num(indicators['macd']["signal"])
        atr_val = np.nan_to_num(atr)

        long_mask = np.logical_and(
            macd_fast_line > macd_slow_line,
            atr_val > 10,
        )
        short_mask = np.logical_and(
            macd_fast_line < macd_slow_line,
            atr_val > 10,
        )

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based risk management
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        entry_mask_long = signals == 1.0
        entry_mask_short = signals == -1.0

        close = df["close"].values
        atr_at_entry = atr_val[entry_mask_long] if len(entry_mask_long) > 0 else np.array([])
        df.loc[entry_mask_long, "bb_stop_long"] = close[entry_mask_long] - stop_atr_mult * atr_at_entry
        df.loc[entry_mask_long, "bb_tp_long"] = close[entry_mask_long] + tp_atr_mult * atr_at_entry

        atr_at_entry_short = atr_val[entry_mask_short] if len(entry_mask_short) > 0 else np.array([])
        df.loc[entry_mask_short, "bb_stop_short"] = close[entry_mask_short] + stop_atr_mult * atr_at_entry_short
        df.loc[entry_mask_short, "bb_tp_short"] = close[entry_mask_short] - tp_atr_mult * atr_at_entry_short
        signals.iloc[:warmup] = 0.0
        return signals