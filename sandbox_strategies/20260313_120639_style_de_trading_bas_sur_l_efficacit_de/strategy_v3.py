from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='volatility_efficiency_keltner')

    @property
    def required_indicators(self) -> List[str]:
        return ['keltner', 'volume_oscillator', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'keltner_atr_period': 14,
         'keltner_multiplier': 1.5,
         'keltner_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'volume_oscillator_fast': 12,
         'volume_oscillator_slow': 26,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'keltner_multiplier': ParameterSpec(
                name='keltner_multiplier',
                min_val=0.5,
                max_val=3.0,
                default=1.5,
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
                max_val=8.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=30,
                default=14,
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
        # warmup protection
        signals.iloc[:warmup] = 0.0
        # Extract indicators
        kelt = indicators['keltner']
        indicators['keltner']['upper'] = np.nan_to_num(kelt["upper"])
        indicators['keltner']['lower'] = np.nan_to_num(kelt["lower"])
        close = np.nan_to_num(df["close"].values)
        volume_osc = np.nan_to_num(indicators['volume_oscillator'])
        adx_d = indicators['adx']
        adx_val = np.nan_to_num(adx_d["adx"])
        atr = np.nan_to_num(indicators['atr'])
        # Volume oscillator MA
        volume_ma = np.nan_to_num(pd.Series(volume_osc).rolling(20).mean().values)
        # Entry conditions
        # Long entry: close crosses above indicators['keltner']['upper'], volume_osc > MA, adx > 25
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_kelt_upper = np.roll(indicators['keltner']['upper'], 1)
        prev_kelt_upper[0] = np.nan
        cross_above = (close > indicators['keltner']['upper']) & (prev_close <= prev_kelt_upper)
        long_condition = (volume_osc > volume_ma) & (adx_val > 25) & cross_above
        long_mask = long_condition
        # Short entry: close crosses below indicators['keltner']['lower'], volume_osc > MA, adx > 25
        prev_kelt_lower = np.roll(indicators['keltner']['lower'], 1)
        prev_kelt_lower[0] = np.nan
        cross_below = (close < indicators['keltner']['lower']) & (prev_close >= prev_kelt_lower)
        short_condition = (volume_osc > volume_ma) & (adx_val > 25) & cross_below
        short_mask = short_condition
        # Exit conditions
        # Exit long: close touches indicators['keltner']['upper'] OR volume_osc < MA
        exit_long = (close >= indicators['keltner']['upper']) | (volume_osc < volume_ma)
        long_exit_mask = exit_long & (np.roll(signals, 1) == 1.0)
        # Exit short: close touches indicators['keltner']['lower'] OR volume_osc < MA
        exit_short = (close <= indicators['keltner']['lower']) | (volume_osc < volume_ma)
        short_exit_mask = exit_short & (np.roll(signals, 1) == -1.0)
        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[long_exit_mask] = 0.0
        signals[short_exit_mask] = 0.0
        # Risk management: set ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        # Long entries
        entry_long = signals == 1.0
        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]
        # Short entries
        entry_short = signals == -1.0
        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
