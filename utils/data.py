"""
Module-ID: utils.data

Purpose: Utilitaires analyse/validation données OHLCV (détection gaps, stats).

Role in pipeline: data quality

Key components: detect_gaps(), DataFrame validators

Inputs: pandas DataFrame avec DatetimeIndex OHLCV

Outputs: Gap dict {gaps_count, gaps_pct, gaps_sample}, validation results

Dependencies: pandas

Conventions: DatetimeIndex requis; fréquence inférée si non fournie.

Read-if: Modification validation données ou détection gaps.

Skip-if: Vous utilisez juste detect_gaps().
"""

from typing import Optional

import pandas as pd


def detect_gaps(df: pd.DataFrame, expected_freq: Optional[str] = None) -> dict:
    """
    Détecte les gaps temporels dans un DataFrame OHLCV.

    Les gaps sont des périodes manquantes dans la série temporelle qui devraient
    normalement être présentes selon la fréquence attendue.

    Args:
        df: DataFrame avec DatetimeIndex contenant les données OHLCV
        expected_freq: Fréquence attendue ('1h', '4h', '1d', etc.). Si None, sera inférée.

    Returns:
        Dict avec:
            - gaps_count: Nombre total de gaps détectés
            - gaps_pct: Pourcentage de données manquantes
            - gaps_sample: Échantillon (max 5) des timestamps manquants
            - note: Information supplémentaire si détection impossible

    Examples:
        >>> df = load_ohlcv_data()
        >>> gaps = detect_gaps(df, expected_freq='1h')
        >>> print(f"Gaps trouvés : {gaps['gaps_count']} ({gaps['gaps_pct']:.2f}%)")
    """
    # Vérifier que l'index est DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        return {
            "gaps_count": 0,
            "gaps_pct": 0.0,
            "gaps_sample": [],
            "note": "not_datetime_index"
        }

    # Inférer fréquence si non fournie
    if expected_freq is None:
        expected_freq = pd.infer_freq(df.index)

    if expected_freq is None:
        return {
            "gaps_count": 0,
            "gaps_pct": 0.0,
            "gaps_sample": [],
            "note": "freq_not_inferable"
        }

    # Créer série complète attendue
    try:
        full_index = pd.date_range(
            start=df.index[0],
            end=df.index[-1],
            freq=expected_freq
        )
    except Exception:
        return {
            "gaps_count": 0,
            "gaps_pct": 0.0,
            "gaps_sample": [],
            "note": "freq_invalid"
        }

    # Identifier gaps (timestamps manquants)
    missing = full_index.difference(df.index)

    gaps_count = len(missing)
    gaps_pct = (gaps_count / len(full_index) * 100) if len(full_index) > 0 else 0.0

    return {
        "gaps_count": gaps_count,
        "gaps_pct": gaps_pct,
        "gaps_sample": missing.tolist()[:5] if gaps_count > 0 else []
    }


__all__ = ["detect_gaps"]
