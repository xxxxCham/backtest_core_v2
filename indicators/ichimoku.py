"""
Module-ID: indicators.ichimoku

Purpose: Indicateur Ichimoku Cloud - système complet japonais (5 lignes).

Role in pipeline: data

Key components: ichimoku, calculate_ichimoku, Tenkan, Kijun, Senkou A/B, Chikou

Inputs: DataFrame avec high, low, close; périodes standards (9, 26, 52, 26)

Outputs: Dict{tenkan, kijun, senkou_a, senkou_b, chikou, cloud_position}

Dependencies: pandas, numpy

Conventions: Cloud = Senkou A/B; Tenkan croise Kijun = signal; Chikou retardé 26 jours.

Read-if: Modification périodes, output format.

Skip-if: Vous utilisez juste calculate_indicator('ichimoku').
"""

from typing import Dict, Tuple

import numpy as np
import pandas as pd

from indicators.registry import register_indicator


def tenkan_sen(high: pd.Series, low: pd.Series, period: int = 9) -> np.ndarray:
    """
    Calcule le Tenkan-sen (Conversion Line).

    Formule: (Plus haut sur N périodes + Plus bas sur N périodes) / 2

    Args:
        high: Série des prix hauts
        low: Série des prix bas
        period: Période de calcul (défaut: 9)

    Returns:
        Array du Tenkan-sen
    """
    high_arr = np.asarray(high, dtype=np.float64)
    low_arr = np.asarray(low, dtype=np.float64)
    n = len(high_arr)

    result = np.full(n, np.nan)

    for i in range(period - 1, n):
        highest = np.max(high_arr[i - period + 1:i + 1])
        lowest = np.min(low_arr[i - period + 1:i + 1])
        result[i] = (highest + lowest) / 2

    return result


def kijun_sen(high: pd.Series, low: pd.Series, period: int = 26) -> np.ndarray:
    """
    Calcule le Kijun-sen (Base Line).

    Formule: (Plus haut sur N périodes + Plus bas sur N périodes) / 2

    Args:
        high: Série des prix hauts
        low: Série des prix bas
        period: Période de calcul (défaut: 26)

    Returns:
        Array du Kijun-sen
    """
    # Même formule que Tenkan-sen mais période différente
    return tenkan_sen(high, low, period)


def senkou_span_a(
    tenkan: np.ndarray,
    kijun: np.ndarray,
    displacement: int = 26
) -> np.ndarray:
    """
    Calcule le Senkou Span A (Leading Span A).

    Formule: (Tenkan-sen + Kijun-sen) / 2, décalé de N périodes dans le futur

    Args:
        tenkan: Array du Tenkan-sen
        kijun: Array du Kijun-sen
        displacement: Décalage vers le futur (défaut: 26)

    Returns:
        Array du Senkou Span A
    """
    n = len(tenkan)
    span_a = (tenkan + kijun) / 2

    # Décaler vers le futur (ajouter des NaN au début, tronquer la fin)
    result = np.full(n, np.nan)
    if displacement < n:
        result[displacement:] = span_a[:-displacement]

    return result


def senkou_span_b(
    high: pd.Series,
    low: pd.Series,
    period: int = 52,
    displacement: int = 26
) -> np.ndarray:
    """
    Calcule le Senkou Span B (Leading Span B).

    Formule: (Plus haut sur N périodes + Plus bas sur N périodes) / 2,
             décalé de M périodes dans le futur

    Args:
        high: Série des prix hauts
        low: Série des prix bas
        period: Période de calcul (défaut: 52)
        displacement: Décalage vers le futur (défaut: 26)

    Returns:
        Array du Senkou Span B
    """
    # Calculer la ligne de base sur 52 périodes
    span_b_raw = tenkan_sen(high, low, period)

    n = len(span_b_raw)
    result = np.full(n, np.nan)

    # Décaler vers le futur
    if displacement < n:
        result[displacement:] = span_b_raw[:-displacement]

    return result


def chikou_span(close: pd.Series, displacement: int = 26) -> np.ndarray:
    """
    Calcule le Chikou Span (Lagging Span).

    Formule: Prix de clôture actuel tracé N périodes dans le passé

    Args:
        close: Série des prix de clôture
        displacement: Décalage vers le passé (défaut: 26)

    Returns:
        Array du Chikou Span
    """
    close_arr = np.asarray(close, dtype=np.float64)
    n = len(close_arr)

    result = np.full(n, np.nan)

    # Décaler vers le passé (prix actuel affiché 26 périodes en arrière)
    if displacement < n:
        result[:-displacement] = close_arr[displacement:]

    return result


