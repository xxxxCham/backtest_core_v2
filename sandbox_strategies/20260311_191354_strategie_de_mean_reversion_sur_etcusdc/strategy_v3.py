from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='etcutc_mean_reversion_v3')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 1.0,
         'tp_atr_mult': 2.0,
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
                default=1.0,
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
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=4.5,
                default=2.0,
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
        def generate_signals(
                self,
                df: pd.DataFrame,
                indicators: Dict[str, Any],
                params: Dict[str, Any],
            ) -> pd.Series:
                signals = pd.Series(0.0, index=df.index, dtype=np.float64)
                n = len(df)
                long_mask = np.zeros(n, dtype=bool)
                short_mask = np.zeros(n, dtype=bool)
                warmup = int(params.get("warmup", 50))
                signals.iloc[:warmup] = 0.0

                # Extract and sanitize indicators
                bollinger = indicators['bollinger']
                atr = np.nan_to_num(indicators['atr'])
                close = df["close"].values
                rsi = np.nan_to_num(indicators['rsi'])

                # Calculate offset for warmup
                offset = warmup

                # Entry conditions

                # Long entry: price above upper Bollinger + RSI above threshold
                upper = np.nan_to_num(indicators['bollinger']["upper"])
                lower = np.nan_to_num(indicators['bollinger']["lower"])

                long_entry = (
                    (close > upper) & 
                    (rsi > params["rsi_overbought"])
                )
                long_entry = np.roll(long_entry, offset)
                long_entry[:offset] = False
                long_mask = long_entry.astype(bool)

                # Short entry: price below lower Bollinger + RSI below threshold
                short_entry = (
                    (close < lower) & 
                    (rsi < params["rsi_oversold"])
                )
                short_entry = np.roll(short_entry, offset)
                short_entry[:offset] = False
                short_mask = short_entry.astype(bool)

                # Apply signals
                signals[long_mask] = 1.0
                signals[short_mask] = -1.0

                # Exit conditions
                exit_threshold = np.nan_to_num(indicators['bollinger']["upper"])
                exit_threshold = np.roll(exit_threshold, offset)
                exit_threshold[:offset] = np.nan

                cross_down = (
                    (close < exit_threshold) &
                    (np.roll(close, 1)[offset:] >= exit_threshold[offset:])
                )
                cross_down = np.zeros(n, dtype=bool)
                cross_down[offset:] = cross_down[offset:]

                cross_up = (
                    (close > exit_threshold) &
                    (np.roll(close, 1)[offset:] < exit_threshold[offset:])
                )
                cross_up = np.zeros(n, dtype=bool)
                cross_up[offset:] = cross_up[offset:]

                exit_mask = cross_down | cross_up
                signals[exit_mask] = 0.0

                # Risk management - SL/TP levels
                entry_mask_long = (signals == 1.0) & long_mask
                entry_mask_short = (signals == -1.0) & short_mask

                # Long positions
                if len(entry_mask_long) > 0:
                    entry_prices = close[entry_mask_long]
                    sl_prices = entry_prices - params["stop_atr_mult"] * atr[entry_mask_long]
                    tp_prices = entry_prices + params["tp_atr_mult"] * atr[entry_mask_long]

                    df.loc[entry_mask_long, "sl_level"] = sl_prices
                    df.loc[entry_mask_long, "tp_level"] = tp_prices

                # Short positions
                if len(entry_mask_short) > 0:
                    entry_prices = close[entry_mask_short]
                    sl_prices = entry_prices + params["stop_atr_mult"] * atr[entry_mask_short]
                    tp_prices = entry_prices - params["tp_atr_mult"] * atr[entry_mask_short]

                    df.loc[entry_mask_short, "sl_level"] = sl_prices
                    df.loc[entry_mask_short, "tp_level"] = tp_prices

                return signals
        signals.iloc[:warmup] = 0.0
        return signals
