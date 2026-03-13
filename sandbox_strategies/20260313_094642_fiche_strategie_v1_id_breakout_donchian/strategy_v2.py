from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_donchian_adx_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.75, 'tp_atr_mult': 2.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=6.0,
                default=2.0,
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
        # implement explicit LONG / SHORT / FLAT logic
        # warmup protection
        signals.iloc[:warmup] = 0.0

        # Extract indicators
        dc = indicators['donchian']
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        close = np.nan_to_num(df["close"].values)
        upper = np.nan_to_num(dc["upper"])
        middle = np.nan_to_num(dc["middle"])
        lower = np.nan_to_num(dc["lower"])
        adx_val = np.nan_to_num(adx_d["adx"])

        # Entry conditions
        # Long entry: close > upper and adx > 20 and atr > mean(atr) * 0.5
        long_entry_condition = (close > upper) & (adx_val > 20) & (atr > np.nanmean(atr) * 0.5)
        long_mask = long_entry_condition

        # Short entry: close < lower and adx > 20 and atr > mean(atr) * 0.5
        short_entry_condition = (close < lower) & (adx_val > 20) & (atr > np.nanmean(atr) * 0.5)
        short_mask = short_entry_condition

        # Exit conditions
        # Cross any close with middle or adx < 15
        prev_close = np.roll(close, 1)
        prev_middle = np.roll(middle, 1)
        prev_close[0] = np.nan
        prev_middle[0] = np.nan
        cross_up_middle = (close > middle) & (prev_close <= prev_middle)
        cross_down_middle = (close < middle) & (prev_close >= prev_middle)
        cross_any_middle = cross_up_middle | cross_down_middle

        exit_condition = cross_any_middle | (adx_val < 15)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels for long positions
        stop_atr_mult = params.get("stop_atr_mult", 1.75)
        tp_atr_mult = params.get("tp_atr_mult", 2.0)
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        entry_long_mask = (signals == 1.0)
        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        # Set SL/TP levels for short positions
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        entry_short_mask = (signals == -1.0)
        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
