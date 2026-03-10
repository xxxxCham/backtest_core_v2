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
        donchian = indicators['donchian']
        indicators['donchian']['upper'] = np.nan_to_num(indicators['donchian']["upper"])
        indicators['donchian']['middle'] = np.nan_to_num(indicators['donchian']["middle"])
        indicators['donchian']['lower'] = np.nan_to_num(indicators['donchian']["lower"])

        macd_d = indicators['macd']
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        indicators['macd']['signal'] = np.nan_to_num(macd_d["signal"])

        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Compute previous values for crossovers
        prev_dc_upper = np.roll(indicators['donchian']['upper'], 1)
        prev_dc_lower = np.roll(indicators['donchian']['lower'], 1)
        prev_dc_middle = np.roll(indicators['donchian']['middle'], 1)
        prev_macd_line = np.roll(indicators['macd']['macd'], 1)
        prev_macd_signal = np.roll(indicators['macd']['signal'], 1)

        # Set first values to NaN to avoid false crossovers
        prev_dc_upper[0] = np.nan
        prev_dc_lower[0] = np.nan
        prev_dc_middle[0] = np.nan
        prev_macd_line[0] = np.nan
        prev_macd_signal[0] = np.nan

        # Entry conditions
        # Long entry: close crosses above indicators['donchian']['upper'] AND macd.macro > indicators['macd']['signal']
        long_entry_condition = (close > indicators['donchian']['upper']) & (prev_dc_upper <= indicators['donchian']['upper']) & (indicators['macd']['macd'] > indicators['macd']['signal']) & (prev_macd_line <= indicators['macd']['signal'])

        # Short entry: close crosses below indicators['donchian']['lower'] AND macd.macro < indicators['macd']['signal']
        short_entry_condition = (close < indicators['donchian']['lower']) & (prev_dc_lower >= indicators['donchian']['lower']) & (indicators['macd']['macd'] < indicators['macd']['signal']) & (prev_macd_line >= indicators['macd']['signal'])

        # Exit conditions
        # Exit long: close crosses below indicators['donchian']['middle']
        long_exit_condition = (close < indicators['donchian']['middle']) & (prev_dc_middle >= indicators['donchian']['middle'])

        # Exit short: close crosses above indicators['donchian']['middle']
        short_exit_condition = (close > indicators['donchian']['middle']) & (prev_dc_middle <= indicators['donchian']['middle'])

        # Set masks
        long_mask = long_entry_condition
        short_mask = short_entry_condition

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Handle exits
        # For existing long positions
        long_positions = signals == 1.0
        signals[long_exit_condition & long_positions] = 0.0

        # For existing short positions
        short_positions = signals == -1.0
        signals[short_exit_condition & short_positions] = 0.0

        # ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

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
