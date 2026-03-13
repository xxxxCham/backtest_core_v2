from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_mean_reversion_adx_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'atr', 'adx']

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

        # unpack indicators with np.nan_to_num
        bb = indicators['bollinger']
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])
        atr = np.nan_to_num(indicators['atr'])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        close = df["close"].values

        # helper cross functions
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        prev_upper = np.roll(upper, 1)
        prev_upper[0] = np.nan
        prev_lower = np.roll(lower, 1)
        prev_lower[0] = np.nan

        cross_up_middle = (close > middle) & (prev_close <= prev_middle)
        cross_down_middle = (close < middle) & (prev_close >= prev_middle)

        # long entry: cross up middle and previous close below lower and adx < 25
        long_mask = cross_up_middle & (prev_close < lower) & (adx_val < 25)

        # short entry: cross down middle and previous close above upper and adx < 25
        short_mask = cross_down_middle & (prev_close > upper) & (adx_val < 25)

        # exit conditions: cross any middle or adx >= 25
        exit_mask = cross_up_middle | cross_down_middle | (adx_val >= 25)

        # apply warmup
        signals.iloc[:warmup] = 0.0

        # set entry signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # apply exit signals (flat)
        signals[exit_mask] = 0.0

        # write ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        # long entry levels
        long_entries = (signals == 1.0)
        df.loc[long_entries, "bb_stop_long"] = close[long_entries] - stop_atr_mult * atr[long_entries]
        df.loc[long_entries, "bb_tp_long"] = close[long_entries] + tp_atr_mult * atr[long_entries]

        # short entry levels
        short_entries = (signals == -1.0)
        df.loc[short_entries, "bb_stop_short"] = close[short_entries] + stop_atr_mult * atr[short_entries]
        df.loc[short_entries, "bb_tp_short"] = close[short_entries] - tp_atr_mult * atr[short_entries]
        signals.iloc[:warmup] = 0.0
        return signals
