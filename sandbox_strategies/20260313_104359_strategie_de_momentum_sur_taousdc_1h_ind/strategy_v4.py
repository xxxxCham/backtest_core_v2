from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_trend_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'momentum', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=3.0,
                default=1.5,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=5.0,
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
        macd_d = indicators['macd']
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        signal_line = np.nan_to_num(macd_d["signal"])
        histogram = np.nan_to_num(macd_d["histogram"])

        momentum = np.nan_to_num(indicators['momentum'])
        atr = np.nan_to_num(indicators['atr'])

        # Compute crossovers
        prev_macd = np.roll(indicators['macd']['macd'], 1)
        prev_signal = np.roll(signal_line, 1)
        prev_macd[0] = np.nan
        prev_signal[0] = np.nan

        cross_up = (indicators['macd']['macd'] > signal_line) & (prev_macd <= prev_signal)
        cross_down = (indicators['macd']['macd'] < signal_line) & (prev_macd >= prev_signal)

        # Entry conditions
        long_mask = cross_up & (momentum > 0)
        short_mask = cross_down & (momentum < 0)

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        close = df["close"].values
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        long_entry_mask = (signals == 1.0)
        df.loc[long_entry_mask, "bb_stop_long"] = close[long_entry_mask] - stop_atr_mult * atr[long_entry_mask]
        df.loc[long_entry_mask, "bb_tp_long"] = close[long_entry_mask] + tp_atr_mult * atr[long_entry_mask]

        # Short entries
        short_entry_mask = (signals == -1.0)
        df.loc[short_entry_mask, "bb_stop_short"] = close[short_entry_mask] + stop_atr_mult * atr[short_entry_mask]
        df.loc[short_entry_mask, "bb_tp_short"] = close[short_entry_mask] - tp_atr_mult * atr[short_entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
