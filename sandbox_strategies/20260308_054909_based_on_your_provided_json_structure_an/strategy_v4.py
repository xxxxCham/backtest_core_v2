from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='keltner_mean_reversion_trend_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['keltner', 'adx', 'atr']

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

        # Extract indicators
        kelt = indicators['keltner']
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        close = np.nan_to_num(df["close"].values)
        indicators['keltner']['upper'] = np.nan_to_num(kelt["upper"])
        indicators['keltner']['middle'] = np.nan_to_num(kelt["middle"])
        indicators['keltner']['lower'] = np.nan_to_num(kelt["lower"])
        adx_val = np.nan_to_num(adx_d["adx"])

        # Entry conditions
        # Long entry: close crosses above indicators['keltner']['lower'] band AND adx > 25
        prev_close = np.roll(close, 1)
        prev_kelt_lower = np.roll(indicators['keltner']['lower'], 1)
        prev_close[0] = np.nan
        prev_kelt_lower[0] = np.nan
        cross_above_lower = (close > indicators['keltner']['lower']) & (prev_close <= prev_kelt_lower)

        # Short entry: close crosses below indicators['keltner']['upper'] band AND adx > 25
        prev_kelt_upper = np.roll(indicators['keltner']['upper'], 1)
        prev_kelt_upper[0] = np.nan
        cross_below_upper = (close < indicators['keltner']['upper']) & (prev_close >= prev_kelt_upper)

        # Trend filter
        adx_condition = adx_val > 25

        # Long signal
        long_mask = cross_above_lower & adx_condition

        # Short signal
        short_mask = cross_below_upper & adx_condition

        # Exit conditions
        # Exit long: close crosses indicators['keltner']['middle'] band OR adx < 20
        prev_middle = np.roll(indicators['keltner']['middle'], 1)
        prev_middle[0] = np.nan
        cross_middle_long = (close < indicators['keltner']['middle']) & (prev_close >= prev_middle)

        # Exit short: close crosses indicators['keltner']['middle'] band OR adx < 20
        cross_middle_short = (close > indicators['keltner']['middle']) & (prev_close <= prev_middle)

        adx_exit = adx_val < 20

        # Apply exits
        exit_long_mask = cross_middle_long | adx_exit
        exit_short_mask = cross_middle_short | adx_exit

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exits
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Set ATR-based stop-loss and take-profit levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        entry_long_mask = (signals == 1.0)
        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]

        # Short entries
        entry_short_mask = (signals == -1.0)
        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
