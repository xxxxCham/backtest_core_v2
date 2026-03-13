from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='volatility_efficiency_keltner_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['keltner', 'adx', 'volume_oscillator', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

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
                max_val=8.0,
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
        # Warmup protection
        signals.iloc[:warmup] = 0.0
        # Extract indicators
        kelt = indicators['keltner']
        indicators['keltner']['upper'] = np.nan_to_num(kelt["upper"])
        indicators['keltner']['lower'] = np.nan_to_num(kelt["lower"])
        adx_d = indicators['adx']
        adx_val = np.nan_to_num(adx_d["adx"])
        volume_osc = np.nan_to_num(indicators['volume_oscillator'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values
        # Precompute previous values for crossovers
        prev_volume_osc = np.roll(volume_osc, 1)
        prev_volume_osc[0] = np.nan
        prev_kelt_upper = np.roll(indicators['keltner']['upper'], 1)
        prev_kelt_upper[0] = np.nan
        prev_kelt_lower = np.roll(indicators['keltner']['lower'], 1)
        prev_kelt_lower[0] = np.nan
        # Entry conditions
        volume_mean = np.nanmean(volume_osc)
        adx_filter = adx_val > 25
        # Long entry: close crosses above upper Keltner band AND volume oscillator > mean AND adx > 25
        long_cross_up = (close > indicators['keltner']['upper']) & (prev_kelt_upper <= indicators['keltner']['upper'])
        long_volume_filter = volume_osc > volume_mean
        long_entry = long_cross_up & long_volume_filter & adx_filter
        long_mask = long_entry
        # Short entry: close crosses below lower Keltner band AND volume oscillator > mean AND adx > 25
        short_cross_down = (close < indicators['keltner']['lower']) & (prev_kelt_lower >= indicators['keltner']['lower'])
        short_volume_filter = volume_osc > volume_mean
        short_entry = short_cross_down & short_volume_filter & adx_filter
        short_mask = short_entry
        # Exit conditions
        # Exit long: close touches indicators['keltner']['upper'] band
        long_exit = close >= indicators['keltner']['upper']
        # Exit short: close touches indicators['keltner']['lower'] band
        short_exit = close <= indicators['keltner']['lower']
        # Volume oscillator drops below mean
        volume_exit = volume_osc < volume_mean
        # Apply exits
        long_exit_mask = long_exit | volume_exit
        short_exit_mask = short_exit | volume_exit
        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[long_exit_mask] = 0.0
        signals[short_exit_mask] = 0.0
        # ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        # Long entries
        entry_long_mask = (signals == 1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]
        # Short entries
        entry_short_mask = (signals == -1.0)
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
