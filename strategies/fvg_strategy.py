"""
Module-ID: strategies.fvg_strategy

Purpose: Strategie FairValOseille - Trading base sur FVG, FVA, swings et smart legs.

Role in pipeline: trading strategy

Key components: FVGStrategy, register_strategy("fvg_strategy")

Inputs: DataFrame OHLCV, parametres (leverage, scoring)

Outputs: StrategyResult (signaux LONG/SHORT, prix, stop-loss, metadata)

Dependencies: pandas, numpy, utils.parameters, strategies.base

Conventions: Signaux bases sur consensus patterns; stop-loss dynamiques; scoring multi-indicateurs.
"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from utils.parameters import ParameterSpec

from .base import StrategyBase, register_strategy


@register_strategy("fvg_strategy")
class FVGStrategy(StrategyBase):
    """
    Strategie FairValOseille - Version simplifiee et corrigee.

    Logique de trading:
        LONG: Score bull > seuil ET (swing_low OU fvg_bullish)
        SHORT: Score bear > seuil ET (swing_high OU fvg_bearish)

    Indicateurs requis:
        - swing_high, swing_low (detection fractals)
        - fvg_bullish, fvg_bearish (fair value gaps)
        - fva (fair value areas)
        - smart_leg_bullish, smart_leg_bearish (validation directionnelle)
        - bull_score, bear_score (scoring)
        - atr (volatilite pour stops)
    """

    def __init__(self):
        super().__init__(name="FVG_Strategy")

    @property
    def required_indicators(self) -> List[str]:
        """Indicateurs requis par la strategie."""
        return [
            "swing_high",
            "swing_low",
            "fvg_bullish",
            "fvg_bearish",
            "fva",
            "smart_leg_bullish",
            "smart_leg_bearish",
            "bull_score",
            "bear_score",
            "atr"
        ]

    @property
    def default_params(self) -> Dict[str, Any]:
        """Parametres par defaut de la strategie."""
        return {
            # Scoring
            "min_bull_score": 0.6,   # Score minimum pour entree LONG
            "min_bear_score": 0.6,   # Score minimum pour entree SHORT
            # Stop-loss / Take-profit
            "stop_atr_mult": 1.5,    # Multiplicateur ATR pour stop-loss
            "tp_atr_mult": 3.0,      # Multiplicateur ATR pour take-profit
            # Trading
            "leverage": 1,  # Fixé à 1 - ne pas optimiser
            "risk_pct": 0.02,        # 2% du capital par trade
            # Frais
            "fees_bps": 10,
            "slippage_bps": 5
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        """Specifications des parametres pour UI/optimisation."""
        return {
            "min_bull_score": ParameterSpec(
                name="min_bull_score",
                min_val=0.3, max_val=0.9, step=0.05, default=0.6,
                param_type="float",
                description="Score minimum pour signal LONG"
            ),
            "min_bear_score": ParameterSpec(
                name="min_bear_score",
                min_val=0.3, max_val=0.9, step=0.05, default=0.6,
                param_type="float",
                description="Score minimum pour signal SHORT"
            ),
            "stop_atr_mult": ParameterSpec(
                name="stop_atr_mult",
                min_val=1.0, max_val=3.0, step=0.25, default=1.5,
                param_type="float",
                description="Multiplicateur ATR pour stop-loss"
            ),
            "tp_atr_mult": ParameterSpec(
                name="tp_atr_mult",
                min_val=2.0, max_val=5.0, step=0.5, default=3.0,
                param_type="float",
                description="Multiplicateur ATR pour take-profit"
            ),
            "leverage": ParameterSpec(
                name="leverage",
                min_val=1, max_val=10, default=1,
                param_type="int",
                description="Levier de trading (non optimisé)",
                optimize=False,
            ),
        }

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any]
    ) -> pd.Series:
        """
        Genere les signaux de trading bases sur les patterns detectes.

        Args:
            df: DataFrame OHLCV
            indicators: Dict contenant tous les indicateurs requis
            params: Parametres de strategie

        Returns:
            pd.Series de signaux (+1 LONG, -1 SHORT, 0 HOLD)
        """
        # Initialiser signaux
        signals = pd.Series(0.0, index=df.index, dtype=np.float64, name="signals")

        # Verifier presence des indicateurs
        required = self.required_indicators
        if not all(ind in indicators for ind in required):
            return signals

        # Extraire les indicateurs
        swing_high = indicators["swing_high"]
        swing_low = indicators["swing_low"]
        fvg_bull = indicators["fvg_bullish"]
        fvg_bear = indicators["fvg_bearish"]
        bull_score = indicators["bull_score"]
        bear_score = indicators["bear_score"]

        # Convertir en Series si necessaire
        if not isinstance(swing_high, pd.Series):
            swing_high = pd.Series(swing_high, index=df.index)
        if not isinstance(swing_low, pd.Series):
            swing_low = pd.Series(swing_low, index=df.index)
        if not isinstance(fvg_bull, pd.Series):
            fvg_bull = pd.Series(fvg_bull, index=df.index)
        if not isinstance(fvg_bear, pd.Series):
            fvg_bear = pd.Series(fvg_bear, index=df.index)
        if not isinstance(bull_score, pd.Series):
            bull_score = pd.Series(bull_score, index=df.index)
        if not isinstance(bear_score, pd.Series):
            bear_score = pd.Series(bear_score, index=df.index)

        # Seuils de scoring
        min_bull_score = params.get("min_bull_score", 0.6)
        min_bear_score = params.get("min_bear_score", 0.6)

        # === CONDITIONS LONG ===
        # Score bull suffisant ET presence d'un pattern (swing_low OU fvg_bullish)
        long_condition = (
            (bull_score >= min_bull_score) &
            (swing_low | fvg_bull)
        )

        # === CONDITIONS SHORT ===
        # Score bear suffisant ET presence d'un pattern (swing_high OU fvg_bearish)
        short_condition = (
            (bear_score >= min_bear_score) &
            (swing_high | fvg_bear)
        )

        # Assigner signaux
        signals[long_condition] = 1.0
        signals[short_condition] = -1.0

        # Eviter signaux consecutifs identiques
        signals_diff = signals.diff()
        signals_clean = signals.copy()
        signals_clean[1:] = np.where(signals_diff[1:] != 0, signals[1:], 0)

        return signals_clean

    def get_stop_loss(
        self,
        entry_price: float,
        atr_value: float,
        side: str,
        params: Dict[str, Any],
        **kwargs
    ) -> float:
        """
        Calcule le stop-loss base sur ATR.

        Args:
            entry_price: Prix d'entree
            atr_value: Valeur ATR actuelle
            side: "long" ou "short"
            params: Parametres (contient stop_atr_mult)

        Returns:
            Prix du stop-loss
        """
        stop_mult = params.get("stop_atr_mult", 1.5)
        distance = atr_value * stop_mult

        if side == "long":
            return entry_price - distance
        else:  # SHORT
            return entry_price + distance

    def get_take_profit(
        self,
        entry_price: float,
        atr_value: float,
        side: str,
        params: Dict[str, Any],
        **kwargs
    ) -> float:
        """
        Calcule le take-profit base sur ATR.

        Args:
            entry_price: Prix d'entree
            atr_value: Valeur ATR actuelle
            side: "long" ou "short"
            params: Parametres (contient tp_atr_mult)

        Returns:
            Prix du take-profit
        """
        tp_mult = params.get("tp_atr_mult", 3.0)
        distance = atr_value * tp_mult

        if side == "long":
            return entry_price + distance
        else:  # SHORT
            return entry_price - distance


__all__ = ["FVGStrategy"]
