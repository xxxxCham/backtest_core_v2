from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_rsi_adx_filter')

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

        # Extract indicators
        bb = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        # Price arrays
        close = df["close"].values
        upper_band = np.nan_to_num(bb["upper"])
        middle_band = np.nan_to_num(bb["middle"])
        lower_band = np.nan_to_num(bb["lower"])
        adx_val = np.nan_to_num(adx_d["adx"])

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Cross detection
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_upper_band = np.roll(upper_band, 1)
        prev_upper_band[0] = np.nan
        prev_lower_band = np.roll(lower_band, 1)
        prev_lower_band[0] = np.nan
        prev_middle_band = np.roll(middle_band, 1)
        prev_middle_band[0] = np.nan

        # Long entry: close crosses above upper band AND rsi < 65 AND adx > 20
        cross_above_upper = (close > upper_band) & (prev_close <= prev_upper_band)
        rsi_long_cond = rsi < params["rsi_overbought"]
        adx_long_cond = adx_val > 20
        long_entry = cross_above_upper & rsi_long_cond & adx_long_cond

        # Short entry: close crosses below lower band AND rsi > 35 AND adx > 20
        cross_below_lower = (close < lower_band) & (prev_close >= prev_lower_band)
        rsi_short_cond = rsi > params["rsi_oversold"]
        adx_short_cond = adx_val > 20
        short_entry = cross_below_lower & rsi_short_cond & adx_short_cond

        # Exit: close crosses below middle band OR adx < 20
        cross_below_middle = (close < middle_band) & (prev_close >= prev_middle_band)
        adx_exit = adx_val < 20
        exit_signal = cross_below_middle | adx_exit

        # Set masks
        long_mask = long_entry
        short_mask = short_entry

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels for long entries
        entry_long = (signals == 1.0)
        if entry_long.any():
            df.loc[:, "bb_stop_long"] = np.nan
            df.loc[:, "bb_tp_long"] = np.nan
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]

        # Set SL/TP levels for short entries
        entry_short = (signals == -1.0)
        if entry_short.any():
            df.loc[:, "bb_stop_short"] = np.nan
            df.loc[:, "bb_tp_short"] = np.nan
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
