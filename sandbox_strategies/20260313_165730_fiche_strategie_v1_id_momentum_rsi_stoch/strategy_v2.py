from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_rsi_stochastic_adx')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'stochastic', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'atr_min': 0.0005,
         'atr_period': 14,
         'leverage': 1,
         'rsi_overbought': 80,
         'rsi_oversold': 20,
         'rsi_period': 14,
         'stochastic_d_period': 3,
         'stochastic_k_period': 14,
         'stochastic_smoothing': 3,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=50,
                default=14,
                param_type='int',
                step=1,
            ),
            'stochastic_k_period': ParameterSpec(
                name='stochastic_k_period',
                min_val=5,
                max_val=20,
                default=14,
                param_type='int',
                step=1,
            ),
            'stochastic_d_period': ParameterSpec(
                name='stochastic_d_period',
                min_val=1,
                max_val=10,
                default=3,
                param_type='int',
                step=1,
            ),
            'stochastic_smoothing': ParameterSpec(
                name='stochastic_smoothing',
                min_val=1,
                max_val=5,
                default=3,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=20,
                default=14,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=20,
                default=14,
                param_type='int',
                step=1,
            ),
            'atr_min': ParameterSpec(
                name='atr_min',
                min_val=0.0001,
                max_val=0.01,
                default=0.0005,
                param_type='float',
                step=0.0001,
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

        signals.iloc[:warmup] = 0.0

        rsi = np.nan_to_num(indicators['rsi'])
        stoch = indicators['stochastic']
        k = np.nan_to_num(stoch["stoch_k"])
        d = np.nan_to_num(stoch["stoch_d"])
        adx_arr = np.nan_to_num(indicators['adx']["adx"])
        atr_arr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        long_cond = (
            (rsi < params["rsi_oversold"])
            & (k < 20)
            & (d < 20)
            & (adx_arr > 25)
            & (atr_arr > params["atr_min"])
        )
        short_cond = (
            (rsi > params["rsi_overbought"])
            & (k > 80)
            & (d > 80)
            & (adx_arr > 25)
            & (atr_arr > params["atr_min"])
        )

        long_mask = long_cond
        short_mask = short_cond

        prev_k = np.roll(k, 1)
        prev_k[0] = np.nan
        prev_d = np.roll(d, 1)
        prev_d[0] = np.nan
        cross_up = (k > d) & (prev_k <= prev_d)
        cross_down = (k < d) & (prev_k >= prev_d)
        cross_any = cross_up | cross_down
        exit_mask = cross_any

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = long_mask
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr_arr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr_arr[entry_long]

        entry_short = short_mask
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr_arr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr_arr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
