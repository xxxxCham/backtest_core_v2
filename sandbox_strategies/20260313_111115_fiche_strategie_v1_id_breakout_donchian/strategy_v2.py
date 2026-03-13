from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_donchian_adx_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 11,
         'donchian_period': 35,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 5.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'donchian_period': ParameterSpec(
                name='donchian_period',
                min_val=10,
                max_val=100,
                default=35,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=50,
                default=11,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
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

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Extract indicators
        donchian = indicators['donchian']
        adx = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        close = np.nan_to_num(df["close"].values)
        indicators['donchian']['upper'] = np.nan_to_num(indicators['donchian']["upper"])
        indicators['donchian']['lower'] = np.nan_to_num(indicators['donchian']["lower"])
        indicators['donchian']['middle'] = np.nan_to_num(indicators['donchian']["middle"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])

        # Volatility confirmation
        atr_mean = np.convolve(atr, np.ones(20)/20, mode='valid')
        atr_mean = np.pad(atr_mean, (len(atr) - len(atr_mean), 0), mode='constant', constant_values=np.nan)
        volatility_conf = atr > atr_mean

        # Entry conditions
        long_entry = (close > indicators['donchian']['upper']) & (adx_val > 25) & volatility_conf
        short_entry = (close < indicators['donchian']['lower']) & (adx_val > 25) & volatility_conf

        # Exit conditions
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_donchian_middle = np.roll(indicators['donchian']['middle'], 1)
        prev_donchian_middle[0] = np.nan
        cross_down_middle = (close < indicators['donchian']['middle']) & (prev_close >= prev_donchian_middle)
        adx_exit = adx_val < 20

        # Signal assignment
        long_mask = long_entry
        short_mask = short_entry

        # Exit signal
        exit_long = cross_down_middle | adx_exit
        exit_short = cross_down_middle | adx_exit

        # Apply exits
        exit_long_mask = np.zeros(n, dtype=bool)
        exit_short_mask = np.zeros(n, dtype=bool)
        prev_long_mask = np.roll(long_mask, 1)
        prev_long_mask[0] = False
        prev_short_mask = np.roll(short_mask, 1)
        prev_short_mask[0] = False

        # Mark exit points
        exit_long_mask = (prev_long_mask & exit_long)
        exit_short_mask = (prev_short_mask & exit_short)

        # Final signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # ATR-based SL/TP levels
        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 5.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals