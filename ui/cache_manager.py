"""
Module de gestion du cache pour l'interface utilisateur.

Fournit un cache intelligent avec TTL pour éviter les rechargements répétés
des données OHLCV.
"""
from __future__ import annotations

import gc
import time
from typing import Optional

import pandas as pd

# Cache global pour éviter rechargements répétés
_DATA_CACHE = {}
_CACHE_MAX_SIZE = 10  # Nombre max d'entrées en cache
_CACHE_TTL = 300  # TTL en secondes (5 minutes)


def get_cached_data(symbol: str, timeframe: str, start_date, end_date) -> Optional[pd.DataFrame]:
    """
    Récupère les données du cache si disponibles et valides.

    Args:
        symbol: Symbole du token (ex: BTCUSDC)
        timeframe: Timeframe (ex: 1h)
        start_date: Date de début
        end_date: Date de fin

    Returns:
        DataFrame des données ou None si pas en cache/expiré
    """
    cache_key = f"{symbol}_{timeframe}_{start_date}_{end_date}"

    if cache_key in _DATA_CACHE:
        cached_entry = _DATA_CACHE[cache_key]
        # Vérifier TTL
        if time.time() - cached_entry["timestamp"] < _CACHE_TTL:
            return cached_entry["data"].copy()  # Copie défensive
        else:
            # Nettoyer entrée expirée
            del _DATA_CACHE[cache_key]

    return None


def cache_data(symbol: str, timeframe: str, start_date, end_date, df: pd.DataFrame) -> None:
    """
    Stocke les données en cache avec nettoyage automatique.

    Args:
        symbol: Symbole du token
        timeframe: Timeframe
        start_date: Date de début
        end_date: Date de fin
        df: DataFrame à mettre en cache
    """
    cache_key = f"{symbol}_{timeframe}_{start_date}_{end_date}"

    # Nettoyer le cache si trop plein
    if len(_DATA_CACHE) >= _CACHE_MAX_SIZE:
        # Supprimer l'entrée la plus ancienne
        oldest_key = min(_DATA_CACHE.keys(),
                         key=lambda k: _DATA_CACHE[k]["timestamp"])
        del _DATA_CACHE[oldest_key]
        gc.collect()  # Forcer nettoyage mémoire

    _DATA_CACHE[cache_key] = {
        "data": df.copy(),
        "timestamp": time.time()
    }


def clear_data_cache() -> None:
    """Nettoie complètement le cache de données."""
    global _DATA_CACHE
    _DATA_CACHE.clear()
    gc.collect()


def get_cache_stats() -> dict:
    """Retourne les statistiques du cache."""
    current_time = time.time()
    valid_entries = 0
    expired_entries = 0

    for entry in _DATA_CACHE.values():
        if current_time - entry["timestamp"] < _CACHE_TTL:
            valid_entries += 1
        else:
            expired_entries += 1

    return {
        "total_entries": len(_DATA_CACHE),
        "valid_entries": valid_entries,
        "expired_entries": expired_entries,
        "max_size": _CACHE_MAX_SIZE,
        "ttl_seconds": _CACHE_TTL,
    }
