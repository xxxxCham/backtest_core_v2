from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ichimoku_volume_adx_breakout')

    @property
    def required_indicators(self) -> List[str]:
        # ATR is needed for stop/TP calculations
        return ['ichimoku', 'volume_oscillator', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'adx_threshold': 25,
            'leverage': 1,
            'stop_atr_mult': 2.0,
            'tp_atr_mult': 4.0,
            'warmup': 50
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'adx_threshold': ParameterSpec(
                name='adx_threshold',
                min_val=10,
                max_val=40,
                default=25,
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
                default=4.0,
                param_type='float',
                step=0.1,
            ),
            'warmup': ParameterSpec(
                name='warmup',
                min_val=20,
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

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any]
    ) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Extract indicator arrays
        close = df["close"].values
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        vol_osc = np.nan_to_num(indicators['volume_oscillator'])
        atr = np.nan_to_num(indicators['atr'])
        ich = indicators['ichimoku']
        senkou_a = np.nan_to_num(ich["senkou_a"])
        senkou_b = np.nan_to_num(ich["senkou_b"])
        cloud_top = np.maximum(senkou_a, senkou_b)
        cloud_bottom = np.minimum(senkou_a, senkou_b)
        kijun = np.nan_to_num(ich["kijun"])

        # Long entry condition
        long_mask = (
            (close > cloud_top)
            & (vol_osc > 0.0)
            & (adx_val > params.get("adx_threshold", 25.0))
        )

        # Short entry condition
        short_mask = (
            (close < cloud_bottom)
            & (vol_osc < 0.0)
            & (adx_val > params.get("adx_threshold", 25.0))
        )

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        prev_close = np.roll(close, 1)
        prev_kijun = np.roll(kijun, 1)
        prev_close[0] = np.nan
        prev_kijun[0] = np.nan
        cross_up = (close > kijun) & (prev_close <= prev_kijun)
        cross_down = (close < kijun) & (prev_close >= prev_kijun)
        cross_any = cross_up | cross_down

        exit_cond = cross_any | (adx_val < 20.0)
        signals[exit_cond] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Prepare SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR-based SL/TP on entry bars
        long_entry = (signals == 1.0)
        short_entry = (signals == -1.0)

        df.loc[long_entry, "bb_stop_long"] = (
            close[long_entry] - params.get("stop_atr_mult", 2.0) * atr[long_entry]
        )
        df.loc[long_entry, "bb_tp_long"] = (
            close[long_entry] + params.get("tp_atr_mult", 4.0) * atr[long_entry]
        )

        df.loc[short_entry, "bb_stop_short"] = (
            close[short_entry] + params.get("stop_atr_mult", 2.0) * atr[short_entry]
        )
        df.loc[short_entry, "bb_tp_short"] = (
            close[short_entry] - params.get("tp_atr_mult", 4.0) * atr[short_entry]
        )

        signals.iloc[:warmup] = 0.0
        return signals