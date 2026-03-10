"""
Module-ID: strategies.bollinger_atr_v2

Purpose: Stratégie mean-reversion Bollinger Bands + ATR avec stop-loss Bollinger paramétrable (V2).

Role in pipeline: trading strategy

Key components: BollingerATRStrategyV2, register_strategy("bollinger_atr_v2")

Inputs: DataFrame OHLCV, paramètres (bb_period, bb_std, entry_z, atr_period, atr_percentile, bb_stop_factor, leverage)

Outputs: StrategyResult (signaux LONG/SHORT, prix, stop-loss Bollinger, métadata)

Dependencies: pandas, numpy, utils.parameters, strategies.base

Conventions: LONG sur bande inférieure (oversold), SHORT sur bande supérieure (overbought); stop-loss fixe basé sur Bollinger distance × bb_stop_factor (0.2-2.0); filtre ATR exclut marchés plats; signaux 1/-1/0.

Améliorations V2 vs V1: Stop-loss basé Bollinger au lieu ATR; facteur stop paramétrable; stop fixe à l'entrée (ne bouge pas).

Read-if: Configuration V2 spécifique, paramètres stop-loss Bollinger, ou logique mean-reversion Bollinger+ATR.

Skip-if: Vous utilisez V1 ou V3, ou autres stratégies.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from utils.parameters import SAFE_RANGES_PRESET, ParameterSpec, Preset

from .base import StrategyBase, register_strategy


@register_strategy("bollinger_atr_v2")
class BollingerATRStrategyV2(StrategyBase):
    """
    Stratégie Bollinger Bands + ATR V2 (Mean Reversion + Stop Bollinger).

    Paramètres:
        bb_period: Période des Bandes de Bollinger (défaut: 20)
        bb_std: Écarts-types pour les bandes (défaut: 2.0)
        entry_z: Seuil d'entrée en Z-score (défaut: 2.0)
        atr_period: Période de l'ATR (défaut: 14)
        atr_percentile: Percentile ATR pour filtre volatilité (défaut: 30)
        bb_stop_factor: Facteur de stop-loss Bollinger (défaut: 0.5)
            - 0.2 = stop très proche des bandes (conservateur)
            - 0.5 = stop à mi-distance (équilibré)
            - 2.0 = stop très éloigné (agressif)
        leverage: Levier de trading (défaut: 3)

    Stop-Loss:
        - LONG: stop = lower_band - bb_stop_factor × (middle_band - lower_band)
        - SHORT: stop = upper_band + bb_stop_factor × (upper_band - middle_band)

    Signaux:
        +1 (Long): close <= entry_lower ET ATR > seuil
        -1 (Short): close >= entry_upper ET ATR > seuil
        0: Sinon
    """

    def __init__(self):
        super().__init__(name="BollingerATR_V2")

    @property
    def required_indicators(self) -> List[str]:
        """Indicateurs requis: Bollinger Bands et ATR."""
        return ["bollinger", "atr"]

    @property
    def default_params(self) -> Dict[str, Any]:
        """Paramètres par défaut de la stratégie."""
        return {
            # Bollinger
            "bb_period": 20,
            "bb_std": 2.0,
            # ATR
            "atr_period": 14,
            "atr_percentile": 30,  # Filtre: ATR doit être > ce percentile
            # Trading
            "entry_z": 2.0,  # Z-score pour entrée (touch band = 2 std)
            "bb_stop_factor": 0.5,  # NOUVEAU: Facteur de stop-loss Bollinger
            "leverage": 1,  # Fixé à 1 - ne pas optimiser
            # Frais (pour référence)
            "fees_bps": 10,
            "slippage_bps": 5
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        """Spécifications détaillées des paramètres pour UI/optimisation."""
        return {
            "bb_period": ParameterSpec(
                name="bb_period",
                min_val=5, max_val=60, default=20,  # Élargi: 5-60 pour explorer très court terme à long terme
                param_type="int",
                description="Période des Bandes de Bollinger"
            ),
            "bb_std": ParameterSpec(
                name="bb_std",
                min_val=0.5, max_val=5.0, default=2.0,  # Élargi: 0.5-5.0 pour bandes très serrées à ultra larges
                param_type="float",
                description="Écarts-types pour les bandes"
            ),
            "entry_z": ParameterSpec(
                name="entry_z",
                min_val=0.5, max_val=4.0, default=2.0,  # Élargi: 0.5-4.0 pour entrées agressives à conservatrices
                param_type="float",
                description="Seuil z-score pour entrée"
            ),
            "atr_period": ParameterSpec(
                name="atr_period",
                min_val=5, max_val=35, default=14,  # Élargi: 5-35 pour volatilité ultra court à long terme
                param_type="int",
                description="Période de l'ATR"
            ),
            "atr_percentile": ParameterSpec(
                name="atr_percentile",
                min_val=0, max_val=90, default=30,  # Élargi: 0-90 pour aucun filtre à très restrictif
                param_type="int",
                description="Percentile volatilité minimum (ATR)"
            ),
            "bb_stop_factor": ParameterSpec(
                name="bb_stop_factor",
                min_val=0.1, max_val=3.0, step=0.1, default=0.5,  # Élargi: 0.1-3.0 pour stops ultra serrés à très larges
                param_type="float",
                description="Facteur stop-loss Bollinger (0.1=très proche, 3.0=très loin)"
            ),
            "leverage": ParameterSpec(
                name="leverage",
                min_val=1, max_val=10, default=1,
                param_type="int",
                description="Levier de trading (non optimisé)",
                optimize=False,
            ),
        }

    def get_preset(self) -> Optional[Preset]:
        """Retourne le preset Safe Ranges associé."""
        return SAFE_RANGES_PRESET

    def get_indicator_params(
        self,
        indicator_name: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Mappe les paramètres de la stratégie vers les indicateurs."""
        if indicator_name == "bollinger":
            return {
                "period": int(params.get("bb_period", 20)),
                "std_dev": float(params.get("bb_std", 2.0)),
            }
        if indicator_name == "atr":
            return {"period": int(params.get("atr_period", 14))}
        return super().get_indicator_params(indicator_name, params)

    def generate_signals(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        params: Dict[str, Any]
    ) -> pd.Series:
        """
        Génère les signaux de trading Bollinger + ATR.

        Args:
            df: DataFrame OHLCV
            indicators: {"bollinger": (upper, middle, lower), "atr": atr_array}
            params: Paramètres de stratégie

        Returns:
            pd.Series de signaux (+1, -1, 0)
        """
        # Initialiser signaux à 0 (hold)
        signals = pd.Series(0.0, index=df.index, dtype=np.float64, name="signals")

        # Extraire Bollinger Bands
        if "bollinger" not in indicators or indicators["bollinger"] is None:
            return signals

        bb_result = indicators["bollinger"]
        if isinstance(bb_result, dict):
            upper, middle, lower = bb_result["upper"], bb_result["middle"], bb_result["lower"]
        elif isinstance(bb_result, tuple) and len(bb_result) >= 3:
            upper, middle, lower = bb_result[:3]
        else:
            return signals

        # Convertir en Series si nécessaire
        if not isinstance(upper, pd.Series):
            upper = pd.Series(np.asarray(upper), index=df.index)
        if not isinstance(lower, pd.Series):
            lower = pd.Series(np.asarray(lower), index=df.index)
        if not isinstance(middle, pd.Series):
            middle = pd.Series(np.asarray(middle), index=df.index)

        close = df["close"]

        # === Signaux Bollinger (Mean Reversion) ===
        bb_std = float(params.get("bb_std", 2.0))
        if bb_std <= 0:
            bb_std = 2.0
        entry_z = float(params.get("entry_z", bb_std))
        sigma = (upper - middle) / bb_std
        entry_upper = middle + (sigma * entry_z)
        entry_lower = middle - (sigma * entry_z)

        # Long: prix <= seuil bas (oversold)
        long_condition = close <= entry_lower

        # Short: prix >= seuil haut (overbought)
        short_condition = close >= entry_upper

        signals[long_condition] = 1.0
        signals[short_condition] = -1.0

        # === Filtre ATR (volatilité) ===
        if "atr" in indicators and indicators["atr"] is not None:
            atr_values = indicators["atr"]

            if not isinstance(atr_values, pd.Series):
                atr_values = pd.Series(np.asarray(atr_values), index=df.index)

            # Seuil de volatilité (percentile)
            atr_percentile = params.get("atr_percentile", 30)
            atr_threshold = atr_values.quantile(atr_percentile / 100.0)

            # Filtre: annuler signaux si volatilité trop faible
            low_volatility = atr_values <= atr_threshold
            signals[low_volatility] = 0.0

        # === Calculer stop-loss basés sur Bollinger Bands ===
        # Récupérer le facteur de stop-loss (paramétrable)
        bb_stop_factor = float(params.get("bb_stop_factor", 0.5))

        # Distances entre bandes
        bb_distance_lower = middle - lower  # Distance entre middle et lower
        bb_distance_upper = upper - middle  # Distance entre middle et upper

        # Calculer les prix de stop-loss avec le facteur paramétrable
        # LONG: stop = lower - bb_stop_factor × (middle - lower)
        # SHORT: stop = upper + bb_stop_factor × (upper - middle)
        stop_long = lower - bb_stop_factor * bb_distance_lower
        stop_short = upper + bb_stop_factor * bb_distance_upper

        # Ajouter les colonnes au DataFrame (disponibles pour le backtest)
        df.loc[:, 'bb_stop_long'] = stop_long
        df.loc[:, 'bb_stop_short'] = stop_short
        df.loc[:, 'bb_upper'] = upper
        df.loc[:, 'bb_middle'] = middle
        df.loc[:, 'bb_lower'] = lower
        df.loc[:, 'bb_stop_factor'] = bb_stop_factor  # Pour debug/analyse

        # === Éviter signaux consécutifs identiques ===
        # Ne garder que les changements de signal
        signals_diff = signals.diff()
        # Premier signal conservé, ensuite seulement les changements
        signals_clean = signals.copy()
        signals_clean[1:] = np.where(signals_diff[1:] != 0, signals[1:], 0)

        return signals_clean

    def calculate_position_size(
        self,
        capital: float,
        entry_price: float,
        atr_value: float,
        params: Dict[str, Any]
    ) -> float:
        """
        Calcule la taille de position basée sur le risque.

        Position sizing: risk_amount / stop_distance

        Args:
            capital: Capital disponible
            entry_price: Prix d'entrée
            atr_value: Valeur ATR actuelle
            params: Paramètres de stratégie

        Returns:
            Quantité à trader
        """
        leverage = params.get("leverage", 1)
        risk_pct = params.get("risk_pct", 0.02)  # 2% du capital par trade

        # Risque en valeur absolue
        risk_amount = capital * risk_pct

        # Distance du stop (estimation basée sur ATR en attendant les bandes)
        # Note: Dans un backtest réel, cela serait calculé via bb_stop_long/short
        bb_stop_factor = params.get("bb_stop_factor", 0.5)
        stop_distance = bb_stop_factor * atr_value

        # Quantité basée sur le risque
        if stop_distance > 0:
            quantity = risk_amount / stop_distance
        else:
            quantity = 0

        # Limiter par le leverage disponible
        max_quantity = (capital * leverage) / entry_price

        return min(quantity, max_quantity)

    def get_stop_loss(
        self,
        entry_price: float,
        atr_value: float,
        side: str,
        params: Dict[str, Any],
        bb_middle: Optional[float] = None,
        bb_upper: Optional[float] = None,
        bb_lower: Optional[float] = None
    ) -> float:
        """
        Calcule le niveau de stop-loss basé sur les bandes de Bollinger.

        Logique V2 (paramétrable):
        - LONG: stop = lower_band - bb_stop_factor × (middle_band - lower_band)
                (facteur × distance entre middle et lower, EN DESSOUS de lower_band)
        - SHORT: stop = upper_band + bb_stop_factor × (upper_band - middle_band)
                (facteur × distance entre upper et middle, AU DESSUS de upper_band)

        Cette valeur est FIXE au moment de l'entrée (ne change pas avec les nouvelles bandes).

        Args:
            entry_price: Prix d'entrée
            atr_value: Valeur ATR (fallback uniquement)
            side: "long" ou "short"
            params: Paramètres (contient bb_stop_factor)
            bb_middle: Bande de Bollinger médiane (au moment de l'entrée)
            bb_upper: Bande de Bollinger supérieure (au moment de l'entrée)
            bb_lower: Bande de Bollinger inférieure (au moment de l'entrée)

        Returns:
            Prix du stop-loss
        """
        # Récupérer le facteur paramétrable
        bb_stop_factor = float(params.get("bb_stop_factor", 0.5))

        # Si les bandes de Bollinger sont fournies, utiliser la logique Bollinger
        if bb_middle is not None and bb_upper is not None and bb_lower is not None:
            if side == "long":
                # Stop LONG: lower - bb_stop_factor × (middle - lower)
                bb_distance = bb_middle - bb_lower
                return bb_lower - bb_stop_factor * bb_distance
            else:  # SHORT
                # Stop SHORT: upper + bb_stop_factor × (upper - middle)
                bb_distance = bb_upper - bb_middle
                return bb_upper + bb_stop_factor * bb_distance
        else:
            # Fallback: logique ATR legacy (si les bandes ne sont pas disponibles)
            # Utiliser bb_stop_factor à la place de k_sl
            distance = bb_stop_factor * atr_value

            if side == "long":
                return entry_price - distance
            else:
                return entry_price + distance


__all__ = ["BollingerATRStrategyV2"]
