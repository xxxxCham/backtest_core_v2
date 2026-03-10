"""
Module-ID: indicators.roc

Purpose: Indicateur ROC (Rate of Change) - changement % prix.

Role in pipeline: data

Key components: roc, ROCSettings, calculate_roc

Inputs: DataFrame avec close; period

Outputs: np.ndarray (% changement)

Dependencies: pandas, numpy, dataclasses

Conventions: ROC = (Close - Close[n]) / Close[n] * 100; momentum en pourcent.

Read-if: Modification période, normalisation %.

Skip-if: Vous utilisez juste calculate_indicator('roc').
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class ROCSettings:
    """Paramètres ROC."""
    period: int = 12


def roc(
    close: pd.Series | np.ndarray,
    period: int = 12,
) -> np.ndarray:
    """
    Calcule Rate of Change.

    Args:
        close: Prix de clôture
        period: Période (défaut: 12)

    Returns:
        ROC en pourcentage
    """
    if isinstance(close, pd.Series):
        close = close.values

    close_shifted = np.roll(close, period)
    roc_values = ((close - close_shifted) / close_shifted) * 100.0
    roc_values[:period] = np.nan

    return roc_values


__all__ = ["roc", "ROCSettings"]
