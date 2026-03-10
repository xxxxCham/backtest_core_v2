from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_rsi_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            'bollinger_period': 20,
            'bollinger_std_dev': 2,
            'leverage': 1,
            'rsi_period': 14,
            'stop_atr_mult': 1.5,
            'tp_atr_mult': 3.5,
            'warmup': 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'bollinger_period': ParameterSpec(
                name='bollinger_period',
                min_val=10,
                max_val=30,
                default=20,
                param_type='int',
                step=1,
            ),
            'bollinger_std_dev': ParameterSpec(
                name='bollinger_std_dev',
                min_val=1,
                max_val=3,
                default=2,
                param_type='float',
                step=0.1,
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
                max_val=6.0,
                default=3.5,
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

    def generate_signals(
        self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]
    ) -> pd.Series:
        n = len(df)
        warmup = int(params.get('warmup', 50))

        # Initialise signal series
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        # Extract price and indicator arrays
        close = df['close'].values
        bb = indicators['bollinger']
        upper = np.nan_to_num(bb['upper'])
        lower = np.nan_to_num(bb['lower'])
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Entry conditions
        long_entry = (close > upper) & (rsi > 55)
        short_entry = (close < lower) & (rsi < 45)

        # Apply warm‑up protection
        long_entry[:warmup] = False
        short_entry[:warmup] = False

        # Masks for entries (avoid overlap)
        long_mask = long_entry
        short_mask = short_entry & ~long_mask

        # Exit conditions: price crosses inside Bollinger band OR RSI crosses 50
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        cross_inside_upper = (prev_close > upper) & (close <= upper)
        cross_inside_lower = (prev_close < lower) & (close >= lower)
        cross_inside = cross_inside_upper | cross_inside_lower

        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        rsi_cross = ((rsi > 50) & (prev_rsi <= 50)) | ((rsi < 50) & (prev_rsi >= 50))

        exit_mask = cross_inside | rsi_cross
        exit_mask[:warmup] = False

        # Build raw position array (1 = long, -1 = short, 0 = flat)
        raw_arr = np.where(long_mask, 1.0, np.where(short_mask, -1.0, 0.0))
        pos_series = pd.Series(raw_arr, index=df.index)
        pos_series = pos_series.replace(0, np.nan).ffill().fillna(0.0)
        pos_series[exit_mask] = 0.0
        signals = pos_series.astype(np.float64)

        # ----- ATR‑based stop‑loss / take‑profit -----
        stop_atr_mult = params.get('stop_atr_mult', 1.5)
        tp_atr_mult = params.get('tp_atr_mult', 3.5)

        # Prepare columns
        df['bb_stop_long'] = np.nan
        df['bb_tp_long'] = np.nan
        df['bb_stop_short'] = np.nan
        df['bb_tp_short'] = np.nan

        # Long entries
        long_idx = np.where(long_mask)[0]
        if long_idx.size:
            df.iloc[long_idx, df.columns.get_loc('bb_stop_long')] = (
                close[long_idx] - stop_atr_mult * atr[long_idx]
            )
            df.iloc[long_idx, df.columns.get_loc('bb_tp_long')] = (
                close[long_idx] + tp_atr_mult * atr[long_idx]
            )

        # Short entries
        short_idx = np.where(short_mask)[0]
        if short_idx.size:
            df.iloc[short_idx, df.columns.get_loc('bb_stop_short')] = (
                close[short_idx] + stop_atr_mult * atr[short_idx]
            )
            df.iloc[short_idx, df.columns.get_loc('bb_tp_short')] = (
                close[short_idx] - tp_atr_mult * atr[short_idx]
            )

        # Ensure warm‑up period stays flat
        signals.iloc[:warmup] = 0.0

        return signals