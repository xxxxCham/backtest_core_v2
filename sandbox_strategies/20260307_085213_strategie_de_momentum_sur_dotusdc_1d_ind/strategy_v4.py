from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='builder_strategy')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

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
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # warmup protection
        signals.iloc[:warmup] = 0.0

        rsi5 = np.nan_to_num(indicators['rsi'])
        rsi14 = np.nan_to_num(indicators['rsi'])

        # Short signal: RSI(5) crosses below RSI(14)
        prev_rsi5 = np.roll(rsi5, 1)
        prev_rsi5[0] = np.nan
        prev_rsi14 = np.roll(rsi14, 1)
        prev_rsi14[0] = np.nan
        short_mask = (rsi5 < rsi14) & (prev_rsi5 >= prev_rsi14)

        # ATR-based stop-loss and take-profit
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Initialize SL/TP columns with NaN (no level = no stop)
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan

        # On entry signal bars only, compute ATR-based levels:
        long_mask_bool = (signals == 1.0)
        df.loc[long_mask_bool, "bb_stop_long"] = close[long_mask_bool] - stop_atr_mult * atr[long_mask_bool]
        df.loc[long_mask_bool, "bb_tp_long"] = close[long_mask_bool] + tp_atr_mult * atr[long_mask_bool]

        signals[short_mask] = -1.0
        signals.iloc[:warmup] = 0.0
        return signals