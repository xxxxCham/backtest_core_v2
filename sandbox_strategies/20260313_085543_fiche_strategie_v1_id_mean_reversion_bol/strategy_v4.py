from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'bollinger', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 1.5,
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
        # warmup protection
        signals.iloc[:warmup] = 0.0
        # extract indicators
        rsi = np.nan_to_num(indicators['rsi'])
        bb = indicators['bollinger']
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        atr = np.nan_to_num(indicators['atr'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])
        # entry conditions
        rsi_overbought = params.get("rsi_overbought", 70)
        rsi_oversold = params.get("rsi_oversold", 30)
        adx_threshold = 25
        long_condition = (df["close"].values < indicators['bollinger']['lower']) & (rsi < rsi_oversold) & (adx > adx_threshold)
        short_condition = (df["close"].values > indicators['bollinger']['upper']) & (rsi > rsi_overbought) & (adx > adx_threshold)
        long_mask = long_condition
        short_mask = short_condition
        # exit conditions
        prev_close = np.roll(df["close"].values, 1)
        prev_close[0] = np.nan
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan
        cross_up_middle = (df["close"].values > indicators['bollinger']['middle']) & (prev_close <= prev_bb_middle)
        cross_down_middle = (df["close"].values < indicators['bollinger']['middle']) & (prev_close >= prev_bb_middle)
        cross_any_middle = cross_up_middle | cross_down_middle
        adx_exit_threshold = 20
        adx_exit = adx < adx_exit_threshold
        exit_condition = cross_any_middle | adx_exit
        # apply exit to existing positions
        long_exit_mask = np.zeros(n, dtype=bool)
        short_exit_mask = np.zeros(n, dtype=bool)
        # initialize sl/tp columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        # handle entries
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        # apply ATR-based SL/TP for long entries
        entry_long_mask = (signals == 1.0)
        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = df["close"].values[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = df["close"].values[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]
        # apply ATR-based SL/TP for short entries
        entry_short_mask = (signals == -1.0)
        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = df["close"].values[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = df["close"].values[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        # ensure no consecutive same signals
        prev_signal = np.roll(signals.values, 1)
        prev_signal[0] = 0.0
        same_signal = signals.values == prev_signal
        signals[same_signal] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
