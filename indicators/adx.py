"""
Module-ID: indicators.adx

Purpose: Indicateur ADX (force tendance) + DI+ (haussier) + DI- (baissier).

Role in pipeline: data

Key components: adx, calculate_adx, ADXSettings, plus_di, minus_di

Inputs: DataFrame avec high, low, close; period (14 standard)

Outputs: Dict{adx, plus_di, minus_di} ou Tuple

Dependencies: pandas, numpy, dataclasses

Conventions: ADX lissé 14 périodes; +DI/DI- direction; <20 faible, >40 forte tendance.

Read-if: Modification période, lissage ADX.

Skip-if: Vous utilisez juste calculate_indicator('adx').
"""

from typing import Dict, Tuple, Union

import numpy as np
import pandas as pd


def directional_movement(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray]
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Calcule les mouvements directionnels (+DM, -DM) et True Range.

    Args:
        high: Série des plus hauts
        low: Série des plus bas
        close: Série des clôtures

    Returns:
        Tuple (+DM, -DM, TR)
    """
    # Convertir en arrays
    if isinstance(high, pd.Series):
        high = high.values
    if isinstance(low, pd.Series):
        low = low.values
    if isinstance(close, pd.Series):
        close = close.values

    n = len(high)

    # True Range
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i-1]),
            abs(low[i] - close[i-1])
        )

    # Directional Movement
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)

    for i in range(1, n):
        up_move = high[i] - high[i-1]
        down_move = low[i-1] - low[i]

        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    return plus_dm, minus_dm, tr


def smooth_directional(
    values: np.ndarray,
    period: int
) -> np.ndarray:
    """
    Applique le lissage Wilder (type EMA avec alpha = 1/period).

    Args:
        values: Valeurs à lisser
        period: Période de lissage

    Returns:
        Valeurs lissées
    """
    n = len(values)
    smoothed = np.zeros(n)

    # Première valeur = somme des N premières valeurs
    smoothed[period-1] = np.sum(values[:period])

    # Lissage Wilder: new = prev - (prev/period) + current
    for i in range(period, n):
        smoothed[i] = smoothed[i-1] - (smoothed[i-1] / period) + values[i]

    return smoothed


def adx(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int = 14
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Calcule l'ADX (Average Directional Index) et les DI.

    Args:
        high: Série des plus hauts
        low: Série des plus bas
        close: Série des clôtures
        period: Période de calcul (défaut: 14)

    Returns:
        Tuple (adx, plus_di, minus_di)

    Example:
        >>> adx_val, plus_di, minus_di = adx(df["high"], df["low"], df["close"])
        >>> # Tendance forte si adx_val > 25
        >>> # Tendance haussière si plus_di > minus_di
    """
    # Mouvements directionnels et True Range
    plus_dm, minus_dm, tr = directional_movement(high, low, close)

    # Lissage Wilder
    smoothed_tr = smooth_directional(tr, period)
    smoothed_plus_dm = smooth_directional(plus_dm, period)
    smoothed_minus_dm = smooth_directional(minus_dm, period)

    # Éviter division par zéro
    smoothed_tr = np.where(smoothed_tr == 0, 1e-10, smoothed_tr)

    # Directional Indicators (+DI, -DI)
    plus_di = 100 * smoothed_plus_dm / smoothed_tr
    minus_di = 100 * smoothed_minus_dm / smoothed_tr

    # DX (Directional Movement Index)
    di_sum = plus_di + minus_di
    di_sum = np.where(di_sum == 0, 1e-10, di_sum)
    dx = 100 * np.abs(plus_di - minus_di) / di_sum

    # ADX = smoothed DX
    n = len(dx)
    adx_values = np.zeros(n)

    # Première valeur ADX = moyenne des N premiers DX
    if 2 * period - 1 < n:
        adx_values[2*period-2] = np.mean(dx[period-1:2*period-1])

        # Lissage pour le reste
        for i in range(2*period-1, n):
            adx_values[i] = (adx_values[i-1] * (period-1) + dx[i]) / period

    return adx_values, plus_di, minus_di


def adx_trend_strength(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int = 14
) -> np.ndarray:
    """
    Retourne uniquement la valeur ADX (force de tendance).

    Args:
        high, low, close: Séries OHLC
        period: Période

    Returns:
        Array ADX
    """
    adx_val, _, _ = adx(high, low, close, period)
    return adx_val


def adx_signal(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int = 14,
    adx_threshold: float = 25.0
) -> np.ndarray:
    """
    Génère des signaux de trading basés sur ADX/DI.

    Logique:
    - +1: ADX > seuil ET +DI > -DI ET +DI croise -DI à la hausse
    - -1: ADX > seuil ET -DI > +DI ET -DI croise +DI à la hausse
    - 0: Sinon

    Args:
        high, low, close: Séries OHLC
        period: Période ADX
        adx_threshold: Seuil ADX pour confirmer tendance

    Returns:
        Array de signaux
    """
    adx_val, plus_di, minus_di = adx(high, low, close, period)

    n = len(adx_val)
    signals = np.zeros(n, dtype=np.int8)

    for i in range(1, n):
        if adx_val[i] < adx_threshold:
            continue  # Pas de tendance suffisante

        # Croisement +DI au-dessus de -DI
        if plus_di[i] > minus_di[i] and plus_di[i-1] <= minus_di[i-1]:
            signals[i] = 1
        # Croisement -DI au-dessus de +DI
        elif minus_di[i] > plus_di[i] and minus_di[i-1] <= plus_di[i-1]:
            signals[i] = -1

    return signals


# Pour le registre d'indicateurs
def calculate_adx(df: pd.DataFrame, params: Dict) -> Dict[str, np.ndarray]:
    """
    Fonction wrapper pour le registre d'indicateurs.

    Args:
        df: DataFrame OHLCV
        params: {"period": 14}

    Returns:
        Dict avec adx, plus_di, minus_di
    """
    period = int(params.get("period", 14))

    adx_val, plus_di, minus_di = adx(
        df["high"], df["low"], df["close"], period
    )

    return {
        "adx": adx_val,
        "plus_di": plus_di,
        "minus_di": minus_di
    }


__all__ = [
    "adx",
    "adx_trend_strength",
    "adx_signal",
    "directional_movement",
    "calculate_adx"
]