def ichimoku(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    displacement: int = 26
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Calcule tous les composants de l'Ichimoku Cloud.

    Args:
        high: Série des prix hauts
        low: Série des prix bas
        close: Série des prix de clôture
        tenkan_period: Période du Tenkan-sen (défaut: 9)
        kijun_period: Période du Kijun-sen (défaut: 26)
        senkou_b_period: Période du Senkou Span B (défaut: 52)
        displacement: Décalage pour Senkou et Chikou (défaut: 26)

    Returns:
        Tuple (tenkan, kijun, senkou_a, senkou_b, chikou)
    """
    # Calculer les lignes de base
    tenkan = tenkan_sen(high, low, tenkan_period)
    kijun = kijun_sen(high, low, kijun_period)

    # Calculer le cloud (Kumo)
    senkou_a = senkou_span_a(tenkan, kijun, displacement)
    senkou_b = senkou_span_b(high, low, senkou_b_period, displacement)

    # Calculer le Chikou
    chikou = chikou_span(close, displacement)

    return tenkan, kijun, senkou_a, senkou_b, chikou


def ichimoku_cloud_position(
    close: pd.Series,
    senkou_a: np.ndarray,
    senkou_b: np.ndarray
) -> np.ndarray:
    """
    Détermine la position du prix par rapport au cloud.

    Returns:
        1 = au-dessus du cloud (bullish)
        -1 = en-dessous du cloud (bearish)
        0 = dans le cloud (neutre)
    """
    close_arr = np.asarray(close, dtype=np.float64)
    n = len(close_arr)

    result = np.zeros(n)

    cloud_top = np.maximum(senkou_a, senkou_b)
    cloud_bottom = np.minimum(senkou_a, senkou_b)

    # Au-dessus du cloud
    result[close_arr > cloud_top] = 1
    # En-dessous du cloud
    result[close_arr < cloud_bottom] = -1
    # Dans le cloud = 0 (déjà initialisé)

    # Gérer les NaN
    nan_mask = np.isnan(senkou_a) | np.isnan(senkou_b)
    result[nan_mask] = np.nan

    return result


def ichimoku_signal(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    displacement: int = 26
) -> np.ndarray:
    """
    Génère des signaux de trading basés sur l'Ichimoku.

    Signaux:
    - Long (1): Tenkan croise Kijun vers le haut ET prix au-dessus du cloud
    - Short (-1): Tenkan croise Kijun vers le bas ET prix en-dessous du cloud
    - Neutre (0): Autres cas

    Args:
        high, low, close: Séries de prix OHLC
        tenkan_period: Période Tenkan (défaut: 9)
        kijun_period: Période Kijun (défaut: 26)
        senkou_b_period: Période Senkou B (défaut: 52)
        displacement: Décalage (défaut: 26)

    Returns:
        Array de signaux (-1, 0, 1)
    """
    tenkan, kijun, senkou_a, senkou_b, chikou = ichimoku(
        high, low, close,
        tenkan_period, kijun_period, senkou_b_period, displacement
    )

    n = len(close)
    signals = np.zeros(n)

    # Position par rapport au cloud
    cloud_pos = ichimoku_cloud_position(close, senkou_a, senkou_b)

    # Croisements Tenkan/Kijun
    for i in range(1, n):
        if np.isnan(tenkan[i]) or np.isnan(kijun[i]):
            continue
        if np.isnan(tenkan[i-1]) or np.isnan(kijun[i-1]):
            continue

        # Croisement haussier: Tenkan passe au-dessus de Kijun
        if tenkan[i-1] <= kijun[i-1] and tenkan[i] > kijun[i]:
            if cloud_pos[i] == 1:  # Au-dessus du cloud
                signals[i] = 1

        # Croisement baissier: Tenkan passe en-dessous de Kijun
        elif tenkan[i-1] >= kijun[i-1] and tenkan[i] < kijun[i]:
            if cloud_pos[i] == -1:  # En-dessous du cloud
                signals[i] = -1

    return signals


def calculate_ichimoku(df: pd.DataFrame, **params) -> Dict[str, np.ndarray]:
    """
    Fonction wrapper pour le registre d'indicateurs.

    Args:
        df: DataFrame avec colonnes high, low, close
        **params: Paramètres clé-valeur
            - tenkan_period: Période Tenkan (défaut: 9)
            - kijun_period: Période Kijun (défaut: 26)
            - senkou_b_period: Période Senkou B (défaut: 52)
            - displacement: Décalage (défaut: 26)

    Returns:
        Dict avec tenkan, kijun, senkou_a, senkou_b, chikou, cloud_position
    """
    tenkan_period = params.get("tenkan_period", 9)
    kijun_period = params.get("kijun_period", 26)
    senkou_b_period = params.get("senkou_b_period", 52)
    displacement = params.get("displacement", 26)

    tenkan_arr, kijun_arr, senkou_a, senkou_b, chikou = ichimoku(
        df["high"], df["low"], df["close"],
        tenkan_period, kijun_period, senkou_b_period, displacement
    )

    cloud_pos = ichimoku_cloud_position(df["close"], senkou_a, senkou_b)

    return {
        "tenkan": tenkan_arr,
        "kijun": kijun_arr,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b,
        "chikou": chikou,
        "cloud_position": cloud_pos
    }


# Enregistrement dans le registre
register_indicator(
    "ichimoku",
    calculate_ichimoku,
    required_columns=("high", "low", "close"),
    description="Ichimoku Kinko Hyo - Système d'analyse technique japonais"
)


__all__ = [
    "ichimoku",
    "tenkan_sen",
    "kijun_sen",
    "senkou_span_a",
    "senkou_span_b",
    "chikou_span",
    "ichimoku_cloud_position",
    "ichimoku_signal",
    "calculate_ichimoku",
]
