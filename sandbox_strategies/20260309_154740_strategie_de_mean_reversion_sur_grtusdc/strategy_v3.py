from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_atr_adx_mean_reversion_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_exit': 15,
         'adx_min': 20,
         'adx_period': 14,
         'atr_distance_factor': 0.5,
         'atr_min': 0.001,
         'atr_period': 14,
         'bollinger_period': 20,
         'bollinger_std_dev': 2.0,
         'leverage': 1,
         'stop_atr_mult': 1.0,
         'tp_atr_mult': 2.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'bollinger_period': ParameterSpec(
                name='bollinger_period',
                min_val=5,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'bollinger_std_dev': ParameterSpec(
                name='bollinger_std_dev',
                min_val=1.0,
                max_val=4.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'atr_min': ParameterSpec(
                name='atr_min',
                min_val=0.0001,
                max_val=0.01,
                default=0.001,
                param_type='float',
                step=0.1,
            ),
            'atr_distance_factor': ParameterSpec(
                name='atr_distance_factor',
                min_val=0.1,
                max_val=2.0,
                default=0.5,
                param_type='float',
                step=0.1,
            ),
            'adx_min': ParameterSpec(
                name='adx_min',
                min_val=10,
                max_val=40,
                default=20,
                param_type='int',
                step=1,
            ),
            'adx_exit': ParameterSpec(
                name='adx_exit',
                min_val=5,
                max_val=30,
                default=15,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=0.5,
                max_val=6.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=10,
                max_val=200,
                default=50,
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
        # Initialise masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Extract price series
        close = df["close"].values

        # Extract indicators with NaN handling
        bb = indicators['bollinger']
        lower = np.nan_to_num(bb["lower"])
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])

        atr = np.nan_to_num(indicators['atr'])

        adx_dict = indicators['adx']
        adx_val = np.nan_to_num(adx_dict["adx"])

        # Parameters
        atr_distance_factor = float(params.get("atr_distance_factor", 0.5))
        atr_min = float(params.get("atr_min", 0.001))
        adx_min = float(params.get("adx_min", 20))
        adx_exit = float(params.get("adx_exit", 15))
        stop_atr_mult = float(params.get("stop_atr_mult", 1.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 2.0))

        # Entry conditions
        long_entry = (
            (close <= lower)
            & ((lower - close) >= atr_distance_factor * atr)
            & (atr > atr_min)
            & (adx_val > adx_min)
        )
        short_entry = (
            (close >= upper)
            & ((close - upper) >= atr_distance_factor * atr)
            & (atr > atr_min)
            & (adx_val > adx_min)
        )

        # Exit conditions: price crossing middle band OR ADX dropping below exit threshold
        prev_close = np.roll(close, 1)
        prev_middle = np.roll(middle, 1)
        prev_close[0] = np.nan
        prev_middle[0] = np.nan

        cross_up = (close > middle) & (prev_close <= prev_middle)
        cross_down = (close < middle) & (prev_close >= prev_middle)
        cross_mid = cross_up | cross_down

        exit_condition = cross_mid | (adx_val < adx_exit)

        # Apply masks to signals
        long_mask[long_entry] = True
        short_mask[short_entry] = True

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_condition] = 0.0  # flatten on exit

        # Prepare SL/TP columns
        df["bb_stop_long"] = np.nan
        df["bb_tp_long"] = np.nan
        df["bb_stop_short"] = np.nan
        df["bb_tp_short"] = np.nan

        # Write ATR‑based stop‑loss and take‑profit on entry bars
        entry_long_idx = signals == 1.0
        entry_short_idx = signals == -1.0

        df.loc[entry_long_idx, "bb_stop_long"] = close[entry_long_idx] - stop_atr_mult * atr[entry_long_idx]
        df.loc[entry_long_idx, "bb_tp_long"] = close[entry_long_idx] + tp_atr_mult * atr[entry_long_idx]

        df.loc[entry_short_idx, "bb_stop_short"] = close[entry_short_idx] + stop_atr_mult * atr[entry_short_idx]
        df.loc[entry_short_idx, "bb_tp_short"] = close[entry_short_idx] - tp_atr_mult * atr[entry_short_idx]
        signals.iloc[:warmup] = 0.0
        return signals
