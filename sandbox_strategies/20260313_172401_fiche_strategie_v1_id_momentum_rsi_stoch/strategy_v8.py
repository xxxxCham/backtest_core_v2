from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_stoch_rsi_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'stochastic', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_period': 14,
         'stoch_d_period': 3,
         'stoch_k_period': 5,
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
                default=5,
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
        signals.iloc[:warmup] = 0.0

        # Extract indicator arrays
        rsi = np.nan_to_num(indicators['rsi'])
        stoch = indicators['stochastic']
        k = np.nan_to_num(stoch["stoch_k"])
        d = np.nan_to_num(stoch["stoch_d"])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Cross detection
        prev_k = np.roll(k, 1)
        prev_d = np.roll(d, 1)
        prev_k[0] = np.nan
        prev_d[0] = np.nan
        cross_up = (k > d) & (prev_k <= prev_d)
        cross_down = (k < d) & (prev_k >= prev_d)

        # Entry conditions
        long_mask = cross_up & (rsi < 30)
        short_mask = cross_down & (rsi > 70)
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        exit_long_mask = cross_down
        exit_short_mask = cross_up
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR-based SL/TP on entry bars
        entry_long = signals == 1.0
        entry_short = signals == -1.0
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
