from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_breakout_adx')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'capital': 10000,
         'fees': 10.0,
         'leverage': 1,
         'slippage': 5.0,
         'stop_atr_mult': 2.75,
         'tp_atr_mult': 4.5,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=5.0,
                default=2.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=6.0,
                default=4.5,
                param_type='float',
                step=0.1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=50,
                default=19,
                param_type='int',
                step=1,
            ),
            'donchian_period': ParameterSpec(
                name='donchian_period',
                min_val=20,
                max_val=100,
                default=50,
                param_type='int',
                step=1,
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

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Get indicators
        donchian = indicators['donchian']
        adx = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        # Extract Donchian upper and lower bands
        upper_band = indicators['donchian']["upper"]
        lower_band = indicators['donchian']["lower"]

        # Get ADX values
        adx_val = np.nan_to_num(indicators['adx']["adx"])

        # Compute crosses
        prev_upper = np.roll(upper_band, 1)
        prev_lower = np.roll(lower_band, 1)

        # Long signals: close > upper band and ADX > 25
        long_mask = (df["close"].values > upper_band) & (adx_val > 25)
        long_mask[:warmup] = False

        # Short signals: close < lower band and ADX > 25
        short_mask = (df["close"].values < lower_band) & (adx_val > 25)
        short_mask[:warmup] = False

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Calculate ATR-based stop and target levels
        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Initialize SL/TP columns with NaN
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Calculate stop and target for long signals
        entry_mask_long = (signals == 1.0)
        close_long = df["close"].values[entry_mask_long]
        atr_long = atr[entry_mask_long]

        df.loc[entry_mask_long, "bb_stop_long"] = close_long - stop_atr_mult * atr_long
        df.loc[entry_mask_long, "bb_tp_long"] = close_long + tp_atr_mult * atr_long

        # Calculate stop and target for short signals
        entry_mask_short = (signals == -1.0)
        close_short = df["close"].values[entry_mask_short]
        atr_short = atr[entry_mask_short]

        df.loc[entry_mask_short, "bb_stop_short"] = close_short + stop_atr_mult * atr_short
        df.loc[entry_mask_short, "bb_tp_short"] = close_short - tp_atr_mult * atr_short
        signals.iloc[:warmup] = 0.0
        return signals
