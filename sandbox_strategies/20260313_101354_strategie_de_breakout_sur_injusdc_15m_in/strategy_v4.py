from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='injusdc_breakout_strategy')

    @property
    def required_indicators(self) -> List[str]:
        return ['ema', 'obv', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_threshold': 0.005,
         'ema_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.0,
         'tp_atr_mult': 2.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=5,
                max_val=50,
                default=20,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=6.0,
                default=2.0,
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

        ema = np.nan_to_num(indicators['ema'])
        obv = np.nan_to_num(indicators['obv'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Warmup
        signals.iloc[:warmup] = 0.0

        # Entry conditions
        ema_period = int(params.get("ema_period", 20))
        atr_threshold = float(params.get("atr_threshold", 0.005))

        # Cross up/down for EMA
        prev_ema = np.roll(ema, 1)
        prev_ema[0] = np.nan
        close_ema_up = (close > ema) & (prev_ema <= ema)
        close_ema_down = (close < ema) & (prev_ema >= ema)

        # OBV trend
        obv_diff = np.insert(np.diff(obv), 0, 0.0)
        obv_increasing = obv_diff > 0
        obv_decreasing = obv_diff < 0

        # ATR threshold
        atr_above_threshold = atr > atr_threshold

        # Long entry: close crosses above EMA AND OBV increasing AND ATR above threshold
        long_entry = close_ema_up & obv_increasing & atr_above_threshold

        # Short entry: close crosses below EMA AND OBV decreasing AND ATR above threshold
        short_entry = close_ema_down & obv_decreasing & atr_above_threshold

        long_mask = long_entry
        short_mask = short_entry

        # Exit conditions (cross EMA)
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        exit_long = close_ema_down
        exit_short = close_ema_up

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Write SL/TP levels into df if using ATR-based risk management
        stop_atr_mult = float(params.get("stop_atr_mult", 1.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 2.0))

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
