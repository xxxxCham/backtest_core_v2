from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
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
                min_val=2.0,
                max_val=4.5,
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
        bb = indicators['bollinger']
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Previous close for crossover detection
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan

        # Short entry: price crosses below middle band after being above upper band
        cross_below_middle = (close < middle) & (prev_close >= middle)
        # Rejection from upper band: close was above upper band previously
        was_above_upper = (prev_close > upper) & (close <= upper)
        short_entry = cross_below_middle & was_above_upper

        short_mask = short_entry

        # Exit short: price crosses above middle band
        exit_short = (close > middle) & (prev_close <= middle)
        short_exit = exit_short

        # Apply signals
        signals[short_mask] = -1.0
        signals[short_exit] = 0.0

        # ATR-based SL/TP for short entries
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_mask = (signals == -1.0)
        if np.any(entry_mask):
            df.loc[entry_mask, "bb_stop_short"] = close[entry_mask] + stop_atr_mult * atr[entry_mask]
            df.loc[entry_mask, "bb_tp_short"] = close[entry_mask] - tp_atr_mult * atr[entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
