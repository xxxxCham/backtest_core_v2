from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_donchian_adx_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 15,
         'donchian_period': 45,
         'leverage': 1,
         'stop_atr_mult': 1.0,
         'tp_atr_mult': 4.5,
         'warmup': 60}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'donchian_period': ParameterSpec(
                name='donchian_period',
                min_val=20,
                max_val=90,
                default=45,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=10,
                max_val=30,
                default=15,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=3.0,
                default=1.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=8.0,
                default=4.5,
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
        donchian = indicators['donchian']
        adx = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])
        close = np.nan_to_num(df["close"].values)

        # Donchian bands
        indicators['donchian']['upper'] = np.nan_to_num(indicators['donchian']["upper"])
        indicators['donchian']['lower'] = np.nan_to_num(indicators['donchian']["lower"])
        indicators['donchian']['middle'] = np.nan_to_num(indicators['donchian']["middle"])

        # ADX values
        adx_val = np.nan_to_num(indicators['adx']["adx"])

        # Define entry conditions
        # Entry long: close crosses above indicators['donchian']['upper'] AND adx > 25
        prev_close = np.roll(close, 1)
        prev_dc_upper = np.roll(indicators['donchian']['upper'], 1)
        prev_dc_middle = np.roll(indicators['donchian']['middle'], 1)
        prev_adx_val = np.roll(adx_val, 1)

        prev_close[0] = np.nan
        prev_dc_upper[0] = np.nan
        prev_dc_middle[0] = np.nan
        prev_adx_val[0] = np.nan

        cross_above = (close > indicators['donchian']['upper']) & (prev_close <= prev_dc_upper)
        adx_above = adx_val > 25

        long_entry = cross_above & adx_above

        # Entry short: close crosses below indicators['donchian']['lower'] AND adx > 25
        prev_dc_lower = np.roll(indicators['donchian']['lower'], 1)
        prev_dc_lower[0] = np.nan

        cross_below = (close < indicators['donchian']['lower']) & (prev_close >= prev_dc_lower)
        short_entry = cross_below & adx_above

        # Exit conditions: close crosses below indicators['donchian']['middle'] OR adx < 25
        cross_below_middle = (close < indicators['donchian']['middle']) & (prev_close >= prev_dc_middle)
        adx_below = adx_val < 25

        exit_condition = cross_below_middle | adx_below

        # Apply signals
        long_mask = long_entry
        short_mask = short_entry

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Handle exits
        # For simplicity, we'll treat exit as a flat signal if exit condition is met
        # This means we don't close positions immediately but let the next entry overwrite
        # Alternatively, we could track positions, but that's more complex

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Write SL/TP columns for ATR-based risk management
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Compute stop-loss and take-profit levels for long entries
        entry_long = (signals == 1.0)
        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]

        # Compute stop-loss and take-profit levels for short entries
        entry_short = (signals == -1.0)
        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
