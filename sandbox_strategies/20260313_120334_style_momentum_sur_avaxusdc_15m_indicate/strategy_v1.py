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
        indicators['donchian']['middle'] = np.nan_to_num(indicators['donchian']["middle"])
        volume_oscillator = np.nan_to_num(indicators['volume_oscillator'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Volume oscillator moving average
        volume_ma = np.nan_to_num(pd.Series(volume_oscillator).rolling(20).mean().values)

        # RSI cross detection
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        rsi_cross_up = (rsi > 50) & (prev_rsi <= 50)
        rsi_cross_down = (rsi < 50) & (prev_rsi >= 50)

        # Close inside Donchian bands
        close_inside_bands = (close > indicators['donchian']['lower']) & (close < indicators['donchian']['upper'])

        # Volume oscillator spike
        volume_spike = volume_oscillator > volume_ma

        # Entry conditions
        long_entry = rsi_cross_up & close_inside_bands & volume_spike
        short_entry = rsi_cross_down & close_inside_bands & volume_spike

        long_mask = long_entry
        short_mask = short_entry

        # Exit conditions
        rsi_exit_long = rsi < 50
        rsi_exit_short = rsi > 50
        below_donchian_lower = close < indicators['donchian']['lower']
        above_donchian_upper = close > indicators['donchian']['upper']

        long_exit = rsi_exit_long | below_donchian_lower
        short_exit = rsi_exit_short | above_donchian_upper

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Apply exits
        exit_long_mask = np.zeros(n, dtype=bool)
        exit_short_mask = np.zeros(n, dtype=bool)
        prev_signal = np.roll(signals, 1)
        prev_signal[0] = 0.0

        exit_long_mask = (signals == 1.0) & (prev_signal == 1.0) & long_exit
        exit_short_mask = (signals == -1.0) & (prev_signal == -1.0) & short_exit

        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # ATR-based SL/TP levels
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

        # Warmup
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
