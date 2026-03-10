from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_adx_momentum_short')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_threshold': 25,
         'ema_fast_period': 10,
         'ema_slow_period': 30,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 5.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_fast_period': ParameterSpec(
                name='ema_fast_period',
                min_val=5,
                max_val=20,
                default=10,
                param_type='int',
                step=1,
            ),
            'ema_slow_period': ParameterSpec(
                name='ema_slow_period',
                min_val=21,
                max_val=60,
                default=30,
                param_type='int',
                step=1,
            ),
            'adx_threshold': ParameterSpec(
                name='adx_threshold',
                min_val=20,
                max_val=40,
                default=25,
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
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)

        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # warmup protection
        warmup = int(params.get("warmup", 50))
        signals.iloc[:warmup] = 0.0

        # extract indicator arrays
        close = df["close"].values
        ema = np.nan_to_num(indicators['ema'])
        adx = np.nan_to_num(indicators['adx']["adx"])
        atr = np.nan_to_num(indicators['atr'])

        # parameters
        adx_thr = params.get("adx_threshold", 25)
        stop_mult = params.get("stop_atr_mult", 2.0)
        tp_mult = params.get("tp_atr_mult", 5.0)

        # ------------------------------------------------------------------
        # Short entry: EMA turning down (cross down) + strong ADX trend
        # ------------------------------------------------------------------
        prev_ema = np.roll(ema, 1)
        prev_prev_ema = np.roll(ema, 2)
        prev_ema[0] = np.nan
        prev_prev_ema[0] = np.nan
        prev_prev_ema[1] = np.nan

        cross_down = (ema < prev_ema) & (prev_ema >= prev_prev_ema)
        short_mask = cross_down & (adx >= adx_thr)

        # set short entry signals
        signals[short_mask] = -1.0

        # ------------------------------------------------------------------
        # Exit conditions for short positions
        #   1) Close crosses above EMA
        #   2) ADX falls below threshold
        # ------------------------------------------------------------------
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_ema_shift = np.roll(ema, 1)

        cross_up = (close > ema) & (prev_close <= prev_ema_shift)
        adx_drop = adx < adx_thr
        exit_mask = cross_up | adx_drop

        # flatten position on exit
        signals[exit_mask] = 0.0

        # ------------------------------------------------------------------
        # ATR‑based stop‑loss and take‑profit for short entries
        # ------------------------------------------------------------------
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_price = close
        df.loc[short_mask, "bb_stop_short"] = entry_price[short_mask] + stop_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = entry_price[short_mask] - tp_mult * atr[short_mask]

        return signals
        signals.iloc[:warmup] = 0.0
        return signals
