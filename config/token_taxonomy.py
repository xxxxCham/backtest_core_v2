"""Module-ID: config.token_taxonomy

Purpose: Taxonomie naturelle des tokens crypto (univers primaire + bucket de
         liquidité) consommée par catalog.graduation phase P3 pour la
         généralisation cross-token.

Role in pipeline: Configuration / lookup

Key components: load_token_taxonomy, get_token_universe, get_token_bucket,
                get_natural_universe_id, get_tokens_in_universe,
                get_adjacent_bucket_tokens, get_cross_universe_diagnostic_tokens.

Inputs: config/token_taxonomy.json

Outputs: Listes de symbols et identifiants d'univers naturel.

Dependencies: json (stdlib), pathlib (stdlib).

Conventions: Path résolu via Path(__file__).resolve().parent — résilient au
             changement de cwd (Streamlit). Symbols normalisés en upper-case.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_TAXONOMY_PATH = Path(__file__).resolve().parent / "token_taxonomy.json"
_CACHE: dict[str, Any] | None = None
_CACHE_LOCK = Lock()


def _normalize_symbol(symbol: Any) -> str:
    return str(symbol or "").strip().upper()


def load_token_taxonomy(*, force_reload: bool = False) -> dict[str, Any]:
    """Charge la taxonomie depuis token_taxonomy.json (cache process).

    Args:
        force_reload: Si True, ignore le cache et relit le fichier.

    Returns:
        Dict avec clés: version, primary_universes, liquidity_buckets,
        bucket_order, tokens.

    Raises:
        FileNotFoundError: Si le JSON est manquant.
        json.JSONDecodeError: Si le JSON est invalide.
    """
    global _CACHE
    with _CACHE_LOCK:
        if _CACHE is not None and not force_reload:
            return _CACHE
        if not _TAXONOMY_PATH.exists():
            raise FileNotFoundError(
                f"Token taxonomy missing: {_TAXONOMY_PATH}\n"
                "Run the graduation P3 refresh pipeline or restore the file.",
            )
        with _TAXONOMY_PATH.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError(f"Token taxonomy must be a JSON object, got {type(payload).__name__}")
        _CACHE = payload
        return _CACHE


def _tokens_map() -> dict[str, dict[str, Any]]:
    payload = load_token_taxonomy()
    tokens = payload.get("tokens") or {}
    if not isinstance(tokens, dict):
        return {}
    return tokens


def _bucket_order() -> list[str]:
    payload = load_token_taxonomy()
    raw = payload.get("bucket_order")
    if isinstance(raw, list) and raw:
        return [str(item) for item in raw if str(item).strip()]
    return ["L0_mega", "L1_high", "L2_mid", "L3_low", "L4_micro"]


def get_token_entry(symbol: str) -> dict[str, Any] | None:
    """Retourne le mapping brut d'un symbol ou None si inconnu."""
    normalized = _normalize_symbol(symbol)
    if not normalized:
        return None
    entry = _tokens_map().get(normalized)
    return entry if isinstance(entry, dict) else None


def get_token_universe(symbol: str) -> str | None:
    """Retourne le primary_universe d'un token (ex: 'DEFI_DEX_LENDING_PERPS_YIELD')."""
    entry = get_token_entry(symbol)
    if not entry:
        return None
    universe = entry.get("primary_universe")
    return str(universe).strip() if universe else None


def get_token_bucket(symbol: str) -> str | None:
    """Retourne le liquidity_bucket d'un token (ex: 'L2_mid')."""
    entry = get_token_entry(symbol)
    if not entry:
        return None
    bucket = entry.get("liquidity_bucket")
    return str(bucket).strip() if bucket else None


def get_token_tags(symbol: str) -> list[str]:
    """Retourne les secondary_tags d'un token (toujours une liste)."""
    entry = get_token_entry(symbol)
    if not entry:
        return []
    tags = entry.get("secondary_tags") or []
    if not isinstance(tags, list):
        return []
    return [str(tag).strip() for tag in tags if str(tag).strip()]


def get_natural_universe_id(symbol: str) -> str | None:
    """Identifiant composite '{primary_universe}:{liquidity_bucket}'.

    Retourne None si l'un des deux est inconnu.
    """
    universe = get_token_universe(symbol)
    bucket = get_token_bucket(symbol)
    if not universe or not bucket:
        return None
    return f"{universe}:{bucket}"


