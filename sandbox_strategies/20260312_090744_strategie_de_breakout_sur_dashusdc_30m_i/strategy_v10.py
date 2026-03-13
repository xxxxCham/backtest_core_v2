from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_stochastic_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['stochastic', 'bollinger', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'bollinger_period': 20,
         'bollinger_std_dev': 2,
         'leverage': 1,
         'stochastic_d': 3,
         'stochastic_k': 3,
         'stochastic_overbought': 80,
         'stochastic_oversold': 20,
         'stochastic_period': 14,
         'stop_atr_mult': 1.0,
         'tp_atr_mult': 2.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stochastic_period': ParameterSpec(
                name='stochastic_period',
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
                default=1.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # unwrap indicators
        close = df["close"].values
        atr = np.nan_to_num(indicators['atr'])
        bb = indicators['bollinger']
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])
        stoch = indicators['stochastic']
        k = np.nan_to_num(stoch["stoch_k"])

        # cross helper
        def cross_down(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return (x < y) & (prev_x >= prev_y)

        # long entry: close > upper & stoch > overbought
        long_mask = (close > upper) & (k > params["stochastic_overbought"])

        # short entry: close < lower & stoch < oversold
        short_mask = (close < lower) & (k < params["stochastic_oversold"])

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # exit conditions
        exit_long_mask = cross_down(close, middle) | cross_down(k, np.full_like(k, 70.0))
        exit_short_mask = cross_down(middle, close) | cross_down(np.full_like(k, 70.0), k)

        # apply exits by setting to 0.0 (flat)
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # warmup
        signals.iloc[:warmup] = 0.0

        # write ATR based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        long_entry_mask = signals == 1.0
        short_entry_mask = signals == -1.0

        df.loc[long_entry_mask, "bb_stop_long"] = close[long_entry_mask] - params["stop_atr_mult"] * atr[long_entry_mask]
        df.loc[long_entry_mask, "bb_tp_long"] = close[long_entry_mask] + params["tp_atr_mult"] * atr[long_entry_mask]

        df.loc[short_entry_mask, "bb_stop_short"] = close[short_entry_mask] + params["stop_atr_mult"] * atr[short_entry_mask]
        df.loc[short_entry_mask, "bb_tp_short"] = close[short_entry_mask] - params["tp_atr_mult"] * atr[short_entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
