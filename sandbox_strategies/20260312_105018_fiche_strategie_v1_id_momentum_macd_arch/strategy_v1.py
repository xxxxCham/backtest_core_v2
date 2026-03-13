from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_macd_rsi_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 17,
         'stop_atr_mult': 2.75,
         'tp_atr_mult': 4.0,
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

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # extract indicator arrays
        macd_dict = indicators['macd']
        indicators['macd']['macd'] = np.nan_to_num(macd_dict["macd"])
        indicators['macd']['signal'] = np.nan_to_num(macd_dict["signal"])
        macd_hist = np.nan_to_num(macd_dict["histogram"])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # cross detection
        prev_macd = np.roll(indicators['macd']['macd'], 1)
        prev_signal = np.roll(indicators['macd']['signal'], 1)
        prev_macd[0] = np.nan
        prev_signal[0] = np.nan
        cross_up = (indicators['macd']['macd'] > indicators['macd']['signal']) & (prev_macd <= prev_signal)
        cross_down = (indicators['macd']['macd'] < indicators['macd']['signal']) & (prev_macd >= prev_signal)

        # entry conditions
        long_cond = cross_up & (rsi > params["rsi_oversold"]) & (rsi < params["rsi_overbought"])
        short_cond = cross_down & (rsi > params["rsi_oversold"]) & (rsi < params["rsi_overbought"])

        long_mask[long_cond] = True
        short_mask[short_cond] = True

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # exit conditions
        prev_hist = np.roll(macd_hist, 1)
        prev_hist[0] = np.nan
        hist_sign_change = (macd_hist * prev_hist < 0)
        rsi_over = rsi > 80.0
        rsi_under = rsi < 20.0
        exit_mask = hist_sign_change | rsi_over | rsi_under

        # flat signal where exit occurs
        signals[exit_mask] = 0.0

        # warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP for long positions
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        stop_atr_mult = float(params.get("stop_atr_mult", 2.75))
        tp_atr_mult = float(params.get("tp_atr_mult", 4.0))
        close = df["close"].values
        long_entry_mask = long_mask
        df.loc[long_entry_mask, "bb_stop_long"] = close[long_entry_mask] - stop_atr_mult * atr[long_entry_mask]
        df.loc[long_entry_mask, "bb_tp_long"] = close[long_entry_mask] + tp_atr_mult * atr[long_entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
