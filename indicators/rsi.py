"""
Module-ID: indicators.rsi

Purpose: Indicateur RSI (Relative Strength Index) momentum vectorisé.

Role in pipeline: data

Key components: rsi, RSISettings, calculate_rsi

Inputs: DataFrame avec close; period (typique 14)

Outputs: np.ndarray (0-100 oscillateur)

Dependencies: pandas, numpy, dataclasses

Conventions: Valeurs 0-100; >70 surachat, <30 survente; RSI lissé.

Read-if: Modification période, lissage gains/pertes.

Skip-if: Vous utilisez juste calculate_indicator('rsi').
"""

from dataclasses import dataclass
from typing import Union

import numpy as np
import pandas as pd


@dataclass
class RSISettings:
    """Configuration du RSI."""

    period: int = 14
    overbought: float = 70.0
    oversold: float = 30.0

    def __post_init__(self):
        if self.period < 1:
            raise ValueError(f"period doit être >= 1, reçu: {self.period}")
        if not 0 <= self.oversold < self.overbought <= 100:
            raise ValueError(
                f"Niveaux invalides: oversold={self.oversold}, overbought={self.overbought}"
            )


def rsi(
    close: Union[pd.Series, np.ndarray],
    period: int = 14,
    settings: RSISettings = None
) -> np.ndarray:
    """
    Calcule le Relative Strength Index.

    Args:
        close: Prix de clôture
        period: Période du RSI (défaut: 14)
        settings: Configuration alternative

    Returns:
        Array RSI de valeurs entre 0 et 100.
        Les premières 'period' valeurs seront NaN.
    """
    # Utiliser settings si fourni
    if settings is not None:
        period = settings.period

    # Convertir en array numpy
    if isinstance(close, pd.Series):
        close = close.values
    close = np.asarray(close, dtype=np.float64)

    n = len(close)
    if n <= period:
        raise ValueError(f"Données insuffisantes: {n} <= period={period}")

    # Calcul des variations
    deltas = np.diff(close)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Initialiser les moyennes
    rsi_values = np.full(n, np.nan, dtype=np.float64)

    # Première moyenne (SMA sur la première fenêtre)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    # Première valeur RSI
    if avg_loss == 0:
        rsi_values[period] = 100.0 if avg_gain > 0 else 50.0
    else:
        rs = avg_gain / avg_loss
        rsi_values[period] = 100.0 - (100.0 / (1.0 + rs))

    # EMA pour le reste (méthode Wilder)
    alpha = 1.0 / period

    for i in range(period, n - 1):
        avg_gain = (1 - alpha) * avg_gain + alpha * gains[i]
        avg_loss = (1 - alpha) * avg_loss + alpha * losses[i]

        if avg_loss == 0:
            rsi_values[i + 1] = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi_values[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return rsi_values


def rsi_signal(
    close: Union[pd.Series, np.ndarray],
    period: int = 14,
    overbought: float = 70.0,
    oversold: float = 30.0
) -> np.ndarray:
    """
    Génère des signaux de trading basés sur le RSI.

    Args:
        close: Prix de clôture
        period: Période du RSI
        overbought: Niveau de surachat (défaut: 70)
        oversold: Niveau de survente (défaut: 30)

    Returns:
        Array de signaux: 1 (achat), -1 (vente), 0 (neutre)
    """
    rsi_values = rsi(close, period)

    signals = np.zeros(len(close), dtype=np.float64)

    # Signal d'achat: RSI < oversold
    signals[rsi_values < oversold] = 1.0

    # Signal de vente: RSI > overbought
    signals[rsi_values > overbought] = -1.0

    return signals


def rsi_divergence(
    close: Union[pd.Series, np.ndarray],
    period: int = 14,
    lookback: int = 14
) -> np.ndarray:
    """
    Détecte les divergences RSI/Prix.

    Retourne:
        1 = Divergence haussière (prix plus bas, RSI plus haut)
       -1 = Divergence baissière (prix plus haut, RSI plus bas)
        0 = Pas de divergence
    """
    if isinstance(close, pd.Series):
        close = close.values
    close = np.asarray(close, dtype=np.float64)

    rsi_values = rsi(close, period)
    n = len(close)

    divergence = np.zeros(n, dtype=np.float64)

    for i in range(period + lookback, n):
        price_change = close[i] - close[i - lookback]
        rsi_change = rsi_values[i] - rsi_values[i - lookback]

        # Divergence haussière
        if price_change < 0 and rsi_change > 0:
            divergence[i] = 1.0
        # Divergence baissière
        elif price_change > 0 and rsi_change < 0:
            divergence[i] = -1.0

    return divergence


__all__ = ["rsi", "RSISettings", "rsi_signal", "rsi_divergence"]
