"""
Module-ID: indicators.scoring

Purpose: Calcul score directionnel bull/bear base sur patterns.

Role in pipeline: decision / bias calculation

Key components: calculate_bull_score, calculate_bear_score

Inputs: DataFrame avec swing, fvg, fva, smart_legs

Outputs: np.ndarray float (score 0.0-1.0)

Dependencies: pandas, numpy

Conventions: Score = somme ponderee patterns detectes, normalise 0-1
"""

from typing import Dict

import numpy as np
import pandas as pd


def calculate_bull_score(df: pd.DataFrame, **params) -> np.ndarray:
    """
    Calcule le score haussier base sur patterns detectes.

    Composantes:
        +1 si swing_low detecte (support potentiel)
        +1 si fvg_bullish actif
        +1 si smart_leg_bullish actif
        +1 si fva presente (consolidation avant reprise)

    Args:
        df: DataFrame avec colonnes pattern
        **params: Ignore

    Returns:
        Float array (score 0.0-1.0, normalise par max possible)
    """
    n = len(df)
    score = np.zeros(n, dtype=float)

    # Composantes optionnelles
    if 'swing_low' in df.columns:
        score += df['swing_low'].values.astype(float)

    if 'fvg_bullish' in df.columns:
        score += df['fvg_bullish'].values.astype(float)

    if 'smart_leg_bullish' in df.columns:
        score += df['smart_leg_bullish'].values.astype(float)

    if 'fva' in df.columns:
        score += df['fva'].values.astype(float) * 0.5  # Poids reduit

    # Normaliser par max possible (3.5)
    max_score = 3.5
    score_normalized = np.clip(score / max_score, 0.0, 1.0)

    return score_normalized


def calculate_bear_score(df: pd.DataFrame, **params) -> np.ndarray:
    """
    Calcule le score baissier base sur patterns detectes.

    Composantes:
        +1 si swing_high detecte (resistance potentielle)
        +1 si fvg_bearish actif
        +1 si smart_leg_bearish actif
        +1 si fva presente (consolidation avant chute)

    Args:
        df: DataFrame avec colonnes pattern
        **params: Ignore

    Returns:
        Float array (score 0.0-1.0, normalise par max possible)
    """
    n = len(df)
    score = np.zeros(n, dtype=float)

    # Composantes optionnelles
    if 'swing_high' in df.columns:
        score += df['swing_high'].values.astype(float)

    if 'fvg_bearish' in df.columns:
        score += df['fvg_bearish'].values.astype(float)

    if 'smart_leg_bearish' in df.columns:
        score += df['smart_leg_bearish'].values.astype(float)

    if 'fva' in df.columns:
        score += df['fva'].values.astype(float) * 0.5  # Poids reduit

    # Normaliser par max possible (3.5)
    max_score = 3.5
    score_normalized = np.clip(score / max_score, 0.0, 1.0)

    return score_normalized


def directional_bias(df: pd.DataFrame, **params) -> Dict[str, np.ndarray]:
    """
    Calcule le biais directionnel net.

    Returns:
        Dict avec:
            'bull_score': score haussier 0-1
            'bear_score': score baissier 0-1
            'net_bias': bull_score - bear_score (-1 a +1)
    """
    bull = calculate_bull_score(df, **params)
    bear = calculate_bear_score(df, **params)

    return {
        'bull_score': bull,
        'bear_score': bear,
        'net_bias': bull - bear
    }


__all__ = ['calculate_bull_score', 'calculate_bear_score', 'directional_bias']
