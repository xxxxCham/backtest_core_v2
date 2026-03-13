from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='obv_ema_atr_momentum')

    @property
    def required_indicators(self) -> List[str]:
        return ['obv', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'ema_period': 20,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 5.0,
         'warmup': 20}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=5,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
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
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=10.0,
                default=5.0,
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

        # Wrap indicator arrays
        obv = np.nan_to_num(indicators['obv'])
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # previous values
        prev_obv = np.roll(obv, 1)
        prev_obv[0] = np.nan
        prev_atr = np.roll(atr, 1)
        prev_atr[0] = np.nan

        # Entry logic
        long_mask = (obv > prev_obv) & (atr > prev_atr) & (close > ema)
        short_mask = (obv < prev_obv) & (atr > prev_atr) & (close < ema)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 5.0))

        # ATR-based SL/TP for long entries
        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]

        # ATR-based SL/TP for short entries
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
