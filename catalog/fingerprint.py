"""
Module-ID: catalog.fingerprint

Purpose: Canonicalisation JSON et fingerprint SHA256 pour déduplication de variants.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np


def _normalize_value(value: Any) -> Any:
    """Normalise les types pour sérialisation JSON déterministe."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Inf" if value > 0 else "-Inf"
        # Normaliser les flottants pour éviter les différences de précision
        if value == int(value) and abs(value) < 2**53:
            return int(value)
        return round(value, 10)
    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(v) for v in value]
    return value


def canonical_json(obj: Any) -> str:
    """
    Produit une représentation JSON canonique (déterministe).

    - Clés triées
    - Séparateurs compacts
    - Flottants normalisés
    - Types numpy convertis
    """
    normalized = _normalize_value(obj)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint_sha256(obj: Any) -> str:
    """Calcule le SHA256 de la forme canonique JSON d'un objet."""
    payload = canonical_json(obj).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
