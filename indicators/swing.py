"""
Module-ID: indicators.swing

Purpose: Detection swing highs/lows (fractals) - COMPARAISON ADJACENTE UNIQUEMENT.

Role in pipeline: data / pattern detection

Key components: calculate_swing_high, calculate_swing_low, swing (wrapper)

Inputs: DataFrame avec high/low; pas de parametre lookback

Outputs: np.ndarray boolean (True = swing detected)

Dependencies: pandas, numpy

Conventions: SwingHigh[i] = (high[i] > high[i-1] AND high[i] > high[i+1])
             SwingLow[i] = (low[i] < low[i-1] AND low[i] < low[i+1])

CRITICAL: NE PAS utiliser de lookback variable - c'est une erreur conceptuelle.
"""

from typing import Dict

import numpy as np
import pandas as pd


def calculate_swing_high(df: pd.DataFrame, **params) -> np.ndarray:
    """
    Detecte les swing highs (fractals haussiers).

    Definition STRICTE:
        swing_high[i] = True si high[i] > high[i-1] ET high[i] > high[i+1]

    Args:
        df: DataFrame avec colonne 'high'
        **params: Ignore (compatibilite registry)

    Returns:
        Boolean array (True aux positions de swing high)
    """
    highs = df['high'].values
    n = len(highs)
    swing = np.zeros(n, dtype=bool)

    # CORRECTIF: Comparaison ADJACENTE uniquement
    for i in range(1, n - 1):
        if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
            swing[i] = True

    return swing


def calculate_swing_low(df: pd.DataFrame, **params) -> np.ndarray:
    """
    Detecte les swing lows (fractals baissiers).

    Definition STRICTE:
        swing_low[i] = True si low[i] < low[i-1] ET low[i] < low[i+1]

    Args:
        df: DataFrame avec colonne 'low'
        **params: Ignore (compatibilite registry)

    Returns:
        Boolean array (True aux positions de swing low)
    """
    lows = df['low'].values
    n = len(lows)
    swing = np.zeros(n, dtype=bool)

    # CORRECTIF: Comparaison ADJACENTE uniquement
    for i in range(1, n - 1):
        if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
            swing[i] = True

    return swing


def swing(df: pd.DataFrame, **params) -> Dict[str, np.ndarray]:
    """
    Wrapper retournant les deux types de swings.

    Returns:
        Dict avec 'swing_high' et 'swing_low' (boolean arrays)
    """
    return {
        'swing_high': calculate_swing_high(df, **params),
        'swing_low': calculate_swing_low(df, **params)
    }


__all__ = ['calculate_swing_high', 'calculate_swing_low', 'swing']
