from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_filter_adx')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'adx', 'atr']

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
        bb = indicators['bollinger']
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])
        indicators['adx']['plus_di'] = np.nan_to_num(adx_d["plus_di"])
        indicators['adx']['minus_di'] = np.nan_to_num(adx_d["minus_di"])

        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Precompute previous values for crossovers
        prev_upper = np.roll(upper, 1)
        prev_lower = np.roll(lower, 1)
        prev_middle = np.roll(middle, 1)
        prev_adx = np.roll(adx, 1)
        prev_plus_di = np.roll(indicators['adx']['plus_di'], 1)
        prev_minus_di = np.roll(indicators['adx']['minus_di'], 1)

        prev_upper[0] = np.nan
        prev_lower[0] = np.nan
        prev_middle[0] = np.nan
        prev_adx[0] = np.nan
        prev_plus_di[0] = np.nan
        prev_minus_di[0] = np.nan

        # Entry conditions
        # Long entry: close crosses above upper band AND adx > 25
        cross_up_upper = (close > upper) & (prev_upper <= upper)
        long_entry = cross_up_upper & (adx > 25)

        # Short entry: close crosses below lower band AND adx > 25
        cross_down_lower = (close < lower) & (prev_lower >= lower)
        short_entry = cross_down_lower & (adx > 25)

        # Exit conditions
        # Exit long: close crosses below middle band OR adx < 20
        cross_down_middle = (close < middle) & (prev_middle >= middle)
        long_exit = cross_down_middle | (adx < 20)

        # Exit short: close crosses above middle band OR adx < 20
        cross_up_middle = (close > middle) & (prev_middle <= middle)
        short_exit = cross_up_middle | (adx < 20)

        # Set masks
        long_mask = long_entry
        short_mask = short_entry

        # Apply exits
        long_exit_mask = long_exit & (np.roll(signals, 1) == 1.0)
        short_exit_mask = short_exit & (np.roll(signals, 1) == -1.0)

        long_mask = long_mask | long_exit_mask
        short_mask = short_mask | short_exit_mask

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Write SL/TP levels for long entries
        entry_long_mask = (signals == 1.0)
        if entry_long_mask.any():
            df.loc[:, "bb_stop_long"] = np.nan
            df.loc[:, "bb_tp_long"] = np.nan
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]

        # Write SL/TP levels for short entries
        entry_short_mask = (signals == -1.0)
        if entry_short_mask.any():
            df.loc[:, "bb_stop_short"] = np.nan
            df.loc[:, "bb_tp_short"] = np.nan
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
