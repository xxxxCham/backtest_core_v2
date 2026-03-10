"""
Module-ID: strategies.bollinger_atr_v3

Purpose: Stratégie mean-reversion Bollinger+ATR avec entrées ET stop-loss VARIABLES sur échelle unifiée (V3 - Pure Logic).

Role in pipeline: trading strategy / analysis base

Key components: BollingerATRStrategyV3, register_strategy("bollinger_atr_v3")

Inputs: DataFrame OHLCV, paramètres (bb_period, bb_std, entry_level_long, entry_level_short, atr_period, atr_percentile, stop_distance, leverage)

Outputs: StrategyResult (signaux LONG/SHORT variables, prix, stop-loss calculés, metadata)

Dependencies: pandas, numpy, utils.parameters, strategies.base

Conventions: Échelle unifiée 0%=lower, 50%=middle, 100%=upper; LONG variables -50% à +20% (sous lower → middle); SHORT variables +80% à +150% (vers/au-dessus upper); stop-loss 0.1-1.0 × distance depuis entry_price; filtre ATR volatilité; BASE D'ANALYSE pour patterns pre-filtre.

V3 Innovations: Entrées/stop variables vs fixes V2; échelle unifiée exploratoire; base patterns avant filtrage.

Read-if: Analyse patterns Bollinger exploratoires, échelle unifiée, ou logique V3 entrées/stop variables.

Skip-if: Vous préférez V1/V2 fixes ou autres stratégies.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from utils.parameters import SAFE_RANGES_PRESET, ParameterSpec, Preset

from .base import StrategyBase, register_strategy


@register_strategy("bollinger_atr_v3")
class BollingerATRStrategyV3(StrategyBase):
    """
    Stratégie Bollinger Bands + ATR V3 (Entrée et Stop Variables).

    Échelle de référence:
        0% = lower_band
        50% = middle_band
        100% = upper_band
        Distance totale = upper_band - lower_band

    Paramètres:
        bb_period: Période des Bandes de Bollinger (défaut: 20)
        bb_std: Écarts-types pour les bandes (défaut: 2.0)
        atr_period: Période de l'ATR (défaut: 14)
        atr_percentile: Percentile ATR pour filtre volatilité (défaut: 30)

        entry_pct_long: Position d'entrée LONG sur échelle (défaut: 0.0)
            -0.5 = 50% en dessous de lower (agressif)
             0.0 = Exactement sur lower_band (défaut)
            +0.2 = 20% du chemin lower→upper (prudent)

        entry_pct_short: Position d'entrée SHORT sur échelle (défaut: 1.0)
             0.8 = 80% du chemin (entre middle et upper, prudent)
             1.0 = Exactement sur upper_band (défaut)
             1.5 = 50% au-dessus de upper (agressif)

        stop_factor: Distance stop-loss depuis entrée (défaut: 0.5)
             0.1 = Stop proche (10% de distance totale)
             0.5 = Stop moyen (50% de distance totale)
             1.0 = Stop loin (100% de distance totale)

        tp_factor: Distance take-profit depuis entrée (défaut: 0.7)
             0.2 = TP proche (20% de distance totale)
             0.7 = TP moyen (70% de distance totale)
             1.5 = TP loin (150% de distance totale)

        leverage: Levier de trading (défaut: 3)

    Formules:
        entry_level = lower_band + entry_pct × (upper_band - lower_band)

        LONG:
            stop = entry_price - stop_factor × (upper_band - lower_band)
            tp   = entry_price + tp_factor × (upper_band - lower_band)

        SHORT:
            stop = entry_price + stop_factor × (upper_band - lower_band)
            tp   = entry_price - tp_factor × (upper_band - lower_band)

    Signaux:
        +1 (Long): close <= entry_level_long ET ATR > seuil
        -1 (Short): close >= entry_level_short ET ATR > seuil
        0: Sinon
    """

    def __init__(self):
        super().__init__(name="BollingerATR_V3")

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
            # Entry levels (échelle unifiée)
            "entry_pct_long": 0.0,   # 0% = sur lower_band
            "entry_pct_short": 1.0,  # 100% = sur upper_band
            # Stop-loss et Take-profit
            "stop_factor": 0.5,      # 50% de la distance totale
            "tp_factor": 0.7,        # 70% de la distance totale
            # Trading
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
                min_val=0.5, max_val=5.0, step=0.25, default=2.0,  # Élargi: 0.5-5.0 pour bandes très serrées à ultra larges
                param_type="float",
                description="Amplitude Bollinger (écarts-types) 0.5σ → 5σ"
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
            "entry_pct_long": ParameterSpec(
                name="entry_pct_long",
                min_val=-1.0, max_val=0.5, step=0.05, default=0.0,  # Élargi: -1.0→+0.5 pour très sous lower à milieu bandes
                param_type="float",
                description="Entrée LONG: -100% (très agressif) → +50% (milieu bande)"
            ),
            "entry_pct_short": ParameterSpec(
                name="entry_pct_short",
                min_val=0.5, max_val=2.0, step=0.05, default=1.0,  # Élargi: 0.5→2.0 pour milieu à très au-dessus upper
                param_type="float",
                description="Entrée SHORT: +50% (milieu) → +200% (très au-dessus)"
            ),
            "stop_factor": ParameterSpec(
                name="stop_factor",
                min_val=0.05, max_val=1.5, step=0.05, default=0.5,  # Élargi: 0.05-1.5 pour stops ultra serrés à très larges
                param_type="float",
                description="Stop-loss: 5% (ultra proche) → 150% (très loin)"
            ),
            "tp_factor": ParameterSpec(
                name="tp_factor",
                min_val=0.1, max_val=2.0, step=0.1, default=0.7,  # Élargi: 0.1-2.0 pour TP très proche à très loin
                param_type="float",
                description="Take-profit: 10% (très proche) → 200% (très loin)"
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
        Génère les signaux de trading Bollinger + ATR V3.

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

        # === Calcul des niveaux d'entrée sur échelle unifiée ===
        # Échelle: 0% = lower, 50% = middle, 100% = upper
        entry_pct_long = float(params.get("entry_pct_long", 0.0))
        entry_pct_short = float(params.get("entry_pct_short", 1.0))

        total_distance = upper - lower

        # LONG: entry_level = lower + entry_pct_long × (upper - lower)
        entry_level_long = lower + entry_pct_long * total_distance

        # SHORT: entry_level = lower + entry_pct_short × (upper - lower)
        entry_level_short = lower + entry_pct_short * total_distance

        # === Signaux basés sur les niveaux d'entrée calculés ===
        # Long: prix <= niveau d'entrée long (oversold)
        long_condition = close <= entry_level_long

        # Short: prix >= niveau d'entrée short (overbought)
        short_condition = close >= entry_level_short

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

        # === Calculer les niveaux de take-profit et stop-loss ===
        # Ces valeurs seront appliquées au moment de l'entrée réelle
        stop_factor = float(params.get("stop_factor", 0.5))
        tp_factor = float(params.get("tp_factor", 0.7))

        # LONG: stop en dessous, tp au-dessus
        # Note: Ces calculs sont préliminaires, les vrais niveaux seront
        # calculés depuis entry_price dans le simulateur
        stop_distance = stop_factor * total_distance
        tp_distance = tp_factor * total_distance

        # Stocker pour analyse (basé sur close comme approximation)
        df.loc[:, 'stop_long_approx'] = close - stop_distance
        df.loc[:, 'tp_long_approx'] = close + tp_distance
        df.loc[:, 'stop_short_approx'] = close + stop_distance
        df.loc[:, 'tp_short_approx'] = close - tp_distance

        # === Stocker les niveaux et distances pour analyse ===
        df.loc[:, 'entry_level_long'] = entry_level_long
        df.loc[:, 'entry_level_short'] = entry_level_short
        df.loc[:, 'bb_total_distance'] = total_distance
        df.loc[:, 'bb_stop_factor'] = stop_factor
        df.loc[:, 'bb_tp_factor'] = tp_factor
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

        # Distance du stop (estimation basée sur ATR × stop_factor)
        stop_factor = params.get("stop_factor", 0.5)
        # Approximation: on utilise ATR × 2 comme proxy de (upper - lower)
        bb_distance_estimate = atr_value * 2.0
        stop_distance = stop_factor * bb_distance_estimate

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
        Calcule le niveau de stop-loss DEPUIS LE PRIX D'ENTRÉE.

        Logique V3:
        - Distance de référence = upper_band - lower_band
        - LONG:  stop = entry_price - stop_factor × (upper - lower)
        - SHORT: stop = entry_price + stop_factor × (upper - lower)

        Args:
            entry_price: Prix d'entrée RÉEL
            atr_value: Valeur ATR (fallback uniquement)
            side: "long" ou "short"
            params: Paramètres (contient stop_factor)
            bb_middle: Bande de Bollinger médiane (au moment de l'entrée)
            bb_upper: Bande de Bollinger supérieure (au moment de l'entrée)
            bb_lower: Bande de Bollinger inférieure (au moment de l'entrée)

        Returns:
            Prix du stop-loss
        """
        # Récupérer le facteur paramétrable
        stop_factor = float(params.get("stop_factor", 0.5))

        # Si les bandes de Bollinger sont fournies, calculer depuis entry_price
        if bb_middle is not None and bb_upper is not None and bb_lower is not None:
            total_distance = bb_upper - bb_lower

            if side == "long":
                # Stop LONG: entry_price - stop_factor × (upper - lower)
                return entry_price - stop_factor * total_distance
            else:  # SHORT
                # Stop SHORT: entry_price + stop_factor × (upper - lower)
                return entry_price + stop_factor * total_distance
        else:
            # Fallback: approximation basée sur ATR
            # Approximation: (upper - lower) ≈ ATR × 2
            bb_distance_estimate = atr_value * 2.0
            distance = stop_factor * bb_distance_estimate

            if side == "long":
                return entry_price - distance
            else:
                return entry_price + distance


__all__ = ["BollingerATRStrategyV3"]
