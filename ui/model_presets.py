"""
Module-ID: ui.model_presets

Purpose: Gestion des presets de configuration de modèles LLM pour les agents.

Role in pipeline: configuration UI

Key components: BUILTIN_PRESETS, save/load/delete presets, apply preset

Inputs: Nom de preset, RoleModelConfig

Outputs: Presets JSON, config modifiée

Dependencies: pathlib, json, datetime, agents.model_config

Conventions: Presets builtin non modifiables, fichiers JSON dans data/model_presets/

Read-if: Modification des presets builtin ou logique de sauvegarde

Skip-if: Vous utilisez juste list_model_presets() ou load_model_preset()
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from utils.log import get_logger

logger = get_logger(__name__)

# Répertoire de sauvegarde des presets utilisateur
MODEL_PRESETS_DIR = Path("data") / "model_presets"

# ===== PRESETS PRÉDÉFINIS (NON MODIFIABLES) =====

BUILTIN_PRESETS: Dict[str, Dict[str, Any]] = {
    "Optimal": {
        "name": "Optimal",
        "description": "Configuration optimale basée sur benchmarks Dec 2025",
        "models": {
            "analyst": ["qwen2.5:14b"],
            "strategist": ["gemma3:27b"],
            "critic": ["llama3.3-70b-optimized"],
            "validator": ["llama3.3-70b-optimized"]
        },
        "builtin": True
    },
    "Rapide": {
        "name": "Rapide",
        "description": "Modèles légers pour exploration rapide",
        "models": {
            "analyst": ["gemma3:12b"],
            "strategist": ["mistral:22b"],
            "critic": ["deepseek-r1:32b"],
            "validator": ["deepseek-r1:32b"]
        },
        "builtin": True
    },
    "Équilibré": {
        "name": "Équilibré",
        "description": "Mix light/medium/heavy pour compromis performance/vitesse",
        "models": {
            "analyst": ["qwen2.5:14b"],
            "strategist": ["gemma3:27b"],
            "critic": ["deepseek-r1:32b"],
            "validator": ["qwq:32b"]
        },
        "builtin": True
    },
    "Puissant": {
        "name": "Puissant",
        "description": "Heavy models pour analyses complexes et ajustements fins",
        "models": {
            "analyst": ["qwen2.5:32b"],
            "strategist": ["deepseek-r1:32b"],
            "critic": ["llama3.3-70b-optimized"],
            "validator": ["llama3.3-70b-optimized"]
        },
        "builtin": True
    }
}

# ===== FONCTIONS PRINCIPALES =====


def get_presets_dir() -> Path:
    """Retourne le répertoire de sauvegarde des presets."""
    MODEL_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    return MODEL_PRESETS_DIR


def list_model_presets() -> List[Dict[str, Any]]:
    """
    Liste tous les presets disponibles (builtin + utilisateur).

    Returns:
        Liste de dicts avec clés: name, description, models, builtin
    """
    # Presets builtin
    presets = list(BUILTIN_PRESETS.values())

    # Presets utilisateur sur disque
    presets_dir = get_presets_dir()
    for filepath in presets_dir.glob("*.json"):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                preset = json.load(f)
                preset["builtin"] = False
                presets.append(preset)
        except Exception as e:
            logger.warning(f"Erreur chargement preset {filepath}: {e}")

    return presets


def load_model_preset(name: str) -> Dict[str, Any]:
    """
    Charge un preset par son nom.

    Args:
        name: Nom du preset

    Returns:
        Dict avec clés: name, description, models, builtin

    Raises:
        ValueError: Si le preset n'existe pas
    """
    # Vérifier dans les builtin
    if name in BUILTIN_PRESETS:
        return BUILTIN_PRESETS[name].copy()

    # Vérifier sur disque
    presets_dir = get_presets_dir()
    filepath = presets_dir / f"{name}.json"

    if not filepath.exists():
        raise ValueError(f"Preset '{name}' introuvable")

    with open(filepath, "r", encoding="utf-8") as f:
        preset = json.load(f)
        preset["builtin"] = False
        return preset


def save_model_preset(name: str, models: Dict[str, List[str]]) -> None:
    """
    Sauvegarde un preset utilisateur.

    Args:
        name: Nom du preset
        models: Dict {role: [model_names]}

    Raises:
        ValueError: Si le nom est invalide ou si c'est un builtin
    """
    name = name.strip()
    if not name:
        raise ValueError("Nom de preset requis")

    if name in BUILTIN_PRESETS:
        raise ValueError(f"Impossible de modifier le preset builtin '{name}'")

    preset = {
        "name": name,
        "description": "",
        "models": models,
        "created_at": datetime.utcnow().isoformat() + "Z"
    }

    presets_dir = get_presets_dir()
    filepath = presets_dir / f"{name}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(preset, f, indent=2, ensure_ascii=False)

    logger.info(f"Preset '{name}' sauvegardé: {filepath}")


def delete_model_preset(name: str) -> bool:
    """
    Supprime un preset utilisateur.

    Args:
        name: Nom du preset

    Returns:
        True si supprimé, False sinon

    Raises:
        ValueError: Si c'est un preset builtin
    """
    if name in BUILTIN_PRESETS:
        raise ValueError(f"Impossible de supprimer le preset builtin '{name}'")

    presets_dir = get_presets_dir()
    filepath = presets_dir / f"{name}.json"

    if filepath.exists():
        filepath.unlink()
        logger.info(f"Preset '{name}' supprimé")
        return True

    return False


def get_current_config_as_dict(role_model_config) -> Dict[str, Any]:
    """
    Convertit la config actuelle en dict pour sauvegarde.

    Args:
        role_model_config: Instance de RoleModelConfig

    Returns:
        Dict avec clé 'models' contenant la config de chaque rôle
    """
    return {
        "models": {
            "analyst": role_model_config.analyst.models,
            "strategist": role_model_config.strategist.models,
            "critic": role_model_config.critic.models,
            "validator": role_model_config.validator.models,
        }
    }


def apply_preset_to_config(preset: Dict[str, Any], role_model_config) -> None:
    """
    Applique un preset à la config globale.

    Args:
        preset: Dict du preset
        role_model_config: Instance de RoleModelConfig à modifier
    """
    models = preset.get("models", {})

    role_model_config.analyst.models = models.get("analyst", [])
    role_model_config.strategist.models = models.get("strategist", [])
    role_model_config.critic.models = models.get("critic", [])
    role_model_config.validator.models = models.get("validator", [])

    logger.info(f"Preset '{preset.get('name')}' appliqué à la config")


__all__ = [
    "BUILTIN_PRESETS",
    "get_presets_dir",
    "list_model_presets",
    "load_model_preset",
    "save_model_preset",
    "delete_model_preset",
    "get_current_config_as_dict",
    "apply_preset_to_config",
]
