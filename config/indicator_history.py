"""Module-ID: config.indicator_history

Purpose: Persistance inter-sessions de la mémoire d'indicateurs pour le Strategy Builder.
         Mémorise les indicateurs et familles utilisés dans les runs précédents afin
         d'alimenter un système de pénalités de répétition et de bannissements temporaires.

Role in pipeline: configuration / diversité indicateurs

Key components:
    - load_policy()         : charge indicator_policy.json avec valeurs par défaut
    - load_history()        : lit le JSON d'historique depuis le disque
    - save_history()        : écrit le JSON d'historique sur le disque (atomique)
    - update_history()      : intègre un run dans l'historique et gère les bannissements
    - get_banned_indicators(): retourne l'ensemble des indicateurs actuellement bannis
    - get_recent_indicators(): retourne la liste FIFO des indicateurs des N derniers runs
    - get_recent_families() : retourne la liste FIFO des familles des N derniers runs
    - build_indicator_to_family_map(): construit le mapping indicateur → famille

Inputs:  liste d'indicateurs utilisés dans le run courant
Outputs: bannissements, listes d'indicateurs/familles récents

Format JSON d'historique:
{
  "recent_runs":   [["ind1", "ind2"], ...],      // FIFO, chaque élément = run
  "recent_families": [["fam1", "fam2"], ...],    // FIFO des familles par run
  "banned_indicators": {"ind_name": <runs_restants>, ...}
}
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

# Verrou global pour les accès concurrent en mode autonome 24/24
_HISTORY_LOCK = threading.Lock()

# Racine du projet : deux niveaux au-dessus de ce fichier (config/indicator_history.py)
_PROJECT_ROOT = Path(__file__).parent.parent

_DEFAULT_POLICY: dict[str, Any] = {
    "enabled": True,
    "history_length": 10,
    "ban_threshold": 4,
    "ban_duration": 3,
    "family_penalty_runs": 3,
    "previous_penalty": 0.50,
    "novelty_bonus": 0.60,
    "family_penalty": 0.25,
    "family_bonus": 0.15,
    "category_sampling_enabled": False,
    "category_min_families": 2,
    "history_file": "config/indicator_history.json",
}

_EMPTY_HISTORY: dict[str, Any] = {
    "recent_runs": [],
    "recent_families": [],
    "banned_indicators": {},
}

# Cache module-level pour éviter des recharges répétées sous workload intensif
_policy_cache: dict[str, Any] | None = None
_policy_mtime: float = 0.0


def _policy_file() -> Path:
    return _PROJECT_ROOT / "config" / "indicator_policy.json"


def load_policy(force_reload: bool = False) -> dict[str, Any]:
    """Charge la politique depuis ``config/indicator_policy.json``.

    Fusionne avec les valeurs par défaut afin que les clés manquantes
    ne provoquent pas d'erreur.  Un cache en mémoire évite des relectures
    fréquentes ; passer ``force_reload=True`` invalide ce cache.
    """
    global _policy_cache, _policy_mtime

    path = _policy_file()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return dict(_DEFAULT_POLICY)

    if not force_reload and _policy_cache is not None and mtime == _policy_mtime:
        return dict(_policy_cache)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, json.JSONDecodeError):
        raw = {}

    merged = dict(_DEFAULT_POLICY)
    merged.update({k: v for k, v in raw.items() if not k.startswith("_")})
    _policy_cache = merged
    _policy_mtime = mtime
    return dict(merged)


def _history_path(policy: dict[str, Any] | None = None) -> Path:
    pol = policy or load_policy()
    rel = str(pol.get("history_file", "config/indicator_history.json") or "config/indicator_history.json")
    return _PROJECT_ROOT / rel


def load_history(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lit le JSON d'historique depuis le disque.

    Retourne un historique vide en cas d'absence ou de corruption du fichier.
    Thread-safe.
    """
    path = _history_path(policy)
    with _HISTORY_LOCK:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return _clone_empty()
            return _sanitize_history(raw)
        except (OSError, json.JSONDecodeError):
            return _clone_empty()


