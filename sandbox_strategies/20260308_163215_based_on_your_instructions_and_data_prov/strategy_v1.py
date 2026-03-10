from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_rsi_atr_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr']

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
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Compute rolling mean of ATR for filtering
        atr_rolling_mean = np.convolve(atr, np.ones(50)/50, mode='valid')
        atr_rolling_mean = np.pad(atr_rolling_mean, (49, 0), mode='constant', constant_values=np.nan)

        # Define entry conditions
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        # Boolean masks for long and short entries
        upper = np.nan_to_num(bb["upper"])
        lower = np.nan_to_num(bb["lower"])
        middle = np.nan_to_num(bb["middle"])

        # Cross detection
        prev_close = np.roll(close, 1)
        prev_upper = np.roll(upper, 1)
        prev_lower = np.roll(lower, 1)
        prev_middle = np.roll(middle, 1)
        prev_rsi = np.roll(rsi, 1)
        prev_atr = np.roll(atr, 1)
        prev_atr_rolling_mean = np.roll(atr_rolling_mean, 1)

        prev_close[0] = np.nan
        prev_upper[0] = np.nan
        prev_lower[0] = np.nan
        prev_middle[0] = np.nan
        prev_rsi[0] = np.nan
        prev_atr[0] = np.nan
        prev_atr_rolling_mean[0] = np.nan

        # Long entry conditions
        long_entry_cross = (close > upper) & (prev_close <= prev_upper)
        long_rsi_condition = rsi > rsi_overbought
        long_atr_condition = atr > atr_rolling_mean

        long_mask = long_entry_cross & long_rsi_condition & long_atr_condition

        # Short entry conditions
        short_entry_cross = (close < lower) & (prev_close >= prev_lower)
        short_rsi_condition = rsi < rsi_oversold
        short_atr_condition = atr > atr_rolling_mean

        short_mask = short_entry_cross & short_rsi_condition & short_atr_condition

        # Exit conditions
        exit_long = (close < middle) | (rsi < rsi_overbought) | (rsi > rsi_oversold)
        exit_short = (close > middle) | (rsi > rsi_oversold) | (rsi < rsi_oversold)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Write SL/TP columns into df if using ATR-based risk management
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
