from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_ema_pente_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'ema_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'threshold': 0.0001,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'threshold': ParameterSpec(
                name='threshold',
                min_val=5e-05,
                max_val=0.001,
                default=0.0001,
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
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=2.0,
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
        }

    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        n = len(df)
        warmup = int(params.get('warmup', 50))
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        # Get indicators
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])

        # Calculate momentum (slope of EMA)
        ema_diff = np.insert(np.diff(ema), 0, 0.0)  # Pad with first value

        long_mask = ema_diff > params["stop_atr_mult"]*atr
        short_mask = ema_diff < -params["stop_atr_mult"]*atr

        # Apply warmup period
        signals.iloc[:warmup] = 0.0

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Calculate and write stop-loss levels
        close = df["close"].values
        stop_mult = params.get("stop_atr_mult", 2.0)
        tp_mult = params.get("tp_atr_mult", 3.0)

        # Initialize columns with NaN
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        # Only set levels on entry bars (non-warmup period)
        entry_mask = (signals == 1.0) & (np.arange(n) >= warmup)
        df.loc[entry_mask, "bb_stop_long"] = close[entry_mask] - stop_mult * atr[entry_mask]
        df.loc[entry_mask, "bb_tp_long"] = close[entry_mask] + tp_mult * atr[entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
