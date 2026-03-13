from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='macd_rsi_adx_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_period': 14,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 3.5,
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
                min_val=1.0,
                max_val=6.0,
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

        signals.iloc[:warmup] = 0.0

        # Wrap indicator arrays
        rsi = np.nan_to_num(indicators['rsi'])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        indicators['macd']['macd'] = np.nan_to_num(indicators['macd']["macd"])
        indicators['macd']['signal'] = np.nan_to_num(indicators['macd']["signal"])
        macd_hist = np.nan_to_num(indicators['macd']["histogram"])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Cross helpers
        prev_macd = np.roll(indicators['macd']['macd'], 1)
        prev_macd[0] = np.nan
        prev_signal = np.roll(indicators['macd']['signal'], 1)
        prev_signal[0] = np.nan
        cross_up = (indicators['macd']['macd'] > indicators['macd']['signal']) & (prev_macd <= prev_signal)
        cross_down = (indicators['macd']['macd'] < indicators['macd']['signal']) & (prev_macd >= prev_signal)

        # Entry conditions
        long_mask = cross_up & (rsi > 30.0) & (rsi < 70.0) & (adx_val > 25.0)
        short_mask = cross_down & (rsi > 30.0) & (rsi < 70.0) & (adx_val > 25.0)

        # Exit conditions
        hist_sign = np.sign(macd_hist)
        prev_sign = np.roll(hist_sign, 1)
        prev_sign[0] = np.nan
        exit_hist = (hist_sign != prev_sign) & (~np.isnan(prev_sign))
        exit_mask = exit_hist | (rsi > 80.0) | (rsi < 20.0) | (adx_val < 20.0)

        # Apply signals
        signals[exit_mask] = 0.0
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.5))

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_atr_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_atr_mult * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
