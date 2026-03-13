from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='supertrend_adx_trend_filtering')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'atr', 'rsi']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 16,
         'atr_period': 14,
         'leverage': 1,
         'rsi_period': 14,
         'stop_atr_mult': 1.25,
         'supertrend_atr_period': 10,
         'supertrend_multiplier': 2.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'supertrend_atr_period': ParameterSpec(
                name='supertrend_atr_period',
                min_val=5,
                max_val=30,
                default=10,
                param_type='int',
                step=1,
            ),
            'supertrend_multiplier': ParameterSpec(
                name='supertrend_multiplier',
                min_val=1.0,
                max_val=5.0,
                default=2.5,
                param_type='float',
                step=0.1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=50,
                default=16,
                param_type='int',
                step=1,
            ),
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
                default=1.25,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=10.0,
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

        # Extract indicators
        st = indicators['supertrend']
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])
        rsi = np.nan_to_num(indicators['rsi'])

        # Direction and ADX
        direction = np.nan_to_num(st["direction"])
        adx = np.nan_to_num(adx_d["adx"])

        # Warmup
        signals.iloc[:warmup] = 0.0

        # Entry conditions
        long_condition = (direction == 1) & (adx > 25) & (rsi > 50)
        short_condition = (direction == -1) & (adx > 25) & (rsi < 50)

        # Exit conditions
        prev_direction = np.roll(direction, 1)
        prev_direction[0] = 0
        direction_change = (direction != prev_direction) & (direction != 0)
        adx_weak = adx < 20

        # RSI cross conditions
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        rsi_cross_down = (rsi < 50) & (prev_rsi >= 50)
        rsi_cross_up = (rsi > 50) & (prev_rsi <= 50)

        # Long signals
        long_mask = long_condition & ~direction_change & ~adx_weak & ~rsi_cross_down
        signals[long_mask] = 1.0

        # Short signals
        short_mask = short_condition & ~direction_change & ~adx_weak & ~rsi_cross_up
        signals[short_mask] = -1.0

        # Write SL/TP columns if using ATR-based risk management
        stop_atr_mult = params.get("stop_atr_mult", 1.25)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)
        close = df["close"].values

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
