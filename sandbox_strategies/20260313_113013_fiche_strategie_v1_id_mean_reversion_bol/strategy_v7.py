from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr', 'adx']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 80,
         'rsi_oversold': 20,
         'rsi_period': 17,
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
                default=17,
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
        bb = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])

        # Get price arrays
        close = df["close"].values
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])

        # Entry conditions with ADX trend filter
        rsi_overbought = params.get("rsi_overbought", 80)
        rsi_oversold = params.get("rsi_oversold", 20)
        adx_threshold = 25

        long_condition = (close < indicators['bollinger']['lower']) & (rsi < rsi_oversold) & (adx > adx_threshold)
        short_condition = (close > indicators['bollinger']['upper']) & (rsi > rsi_overbought) & (adx > adx_threshold)

        long_mask = long_condition
        short_mask = short_condition

        # Exit conditions
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan

        cross_up_bb = (close > indicators['bollinger']['middle']) & (prev_close <= prev_bb_middle)
        cross_down_bb = (close < indicators['bollinger']['middle']) & (prev_close >= prev_bb_middle)
        cross_any_bb = cross_up_bb | cross_down_bb

        # RSI exit condition
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        cross_up_rsi = (rsi > 50) & (prev_rsi <= 50)
        cross_down_rsi = (rsi < 50) & (prev_rsi >= 50)
        cross_any_rsi = cross_up_rsi | cross_down_rsi

        # ADX exit condition
        adx_exit = adx < adx_threshold

        # Exit mask
        exit_mask = cross_any_bb | cross_any_rsi | adx_exit

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Handle exit signals
        exit_long_mask = long_mask & exit_mask
        exit_short_mask = short_mask & exit_mask

        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Set ATR-based stop-loss and take-profit levels
        stop_atr_mult = params.get("stop_atr_mult", 1.75)
        tp_atr_mult = params.get("tp_atr_mult", 3.5)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
        df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
        df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
