from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_rsi_stochastic_optimized')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'stochastic', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_period': 14,
         'stoch_d_period': 3,
         'stoch_k_period': 14,
         'stoch_smoothing': 3,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'stoch_k_period': ParameterSpec(
                name='stoch_k_period',
                min_val=5,
                max_val=20,
                default=14,
                param_type='int',
                step=1,
            ),
            'stoch_d_period': ParameterSpec(
                name='stoch_d_period',
                min_val=2,
                max_val=10,
                default=3,
                param_type='int',
                step=1,
            ),
            'stoch_smoothing': ParameterSpec(
                name='stoch_smoothing',
                min_val=1,
                max_val=5,
                default=3,
                param_type='int',
                step=1,
            ),
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

        # wrap indicator arrays with np.nan_to_num
        rsi = np.nan_to_num(indicators['rsi'])
        stoch = indicators['stochastic']
        k = np.nan_to_num(stoch["stoch_k"])
        d = np.nan_to_num(stoch["stoch_d"])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Entry conditions
        long_mask = (rsi < 30) & (k < 30) & (d < 30)
        short_mask = (rsi > 70) & (k > 70) & (d > 70)

        # Cross detection helper
        prev_k = np.roll(k, 1)
        prev_k[0] = np.nan
        prev_d = np.roll(d, 1)
        prev_d[0] = np.nan
        cross_up = (k > d) & (prev_k <= prev_d)
        cross_down = (k < d) & (prev_k >= prev_d)
        cross_any = cross_up | cross_down

        # Exit condition
        exit_mask = cross_any

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        # Flatten on exit if not an entry bar
        signals[exit_mask & ~long_mask & ~short_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Initialize SL/TP columns with NaN
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR-based SL/TP on entry bars
        entry_mask = long_mask | short_mask
        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - params["stop_atr_mult"] * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + params["tp_atr_mult"] * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + params["stop_atr_mult"] * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - params["tp_atr_mult"] * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
