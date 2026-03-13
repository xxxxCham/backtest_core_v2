from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_rsi_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_threshold_entry': 25,
         'adx_threshold_exit': 30,
         'leverage': 1,
         'rsi_period_long': 14,
         'rsi_period_short': 5,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period_short': ParameterSpec(
                name='rsi_period_short',
                min_val=2,
                max_val=30,
                default=5,
                param_type='int',
                step=1,
            ),
            'rsi_period_long': ParameterSpec(
                name='rsi_period_long',
                min_val=8,
                max_val=50,
                default=14,
                param_type='int',
                step=1,
            ),
            'adx_threshold_entry': ParameterSpec(
                name='adx_threshold_entry',
                min_val=10,
                max_val=50,
                default=25,
                param_type='int',
                step=1,
            ),
            'adx_threshold_exit': ParameterSpec(
                name='adx_threshold_exit',
                min_val=20,
                max_val=60,
                default=30,
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

        signals.iloc[:warmup] = 0.0

        rsi_5 = np.nan_to_num(indicators['rsi'])
        rsi_14 = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        adx_val = np.nan_to_num(indicators['adx']['adx'])

        rsi_5_prev = np.roll(rsi_5, 1)
        rsi_14_prev = np.roll(rsi_14, 1)
        adx_val_prev = np.roll(adx_val, 1)
        adx_val_prev[0] = np.nan
        rsi_5_prev[0] = np.nan
        rsi_14_prev[0] = np.nan

        short_cross = (rsi_5 < rsi_14) & (rsi_5_prev >= rsi_14_prev)
        long_cross = (rsi_5 > rsi_14) & (rsi_5_prev <= rsi_14_prev)

        short_mask = short_cross & (adx_val < params["adx_threshold_entry"])
        long_mask = long_cross & (adx_val < params["adx_threshold_entry"])

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based stop-loss and take-profit
        close = df["close"].values
        entry_mask_long = signals == 1.0
        entry_mask_short = signals == -1.0

        df.loc[entry_mask_long, "bb_stop_long"] = close[entry_mask_long] - params["stop_atr_mult"] * atr[entry_mask_long]
        df.loc[entry_mask_long, "bb_tp_long"] = close[entry_mask_long] + params["tp_atr_mult"] * atr[entry_mask_long]
        df.loc[entry_mask_short, "bb_stop_short"] = close[entry_mask_short] + params["stop_atr_mult"] * atr[entry_mask_short]
        df.loc[entry_mask_short, "bb_tp_short"] = close[entry_mask_short] - params["tp_atr_mult"] * atr[entry_mask_short]
        signals.iloc[:warmup] = 0.0
        return signals