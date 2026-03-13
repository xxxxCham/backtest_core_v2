from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_adx_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 12,
         'bollinger_period': 20,
         'bollinger_std': 2,
         'leverage': 1,
         'stop_atr_mult': 2.25,
         'tp_atr_mult': 5.0,
         'warmup': 50}

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
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=30,
                default=12,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.25,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=10.0,
                default=5.0,
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
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Get band values
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])

        # Get ADX values
        adx_val = np.nan_to_num(adx_d["adx"])

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Entry conditions
        # Long entry: close crosses above bb.lower AND adx > 25
        prev_close = np.roll(close, 1)
        prev_bb_lower = np.roll(indicators['bollinger']['lower'], 1)
        prev_bb_lower[0] = np.nan

        cross_above_lower = (close > indicators['bollinger']['lower']) & (prev_close <= prev_bb_lower)

        long_entry = cross_above_lower & (adx_val > 25)
        long_mask[long_entry] = True

        # Short entry: close crosses below bb.upper AND adx > 25
        prev_bb_upper = np.roll(indicators['bollinger']['upper'], 1)
        prev_bb_upper[0] = np.nan

        cross_below_upper = (close < indicators['bollinger']['upper']) & (prev_close >= prev_bb_upper)

        short_entry = cross_below_upper & (adx_val > 25)
        short_mask[short_entry] = True

        # Exit conditions
        # Exit long: close crosses bb.middle OR adx < 20
        prev_close = np.roll(close, 1)
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan

        cross_middle_long = (close < indicators['bollinger']['middle']) & (prev_close >= prev_bb_middle)

        long_exit = cross_middle_long | (adx_val < 20)
        long_mask[long_exit] = False

        # Exit short: close crosses bb.middle OR adx < 20
        prev_close = np.roll(close, 1)
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan

        cross_middle_short = (close > indicators['bollinger']['middle']) & (prev_close <= prev_bb_middle)

        short_exit = cross_middle_short | (adx_val < 20)
        short_mask[short_exit] = False

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 2.25)
        tp_atr_mult = params.get("tp_atr_mult", 5.0)

        entry_long = (signals == 1.0)
        entry_short = (signals == -1.0)

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
