from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='adx_filtered_bollinger_rsi_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr', 'adx']

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

        # Extract and clean indicators
        bb = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])

        close = df["close"].values
        open_ = df["open"].values

        # Get threshold values from params
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        # Prepare cross detection
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])

        # Previous values for crossovers
        prev_close = np.roll(close, 1)
        prev_bb_upper = np.roll(indicators['bollinger']['upper'], 1)
        prev_bb_lower = np.roll(indicators['bollinger']['lower'], 1)
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_rsi = np.roll(rsi, 1)
        prev_adx = np.roll(adx, 1)

        # Set first values to NaN to avoid false signals
        prev_close[0] = np.nan
        prev_bb_upper[0] = np.nan
        prev_bb_lower[0] = np.nan
        prev_bb_middle[0] = np.nan
        prev_rsi[0] = np.nan
        prev_adx[0] = np.nan

        # Entry conditions
        long_condition = (close > indicators['bollinger']['upper']) & (prev_close <= prev_bb_upper) & (rsi > rsi_overbought) & (adx > 25)
        short_condition = (close < indicators['bollinger']['lower']) & (prev_close >= prev_bb_lower) & (rsi < rsi_oversold) & (adx > 25)

        # Exit conditions
        long_exit = (close < indicators['bollinger']['middle']) | (prev_adx >= 20) | (adx < 20)
        short_exit = (close > indicators['bollinger']['middle']) | (prev_adx >= 20) | (adx < 20)

        # Generate masks
        long_mask = long_condition
        short_mask = short_condition

        # Apply exit conditions
        exit_long_mask = long_exit
        exit_short_mask = short_exit

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exits
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Set SL/TP levels for long entries
        entry_long_mask = (signals == 1.0)
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        # Set SL/TP levels for short entries
        entry_short_mask = (signals == -1.0)
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
