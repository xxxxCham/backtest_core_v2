from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec
from strategies.base import StrategyBase


class BuilderGeneratedStrategy(StrategyBase):
    def __init__(self):
        super().__init__(name="amplitude_rsi_donchian_breakout")

    @property
    def required_indicators(self) -> List[str]:
        return ["amplitude_hunter", "donchian", "rsi", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "amplitude_hunter_entry_threshold": 0.6,
            "amplitude_hunter_exit_threshold": 0.15,
            "leverage": 1,
            "rsi_overbought": 70,
            "rsi_oversold": 30,
            "rsi_period": 14,
            "stop_atr_mult": 2.25,
            "tp_atr_mult": 4.0,
            "warmup": 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "amplitude_hunter_entry_threshold": ParameterSpec(
                name="amplitude_hunter_entry_threshold",
                min_val=0.5,
                max_val=0.9,
                default=0.6,
                param_type="float",
                step=0.1,
            ),
            "amplitude_hunter_exit_threshold": ParameterSpec(
                name="amplitude_hunter_exit_threshold",
                min_val=0.05,
                max_val=0.3,
                default=0.15,
                param_type="float",
                step=0.1,
            ),
            "rsi_period": ParameterSpec(
                name="rsi_period",
                min_val=5,
                max_val=30,
                default=14,
                param_type="int",
                step=1,
            ),
            "stop_atr_mult": ParameterSpec(
                name="stop_atr_mult",
                min_val=0.5,
                max_val=4.0,
                default=2.25,
                param_type="float",
                step=0.1,
            ),
            "tp_atr_mult": ParameterSpec(
                name="tp_atr_mult",
                min_val=2.0,
                max_val=6.0,
                default=4.0,
                param_type="float",
                step=0.1,
            ),
            "leverage": ParameterSpec(
                name="leverage",
                min_val=1,
                max_val=2,
                default=1,
                param_type="int",
                step=1,
            ),
        }

    def generate_signals(
        self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]
    ) -> pd.Series:
        n = len(df)
        warmup = int(params.get("warmup", 50))

        signals = pd.Series(0.0, index=df.index, dtype=np.float64)

        # === EXTRACT INDICATOR ARRAYS ===
        amp_raw = indicators['amplitude_hunter']
        # amplitude_hunter may return a dict with a 'score' key
        if isinstance(amp_raw, dict):
            amplitude = np.nan_to_num(amp_raw.get("score", np.zeros(n)))
        else:
            amplitude = np.nan_to_num(amp_raw)

        donch = indicators['donchian']
        upper = np.nan_to_num(donch["upper"])
        lower = np.nan_to_num(donch["lower"])
        middle = np.nan_to_num(donch["middle"])

        rsi = np.nan_to_num(indicators['rsi'])
        atr = np.nan_to_num(indicators['atr'])
        close = df["close"].values

        # === CROSS HELPERS ===
        prev_close = np.roll(close, 1)
        prev_close[0] = np.nan
        prev_middle = np.roll(middle, 1)
        prev_middle[0] = np.nan
        cross_up = (close > middle) & (prev_close <= prev_middle)
        cross_down = (close < middle) & (prev_close >= prev_middle)

        # === ENTRY CONDITIONS ===
        entry_thresh = params.get("amplitude_hunter_entry_threshold", 0.6)
        long_entry_mask = (
            (amplitude > entry_thresh) & (close > upper) & (rsi > 50.0)
        )
        short_entry_mask = (
            (amplitude > entry_thresh) & (close < lower) & (rsi < 50.0)
        )

        signals[long_entry_mask] = 1.0
        signals[short_entry_mask] = -1.0

        # === EXIT CONDITIONS ===
        rsi_exit = params.get("rsi_exit_threshold", 40.0)
        long_exit_mask = cross_down | (rsi < rsi_exit)
        short_exit_mask = cross_up | (rsi > params.get("rsi_overbought", 70.0))

        signals[long_exit_mask] = 0.0
        signals[short_exit_mask] = 0.0

        # Ensure warmup period has no signals
        signals.iloc[:warmup] = 0.0

        # === ATR-BASED SL/TP ===
        df.loc[:, "bb_stop_long"] = np.nan
        df.loc[:, "bb_tp_long"] = np.nan
        df.loc[:, "bb_stop_short"] = np.nan
        df.loc[:, "bb_tp_short"] = np.nan

        stop_mult = params.get("stop_atr_mult", 2.25)
        tp_mult = params.get("tp_atr_mult", 4.0)

        df.loc[long_entry_mask, "bb_stop_long"] = close[long_entry_mask] - (
            stop_mult * atr[long_entry_mask]
        )
        df.loc[long_entry_mask, "bb_tp_long"] = close[long_entry_mask] + (
            tp_mult * atr[long_entry_mask]
        )
        df.loc[short_entry_mask, "bb_stop_short"] = close[short_entry_mask] + (
            stop_mult * atr[short_entry_mask]
        )
        df.loc[short_entry_mask, "bb_tp_short"] = close[short_entry_mask] - (
            tp_mult * atr[short_entry_mask]
        )

        return signals