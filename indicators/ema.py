"""
Module-ID: indicators.ema

Purpose: Indicateurs EMA (exponentielles) et SMA (simples) vectorisés.

Role in pipeline: data

Key components: ema, sma, EMASettings, calculate_ema

Inputs: DataFrame avec close; period

Outputs: np.ndarray (moyennes mobiles)

Dependencies: pandas, numpy, dataclasses

Conventions: Vectorisé NumPy; SMA simple, EMA avec alpha=2/(n+1); NaN au début.

Read-if: Modification période, gestion NaN.

Skip-if: Vous utilisez juste calculate_indicator('ema').
"""

from dataclasses import dataclass
from typing import Union

import numpy as np
import pandas as pd


@dataclass
class EMASettings:
    """Configuration des EMAs."""

    period: int = 20

    def __post_init__(self):
        if self.period < 1:
            raise ValueError(f"period doit être >= 1, reçu: {self.period}")


def sma(
    data: Union[pd.Series, np.ndarray],
    period: int = 20
) -> np.ndarray:
    """
    Calcule la Simple Moving Average.

    Args:
        data: Série de données (typiquement close)
        period: Période de la moyenne

    Returns:
        Array SMA de même longueur. Les premières (period-1) valeurs seront NaN.
    """
    if isinstance(data, pd.Series):
        data = data.values
    data = np.asarray(data, dtype=np.float64)
    period = int(period)  # Assurer que period est un entier

    if len(data) < period:
        # Retourner array de NaN au lieu d'erreur pour compatibilité
        return np.full(len(data), np.nan)

    # Utiliser pandas rolling pour efficacité
    data_series = pd.Series(data)
    sma_values = data_series.rolling(window=period, min_periods=period).mean()

    return sma_values.values


def ema(
    data: Union[pd.Series, np.ndarray],
    period: int = 20,
    adjust: bool = True,
    settings: EMASettings = None
) -> np.ndarray:
    """
    Calcule l'Exponential Moving Average.

    Args:
        data: Série de données
        period: Période de l'EMA
        adjust: Si True, utilise la formule ajustée (défaut pandas)
        settings: Configuration alternative

    Returns:
        Array EMA de même longueur.
    """
    if settings is not None:
        period = settings.period

    if isinstance(data, pd.Series):
        data = data.values
    data = np.asarray(data, dtype=np.float64)
    period = int(period)  # Assurer que period est un entier

    if len(data) < period:
        # Retourner array de NaN au lieu d'erreur pour compatibilité
        return np.full(len(data), np.nan)

    # Utiliser pandas ewm pour efficacité
    data_series = pd.Series(data)
    ema_values = data_series.ewm(span=period, adjust=adjust, min_periods=period).mean()

    return ema_values.values


def ema_crossover(
    data: Union[pd.Series, np.ndarray],
    fast_period: int = 12,
    slow_period: int = 26
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Calcule les EMAs rapide et lente avec détection de croisement.

    Args:
        data: Prix de clôture
        fast_period: Période de l'EMA rapide
        slow_period: Période de l'EMA lente

    Returns:
        Tuple (ema_fast, ema_slow, crossover_signal)
        crossover_signal: 1 = golden cross, -1 = death cross, 0 = pas de croisement
    """
    ema_fast = ema(data, fast_period)
    ema_slow = ema(data, slow_period)

    n = len(data)
    crossover = np.zeros(n, dtype=np.float64)

    # Détecter les croisements
    fast_above = ema_fast > ema_slow
    fast_above_prev = np.roll(fast_above, 1)
    fast_above_prev[0] = fast_above[0]

    # Golden cross: fast passe au-dessus de slow
    golden_cross = fast_above & ~fast_above_prev
    crossover[golden_cross] = 1.0

    # Death cross: fast passe en dessous de slow
    death_cross = ~fast_above & fast_above_prev
    crossover[death_cross] = -1.0

    return ema_fast, ema_slow, crossover


def dema(
    data: Union[pd.Series, np.ndarray],
    period: int = 20
) -> np.ndarray:
    """
    Calcule la Double EMA (DEMA).

    Formule: DEMA = 2 * EMA(data) - EMA(EMA(data))

    Plus réactive qu'une EMA simple avec moins de lag.
    """
    ema1 = ema(data, period)
    ema2 = ema(ema1, period)

    return 2 * ema1 - ema2


def tema(
    data: Union[pd.Series, np.ndarray],
    period: int = 20
) -> np.ndarray:
    """
    Calcule la Triple EMA (TEMA).

    Formule: TEMA = 3*EMA - 3*EMA(EMA) + EMA(EMA(EMA))

    Encore plus réactive que DEMA.
    """
    ema1 = ema(data, period)
    ema2 = ema(ema1, period)
    ema3 = ema(ema2, period)

    return 3 * ema1 - 3 * ema2 + ema3


__all__ = ["sma", "ema", "EMASettings", "ema_crossover", "dema", "tema"]
