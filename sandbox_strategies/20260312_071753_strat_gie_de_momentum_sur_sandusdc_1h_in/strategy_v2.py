from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_ema_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
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
                min_val=1.0,
                max_val=6.0,
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

        # Get indicators with NaN handling
        ema = np.nan_to_num(indicators['ema'])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Warmup period
        signals[:warmup] = 0.0

        # Define EMA crossover conditions
        ema_12 = ema[12-1]
        ema_26 = ema[26-1]
        cross_up = (ema_12 > ema_26)
        cross_down = (ema_12 < ema_26)

        # Define RSI conditions
        rsi_long = (rsi > 65)
        rsi_short = (rsi < 40)

        # Generate long signals where both conditions are met
        long_conditions = cross_up & rsi_long
        long_mask[:] = long_conditions

        # Generate short signals where both conditions are met
        short_conditions = cross_down & rsi_short
        short_mask[:] = short_conditions

        # Set signals based on conditions
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Write SL/TP levels to df for ATR-based risk management
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        close = df["close"].values

        df["bb_stop_long"] = np.nan
        df["bb_tp_long"] = np.nan
        df["bb_stop_short"] = np.nan
        df["bb_tp_short"] = np.nan

        # Calculate stop and take profit levels for entries
        entry_mask = (signals == 1.0) | (signals == -1.0)

        if entry_mask.any():
            df.loc[entry_mask, "bb_stop_long"] = close[entry_mask] - stop_atr_mult * atr[entry_mask]
            df.loc[entry_mask, "bb_tp_long"] = close[entry_mask] + tp_atr_mult * atr[entry_mask]

            # For shorts (commented out as per original logic)
            # df.loc[short_mask, "bb_stop_short"] = close[short_mask] + stop_atr_mult * atr[short_mask]
            # df.loc[short_mask, "bb_tp_short"] = close[short_mask] - tp_atr_mult * atr[short_mask]

        return signals