from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_macd_breakout_with_atr_risk')

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
        indicators['donchian']['upper'] = np.nan_to_num(dc["upper"])
        indicators['donchian']['lower'] = np.nan_to_num(dc["lower"])
        indicators['donchian']['middle'] = np.nan_to_num(dc["middle"])

        macd_d = indicators['macd']
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        indicators['macd']['signal'] = np.nan_to_num(macd_d["signal"])

        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # Entry conditions
        # Long entry: close crosses above indicators['donchian']['upper'] AND macd.macro > indicators['macd']['signal']
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_donchian_upper = np.roll(indicators['donchian']['upper'], 1)
        prev_donchian_upper[0] = np.nan

        cross_above = (close > indicators['donchian']['upper']) & (prev_close <= prev_donchian_upper)

        long_condition = (indicators['macd']['macd'] > indicators['macd']['signal'])
        long_mask = cross_above & long_condition

        # Short entry: close crosses below indicators['donchian']['lower'] AND macd.macro < indicators['macd']['signal']
        prev_donchian_lower = np.roll(indicators['donchian']['lower'], 1)
        prev_donchian_lower[0] = np.nan
        cross_below = (close < indicators['donchian']['lower']) & (prev_close >= prev_donchian_lower)

        short_condition = (indicators['macd']['macd'] < indicators['macd']['signal'])
        short_mask = cross_below & short_condition

        # Exit conditions
        # Exit long: close crosses below indicators['donchian']['middle']
        prev_donchian_middle = np.roll(indicators['donchian']['middle'], 1)
        prev_donchian_middle[0] = np.nan
        exit_long = (close < indicators['donchian']['middle']) & (prev_close >= prev_donchian_middle)
        exit_long_mask = exit_long & (np.roll(signals, 1) == 1.0)

        # Exit short: close crosses above indicators['donchian']['middle']
        exit_short = (close > indicators['donchian']['middle']) & (prev_close <= prev_donchian_middle)
        exit_short_mask = exit_short & (np.roll(signals, 1) == -1.0)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # ATR-based risk management
        stop_atr_mult = params.get("stop_atr_mult", 1.5)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

        # Initialize SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        entry_long = (signals == 1.0)
        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        # Short entries
        entry_short = (signals == -1.0)
        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
