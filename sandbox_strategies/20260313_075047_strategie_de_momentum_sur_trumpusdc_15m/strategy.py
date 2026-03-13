from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trumpusdc_momentum_with_trend_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.5, 'tp_atr_mult': 3.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
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
        # warmup protection
        signals.iloc[:warmup] = 0.0

        # Extract indicators
        macd_d = indicators['macd']
        macd_hist = np.nan_to_num(macd_d["histogram"])
        atr = np.nan_to_num(indicators['atr'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])

        # Compute previous values for crossovers
        prev_macd_hist = np.roll(macd_hist, 1)
        prev_macd_hist[0] = np.nan

        # Long entry: MACD histogram positive and crossing up, ADX > 25
        long_signal = (macd_hist > 0) & (prev_macd_hist <= 0)
        trend_filter_long = adx > 25
        long_mask = long_signal & trend_filter_long

        # Short entry: MACD histogram negative and crossing down, ADX > 25
        short_signal = (macd_hist < 0) & (prev_macd_hist >= 0)
        trend_filter_short = adx > 25
        short_mask = short_signal & trend_filter_short

        # Exit conditions
        exit_long = (macd_hist < 0) & (prev_macd_hist >= 0)
        exit_short = (macd_hist > 0) & (prev_macd_hist <= 0)
        trend_weak = adx < 20

        # Apply exit conditions
        exit_mask_long = exit_long | trend_weak
        exit_mask_short = exit_short | trend_weak

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exits
        signals[exit_mask_long] = 0.0
        signals[exit_mask_short] = 0.0

        # ATR-based SL/TP
        close = df["close"].values
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        entry_long_mask = (signals == 1.0)
        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        # Short entries
        entry_short_mask = (signals == -1.0)
        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