def save_history(data: dict[str, Any], policy: dict[str, Any] | None = None) -> None:
    """Écrit le JSON d'historique de façon atomique (write → rename).

    Thread-safe.
    """
    path = _history_path(policy)
    serializable = _sanitize_history(data)
    with _HISTORY_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=path.parent,
                suffix=".tmp",
                prefix=".indicator_history_",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(serializable, fh, ensure_ascii=False, indent=2)
                os.replace(tmp_path, path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError:
            pass  # Écriture impossible : on continue sans planter le Builder


def update_history(
    current_used_indicators: list[str],
    families_used: list[str] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Intègre un run dans l'historique et recalcule les bannissements.

    Args:
        current_used_indicators: Indicateurs utilisés dans le run qui vient de terminer.
        families_used: Familles d'indicateurs repérées dans ce run (optionnel).
        policy: Politique chargée ; si None, chargée depuis le fichier.

    Returns:
        L'historique mis à jour (également sauvegardé sur le disque).

    """
    pol = policy or load_policy()
    if not pol.get("enabled", True):
        return _clone_empty()

    history = load_history(pol)
    history_length: int = int(pol.get("history_length", 10))
    ban_threshold: int = int(pol.get("ban_threshold", 4))
    ban_duration: int = int(pol.get("ban_duration", 3))

    # Normaliser la liste d'indicateurs
    normalized = [str(ind).strip().lower() for ind in (current_used_indicators or []) if str(ind).strip()]
    norm_families = [str(f).strip().lower() for f in (families_used or []) if str(f).strip()]

    # Ajouter le run courant à la FIFO
    recent_runs: list[list[str]] = list(history.get("recent_runs", []) or [])
    recent_runs.append(normalized)
    if len(recent_runs) > history_length:
        recent_runs = recent_runs[-history_length:]

    recent_families: list[list[str]] = list(history.get("recent_families", []) or [])
    recent_families.append(norm_families)
    if len(recent_families) > history_length:
        recent_families = recent_families[-history_length:]

    # Décrémenter les compteurs de bannissement (durée restante -1)
    banned: dict[str, int] = {
        str(k): int(v) for k, v in (history.get("banned_indicators", {}) or {}).items() if int(v) > 0
    }
    # Décrémenter tous les bannis de 1 pour ce run
    expired = [k for k, v in banned.items() if v <= 1]
    for k in expired:
        del banned[k]
    for k in list(banned.keys()):
        banned[k] = banned[k] - 1

    # Compter les apparitions de chaque indicateur sur la fenêtre récente
    freq: dict[str, int] = {}
    for run in recent_runs:
        for ind in run:
            freq[ind] = freq.get(ind, 0) + 1

    # Bannir les indicateurs dépassant le seuil (sauf ceux déjà bannis)
    for ind, count in freq.items():
        if count >= ban_threshold and ind not in banned:
            banned[ind] = ban_duration

    history["recent_runs"] = recent_runs
    history["recent_families"] = recent_families
    history["banned_indicators"] = banned

    save_history(history, pol)
    return history


def get_banned_indicators(
    history: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> set[str]:
    """Retourne l'ensemble des noms d'indicateurs actuellement bannis."""
    h = history if history is not None else load_history(policy)
    banned = h.get("banned_indicators", {}) or {}
    return {str(k).strip().lower() for k, v in banned.items() if int(v) > 0}


def get_recent_indicators(
    history: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    n_runs: int | None = None,
) -> list[str]:
    """Retourne la liste dédupliquée des indicateurs des N derniers runs (FIFO).

    Args:
        n_runs: Si fourni, ne considère que les N derniers runs (None = tous).

    """
    h = history if history is not None else load_history(policy)
    recent_runs: list[list[str]] = list(h.get("recent_runs", []) or [])
    if n_runs is not None:
        recent_runs = recent_runs[-n_runs:]
    seen: list[str] = []
    seen_set: set[str] = set()
    for run in recent_runs:
        for ind in run:
            key = str(ind).strip().lower()
            if key and key not in seen_set:
                seen.append(key)
                seen_set.add(key)
    return seen


def get_recent_families(
    history: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    n_runs: int | None = None,
) -> list[str]:
    """Retourne la liste dédupliquée des familles des N derniers runs."""
    pol = policy or load_policy()
    h = history if history is not None else load_history(pol)
    n = n_runs if n_runs is not None else int(pol.get("family_penalty_runs", 3))
    recent: list[list[str]] = list(h.get("recent_families", []) or [])
    if n is not None:
        recent = recent[-n:]
    seen: list[str] = []
    seen_set: set[str] = set()
    for run_fams in recent:
        for fam in run_fams:
            key = str(fam).strip().lower()
            if key and key not in seen_set:
                seen.append(key)
                seen_set.add(key)
    return seen


def build_indicator_to_family_map() -> dict[str, str]:
    """Construit le mapping {indicateur → famille} depuis _INDICATOR_FAMILIES.

    Importe `builder_objectives._INDICATOR_FAMILIES` dynamiquement pour éviter
    les dépendances circulaires.  Si l'import échoue, retourne un dict vide.
    """
    try:
        from agents.builder_objectives import _INDICATOR_FAMILIES  # type: ignore[import]
    except ImportError:
        return {}
    mapping: dict[str, str] = {}
    for family_key, family_data in _INDICATOR_FAMILIES.items():
        primary = family_data.get("primary", []) if isinstance(family_data, dict) else []
        for ind in primary:
            key = str(ind).strip().lower()
            if key and key not in mapping:
                mapping[key] = family_key
    return mapping


def infer_families_from_indicators(
    indicators: list[str],
    indicator_to_family: dict[str, str] | None = None,
) -> list[str]:
    """Déduit la liste des familles touchées par un ensemble d'indicateurs."""
    mapping = indicator_to_family if indicator_to_family is not None else build_indicator_to_family_map()
    families: list[str] = []
    seen: set[str] = set()
    for ind in indicators:
        key = str(ind).strip().lower()
        fam = mapping.get(key)
        if fam and fam not in seen:
            families.append(fam)
            seen.add(fam)
    return families


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------


def _clone_empty() -> dict[str, Any]:
    return {
        "recent_runs": [],
        "recent_families": [],
        "banned_indicators": {},
    }


def _sanitize_history(raw: dict[str, Any]) -> dict[str, Any]:
    """Valide et nettoie un dict d'historique brut."""
    recent_runs = raw.get("recent_runs", [])
    if not isinstance(recent_runs, list):
        recent_runs = []
    else:
        recent_runs = [[str(ind) for ind in run] if isinstance(run, list) else [] for run in recent_runs]

    recent_families = raw.get("recent_families", [])
    if not isinstance(recent_families, list):
        recent_families = []
    else:
        recent_families = [[str(f) for f in fam] if isinstance(fam, list) else [] for fam in recent_families]

    banned = raw.get("banned_indicators", {})
    if not isinstance(banned, dict):
        banned = {}
    else:
        banned = {str(k): max(0, int(v)) for k, v in banned.items() if str(k).strip()}

    return {
        "recent_runs": recent_runs,
        "recent_families": recent_families,
        "banned_indicators": banned,
    }
