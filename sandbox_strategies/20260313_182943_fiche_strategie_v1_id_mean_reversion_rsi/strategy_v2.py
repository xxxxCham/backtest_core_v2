from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_rsi_bollinger_atr')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'bollinger', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'bollinger_period': 20,
         'bollinger_std_dev': 2,
         'leverage': 1,
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
            'bollinger_period': ParameterSpec(
                name='bollinger_period',
                min_val=5,
                max_val=50,
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
            'atr_period': ParameterSpec(
                name='atr_period',
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
                min_val=1.0,
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

        # Extract indicator arrays with nan handling
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        bb = indicators['bollinger']
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        close = df["close"].values

        # ATR previous comparison
        atr_prev = np.roll(atr, 1)
        atr_prev[0] = np.nan
        atr_gt_prev = atr > atr_prev

        # Long entry conditions
        long_mask = (rsi < 30) & (close < indicators['bollinger']['lower']) & atr_gt_prev

        # Short entry conditions
        short_mask = (rsi > 70) & (close > indicators['bollinger']['upper']) & atr_gt_prev

        # Apply entry signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions: cross any of close and middle Bollinger band
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        cross_up = (close > indicators['bollinger']['middle']) & (prev_close <= indicators['bollinger']['middle'])
        cross_down = (close < indicators['bollinger']['middle']) & (prev_close >= indicators['bollinger']['middle'])
        exit_mask = cross_up | cross_down
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Prepare SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # ATR-based SL/TP for long entries
        long_entries = signals == 1.0
        df.loc[long_entries, "bb_stop_long"] = close[long_entries] - params["stop_atr_mult"] * atr[long_entries]
        df.loc[long_entries, "bb_tp_long"] = close[long_entries] + params["tp_atr_mult"] * atr[long_entries]

        # ATR-based SL/TP for short entries
        short_entries = signals == -1.0
        df.loc[short_entries, "bb_stop_short"] = close[short_entries] + params["stop_atr_mult"] * atr[short_entries]
        df.loc[short_entries, "bb_tp_short"] = close[short_entries] - params["tp_atr_mult"] * atr[short_entries]
        signals.iloc[:warmup] = 0.0
        return signals
