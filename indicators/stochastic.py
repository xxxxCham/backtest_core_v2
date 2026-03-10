"""
Module-ID: indicators.stochastic

Purpose: Indicateur Stochastic (%K + %D signal) - timing survente/surachat.

Role in pipeline: data

Key components: stochastic, StochasticSettings, calculate_stochastic, %K, %D

Inputs: DataFrame avec high, low, close; k_period, d_period

Outputs: Dict{stoch_k, stoch_d} ou Tuple

Dependencies: pandas, numpy, dataclasses

Conventions: %K position prix dans range; %D = SMA(%K); <20 survente, >80 surachat.

Read-if: Modification périodes K/D, formule %K.

Skip-if: Vous utilisez juste calculate_indicator('stochastic').
"""

from typing import Tuple, Union

import numpy as np
import pandas as pd


def stochastic(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    k_period: int = 14,
    d_period: int = 3,
    smooth_k: int = 3,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Calcule le Stochastic Oscillator.

    Formule:
        %K = 100 * (Close - Lowest Low) / (Highest High - Lowest Low)
        %K_smooth = SMA(%K, smooth_k)
        %D = SMA(%K_smooth, d_period)

    Args:
        high: Prix hauts
        low: Prix bas
        close: Prix de clôture
        k_period: Période pour highest high et lowest low (défaut: 14)
        d_period: Période pour la ligne %D (défaut: 3)
        smooth_k: Lissage de %K (défaut: 3)

    Returns:
        Tuple (stoch_k, stoch_d) en numpy arrays [0, 100]

    Example:
        >>> k, d = stochastic(df["high"], df["low"], df["close"])
        >>> oversold = k < 20
        >>> overbought = k > 80
    """
    # Convertir en arrays numpy
    if isinstance(high, pd.Series):
        high_vals = high.values
    else:
        high_vals = np.asarray(high)

    if isinstance(low, pd.Series):
        low_vals = low.values
    else:
        low_vals = np.asarray(low)

    if isinstance(close, pd.Series):
        close_vals = close.values
    else:
        close_vals = np.asarray(close)

    n = len(close_vals)

    # Calcul rolling highest high et lowest low
    highest_high = np.full(n, np.nan)
    lowest_low = np.full(n, np.nan)

    for i in range(k_period - 1, n):
        highest_high[i] = np.max(high_vals[i - k_period + 1:i + 1])
        lowest_low[i] = np.min(low_vals[i - k_period + 1:i + 1])

    # %K brut
    range_hl = highest_high - lowest_low
    range_hl = np.where(range_hl == 0, np.nan, range_hl)  # Éviter division par zéro

    stoch_k_raw = 100 * (close_vals - lowest_low) / range_hl

    # Lissage de %K (slow stochastic)
    if smooth_k > 1:
        stoch_k = _sma(stoch_k_raw, smooth_k)
    else:
        stoch_k = stoch_k_raw

    # %D = SMA de %K
    stoch_d = _sma(stoch_k, d_period)

    return stoch_k, stoch_d


def _sma(data: np.ndarray, period: int) -> np.ndarray:
    """Calcule une simple moving average."""
    n = len(data)
    result = np.full(n, np.nan)

    for i in range(period - 1, n):
        window = data[i - period + 1:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) > 0:
            result[i] = np.mean(valid)

    return result


def stochastic_signal(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    k_period: int = 14,
    d_period: int = 3,
    smooth_k: int = 3,
    oversold: float = 20.0,
    overbought: float = 80.0,
) -> np.ndarray:
    """
    Génère des signaux basés sur le Stochastic.

    Signaux:
        - +1: %K sort de zone survente (<oversold) et croise %D vers le haut
        - -1: %K sort de zone surachat (>overbought) et croise %D vers le bas
        -  0: Neutre

    Args:
        high, low, close: Prix OHLC
        k_period: Période %K (défaut: 14)
        d_period: Période %D (défaut: 3)
        smooth_k: Lissage %K (défaut: 3)
        oversold: Seuil survente (défaut: 20)
        overbought: Seuil surachat (défaut: 80)

    Returns:
        np.ndarray de signaux (-1, 0, +1)
    """
    stoch_k, stoch_d = stochastic(high, low, close, k_period, d_period, smooth_k)

    n = len(stoch_k)
    signals = np.zeros(n, dtype=np.float64)

    for i in range(1, n):
        if np.isnan(stoch_k[i]) or np.isnan(stoch_d[i]):
            continue

        k_prev = stoch_k[i - 1]
        k_curr = stoch_k[i]
        d_prev = stoch_d[i - 1]
        d_curr = stoch_d[i]

        if np.isnan(k_prev) or np.isnan(d_prev):
            continue

        # Signal LONG: %K croise %D vers le haut en zone survente
        if k_prev < d_prev and k_curr >= d_curr:
            if k_curr < oversold + 10:  # Proche de la zone survente
                signals[i] = 1.0

        # Signal SHORT: %K croise %D vers le bas en zone surachat
        if k_prev > d_prev and k_curr <= d_curr:
            if k_curr > overbought - 10:  # Proche de la zone surachat
                signals[i] = -1.0

    return signals


# Alias pour compatibilité
stoch = stochastic