def _matches(
    entry: dict[str, Any],
    *,
    universe: str | None,
    bucket: str | None,
) -> bool:
    if universe is not None and entry.get("primary_universe") != universe:
        return False
    if bucket is not None and entry.get("liquidity_bucket") != bucket:
        return False
    return True


def get_tokens_in_universe(
    universe: str,
    bucket: str | None = None,
    *,
    exclude: list[str] | None = None,
) -> list[str]:
    """Retourne les tokens d'un primary_universe, optionnellement filtrés par bucket.

    Args:
        universe: Nom du primary_universe (ex: 'MAJORS_RESERVE_BETA').
        bucket: Si fourni, ne retourne que les tokens de ce liquidity_bucket.
        exclude: Symbols à exclure (typiquement le source de la stratégie).

    Returns:
        Liste triée de symbols normalisés (upper-case).
    """
    exclude_set = {_normalize_symbol(item) for item in (exclude or []) if str(item).strip()}
    universe_normalized = str(universe or "").strip()
    if not universe_normalized:
        return []
    bucket_normalized = str(bucket or "").strip() or None
    result: list[str] = []
    for symbol, entry in _tokens_map().items():
        if not isinstance(entry, dict):
            continue
        if not _matches(entry, universe=universe_normalized, bucket=bucket_normalized):
            continue
        if symbol in exclude_set:
            continue
        result.append(symbol)
    return sorted(result)


def get_adjacent_bucket_tokens(
    universe: str,
    bucket: str,
    *,
    exclude: list[str] | None = None,
) -> list[str]:
    """Retourne les tokens du même primary_universe dans les buckets voisins (L_n±1).

    Utile en fallback quand le pool exact universe:bucket est trop petit.
    """
    order = _bucket_order()
    bucket_normalized = str(bucket or "").strip()
    if bucket_normalized not in order:
        return []
    idx = order.index(bucket_normalized)
    neighbors = []
    if idx - 1 >= 0:
        neighbors.append(order[idx - 1])
    if idx + 1 < len(order):
        neighbors.append(order[idx + 1])
    result: list[str] = []
    for neighbor in neighbors:
        result.extend(get_tokens_in_universe(universe, neighbor, exclude=exclude))
    return sorted(set(result))


def list_primary_universes() -> list[str]:
    """Retourne la liste des primary_universes déclarés (clé du JSON, triée)."""
    payload = load_token_taxonomy()
    universes = payload.get("primary_universes") or {}
    if not isinstance(universes, dict):
        return []
    return sorted(str(key) for key in universes.keys() if str(key).strip())


def get_cross_universe_diagnostic_tokens(
    universe: str,
    *,
    n_per_universe: int = 2,
    bucket_preference: list[str] | None = None,
) -> list[str]:
    """Retourne un échantillon de tokens d'autres univers (pour diagnostic non-bloquant).

    Args:
        universe: Univers source à exclure du sample.
        n_per_universe: Nombre de tokens à prélever par univers étranger.
        bucket_preference: Ordre de préférence des buckets (défaut: L1_high > L2_mid > L0_mega > L3_low > L4_micro).

    Returns:
        Liste triée de symbols, jamais incluant l'univers source.
    """
    universe_normalized = str(universe or "").strip()
    if not universe_normalized:
        return []
    n = max(0, int(n_per_universe))
    if n == 0:
        return []
    preference = list(bucket_preference or ["L1_high", "L2_mid", "L0_mega", "L3_low", "L4_micro"])
    result: set[str] = set()
    for other_universe in list_primary_universes():
        if other_universe == universe_normalized:
            continue
        picked: list[str] = []
        for bucket in preference:
            candidates = get_tokens_in_universe(other_universe, bucket)
            for symbol in candidates:
                if symbol in picked:
                    continue
                picked.append(symbol)
                if len(picked) >= n:
                    break
            if len(picked) >= n:
                break
        result.update(picked[:n])
    return sorted(result)


def reset_cache() -> None:
    """Vide le cache process (utile pour les tests)."""
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = None
