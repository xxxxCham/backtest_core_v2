from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 60,
         'rsi_oversold': 20,
         'rsi_period': 17,
         'stop_atr_mult': 1.75,
         'tp_atr_mult': 3.5,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=50,
                default=17,
                param_type='int',
                step=1,
            ),
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
                min_val=2.0,
                max_val=4.5,
                default=3.5,
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
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Entry conditions
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])

        # Long entry: close < lower band and rsi < oversold
        long_entry = (close < indicators['bollinger']['lower']) & (rsi < params["rsi_oversold"])
        long_mask = long_entry

        # Short entry: close > upper band and rsi > overbought
        short_entry = (close > indicators['bollinger']['upper']) & (rsi > params["rsi_overbought"])
        short_mask = short_entry

        # Exit conditions: cross middle band or cross 50
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan

        cross_up_middle = (close > indicators['bollinger']['middle']) & (prev_close <= indicators['bollinger']['middle'])
        cross_down_middle = (close < indicators['bollinger']['middle']) & (prev_close >= indicators['bollinger']['middle'])
        cross_middle = cross_up_middle | cross_down_middle

        cross_up_rsi = (rsi > 50) & (prev_rsi <= 50)
        cross_down_rsi = (rsi < 50) & (prev_rsi >= 50)
        cross_rsi = cross_up_rsi | cross_down_rsi

        # Exit mask
        exit_mask = cross_middle | cross_rsi

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exit logic
        # Find entry bars and mark them for potential exit
        entry_long = signals == 1.0
        entry_short = signals == -1.0

        # Exit on next bar after entry if exit condition occurs
        exit_long = np.zeros(n, dtype=bool)
        exit_short = np.zeros(n, dtype=bool)

        # Shift exit mask to next bar
        exit_long_mask = np.zeros(n, dtype=bool)
        exit_short_mask = np.zeros(n, dtype=bool)

        # Use np.roll to shift exit condition to next bar
        exit_long_mask[:-1] = exit_mask[1:]
        exit_short_mask[:-1] = exit_mask[1:]

        # Apply exit conditions
        signals[exit_long_mask & entry_long] = 0.0
        signals[exit_short_mask & entry_short] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Set SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long SL/TP
        entry_long_mask = signals == 1.0
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]

        # Short SL/TP
        entry_short_mask = signals == -1.0
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
