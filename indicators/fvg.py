"""
Module-ID: indicators.fvg

Purpose: Detection Fair Value Gaps (FVG) - zones d'imbalance.

Role in pipeline: pattern detection / entry zones

Key components: calculate_fvg_bullish, calculate_fvg_bearish, fvg (wrapper)

Inputs: DataFrame avec high/low

Outputs: np.ndarray boolean (True = FVG detecte a cette position)

Dependencies: pandas, numpy

Conventions: FVG bullish si low[i] > high[i-2] (gap haussier)
             FVG bearish si high[i] < low[i-2] (gap baissier)
"""

from typing import Dict

import numpy as np
import pandas as pd


def calculate_fvg_bullish(df: pd.DataFrame, **params) -> np.ndarray:
    """
    Detecte les Fair Value Gaps haussiers (bullish FVG).

    Definition:
        FVG bullish[i] = True si low[i] > high[i-2]
        (il y a un gap/imbalance entre bougie i-2 et bougie i)

    Args:
        df: DataFrame avec colonnes 'high', 'low'
        **params: Ignore (compatibilite registry)

    Returns:
        Boolean array (True aux positions de FVG bullish)
    """
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)

    fvg_bull = np.zeros(n, dtype=bool)

    for i in range(2, n):
        # FVG bullish: gap entre i-2 high et i low
        if lows[i] > highs[i-2]:
            fvg_bull[i] = True

    return fvg_bull


def calculate_fvg_bearish(df: pd.DataFrame, **params) -> np.ndarray:
    """
    Detecte les Fair Value Gaps baissiers (bearish FVG).

    Definition:
        FVG bearish[i] = True si high[i] < low[i-2]
        (il y a un gap/imbalance entre bougie i-2 et bougie i)

    Args:
        df: DataFrame avec colonnes 'high', 'low'
        **params: Ignore (compatibilite registry)

    Returns:
        Boolean array (True aux positions de FVG bearish)
    """
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)

    fvg_bear = np.zeros(n, dtype=bool)

    for i in range(2, n):
        # FVG bearish: gap entre i-2 low et i high
        if highs[i] < lows[i-2]:
            fvg_bear[i] = True

    return fvg_bear


def fvg(df: pd.DataFrame, **params) -> Dict[str, np.ndarray]:
    """
    Wrapper retournant les deux types de FVG.

    Returns:
        Dict avec 'fvg_bullish' et 'fvg_bearish' (boolean arrays)
    """
    return {
        'fvg_bullish': calculate_fvg_bullish(df, **params),
        'fvg_bearish': calculate_fvg_bearish(df, **params)
    }


__all__ = ['calculate_fvg_bullish', 'calculate_fvg_bearish', 'fvg']
