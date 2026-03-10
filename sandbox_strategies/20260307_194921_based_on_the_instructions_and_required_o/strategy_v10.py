from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='keltner_rsi_trend_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['keltner', 'rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
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

        # Extract indicators
        kelt = indicators['keltner']
        rsi = np.nan_to_num(indicators['rsi'])
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Prepare arrays for crossover detection
        indicators['keltner']['upper'] = np.nan_to_num(kelt["upper"])
        indicators['keltner']['lower'] = np.nan_to_num(kelt["lower"])
        indicators['keltner']['middle'] = np.nan_to_num(kelt["middle"])
        adx_val = np.nan_to_num(adx_d["adx"])

        # Previous values for crossovers
        prev_close = np.roll(close, 1)
        prev_kelt_upper = np.roll(indicators['keltner']['upper'], 1)
        prev_kelt_lower = np.roll(indicators['keltner']['lower'], 1)
        prev_kelt_middle = np.roll(indicators['keltner']['middle'], 1)
        prev_rsi = np.roll(rsi, 1)
        prev_adx_val = np.roll(adx_val, 1)

        # Set first values to NaN for proper crossover detection
        prev_close[0] = np.nan
        prev_kelt_upper[0] = np.nan
        prev_kelt_lower[0] = np.nan
        prev_kelt_middle[0] = np.nan
        prev_rsi[0] = np.nan
        prev_adx_val[0] = np.nan

        # Entry conditions
        long_entry = (close > indicators['keltner']['upper']) & (prev_close <= prev_kelt_upper) & (rsi > params["rsi_overbought"]) & (adx_val > 25)
        short_entry = (close < indicators['keltner']['lower']) & (prev_close >= prev_kelt_lower) & (rsi < params["rsi_oversold"]) & (adx_val > 25)

        # Exit conditions
        long_exit = (close < indicators['keltner']['middle']) | (adx_val < 20)
        short_exit = (close > indicators['keltner']['middle']) | (adx_val < 20)

        # Initialize masks
        long_mask = long_entry
        short_mask = short_entry

        # Apply exits to existing positions
        long_exit_mask = long_exit & (np.roll(signals, 1) == 1.0)
        short_exit_mask = short_exit & (np.roll(signals, 1) == -1.0)

        # Apply exits first to avoid conflicting signals
        signals[long_exit_mask] = 0.0
        signals[short_exit_mask] = 0.0

        # Apply entries
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]

        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
