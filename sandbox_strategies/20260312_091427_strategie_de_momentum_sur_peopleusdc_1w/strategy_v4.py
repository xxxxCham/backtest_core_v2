from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_obv_ema_atr_v2')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'obv', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 30}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
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
        # boolean masks
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # extract indicators
        close = df["close"].values
        ema = np.nan_to_num(indicators['ema'])
        obv = np.nan_to_num(indicators['obv'])
        atr = np.nan_to_num(indicators['atr'])

        # compute ATR moving average (window 14)
        atr_window = 14
        atr_ma = np.convolve(atr, np.ones(atr_window) / atr_window, mode="same")

        # OBV 3‑bar roll
        obv_roll3 = np.roll(obv, 3)
        obv_roll3[:3] = np.nan

        # long condition
        long_cond = (close > ema) & (obv > obv_roll3) & (atr > atr_ma)
        long_mask = long_cond

        # short condition
        short_cond = (close < ema) & (obv < obv_roll3) & (atr > atr_ma)
        short_mask = short_cond

        # exit condition: close crosses below ema OR OBV decreasing
        prev_close = np.roll(close, 1)
        prev_ema = np.roll(ema, 1)
        prev_close[0] = np.nan
        prev_ema[0] = np.nan
        cross_down = (close < ema) & (prev_close >= prev_ema)
        obv_decreasing = obv < obv_roll3
        exit_mask = cross_down | obv_decreasing

        # assign signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # warmup
        signals.iloc[:warmup] = 0.0

        # ATR‑based SL/TP levels
        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = (signals == 1.0)
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        entry_short = (signals == -1.0)
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
