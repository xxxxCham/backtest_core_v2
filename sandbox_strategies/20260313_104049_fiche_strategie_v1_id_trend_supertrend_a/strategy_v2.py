from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_supertrend_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['adx', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'ema_period': 20,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 4.0,
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
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=10,
                max_val=30,
                default=14,
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
                max_val=8.0,
                default=4.0,
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
        adx_d = indicators['adx']
        adx_val = np.nan_to_num(adx_d["adx"])
        ema_vals = np.nan_to_num(indicators['ema'])
        close = df["close"].values
        atr = np.nan_to_num(indicators['atr'])

        # Entry conditions
        ema_period = int(params.get("ema_period", 20))
        adx_period = int(params.get("adx_period", 14))

        # EMA crossover signals
        prev_ema = np.roll(ema_vals, 1)
        prev_ema[0] = np.nan
        cross_up_ema = (close > ema_vals) & (prev_ema <= ema_vals)
        cross_down_ema = (close < ema_vals) & (prev_ema >= ema_vals)

        # Long entry: price crosses above EMA and ADX > 25
        long_entry = cross_up_ema & (adx_val > 25)
        long_mask = long_entry

        # Short entry: price crosses below EMA and ADX > 25
        short_entry = cross_down_ema & (adx_val > 25)
        short_mask = short_entry

        # Exit conditions
        # Exit long: ADX < 20 OR EMA crosses below close
        adx_below_20_long = (adx_val < 20) & long_mask
        exit_long = adx_below_20_long | (cross_down_ema & long_mask)

        # Exit short: ADX < 20 OR EMA crosses above close
        adx_below_20_short = (adx_val < 20) & short_mask
        exit_short = adx_below_20_short | (cross_up_ema & short_mask)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_long] = 0.0
        signals[exit_short] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Risk management: ATR-based stop-loss and take-profit
        stop_atr_mult = float(params.get("stop_atr_mult", 2.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 4.0))

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Set SL/TP for long entries
        entry_long_mask = (signals == 1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        # Set SL/TP for short entries
        entry_short_mask = (signals == -1.0)
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
