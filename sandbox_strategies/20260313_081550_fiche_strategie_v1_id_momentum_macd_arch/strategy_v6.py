from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_macd_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 80,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 2.25,
         'tp_atr_mult': 3.5,
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
                min_val=1.0,
                max_val=5.0,
                default=2.25,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=4.5,
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
        rsi = np.nan_to_num(indicators['rsi'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])
        atr = np.nan_to_num(indicators['atr'])

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Entry conditions
        # Long entry: RSI crosses above 50 AND ADX > 25 AND RSI < 70
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        rsi_cross_up_50 = (rsi > 50) & (prev_rsi <= 50)
        long_condition = rsi_cross_up_50 & (adx > 25) & (rsi < 70)
        long_mask = long_condition

        # Short entry: RSI crosses below 50 AND ADX > 25 AND RSI > 30
        rsi_cross_down_50 = (rsi < 50) & (prev_rsi >= 50)
        short_condition = rsi_cross_down_50 & (adx > 25) & (rsi > 30)
        short_mask = short_condition

        # Exit conditions
        # Exit long/short if RSI overbought/oversold or ADX weak
        exit_long = (rsi > params["rsi_overbought"]) | (rsi < params["rsi_oversold"]) | (adx < 20)
        exit_short = (rsi > params["rsi_overbought"]) | (rsi < params["rsi_oversold"]) | (adx < 20)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exit conditions
        # For simplicity, we'll treat exit as flat signal
        exit_long_mask = exit_long & (np.roll(signals, 1) == 1.0)
        exit_short_mask = exit_short & (np.roll(signals, 1) == -1.0)
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # ATR-based SL/TP levels
        close = df["close"].values
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        long_entry_mask = signals == 1.0
        if np.any(long_entry_mask):
            df.loc[long_entry_mask, "bb_stop_long"] = close[long_entry_mask] - params["stop_atr_mult"] * atr[long_entry_mask]
            df.loc[long_entry_mask, "bb_tp_long"] = close[long_entry_mask] + params["tp_atr_mult"] * atr[long_entry_mask]

        # Short entries
        short_entry_mask = signals == -1.0
        if np.any(short_entry_mask):
            df.loc[short_entry_mask, "bb_stop_short"] = close[short_entry_mask] + params["stop_atr_mult"] * atr[short_entry_mask]
            df.loc[short_entry_mask, "bb_tp_short"] = close[short_entry_mask] - params["tp_atr_mult"] * atr[short_entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
