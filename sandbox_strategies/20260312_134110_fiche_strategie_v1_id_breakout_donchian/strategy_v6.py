from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='donchian_adx_rsi_breakout')

    @property
    def required_indicators(self) -> List[str]:
        return ['donchian', 'adx', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 70,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 2.75,
         'tp_atr_mult': 4.0,
         'warmup': 30}

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
                default=2.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=6.0,
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

        # Wrap indicator arrays
        close = df["close"].values
        atr = np.nan_to_num(indicators['atr'])
        rsi = np.nan_to_num(indicators['rsi'])
        adx_val = np.nan_to_num(indicators['adx']["adx"])
        dc = indicators['donchian']
        indicators['donchian']['upper'] = np.nan_to_num(dc["upper"])
        indicators['donchian']['middle'] = np.nan_to_num(dc["middle"])
        indicators['donchian']['lower'] = np.nan_to_num(dc["lower"])

        # Helper cross_any
        def cross_any(x: np.ndarray, y: np.ndarray) -> np.ndarray:
            prev_x = np.roll(x, 1)
            prev_y = np.roll(y, 1)
            prev_x[0] = np.nan
            prev_y[0] = np.nan
            return ((x > y) & (prev_x <= prev_y)) | ((x < y) & (prev_x >= prev_y))

        # Entry conditions
        long_mask = (
            (close > indicators['donchian']['upper'])
            & (adx_val > 35.0)
            & (rsi > params["rsi_overbought"])
        )
        short_mask = (
            (close < indicators['donchian']['lower'])
            & (adx_val > 35.0)
            & (rsi < params["rsi_oversold"])
        )

        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Exit conditions
        rsi_cross_50 = cross_any(rsi, np.full_like(rsi, 50.0))
        close_cross_mid = cross_any(close, indicators['donchian']['middle'])
        exit_mask = close_cross_mid | (adx_val < 25.0) | rsi_cross_50
        signals[exit_mask] = 0.0

        # Warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_mask = signals == 1.0
        df.loc[entry_mask, "bb_stop_long"] = close[entry_mask] - params["stop_atr_mult"] * atr[entry_mask]
        df.loc[entry_mask, "bb_tp_long"] = close[entry_mask] + params["tp_atr_mult"] * atr[entry_mask]

        short_entry_mask = signals == -1.0
        df.loc[short_entry_mask, "bb_stop_short"] = close[short_entry_mask] + params["stop_atr_mult"] * atr[short_entry_mask]
        df.loc[short_entry_mask, "bb_tp_short"] = close[short_entry_mask] - params["tp_atr_mult"] * atr[short_entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
