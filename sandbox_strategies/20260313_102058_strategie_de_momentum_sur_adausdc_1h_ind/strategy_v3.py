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
        return ['rsi', 'ema', 'atr', 'macd']

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

        # Extract and prepare indicators
        rsi = np.nan_to_num(indicators['rsi'])
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])
        macd_d = indicators['macd']
        macd_line = np.nan_to_num(macd_d["macd"])
        signal_line = np.nan_to_num(macd_d["signal"])
        histogram = np.nan_to_num(macd_d["histogram"])

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Short entry conditions
        # MACD below signal line
        macd_below_signal = (macd_line < signal_line)
        # Negative momentum (histogram decreasing)
        prev_histogram = np.roll(histogram, 1)
        prev_histogram[0] = np.nan
        momentum_negative = (histogram < prev_histogram)
        # RSI not overbought
        rsi_not_overbought = (rsi < 65)

        short_condition = macd_below_signal & momentum_negative & rsi_not_overbought

        short_mask = short_condition

        # Set signals
        signals[short_mask] = -1.0

        # Write SL/TP columns for short entries
        close = df["close"].values
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        short_entry_mask = (signals == -1.0)
        df.loc[short_entry_mask, "bb_stop_short"] = close[short_entry_mask] + stop_atr_mult * atr[short_entry_mask]
        df.loc[short_entry_mask, "bb_tp_short"] = close[short_entry_mask] - tp_atr_mult * atr[short_entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals