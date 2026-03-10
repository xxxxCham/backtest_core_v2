from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='keltner_channel_breakout_with_atr_risk_mgmt')

    @property
    def required_indicators(self) -> List[str]:
        return ['keltner', 'atr', 'adx']

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
                max_val=5.0,
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
        upper = np.nan_to_num(kelt["upper"])
        middle = np.nan_to_num(kelt["middle"])
        lower = np.nan_to_num(kelt["lower"])

        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])
        indicators['adx']['plus_di'] = np.nan_to_num(adx_d["plus_di"])
        indicators['adx']['minus_di'] = np.nan_to_num(adx_d["minus_di"])

        atr = np.nan_to_num(indicators['atr'])
        close = np.nan_to_num(df["close"].values)

        # Entry conditions
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_upper = np.roll(upper, 1)
        prev_upper[0] = np.nan
        prev_lower = np.roll(lower, 1)
        prev_lower[0] = np.nan
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan

        # Long entry: close crosses above indicators['keltner']['upper'] AND adx > 25
        cross_up = (close > upper) & (prev_close <= prev_upper)
        adx_long = adx > 25
        long_mask = cross_up & adx_long

        # Short entry: close crosses below indicators['keltner']['lower'] AND adx > 25
        cross_down = (close < lower) & (prev_close >= prev_lower)
        adx_short = adx > 25
        short_mask = cross_down & adx_short

        # Exit conditions
        # Exit long: close crosses below indicators['keltner']['middle'] OR adx < 20
        exit_long = (close < middle) | (adx < 20)
        exit_long_mask = np.zeros(n, dtype=bool)
        exit_long_mask[1:] = np.diff(exit_long.astype(int)) == 1

        # Exit short: close crosses above indicators['keltner']['middle'] OR adx < 20
        exit_short = (close > middle) | (adx < 20)
        exit_short_mask = np.zeros(n, dtype=bool)
        exit_short_mask[1:] = np.diff(exit_short.astype(int)) == 1

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set exit signals
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based risk management
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        entry_long_mask = (signals == 1.0)
        if np.any(entry_long_mask):
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]

        # Short entries
        entry_short_mask = (signals == -1.0)
        if np.any(entry_short_mask):
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
