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

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Define entry conditions
        # Long entry: close crosses above upper donchian band, rsi > 50, volume oscillator positive
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        close_above_upper = (close > indicators['donchian']['upper']) & (prev_close <= np.roll(indicators['donchian']['upper'], 1))

        rsi_long_condition = rsi > params["rsi_overbought"]
        volume_long_condition = volume_oscillator > 0

        long_entry = close_above_upper & rsi_long_condition & volume_long_condition

        # Short entry: close crosses below lower donchian band, rsi < 50, volume oscillator negative
        close_below_lower = (close < indicators['donchian']['lower']) & (prev_close >= np.roll(indicators['donchian']['lower'], 1))

        rsi_short_condition = rsi < params["rsi_oversold"]
        volume_short_condition = volume_oscillator < 0

        short_entry = close_below_lower & rsi_short_condition & volume_short_condition

        # Exit conditions
        # Long exit: close below lower donchian band or rsi < 50
        rsi_exit_long = rsi < params["rsi_oversold"]
        exit_long = (close < indicators['donchian']['lower']) | rsi_exit_long

        # Short exit: close above upper donchian band or rsi > 50
        rsi_exit_short = rsi > params["rsi_overbought"]
        exit_short = (close > indicators['donchian']['upper']) | rsi_exit_short

        # Set long and short masks
        long_mask = long_entry
        short_mask = short_entry

        # Handle exits for existing positions
        # For longs, check if exit condition occurs after entry
        prev_long_mask = np.roll(long_mask, 1)
        prev_long_mask[0] = False
        prev_exit_long = np.roll(exit_long, 1)
        prev_exit_long[0] = False

        # Exit longs that are no longer valid
        exit_long_mask = (long_mask == False) & (prev_long_mask == True) & (exit_long == True)

        # For shorts, check if exit condition occurs after entry
        prev_short_mask = np.roll(short_mask, 1)
        prev_short_mask[0] = False
        prev_exit_short = np.roll(exit_short, 1)
        prev_exit_short[0] = False

        # Exit shorts that are no longer valid
        exit_short_mask = (short_mask == False) & (prev_short_mask == True) & (exit_short == True)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Write SL/TP levels into DataFrame
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long_mask = (signals == 1.0)
        entry_short_mask = (signals == -1.0)

        if entry_long_mask.any():
            df.loc[entry_long_mask, "bb_stop_long"] = close[entry_long_mask] - params["stop_atr_mult"] * atr[entry_long_mask]
            df.loc[entry_long_mask, "bb_tp_long"] = close[entry_long_mask] + params["tp_atr_mult"] * atr[entry_long_mask]

        if entry_short_mask.any():
            df.loc[entry_short_mask, "bb_stop_short"] = close[entry_short_mask] + params["stop_atr_mult"] * atr[entry_short_mask]
            df.loc[entry_short_mask, "bb_tp_short"] = close[entry_short_mask] - params["tp_atr_mult"] * atr[entry_short_mask]
        signals.iloc[:warmup] = 0.0
        return signals
