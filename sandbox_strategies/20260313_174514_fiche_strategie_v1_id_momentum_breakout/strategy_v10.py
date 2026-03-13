from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='ichimoku_volume_atr_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['ichimoku', 'volume_oscillator', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_threshold': 0.0005,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 4.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'atr_threshold': ParameterSpec(
                name='atr_threshold',
                min_val=0.0001,
                max_val=0.01,
                default=0.0005,
                param_type='float',
                step=0.1,
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
        atr = np.nan_to_num(indicators['atr'])
        volume_osc = np.nan_to_num(indicators['volume_oscillator'])

        ich = indicators['ichimoku']
        senkou_a = np.nan_to_num(ich["senkou_a"])
        senkou_b = np.nan_to_num(ich["senkou_b"])
        kijun = np.nan_to_num(ich["kijun"])
        cloud_top = np.maximum(senkou_a, senkou_b)
        cloud_bottom = np.minimum(senkou_a, senkou_b)

        atr_threshold = float(params.get("atr_threshold", 0.0005))
        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 4.0))

        # Boolean masks for entries
        long_mask = (
            (close > cloud_top)
            & (volume_osc > 0.0)
            & (close > kijun)
            & (atr > atr_threshold)
        )
        short_mask = (
            (close < cloud_bottom)
            & (volume_osc < 0.0)
            & (close < kijun)
            & (atr > atr_threshold)
        )

        # Cross detection helpers
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_kijun = np.roll(kijun, 1)
        prev_kijun[0] = np.nan
        cross_down_close_kijun = (close < kijun) & (prev_close >= prev_kijun)

        zeros = np.zeros(n)
        prev_volume = np.roll(volume_osc, 1)
        prev_volume[0] = np.nan
        cross_up_vol = (volume_osc > zeros) & (prev_volume <= prev_volume)
        cross_down_vol = (volume_osc < zeros) & (prev_volume >= prev_volume)
        cross_any_vol = cross_up_vol | cross_down_vol

        exit_mask = cross_down_close_kijun | cross_any_vol

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Initialize SL/TP columns with NaN
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR-based SL/TP for long entries
        long_entries = signals == 1.0
        df.loc[long_entries, "bb_stop_long"] = close[long_entries] - stop_atr_mult * atr[long_entries]
        df.loc[long_entries, "bb_tp_long"] = close[long_entries] + tp_atr_mult * atr[long_entries]

        # ATR-based SL/TP for short entries
        short_entries = signals == -1.0
        df.loc[short_entries, "bb_stop_short"] = close[short_entries] + stop_atr_mult * atr[short_entries]
        df.loc[short_entries, "bb_tp_short"] = close[short_entries] - tp_atr_mult * atr[short_entries]
        signals.iloc[:warmup] = 0.0
        return signals
