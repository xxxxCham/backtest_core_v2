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
        return ['rsi', 'bollinger', 'atr', 'adx']

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
        rsi = np.nan_to_num(indicators['rsi'])
        bb = indicators['bollinger']
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        atr = np.nan_to_num(indicators['atr'])
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])
        adx_plus = np.nan_to_num(adx_d["plus_di"])
        adx_minus = np.nan_to_num(adx_d["minus_di"])

        # Entry conditions
        rsi_overbought = params["rsi_overbought"]
        rsi_oversold = params["rsi_oversold"]
        stop_atr_mult = params["stop_atr_mult"]
        tp_atr_mult = params["tp_atr_mult"]

        # Long entry: close < lower bb, rsi < oversold, adx > 25
        long_condition = (df["close"].values < indicators['bollinger']['lower']) & (rsi < rsi_oversold) & (adx > 25)
        long_mask = long_condition

        # Short entry: close > upper bb, rsi > overbought, adx > 25
        short_condition = (df["close"].values > indicators['bollinger']['upper']) & (rsi > rsi_overbought) & (adx > 25)
        short_mask = short_condition

        # Exit conditions
        close = df["close"].values
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_bb_middle = np.roll(indicators['bollinger']['middle'], 1)
        prev_bb_middle[0] = np.nan

        # Exit on cross of close with middle bollinger band
        cross_up_bb = (close > indicators['bollinger']['middle']) & (prev_close <= prev_bb_middle)
        cross_down_bb = (close < indicators['bollinger']['middle']) & (prev_close >= prev_bb_middle)
        cross_any_bb = cross_up_bb | cross_down_bb

        # Exit on cross of rsi with 50
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        cross_up_rsi = (rsi > 50) & (prev_rsi <= 50)
        cross_down_rsi = (rsi < 50) & (prev_rsi >= 50)
        cross_any_rsi = cross_up_rsi | cross_down_rsi

        # Exit on adx < 20
        adx_condition = adx < 20

        # Combine exit conditions
        exit_condition = cross_any_bb | cross_any_rsi | adx_condition

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set warmup
        signals.iloc[:warmup] = 0.0

        # Set ATR-based SL/TP
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        entry_long = signals == 1.0
        entry_short = signals == -1.0

        if entry_long.any():
            df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
            df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        if entry_short.any():
            df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
            df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
