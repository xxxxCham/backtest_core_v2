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

        # Prepare band values
        upper_band = np.nan_to_num(bb["upper"])
        middle_band = np.nan_to_num(bb["middle"])
        lower_band = np.nan_to_num(bb["lower"])

        # Prepare ADX values
        adx = np.nan_to_num(adx_d["adx"])

        # Define thresholds
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]
        adx_threshold = 25
        exit_adx_threshold = 20

        # Compute previous values for crossovers
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_upper_band = np.roll(upper_band, 1)
        prev_upper_band[0] = np.nan
        prev_lower_band = np.roll(lower_band, 1)
        prev_lower_band[0] = np.nan
        prev_middle_band = np.roll(middle_band, 1)
        prev_middle_band[0] = np.nan
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        prev_adx = np.roll(adx, 1)
        prev_adx[0] = np.nan

        # Entry conditions
        # Long entry: close crosses above lower band, RSI < oversold, ADX > threshold
        long_entry_cross = (close > lower_band) & (prev_close <= prev_lower_band)
        long_entry_rsi = rsi < rsi_oversold
        long_entry_adx = adx > adx_threshold
        long_mask = long_entry_cross & long_entry_rsi & long_entry_adx

        # Short entry: close crosses below upper band, RSI > overbought, ADX > threshold
        short_entry_cross = (close < upper_band) & (prev_close >= prev_upper_band)
        short_entry_rsi = rsi > rsi_overbought
        short_entry_adx = adx > adx_threshold
        short_mask = short_entry_cross & short_entry_rsi & short_entry_adx

        # Exit conditions
        # Exit long: close crosses above middle band OR ADX < exit_threshold
        long_exit_cross = (close > middle_band) & (prev_close <= prev_middle_band)
        long_exit_adx = adx < exit_adx_threshold
        long_exit_mask = long_exit_cross | long_exit_adx
        long_exit_mask = long_exit_mask & (signals != 0.0)

        # Exit short: close crosses below middle band OR ADX < exit_threshold
        short_exit_cross = (close < middle_band) & (prev_close >= prev_middle_band)
        short_exit_adx = adx < exit_adx_threshold
        short_exit_mask = short_exit_cross | short_exit_adx
        short_exit_mask = short_exit_mask & (signals != 0.0)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[long_exit_mask] = 0.0
        signals[short_exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

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
