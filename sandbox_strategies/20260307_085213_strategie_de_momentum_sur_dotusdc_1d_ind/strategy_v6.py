from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='builder_strategy')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=1,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=2.0,
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

        rsi_short_threshold = params.get("rsi_short_threshold", 35.0)
        rsi_long_threshold = params.get("rsi_long_threshold", 65.0)
        atr_stop_mult = params.get("atr_stop_mult", 1.5)
        atr_tp_mult = params.get("atr_tp_mult", 3.0)

        rsi = np.nan_to_num(indicators['rsi'])
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        short_cross = np.zeros(n, dtype=bool)
        short_cross[1:] = (rsi[1:] < rsi_short_threshold) & (rsi[:-1] >= rsi_short_threshold)

        long_cross = np.zeros(n, dtype=bool)
        long_cross[1:] = (rsi[1:] > rsi_long_threshold) & (rsi[:-1] <= rsi_long_threshold)

        short_mask = short_cross

        long_mask = long_cross

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        long_entries = signals == 1.0
        if np.any(long_entries):
            df.loc[long_entries, "bb_stop_long"] = close[long_entries] - atr_stop_mult * atr[long_entries]
            df.loc[long_entries, "bb_tp_long"] = close[long_entries] + atr_tp_mult * atr[long_entries]

        short_entries = signals == -1.0
        if np.any(short_entries):
            df.loc[short_entries, "bb_stop_short"] = close[short_entries] + atr_stop_mult * atr[short_entries]
            df.loc[short_entries, "bb_tp_short"] = close[short_entries] - atr_tp_mult * atr[short_entries]
        signals.iloc[:warmup] = 0.0
        return signals
