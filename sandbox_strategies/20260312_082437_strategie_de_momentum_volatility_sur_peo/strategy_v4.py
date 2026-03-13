from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='obv_ema_atr_momentum_v4')

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
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=10,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=10,
                max_val=20,
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

        # unwrap indicators
        close = df["close"].values
        obv = np.nan_to_num(indicators['obv'])
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])

        # previous values
        prev_obv = np.roll(obv, 1)
        prev_obv[0] = np.nan
        prev_atr = np.roll(atr, 1)
        prev_atr[0] = np.nan

        # OBV acceleration
        obv_accel = obv - prev_obv

        # long entry conditions
        long_cond = (
            (close > ema)
            & (obv_accel > 0.5 * atr)
            & (atr > prev_atr)
            & (obv_accel > 0)
        )
        long_mask[long_cond] = True

        # short entry conditions
        short_cond = (
            (close < ema)
            & ((prev_obv - obv) > 0.5 * atr)
            & (atr > prev_atr)
            & (prev_obv - obv > 0)
        )
        short_mask[short_cond] = True

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # warmup protection
        signals.iloc[:warmup] = 0.0

        # initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # write ATR-based SL/TP levels on entry bars
        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 5.0)

        df.loc[long_mask, "bb_stop_long"] = (
            close[long_mask] - stop_atr_mult * atr[long_mask]
        )
        df.loc[long_mask, "bb_tp_long"] = (
            close[long_mask] + tp_atr_mult * atr[long_mask]
        )
        df.loc[short_mask, "bb_stop_short"] = (
            close[short_mask] + stop_atr_mult * atr[short_mask]
        )
        df.loc[short_mask, "bb_tp_short"] = (
            close[short_mask] - tp_atr_mult * atr[short_mask]
        )
        signals.iloc[:warmup] = 0.0
        return signals
