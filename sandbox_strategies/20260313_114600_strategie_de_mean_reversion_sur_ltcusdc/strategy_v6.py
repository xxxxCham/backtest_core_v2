from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_rsi_atr_filtered')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'atr', 'bollinger']

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
        # implement explicit LONG / SHORT / FLAT logic
        # warmup protection
        signals.iloc[:warmup] = 0.0

        # Extract indicators
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        bb = indicators['bollinger']
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])
        close = df["close"].values

        # ATR filter
        atr_avg = np.nan_to_num(np.mean(atr))
        atr_filter = atr > atr_avg

        # Entry conditions
        # Long entry: close crosses above bb.lower AND rsi < oversold AND atr filter
        prev_close = np.roll(close, 1)
        prev_bb_lower = np.roll(indicators['bollinger']['lower'], 1)
        prev_close[0] = np.nan
        prev_bb_lower[0] = np.nan
        cross_above_lower = (close > indicators['bollinger']['lower']) & (prev_close <= prev_bb_lower)
        rsi_oversold = rsi < params["rsi_oversold"]
        long_condition = cross_above_lower & rsi_oversold & atr_filter

        # Short entry: close crosses below bb.upper AND rsi > overbought AND atr filter
        prev_bb_upper = np.roll(indicators['bollinger']['upper'], 1)
        prev_bb_upper[0] = np.nan
        cross_below_upper = (close < indicators['bollinger']['upper']) & (prev_close >= prev_bb_upper)
        rsi_overbought = rsi > params["rsi_overbought"]
        short_condition = cross_below_upper & rsi_overbought & atr_filter

        # Set masks
        long_mask = long_condition
        short_mask = short_condition

        # Exit conditions
        # Exit long: close crosses below bb.middle
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan
        exit_long = (close < indicators['bollinger']['middle']) & (prev_close >= prev_bb_middle)

        # Exit short: close crosses above bb.middle
        exit_short = (close > indicators['bollinger']['middle']) & (prev_close <= prev_bb_middle)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]

        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
