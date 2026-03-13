from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_vwap_cci_adx')

    @property
    def required_indicators(self) -> List[str]:
        # Added 'atr' to the list of required indicators
        return ['vwap', 'cci', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 2.0, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
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
                min_val=1.5,
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

        # Wrap indicators
        close = df["close"].values
        vwap = np.nan_to_num(indicators['vwap'])
        cci = np.nan_to_num(indicators['cci'])
        adx = np.nan_to_num(indicators['adx']["adx"])
        atr = np.nan_to_num(indicators['atr'])

        # Helper cross functions
        prev_vwap = np.roll(vwap, 1)
        prev_vwap[0] = np.nan
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_cci = np.roll(cci, 1)
        prev_cci[0] = np.nan

        cross_down_close_vwap = (close < vwap) & (prev_close >= prev_vwap)
        cross_down_cci_0 = (cci < 0.0) & (prev_cci >= 0.0)
        exit_mask = cross_down_close_vwap | cross_down_cci_0

        # Entry masks
        long_mask = (close > vwap) & (cci > 100.0) & (adx > 25.0)
        short_mask = (close < vwap) & (cci < -100.0) & (adx > 25.0)

        # Assign signals
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

        # Write ATR-based SL/TP only on entry bars
        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals