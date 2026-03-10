from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='cvxusdc_rsi_bollinger_atr_mean_reversion')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'bollinger', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_threshold': 0.0005,
         'leverage': 1,
         'rsi_overbought': 90,
         'rsi_oversold': 10,
         'rsi_period': 3,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 30}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=2,
                max_val=10,
                default=3,
                param_type='int',
                step=1,
            ),
            'rsi_oversold': ParameterSpec(
                name='rsi_oversold',
                min_val=0,
                max_val=30,
                default=10,
                param_type='int',
                step=1,
            ),
            'rsi_overbought': ParameterSpec(
                name='rsi_overbought',
                min_val=70,
                max_val=100,
                default=90,
                param_type='int',
                step=1,
            ),
            'atr_threshold': ParameterSpec(
                name='atr_threshold',
                min_val=0.0001,
                max_val=0.01,
                default=0.0005,
                param_type='float',
                step=0.1,
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
                default=30,
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
        # --- extract indicators with NaN handling ---
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        bb = indicators['bollinger']
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])

        close = df["close"].values

        # --- parameters ---
        atr_thr = float(params.get("atr_threshold", 0.0005))
        rsi_ob = float(params.get("rsi_overbought", 90))
        rsi_os = float(params.get("rsi_oversold", 10))
        stop_mult = float(params.get("stop_atr_mult", 1.5))
        tp_mult = float(params.get("tp_atr_mult", 3.0))

        # --- entry conditions ---
        long_entry = (rsi < rsi_os) & (close < indicators['bollinger']['lower']) & (atr > atr_thr)
        short_entry = (rsi > rsi_ob) & (close > indicators['bollinger']['upper']) & (atr > atr_thr)

        # --- exit condition: price crosses Bollinger middle ---
        prev_close = np.roll(close, 1)
        prev_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_close[0] = np.nan
        prev_middle[0] = np.nan
        cross_up = (close > indicators['bollinger']['middle']) & (prev_close <= prev_middle)
        cross_down = (close < indicators['bollinger']['middle']) & (prev_close >= prev_middle)
        exit_mask = cross_up | cross_down

        # --- build position series ---
        entry_signal = pd.Series(0.0, index=df.index, dtype=np.float64)
        entry_signal[long_entry] = 1.0
        entry_signal[short_entry] = -1.0

        exit_series = pd.Series(0, index=df.index, dtype=int)
        exit_series[exit_mask] = 1

        groups = exit_series.cumsum()
        position = entry_signal.groupby(groups).ffill().fillna(0.0)


        # --- warmup protection ---
        signals.iloc[:warmup] = 0.0

        # --- ATR‑based stop‑loss / take‑profit levels ---
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        df.loc[long_entry, "bb_stop_long"] = close[long_entry] - stop_mult * atr[long_entry]
        df.loc[long_entry, "bb_tp_long"] = close[long_entry] + tp_mult * atr[long_entry]

        df.loc[short_entry, "bb_stop_short"] = close[short_entry] + stop_mult * atr[short_entry]
        df.loc[short_entry, "bb_tp_short"] = close[short_entry] - tp_mult * atr[short_entry]
        signals.iloc[:warmup] = 0.0
        return signals
