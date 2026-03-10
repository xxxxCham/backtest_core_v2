"""
Module-ID: strategies.scalping_bollinger_vwap_atr

Purpose: Scalping mean-reversion avec Bollinger (extrêmes) filtré par VWAP,
et gestion du risque via stop/take-profit ATR.

Role in pipeline: core

Key components: ScalpingBollingerVwapAtrStrategy

Inputs: DataFrame OHLCV, indicateurs {"bollinger": {upper,middle,lower}, "vwap": arr, "atr": arr}

Outputs: pd.Series signaux (+1, -1, 0) en impulsions.

Dependencies: strategies.base, utils.parameters
"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec

from .base import StrategyBase, register_strategy


def _as_float_array(value: Any, *, nan: float = 0.0) -> np.ndarray:
    """Convertit en np.ndarray float64 et remplace les NaN pour sécurité."""
    arr = value.values if hasattr(value, "values") else np.asarray(value)
    return np.nan_to_num(arr, nan=nan).astype(np.float64)


@register_strategy("scalping_bollinger_vwap_atr")
class ScalpingBollingerVwapAtrStrategy(StrategyBase):
    """
    Scalping Bollinger + VWAP avec stops/take-profits ATR.

    Contrat moteur:
    - Les signaux sont des impulsions (+1 / -1 / 0).
    - Les sorties sont gérées par le simulateur via des niveaux par-trade.

    Entrées:
        LONG  : close < lower_BB AND close > VWAP AND close > open
        SHORT : close > upper_BB AND close < VWAP AND close < open

    Gestion du risque:
        - stop = entry ± stop_atr_mult * ATR
        - tp   = entry ± tp_atr_mult   * ATR

    Intégration simulateur:
        Les niveaux sont écrits uniquement sur les barres d'entrée dans:
        - bb_stop_long, bb_tp_long, bb_stop_short, bb_tp_short
        (NaN ailleurs, pour limiter la pollution du DataFrame).
    """

    def __init__(self):
        super().__init__(name="Scalping BB+VWAP+ATR")

    @property
    def required_indicators(self) -> List[str]:
        return ["bollinger", "vwap", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            # Indicators
            "bb_period": 20,
            "bb_std": 2.0,
            "vwap_period": 0,  # 0 => anchored (period=None)
            "atr_period": 14,
            # Risk
            "stop_atr_mult": 1.0,
            "tp_atr_mult": 1.5,
            # Trading
            "leverage": 1,
            "initial_capital": 10000,
            # Warmup
            "warmup": 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        return {
            "bb_period": ParameterSpec(
                name="bb_period",
                min_val=10,
                max_val=50,
                default=20,
                step=10,
                param_type="int",
                description="Bollinger period",
            ),
            "bb_std": ParameterSpec(
                name="bb_std",
                min_val=1.0,
                max_val=3.0,
                default=2.0,
                step=0.5,
                param_type="float",
                description="Bollinger std dev",
            ),
            "vwap_period": ParameterSpec(
                name="vwap_period",
                min_val=0,
                max_val=100,
                default=0,
                step=20,
                param_type="int",
                description="VWAP rolling period (0 = anchored)",
            ),
            "atr_period": ParameterSpec(
                name="atr_period",
                min_val=7,
                max_val=28,
                default=14,
                step=7,
                param_type="int",
                description="ATR period",
            ),
            "stop_atr_mult": ParameterSpec(
                name="stop_atr_mult",
                min_val=0.5,
                max_val=2.0,
                default=1.0,
                step=0.1,
                param_type="float",
                description="Stop-loss ATR multiplier",
            ),
            "tp_atr_mult": ParameterSpec(
                name="tp_atr_mult",
                min_val=1.0,
                max_val=3.0,
                default=1.5,
                step=0.1,
                param_type="float",
                description="Take-profit ATR multiplier",
            ),
            "warmup": ParameterSpec(
                name="warmup",
                min_val=20,
                max_val=100,
                default=50,
                step=10,
                param_type="int",
                description="Warmup bars",
                optimize=False,
            ),
            "leverage": ParameterSpec(
                name="leverage",
                min_val=1,
                max_val=10,
                default=1,
                param_type="int",
                description="Leverage (non optimise)",
                optimize=False,
            ),
        }

    def get_indicator_params(
        self,
        indicator_name: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        if indicator_name == "bollinger":
            return {
                "period": int(params.get("bb_period", 20)),
                "std_dev": float(params.get("bb_std", 2.0)),
            }
        if indicator_name == "atr":
            return {"period": int(params.get("atr_period", 14))}
        if indicator_name == "vwap":
            period = int(params.get("vwap_period", 0) or 0)
            return {"period": None if period <= 0 else period}
        return super().get_indicator_params(indicator_name, params)

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any],
    ) -> pd.Series:
        signals = pd.Series(0.0, index=df.index, dtype=np.float64, name="signals")

        bb = indicators.get("bollinger")
        vwap_raw = indicators.get("vwap")
        atr_raw = indicators.get("atr")
        if bb is None or vwap_raw is None or atr_raw is None:
            return signals

        # --- Bollinger ---
        if isinstance(bb, dict):
            upper = _as_float_array(bb.get("upper"), nan=0.0)
            lower = _as_float_array(bb.get("lower"), nan=0.0)
        elif isinstance(bb, tuple) and len(bb) >= 3:
            upper = _as_float_array(bb[0], nan=0.0)
            lower = _as_float_array(bb[2], nan=0.0)
        else:
            return signals

        # --- VWAP / ATR ---
        vwap = _as_float_array(vwap_raw, nan=0.0)
        atr = _as_float_array(atr_raw, nan=0.0)

        # --- OHLC ---
        close = _as_float_array(df["close"].values, nan=0.0)
        open_ = _as_float_array(df["open"].values, nan=0.0)

        # --- Params ---
        stop_atr_mult = float(params.get("stop_atr_mult", 1.0))
        tp_atr_mult = float(params.get("tp_atr_mult", 1.5))
        warmup = int(params.get("warmup", 50))
        warmup = max(
            0,
            min(
                len(df),
                max(
                    warmup,
                    int(params.get("bb_period", 20)),
                    int(params.get("atr_period", 14)),
                    int(params.get("vwap_period", 0) or 0),
                ),
            ),
        )

        # Safety clamps (user params override)
        if not np.isfinite(stop_atr_mult) or stop_atr_mult < 0:
            stop_atr_mult = 1.0
        if not np.isfinite(tp_atr_mult) or tp_atr_mult < 0:
            tp_atr_mult = 1.5

        # --- Entry conditions ---
        long_entry = (close < lower) & (close > vwap) & (close > open_)
        short_entry = (close > upper) & (close < vwap) & (close < open_)

        signals_arr = np.zeros(len(df), dtype=np.float64)
        signals_arr[long_entry] = 1.0
        signals_arr[short_entry] = -1.0

        # Warmup: pas de signal avant N barres
        signals_arr[:warmup] = 0.0

        # Nettoyage signaux consécutifs identiques (impulsions)
        diff = np.diff(signals_arr, prepend=0.0)
        signals_arr[diff == 0] = 0.0

        # --- Per-entry stop/tp levels for simulator (NaN except on entry bars) ---
        n = len(df)
        stop_long = np.full(n, np.nan, dtype=np.float64)
        tp_long = np.full(n, np.nan, dtype=np.float64)
        stop_short = np.full(n, np.nan, dtype=np.float64)
        tp_short = np.full(n, np.nan, dtype=np.float64)

        valid_atr = np.isfinite(atr) & (atr > 0) & np.isfinite(close)
        long_impulse = (signals_arr == 1.0) & valid_atr
        short_impulse = (signals_arr == -1.0) & valid_atr

        if np.any(long_impulse):
            stop_long[long_impulse] = close[long_impulse] - (stop_atr_mult * atr[long_impulse])
            tp_long[long_impulse] = close[long_impulse] + (tp_atr_mult * atr[long_impulse])
        if np.any(short_impulse):
            stop_short[short_impulse] = close[short_impulse] + (stop_atr_mult * atr[short_impulse])
            tp_short[short_impulse] = close[short_impulse] - (tp_atr_mult * atr[short_impulse])

        # ⚠️ Compat simulateur: colonnes "bb_*" lues comme niveaux stop/tp fixes à l'entrée
        df.loc[:, "bb_stop_long"] = stop_long
        df.loc[:, "bb_tp_long"] = tp_long
        df.loc[:, "bb_stop_short"] = stop_short
        df.loc[:, "bb_tp_short"] = tp_short

        signals[:] = signals_arr
        return signals


__all__ = ["ScalpingBollingerVwapAtrStrategy"]

