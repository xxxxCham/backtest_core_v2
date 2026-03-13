from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='trend_filter_mean_reversion')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 65,
         'rsi_oversold': 35,
         'rsi_period': 14,
         'stop_atr_mult': 1.75,
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
                min_val=0.5,
                max_val=4.0,
                default=1.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=5.0,
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
        close = df["close"].values
        bb = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        adx_d = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        # Bollinger Bands
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])

        # ADX
        adx = np.nan_to_num(adx_d["adx"])

        # Entry conditions
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]
        adx_threshold = 25

        # Long entry: close < lower band AND rsi < oversold AND adx > threshold
        long_entry_condition = (close < indicators['bollinger']['lower']) & (rsi < rsi_oversold) & (adx > adx_threshold)
        long_mask = long_entry_condition

        # Short entry: close > upper band AND rsi > overbought AND adx > threshold
        short_entry_condition = (close > indicators['bollinger']['upper']) & (rsi > rsi_overbought) & (adx > adx_threshold)
        short_mask = short_entry_condition

        # Exit conditions
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan

        cross_up_bb = (close > indicators['bollinger']['middle']) & (prev_close <= prev_bb_middle)
        cross_down_bb = (close < indicators['bollinger']['middle']) & (prev_close >= prev_bb_middle)
        cross_any_bb = cross_up_bb | cross_down_bb

        cross_up_rsi = (rsi > 50) & (prev_rsi <= 50)
        cross_down_rsi = (rsi < 50) & (prev_rsi >= 50)
        cross_any_rsi = cross_up_rsi | cross_down_rsi

        exit_condition = cross_any_bb | cross_any_rsi

        # Apply exit logic to existing positions
        # For simplicity, we assume no partial exits and flat the position on exit
        exit_mask = exit_condition

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP levels
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        long_entry_indices = np.where(long_mask)[0]
        for i in long_entry_indices:
            df.loc[df.index[i], "bb_stop_long"] = close[i] - stop_atr_mult * atr[i]
            df.loc[df.index[i], "bb_tp_long"] = close[i] + tp_atr_mult * atr[i]

        # Short entries
        short_entry_indices = np.where(short_mask)[0]
        for i in short_entry_indices:
            df.loc[df.index[i], "bb_stop_short"] = close[i] + stop_atr_mult * atr[i]
            df.loc[df.index[i], "bb_tp_short"] = close[i] - tp_atr_mult * atr[i]
        signals.iloc[:warmup] = 0.0
        return signals
