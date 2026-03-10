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
        # warmup protection
        signals.iloc[:warmup] = 0.0

        # Extract indicators
        close = df["close"].values
        dc = indicators['donchian']
        indicators['donchian']['upper'] = np.nan_to_num(dc["upper"])
        indicators['donchian']['lower'] = np.nan_to_num(dc["lower"])
        indicators['donchian']['middle'] = np.nan_to_num(dc["middle"])
        macd_d = indicators['macd']
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        indicators['macd']['signal'] = np.nan_to_num(macd_d["signal"])
        atr = np.nan_to_num(indicators['atr'])

        # Entry conditions
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_dc_upper = np.roll(indicators['donchian']['upper'], 1)
        prev_dc_upper[0] = np.nan
        prev_dc_lower = np.roll(indicators['donchian']['lower'], 1)
        prev_dc_lower[0] = np.nan

        # Long entry: close crosses above indicators['donchian']['upper'] AND indicators['macd']['macd'] > indicators['macd']['signal']
        long_entry_cross = (close > indicators['donchian']['upper']) & (prev_close <= prev_dc_upper)
        long_macd_conf = indicators['macd']['macd'] > indicators['macd']['signal']
        long_mask = long_entry_cross & long_macd_conf

        # Short entry: close crosses below indicators['donchian']['lower'] AND indicators['macd']['macd'] < indicators['macd']['signal']
        short_entry_cross = (close < indicators['donchian']['lower']) & (prev_close >= prev_dc_lower)
        short_macd_conf = indicators['macd']['macd'] < indicators['macd']['signal']
        short_mask = short_entry_cross & short_macd_conf

        # Exit conditions
        prev_dc_middle = np.roll(indicators['donchian']['middle'], 1)
        prev_dc_middle[0] = np.nan
        exit_long = (close < indicators['donchian']['middle']) & (prev_close >= prev_dc_middle)
        exit_short = (close > indicators['donchian']['middle']) & (prev_close <= prev_dc_middle)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set SL/TP levels for long entries
        entry_long = (signals == 1.0)
        if entry_long.any():
            df.loc[:, "bb_stop_long"] = np.nan
            df.loc[:, "bb_tp_long"] = np.nan
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]

        # Set SL/TP levels for short entries
        entry_short = (signals == -1.0)
        if entry_short.any():
            df.loc[:, "bb_stop_short"] = np.nan
            df.loc[:, "bb_tp_short"] = np.nan
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
