from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='volatility_efficiency_keltner_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['keltner', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'adx_period': 14,
         'keltner_atr_period': 14,
         'keltner_multiplier': 1.5,
         'keltner_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=5,
                max_val=30,
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
                min_val=1.0,
                max_val=8.0,
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

        # Extract indicators
        kelt = indicators['keltner']
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        close = df["close"].values
        indicators['keltner']['upper'] = np.nan_to_num(kelt["upper"])
        indicators['keltner']['lower'] = np.nan_to_num(kelt["lower"])
        adx_val = np.nan_to_num(adx_d["adx"])

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Entry conditions
        # Long entry: close crosses above indicators['keltner']['upper'] band AND adx > 25 AND previous close <= previous indicators['keltner']['upper'] band
        prev_close = np.roll(close, 1)
        prev_kelt_upper = np.roll(indicators['keltner']['upper'], 1)
        prev_close[0] = np.nan
        prev_kelt_upper[0] = np.nan

        long_entry = (close > indicators['keltner']['upper']) & (prev_close <= prev_kelt_upper) & (adx_val > 25)
        long_mask = long_entry

        # Short entry: close crosses below indicators['keltner']['lower'] band AND adx > 25 AND previous close >= previous indicators['keltner']['lower'] band
        prev_kelt_lower = np.roll(indicators['keltner']['lower'], 1)
        prev_kelt_lower[0] = np.nan

        short_entry = (close < indicators['keltner']['lower']) & (prev_close >= prev_kelt_lower) & (adx_val > 25)
        short_mask = short_entry

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        entry_long = (signals == 1.0)
        entry_short = (signals == -1.0)

        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
