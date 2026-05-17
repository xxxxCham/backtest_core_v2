"""Module-ID: indicators.ad_line

Purpose: Accumulation/Distribution Line (ADL) - indicateur de volume de Marc Chaikin.

L'A/D Line est la base de la famille Chaikin (Chaikin Oscillator = MACD applique
sur A/D Line). Elle accumule le Money Flow Volume signe par la position du close
dans le range de la bougie:

    MFM (Money Flow Multiplier) = ((Close - Low) - (High - Close)) / (High - Low)
    MFV (Money Flow Volume)     = MFM * Volume
    A/D Line                    = sum cumulee de MFV

Interpretation:
- A/D Line en hausse alors que le prix stagne ou baisse = accumulation cachee
- A/D Line en baisse alors que le prix monte = distribution cachee (divergence baissiere)
- Plus utile en divergence prix/indicateur qu'en valeur absolue (cumul sans bornes).

2026-05-15 - Ajoute pour completer la famille Chaikin du Builder (Oscillator + CMF
deja presents, A/D Line manquante alors qu'elle en est la base mathematique).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .registry import register_indicator


@dataclass
class ADLineSettings:
    """A/D Line n'a pas de parametre de fenetre - c'est un cumul depuis l'origine."""


def ad_line(
    high: pd.Series | np.ndarray,
    low: pd.Series | np.ndarray,
    close: pd.Series | np.ndarray,
    volume: pd.Series | np.ndarray,
) -> np.ndarray:
    """Calcule l'Accumulation/Distribution Line.

    Returns un ndarray de la meme longueur que les inputs, en cumul depuis l'index 0.
    Les valeurs sont en valeur absolue (somme cumulee de MFV signe) - utilisable en
    divergence vs prix, en derivee (np.diff) pour un proxy de flux instantane, ou
    en regression vs prix pour detecter des accumulations.
    """
    high_series = pd.Series(np.asarray(high, dtype=np.float64))
    low_series = pd.Series(np.asarray(low, dtype=np.float64))
    close_series = pd.Series(np.asarray(close, dtype=np.float64))
    volume_series = pd.Series(np.asarray(volume, dtype=np.float64))

    # Money Flow Multiplier: ((Close - Low) - (High - Close)) / (High - Low)
    # Si High == Low (bougie plate), MFM force a 0 pour eviter NaN qui propage en cumsum.
    denominator = (high_series - low_series).replace(0.0, np.nan)
    mfm = ((close_series - low_series) - (high_series - close_series)) / denominator
    mfm = mfm.fillna(0.0)

    # Money Flow Volume = MFM * Volume, puis cumul depuis l'origine
    mfv = mfm * volume_series
    return mfv.cumsum().values


def calculate_ad_line(df: pd.DataFrame, **params) -> np.ndarray:
    return ad_line(
        df["high"],
        df["low"],
        df["close"],
        df["volume"],
    )


register_indicator(
    "ad_line",
    calculate_ad_line,
    settings_class=ADLineSettings,
    required_columns=("high", "low", "close", "volume"),
    description="Accumulation/Distribution Line (Chaikin)",
)


__all__ = ["ADLineSettings", "ad_line", "calculate_ad_line"]
