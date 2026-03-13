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
        return ['bollinger', 'rsi', 'atr', 'adx']

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
        bb = indicators['bollinger']
        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])

        # Entry conditions
        close = df["close"].values
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]

        # Long entry: close < lower bollinger AND rsi < oversold AND adx > 25
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])
        long_condition = (close < indicators['bollinger']['lower']) & (rsi < rsi_oversold) & (adx > 25)
        long_mask = long_condition

        # Short entry: close > upper bollinger AND rsi > overbought AND adx > 25
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        short_condition = (close > indicators['bollinger']['upper']) & (rsi > rsi_overbought) & (adx > 25)
        short_mask = short_condition

        # Exit conditions
        # Cross any of close with middle bollinger or cross any of rsi with 50
        prev_close = np.roll(close, 1)
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_close[0] = np.nan
        prev_bb_middle[0] = np.nan

        cross_up_middle = (close > indicators['bollinger']['middle']) & (prev_close <= prev_bb_middle)
        cross_down_middle = (close < indicators['bollinger']['middle']) & (prev_close >= prev_bb_middle)
        cross_middle = cross_up_middle | cross_down_middle

        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        cross_up_rsi = (rsi > 50) & (prev_rsi <= 50)
        cross_down_rsi = (rsi < 50) & (prev_rsi >= 50)
        cross_rsi = cross_up_rsi | cross_down_rsi

        exit_condition = cross_middle | cross_rsi

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set exit signals
        exit_long_mask = long_mask & exit_condition
        exit_short_mask = short_mask & exit_condition
        signals[exit_long_mask] = 0.0
        signals[exit_short_mask] = 0.0

        # Warmup
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

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
