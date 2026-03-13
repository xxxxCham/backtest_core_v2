from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_supertrend_adx_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 2.25, 'tp_atr_mult': 5.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.25,
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

        # Extract indicators
        st = indicators['supertrend']
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        # Clean arrays
        direction = np.nan_to_num(st["direction"])
        adx_val = np.nan_to_num(adx_d["adx"])

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Entry conditions
        long_condition = (direction == 1) & (adx_val > 25)
        short_condition = (direction == -1) & (adx_val > 25)

        long_mask[long_condition] = True
        short_mask[short_condition] = True

        # Exit conditions
        prev_direction = np.roll(direction, 1)
        prev_direction[0] = 0
        direction_change = (direction != prev_direction) & (prev_direction != 0)

        adx_weak = adx_val < 15

        # Apply exits
        exit_long = direction_change | adx_weak
        exit_short = direction_change | adx_weak

        # Mark exits
        signals[exit_long & (np.roll(signals, 1) == 1.0)] = 0.0
        signals[exit_short & (np.roll(signals, 1) == -1.0)] = 0.0

        # Apply entries
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based SL/TP levels
        stop_atr_mult = params.get("stop_atr_mult", 2.25)
        tp_atr_mult = params.get("tp_atr_mult", 5.0)

        close = df["close"].values

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        long_entries = signals == 1.0
        df.loc[long_entries, "bb_stop_long"] = close[long_entries] - stop_atr_mult * atr[long_entries]
        df.loc[long_entries, "bb_tp_long"] = close[long_entries] + tp_atr_mult * atr[long_entries]

        # Short entries
        short_entries = signals == -1.0
        df.loc[short_entries, "bb_stop_short"] = close[short_entries] + stop_atr_mult * atr[short_entries]
        df.loc[short_entries, "bb_tp_short"] = close[short_entries] - tp_atr_mult * atr[short_entries]
        signals.iloc[:warmup] = 0.0
        return signals
