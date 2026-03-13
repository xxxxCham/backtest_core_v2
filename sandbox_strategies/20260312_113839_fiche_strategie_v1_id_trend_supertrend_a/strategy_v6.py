from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_supertrend_adx_20')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_threshold': 20,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'adx_threshold': ParameterSpec(
                name='adx_threshold',
                min_val=10,
                max_val=30,
                default=20,
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

        # Wrap indicator arrays with np.nan_to_num
        supertrend = indicators['supertrend']
        direction = np.nan_to_num(indicators['supertrend']["direction"])
        st_line = np.nan_to_num(indicators['supertrend']["supertrend"])

        adx = indicators['adx']
        adx_val = np.nan_to_num(indicators['adx']["adx"])

        atr = np.nan_to_num(indicators['atr'])

        close = df["close"].values

        # Long entry: direction up, price above supertrend line, ADX > threshold
        long_mask = (
            (direction == 1)
            & (close > st_line)
            & (adx_val > params.get("adx_threshold", 20))
        )

        # Short entry: direction down, price below supertrend line, ADX > threshold
        short_mask = (
            (direction == -1)
            & (close < st_line)
            & (adx_val > params.get("adx_threshold", 20))
        )

        # Exit conditions: direction change or weak trend
        prev_dir = np.roll(direction, 1)
        prev_dir[0] = 0.0
        direction_change = (direction != prev_dir) & (prev_dir != 0.0)
        exit_mask = direction_change | (adx_val < 15)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR-based SL/TP for long entries
        long_entries = signals == 1.0
        if long_entries.any():
            df.loc[long_entries, "bb_stop_long"] = (
                close[long_entries] - params["stop_atr_mult"] * atr[long_entries]
            )
            df.loc[long_entries, "bb_tp_long"] = (
                close[long_entries] + params["tp_atr_mult"] * atr[long_entries]
            )

        # ATR-based SL/TP for short entries
        short_entries = signals == -1.0
        if short_entries.any():
            df.loc[short_entries, "bb_stop_short"] = (
                close[short_entries] + params["stop_atr_mult"] * atr[short_entries]
            )
            df.loc[short_entries, "bb_tp_short"] = (
                close[short_entries] - params["tp_atr_mult"] * atr[short_entries]
            )
        signals.iloc[:warmup] = 0.0
        return signals
