from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='builder_strategy')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'leverage': ParameterSpec(
                name='leverage',
                min_val=1,
                max_val=2,
                default=1,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=2.0,
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

        # Warmup period
        signals.iloc[:warmup] = 0.0

        # Get indicators
        rsi = np.nan_to_num(indicators['rsi'])
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # RSI-based signals
        rsi_oversold = params.get("rsi_oversold", 30)
        rsi_overbought = params.get("rsi_overbought", 70)

        # Create masks for oversold and overbought conditions
        oversold_mask = rsi <= rsi_oversold
        overbought_mask = rsi >= rsi_overbought

        # Trend filter using EMA
        trend_mask_long = ema > np.roll(ema, 1)
        trend_mask_short = ema < np.roll(ema, 1)

        # Combine signals with trend filter
        long_mask = oversold_mask & trend_mask_long
        short_mask = overbought_mask & trend_mask_short

        # Apply warmup protection
        long_mask[:warmup] = False
        short_mask[:warmup] = False

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Calculate and set stop levels using ATR
        stop_multiple = params.get("atr_multiple", 2.0)
        entry_mask = (signals == 1.0) | (signals == -1.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # For long entries
        if np.any(entry_mask):
            df.loc[entry_mask, "bb_stop_long"] = close[entry_mask] - stop_multiple * atr[entry_mask]
            df.loc[entry_mask, "bb_tp_long"] = close[entry_mask] + stop_multiple * atr[entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
