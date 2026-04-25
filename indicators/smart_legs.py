"""Module-ID: indicators.smart_legs

Purpose: Construction smart legs (segments directionnels valides).

Role in pipeline: structure detection / trend validation

Key components: calculate_smart_legs_bullish, calculate_smart_legs_bearish

Inputs: DataFrame avec swing_high, swing_low, fvg_bullish, fvg_bearish

Outputs: np.ndarray boolean (True = position fait partie d'un smart leg)

Dependencies: pandas, numpy

Conventions: Smart leg valide = segment entre 2 swings contenant >= 1 FVG
"""

import numpy as np
import pandas as pd

from .fvg import calculate_fvg_bearish, calculate_fvg_bullish
from .registry import register_indicator
from .swing import calculate_swing_high, calculate_swing_low


def calculate_smart_legs_bullish(df: pd.DataFrame, **params) -> np.ndarray:
    """Detecte les smart legs haussiers.

    Definition:
        Segment entre swing_low[i] et swing_high[j] (j > i)
        contenant au moins 1 FVG bullish

    Args:
        df: DataFrame avec 'swing_low', 'swing_high', 'fvg_bullish'
        **params: Ignore

    Returns:
        Boolean array (True = position dans un smart leg bullish)

    """
    n = len(df)
    smart_leg_bull = np.zeros(n, dtype=bool)

    swing_lows = df["swing_low"].values if "swing_low" in df.columns else calculate_swing_low(df, **params)
    swing_highs = df["swing_high"].values if "swing_high" in df.columns else calculate_swing_high(df, **params)
    fvg_bull = df["fvg_bullish"].values if "fvg_bullish" in df.columns else calculate_fvg_bullish(df, **params)

    # Parcourir les swing lows
    swing_low_indices = np.where(swing_lows)[0]

    for start_idx in swing_low_indices:
        # Chercher le prochain swing high
        future_highs = np.where(swing_highs[start_idx + 1 :])[0]

        if len(future_highs) == 0:
            continue

        end_idx = start_idx + 1 + future_highs[0]

        # Verifier presence FVG dans le segment
        segment_has_fvg = np.any(fvg_bull[start_idx : end_idx + 1])

        if segment_has_fvg:
            # Marquer toutes les positions du segment
            smart_leg_bull[start_idx : end_idx + 1] = True

    return smart_leg_bull


def calculate_smart_legs_bearish(df: pd.DataFrame, **params) -> np.ndarray:
    """Detecte les smart legs baissiers.

    Definition:
        Segment entre swing_high[i] et swing_low[j] (j > i)
        contenant au moins 1 FVG bearish

    Args:
        df: DataFrame avec 'swing_high', 'swing_low', 'fvg_bearish'
        **params: Ignore

    Returns:
        Boolean array (True = position dans un smart leg bearish)

    """
    n = len(df)
    smart_leg_bear = np.zeros(n, dtype=bool)

    swing_lows = df["swing_low"].values if "swing_low" in df.columns else calculate_swing_low(df, **params)
    swing_highs = df["swing_high"].values if "swing_high" in df.columns else calculate_swing_high(df, **params)
    fvg_bear = df["fvg_bearish"].values if "fvg_bearish" in df.columns else calculate_fvg_bearish(df, **params)

    # Parcourir les swing highs
    swing_high_indices = np.where(swing_highs)[0]

    for start_idx in swing_high_indices:
        # Chercher le prochain swing low
        future_lows = np.where(swing_lows[start_idx + 1 :])[0]

        if len(future_lows) == 0:
            continue

        end_idx = start_idx + 1 + future_lows[0]

        # Verifier presence FVG dans le segment
        segment_has_fvg = np.any(fvg_bear[start_idx : end_idx + 1])

        if segment_has_fvg:
            # Marquer toutes les positions du segment
            smart_leg_bear[start_idx : end_idx + 1] = True

    return smart_leg_bear


def smart_legs(df: pd.DataFrame, **params) -> dict[str, np.ndarray]:
    """Wrapper retournant les deux types de smart legs.

    Returns:
        Dict avec 'smart_leg_bullish' et 'smart_leg_bearish'

    """
    return {
        "smart_leg_bullish": calculate_smart_legs_bullish(df, **params),
        "smart_leg_bearish": calculate_smart_legs_bearish(df, **params),
    }


register_indicator(
    name="smart_legs",
    function=smart_legs,
    settings_class=None,
    required_columns=("high", "low"),
    description="Smart legs - validated directional segments built from swings and FVGs",
)


__all__ = ["calculate_smart_legs_bearish", "calculate_smart_legs_bullish", "smart_legs"]
