"""
Module-ID: indicators.psar

Purpose: Indicateur Parabolic SAR - suivi tendance + stop-loss dynamique.

Role in pipeline: data

Key components: parabolic_sar, calculate_psar, SAR, trend, signal

Inputs: DataFrame avec high, low, close; iaf, maxaf, periods

Outputs: Dict{sar, trend, signal} ou Tuple

Dependencies: pandas, numpy

Conventions: SAR = point d'arrêt; accélération AF jusqu'à maxaf; trend 1/-1.

Read-if: Modification AF init/max, logique SAR update.

Skip-if: Vous utilisez juste calculate_indicator('psar').
"""

from typing import Dict, Tuple

import numpy as np
import pandas as pd

from indicators.registry import register_indicator


def parabolic_sar(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    af_start: float = 0.02,
    af_increment: float = 0.02,
    af_max: float = 0.20
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Calcule le Parabolic SAR.

    Args:
        high: Série des prix hauts
        low: Série des prix bas
        close: Série des prix de clôture
        af_start: Facteur d'accélération initial (défaut: 0.02)
        af_increment: Incrément du facteur d'accélération (défaut: 0.02)
        af_max: Facteur d'accélération maximum (défaut: 0.20)

    Returns:
        Tuple (sar_values, trend_direction)
        - sar_values: Array des valeurs SAR
        - trend_direction: 1 = haussier, -1 = baissier
    """
    high_arr = np.asarray(high, dtype=np.float64)
    low_arr = np.asarray(low, dtype=np.float64)
    close_arr = np.asarray(close, dtype=np.float64)
    n = len(high_arr)

    if n < 2:
        return np.full(n, np.nan), np.full(n, np.nan)

    # Initialisation
    sar = np.full(n, np.nan)
    trend = np.zeros(n)  # 1 = up, -1 = down

    # Déterminer la tendance initiale
    if close_arr[1] > close_arr[0]:
        trend[0] = 1  # Tendance haussière
        sar[0] = low_arr[0]
        ep = high_arr[0]  # Extreme Point
    else:
        trend[0] = -1  # Tendance baissière
        sar[0] = high_arr[0]
        ep = low_arr[0]

    af = af_start

    for i in range(1, n):
        # Calculer le SAR pour cette période
        if trend[i-1] == 1:  # Tendance haussière
            # SAR ne peut pas être au-dessus des deux derniers bas
            sar[i] = sar[i-1] + af * (ep - sar[i-1])
            sar[i] = min(sar[i], low_arr[i-1])
            if i >= 2:
                sar[i] = min(sar[i], low_arr[i-2])

            # Vérifier le retournement
            if low_arr[i] < sar[i]:
                # Retournement vers baissier
                trend[i] = -1
                sar[i] = ep  # Le nouveau SAR est l'ancien EP
                ep = low_arr[i]
                af = af_start
            else:
                trend[i] = 1
                # Mettre à jour EP si nouveau plus haut
                if high_arr[i] > ep:
                    ep = high_arr[i]
                    af = min(af + af_increment, af_max)

        else:  # Tendance baissière
            # SAR ne peut pas être en-dessous des deux derniers hauts
            sar[i] = sar[i-1] + af * (ep - sar[i-1])
            sar[i] = max(sar[i], high_arr[i-1])
            if i >= 2:
                sar[i] = max(sar[i], high_arr[i-2])

            # Vérifier le retournement
            if high_arr[i] > sar[i]:
                # Retournement vers haussier
                trend[i] = 1
                sar[i] = ep  # Le nouveau SAR est l'ancien EP
                ep = high_arr[i]
                af = af_start
            else:
                trend[i] = -1
                # Mettre à jour EP si nouveau plus bas
                if low_arr[i] < ep:
                    ep = low_arr[i]
                    af = min(af + af_increment, af_max)

    return sar, trend


def psar_signal(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    af_start: float = 0.02,
    af_increment: float = 0.02,
    af_max: float = 0.20
) -> np.ndarray:
    """
    Génère des signaux de trading basés sur le Parabolic SAR.

    Signaux:
    - Long (1): SAR passe en-dessous du prix (début tendance haussière)
    - Short (-1): SAR passe au-dessus du prix (début tendance baissière)
    - Neutre (0): Pas de changement

    Returns:
        Array de signaux (-1, 0, 1)
    """
    sar, trend = parabolic_sar(high, low, close, af_start, af_increment, af_max)

    n = len(close)
    signals = np.zeros(n)

    # Détecter les changements de tendance
    for i in range(1, n):
        if np.isnan(trend[i]) or np.isnan(trend[i-1]):
            continue

        # Passage de baissier à haussier
        if trend[i-1] == -1 and trend[i] == 1:
            signals[i] = 1

        # Passage de haussier à baissier
        elif trend[i-1] == 1 and trend[i] == -1:
            signals[i] = -1

    return signals


def psar_stop_loss(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    position: int,
    af_start: float = 0.02,
    af_increment: float = 0.02,
    af_max: float = 0.20
) -> np.ndarray:
    """
    Utilise le PSAR comme niveau de stop-loss dynamique.

    Args:
        high, low, close: Séries de prix
        position: Direction de la position (1 = long, -1 = short)
        af_start, af_increment, af_max: Paramètres PSAR

    Returns:
        Array des niveaux de stop-loss
    """
    sar, trend = parabolic_sar(high, low, close, af_start, af_increment, af_max)

    # Pour une position long, le stop est le SAR quand il est en dessous
    # Pour une position short, le stop est le SAR quand il est au-dessus
    if position == 1:
        # Stop pour position long: SAR en dessous du prix
        stop = np.where(trend == 1, sar, np.nan)
    else:
        # Stop pour position short: SAR au-dessus du prix
        stop = np.where(trend == -1, sar, np.nan)

    return stop


def calculate_psar(df: pd.DataFrame, **params) -> Dict[str, np.ndarray]:
    """
    Fonction wrapper pour le registre d'indicateurs.

    Args:
        df: DataFrame avec colonnes high, low, close
        **params: Paramètres clé-valeur
            - af_start: Facteur d'accélération initial (défaut: 0.02)
            - af_increment: Incrément AF (défaut: 0.02)
            - af_max: AF maximum (défaut: 0.20)

    Returns:
        Dict avec sar, trend, signal
    """
    af_start = params.get("af_start", 0.02)
    af_increment = params.get("af_increment", 0.02)
    af_max = params.get("af_max", 0.20)

    sar, trend = parabolic_sar(
        df["high"], df["low"], df["close"],
        af_start, af_increment, af_max
    )

    signal = psar_signal(
        df["high"], df["low"], df["close"],
        af_start, af_increment, af_max
    )

    return {
        "sar": sar,
        "trend": trend,
        "signal": signal
    }


# Enregistrement dans le registre
register_indicator(
    "psar",
    calculate_psar,
    required_columns=("high", "low", "close"),
    description="Parabolic SAR - Indicateur de suivi de tendance"
)


__all__ = [
    "parabolic_sar",
    "psar_signal",
    "psar_stop_loss",
    "calculate_psar",
]
