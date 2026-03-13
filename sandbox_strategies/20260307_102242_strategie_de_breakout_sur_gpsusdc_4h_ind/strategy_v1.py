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
        return ['rsi', 'ema', 'atr', 'bollinger']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {}

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        n = len(df)
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        warmup = int(params.get('warmup', 50))
        rsi_oversold = float(params.get('rsi_oversold', 30))
        rsi_overbought = float(params.get('rsi_overbought', 70))
        stop_atr_mult = float(params.get('stop_atr_mult', 1.5))
        tp_atr_mult = float(params.get('tp_atr_mult', 3.0))
        close = np.nan_to_num(df['close'].values.astype(np.float64))
        if len(close) < warmup + 2:
            return signals
        atr_raw = indicators.get('atr')
        if isinstance(atr_raw, np.ndarray):
            atr = np.nan_to_num(atr_raw.astype(np.float64))
        else:
            atr = np.full(n, 0.0)
        rsi_raw = indicators.get('rsi')
        bb_raw = indicators.get('bollinger')
        has_rsi = isinstance(rsi_raw, np.ndarray)
        has_bb = isinstance(bb_raw, dict)
        if has_rsi:
            rsi = np.nan_to_num(rsi_raw.astype(np.float64))
        else:
            rsi = np.full(n, 50.0)
        if has_bb:
            bb_lower = np.nan_to_num(bb_raw.get('lower', np.zeros(n)).astype(np.float64))
            bb_upper = np.nan_to_num(bb_raw.get('upper', np.zeros(n)).astype(np.float64))
        else:
            bb_lower = np.full(n, 0.0)
            bb_upper = np.full(n, np.inf)
        df.loc[:, 'bb_stop_long'] = np.nan
        df.loc[:, 'bb_tp_long'] = np.nan
        df.loc[:, 'bb_stop_short'] = np.nan
        df.loc[:, 'bb_tp_short'] = np.nan
        long_cond = (rsi < rsi_oversold) & (close <= bb_lower)
        short_cond = (rsi > rsi_overbought) & (close >= bb_upper)
        long_prev = np.roll(long_cond, 1)
        short_prev = np.roll(short_cond, 1)
        long_prev[:1] = False
        short_prev[:1] = False
        long_entry = long_cond & (~long_prev)
        short_entry = short_cond & (~short_prev)
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
