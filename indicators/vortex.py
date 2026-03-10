"""
Module-ID: indicators.vortex

Purpose: Indicateur Vortex (VI+ et VI-) - force mouvement haussier/baissier.

Role in pipeline: data

Key components: vortex, calculate_vortex, vi_plus, vi_minus, oscillator, signal

Inputs: DataFrame avec high, low, close; period

Outputs: Dict{vi_plus, vi_minus, signal, oscillator} ou Tuple

Dependencies: pandas, numpy

Conventions: VI+ > VI- tendance haussière; oscillator = VI+ - VI-.

Read-if: Modification période, output format.

Skip-if: Vous utilisez juste calculate_indicator('vortex').
"""

from typing import Dict, Tuple

import numpy as np
import pandas as pd

from indicators.registry import register_indicator


def vortex_movement(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Calcule les mouvements Vortex (+VM, -VM) et le True Range.

    Args:
        high: Série des prix hauts
        low: Série des prix bas
        close: Série des prix de clôture

    Returns:
        Tuple (plus_vm, minus_vm, true_range)
    """
    high_arr = np.asarray(high, dtype=np.float64)
    low_arr = np.asarray(low, dtype=np.float64)
    close_arr = np.asarray(close, dtype=np.float64)
    n = len(high_arr)

    # +VM = |High actuel - Low précédent|
    plus_vm = np.full(n, np.nan)
    plus_vm[1:] = np.abs(high_arr[1:] - low_arr[:-1])

    # -VM = |Low actuel - High précédent|
    minus_vm = np.full(n, np.nan)
    minus_vm[1:] = np.abs(low_arr[1:] - high_arr[:-1])

    # True Range
    tr = np.full(n, np.nan)
    tr[0] = high_arr[0] - low_arr[0]
    for i in range(1, n):
        tr[i] = max(
            high_arr[i] - low_arr[i],
            abs(high_arr[i] - close_arr[i-1]),
            abs(low_arr[i] - close_arr[i-1])
        )

    return plus_vm, minus_vm, tr


def vortex(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Calcule les indicateurs Vortex VI+ et VI-.

    Formule:
    - VI+ = SUM(+VM, N) / SUM(TR, N)
    - VI- = SUM(-VM, N) / SUM(TR, N)

    Args:
        high: Série des prix hauts
        low: Série des prix bas
        close: Série des prix de clôture
        period: Période de calcul (défaut: 14)

    Returns:
        Tuple (vi_plus, vi_minus)
    """
    plus_vm, minus_vm, tr = vortex_movement(high, low, close)

    n = len(high)
    vi_plus = np.full(n, np.nan)
    vi_minus = np.full(n, np.nan)

    for i in range(period, n):
        # Somme sur la période
        vm_plus_sum = np.nansum(plus_vm[i - period + 1:i + 1])
        vm_minus_sum = np.nansum(minus_vm[i - period + 1:i + 1])
        tr_sum = np.nansum(tr[i - period + 1:i + 1])

        if tr_sum > 0:
            vi_plus[i] = vm_plus_sum / tr_sum
            vi_minus[i] = vm_minus_sum / tr_sum

    return vi_plus, vi_minus


def vortex_signal(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
    threshold: float = 0.0
) -> np.ndarray:
    """
    Génère des signaux de trading basés sur le Vortex Indicator.

    Signaux:
    - Long (1): VI+ croise VI- vers le haut
    - Short (-1): VI+ croise VI- vers le bas
    - Neutre (0): Pas de croisement

    Args:
        high, low, close: Séries de prix
        period: Période du Vortex
        threshold: Seuil minimum de différence pour générer un signal

    Returns:
        Array de signaux (-1, 0, 1)
    """
    vi_plus, vi_minus = vortex(high, low, close, period)

    n = len(close)
    signals = np.zeros(n)

    for i in range(1, n):
        if np.isnan(vi_plus[i]) or np.isnan(vi_minus[i]):
            continue
        if np.isnan(vi_plus[i-1]) or np.isnan(vi_minus[i-1]):
            continue

        diff_prev = vi_plus[i-1] - vi_minus[i-1]
        diff_curr = vi_plus[i] - vi_minus[i]

        # Croisement haussier: VI+ passe au-dessus de VI-
        if diff_prev <= threshold and diff_curr > threshold:
            signals[i] = 1

        # Croisement baissier: VI+ passe en-dessous de VI-
        elif diff_prev >= -threshold and diff_curr < -threshold:
            signals[i] = -1

    return signals


def vortex_trend_strength(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14
) -> np.ndarray:
    """
    Mesure la force de la tendance basée sur la différence VI+ - VI-.

    Returns:
        Valeurs positives = tendance haussière forte
        Valeurs négatives = tendance baissière forte
        Valeurs proches de 0 = pas de tendance claire
    """
    vi_plus, vi_minus = vortex(high, low, close, period)
    return vi_plus - vi_minus


def vortex_oscillator(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14
) -> np.ndarray:
    """
    Oscillateur Vortex normalisé entre -100 et +100.

    Formule: (VI+ - VI-) / (VI+ + VI-) * 100

    Returns:
        Oscillateur entre -100 et +100
    """
    vi_plus, vi_minus = vortex(high, low, close, period)

    # Éviter la division par zéro
    denominator = vi_plus + vi_minus
    oscillator = np.where(
        denominator > 0,
        (vi_plus - vi_minus) / denominator * 100,
        0
    )

    # Propager les NaN
    nan_mask = np.isnan(vi_plus) | np.isnan(vi_minus)
    oscillator[nan_mask] = np.nan

    return oscillator


def calculate_vortex(df: pd.DataFrame, **params) -> Dict[str, np.ndarray]:
    """
    Fonction wrapper pour le registre d'indicateurs.

    Args:
        df: DataFrame avec colonnes high, low, close
        **params: Paramètres clé-valeur
            - period: Période de calcul (défaut: 14)
            - threshold: Seuil pour les signaux (défaut: 0.0)

    Returns:
        Dict avec vi_plus, vi_minus, signal, oscillator
    """
    period = params.get("period", 14)
    threshold = params.get("threshold", 0.0)

    vi_plus, vi_minus = vortex(df["high"], df["low"], df["close"], period)
    signal = vortex_signal(df["high"], df["low"], df["close"], period, threshold)
    oscillator = vortex_oscillator(df["high"], df["low"], df["close"], period)

    return {
        "vi_plus": vi_plus,
        "vi_minus": vi_minus,
        "signal": signal,
        "oscillator": oscillator
    }


# Enregistrement dans le registre
register_indicator(
    "vortex",
    calculate_vortex,
    required_columns=("high", "low", "close"),
    description="Vortex Indicator - Mesure la force des tendances"
)


__all__ = [
    "vortex",
    "vortex_movement",
    "vortex_signal",
    "vortex_trend_strength",
    "vortex_oscillator",
    "calculate_vortex",
]
