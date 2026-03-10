from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_atr_mean_reversion')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_min': 0.0005,
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
            'atr_min': ParameterSpec(
                name='atr_min',
                min_val=0.0,
                max_val=0.01,
                default=0.0005,
                param_type='float',
                step=0.1,
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
        # Initialize masks
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

        # Previous close for cross detection
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan

        # Parameter thresholds
        atr_min = float(params.get("atr_min", 0.0005))
        stop_atr_mult = float(params.get("stop_atr_mult", 1.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 2.0))

        # Entry conditions
        cross_below_lower = (close < lower) & (prev_close >= lower)
        cross_above_upper = (close > upper) & (prev_close <= upper)
        atr_filter = atr > atr_min

        long_mask = cross_below_lower & atr_filter
        short_mask = cross_above_upper & atr_filter

        # Assign entry signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions (mean-reversion to middle band)
        cross_up_middle = (close > middle) & (prev_close <= middle)
        cross_down_middle = (close < middle) & (prev_close >= middle)

        # Ensure we do not hold a position after exit; the engine treats 0.0 as flat.
        # No explicit signal needed because default is 0.0.

        # Prepare SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Write SL/TP levels for long entries
        if long_mask.any():
            entry_price_long = close[long_mask]
            atr_long = atr[long_mask]
            df.loc[long_mask, "bb_stop_long"] = entry_price_long - stop_atr_mult * atr_long
            df.loc[long_mask, "bb_tp_long"] = entry_price_long + tp_atr_mult * atr_long

        # Write SL/TP levels for short entries
        if short_mask.any():
            entry_price_short = close[short_mask]
            atr_short = atr[short_mask]
            df.loc[short_mask, "bb_stop_short"] = entry_price_short + stop_atr_mult * atr_short
            df.loc[short_mask, "bb_tp_short"] = entry_price_short - tp_atr_mult * atr_short
        signals.iloc[:warmup] = 0.0
        return signals
