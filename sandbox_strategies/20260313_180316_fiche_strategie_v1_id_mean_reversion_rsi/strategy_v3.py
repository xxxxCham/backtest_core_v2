from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_rsi_obv_atr_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'obv', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_threshold': 0.5,
         'leverage': 1,
         'rsi_overbought': 65,
         'rsi_oversold': 35,
         'rsi_period': 14,
         'stop_atr_mult': 2.0,
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
            'rsi_oversold': ParameterSpec(
                name='rsi_oversold',
                min_val=10,
                max_val=40,
                default=35,
                param_type='int',
                step=1,
            ),
            'rsi_overbought': ParameterSpec(
                name='rsi_overbought',
                min_val=60,
                max_val=90,
                default=65,
                param_type='int',
                step=1,
            ),
            'atr_threshold': ParameterSpec(
                name='atr_threshold',
                min_val=0.1,
                max_val=2.0,
                default=0.5,
                param_type='float',
                step=0.1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=6.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=10,
                max_val=200,
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

        rsi = np.nan_to_num(indicators['rsi'])
        obv = np.nan_to_num(indicators['obv'])
        atr = np.nan_to_num(indicators['atr'])

        obv_prev = np.roll(obv, 1)
        obv_prev[0] = np.nan

        atr_threshold = float(params.get("atr_threshold", 0.5))
        rsi_overbought = float(params.get("rsi_overbought", 65.0))
        rsi_oversold = float(params.get("rsi_oversold", 35.0))
        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        long_entry = (rsi < rsi_oversold) & (obv > obv_prev) & (atr > atr_threshold)
        short_entry = (rsi > rsi_overbought) & (obv < obv_prev) & (atr > atr_threshold)

        long_mask[long_entry] = True
        short_mask[short_entry] = True

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        exit_long = (rsi > 50.0) | (obv < obv_prev)
        exit_short = (rsi < 50.0) | (obv > obv_prev)

        signals[(exit_long) & (signals == 1.0)] = 0.0
        signals[(exit_short) & (signals == -1.0)] = 0.0

        close = df["close"].values

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        long_entries = signals == 1.0
        short_entries = signals == -1.0

        df.loc[long_entries, "bb_stop_long"] = close[long_entries] - stop_atr_mult * atr[long_entries]
        df.loc[long_entries, "bb_tp_long"] = close[long_entries] + tp_atr_mult * atr[long_entries]
        df.loc[short_entries, "bb_stop_short"] = close[short_entries] + stop_atr_mult * atr[short_entries]
        df.loc[short_entries, "bb_tp_short"] = close[short_entries] - tp_atr_mult * atr[short_entries]
        signals.iloc[:warmup] = 0.0
        return signals
