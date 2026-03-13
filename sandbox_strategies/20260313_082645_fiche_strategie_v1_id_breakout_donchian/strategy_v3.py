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
        return ['donchian', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1, 'stop_atr_mult': 1.75, 'tp_atr_mult': 2.0, 'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=3.0,
                default=1.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.5,
                max_val=4.0,
                default=2.0,
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
        donchian = indicators['donchian']
        adx = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        close = np.nan_to_num(df["close"].values)
        indicators['donchian']['upper'] = np.nan_to_num(indicators['donchian']["upper"])
        indicators['donchian']['lower'] = np.nan_to_num(indicators['donchian']["lower"])
        indicators['donchian']['middle'] = np.nan_to_num(indicators['donchian']["middle"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])

        # Entry conditions
        # Long entry: close crosses above indicators['donchian']['upper'] AND indicators['adx']['adx'] > 30
        prev_close = np.roll(close, 1)
        prev_donchian_upper = np.roll(indicators['donchian']['upper'], 1)
        prev_close[0] = np.nan
        prev_donchian_upper[0] = np.nan
        cross_above = (close > indicators['donchian']['upper']) & (prev_close <= prev_donchian_upper)
        long_entry = cross_above & (adx_val > 30)

        # Short entry: close crosses below indicators['donchian']['lower'] AND indicators['adx']['adx'] > 30
        prev_donchian_lower = np.roll(indicators['donchian']['lower'], 1)
        prev_donchian_lower[0] = np.nan
        cross_below = (close < indicators['donchian']['lower']) & (prev_close >= prev_donchian_lower)
        short_entry = cross_below & (adx_val > 30)

        long_mask = long_entry
        short_mask = short_entry

        # Exit conditions
        # Exit long: cross below indicators['donchian']['middle'] OR indicators['adx']['adx'] < 25
        prev_donchian_middle = np.roll(indicators['donchian']['middle'], 1)
        prev_donchian_middle[0] = np.nan
        cross_below_middle = (close < indicators['donchian']['middle']) & (prev_close >= prev_donchian_middle)
        exit_long = cross_below_middle | (adx_val < 25)

        # Exit short: cross above indicators['donchian']['middle'] OR indicators['adx']['adx'] < 25
        cross_above_middle = (close > indicators['donchian']['middle']) & (prev_close <= prev_donchian_middle)
        exit_short = cross_above_middle | (adx_val < 25)

        # Apply exit masks
        long_exit_mask = np.zeros(n, dtype=bool)
        short_exit_mask = np.zeros(n, dtype=bool)
        long_exit_mask[long_mask] = exit_long[long_mask]
        short_exit_mask[short_mask] = exit_short[short_mask]

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[long_exit_mask] = 0.0
        signals[short_exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP levels
        stop_atr_mult = params.get("stop_atr_mult", 1.75)
        tp_atr_mult = params.get("tp_atr_mult", 2.0)

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
