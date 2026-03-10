from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_macd_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'macd', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'donchian_period': 20,
         'leverage': 1,
         'stop_atr_mult': 1.5,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'donchian_period': ParameterSpec(
                name='donchian_period',
                min_val=10,
                max_val=50,
                default=20,
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
        dc = indicators['donchian']
        macd_d = indicators['macd']
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Donchian bands
        indicators['donchian']['upper'] = np.nan_to_num(dc["upper"])
        indicators['donchian']['middle'] = np.nan_to_num(dc["middle"])
        indicators['donchian']['lower'] = np.nan_to_num(dc["lower"])

        # MACD
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        indicators['macd']['signal'] = np.nan_to_num(macd_d["signal"])

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Cross helpers
        prev_dc_upper = np.roll(indicators['donchian']['upper'], 1)
        prev_dc_lower = np.roll(indicators['donchian']['lower'], 1)
        prev_dc_middle = np.roll(indicators['donchian']['middle'], 1)
        prev_dc_upper[0] = np.nan
        prev_dc_lower[0] = np.nan
        prev_dc_middle[0] = np.nan

        close_prev = np.roll(close, 1)
        close_prev[0] = np.nan

        # Entry conditions
        long_entry = (close > indicators['donchian']['upper']) & (indicators['macd']['macd'] > indicators['macd']['signal'])
        short_entry = (close < indicators['donchian']['lower']) & (indicators['macd']['macd'] < indicators['macd']['signal'])

        # Exit conditions
        long_exit = (close < indicators['donchian']['middle'])
        short_exit = (close > indicators['donchian']['middle'])

        # Cross detection
        cross_up_upper = (close > indicators['donchian']['upper']) & (close_prev <= prev_dc_upper)
        cross_down_lower = (close < indicators['donchian']['lower']) & (close_prev >= prev_dc_lower)
        cross_down_middle = (close < indicators['donchian']['middle']) & (close_prev >= prev_dc_middle)
        cross_up_middle = (close > indicators['donchian']['middle']) & (close_prev <= prev_dc_middle)

        # Long signals
        long_mask = cross_up_upper & (indicators['macd']['macd'] > indicators['macd']['signal'])
        signals[long_mask] = 1.0

        # Short signals
        short_mask = cross_down_lower & (indicators['macd']['macd'] < indicators['macd']['signal'])
        signals[short_mask] = -1.0

        # ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

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
        signals.iloc[:warmup] = 0.0
        return signals
