from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='macd_rsi_entry')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
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
                default=16,
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
        macd = indicators['macd']
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Calculate MACD signals
        indicators['macd']['macd'] = indicators['macd']["macd"]
        signal_line = indicators['macd']["signal"]

        # Long signal: MACD crosses above signal and RSI >70
        cross_long = (indicators['macd']['macd'] > signal_line) & (rsi > 70)
        long_mask[cross_long] = True

        # Short signal: MACD crosses below signal and RSI <30
        cross_short = (indicators['macd']['macd'] < signal_line) & (rsi < 30)
        short_mask[cross_short] = True

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based stop and TP levels
        df["bb_stop_long"] = np.nan
        df["bb_tp_long"] = np.nan
        df["bb_stop_short"] = np.nan
        df["bb_tp_short"] = np.nan

        close = df["close"].values

        # Long entries
        entry_mask_long = (signals == 1.0)
        df.loc[entry_mask_long, "bb_stop_long"] = close[entry_mask_long] - params["stop_atr_mult"] * atr[entry_mask_long]
        df.loc[entry_mask_long, "bb_tp_long"] = close[entry_mask_long] + params["tp_atr_mult"] * atr[entry_mask_long]

        # Short entries
        entry_mask_short = (signals == -1.0)
        df.loc[entry_mask_short, "bb_stop_short"] = close[entry_mask_short] + params["stop_atr_mult"] * atr[entry_mask_short]
        df.loc[entry_mask_short, "bb_tp_short"] = close[entry_mask_short] - params["tp_atr_mult"] * atr[entry_mask_short]
        signals.iloc[:warmup] = 0.0
        return signals
