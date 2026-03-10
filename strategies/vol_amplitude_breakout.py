from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase, register_strategy


@register_strategy('vol_amplitude_breakout')
class VolAmplitudeBreakoutStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="vol_amplitude_breakout_trend_filter")

    @property
    def required_indicators(self) -> List[str]:
        return ['amplitude_hunter', 'donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "amplitude_hunter_period": 20,
            "amplitude_threshold": 0.5,
            "donchian_period": 20,
            "adx_period": 14,
            "adx_threshold": 18.0,
            "atr_period": 14,
            "leverage": 1,
            "stop_atr_mult": 1.75,
            "tp_atr_mult": 5.5,
            "warmup": 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "amplitude_hunter_period": ParameterSpec(
                name="amplitude_hunter_period",
                min_val=10,
                max_val=80,
                default=20,
                param_type="int",
                step=1,
            ),
            "amplitude_threshold": ParameterSpec(
                name="amplitude_threshold",
                min_val=-1.0,
                max_val=3.0,
                default=0.5,
                param_type="float",
                step=0.1,
            ),
            "donchian_period": ParameterSpec(
                name="donchian_period",
                min_val=10,
                max_val=80,
                default=20,
                param_type="int",
                step=1,
            ),
            "adx_period": ParameterSpec(
                name="adx_period",
                min_val=7,
                max_val=35,
                default=14,
                param_type="int",
                step=1,
            ),
            "adx_threshold": ParameterSpec(
                name="adx_threshold",
                min_val=10.0,
                max_val=45.0,
                default=18.0,
                param_type="float",
                step=0.5,
            ),
            "atr_period": ParameterSpec(
                name="atr_period",
                min_val=5,
                max_val=30,
                default=14,
                param_type="int",
                step=1,
            ),
            "stop_atr_mult": ParameterSpec(
                name="stop_atr_mult",
                min_val=0.5,
                max_val=5.0,
                default=1.75,
                param_type="float",
                step=0.1,
            ),
            "tp_atr_mult": ParameterSpec(
                name="tp_atr_mult",
                min_val=1.0,
                max_val=10.0,
                default=5.5,
                param_type="float",
                step=0.1,
            ),
            "leverage": ParameterSpec(
                name="leverage",
                min_val=1,
                max_val=3,
                default=1,
                param_type="int",
                step=1,
                optimize=False,
            ),
            "warmup": ParameterSpec(
                name="warmup",
                min_val=20,
                max_val=200,
                default=50,
                param_type="int",
                step=5,
                optimize=False,
            ),
        }

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        n = len(df)
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        warmup = int(params.get('warmup', 50))
        stop_atr_mult = float(params.get('stop_atr_mult', 1.5))
        tp_atr_mult = float(params.get('tp_atr_mult', 3.0))
        adx_threshold = float(params.get('adx_threshold', 18.0))
        amplitude_threshold = float(params.get("amplitude_threshold", 0.5))
        close = np.nan_to_num(df['close'].values.astype(np.float64))
        if len(close) < warmup + 2:
            return signals
        atr_raw = indicators.get('atr')
        if isinstance(atr_raw, np.ndarray):
            atr = np.nan_to_num(atr_raw.astype(np.float64))
        else:
            atr = np.full(n, 0.0)
        dc_raw = indicators.get('donchian')
        if isinstance(dc_raw, dict):
            dc_upper = np.nan_to_num(dc_raw.get('upper', np.full(n, np.inf)).astype(np.float64))
            dc_lower = np.nan_to_num(dc_raw.get('lower', np.full(n, -np.inf)).astype(np.float64))
        else:
            dc_upper = np.full(n, np.inf)
            dc_lower = np.full(n, -np.inf)
        adx_raw = indicators.get('adx')
        if isinstance(adx_raw, dict):
            adx = np.nan_to_num(adx_raw.get('adx', np.zeros(n))).astype(np.float64)
        else:
            adx = np.full(n, 0.0)
        amp_raw = indicators.get("amplitude_hunter")
        if isinstance(amp_raw, dict):
            amp_score = np.nan_to_num(
                np.asarray(amp_raw.get("score", np.zeros(n)), dtype=np.float64)
            )
        else:
            amp_score = np.zeros(n, dtype=np.float64)
        df.loc[:, 'bb_stop_long'] = np.nan
        df.loc[:, 'bb_tp_long'] = np.nan
        df.loc[:, 'bb_stop_short'] = np.nan
        df.loc[:, 'bb_tp_short'] = np.nan
        dc_upper_prev = np.roll(dc_upper, 1)
        dc_lower_prev = np.roll(dc_lower, 1)
        dc_upper_prev[:1] = dc_upper[:1]
        dc_lower_prev[:1] = dc_lower[:1]
        # Breakout validé par force de tendance + score d'amplitude.
        long_cond = (
            (close > dc_upper_prev)
            & (adx >= adx_threshold)
            & (amp_score >= amplitude_threshold)
        )
        short_cond = (
            (close < dc_lower_prev)
            & (adx >= adx_threshold)
            & (amp_score >= amplitude_threshold)
        )
        long_prev = np.roll(long_cond, 1)
        short_prev = np.roll(short_cond, 1)
        long_prev[:1] = False
        short_prev[:1] = False
        long_entry = long_cond & (~long_prev)
        short_entry = short_cond & (~short_prev)
        long_entry[:warmup] = False
        short_entry[:warmup] = False
        signals[long_entry] = 1.0
        signals[short_entry] = -1.0
        df.loc[long_entry, 'bb_stop_long'] = close[long_entry] - stop_atr_mult * atr[long_entry]
        df.loc[long_entry, 'bb_tp_long'] = close[long_entry] + tp_atr_mult * atr[long_entry]
        df.loc[short_entry, 'bb_stop_short'] = close[short_entry] + stop_atr_mult * atr[short_entry]
        df.loc[short_entry, 'bb_tp_short'] = close[short_entry] - tp_atr_mult * atr[short_entry]
        signals.iloc[:warmup] = 0.0
        return signals

