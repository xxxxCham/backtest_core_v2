"""
Module-ID: indicators.keltner

Purpose: Indicateur Keltner Channel - bandes EMA+ATR (alternative Bollinger).

Role in pipeline: data

Key components: keltner_channel, KeltnerSettings, calculate_keltner

Inputs: DataFrame avec high, low, close; ema_period, atr_period, atr_mult

Outputs: Dict{middle, upper, lower} ou Tuple

Dependencies: pandas, numpy, ema, atr, dataclasses

Conventions: middle = EMA; bands = +/- ATR*mult; plus lisse que Bollinger.

Read-if: Modification EMA/ATR params, output format.

Skip-if: Vous utilisez juste calculate_indicator('keltner').
"""

from dataclasses import dataclass
from typing import Tuple

import numpy as np
import pandas as pd

from .atr import atr
from .ema import ema


@dataclass
class KeltnerSettings:
    """Paramètres Keltner Channel."""
    ema_period: int = 20
    atr_period: int = 10
    atr_multiplier: float = 2.0


def keltner_channel(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    ema_period: int = 20,
    atr_period: int = 10,
    atr_multiplier: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Calcule Keltner Channel.

    Args:
        high: Prix hauts
        low: Prix bas
        close: Prix de clôture
        ema_period: Période EMA centrale (défaut: 20)
        atr_period: Période ATR pour les bandes (défaut: 10)
        atr_multiplier: Multiplicateur ATR (défaut: 2.0)

    Returns:
        Tuple (middle, upper, lower)
    """
    # Middle = EMA du close
    middle = ema(close, period=ema_period)

    # ATR
    atr_values = atr(high, low, close, period=atr_period)

    # Bandes
    upper = middle + atr_multiplier * atr_values
    lower = middle - atr_multiplier * atr_values

    return middle, upper, lower


__all__ = ["keltner_channel", "KeltnerSettings"]
