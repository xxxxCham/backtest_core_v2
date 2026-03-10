"""
Module-ID: utils.model_loader

Purpose: Chargement et accès aux modèles depuis D:\\models\\models.json

Role in pipeline: configuration

Key components: load_models_json(), get_model_by_id(), get_models_by_category()

Inputs: models.json path (default: D:\\models\\models.json)

Outputs: Dict de modèles avec infos (path, size, use_case, etc.)

Dependencies: json, pathlib

Conventions: Fallback si fichier absent; cache en mémoire; modèles Ollama prioritaires.

Read-if: Modification de la logique de chargement des modèles.

Skip-if: Vous utilisez directement get_available_models().
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from utils.log import get_logger

logger = get_logger(__name__)

# Chemin par défaut vers models.json
DEFAULT_MODELS_JSON_PATH = Path("D:\\models\\models.json")

# Cache en mémoire
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


def get_models_json_path() -> Path:
    """
    Retourne le chemin vers models.json.

    Peut être configuré via variable d'environnement MODELS_JSON_PATH.

    Returns:
        Path: Chemin vers models.json
    """
    env_path = os.environ.get("MODELS_JSON_PATH")
    if env_path:
        return Path(env_path)

    if DEFAULT_MODELS_JSON_PATH.exists():
        return DEFAULT_MODELS_JSON_PATH

    wsl_path = _windows_to_wsl_path(DEFAULT_MODELS_JSON_PATH)
    if wsl_path and wsl_path.exists():
        return wsl_path

    return DEFAULT_MODELS_JSON_PATH


def load_models_json(force_reload: bool = False) -> Dict:
    """
    Charge le fichier models.json depuis D:\\models\\models.json.

    Args:
        force_reload: Si True, recharge le fichier même si déjà en cache

    Returns:
        Dict contenant la configuration des modèles

    Example:
        >>> data = load_models_json()
        >>> ollama_models = data.get("ollama_models", [])
        >>> for model in ollama_models:
        ...     print(f"{model['id']}: {model['name']}")
    """
    global _models_cache

    # Retourner le cache si disponible
    if _models_cache is not None and not force_reload:
        return _models_cache

    models_path = get_models_json_path()

    if not models_path.exists():
        logger.warning(
            "Fichier models.json introuvable à %s, utilisation de la config par défaut",
            models_path
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
        with open(models_path, encoding="utf-8-sig") as f:
            _models_cache = json.load(f)
        logger.info("✅ Chargé %d modèles depuis %s", _count_total_models(_models_cache), models_path)
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
    """Compte le nombre total de modèles."""
    count = 0
    count += len(data.get("ollama_models", []))
    count += len(data.get("huggingface_models", []))
    count += len(data.get("diffusion_models", []))
    return count


def get_all_ollama_models() -> List[Dict]:
    """
    Retourne tous les modèles Ollama disponibles.

    Returns:
        List[Dict]: Liste des modèles Ollama avec leurs métadonnées

    Example:
        >>> models = get_all_ollama_models()
        >>> for m in models:
        ...     print(f"{m['id']}: {m['size_gb']} GB - {m['use_case']}")
    """
    data = load_models_json()
    return data.get("ollama_models", [])


def get_all_huggingface_models() -> List[Dict]:
    """Retourne tous les modèles HuggingFace disponibles."""
    data = load_models_json()
    return data.get("huggingface_models", [])


def get_all_diffusion_models() -> List[Dict]:
    """Retourne tous les modèles de diffusion disponibles."""
    data = load_models_json()
    return data.get("diffusion_models", [])


def get_model_by_id(model_id: str) -> Optional[Dict]:
    """
    Récupère un modèle par son ID.

    Args:
        model_id: ID du modèle (ex: "llama3.1-8b", "deepseek-r1-32b")

    Returns:
        Dict contenant les métadonnées du modèle ou None si introuvable

    Example:
        >>> model = get_model_by_id("llama3.1-8b")
        >>> if model:
        ...     print(f"Path: {model['path']}")
        ...     print(f"Size: {model['size_gb']} GB")
    """
    if not model_id:
        return None

    data = load_models_json()
    model_id = model_id.strip()

    # Chercher dans ollama_models
    for model in data.get("ollama_models", []):
        if model.get("id") == model_id:
            return model

    # Chercher dans huggingface_models
    for model in data.get("huggingface_models", []):
        if model.get("id") == model_id:
            return model

    # Chercher dans diffusion_models
    for model in data.get("diffusion_models", []):
        if model.get("id") == model_id:
            return model

    # Normaliser les noms Ollama (ex: nemotron-3-nano:30b -> model_name/tag)
    if ":" in model_id:
        base, tag = model_id.split(":", 1)
        for model in data.get("ollama_models", []):
            if model.get("model_name") == base and model.get("tag") == tag:
                return model

        # Ex: llama3.3-70b-optimized:latest -> llama3.3-70b-optimized-latest
        if "/" not in model_id:
            dashed_id = model_id.replace(":", "-")
            for model in data.get("ollama_models", []):
                if model.get("id") == dashed_id:
                    return model

    # Fallback: match par model_name si unique
    matches = [
        m for m in data.get("ollama_models", [])
        if m.get("model_name") == model_id
    ]
    if len(matches) == 1:
        return matches[0]

    logger.debug("Modèle %s introuvable dans models.json", model_id)
    return None


def get_models_by_category(category: str) -> List[Dict]:
    """
    Récupère tous les modèles d'une catégorie.

    Args:
        category: Catégorie (ex: "general", "reasoning", "finance", "image_generation")

    Returns:
        List[Dict]: Liste des modèles de cette catégorie

    Example:
        >>> reasoning_models = get_models_by_category("reasoning")
        >>> for m in reasoning_models:
        ...     print(m['name'])
    """
    data = load_models_json()
    categories = data.get("model_categories", {})

    model_ids = categories.get(category, [])
    if not model_ids:
        return []

    # Récupérer les détails de chaque modèle
    models = []
    for model_id in model_ids:
        model = get_model_by_id(model_id)
        if model:
            models.append(model)

    return models


def get_models_by_use_case(use_case: str) -> List[Dict]:
    """
    Récupère tous les modèles pour un cas d'usage.

    Args:
        use_case: Cas d'usage (ex: "general", "reasoning", "finance", "instruction")

    Returns:
        List[Dict]: Liste des modèles

    Example:
        >>> finance_models = get_models_by_use_case("reasoning_finance")
        >>> for m in finance_models:
        ...     print(f"{m['name']}: {m['description']}")
    """
    all_models = get_all_ollama_models() + get_all_huggingface_models()
    return [m for m in all_models if m.get("use_case") == use_case]


def get_recommended_model_for_task(task: str) -> Optional[str]:
    """
    Retourne le modèle recommandé pour une tâche.

    Args:
        task: Nom de la tâche (ex: "backtest_strategy_generation", "backtest_analysis")

    Returns:
        str: ID du modèle recommandé ou None

    Example:
        >>> model_id = get_recommended_model_for_task("backtest_strategy_generation")
        >>> if model_id:
        ...     model = get_model_by_id(model_id)
        ...     print(f"Recommandé: {model['name']}")
    """
    data = load_models_json()
    recommendations = data.get("recommended_by_task", {})
    return recommendations.get(task)


def get_model_full_path(model_id: str) -> Optional[Path]:
    """
    Retourne le chemin complet vers un modèle.

    Args:
        model_id: ID du modèle

    Returns:
        Path: Chemin absolu vers le modèle ou None si introuvable

    Example:
        >>> path = get_model_full_path("llama3.1-8b")
        >>> if path:
        ...     print(f"Modèle à: {path}")
    """
    model = get_model_by_id(model_id)
    if not model:
        return None

    data = load_models_json()
    base_dir = Path(data.get("models_directory", "D:\\models"))
    relative_path = model.get("path", "")

    if not relative_path:
        return None

    return base_dir / relative_path


def get_ollama_model_names() -> List[str]:
    """
    Retourne la liste des noms de modèles Ollama depuis models.json.

    Utilise le champ ``ollama_name`` pour correspondre exactement aux noms
    retournés par ``ollama list``, évitant les doublons dans l'UI.

    Returns:
        List[str]: Noms Ollama normalisés (sans suffixe ``:latest``).
    """
    models = get_all_ollama_models()
    names = []
    for model in models:
        ollama_name = model.get("ollama_name", "")
        if ollama_name:
            if ollama_name.endswith(":latest"):
                ollama_name = ollama_name[: -len(":latest")]
            names.append(ollama_name)
    return names


def get_model_info_for_ui(model_id: str) -> Dict:
    """
    Retourne les infos formattées pour l'UI.

    Args:
        model_id: ID du modèle

    Returns:
        Dict: Informations formattées {name, size_gb, description, use_case}

    Example:
        >>> info = get_model_info_for_ui("deepseek-r1-32b")
        >>> st.caption(f"{info['size_gb']} GB - {info['description']}")
    """
    model = get_model_by_id(model_id)
    if not model:
        return {
            "name": model_id,
            "size_gb": "?",
            "description": "Modèle inconnu",
            "use_case": "unknown",
        }

    return {
        "name": model.get("name", model_id),
        "size_gb": model.get("size_gb", "?"),
        "description": model.get("description", ""),
        "use_case": model.get("use_case", "general"),
        "parameters": model.get("parameters", ""),
        "context_length": model.get("context_length", 0),
    }


__all__ = [
    "load_models_json",
    "get_all_ollama_models",
    "get_all_huggingface_models",
    "get_all_diffusion_models",
    "get_model_by_id",
    "get_models_by_category",
    "get_models_by_use_case",
    "get_recommended_model_for_task",
    "get_model_full_path",
    "get_ollama_model_names",
    "get_model_info_for_ui",
]
