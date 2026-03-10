"""
Module-ID: indicators.atr

Purpose: Indicateur volatilité ATR (Average True Range) vectorisé.

Role in pipeline: data

Key components: atr, ATRSettings, calculate_atr, true_range

Inputs: DataFrame avec high, low, close; period, method (SMA/EMA)

Outputs: np.ndarray (volatilité ATR) ou Dict avec TR

Dependencies: pandas, numpy, dataclasses

Conventions: True Range normalisé; ATR lissé par SMA ou EMA; vectorisé NumPy.

Read-if: Modification formula true range, smoothing method.

Skip-if: Vous utilisez juste calculate_indicator('atr').
"""

from dataclasses import dataclass
from typing import Literal, Union

import numpy as np
import pandas as pd


@dataclass
class ATRSettings:
    """Configuration de l'ATR."""

    period: int = 14
    method: Literal["ema", "sma"] = "ema"

    def __post_init__(self):
        if self.period < 1:
            raise ValueError(f"period doit être >= 1, reçu: {self.period}")
        if self.method not in ("ema", "sma"):
            raise ValueError(f"method doit être 'ema' ou 'sma', reçu: {self.method}")


def true_range(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray]
) -> np.ndarray:
    """
    Calcule le True Range pour chaque barre.

    TR = max(high-low, abs(high-prev_close), abs(low-prev_close))

    Args:
        high: Prix hauts
        low: Prix bas
        close: Prix de clôture

    Returns:
        Array du True Range (première valeur = high - low)
    """
    # Convertir en arrays numpy
    if isinstance(high, pd.Series):
        high = high.values
    if isinstance(low, pd.Series):
        low = low.values
    if isinstance(close, pd.Series):
        close = close.values

    high = np.asarray(high, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    close = np.asarray(close, dtype=np.float64)

    n = len(close)
    tr = np.zeros(n, dtype=np.float64)

    # Première valeur = high - low
    tr[0] = high[0] - low[0]

    # Calcul vectorisé pour le reste
    prev_close = close[:-1]
    hl = high[1:] - low[1:]
    hpc = np.abs(high[1:] - prev_close)
    lpc = np.abs(low[1:] - prev_close)

    tr[1:] = np.maximum(hl, np.maximum(hpc, lpc))

    return tr


def atr(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int = 14,
    method: Literal["ema", "sma"] = "ema",
    settings: ATRSettings = None
) -> np.ndarray:
    """
    Calcule l'Average True Range.

    Args:
        high: Prix hauts
        low: Prix bas
        close: Prix de clôture
        period: Période de lissage (défaut: 14)
        method: Méthode de lissage 'ema' ou 'sma' (défaut: 'ema')
        settings: Configuration alternative

    Returns:
        Array ATR de même longueur que les entrées.
        Les premières (period-1) valeurs seront NaN pour SMA,
        ou valeurs progressives pour EMA.
    """
    # Utiliser settings si fourni
    if settings is not None:
        period = settings.period
        method = settings.method

    # Calculer True Range
    tr = true_range(high, low, close)
    period = int(period)  # Assurer que period est un entier
    n = len(tr)

    if n < period:
        raise ValueError(f"Données insuffisantes: {n} < period={period}")

    # Lissage selon méthode
    if method == "sma":
        # SMA simple
        tr_series = pd.Series(tr)
        atr_values = tr_series.rolling(window=period, min_periods=period).mean()
        return atr_values.values

    else:  # EMA (méthode Wilder)
        atr_values = np.zeros(n, dtype=np.float64)
        atr_values[:period] = np.nan

        # Première ATR = SMA des premières périodes
        atr_values[period - 1] = np.mean(tr[:period])

        # EMA avec alpha = 1/period (méthode Wilder)
        alpha = 1.0 / period

        for i in range(period, n):
            atr_values[i] = alpha * tr[i] + (1 - alpha) * atr_values[i - 1]

        return atr_values


def atr_percent(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int = 14
) -> np.ndarray:
    """
    Calcule l'ATR en pourcentage du prix.

    Formule: ATR / Close * 100

    Utile pour comparer la volatilité entre actifs à prix différents.
    """
    if isinstance(close, pd.Series):
        close = close.values
    close = np.asarray(close, dtype=np.float64)

    atr_values = atr(high, low, close, period)

    # Éviter division par zéro
    atr_pct = np.where(close != 0, atr_values / close * 100, 0.0)

    return atr_pct


def calculate_stop_loss(
    entry_price: float,
    atr_value: float,
    multiplier: float = 1.5,
    side: Literal["long", "short"] = "long"
) -> float:
    """
    Calcule un niveau de stop-loss basé sur l'ATR.

    Args:
        entry_price: Prix d'entrée
        atr_value: Valeur ATR actuelle
        multiplier: Multiplicateur ATR (défaut: 1.5)
        side: Direction du trade ('long' ou 'short')

    Returns:
        Prix du stop-loss
    """
    distance = atr_value * multiplier

    if side == "long":
        return entry_price - distance
    else:
        return entry_price + distance


__all__ = ["atr", "ATRSettings", "true_range", "atr_percent", "calculate_stop_loss"]
