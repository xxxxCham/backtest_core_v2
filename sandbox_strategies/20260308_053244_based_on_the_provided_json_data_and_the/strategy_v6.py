from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_keltner_cci_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['keltner', 'cci', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'cci_overbought': 100,
         'cci_oversold': -100,
         'cci_period': 14,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'cci_period': ParameterSpec(
                name='cci_period',
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

        # Extract indicators
        kelt = indicators['keltner']
        cci = np.nan_to_num(indicators['cci'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # CCI thresholds
        cci_overbought = params.get("cci_overbought", 100)
        cci_oversold = params.get("cci_oversold", -100)

        # ATR multipliers
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Keltner bands
        indicators['keltner']['upper'] = np.nan_to_num(kelt["upper"])
        indicators['keltner']['lower'] = np.nan_to_num(kelt["lower"])
        indicators['keltner']['middle'] = np.nan_to_num(kelt["middle"])

        # Cross detection
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_kelt_upper = np.roll(indicators['keltner']['upper'], 1)
        prev_kelt_upper[0] = np.nan
        prev_kelt_lower = np.roll(indicators['keltner']['lower'], 1)
        prev_kelt_lower[0] = np.nan
        prev_kelt_middle = np.roll(indicators['keltner']['middle'], 1)
        prev_kelt_middle[0] = np.nan
        prev_cci = np.roll(cci, 1)
        prev_cci[0] = np.nan

        # Long entry: close crosses above indicators['keltner']['upper'] AND cci < -100
        cross_above_upper = (close > indicators['keltner']['upper']) & (prev_close <= prev_kelt_upper)
        cci_long_filter = (cci < cci_oversold)
        long_mask = cross_above_upper & cci_long_filter

        # Short entry: close crosses below indicators['keltner']['lower'] AND cci > 100
        cross_below_lower = (close < indicators['keltner']['lower']) & (prev_close >= prev_kelt_lower)
        cci_short_filter = (cci > cci_overbought)
        short_mask = cross_below_lower & cci_short_filter

        # Exit conditions
        # Close crosses indicators['keltner']['middle']
        cross_middle_long = (close < indicators['keltner']['middle']) & (prev_close >= prev_kelt_middle)
        cross_middle_short = (close > indicators['keltner']['middle']) & (prev_close <= prev_kelt_middle)

        # CCI crosses 0
        cci_zero_cross_long = (cci < 0) & (prev_cci >= 0)
        cci_zero_cross_short = (cci > 0) & (prev_cci <= 0)

        # Exit long
        exit_long_mask = cross_middle_long | cci_zero_cross_long
        signals[exit_long_mask] = 0.0

        # Exit short
        exit_short_mask = cross_middle_short | cci_zero_cross_short
        signals[exit_short_mask] = 0.0

        # Apply entries
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels for long entries
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        entry_long_mask = (signals == 1.0)
        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        # Set SL/TP levels for short entries
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_short_mask = (signals == -1.0)
        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        return signals