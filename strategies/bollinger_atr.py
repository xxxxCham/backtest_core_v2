"""
Module-ID: strategies.bollinger_atr

Purpose: Stratégie de breakout basée sur les Bandes de Bollinger et ATR (volatilité).

Role in pipeline: core

Key components: BollingerATRStrategy, bb_window, bb_std, atr_period, atr_multiplier

Inputs: DataFrame OHLCV avec colonnes high, low, close

Outputs: StrategyResult (signaux 1/-1/0 sur breakouts bandes/ATR)

Dependencies: strategies.base, indicators.bollinger, indicators.atr, utils.parameters

Conventions: bb_window > atr_period recommandé; bandes supérieures/inférieures + filtrage ATR; volume optionnel.

Read-if: Modification breakout logic, seuils volatilité, ou constraints.

Skip-if: Vous ne changez que d'autres stratégies.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from utils.parameters import SAFE_RANGES_PRESET, ParameterSpec, Preset

from .base import StrategyBase, register_strategy


@register_strategy("bollinger_atr")
class BollingerATRStrategy(StrategyBase):
    """
    Stratégie Bollinger Bands + ATR (Mean Reversion).

    Cette stratégie est le "moteur de Baptiste" - la stratégie de référence
    utilisée pour valider le nouveau moteur de backtest.

    Paramètres:
        entry_z: Seuil d'entrée en Z-score (défaut: 2.0)
        k_sl: Multiplicateur ATR pour stop-loss (défaut: 1.5)
        atr_percentile: Percentile ATR pour filtre volatilité (défaut: 30)
        leverage: Levier de trading (défaut: 3)

    Signaux:
        +1 (Long): close <= lower_band ET ATR > seuil
        -1 (Short): close >= upper_band ET ATR > seuil
        0: Sinon
    """

    def __init__(self):
        super().__init__(name="BollingerATR")

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
            "k_sl": 1.5,     # Stop loss = k_sl * ATR
            "leverage": 1,  # Fixé à 1 - ne pas optimiser
            # Frais (pour référence)
            "fees_bps": 10,
            "slippage_bps": 5
        }

    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        """Spécifications basées sur la théorie de l'analyse technique.

        🎓 RANGES THÉORIQUES optimisés (6.1M combinaisons vs 264M précédent) :
        - Basé sur les standards de John Bollinger et Welles Wilder
        - Évite les valeurs aberrantes des backtests (entry_z<0.5, k_sl négatif)
        - Focus sur les plages utilisées par les traders professionnels

        ⚠️ ATTENTION : Les résultats backtests montrent 84.1% d'échecs + 64.6% de comptes ruinés.
        Cette stratégie nécessite peut-être une révision fondamentale de sa logique.
        """
        return {
            "bb_period": ParameterSpec(
                name="bb_period",
                min_val=10, max_val=50, default=20,  # Élargi: 10-50 pour explorer périodes courtes et longues
                param_type="int",
                description="Période des Bandes de Bollinger"
            ),
            "bb_std": ParameterSpec(
                name="bb_std",
                min_val=1.0, max_val=4.0, default=2.0,  # Élargi: 1.0-4.0 pour couvrir bandes serrées à très larges
                param_type="float",
                description="Écarts-types pour les bandes"
            ),
            "entry_z": ParameterSpec(
                name="entry_z",
                min_val=0.5, max_val=4.0, default=2.0,  # Élargi: 0.5-4.0 pour explorer entrées précoces à conservatrices
                param_type="float",
                description="Seuil z-score pour entree"
            ),
            "atr_period": ParameterSpec(
                name="atr_period",
                min_val=7, max_val=28, default=14,  # Élargi: 7-28 pour couvrir volatilité court terme à long terme
                param_type="int",
                description="Période de l'ATR"
            ),
            "atr_percentile": ParameterSpec(
                name="atr_percentile",
                min_val=0, max_val=80, default=30,  # Élargi: 0-80 pour explorer filtre nul à très restrictif
                param_type="int",
                description="Percentile volatilite minimum (ATR)"
            ),
            "k_sl": ParameterSpec(
                name="k_sl",
                min_val=0.5, max_val=4.0, default=1.5,  # Élargi: 0.5-4.0 pour explorer stops serrés à très larges
                param_type="float",
                description="Multiplicateur ATR pour stop-loss"
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
        """Mappe les parametres de la strategie vers les indicateurs."""
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
        # Pour LONG: stop = lower_band - 0.5 × (middle_band - lower_band)
        # Pour SHORT: stop = upper_band + 0.5 × (upper_band - middle_band)
        # Ces stop-loss sont stockés dans le DataFrame pour utilisation ultérieure
        bb_distance_lower = middle - lower  # Distance entre middle et lower
        bb_distance_upper = upper - middle  # Distance entre middle et upper

        # Calculer les prix de stop-loss pour chaque type de position
        stop_long = lower - 0.5 * bb_distance_lower   # En dessous de lower_band
        stop_short = upper + 0.5 * bb_distance_upper  # Au dessus de upper_band

        # Ajouter les colonnes au DataFrame (disponibles pour le backtest)
        df.loc[:, 'bb_stop_long'] = stop_long
        df.loc[:, 'bb_stop_short'] = stop_short
        df.loc[:, 'bb_upper'] = upper
        df.loc[:, 'bb_middle'] = middle
        df.loc[:, 'bb_lower'] = lower

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
        Calcule la taille de position basée sur le risque ATR.

        Position sizing: risk_amount / (k_sl * ATR)

        Args:
            capital: Capital disponible
            entry_price: Prix d'entrée
            atr_value: Valeur ATR actuelle
            params: Paramètres de stratégie

        Returns:
            Quantité à trader
        """
        leverage = params.get("leverage", 1)
        k_sl = params.get("k_sl", 1.5)
        risk_pct = params.get("risk_pct", 0.02)  # 2% du capital par trade

        # Risque en valeur absolue
        risk_amount = capital * risk_pct

        # Distance du stop en prix
        stop_distance = k_sl * atr_value

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

        Logique:
        - LONG: stop = lower_band - 0.5 × (middle_band - lower_band)
                (moitié de la distance entre middle et lower, EN DESSOUS de lower_band)
        - SHORT: stop = upper_band + 0.5 × (upper_band - middle_band)
                (moitié de la distance entre upper et middle, AU DESSUS de upper_band)

        Cette valeur est FIXE au moment de l'entrée (ne change pas avec les nouvelles bandes).

        Args:
            entry_price: Prix d'entrée
            atr_value: Valeur ATR (non utilisé avec stop Bollinger)
            side: "long" ou "short"
            params: Paramètres
            bb_middle: Bande de Bollinger médiane (au moment de l'entrée)
            bb_upper: Bande de Bollinger supérieure (au moment de l'entrée)
            bb_lower: Bande de Bollinger inférieure (au moment de l'entrée)

        Returns:
            Prix du stop-loss
        """
        # Si les bandes de Bollinger sont fournies, utiliser la logique Bollinger
        if bb_middle is not None and bb_upper is not None and bb_lower is not None:
            if side == "long":
                # Stop LONG: lower - 0.5 × (middle - lower)
                bb_distance = bb_middle - bb_lower
                return bb_lower - 0.5 * bb_distance
            else:  # SHORT
                # Stop SHORT: upper + 0.5 × (upper - middle)
                bb_distance = bb_upper - bb_middle
                return bb_upper + 0.5 * bb_distance
        else:
            # Fallback: logique ATR legacy (si les bandes ne sont pas disponibles)
            k_sl = params.get("k_sl", 1.5)
            distance = k_sl * atr_value

            if side == "long":
                return entry_price - distance
            else:
                return entry_price + distance


__all__ = ["BollingerATRStrategy"]
