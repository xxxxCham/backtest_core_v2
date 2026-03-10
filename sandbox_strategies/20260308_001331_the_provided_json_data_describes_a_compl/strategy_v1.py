from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_rsi_adx_trend_filter')

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
        adx = np.nan_to_num(adx_d["adx"])
        close = df["close"].values

        # Prepare band values
        upper = np.nan_to_num(bb["upper"])
        middle = np.nan_to_num(bb["middle"])
        lower = np.nan_to_num(bb["lower"])

        # Prepare previous values for crossovers
        prev_upper = np.roll(upper, 1)
        prev_middle = np.roll(middle, 1)
        prev_lower = np.roll(lower, 1)
        prev_close = np.roll(close, 1)

        prev_upper[0] = np.nan
        prev_middle[0] = np.nan
        prev_lower[0] = np.nan
        prev_close[0] = np.nan

        # Entry conditions
        rsi_overbought = params.get("rsi_overbought", 70)
        rsi_oversold = params.get("rsi_oversold", 30)
        adx_threshold = 25

        # Long entry: close crosses above upper band, RSI < 70, ADX > 25
        long_entry_cross = (close > upper) & (prev_close <= prev_upper)
        long_entry_rsi = rsi < rsi_overbought
        long_entry_adx = adx > adx_threshold

        long_mask = long_entry_cross & long_entry_rsi & long_entry_adx

        # Short entry: close crosses below lower band, RSI > 30, ADX > 25
        short_entry_cross = (close < lower) & (prev_close >= prev_lower)
        short_entry_rsi = rsi > rsi_oversold
        short_entry_adx = adx > adx_threshold

        short_mask = short_entry_cross & short_entry_rsi & short_entry_adx

        # Exit conditions
        # Exit long: close crosses below middle band OR ADX < 20
        exit_long_cross = (close < middle) & (prev_close >= prev_middle)
        exit_long_adx = adx < 20
        exit_long_mask = exit_long_cross | exit_long_adx

        # Exit short: close crosses above middle band OR ADX < 20
        exit_short_cross = (close > middle) & (prev_close <= prev_middle)
        exit_short_adx = adx < 20
        exit_short_mask = exit_short_cross | exit_short_adx

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exits
        # For exits, we need to be careful not to overwrite existing signals
        # We'll only exit positions that are currently open
        long_positions = signals == 1.0
        short_positions = signals == -1.0

        # For long exits
        signals[long_positions & exit_long_mask] = 0.0

        # For short exits
        signals[short_positions & exit_short_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based risk management
        atr = np.nan_to_num(indicators['atr'])
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Set stop-loss and take-profit for long entries
        entry_long = (signals == 1.0)
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        # Set stop-loss and take-profit for short entries
        entry_short = (signals == -1.0)
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals