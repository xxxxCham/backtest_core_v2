from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_ema_atr_v3')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'ema_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=1,
                param_type='int',
                step=1,
            ),
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=5,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
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
            'warmup': ParameterSpec(
                name='warmup',
                min_val=0,
                max_val=100,
                default=50,
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

        # Warmup period
        signals.iloc[:warmup] = 0.0

        # Get indicators
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Calculate EMA momentum
        ema_diff = np.insert(np.diff(ema), 0, 0.0)

        # Generate signals based on EMA crossover
        long_mask = (ema_diff > 0) & (np.roll(ema_diff, 1) <= 0)
        short_mask = (ema_diff < 0) & (np.roll(ema_diff, 1) >= 0)

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Risk management with ATR
        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Calculate stop and take profit levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_mask_long = (signals == 1.0)
        entry_mask_short = (signals == -1.0)

        # For long entries
        df.loc[entry_mask_long, "bb_stop_long"] = close[entry_mask_long] - stop_atr_mult * atr[entry_mask_long]
        df.loc[entry_mask_long, "bb_tp_long"] = close[entry_mask_long] + tp_atr_mult * atr[entry_mask_long]

        # For short entries
        df.loc[entry_mask_short, "bb_stop_short"] = close[entry_mask_short] + stop_atr_mult * atr[entry_mask_short]
        df.loc[entry_mask_short, "bb_tp_short"] = close[entry_mask_short] - tp_atr_mult * atr[entry_mask_short]
        signals.iloc[:warmup] = 0.0
        return signals
