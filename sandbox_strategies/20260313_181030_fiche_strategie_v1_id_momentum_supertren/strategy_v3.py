from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='supertrend_adx_vol_3m')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'volume_oscillator', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'volume_osc_threshold': 0.5,
         'warmup': 50}

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
                min_val=1.0,
                max_val=6.0,
                default=3.0,
                param_type='float',
                step=0.1,
            ),
            'volume_osc_threshold': ParameterSpec(
                name='volume_osc_threshold',
                min_val=0.1,
                max_val=1.0,
                default=0.5,
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

        close = np.nan_to_num(df["close"].values)
        supertrend_line = np.nan_to_num(indicators['supertrend']["supertrend"])
        direction = np.nan_to_num(indicators['supertrend']["direction"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        vol_osc = np.nan_to_num(indicators['volume_oscillator'])
        atr = np.nan_to_num(indicators['atr'])

        vol_thr = params.get("volume_osc_threshold", 0.5)

        long_cond = (close > supertrend_line) & (direction > 0) & (adx_val > 25) & (vol_osc > vol_thr)
        short_cond = (close < supertrend_line) & (direction < 0) & (adx_val > 25) & (vol_osc < -vol_thr)

        long_mask = long_cond
        short_mask = short_cond

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_supertrend = np.roll(supertrend_line, 1)
        prev_supertrend[0] = np.nan
        cross_up = (close > supertrend_line) & (prev_close <= prev_supertrend)
        cross_down = (close < supertrend_line) & (prev_close >= prev_supertrend)
        cross_any = cross_up | cross_down

        exit_long = cross_any | (adx_val < 20)
        exit_short = cross_any | (adx_val < 20)

        signals[exit_long & (signals == 1.0)] = 0.0
        signals[exit_short & (signals == -1.0)] = 0.0

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_mult = params.get("stop_atr_mult", 1.5)
        tp_mult = params.get("tp_atr_mult", 3.0)

        df.loc[long_mask, "bb_stop_long"] = close[long_mask] - stop_mult * atr[long_mask]
        df.loc[long_mask, "bb_tp_long"] = close[long_mask] + tp_mult * atr[long_mask]
        df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_mult * atr[short_mask]
        df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_mult * atr[short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
