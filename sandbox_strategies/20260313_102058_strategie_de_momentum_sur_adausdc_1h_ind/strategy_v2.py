from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="builder_strategy")

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'ema', 'atr', 'supertrend', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'adx_threshold': 20.0,
         'atr_period': 14,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'supertrend_atr_period': 10,
         'supertrend_multiplier': 3.0,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {}

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        n = len(df)
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        warmup = int(params.get('warmup', 50))
        stop_atr_mult = float(params.get('stop_atr_mult', 1.5))
        tp_atr_mult = float(params.get('tp_atr_mult', 3.0))
        adx_threshold = float(params.get('adx_threshold', 20.0))
        close = np.nan_to_num(df['close'].values.astype(np.float64))
        if len(close) < warmup + 2:
            return signals
        atr_raw = indicators.get('atr')
        if isinstance(atr_raw, np.ndarray):
            atr = np.nan_to_num(atr_raw.astype(np.float64))
        else:
            atr = np.full(n, 0.0)
        st_raw = indicators.get('supertrend')
        if isinstance(st_raw, dict):
            direction = np.nan_to_num(st_raw.get('direction', np.zeros(n))).astype(np.float64)
        else:
            direction = np.full(n, 0.0)
        adx_raw = indicators.get('adx')
        if isinstance(adx_raw, dict):
            adx = np.nan_to_num(adx_raw.get('adx', np.zeros(n))).astype(np.float64)
        else:
            adx = np.full(n, 0.0)
        df.loc[:, 'bb_stop_long'] = np.nan
        df.loc[:, 'bb_tp_long'] = np.nan
        df.loc[:, 'bb_stop_short'] = np.nan
        df.loc[:, 'bb_tp_short'] = np.nan
        bull = direction > 0
        bear = direction < 0
        bull_prev = np.roll(bull, 1)
        bear_prev = np.roll(bear, 1)
        bull_prev[:1] = False
        bear_prev[:1] = False
        long_entry = bull & (~bull_prev) & (adx >= adx_threshold)
        short_entry = bear & (~bear_prev) & (adx >= adx_threshold)
        long_entry[:warmup] = False
        short_entry[:warmup] = False
        signals[long_entry] = 1.0
        signals[short_entry] = -1.0
        df.loc[long_entry, 'bb_stop_long'] = close[long_entry] - stop_atr_mult * atr[long_entry]
        df.loc[long_entry, 'bb_tp_long'] = close[long_entry] + tp_atr_mult * atr[long_entry]
        df.loc[short_entry, 'bb_stop_short'] = close[short_entry] + stop_atr_mult * atr[short_entry]
        df.loc[short_entry, 'bb_tp_short'] = close[short_entry] - tp_atr_mult * atr[short_entry]
        signals.iloc[:warmup] = 0.0
        return signals
