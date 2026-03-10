"""
Module-ID: indicators.macd

Purpose: Indicateur MACD (momentum) - ligne signal + histogram.

Role in pipeline: data

Key components: macd, calculate_macd, MACD line, Signal line, Histogram

Inputs: DataFrame avec close; fast_period, slow_period, signal_period

Outputs: Dict{macd, signal, histogram} ou Tuple

Dependencies: pandas, numpy, ema

Conventions: macd = ema_fast - ema_slow; signal = ema(macd); histogram = macd - signal.

Read-if: Modification périodes, output structure.

Skip-if: Vous utilisez juste calculate_indicator('macd').
"""

from typing import Dict, Tuple, Union

import numpy as np
import pandas as pd

from .ema import ema


def macd(
    data: Union[pd.Series, np.ndarray],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Calcule le MACD (Moving Average Convergence Divergence).

    Args:
        data: Série de prix (généralement close)
        fast_period: Période de l'EMA rapide (défaut: 12)
        slow_period: Période de l'EMA lente (défaut: 26)
        signal_period: Période du signal (défaut: 9)

    Returns:
        Tuple (macd_line, signal_line, histogram)

    Example:
        >>> macd_line, signal, hist = macd(df["close"])
        >>> # Signal d'achat: macd_line croise signal à la hausse
    """
    # Convertir en array si nécessaire
    if isinstance(data, pd.Series):
        values = data.values
    else:
        values = np.asarray(data)

    # Calculer les EMAs
    ema_fast = ema(values, fast_period)
    ema_slow = ema(values, slow_period)

    # MACD Line
    macd_line = ema_fast - ema_slow

    # Signal Line (EMA du MACD)
    signal_line = ema(macd_line, signal_period)

    # Histogram
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def macd_signal(
    data: Union[pd.Series, np.ndarray],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> np.ndarray:
    """
    Génère des signaux de trading basés sur le MACD.

    Args:
        data: Série de prix
        fast_period: Période EMA rapide
        slow_period: Période EMA lente
        signal_period: Période du signal

    Returns:
        Array de signaux: +1 (achat), -1 (vente), 0 (neutre)
    """
    macd_line, signal_line, _ = macd(data, fast_period, slow_period, signal_period)

    n = len(macd_line)
    signals = np.zeros(n, dtype=np.int8)

    for i in range(1, n):
        # Croisement haussier: MACD passe au-dessus du signal
        if macd_line[i] > signal_line[i] and macd_line[i-1] <= signal_line[i-1]:
            signals[i] = 1
        # Croisement baissier: MACD passe en-dessous du signal
        elif macd_line[i] < signal_line[i] and macd_line[i-1] >= signal_line[i-1]:
            signals[i] = -1

    return signals


def macd_histogram_divergence(
    prices: Union[pd.Series, np.ndarray],
    histogram: np.ndarray,
    lookback: int = 20
) -> np.ndarray:
    """
    Détecte les divergences entre prix et histogram MACD.

    Une divergence haussière: prix fait un plus bas, histogram fait un plus haut
    Une divergence baissière: prix fait un plus haut, histogram fait un plus bas

    Args:
        prices: Série de prix
        histogram: Histogram MACD
        lookback: Période de lookback pour trouver les extrema

    Returns:
        Array: +1 (divergence haussière), -1 (divergence baissière), 0 (rien)
    """
    if isinstance(prices, pd.Series):
        prices = prices.values

    n = len(prices)
    divergences = np.zeros(n, dtype=np.int8)

    for i in range(lookback, n):
        window_prices = prices[i-lookback:i+1]
        window_hist = histogram[i-lookback:i+1]

        # Indices des extrema locaux
        price_min_idx = np.argmin(window_prices)
        price_max_idx = np.argmax(window_prices)
        hist_min_idx = np.argmin(window_hist)
        hist_max_idx = np.argmax(window_hist)

        # Divergence haussière: nouveau plus bas prix mais histogram remonte
        if price_min_idx > lookback // 2 and hist_min_idx < lookback // 2:
            if window_prices[-1] < window_prices[0] and window_hist[-1] > window_hist[0]:
                divergences[i] = 1

        # Divergence baissière: nouveau plus haut prix mais histogram descend
        if price_max_idx > lookback // 2 and hist_max_idx < lookback // 2:
            if window_prices[-1] > window_prices[0] and window_hist[-1] < window_hist[0]:
                divergences[i] = -1

    return divergences


# Pour le registre d'indicateurs
def calculate_macd(df: pd.DataFrame, params: Dict) -> Dict[str, np.ndarray]:
    """
    Fonction wrapper pour le registre d'indicateurs.

    Args:
        df: DataFrame OHLCV
        params: {"fast_period": 12, "slow_period": 26, "signal_period": 9}

    Returns:
        Dict avec macd, signal, histogram
    """
    fast = int(params.get("fast_period", 12))
    slow = int(params.get("slow_period", 26))
    signal = int(params.get("signal_period", 9))

    macd_line, signal_line, histogram = macd(df["close"], fast, slow, signal)

    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram
    }


__all__ = ["macd", "macd_signal", "macd_histogram_divergence", "calculate_macd"]
