"""
Module-ID: backtest.execution_fast

Purpose: Optimisations Numba JIT pour calculs spread/slippage dynamiques (50-100x accélération).

Role in pipeline: execution / performance

Key components: roll_spread_numba, high_low_spread_numba, HAS_NUMBA flag

Inputs: closes array, returns array, volatilité, volume

Outputs: Spreads/slippages vectorisés (arrays numpy)

Dependencies: numpy, optionnel: numba (JIT compilation); fallback Python si numba absent

Conventions: HAS_NUMBA = False si numba non installé (fallback OK); spreads en fractions; cache=True pour réutilisation.

Read-if: Optimisation exécution ou modification calculs spread/slippage.

Skip-if: Performances acceptables avec execution.py pur Python.
"""

import numpy as np

try:
    from numba import njit, prange
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    prange = range


if HAS_NUMBA:
    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False, parallel=True)
    def roll_spread_numba(
        closes: np.ndarray,
        returns: np.ndarray,
        window: int = 20
    ) -> np.ndarray:
        """
        Estimateur Roll vectorisé avec Numba.

        Calcule le spread effectif basé sur l'auto-covariance des returns.
        Version JIT-compiled pour performance maximale.
        """
        n = len(closes)
        spreads = np.zeros(n)

        for i in prange(window + 1, n):
            # Fenêtre de returns
            r_window = returns[i-window:i]
            r_lag = returns[i-window-1:i-1]

            # Covariance manuelle (plus rapide que np.cov en boucle)
            mean_window = np.mean(r_window)
            mean_lag = np.mean(r_lag)

            cov = 0.0
            for j in range(len(r_window)):
                cov += (r_window[j] - mean_window) * (r_lag[j] - mean_lag)
            cov /= len(r_window)

            if cov < 0:
                spreads[i] = 2 * np.sqrt(-cov) * closes[i]
            else:
                spreads[i] = 0.0

        return spreads

    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False, parallel=True)
    def high_low_spread_numba(
        highs: np.ndarray,
        lows: np.ndarray
    ) -> np.ndarray:
        """
        Estimateur Corwin-Schultz vectorisé avec Numba.

        Version JIT-compiled pour performance maximale.
        """
        n = len(highs)
        spreads = np.zeros(n)
        sqrt_2 = np.sqrt(2.0)

        for i in prange(2, n):
            # Beta
            log_hl_t = np.log(highs[i] / lows[i])
            log_hl_t1 = np.log(highs[i-1] / lows[i-1])
            beta = log_hl_t ** 2 + log_hl_t1 ** 2

            # Gamma
            max_high = max(highs[i], highs[i-1])
            min_low = min(lows[i], lows[i-1])
            gamma = (np.log(max_high / min_low)) ** 2

            # Alpha
            denom = 3.0 - 2.0 * sqrt_2
            if abs(denom) > 1e-10:
                term1 = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / denom
                term2 = np.sqrt(gamma / denom)
                alpha = term1 - term2

                # Spread
                if alpha > -10.0 and alpha < 10.0:  # Éviter overflow
                    exp_alpha = np.exp(alpha)
                    spread_pct = 2.0 * (exp_alpha - 1.0) / (1.0 + exp_alpha)
                    spreads[i] = max(0.0, spread_pct * 10000.0)  # En BPS

        return spreads

    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False, parallel=True)
    def calculate_volatility_fast(
        returns: np.ndarray,
        window: int
    ) -> np.ndarray:
        """
        Calcul de volatilité rolling vectorisé avec Numba.

        Parallélisé pour performance maximale sur grandes séries.
        """
        n = len(returns)
        volatility = np.zeros(n)

        for i in prange(window, n):
            volatility[i] = np.std(returns[i-window:i])

        # Remplir le début
        if window < n and volatility[window] > 0:
            volatility[:window] = volatility[window]

        return volatility

    @njit(cache=True, nogil=True, fastmath=True, boundscheck=False, parallel=True)
    def calculate_volume_ratio_fast(
        volumes: np.ndarray,
        window: int
    ) -> np.ndarray:
        """
        Calcul de volume ratio rolling vectorisé avec Numba.

        Ratio = 1 / (volume_courant / volume_moyen)
        Faible volume -> ratio élevé -> plus de slippage
        """
        n = len(volumes)
        volume_ratio = np.ones(n)

        for i in prange(window, n):
            avg_vol = np.mean(volumes[i-window:i])
            if avg_vol > 0 and volumes[i] > 0:
                ratio = volumes[i] / avg_vol
                if ratio > 0:
                    volume_ratio[i] = 1.0 / ratio

        # Clip entre 0.5 et 3.0
        volume_ratio = np.clip(volume_ratio, 0.5, 3.0)

        return volume_ratio


# =============================================================================
# FALLBACK NUMPY (si Numba non disponible)
# =============================================================================

def roll_spread_numpy(
    closes: np.ndarray,
    returns: np.ndarray,
    window: int = 20
) -> np.ndarray:
    """Version numpy pure (fallback)."""
    import pandas as pd

    n = len(closes)
    spreads = np.zeros(n)

    # Utiliser pandas rolling pour covariance
    returns_series = pd.Series(returns)
    returns_lag = returns_series.shift(1)

    # Rolling covariance
    cov = returns_series.rolling(window).cov(returns_lag)
    cov = cov.fillna(0).values

    # Appliquer formule Roll
    negative_cov = cov < 0
    spreads[negative_cov] = 2 * np.sqrt(-cov[negative_cov]) * closes[negative_cov]

    return spreads


def high_low_spread_numpy(
    highs: np.ndarray,
    lows: np.ndarray
) -> np.ndarray:
    """Version numpy pure (fallback) - garde la boucle car logique complexe."""
    n = len(highs)
    spreads = np.zeros(n)
    sqrt_2 = np.sqrt(2.0)

    for i in range(2, n):
        beta = (np.log(highs[i] / lows[i])) ** 2 + (np.log(highs[i-1] / lows[i-1])) ** 2
        gamma = (np.log(max(highs[i], highs[i-1]) / min(lows[i], lows[i-1]))) ** 2

        denom = 3.0 - 2.0 * sqrt_2
        if abs(denom) > 1e-10:
            alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / denom - np.sqrt(gamma / denom)

            if -10 < alpha < 10:
                exp_alpha = np.exp(alpha)
                spread_pct = 2.0 * (exp_alpha - 1.0) / (1.0 + exp_alpha)
                spreads[i] = max(0.0, spread_pct * 10000.0)

    return spreads


# Docstring update summary
# - Docstring de module normalisée (LLM-friendly) centrée sur optimisations Numba JIT
# - Conventions HAS_NUMBA flag et fallback explicitées
# - Read-if/Skip-if ajoutés pour guider la lecture


# =============================================================================
# INTERFACE UNIFIÉE
# =============================================================================

# Sélectionner automatiquement la meilleure implémentation
if HAS_NUMBA:
    roll_spread = roll_spread_numba
    high_low_spread = high_low_spread_numba
    calculate_volatility = calculate_volatility_fast
    calculate_volume_ratio = calculate_volume_ratio_fast
else:
    roll_spread = roll_spread_numpy
    high_low_spread = high_low_spread_numpy
    # Pas d'équivalent numpy pour ces deux, on garde pandas dans execution.py
    calculate_volatility = None
    calculate_volume_ratio = None
