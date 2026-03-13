from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_volatility_apeusdc_4h')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'obv', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_threshold': 0.005,
         'ema_period': 20,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 5.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=10,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=10.0,
                default=5.0,
                param_type='float',
                step=0.1,
            ),
            'atr_threshold': ParameterSpec(
                name='atr_threshold',
                min_val=0.001,
                max_val=0.02,
                default=0.005,
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
        # Warmup protection
        signals.iloc[:warmup] = 0.0
        # Extract indicators
        close = df["close"].values
        ema = np.nan_to_num(indicators['ema'])
        obv = np.nan_to_num(indicators['obv'])
        atr = np.nan_to_num(indicators['atr'])
        atr_threshold = params.get("atr_threshold", 0.005)
        ema_period = params.get("ema_period", 20)
        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 5.0)
        # Compute previous OBV for trend confirmation
        prev_obv = np.roll(obv, 1)
        prev_obv[0] = np.nan
        # Long entry: price crosses above EMA(20), OBV increasing, ATR above threshold
        close_ema_mask = close > ema
        obv_increasing = obv > prev_obv
        atr_condition = atr > atr_threshold
        long_entry_mask = close_ema_mask & obv_increasing & atr_condition
        # Short entry: price crosses below EMA(20), OBV decreasing, ATR above threshold
        close_ema_short_mask = close < ema
        obv_decreasing = obv < prev_obv
        short_entry_mask = close_ema_short_mask & obv_decreasing & atr_condition
        # Set long/short masks
        long_mask = long_entry_mask
        short_mask = short_entry_mask
        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        # ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan
        # Long SL/TP
        entry_long_mask = (signals == 1.0)
        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]
        # Short SL/TP
        entry_short_mask = (signals == -1.0)
        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
