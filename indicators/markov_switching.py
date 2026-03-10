"""
Markov Switching Model pour détection de phases de marché.

Cet indicateur est SPECIAL : il n'est PAS optimisable via params/sweeps.
Il doit être appelé explicitement dans les stratégies via import direct.

Retourne :
- 'regime' : régime le plus probable (0, 1, 2)
- 'phase' : interprétation lisible ('Bull', 'Bear', 'Ranging')
- 'prob_regime_0', 'prob_regime_1', 'prob_regime_2' : probabilités smoothed

Usage dans une stratégie :
    from indicators.markov_switching import calculate_markov_switching

    markov = calculate_markov_switching(df, resample_to="1h", k_regimes=3)
    df["market_phase"] = markov["phase"]
"""

from __future__ import annotations

import logging
from typing import Dict

import numpy as np
import pandas as pd

try:
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
    STATSMODELS_AVAILABLE = True
except ImportError:
    STATSMODELS_AVAILABLE = False

logger = logging.getLogger(__name__)


def _calculate_markov_core(
    df: pd.DataFrame,
    price_column: str = "close",
    k_regimes: int = 3,
    switching_variance: bool = True,
    min_periods: int = 252,
) -> Dict[str, pd.Series]:
    """Version core : fit sur le df fourni (doit être stable, ex: daily ou hourly)."""
    if not STATSMODELS_AVAILABLE:
        raise ImportError("statsmodels requis pour Markov Switching Model")

    if len(df) < min_periods:
        logger.warning(f"Données insuffisantes ({len(df)} < {min_periods})")
        empty = pd.Series(np.nan, index=df.index)
        result = {"regime": empty.copy(), "phase": empty.copy().astype(object)}
        for i in range(k_regimes):
            result[f"prob_regime_{i}"] = empty.copy()
        return result

    returns = np.log(df[price_column]).diff().dropna()

    try:
        model = MarkovRegression(
            returns,
            k_regimes=k_regimes,
            switching_variance=switching_variance,
        )
        res = model.fit(disp=False)
    except Exception as e:
        logger.error(f"Fit Markov échoué : {e}")
        empty = pd.Series(np.nan, index=df.index)
        result = {"regime": empty.copy(), "phase": empty.copy().astype(object)}
        for i in range(k_regimes):
            result[f"prob_regime_{i}"] = empty.copy()
        return result

    probs = res.smoothed_marginal_probabilities
    probs.index = returns.index
    regime = probs.idxmax(axis=1)

    # Identification automatique des régimes par moyenne des returns
    means = res.params[:k_regimes]
    bull_regime = int(np.argmax(means))
    bear_regime = int(np.argmin(means))

    if k_regimes == 3:
        remaining = {0, 1, 2} - {bull_regime, bear_regime}
        ranging_regime = remaining.pop()
        phase_map = {bull_regime: "Bull", bear_regime: "Bear", ranging_regime: "Ranging"}
    else:
        phase_map = {bull_regime: "Bull", bear_regime: "Bear"}

    phase = regime.map(phase_map).fillna("Unknown")

    result = {
        "regime": regime.reindex(df.index).ffill(),
        "phase": phase.reindex(df.index).ffill(),
    }
    for i in range(k_regimes):
        result[f"prob_regime_{i}"] = probs[i].reindex(df.index).ffill()

    logger.info(
        f"Markov fitted : Bull={bull_regime} (μ={means[bull_regime]:.4f}), "
        f"Bear={bear_regime} (μ={means[bear_regime]:.4f})"
    )

    return result


def calculate_markov_switching(
    df: pd.DataFrame,
    resample_to: str | None = "1h",
    price_column: str = "close",
    k_regimes: int = 3,
    min_periods: int = 252,
    df_reference: pd.DataFrame | None = None,
) -> Dict[str, pd.Series]:
    """
    Calcule les phases de marché via Markov Switching Model.

    IMPORTANT: Pour les timeframes courts (5m, 15m, 30m), il est recommandé
    de fournir df_reference avec des données 1h/4h chargées séparément.
    Cela garantit d'avoir assez de données pour le modèle (252+ points).

    Args:
        df: DataFrame OHLCV avec DatetimeIndex (pour l'alignement final)
        resample_to: Timeframe de resample ("1h", "4h", "1d") - utilisé seulement si df_reference est None
        price_column: Colonne de prix (défaut: 'close')
        k_regimes: Nombre de régimes (défaut: 3 pour Bull/Bear/Ranging)
        min_periods: Minimum de périodes après resample (défaut: 252)
        df_reference: DataFrame OHLCV du TF supérieur (1h/4h) chargé séparément.
                      Si fourni, utilise ces données directement sans resample.

    Returns:
        Dict avec 'regime', 'phase', et 'prob_regime_X' alignés sur df.index
    """
    # Si df_reference fourni, l'utiliser directement (données 1h/4h pré-chargées)
    if df_reference is not None and len(df_reference) >= min_periods:
        logger.info(
            f"Markov: utilisation données référence ({len(df_reference)} barres)"
        )
        markov = _calculate_markov_core(
            df_reference, price_column, k_regimes, min_periods=min_periods
        )
        # Réaligner sur l'index original du backtest
        for key, series in markov.items():
            markov[key] = series.reindex(df.index, method="ffill")
        return markov

    # Sinon, tenter le resample classique
    if resample_to is None:
        return _calculate_markov_core(
            df, price_column, k_regimes, min_periods=min_periods
        )

    # Resample à timeframe supérieur pour stabilité
    df_resampled = df.resample(resample_to).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()

    # Vérifier qu'on a assez de données après resample
    if len(df_resampled) < min_periods:
        logger.warning(
            f"Données insuffisantes après resample vers {resample_to}: "
            f"{len(df_resampled)} < {min_periods}. "
            f"Fournissez df_reference avec des données 1h/4h pré-chargées."
        )

    markov = _calculate_markov_core(
        df_resampled, price_column, k_regimes, min_periods=min_periods
    )

    # Réaligner + forward-fill sur index original
    for key, series in markov.items():
        markov[key] = series.reindex(df.index, method="ffill")

    return markov
