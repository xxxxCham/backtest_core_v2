from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='peopleusdc_mean_reversion_4h')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'adx', 'sma', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'atr_period': 14,
         'leverage': 1,
         'rsi_period': 14,
         'sma_period': 20,
         'stop_atr_mult': 1.2,
         'tp_atr_mult': 2.5,
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
            'sma_period': ParameterSpec(
                name='sma_period',
                min_val=5,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=50,
                default=14,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
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
        # Extract indicator arrays
        close = df["close"].values
        rsi = np.nan_to_num(indicators['rsi'])
        adx = np.nan_to_num(indicators['adx']["adx"])
        sma = np.nan_to_num(indicators['sma'])
        atr = np.nan_to_num(indicators['atr'])

        # Helper for cross detection
        prev_close = np.roll(close, 1)
        prev_sma = np.roll(sma, 1)
        prev_close[0] = np.nan
        prev_sma[0] = np.nan
        cross_up = (close > sma) & (prev_close <= prev_sma)
        cross_down = (close < sma) & (prev_close >= prev_sma)
        cross_any = cross_up | cross_down

        # Entry conditions
        long_mask = (close < sma) & (rsi < 30) & (adx < 20)
        short_mask = (close > sma) & (rsi > 70) & (adx < 20)

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        exit_mask = cross_any | np.isclose(rsi, 50) | (adx > 25)
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 1.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 2.0))

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
