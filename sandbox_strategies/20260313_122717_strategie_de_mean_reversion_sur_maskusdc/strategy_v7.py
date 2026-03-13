from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_apeusdc_4h')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}
    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=2,
                max_val=10,
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

        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]
        rsi_period = params["rsi_period"]
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        # RSI crosses below overbought threshold and RSI > 50 for short entry
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        rsi_cross_down = (rsi < rsi_overbought) & (prev_rsi >= rsi_overbought)
        short_entry = rsi_cross_down & (rsi > 50)

        # RSI crosses above oversold threshold and RSI < 50 for long entry
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        rsi_cross_up = (rsi > rsi_oversold) & (prev_rsi <= rsi_oversold)
        long_entry = rsi_cross_up & (rsi < 50)

        short_mask = short_entry
        long_mask = long_entry

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_mask = (signals == 1.0)
        df.loc[entry_mask, "bb_stop_long"] = close[entry_mask] - stop_atr_mult * atr[entry_mask]
        df.loc[entry_mask, "bb_tp_long"] = close[entry_mask] + tp_atr_mult * atr[entry_mask]

        entry_mask = (signals == -1.0)
        df.loc[entry_mask, "bb_stop_short"] = close[entry_mask] + stop_atr_mult * atr[entry_mask]
        df.loc[entry_mask, "bb_tp_short"] = close[entry_mask] - tp_atr_mult * atr[entry_mask]

        # warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
