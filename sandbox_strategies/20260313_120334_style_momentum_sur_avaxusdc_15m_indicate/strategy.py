from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='style_momentum_avaxusdc_15m')

    @property
    def required_indicators(self) -> List[str]:
        return ['rsi', 'donchian', 'volume_oscillator', 'atr']

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
                min_val=1.0,
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

        # Extract and clean indicators
        rsi = np.nan_to_num(indicators['rsi'])
        volume_oscillator = np.nan_to_num(indicators['volume_oscillator'])
        atr = np.nan_to_num(indicators['atr'])
        donchian = indicators['donchian']
        indicators['donchian']['upper'] = np.nan_to_num(indicators['donchian']["upper"])
        indicators['donchian']['lower'] = np.nan_to_num(indicators['donchian']["lower"])
        close = df["close"].values

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Entry conditions
        # Long entry: close crosses above upper Donchian band, RSI > 50, volume oscillator > 0
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        cross_above_upper = (close > indicators['donchian']['upper']) & (prev_close <= indicators['donchian']['upper'])
        long_entry = cross_above_upper & (rsi > 50) & (volume_oscillator > 0)

        # Short entry: close crosses below lower Donchian band, RSI < 50, volume oscillator < 0
        cross_below_lower = (close < indicators['donchian']['lower']) & (prev_close >= indicators['donchian']['lower'])
        short_entry = cross_below_lower & (rsi < 50) & (volume_oscillator < 0)

        # Exit conditions
        # Exit long: close crosses below lower Donchian band OR RSI < 50
        exit_long = (close < indicators['donchian']['lower']) | (rsi < 50)
        # Exit short: close crosses above upper Donchian band OR RSI > 50
        exit_short = (close > indicators['donchian']['upper']) | (rsi > 50)

        # Apply signals
        long_mask = long_entry
        short_mask = short_entry

        # Set exit signals
        exit_long_mask = np.zeros(n, dtype=bool)
        exit_short_mask = np.zeros(n, dtype=bool)
        prev_exit_long = np.roll(exit_long, 1)
        prev_exit_long[0] = False
        prev_exit_short = np.roll(exit_short, 1)
        prev_exit_short[0] = False
        exit_long_mask = exit_long & ~prev_exit_long
        exit_short_mask = exit_short & ~prev_exit_short

        # Combine all masks
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Risk management - ATR-based SL/TP
        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = (signals == 1.0)
        entry_short = (signals == -1.0)

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
