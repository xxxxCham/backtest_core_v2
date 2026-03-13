from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 60,
         'rsi_oversold': 20,
         'rsi_period': 17,
         'stop_atr_mult': 1.75,
         'tp_atr_mult': 3.5,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=50,
                default=17,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=4.5,
                default=3.5,
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
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Entry conditions
        lower = np.nan_to_num(bb["lower"])
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])

        # Long entry: close < lower and rsi < oversold
        long_entry = (close < lower) & (rsi < params["rsi_oversold"])
        long_mask = long_entry

        # Short entry: close > upper and rsi > overbought
        short_entry = (close > upper) & (rsi > params["rsi_overbought"])
        short_mask = short_entry

        # Exit conditions: cross middle band or cross 50 RSI
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan

        cross_middle_down = (close < middle) & (prev_middle >= middle)
        cross_middle_up = (close > middle) & (prev_middle <= middle)
        cross_rsi_down = (rsi < 50) & (prev_rsi >= 50)
        cross_rsi_up = (rsi > 50) & (prev_rsi <= 50)

        exit_condition = cross_middle_down | cross_middle_up | cross_rsi_down | cross_rsi_up

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set exit signals to flat
        exit_mask = exit_condition & (signals != 0.0)
        signals[exit_mask] = 0.0

        # ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        if np.any(entry_long_mask):
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]

        if np.any(entry_short_mask):
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
