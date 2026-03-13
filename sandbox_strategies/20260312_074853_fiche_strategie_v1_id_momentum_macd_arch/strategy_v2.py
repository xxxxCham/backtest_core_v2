from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name='macd_rsi_ema_trend')

    @property
    def required_indicators(self) -> List[str]:
        return ['macd', 'rsi', 'ema', 'atr']

    @property
    def default_params(self) -> Dict[str, Any]:
        return {'atr_period': 14,
         'ema_period': 50,
         'leverage': 1,
         'rsi_period': 14,
         'stop_atr_mult': 2.0,
         'tp_atr_mult': 2.0,
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
            'ema_period': ParameterSpec(
                name='ema_period',
                min_val=10,
                max_val=200,
                default=50,
                param_type='int',
                step=1,
            ),
            'atr_period': ParameterSpec(
                name='atr_period',
                min_val=5,
                max_val=30,
                default=14,
                param_type='int',
                step=1,
            ),
            'stop_atr_mult': ParameterSpec(
                name='stop_atr_mult',
                min_val=0.5,
                max_val=4.0,
                default=2.0,
                param_type='float',
                step=0.1,
            ),
            'tp_atr_mult': ParameterSpec(
                name='tp_atr_mult',
                min_val=1.0,
                max_val=5.0,
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

        # unwrap indicators
        close = df["close"].values
        rsi = np.nan_to_num(indicators['rsi'])
        ema = np.nan_to_num(indicators['ema'])
        atr = np.nan_to_num(indicators['atr'])

        macd_dict = indicators['macd']
        indicators['macd']['macd'] = np.nan_to_num(macd_dict["macd"])
        indicators['macd']['signal'] = np.nan_to_num(macd_dict["signal"])
        macd_hist = np.nan_to_num(macd_dict["histogram"])

        # cross helpers
        prev_macd_line = np.roll(indicators['macd']['macd'], 1)
        prev_macd_line[0] = np.nan
        prev_macd_signal = np.roll(indicators['macd']['signal'], 1)
        prev_macd_signal[0] = np.nan
        cross_up_macd = (indicators['macd']['macd'] > indicators['macd']['signal']) & (prev_macd_line <= prev_macd_signal)
        cross_down_macd = (indicators['macd']['macd'] < indicators['macd']['signal']) & (prev_macd_line >= prev_macd_signal)

        # long entry conditions
        long_mask = (
            cross_up_macd
            & (rsi > 30)
            & (rsi < 70)
            & (close > ema)
        )

        # short entry conditions
        short_mask = (
            cross_down_macd
            & (rsi > 30)
            & (rsi < 70)
            & (close < ema)
        )

        # exit conditions
        prev_hist = np.roll(macd_hist, 1)
        prev_hist[0] = np.nan
        cross_up_hist = (macd_hist > 0) & (prev_hist <= 0)
        cross_down_hist = (macd_hist < 0) & (prev_hist >= 0)
        exit_hist_cross = cross_up_hist | cross_down_hist

        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        cross_up_close = (close > ema) & (prev_close <= ema)
        cross_down_close = (close < ema) & (prev_close >= ema)
        exit_close_cross = cross_up_close | cross_down_close

        exit_rsi_over = rsi > 80
        exit_rsi_under = rsi < 20

        exit_mask = (
            exit_hist_cross
            | exit_close_cross
            | exit_rsi_over
            | exit_rsi_under
        )

        # apply signals
        signals[long_mask] = 1.0
        signals[short_mask] = -1.0
        signals[exit_mask] = 0.0

        # warmup protection
        signals.iloc[:warmup] = 0.0

        # ATR based SL/TP columns
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_atr_mult = params.get("stop_atr_mult", 2.0)
        tp_atr_mult = params.get("tp_atr_mult", 2.0)

        entry_long = (signals == 1.0)
        entry_short = (signals == -1.0)

        df.loc[entry_long, "bb_stop_long"] = close[entry_long] - stop_atr_mult * atr[entry_long]
        df.loc[entry_long, "bb_tp_long"] = close[entry_long] + tp_atr_mult * atr[entry_long]

        df.loc[entry_short, "bb_stop_short"] = close[entry_short] + stop_atr_mult * atr[entry_short]
        df.loc[entry_short, "bb_tp_short"] = close[entry_short] - tp_atr_mult * atr[entry_short]
        signals.iloc[:warmup] = 0.0
        return signals
