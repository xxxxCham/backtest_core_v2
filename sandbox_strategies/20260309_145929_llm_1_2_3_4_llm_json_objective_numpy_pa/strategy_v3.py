from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='bollinger_rsi_adx_trend_filter')

    @property
    def required_indicators(self) -> List[str]:
        return ['bollinger', 'rsi', 'adx', 'atr']

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
        adx_d = indicators['adx']
        adx = np.nan_to_num(adx_d["adx"])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values
        open_ = df["open"].values

        # Prepare cross functions
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_rsi = np.roll(rsi, 1)
        prev_rsi[0] = np.nan
        prev_adx = np.roll(adx, 1)
        prev_adx[0] = np.nan

        # Entry conditions
        indicators['bollinger']['upper'] = np.nan_to_num(bb["upper"])
        indicators['bollinger']['lower'] = np.nan_to_num(bb["lower"])
        indicators['bollinger']['middle'] = np.nan_to_num(bb["middle"])

        # Long entry: close crosses above upper band, RSI < 70, ADX > 25
        long_entry_cross = (close > indicators['bollinger']['upper']) & (prev_close <= indicators['bollinger']['upper'])
        long_rsi_cond = rsi < params["rsi_overbought"]
        long_adx_cond = adx > 25

        long_mask = long_entry_cross & long_rsi_cond & long_adx_cond

        # Short entry: close crosses below lower band, RSI > 30, ADX > 25
        short_entry_cross = (close < indicators['bollinger']['lower']) & (prev_close >= indicators['bollinger']['lower'])
        short_rsi_cond = rsi > params["rsi_oversold"]
        short_adx_cond = adx > 25

        short_mask = short_entry_cross & short_rsi_cond & short_adx_cond

        # Exit conditions
        # Exit long: close crosses below middle band or ADX < 20
        exit_long = (close < indicators['bollinger']['middle']) | (prev_adx >= 20) & (adx < 20)
        # Exit short: close crosses above middle band or ADX < 20
        exit_short = (close > indicators['bollinger']['middle']) | (prev_adx >= 20) & (adx < 20)

        # Apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0

        # Set warmup period
        signals.iloc[:warmup] = 0.0

        # ATR-based SL/TP levels
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        # Long entries
        long_entry_mask = (signals == 1.0)
        if np.any(long_entry_mask):
            df.loc[long_entry_mask, "bb_stop_long"] = close[long_entry_mask] - params["stop_atr_mult"] * atr[long_entry_mask]
            df.loc[long_entry_mask, "bb_tp_long"] = close[long_entry_mask] + params["tp_atr_mult"] * atr[long_entry_mask]

        # Short entries
        short_entry_mask = (signals == -1.0)
        if np.any(short_entry_mask):
            df.loc[short_entry_mask, "bb_stop_short"] = close[short_entry_mask] + params["stop_atr_mult"] * atr[short_entry_mask]
            df.loc[short_entry_mask, "bb_tp_short"] = close[short_entry_mask] - params["tp_atr_mult"] * atr[short_entry_mask]
        signals.iloc[:warmup] = 0.0
        return signals
