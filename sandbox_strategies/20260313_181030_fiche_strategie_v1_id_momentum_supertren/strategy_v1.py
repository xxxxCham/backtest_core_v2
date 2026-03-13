from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_supertrend_adx_volume')

    @property
    def required_indicators(self) -> List[str]:
        return ['supertrend', 'adx', 'volume_oscillator', 'atr']

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
        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===
        long_mask = np.zeros(n, dtype=bool)
        short_mask = np.zeros(n, dtype=bool)

        # Extract indicator arrays safely
        close = df["close"].values
        supertrend_val = np.nan_to_num(indicators['supertrend']["supertrend"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        vol_osc = np.nan_to_num(indicators['volume_oscillator'])
        atr = np.nan_to_num(indicators['atr'])

        # Cross detection helper
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_supertrend = np.roll(supertrend_val, 1)
        prev_supertrend[0] = np.nan
        cross_up = (close > supertrend_val) & (prev_close <= prev_supertrend)
        cross_down = (close < supertrend_val) & (prev_close >= prev_supertrend)
        cross_any = cross_up | cross_down

        # Exit signals
        exit_mask = cross_any
        signals[exit_mask] = 0.0

        # Entry signals
        long_mask = (close > supertrend_val) & (adx_val > 25) & (vol_osc > 0)
        short_mask = (close < supertrend_val) & (adx_val > 25) & (vol_osc < 0)

        entry_mask_long = long_mask & (signals == 0.0)
        entry_mask_short = short_mask & (signals == 0.0)

        signals[entry_mask_long] = 1.0
        signals[entry_mask_short] = -1.0

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Set ATR-based SL/TP only on entry bars
        df.loc[entry_mask_long, "bb_stop_long"] = close[entry_mask_long] - stop_atr_mult * atr[entry_mask_long]
        df.loc[entry_mask_long, "bb_tp_long"] = close[entry_mask_long] + tp_atr_mult * atr[entry_mask_long]
        df.loc[entry_mask_short, "bb_stop_short"] = close[entry_mask_short] + stop_atr_mult * atr[entry_mask_short]
        df.loc[entry_mask_short, "bb_tp_short"] = close[entry_mask_short] - tp_atr_mult * atr[entry_mask_short]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
