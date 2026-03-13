from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_with_bollinger_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr']

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

        # Extract indicators
        close = df["close"].values
        bb = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])

        # Bollinger bands
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])

        # RSI thresholds
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]

        # ATR multipliers
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        # Cross detection
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_bb_lower = np.roll(indicators['bollinger']['lower'], 1)
        prev_bb_lower[0] = np.nan
        prev_bb_upper = np.roll(indicators['bollinger']['upper'], 1)
        prev_bb_upper[0] = np.nan
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan

        # Entry conditions
        long_condition = (close < indicators['bollinger']['lower']) & (rsi < rsi_oversold)
        short_condition = (close > indicators['bollinger']['upper']) & (rsi > rsi_overbought)

        # Exit conditions
        exit_long = (close > indicators['bollinger']['middle']) | (rsi > 50)
        exit_short = (close < indicators['bollinger']['middle']) | (rsi < 50)

        # Apply signals
        long_mask = long_condition
        short_mask = short_condition

        # Exit signals
        exit_long_mask = exit_long
        exit_short_mask = exit_short

        # Handle crossover logic
        cross_down = (close < indicators['bollinger']['lower']) & (prev_close >= prev_bb_lower)
        cross_up = (close > indicators['bollinger']['upper']) & (prev_close <= prev_bb_upper)

        # Long entries
        long_entry_mask = cross_down & (rsi < rsi_oversold)
        # Short entries
        short_entry_mask = cross_up & (rsi > rsi_overbought)

        # Apply signals
        signals[long_entry_mask] = 1.0
        signals[short_entry_mask] = -1.0

        # Set SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long SL/TP
        entry_long = signals == 1.0
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        # Short SL/TP
        entry_short = signals == -1.0
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
