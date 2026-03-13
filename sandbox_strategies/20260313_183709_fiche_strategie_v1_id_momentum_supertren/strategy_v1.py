from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_supertrend_keltner_volume')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'keltner', 'volume_oscillator', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'keltner_atr_period': 10,
         'keltner_ema_period': 20,
         'keltner_multiplier': 1.5,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'supertrend_atr_period': 10,
         'supertrend_multiplier': 3.0,
         'tp_atr_mult': 3.0,
         'volume_osc_long_period': 20,
         'volume_osc_short_period': 5,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'supertrend_atr_period': ParameterSpec(
                name='supertrend_atr_period',
                min_val=5,
                max_val=20,
                default=10,
                param_type='int',
                step=1,
            ),
            'supertrend_multiplier': ParameterSpec(
                name='supertrend_multiplier',
                min_val=1.0,
                max_val=5.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'keltner_ema_period': ParameterSpec(
                name='keltner_ema_period',
                min_val=10,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
            ),
            'keltner_atr_period': ParameterSpec(
                name='keltner_atr_period',
                min_val=5,
                max_val=20,
                default=10,
                param_type='int',
                step=1,
            ),
            'keltner_multiplier': ParameterSpec(
                name='keltner_multiplier',
                min_val=1.0,
                max_val=3.0,
                default=1.5,
                param_type='float',
                step=0.1,
            ),
            'volume_osc_short_period': ParameterSpec(
                name='volume_osc_short_period',
                min_val=3,
                max_val=10,
                default=5,
                param_type='int',
                step=1,
            ),
            'volume_osc_long_period': ParameterSpec(
                name='volume_osc_long_period',
                min_val=10,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=20,
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
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=3.0,
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

        # Extract indicator arrays
        close = df["close"].values
        atr = np.nan_to_num(indicators['atr'])
        supertrend_dir = np.nan_to_num(indicators['supertrend']["direction"])
        kelt = indicators['keltner']
        indicators['keltner']['upper'] = np.nan_to_num(kelt["upper"])
        indicators['keltner']['middle'] = np.nan_to_num(kelt["middle"])
        indicators['keltner']['lower'] = np.nan_to_num(kelt["lower"])
        vol_osc = np.nan_to_num(indicators['volume_oscillator'])

        # Entry conditions
        long_mask = (supertrend_dir == 1) & (close > indicators['keltner']['upper']) & (vol_osc > 0.2)
        short_mask = (supertrend_dir == -1) & (close < indicators['keltner']['lower']) & (vol_osc < -0.2)

        # Exit condition: cross any of close and indicators['keltner']['middle']
        prev_close = np.roll(close, 1)
        prev_kelt_middle = np.roll(indicators['keltner']['middle'], 1)
        prev_close[0] = np.nan
        prev_kelt_middle[0] = np.nan
        cross_up = (close > indicators['keltner']['middle']) & (prev_close <= prev_kelt_middle)
        cross_down = (close < indicators['keltner']['middle']) & (prev_close >= prev_kelt_middle)
        exit_mask = cross_up | cross_down

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
