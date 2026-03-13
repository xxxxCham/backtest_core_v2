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
        return {'adx_threshold': 30,
         'leverage': 1,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 3.0,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'adx_threshold': ParameterSpec(
                name='adx_threshold',
                min_val=15,
                max_val=40,
                default=30,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=1.0,
                max_val=4.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
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
        donchian = indicators['donchian']
        adx = indicators['adx']
        atr = np.nan_to_num(indicators['atr'])

        close = df["close"].values
        indicators['donchian']['upper'] = np.nan_to_num(indicators['donchian']["upper"])
        indicators['donchian']['lower'] = np.nan_to_num(indicators['donchian']["lower"])
        indicators['donchian']['middle'] = np.nan_to_num(indicators['donchian']["middle"])
        adx_val = np.nan_to_num(indicators['adx']["adx"])

        # Entry conditions
        adx_threshold = params.get("adx_threshold", 30)
        long_condition = (close > indicators['donchian']['upper']) & (adx_val > adx_threshold)
        short_condition = (close < indicators['donchian']['lower']) & (adx_val > adx_threshold)

        # Volatility filter
        atr_prev = np.roll(atr, 1)
        atr_prev[0] = np.nan
        volatility_condition = atr > atr_prev

        long_mask = long_condition & volatility_condition
        short_mask = short_condition & volatility_condition

        # Exit conditions
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_middle = np.roll(indicators['donchian']['middle'], 1)
        prev_middle[0] = np.nan

        exit_long = (close < indicators['donchian']['middle']) | (adx_val < 25)
        exit_short = (close > indicators['donchian']['middle']) | (adx_val < 25)

        # Apply exits
        exit_mask_long = long_mask & exit_long
        exit_mask_short = short_mask & exit_short

        # Set signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask_long] = 0.0
        signals[exit_mask_short] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 3.0)

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
