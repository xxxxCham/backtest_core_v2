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

        # Extract indicators
        rsi = np.nan_to_num(indicators['rsi'])
        donchian = indicators['donchian']
        indicators['donchian']['upper'] = np.nan_to_num(indicators['donchian']["upper"])
        indicators['donchian']['lower'] = np.nan_to_num(indicators['donchian']["lower"])
        volume_oscillator = np.nan_to_num(indicators['volume_oscillator'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Entry conditions
        # Long entry: close crosses above upper Donchian band, RSI > 50, volume oscillator positive, ATR > 0.001
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        close_crossed_above_upper = (close > indicators['donchian']['upper']) & (prev_close <= indicators['donchian']['upper'])
        rsi_long_condition = rsi > 50
        volume_long_condition = volume_oscillator > 0
        atr_condition = atr > 0.001

        long_mask = close_crossed_above_upper & rsi_long_condition & volume_long_condition & atr_condition

        # Short entry: close crosses below lower Donchian band, RSI < 50, volume oscillator negative, ATR > 0.001
        close_crossed_below_lower = (close < indicators['donchian']['lower']) & (prev_close >= indicators['donchian']['lower'])
        rsi_short_condition = rsi < 50
        volume_short_condition = volume_oscillator < 0

        short_mask = close_crossed_below_lower & rsi_short_condition & volume_short_condition & atr_condition

        # Exit conditions
        # Exit long: close crosses below lower Donchian band OR RSI crosses below 30
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        rsi_crossed_below_30 = (rsi < 30) & (prev_rsi >= 30)
        exit_long = close_crossed_below_lower | rsi_crossed_below_30
        signals[exit_long & (signals != -1.0)] = 0.0  # Close long positions

        # Exit short: close crosses above upper Donchian band OR RSI crosses above 70
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        rsi_crossed_above_70 = (rsi > 70) & (prev_rsi <= 70)
        exit_short = close_crossed_above_upper | rsi_crossed_above_70
        signals[exit_short & (signals != 1.0)] = 0.0  # Close short positions

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Warmup
        signals.iloc[:warmup] = 0.0

        # Risk management
        stop_atr_mult = float(params.get("stop_atr_mult", 1.5))
        tp_atr_mult = float(params.get("tp_atr_mult", 3.0))

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - stop_atr_mult * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + tp_atr_mult * atr[entry_long_mask]

        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + stop_atr_mult * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - tp_atr_mult * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
