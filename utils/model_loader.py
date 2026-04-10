"""
Module-ID: utils.model_loader

Purpose: Chargement et acces aux modeles depuis models.json avec resolution
de chemins contemporaine (C/K/L/D) et alias de noms historiques.

Role in pipeline: configuration

Key components: load_models_json(), get_model_by_id(), get_models_json_path()

Inputs: models.json path, env vars MODELS_JSON_PATH / OLLAMA_MODELS /
MODEL_LIBRARY_ROOTS / HUGGINGFACE_ARCHIVE_ROOT.

Outputs: Dict de modeles avec infos (path, size, use_case, etc.)

Dependencies: json, pathlib

Conventions: fallback progressif si un chemin cible n'existe pas encore;
cache en memoire; noms Ollama normalises pour eviter les regressions de selection.

Read-if: Modification de la logique de chargement des modeles.

Skip-if: Vous utilisez directement get_available_models().
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from utils.log import get_logger

logger = get_logger(__name__)

CURRENT_MODELS_JSON_PATH = Path(r"C:\AI\models\catalog\models.json")
CURRENT_OLLAMA_MODELS_ROOT = Path(r"C:\AI\ollama\models")
CURRENT_HUGGINGFACE_ARCHIVE_ROOT = Path(r"L:\models")

LEGACY_MODELS_JSON_CANDIDATES = (
    Path(r"D:\models\models.json"),
)

LEGACY_OLLAMA_MODELS_CANDIDATES = (
    Path(r"D:\models\ollama"),
    Path(r"D:\models\models_via_ollamaGUI"),
)

LEGACY_HUGGINGFACE_ARCHIVE_ROOTS = (
    Path(r"D:\models\huggingface"),
)

DEFAULT_MODELS_JSON_CANDIDATES = (
    CURRENT_MODELS_JSON_PATH,
    Path(r"C:\AI\models\models.json"),
)

DEFAULT_OLLAMA_MODELS_CANDIDATES = (
    CURRENT_OLLAMA_MODELS_ROOT,
)

DEFAULT_MODEL_LIBRARY_ROOTS = (
    Path(r"K:\models"),
    Path(r"L:\models"),
    Path(r"C:\AI\models\library"),
)

DEFAULT_HUGGINGFACE_ARCHIVE_ROOTS = (
    CURRENT_HUGGINGFACE_ARCHIVE_ROOT,
    Path(r"C:\AI\models\library\huggingface"),
)

# Mapping des anciens noms vers les noms runtime actuels.
MODEL_NAME_ALIASES = {
    "alia-40b-local:latest": "alia-40b-local",
    "devstral-small-2": "devstral-small-2:24b",
    "deepseek-coder-33b-local:latest": "deepseek-coder-33b-local",
    "deepseek-moe-16b-local:latest": "deepseek-moe-16b-local",
    "deepseek-r1-14b-local:latest": "deepseek-r1-14b-local",
    "deepseek-r1-14b-local": "deepseek-r1-distill:14b",
    "gemma4:26b-a4b": "gemma4:26b",
    "gemma4:26b-a4b-it": "gemma4:26b",
    "gemma4:26b-a4b-it-q4_k_m": "gemma4:26b",
    "gemma4:26b-a4b-it-q8_0": "gemma4:26b",
    "gemma4:31b-it": "gemma4:31b",
    "gemma4:31b-it-bf16": "gemma4:31b",
    "gemma4:31b-it-q4_k_m": "gemma4:31b",
    "gemma4:31b-it-q8_0": "gemma4:31b",
    "glm-4.7-flash-23b-local:latest": "glm-4.7-flash-23b-local",
    "lfm2": "lfm2:24b",
    "llama3.3-70b-2gpu": "llama3.3:70b-instruct-q4_K_M",
    "llama3.3-70b-optimized": "llama3.3:70b-instruct-q4_K_M",
    "llama3.3:70b": "llama3.3:70b-instruct-q4_K_M",
    "m-moe-4x7b-dark-multiverse-uc-e32-24b-max-d_au-q6_k:latest": "m-moe-4x7b-dark-multiverse-uc-e32-24b-max-d_au-q6_k",
    "nemotron-cascade-14b-local:latest": "nemotron-cascade-14b-local",
    "nemotron-cascade-14b-thinking-claude-4.5-opus-distill.q8_0": "nemotron-cascade-14b-local",
    "nemotron-orchestrator-8b:latest": "nemotron-orchestrator-8b",
    "qwen3.5": "qwen3.5:35b",
    "qwen3-coder-40b-local": "qwen3-coder:30b",
    "qwen3-coder-next-40b-q3_k_xl": "qwen3-coder:30b",
    "qwen3-coder-next-40b-q3_k_xl:latest": "qwen3-coder:30b",
    "qwen3-coder-next": "qwen3-coder:30b",
    "qwen3-coder-next:q4_k_m": "qwen3-coder:30b",
    "qwen3-coder-next-q4_k_m": "qwen3-coder:30b",
    "qwen3-coder:30b-a3b-instruct": "qwen3-coder:30b",
    "qwen3-30b-a3b": "qwen3-30b-a3b:q4_k_m",
    "qwen3-30b-a3b-q4_k_m": "qwen3-30b-a3b:q4_k_m",
    "qwen3-48b-savant:latest": "qwen3-48b-savant",
    "qwen3-vl": "qwen3-vl:32b",
    "qwen3-vl-30b": "qwen3-vl:32b",
    "qwen3-vl:30b": "qwen3-vl:32b",
}

# Cache en memoire
_models_cache: Optional[Dict] = None


def _windows_to_wsl_path(path: Path) -> Optional[Path]:
    path_str = str(path)
    if len(path_str) < 3 or path_str[1] != ":":
        return None

    drive = path_str[0].lower()
    rest = path_str[2:].lstrip("\\/")
    if not rest:
        return None

    rest_posix = rest.replace("\\", "/")
    return Path(f"/mnt/{drive}/{rest_posix}")


def _iter_unique_paths(paths: Iterable[Path]) -> Iterable[Path]:
    seen: set[str] = set()
    for path in paths:
        raw = str(path).strip()
        if not raw:
            continue
        key = raw.lower()
        if key in seen:
            continue
        seen.add(key)
        yield Path(raw)


def _split_env_paths(value: str) -> List[Path]:
    if not value:
        return []
    return [Path(chunk.strip()) for chunk in value.split(";") if chunk.strip()]


def _get_ollama_desktop_db_candidates() -> List[Path]:
    """Retourne les emplacements probables de la base SQLite Ollama Desktop."""
    candidates: List[Path] = []
    local_appdata = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
    if local_appdata:
        candidates.append(Path(local_appdata) / "Ollama" / "db.sqlite")

    home = Path.home()
    candidates.append(home / "AppData" / "Local" / "Ollama" / "db.sqlite")
    return list(_iter_unique_paths(candidates))


def get_ollama_desktop_models_root() -> Optional[Path]:
    """Lit le store modèles configuré dans l'application Ollama Desktop."""
    for db_path in _get_ollama_desktop_db_candidates():
        if not db_path.exists():
            continue
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(str(db_path), timeout=1.0)
            row = connection.execute(
                "SELECT models FROM settings ORDER BY id DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error as exc:
            logger.debug("Lecture config Ollama impossible depuis %s: %s", db_path, exc)
            continue
        finally:
            if connection is not None:
                connection.close()

        if not row:
            continue
        configured = str(row[0] or "").strip()
        if configured:
            return Path(configured)
    return None


def _prefer_current_target(
    configured: Iterable[Path],
    current_target: Path,
    legacy_targets: Iterable[Path],
) -> List[Path]:
    ordered = list(_iter_unique_paths(configured))
    if not ordered or not current_target.exists():
        return ordered

    legacy_keys = {str(path).strip().lower() for path in legacy_targets if str(path).strip()}
    if not legacy_keys:
        return ordered

    configured_keys = {str(path).strip().lower() for path in ordered if str(path).strip()}
    if configured_keys.isdisjoint(legacy_keys):
        return ordered

    return list(_iter_unique_paths([current_target, *ordered]))


def normalize_model_name(name: str) -> str:
    """Normalise un nom de modele et resout les alias historiques."""
    value = str(name or "").strip()
    if not value:
        return ""
    if value.endswith(":latest"):
        value = value[:-7]
    return MODEL_NAME_ALIASES.get(value.lower(), value)


def _entry_identifiers(entry: Dict) -> List[str]:
    identifiers: List[str] = []

    def add(candidate: object) -> None:
        if not isinstance(candidate, str):
            return
        raw = candidate.strip()
        normalized = normalize_model_name(raw)
        for value in (raw, normalized):
            if value and value not in identifiers:
                identifiers.append(value)

    add(entry.get("id"))
    add(entry.get("ollama_name"))
    add(entry.get("model_name"))
    add(entry.get("name"))

    model_name = str(entry.get("model_name") or "").strip()
    tag = str(entry.get("tag") or "").strip()
    if model_name and tag:
        add(f"{model_name}:{tag}")

    for field in ("path", "backup_path"):
        raw_path = str(entry.get(field) or "").strip()
        if not raw_path:
            continue
        add(raw_path)
        candidate = Path(raw_path)
        if candidate.suffix:
            add(candidate.stem)
            add(candidate.parent.name)
        else:
            add(candidate.name)

    for alias in entry.get("aliases", []) or []:
        add(alias)

    return identifiers


def get_candidate_models_json_paths() -> List[Path]:
    """Retourne tous les emplacements candidats pour models.json."""
    env_path = os.environ.get("MODELS_JSON_PATH", "").strip()
    primary = [Path(env_path)] if env_path else []
    primary = _prefer_current_target(
        primary,
        CURRENT_MODELS_JSON_PATH,
        LEGACY_MODELS_JSON_CANDIDATES,
    )
    combined = list(
        _iter_unique_paths(
            [
                *primary,
                *DEFAULT_MODELS_JSON_CANDIDATES,
                *LEGACY_MODELS_JSON_CANDIDATES,
            ]
        )
    )
    candidates: List[Path] = []
    for candidate in combined:
        candidates.append(candidate)
        wsl_candidate = _windows_to_wsl_path(candidate)
        if wsl_candidate is not None:
            candidates.append(wsl_candidate)
    return list(_iter_unique_paths(candidates))


def get_models_json_path() -> Path:
    """
    Retourne le chemin vers models.json.

    Peut etre configure via variable d'environnement MODELS_JSON_PATH. Si la
    cible souhaitee n'existe pas encore, on continue vers les fallbacks connus.
    """
    candidates = get_candidate_models_json_paths()
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def get_ollama_models_root() -> Path:
    """
    Retourne le repertoire du store Ollama.

    La cible contemporaine est ``C:\\AI\\ollama\\models``, avec fallback vers le
    store historique ``D:\\models\\ollama`` tant que la bascule n'est pas achevee.
    """
    env_value = os.environ.get("OLLAMA_MODELS", "").strip()
    configured = _split_env_paths(env_value) if env_value else []
    desktop_configured = get_ollama_desktop_models_root()
    configured = _prefer_current_target(
        configured,
        CURRENT_OLLAMA_MODELS_ROOT,
        LEGACY_OLLAMA_MODELS_CANDIDATES,
    )
    ordered = list(
        _iter_unique_paths(
            [
                *( [desktop_configured] if desktop_configured else [] ),
                *configured,
                *DEFAULT_OLLAMA_MODELS_CANDIDATES,
                *LEGACY_OLLAMA_MODELS_CANDIDATES,
            ]
        )
    )
    for candidate in ordered:
        if candidate.exists():
            return candidate
    return ordered[0]


def get_model_library_roots() -> List[Path]:
    """
    Retourne les racines de bibliotheques canoniques.

    `MODEL_LIBRARY_ROOTS` accepte une liste separee par `;`.
    """
    env_value = os.environ.get("MODEL_LIBRARY_ROOTS", "").strip()
    configured = _split_env_paths(env_value) if env_value else []
    return list(_iter_unique_paths([*configured, *DEFAULT_MODEL_LIBRARY_ROOTS]))


def get_huggingface_archive_root() -> Path:
    """
    Retourne le repertoire d'archive des sources Hugging Face.

    L'architecture actuelle privilegie ``L:\\models``.
    """
    env_value = os.environ.get("HUGGINGFACE_ARCHIVE_ROOT", "").strip()
    configured = _split_env_paths(env_value) if env_value else []
    configured = _prefer_current_target(
        configured,
        CURRENT_HUGGINGFACE_ARCHIVE_ROOT,
        LEGACY_HUGGINGFACE_ARCHIVE_ROOTS,
    )
    ordered = list(
        _iter_unique_paths(
            [
                *configured,
                *DEFAULT_HUGGINGFACE_ARCHIVE_ROOTS,
                *LEGACY_HUGGINGFACE_ARCHIVE_ROOTS,
            ]
        )
    )
    for candidate in ordered:
        if candidate.exists():
            return candidate
    return ordered[0]


def load_models_json(force_reload: bool = False) -> Dict:
    """
    Charge le fichier models.json depuis l'emplacement le plus pertinent.

    Args:
        force_reload: Si True, recharge le fichier meme si deja en cache

    Returns:
        Dict contenant la configuration des modeles
    """
    global _models_cache

    if _models_cache is not None and not force_reload:
        return _models_cache

    models_path = get_models_json_path()

    if not models_path.exists():
        logger.warning(
            "Fichier models.json introuvable a %s, utilisation de la config par defaut",
            models_path,
        )
        _models_cache = {
            "version": "1.0",
            "ollama_models": [],
            "huggingface_models": [],
            "diffusion_models": [],
            "model_categories": {},
            "recommended_by_task": {},
        }
        return _models_cache

    try:
        with open(models_path, encoding="utf-8-sig") as handle:
            _models_cache = json.load(handle)
        logger.info("Charge %d modeles depuis %s", _count_total_models(_models_cache), models_path)
        return _models_cache
    except (json.JSONDecodeError, IOError) as exc:
        logger.error("Erreur lors du chargement de %s: %s", models_path, exc)
        _models_cache = {
            "version": "1.0",
            "ollama_models": [],
            "huggingface_models": [],
            "diffusion_models": [],
            "model_categories": {},
            "recommended_by_task": {},
        }
        return _models_cache


def _count_total_models(data: Dict) -> int:
    """Compte le nombre total de modeles."""
    count = 0
    count += len(data.get("ollama_models", []))
    count += len(data.get("huggingface_models", []))
    count += len(data.get("diffusion_models", []))
    return count


def get_all_ollama_models() -> List[Dict]:
    """Retourne tous les modeles Ollama disponibles."""
    data = load_models_json()
    return data.get("ollama_models", [])


def get_all_huggingface_models() -> List[Dict]:
    """Retourne tous les modeles HuggingFace disponibles."""
    data = load_models_json()
    return data.get("huggingface_models", [])


def get_all_diffusion_models() -> List[Dict]:
    """Retourne tous les modeles de diffusion disponibles."""
    data = load_models_json()
    return data.get("diffusion_models", [])


def get_model_by_id(model_id: str) -> Optional[Dict]:
    """Recupere un modele par ID, nom Ollama ou alias historique."""
    if not model_id:
        return None

    data = load_models_json()
    normalized_model_id = normalize_model_name(model_id)

    for section in ("ollama_models", "huggingface_models", "diffusion_models"):
        for model in data.get(section, []):
            identifiers = {
                normalize_model_name(identifier)
                for identifier in _entry_identifiers(model)
            }
            if normalized_model_id in identifiers:
                return model

    logger.debug("Modele %s introuvable dans models.json", model_id)
    return None


def get_models_by_category(category: str) -> List[Dict]:
    """Recupere tous les modeles d'une categorie."""
    data = load_models_json()
    categories = data.get("model_categories", {})
    model_ids = categories.get(category, [])
    if not model_ids:
        return []

    models: List[Dict] = []
    for model_id in model_ids:
        model = get_model_by_id(model_id)
        if model:
            models.append(model)
    return models


def get_models_by_use_case(use_case: str) -> List[Dict]:
    """Recupere tous les modeles pour un cas d'usage."""
    all_models = get_all_ollama_models() + get_all_huggingface_models()
    return [model for model in all_models if model.get("use_case") == use_case]


def get_recommended_model_for_task(task: str) -> Optional[str]:
    """Retourne le modele recommande pour une tache."""
    data = load_models_json()
    recommendations = data.get("recommended_by_task", {})
    recommendation = recommendations.get(task)
    if isinstance(recommendation, str):
        return normalize_model_name(recommendation)
    return recommendation


def get_model_full_path(model_id: str) -> Optional[Path]:
    """Retourne le chemin complet vers un modele ou son backup canonique."""
    model = get_model_by_id(model_id)
    if not model:
        return None

    data = load_models_json()
    base_dir = Path(data.get("models_directory") or r"C:\AI\models")
    raw_path = str(model.get("path") or model.get("backup_path") or "").strip()
    if not raw_path:
        return None

    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return base_dir / candidate


def get_ollama_model_names() -> List[str]:
    """
    Retourne la liste des noms runtime Ollama depuis models.json.

    On privilegie `ollama_name`, avec normalisation des alias et suppression du
    suffixe `:latest` pour garder une nomenclature stable dans l'UI.
    """
    names: List[str] = []
    for model in get_all_ollama_models():
        preferred_name = (
            model.get("ollama_name")
            or (
                f"{model['model_name']}:{model['tag']}"
                if model.get("model_name") and model.get("tag")
                else ""
            )
            or model.get("model_name")
            or model.get("id", "")
        )
        canonical_name = normalize_model_name(str(preferred_name or "").strip())
        if canonical_name and canonical_name not in names:
            names.append(canonical_name)
    return names


def get_ollama_manifest_model_names() -> List[str]:
    """
    Retourne les noms de modèles présents dans les manifests Ollama locaux.

    Cette source complète ``models.json`` et reflète directement le store
    configuré dans l'application Ollama Desktop, même si le catalogue n'a pas
    encore été régénéré.
    """
    names: List[str] = []
    desktop_root = get_ollama_desktop_models_root()
    candidate_roots = list(
        _iter_unique_paths(
            [
                *([desktop_root] if desktop_root else []),
                get_ollama_models_root(),
                *DEFAULT_OLLAMA_MODELS_CANDIDATES,
                *LEGACY_OLLAMA_MODELS_CANDIDATES,
            ]
        )
    )

    for root in candidate_roots:
        manifest_root = root / "manifests"
        if not manifest_root.exists():
            continue
        for manifest in manifest_root.rglob("*"):
            if not manifest.is_file():
                continue
            try:
                relative_parts = manifest.relative_to(manifest_root).parts
            except ValueError:
                continue
            if len(relative_parts) < 4:
                continue
            registry, namespace, model_name, tag = relative_parts[:4]
            if registry != "registry.ollama.ai":
                continue
            raw_name = f"{model_name}:{tag}" if namespace == "library" else f"{namespace}/{model_name}:{tag}"
            canonical_name = normalize_model_name(raw_name)
            if canonical_name and canonical_name not in names:
                names.append(canonical_name)
    return names


def get_ollama_runtime_model_names() -> List[str]:
    """Retourne l'union catalogue + manifests du runtime Ollama local."""
    names: List[str] = []
    for candidate in [*get_ollama_model_names(), *get_ollama_manifest_model_names()]:
        canonical_name = normalize_model_name(candidate)
        if canonical_name and canonical_name not in names:
            names.append(canonical_name)
    return names


def get_model_info_for_ui(model_id: str) -> Dict:
    """Retourne les infos formatees pour l'UI."""
    model = get_model_by_id(model_id)
    if not model:
        normalized_model_id = normalize_model_name(model_id)
        return {
            "name": normalized_model_id or model_id,
            "size_gb": "?",
            "description": "Modele inconnu",
            "use_case": "unknown",
        }

    return {
        "name": model.get("name", normalize_model_name(model_id)),
        "size_gb": model.get("size_gb", "?"),
        "description": model.get("description", ""),
        "use_case": model.get("use_case", "general"),
        "parameters": model.get("parameters", ""),
        "context_length": model.get("context_length", 0),
    }


__all__ = [
    "DEFAULT_HUGGINGFACE_ARCHIVE_ROOTS",
    "DEFAULT_MODEL_LIBRARY_ROOTS",
    "DEFAULT_MODELS_JSON_CANDIDATES",
    "DEFAULT_OLLAMA_MODELS_CANDIDATES",
    "MODEL_NAME_ALIASES",
    "get_all_diffusion_models",
    "get_all_huggingface_models",
    "get_all_ollama_models",
    "get_candidate_models_json_paths",
    "get_huggingface_archive_root",
    "get_model_by_id",
    "get_model_full_path",
    "get_model_info_for_ui",
    "get_model_library_roots",
    "get_models_by_category",
    "get_models_by_use_case",
    "get_models_json_path",
    "get_ollama_model_names",
    "get_ollama_manifest_model_names",
    "get_ollama_models_root",
    "get_ollama_runtime_model_names",
    "get_ollama_desktop_models_root",
    "get_recommended_model_for_task",
    "load_models_json",
    "normalize_model_name",
]
