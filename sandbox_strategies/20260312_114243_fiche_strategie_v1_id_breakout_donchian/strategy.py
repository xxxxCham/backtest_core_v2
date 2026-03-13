from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ema_crossover_adx_trend')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'ema_fast_period': 20,
         'ema_slow_period': 50,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 4.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_fast_period': ParameterSpec(
                name='ema_fast_period',
                min_val=5,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'ema_slow_period': ParameterSpec(
                name='ema_slow_period',
                min_val=20,
                max_val=200,
                default=50,
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
                max_val=10.0,
                default=4.0,
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
        close = df["close"].values
        atr = np.nan_to_num(indicators['atr'])
        adx_raw = np.nan_to_num(indicators['adx']["adx"])

        # Handle EMA: may be dict with fast/slow or single array
        ema_val = indicators.get('ema')
        if isinstance(ema_val, dict):
            ema_fast = np.nan_to_num(ema_val.get("fast", np.nan))
            ema_slow = np.nan_to_num(ema_val.get("slow", np.nan))
        else:
            ema_fast = ema_slow = np.nan_to_num(ema_val)

        # Cross helpers
        prev_fast = np.roll(ema_fast, 1)
        prev_slow = np.roll(ema_slow, 1)
        prev_fast[0] = np.nan
        prev_slow[0] = np.nan
        cross_up = (ema_fast > ema_slow) & (prev_fast <= prev_slow)
        cross_down = (ema_fast < ema_slow) & (prev_fast >= prev_slow)

        # Entry conditions
        long_mask = cross_up & (close > ema_fast) & (adx_raw > 25)
        short_mask = cross_down & (close < ema_fast) & (adx_raw > 25)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        exit_long = (cross_down | (adx_raw < 20)) & (signals == 1.0)
        exit_short = (cross_up | (adx_raw < 20)) & (signals == -1.0)

        signals[exit_long] = 0.0
        signals[exit_short] = 0.0

        # ATR-based SL/TP levels
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
