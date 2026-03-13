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
        return {'adx_period': 24,
         'donchian_period': 45,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 4.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'donchian_period': ParameterSpec(
                name='donchian_period',
                min_val=20,
                max_val=90,
                default=45,
                param_type='int',
                step=1,
            ),
            'adx_period': ParameterSpec(
                name='adx_period',
                min_val=10,
                max_val=50,
                default=24,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=5.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=8.0,
                default=4.0,
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

        # Get arrays with proper shape
        close = np.nan_to_num(df["close"].values)
        indicators['donchian']['upper'] = np.nan_to_num(indicators['donchian']["upper"])
        indicators['donchian']['lower'] = np.nan_to_num(indicators['donchian']["lower"])
        indicators['donchian']['middle'] = np.nan_to_num(indicators['donchian']["middle"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])

        # Volatility filter
        atr_mean = np.nanmean(atr)
        vol_filter = atr > atr_mean

        # Entry conditions
        long_condition = (close > indicators['donchian']['upper']) & (adx_val > 30) & vol_filter
        short_condition = (close < indicators['donchian']['lower']) & (adx_val > 30) & vol_filter

        # Set masks
        long_mask = long_condition
        short_mask = short_condition

        # Exit conditions
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_middle = np.roll(indicators['donchian']['middle'], 1)
        prev_middle[0] = np.nan

        cross_down = (close < indicators['donchian']['middle']) & (prev_close >= prev_middle)
        adx_exit = adx_val < 25

        # Exit mask
        exit_mask = cross_down | adx_exit

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set warmup
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 4.0)

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = (signals == 1.0)
        entry_short = (signals == -1.0)

        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
