from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='momentum_macd_revised')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'rsi', 'adx', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'leverage': 1,
         'rsi_overbought': 80,
         'rsi_oversold': 30,
         'rsi_period': 14,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 4.5,
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
                default=4.5,
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
        macd_d = indicators['macd']
        indicators['macd']['macd'] = np.nan_to_num(macd_d["macd"])
        indicators['macd']['signal'] = np.nan_to_num(macd_d["signal"])
        macd_hist = np.nan_to_num(macd_d["histogram"])

        rsi = np.nan_to_num(indicators['rsi'])
        adx_d = indicators['adx']
        adx_val = np.nan_to_num(adx_d["adx"])
        atr = np.nan_to_num(indicators['atr'])

        # Cross detection for MACD histogram
        prev_macd_hist = np.roll(macd_hist, 1)
        prev_macd_hist[0] = np.nan
        cross_up_hist = (macd_hist > 0) & (prev_macd_hist <= 0)
        cross_down_hist = (macd_hist < 0) & (prev_macd_hist >= 0)

        # Entry conditions
        # Long entry: histogram > 0, crosses above 0, RSI < 70, ADX > 25
        long_condition = (macd_hist > 0) & cross_up_hist & (rsi < 70) & (adx_val > 25)
        long_mask = long_condition

        # Short entry: histogram < 0, crosses below 0, RSI > 30, ADX > 25
        short_condition = (macd_hist < 0) & cross_down_hist & (rsi > 30) & (adx_val > 25)
        short_mask = short_condition

        # Exit conditions
        # Exit on histogram crossing 0, or RSI overbought/oversold
        exit_condition_long = cross_down_hist | (rsi > params["rsi_overbought"]) | (rsi < params["rsi_oversold"])
        exit_condition_short = cross_up_hist | (rsi > params["rsi_overbought"]) | (rsi < params["rsi_oversold"])

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set warmup period
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        close = df["close"].values
        entry_long = signals == 1.0
        entry_short = signals == -1.0

        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - params["stop_atr_mult"] * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + params["tp_atr_mult"] * atr[entry_long]

        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + params["stop_atr_mult"] * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - params["tp_atr_mult"] * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
