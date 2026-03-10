"""
Module-ID: indicators.stoch_rsi

Purpose: Indicateur Stochastic RSI - stochastique appliqué à RSI.

Role in pipeline: data

Key components: stochastic_rsi, calculate_stoch_rsi, %K, %D, signal

Inputs: DataFrame avec close; rsi_period, stoch_period, k_smooth, d_smooth

Outputs: Dict{k, d, signal} ou Tuple

Dependencies: pandas, numpy, rsi

Conventions: RSI lissé, puis stochastique appliquée; sensibilité augmentée surachat/survente.

Read-if: Modification périodes RSI/Stoch, lissages K/D.

Skip-if: Vous utilisez juste calculate_indicator('stoch_rsi').
"""

from typing import Dict, Tuple

import numpy as np
import pandas as pd

from indicators.registry import register_indicator
from indicators.rsi import rsi


def stochastic_rsi(
    close: pd.Series,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Calcule le Stochastic RSI (%K et %D).

    Formule:
    1. Calculer le RSI
    2. Appliquer la formule stochastique au RSI:
       StochRSI = (RSI - RSI_min) / (RSI_max - RSI_min)
    3. Lisser avec SMA pour obtenir %K et %D

    Args:
        close: Série des prix de clôture
        rsi_period: Période du RSI (défaut: 14)
        stoch_period: Période du stochastique (défaut: 14)
        k_smooth: Période de lissage %K (défaut: 3)
        d_smooth: Période de lissage %D (défaut: 3)

    Returns:
        Tuple (%K, %D) - valeurs entre 0 et 100
    """
    # Calculer le RSI
    rsi_values = rsi(close, period=rsi_period)

    n = len(rsi_values)
    stoch_rsi = np.full(n, np.nan)

    # Appliquer la formule stochastique au RSI
    for i in range(stoch_period - 1, n):
        window = rsi_values[i - stoch_period + 1:i + 1]
        valid = window[~np.isnan(window)]

        if len(valid) < 2:
            continue

        rsi_min = np.min(valid)
        rsi_max = np.max(valid)

        if rsi_max - rsi_min > 0:
            stoch_rsi[i] = (rsi_values[i] - rsi_min) / (rsi_max - rsi_min) * 100
        else:
            stoch_rsi[i] = 50  # Neutre si pas de variation

    # Calculer %K (SMA du StochRSI)
    k_line = np.full(n, np.nan)
    for i in range(k_smooth - 1, n):
        window = stoch_rsi[i - k_smooth + 1:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) > 0:
            k_line[i] = np.mean(valid)

    # Calculer %D (SMA de %K)
    d_line = np.full(n, np.nan)
    for i in range(d_smooth - 1, n):
        window = k_line[i - d_smooth + 1:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) > 0:
            d_line[i] = np.mean(valid)

    return k_line, d_line


def stoch_rsi_signal(
    close: pd.Series,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
    oversold: float = 20,
    overbought: float = 80
) -> np.ndarray:
    """
    Génère des signaux de trading basés sur le Stochastic RSI.

    Signaux:
    - Long (1): %K croise %D vers le haut depuis zone de survente (<20)
    - Short (-1): %K croise %D vers le bas depuis zone de surachat (>80)
    - Neutre (0): Autres cas

    Args:
        close: Série des prix de clôture
        rsi_period: Période du RSI
        stoch_period: Période du stochastique
        k_smooth: Période de lissage %K
        d_smooth: Période de lissage %D
        oversold: Seuil de survente (défaut: 20)
        overbought: Seuil de surachat (défaut: 80)

    Returns:
        Array de signaux (-1, 0, 1)
    """
    k_line, d_line = stochastic_rsi(close, rsi_period, stoch_period, k_smooth, d_smooth)

    n = len(close)
    signals = np.zeros(n)

    for i in range(1, n):
        if np.isnan(k_line[i]) or np.isnan(d_line[i]):
            continue
        if np.isnan(k_line[i-1]) or np.isnan(d_line[i-1]):
            continue

        # Croisement haussier depuis zone de survente
        if k_line[i-1] <= d_line[i-1] and k_line[i] > d_line[i]:
            if k_line[i-1] < oversold or d_line[i-1] < oversold:
                signals[i] = 1

        # Croisement baissier depuis zone de surachat
        elif k_line[i-1] >= d_line[i-1] and k_line[i] < d_line[i]:
            if k_line[i-1] > overbought or d_line[i-1] > overbought:
                signals[i] = -1

    return signals


def stoch_rsi_divergence(
    close: pd.Series,
    k_line: np.ndarray,
    lookback: int = 14
) -> np.ndarray:
    """
    Détecte les divergences entre le prix et le Stochastic RSI.

    Args:
        close: Série des prix de clôture
        k_line: Valeurs %K du Stochastic RSI
        lookback: Période de recherche (défaut: 14)

    Returns:
        1 = divergence haussière, -1 = divergence baissière, 0 = pas de divergence
    """
    close_arr = np.asarray(close, dtype=np.float64)
    n = len(close_arr)

    divergence = np.zeros(n)

    for i in range(lookback, n):
        price_window = close_arr[i - lookback:i + 1]
        stoch_window = k_line[i - lookback:i + 1]

        valid_mask = ~np.isnan(stoch_window)
        if np.sum(valid_mask) < lookback // 2:
            continue

        # Trouver les min/max locaux
        price_min_idx = np.nanargmin(price_window)
        price_max_idx = np.nanargmax(price_window)
        np.nanargmin(stoch_window)
        np.nanargmax(stoch_window)

        # Divergence haussière: prix fait un plus bas, mais StochRSI fait un plus haut
        if price_min_idx > lookback // 2:  # Récent creux de prix
            if stoch_window[price_min_idx] > stoch_window[0]:
                divergence[i] = 1

        # Divergence baissière: prix fait un plus haut, mais StochRSI fait un plus bas
        if price_max_idx > lookback // 2:  # Récent pic de prix
            if stoch_window[price_max_idx] < stoch_window[0]:
                divergence[i] = -1

    return divergence


def calculate_stoch_rsi(df: pd.DataFrame, **params) -> Dict[str, np.ndarray]:
    """
    Fonction wrapper pour le registre d'indicateurs.

    Args:
        df: DataFrame avec colonne close
        **params: Paramètres clé-valeur
            - rsi_period: Période du RSI (défaut: 14)
            - stoch_period: Période du stochastique (défaut: 14)
            - k_smooth: Lissage %K (défaut: 3)
            - d_smooth: Lissage %D (défaut: 3)
            - oversold: Seuil survente (défaut: 20)
            - overbought: Seuil surachat (défaut: 80)

    Returns:
        Dict avec k, d, signal
    """
    rsi_period = params.get("rsi_period", 14)
    stoch_period = params.get("stoch_period", 14)
    k_smooth = params.get("k_smooth", 3)
    d_smooth = params.get("d_smooth", 3)
    oversold = params.get("oversold", 20)
    overbought = params.get("overbought", 80)

    k_line, d_line = stochastic_rsi(
        df["close"], rsi_period, stoch_period, k_smooth, d_smooth
    )

    signal = stoch_rsi_signal(
        df["close"], rsi_period, stoch_period, k_smooth, d_smooth,
        oversold, overbought
    )

    return {
        "k": k_line,
        "d": d_line,
        "signal": signal
    }


# Enregistrement dans le registre
register_indicator(
    "stoch_rsi",
    calculate_stoch_rsi,
    required_columns=("close",),
    description="Stochastic RSI - RSI avec oscillateur stochastique"
)


__all__ = [
    "stochastic_rsi",
    "stoch_rsi_signal",
    "stoch_rsi_divergence",
    "calculate_stoch_rsi",
]
