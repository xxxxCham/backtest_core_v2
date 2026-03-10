from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_keltner_cci_refined')

    @property
    def required_indicators(self) -> List[str]:
        return ['keltner', 'cci', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'cci_overbought': 100,
         'cci_oversold': -100,
         'cci_period': 14,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'cci_period': ParameterSpec(
                name='cci_period',
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
        # implement explicit LONG / SHORT / FLAT logic
        # warmup protection
        signals.iloc[:warmup] = 0.0

        # Extract indicators
        kelt = indicators['keltner']
        upper = np.nan_to_num(kelt["upper"])
        middle = np.nan_to_num(kelt["middle"])
        lower = np.nan_to_num(kelt["lower"])
        cci = np.nan_to_num(indicators['cci'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # CCI thresholds
        cci_overbought = params.get("cci_overbought", 100)
        cci_oversold = params.get("cci_oversold", -100)

        # Entry conditions
        # Long entry: close crosses above upper band AND cci < oversold
        prev_upper = np.roll(upper, 1)
        prev_upper[0] = np.nan
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan

        long_entry = (close > upper) & (prev_close <= prev_upper) & (cci < cci_oversold)
        long_mask = long_entry

        # Short entry: close crosses below lower band AND cci > overbought
        prev_lower = np.roll(lower, 1)
        prev_lower[0] = np.nan

        short_entry = (close < lower) & (prev_close >= prev_lower) & (cci > cci_overbought)
        short_mask = short_entry

        # Exit conditions
        # Exit long: close crosses middle band or cci crosses 0
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        prev_cci = np.roll(cci, 1)
        prev_cci[0] = np.nan

        long_exit = (close < middle) & (prev_close >= prev_middle) | (cci < 0) & (prev_cci >= 0)
        long_mask = long_mask & ~long_exit

        # Exit short: close crosses middle band or cci crosses 0
        short_exit = (close > middle) & (prev_close <= prev_middle) | (cci > 0) & (prev_cci <= 0)
        short_mask = short_mask & ~short_exit

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Risk management: ATR-based stop-loss and take-profit
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        if np.any(entry_long_mask):
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        if np.any(entry_short_mask):
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
