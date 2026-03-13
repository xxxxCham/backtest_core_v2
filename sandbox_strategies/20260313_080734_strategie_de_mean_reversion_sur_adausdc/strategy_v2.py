from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_adacusdc')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'bollinger', 'adx', 'atr']

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

        # Extract indicators
        rsi = np.nan_to_num(indicators['rsi'])
        bb = indicators['bollinger']
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Warmup
        signals.iloc[:warmup] = 0.0

        # Entry conditions
        # Short entry: ADX < 20 and RSI > 70
        short_condition = (adx < 20) & (rsi > params["rsi_overbought"])

        # Long entry: ADX < 20 and RSI < 30
        long_condition = (adx < 20) & (rsi < params["rsi_oversold"])

        # Exit conditions: price crosses middle band or ADX > 20
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan
        cross_middle_long = (close > indicators['bollinger']['middle']) & (prev_bb_middle <= indicators['bollinger']['middle'])
        cross_middle_short = (close < indicators['bollinger']['middle']) & (prev_bb_middle >= indicators['bollinger']['middle'])

        # Trend reversal (ADX > 20)
        trend_reversal_long = (adx > 20) & (prev_bb_middle <= indicators['bollinger']['middle'])
        trend_reversal_short = (adx > 20) & (prev_bb_middle >= indicators['bollinger']['middle'])

        # Set entry masks
        short_mask = short_condition & ~trend_reversal_short
        long_mask = long_condition & ~trend_reversal_long

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # ATR-based SL/TP
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        # Initialize SL/TP columns
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
