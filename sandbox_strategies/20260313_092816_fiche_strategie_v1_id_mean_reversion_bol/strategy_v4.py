from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='mean_reversion_bollinger_rsi')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 60,
         'rsi_oversold': 35,
         'rsi_period': 12,
         'stop_atr_mult': 1.75,
         'tp_atr_mult': 3.5,
         'warmup': 50}

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            'rsi_period': ParameterSpec(
                name='rsi_period',
                min_val=5,
                max_val=50,
                default=12,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=1.75,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=2.0,
                max_val=4.5,
                default=3.5,
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
        bb = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # Entry conditions
        lower_band = np.nan_to_num(bb["lower"])
        upper_band = np.nan_to_num(bb["upper"])
        middle_band = np.nan_to_num(bb["middle"])

        # Long entry: close < lower band and RSI < oversold
        long_entry = (close < lower_band) & (rsi < params["rsi_oversold"])
        long_mask = long_entry

        # Short entry: close > upper band and RSI > overbought
        short_entry = (close > upper_band) & (rsi > params["rsi_overbought"])
        short_mask = short_entry

        # Exit conditions: cross middle band or cross 50 RSI
        prev_close = np.roll(close, 1)
        prev_middle = np.roll(middle_band, 1)
        prev_rsi = np.roll(rsi, 1)

        prev_close[0] = np.nan
        prev_middle[0] = np.nan
        prev_rsi[0] = np.nan

        cross_middle_up = (close > middle_band) & (prev_close <= prev_middle)
        cross_middle_down = (close < middle_band) & (prev_close >= prev_middle)
        cross_rsi_50 = (rsi < 50) & (prev_rsi >= 50) | (rsi > 50) & (prev_rsi <= 50)

        exit_condition = cross_middle_up | cross_middle_down | cross_rsi_50

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set ATR-based SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long SL/TP
        entry_long = signals == 1.0
        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]

        # Short SL/TP
        entry_short = signals == -1.0
        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]

        # Warmup protection
        signals.iloc[:warmup] = 0.0
        signals.iloc[:warmup] = 0.0
        return signals
