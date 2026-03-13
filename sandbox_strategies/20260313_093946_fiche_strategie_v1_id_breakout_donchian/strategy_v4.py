from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='breakout_donchian_adx_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 2.0,
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
                min_val=1.0,
                max_val=4.0,
                default=2.0,
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
        # implement explicit LONG / SHORT / FLAT logic
        # warmup protection
        signals.iloc[:warmup] = 0.0

        # Extract indicators
        donchian = indicators['donchian']
        rsi = np.nan_to_num(indicators['rsi'])
        adx = indicators['adx']
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        close = np.nan_to_num(df["close"].values)
        atr = np.nan_to_num(indicators['atr'])

        # Entry conditions
        indicators['donchian']['upper'] = np.nan_to_num(indicators['donchian']["upper"])
        indicators['donchian']['lower'] = np.nan_to_num(indicators['donchian']["lower"])
        indicators['donchian']['middle'] = np.nan_to_num(indicators['donchian']["middle"])

        # Long entry: close > indicators['donchian']['upper'] AND rsi > 50 AND adx > 30
        long_condition = (close > indicators['donchian']['upper']) & (rsi > 50) & (adx_val > 30)
        long_mask = long_condition

        # Short entry: close < indicators['donchian']['lower'] AND rsi < 50 AND adx > 30
        short_condition = (close < indicators['donchian']['lower']) & (rsi < 50) & (adx_val > 30)
        short_mask = short_condition

        # Exit conditions
        prev_dc_middle = np.roll(indicators['donchian']['middle'], 1)
        prev_dc_middle[0] = np.nan
        cross_down_middle = (close < indicators['donchian']['middle']) & (prev_dc_middle >= indicators['donchian']['middle'])

        # Exit if adx < 25
        exit_condition = (adx_val < 25)

        # Combine exit conditions
        exit_mask = cross_down_middle | exit_condition

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exit conditions
        # Exit long positions
        long_exit_mask = long_mask & exit_mask
        signals[long_exit_mask] = 0.0

        # Exit short positions
        short_exit_mask = short_mask & exit_mask
        signals[short_exit_mask] = 0.0

        # ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Compute SL/TP levels for long entries
        entry_long = (signals == 1.0)
        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]

        # Compute SL/TP levels for short entries
        entry_short = (signals == -1.0)
        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals