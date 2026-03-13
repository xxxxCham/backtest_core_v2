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
        close = df["close"].values
        volume_osc = np.nan_to_num(indicators['volume_oscillator'])
        adx_d = indicators['adx']
        adx_val = np.nan_to_num(adx_d["adx"])
        atr = np.nan_to_num(indicators['atr'])
        # Compute moving average of volume oscillator
        volume_osc_ma = np.convolve(volume_osc, np.ones(20)/20, mode='valid')
        volume_osc_ma = np.pad(volume_osc_ma, (19, 0), mode='constant')
        # Cross detection helpers
        prev_volume_osc = np.roll(volume_osc, 1)
        prev_volume_osc[0] = np.nan
        prev_adx = np.roll(adx_val, 1)
        prev_adx[0] = np.nan
        cross_up_volume = (volume_osc > volume_osc_ma) & (prev_volume_osc <= volume_osc_ma)
        cross_down_volume = (volume_osc < volume_osc_ma) & (prev_volume_osc >= volume_osc_ma)
        # Entry conditions
        # Long entry: close crosses above indicators['keltner']['upper'] AND volume_osc > ma AND adx > 25
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_kelt_upper = np.roll(indicators['keltner']['upper'], 1)
        prev_kelt_upper[0] = np.nan
        cross_above_kelt_upper = (close > indicators['keltner']['upper']) & (prev_close <= prev_kelt_upper)
        long_condition = cross_above_kelt_upper & (volume_osc > volume_osc_ma) & (adx_val > 25)
        long_mask = long_condition
        # Short entry: close crosses below indicators['keltner']['lower'] AND volume_osc > ma AND adx > 25
        prev_kelt_lower = np.roll(indicators['keltner']['lower'], 1)
        prev_kelt_lower[0] = np.nan
        cross_below_kelt_lower = (close < indicators['keltner']['lower']) & (prev_close >= prev_kelt_lower)
        short_condition = cross_below_kelt_lower & (volume_osc > volume_osc_ma) & (adx_val > 25)
        short_mask = short_condition
        # Exit conditions
        # Exit long when close touches indicators['keltner']['upper'] OR volume_osc < ma
        exit_long = (close >= indicators['keltner']['upper']) | (volume_osc < volume_osc_ma)
        # Exit short when close touches indicators['keltner']['lower'] OR volume_osc < ma
        exit_short = (close <= indicators['keltner']['lower']) | (volume_osc < volume_osc_ma)
        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        # Set SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        # Long entries
        entry_long_mask = (signals == 1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]
        # Short entries
        entry_short_mask = (signals == -1.0)
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
