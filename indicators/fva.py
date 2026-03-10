"""
Module-ID: indicators.fva

Purpose: Detection Fair Value Areas (FVA) - zones d'equilibre/consolidation.

Role in pipeline: pattern detection / consolidation zones

Key components: calculate_fva

Inputs: DataFrame avec high/low

Outputs: np.ndarray boolean (True = FVA detecte)

Dependencies: pandas, numpy

Conventions: FVA[i] = True si high[i] < high[i-1] ET low[i] > low[i-1]
             (bar actuelle completement dans le range de la bar precedente)
"""

import numpy as np
import pandas as pd


def calculate_fva(df: pd.DataFrame, **params) -> np.ndarray:
    """
    Detecte les Fair Value Areas (zones de consolidation).

    Definition SIMPLIFIEE:
        FVA[i] = True si la bougie i est completement dans le range de i-1
        high[i] < high[i-1] ET low[i] > low[i-1]

    Args:
        df: DataFrame avec colonnes 'high', 'low'
        **params: Ignore (compatibilite registry)

    Returns:
        Boolean array (True aux positions de FVA)
    """
    highs = df['high'].values
    lows = df['low'].values
    n = len(df)

    fva = np.zeros(n, dtype=bool)

    for i in range(1, n):
        # Bar actuelle completement dans le range de la bar precedente
        if highs[i] < highs[i-1] and lows[i] > lows[i-1]:
            fva[i] = True

    return fva


__all__ = ['calculate_fva']
