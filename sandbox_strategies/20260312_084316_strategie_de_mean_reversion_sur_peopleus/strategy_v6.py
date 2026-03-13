from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='keltner_mean_reversion_adx_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['keltner', 'rsi', 'adx', 'atr']

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

        signals.iloc[:warmup] = 0.0

        close = df["close"].values
        atr = np.nan_to_num(indicators['atr'])
        rsi = np.nan_to_num(indicators['rsi'])
        adx = np.nan_to_num(indicators['adx']["adx"])

        kelt = indicators['keltner']
        indicators['keltner']['lower'] = np.nan_to_num(kelt["lower"])
        indicators['keltner']['upper'] = np.nan_to_num(kelt["upper"])
        indicators['keltner']['middle'] = np.nan_to_num(kelt["middle"])

        rsi_overbought = float(params.get("rsi_overbought", 70))
        rsi_oversold = float(params.get("rsi_oversold", 30))

        long_mask = (close <= indicators['keltner']['lower']) & (rsi <= rsi_oversold) & (adx < 25)
        short_mask = (close >= indicators['keltner']['upper']) & (rsi >= rsi_overbought) & (adx < 25)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        # cross of close with indicators['keltner']['middle']
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        cross_up_middle = (close > indicators['keltner']['middle']) & (prev_close <= indicators['keltner']['middle'])
        cross_down_middle = (close < indicators['keltner']['middle']) & (prev_close >= indicators['keltner']['middle'])
        exit_middle = cross_up_middle | cross_down_middle
        exit_trend = adx > 25
        exit_mask = exit_middle | exit_trend
        signals[exit_mask] = 0.0

        # ATR-based SL/TP levels for longs and shorts
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = long_mask
        entry_short_mask = short_mask

        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
