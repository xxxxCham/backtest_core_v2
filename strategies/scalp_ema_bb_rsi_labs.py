"""
Module-ID: strategies.scalp_ema_bb_rsi_labs

Purpose: Scalp continuation/reversal EMA + Bollinger + RSI (version Labs).

Role in pipeline: core

Key components: ScalpEmaBbRsiLabsStrategy

Inputs: DataFrame OHLCV, indicateurs ema/bollinger/rsi/atr

Outputs: StrategyResult (signaux 1/-1/0)

Dependencies: strategies.base, utils.parameters

Conventions:
    - LABS = exploration paramétrique, résultats NON représentatifs.
    - Logique: pullback sous EMA + touche lower Bollinger + RSI cross oversold → LONG.
      Symétrique pour SHORT.
    - Stop-loss via k_sl (simulateur), pas de gestion interne des sorties.

Read-if: Modification logique scalp continuation ou intégration labs.

Skip-if: Vous ne changez que d'autres stratégies.
"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec

from .base import StrategyBase, register_strategy


@register_strategy("scalp_ema_bb_rsi_labs")
class ScalpEmaBbRsiLabsStrategy(StrategyBase):
    """
    Scalp de continuation / micro-retournement (Labs).

    Hypothèse: Un pullback sous l'EMA21 combiné à un touché de la bande
    de Bollinger inférieure, confirmé par un croisement RSI au-dessus du
    niveau de survente, identifie une entrée haute probabilité.
    Logique miroir pour les shorts.

    LABS: Les plages de paramètres sont larges pour exploration.
    Les résultats du grid search ne sont PAS représentatifs d'un usage réel.

    Capital par trade: 10 000 (leverage × capital / prix).
    """

    def __init__(self):
        super().__init__(name="Scalp EMA+BB+RSI (Labs)")

    @property
    def required_indicators(self) -> List[str]:
        return ["ema", "rsi", "bollinger", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            # Bollinger
            "bb_period": 20,
            "bb_std": 2.0,
            # EMA (une seule, utilisée comme filtre tendance)
            "ema_period": 21,
            # RSI
            "rsi_period": 14,
            "rsi_overbought": 70,
            "rsi_oversold": 30,
            # Trading
            "k_sl": 1.5,
            "leverage": 1,
            "initial_capital": 10000,
            # Warmup
            "warmup": 50,
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        """Plages Labs pour grid search exploratoire.

        Steps explicites pour contrôler la combinatoire :
        5 × 4 × 5 × 4 × 3 × 3 × 4 = 14 400 combos (raisonnable).
        """
        return {
            "bb_period": ParameterSpec(
                name="bb_period",
                min_val=10, max_val=50, default=20,
                step=10,             # 10, 20, 30, 40, 50 → 5 valeurs
                param_type="int",
                description="Bollinger period",
            ),
            "bb_std": ParameterSpec(
                name="bb_std",
                min_val=1.0, max_val=3.0, default=2.0,
                step=0.5,            # 1.0, 1.5, 2.0, 2.5, 3.0 → 5 valeurs
                param_type="float",
                description="Bollinger standard deviation",
            ),
            "ema_period": ParameterSpec(
                name="ema_period",
                min_val=10, max_val=50, default=21,
                step=10,             # 10, 20, 30, 40, 50 → 5 valeurs
                param_type="int",
                description="EMA period (trend filter)",
            ),
            "rsi_period": ParameterSpec(
                name="rsi_period",
                min_val=7, max_val=21, default=14,
                step=7,              # 7, 14, 21 → 3 valeurs
                param_type="int",
                description="RSI period",
            ),
            "rsi_overbought": ParameterSpec(
                name="rsi_overbought",
                min_val=65, max_val=80, default=70,
                step=5,              # 65, 70, 75, 80 → 4 valeurs
                param_type="int",
                description="RSI overbought level",
            ),
            "rsi_oversold": ParameterSpec(
                name="rsi_oversold",
                min_val=20, max_val=35, default=30,
                step=5,              # 20, 25, 30, 35 → 4 valeurs
                param_type="int",
                description="RSI oversold level",
            ),
            "k_sl": ParameterSpec(
                name="k_sl",
                min_val=0.5, max_val=3.0, default=1.5,
                step=0.5,            # 0.5, 1.0, 1.5, 2.0, 2.5, 3.0 → 6 valeurs
                param_type="float",
                description="Stop-loss multiplier (%)",
            ),
            "warmup": ParameterSpec(
                name="warmup",
                min_val=50, max_val=50, default=50,
                param_type="int",
                description="Warmup bars",
                optimize=False,
            ),
            "leverage": ParameterSpec(
                name="leverage",
                min_val=1, max_val=10, default=1,
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
        """Mapping explicite des paramètres vers les indicateurs."""
        if indicator_name == "bollinger":
            return {
                "period": int(params.get("bb_period", 20)),
                "std_dev": float(params.get("bb_std", 2.0)),
            }
        if indicator_name == "ema":
            return {"period": int(params.get("ema_period", 21))}
        if indicator_name == "rsi":
            return {"period": int(params.get("rsi_period", 14))}
        if indicator_name == "atr":
            return {"period": 14}
        return super().get_indicator_params(indicator_name, params)

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any],
    ) -> pd.Series:
        """
        Signaux d'entrée scalp continuation.

        LONG:  close < EMA  AND  close <= lower BB  AND  RSI cross au-dessus oversold
        SHORT: close > EMA  AND  close >= upper BB  AND  RSI cross en-dessous overbought

        Returns:
            pd.Series de signaux impulsion (+1, -1, 0).
        """
        signals = pd.Series(0.0, index=df.index, dtype=np.float64)
        warmup = int(params.get("warmup", 50))

        # --- Prix ---
        close = df["close"].values.astype(np.float64)

        # --- EMA ---
        ema_raw = indicators.get("ema")
        if ema_raw is None:
            return signals
        ema = np.nan_to_num(
            ema_raw.values if hasattr(ema_raw, "values") else np.asarray(ema_raw),
            nan=0.0,
        ).astype(np.float64)

        # --- RSI ---
        rsi_raw = indicators.get("rsi")
        if rsi_raw is None:
            return signals
        rsi = np.nan_to_num(
            rsi_raw.values if hasattr(rsi_raw, "values") else np.asarray(rsi_raw),
            nan=50.0,
        ).astype(np.float64)

        # --- Bollinger ---
        bb = indicators.get("bollinger")
        if bb is None:
            return signals

        if isinstance(bb, dict):
            lower = np.nan_to_num(
                bb["lower"].values if hasattr(bb["lower"], "values") else np.asarray(bb["lower"]),
            ).astype(np.float64)
            upper = np.nan_to_num(
                bb["upper"].values if hasattr(bb["upper"], "values") else np.asarray(bb["upper"]),
            ).astype(np.float64)
        elif isinstance(bb, tuple) and len(bb) >= 3:
            upper = np.nan_to_num(np.asarray(bb[0])).astype(np.float64)
            lower = np.nan_to_num(np.asarray(bb[2])).astype(np.float64)
        else:
            return signals

        # --- Paramètres ---
        overbought = float(params.get("rsi_overbought", 70))
        oversold = float(params.get("rsi_oversold", 30))

        # RSI bar précédente
        rsi_prev = np.empty_like(rsi)
        rsi_prev[0] = np.nan
        rsi_prev[1:] = rsi[:-1]

        # --- Conditions d'entrée ---
        long_entry = (
            (close < ema)
            & (close <= lower)
            & (rsi_prev <= oversold)
            & (rsi > oversold)
        )

        short_entry = (
            (close > ema)
            & (close >= upper)
            & (rsi_prev >= overbought)
            & (rsi < overbought)
        )

        # --- Écriture vectorisée ---
        signals_arr = np.zeros(len(df), dtype=np.float64)
        signals_arr[long_entry] = 1.0
        signals_arr[short_entry] = -1.0

        # Warmup: pas de signal avant N bars
        signals_arr[:warmup] = 0.0

        # Nettoyage signaux consécutifs identiques
        diff = np.diff(signals_arr, prepend=0.0)
        signals_arr[diff == 0] = 0.0

        signals[:] = signals_arr
        return signals
