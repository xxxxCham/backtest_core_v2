"""
Module-ID: indicators.bollinger

Purpose: Indicateur Bandes de Bollinger (volatilité + centre) vectorisé.

Role in pipeline: data

Key components: bollinger_bands, BollingerSettings, calculate_bollinger

Inputs: DataFrame avec close; window, std_dev (nombre d'écarts-types)

Outputs: Dict{upper, middle, lower} ou Tuple

Dependencies: pandas, numpy, dataclasses

Conventions: middle = SMA; upper/lower = +/- std_dev * volatilité; vectorisé.

Read-if: Modification period, nombre écarts-types, ou output format.

Skip-if: Vous utilisez juste calculate_indicator('bollinger').
"""

from dataclasses import dataclass
from typing import Tuple, Union

import numpy as np
import pandas as pd


@dataclass
class BollingerSettings:
    """Configuration des Bandes de Bollinger."""

    period: int = 20
    std_dev: float = 2.0

    def __post_init__(self):
        if self.period < 2:
            raise ValueError(f"period doit être >= 2, reçu: {self.period}")
        if self.std_dev <= 0:
            raise ValueError(f"std_dev doit être > 0, reçu: {self.std_dev}")


def bollinger_bands(
    close: Union[pd.Series, np.ndarray],
    period: int = 20,
    std_dev: float = 2.0,
    settings: BollingerSettings = None
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Calcule les Bandes de Bollinger.

    Args:
        close: Prix de clôture
        period: Période de la SMA (défaut: 20)
        std_dev: Multiplicateur d'écart-type (défaut: 2.0)
        settings: Configuration alternative (surcharge period/std_dev)

    Returns:
        Tuple (upper_band, middle_band, lower_band) - np.ndarray de même longueur que close
        Les premières (period-1) valeurs seront NaN.
    """
    # Utiliser settings si fourni
    if settings is not None:
        period = settings.period
        std_dev = settings.std_dev

    # Convertir en array numpy
    if isinstance(close, pd.Series):
        close = close.values
    close = np.asarray(close, dtype=np.float64)
    period = int(period)  # Assurer que period est un entier

    n = len(close)
    if n < period:
        raise ValueError(f"Données insuffisantes: {n} < period={period}")

    # Calcul vectorisé avec rolling (utilise pandas pour efficacité)
    close_series = pd.Series(close)

    # Middle band = SMA
    middle = close_series.rolling(window=period, min_periods=period).mean()

    # Écart-type rolling
    std = close_series.rolling(window=period, min_periods=period).std(ddof=0)

    # Bandes supérieure et inférieure
    upper = middle + (std_dev * std)
    lower = middle - (std_dev * std)

    return upper.values, middle.values, lower.values


def bollinger_bandwidth(
    close: Union[pd.Series, np.ndarray],
    period: int = 20,
    std_dev: float = 2.0
) -> np.ndarray:
    """
    Calcule le Bollinger Bandwidth (largeur relative des bandes).

    Formule: (Upper - Lower) / Middle * 100

    Utile pour détecter les compressions (squeeze) avant mouvement.
    """
    upper, middle, lower = bollinger_bands(close, period, std_dev)

    # Éviter division par zéro
    bandwidth = np.where(
        middle != 0,
        (upper - lower) / middle * 100,
        0.0
    )

    return bandwidth


def bollinger_percent_b(
    close: Union[pd.Series, np.ndarray],
    period: int = 20,
    std_dev: float = 2.0
) -> np.ndarray:
    """
    Calcule le %B (position du prix dans les bandes).

    Formule: (Price - Lower) / (Upper - Lower)

    - %B > 1: Au-dessus de la bande supérieure (surachat)
    - %B < 0: En dessous de la bande inférieure (survente)
    - %B = 0.5: Au milieu (sur la SMA)
    """
    if isinstance(close, pd.Series):
        close = close.values
    close = np.asarray(close, dtype=np.float64)

    upper, middle, lower = bollinger_bands(close, period, std_dev)

    band_width = upper - lower

    # Éviter division par zéro
    percent_b = np.where(
        band_width != 0,
        (close - lower) / band_width,
        0.5
    )

    return percent_b


__all__ = ["bollinger_bands", "BollingerSettings", "bollinger_bandwidth", "bollinger_percent_b"]
