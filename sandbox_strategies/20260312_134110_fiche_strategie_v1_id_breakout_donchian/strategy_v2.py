from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_donchian_adx')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'adx_threshold': 20,
            'adx_exit_threshold': 15,  # added to avoid KeyError
            'leverage': 1,
            'stop_atr_mult': 2.75,
            'tp_atr_mult': 4.0,
            'warmup': 50
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'adx_threshold': ParameterSpec(
                name='adx_threshold',
                min_val=10,
                max_val=35,
                default=20,
                param_type='int',
                step=1,
            ),
            'adx_exit_threshold': ParameterSpec(
                name='adx_exit_threshold',
                min_val=5,
                max_val=25,
                default=15,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=2.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=6.0,
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

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any],
    ) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)

        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Extract indicator arrays safely
        close = np.nan_to_num(df["close"].values)
        atr = np.nan_to_num(indicators['atr'])
        dc = indicators['donchian']
        upper = np.nan_to_num(dc["upper"])
        middle = np.nan_to_num(dc["middle"])
        lower = np.nan_to_num(dc["lower"])
        adx_d = indicators['adx']
        adx_val = np.nan_to_num(adx_d["adx"])

        # Helper cross functions
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        cross_up = (close > middle) & (prev_close <= prev_middle)
        cross_down = (close < middle) & (prev_close >= prev_middle)
        cross_any = cross_up | cross_down

        # Entry conditions
        entry_long = (close > upper) & (adx_val > params["adx_threshold"])
        entry_short = (close < lower) & (adx_val > params["adx_threshold"])
        long_mask = entry_long
        short_mask = entry_short

        # Apply entry signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        exit_cond = cross_any | (adx_val < params["adx_exit_threshold"])
        signals[exit_cond] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Prepare SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR-based SL/TP for long entries
        entry_long_mask = signals == 1.0
        df.loc[entry_long_mask, "bb_stop_long"] = (
            close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
        )
        df.loc[entry_long_mask, "bb_tp_long"] = (
            close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]
        )

        # ATR-based SL/TP for short entries
        entry_short_mask = signals == -1.0
        df.loc[entry_short_mask, "bb_stop_short"] = (
            close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
        )
        df.loc[entry_short_mask, "bb_tp_short"] = (
            close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        )

        signals.iloc[:warmup] = 0.0
        return signals