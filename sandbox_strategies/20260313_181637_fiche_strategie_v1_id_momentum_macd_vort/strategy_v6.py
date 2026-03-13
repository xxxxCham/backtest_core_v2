from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='macd_vortex_volume_1h')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'vortex', 'volume_oscillator', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'leverage': 1,
         'macd_fast_period': 12,
         'macd_signal_period': 9,
         'macd_slow_period': 26,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 3.0,
         'volume_osc_long_period': 20,
         'volume_osc_short_period': 5,
         'vortex_period': 14,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'macd_fast_period': ParameterSpec(
                name='macd_fast_period',
                min_val=5,
                max_val=20,
                default=12,
                param_type='int',
                step=1,
            ),
            'macd_slow_period': ParameterSpec(
                name='macd_slow_period',
                min_val=15,
                max_val=30,
                default=26,
                param_type='int',
                step=1,
            ),
            'macd_signal_period': ParameterSpec(
                name='macd_signal_period',
                min_val=5,
                max_val=15,
                default=9,
                param_type='int',
                step=1,
            ),
            'vortex_period': ParameterSpec(
                name='vortex_period',
                min_val=5,
                max_val=20,
                default=14,
                param_type='int',
                step=1,
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
                default=2.0,
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
                max_val=100,
                default=50,
                param_type='int',
                step=1,
            ),
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=5,
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

        # Extract indicator arrays
        indicators['macd']['macd'] = np.nan_to_num(indicators['macd']["macd"])
        indicators['macd']['signal'] = np.nan_to_num(indicators['macd']["signal"])
        vortex_plus = np.nan_to_num(indicators['vortex']["vi_plus"])
        vortex_minus = np.nan_to_num(indicators['vortex']["vi_minus"])
        volume_osc = np.nan_to_num(indicators['volume_oscillator'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Cross helpers
        prev_macd = np.roll(indicators['macd']['macd'], 1)
        prev_signal = np.roll(indicators['macd']['signal'], 1)
        prev_macd[0] = np.nan
        prev_signal[0] = np.nan
        cross_up = (indicators['macd']['macd'] > indicators['macd']['signal']) & (prev_macd <= prev_signal)
        cross_down = (indicators['macd']['macd'] < indicators['macd']['signal']) & (prev_macd >= prev_signal)

        # Long entry: MACD cross up, Vortex positive, volume oscillator > 0.1
        long_entry = cross_up & (vortex_plus > vortex_minus) & (volume_osc > 0.1)

        # Short entry: MACD cross down, Vortex negative, volume oscillator < -0.1
        short_entry = cross_down & (vortex_minus > vortex_plus) & (volume_osc < -0.1)

        # Exit signals
        exit_long = cross_down
        exit_short = cross_up

        # Apply masks
        signals[long_entry] = 1.0
        signals[short_entry] = -1.0
        signals[exit_long] = 0.0
        signals[exit_short] = 0.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        long_entries = signals == 1.0
        short_entries = signals == -1.0

        df.loc[long_entries, "bb_stop_long"] = close[long_entries] - stop_atr_mult * atr[long_entries]
        df.loc[long_entries, "bb_tp_long"] = close[long_entries] + tp_atr_mult * atr[long_entries]

        df.loc[short_entries, "bb_stop_short"] = close[short_entries] + stop_atr_mult * atr[short_entries]
        df.loc[short_entries, "bb_tp_short"] = close[short_entries] - tp_atr_mult * atr[short_entries]
        signals.iloc[:warmup] = 0.0
        return signals
