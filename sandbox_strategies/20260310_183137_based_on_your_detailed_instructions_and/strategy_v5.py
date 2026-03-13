from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_filtered_mean_reversion')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=50,
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
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=1,
                param_type='int',
                step=1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=4.5,
                default=3.0,
                param_type='float',
                step=0.1,
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
        rsi = np.nan_to_num(indicators['rsi'])
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Prepare band arrays
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])

        # Prepare ADX arrays
        adx_val = np.nan_to_num(adx_d["adx"])

        # Define entry conditions
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]
        adx_threshold = 25

        # Entry long: close crosses above bb.lower AND rsi < 30 AND adx > 25
        prev_close = np.roll(close, 1)
        prev_bb_lower = np.roll(indicators['bollinger']['lower'], 1)
        prev_close[0] = np.nan
        prev_bb_lower[0] = np.nan

        cross_above_lower = (close > indicators['bollinger']['lower']) & (prev_close <= prev_bb_lower)

        long_entry_condition = (cross_above_lower) & (rsi < rsi_oversold) & (adx_val > adx_threshold)
        long_mask = long_entry_condition

        # Entry short: close crosses below bb.upper AND rsi > 70 AND adx > 25
        prev_bb_upper = np.roll(indicators['bollinger']['upper'], 1)
        prev_bb_upper[0] = np.nan

        cross_below_upper = (close < indicators['bollinger']['upper']) & (prev_close >= prev_bb_upper)

        short_entry_condition = (cross_below_upper) & (rsi > rsi_overbought) & (adx_val > adx_threshold)
        short_mask = short_entry_condition

        # Exit condition: close crosses bb.middle OR adx < 20
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan

        cross_middle = (close > indicators['bollinger']['middle']) & (prev_close <= prev_bb_middle)
        adx_exit = adx_val < 20

        # Generate signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        # Long entries
        entry_long_mask = (signals == 1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        # Short entries
        entry_short_mask = (signals == -1.0)
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
