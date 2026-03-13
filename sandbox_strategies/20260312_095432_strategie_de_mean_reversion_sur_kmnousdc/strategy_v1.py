from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_mean_reversion_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'bollinger_period': 20,
         'bollinger_std_dev': 2,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 20}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'bollinger_period': ParameterSpec(
                name='bollinger_period',
                min_val=10,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
            ),
            'bollinger_std_dev': ParameterSpec(
                name='bollinger_std_dev',
                min_val=1.5,
                max_val=3.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
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

        # unwrap indicators
        bb = indicators['bollinger']
        middle = np.nan_to_num(bb["middle"])
        upper = np.nan_to_num(bb["upper"])
        lower = np.nan_to_num(bb["lower"])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # cross helpers
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan

        # long entry: close crosses above middle AND previous close < lower
        long_cross_up = (close > middle) & (prev_close <= prev_middle)
        long_cond = long_cross_up & (prev_close < lower)
        long_mask = long_cond

        # short entry: close crosses below middle AND previous close > upper
        short_cross_down = (close < middle) & (prev_close >= prev_middle)
        short_cond = short_cross_down & (prev_close > upper)
        short_mask = short_cond

        # apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR based SL/TP on entry bars
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        long_entry = signals == 1.0
        df.loc[long_entry, "bb_stop_long"] = close[long_entry] - stop_atr_mult * atr[long_entry]
        df.loc[long_entry, "bb_tp_long"] = close[long_entry] + tp_atr_mult * atr[long_entry]

        short_entry = signals == -1.0
        df.loc[short_entry, "bb_stop_short"] = close[short_entry] + stop_atr_mult * atr[short_entry]
        df.loc[short_entry, "bb_tp_short"] = close[short_entry] - tp_atr_mult * atr[short_entry]
        signals.iloc[:warmup] = 0.0
        return signals
