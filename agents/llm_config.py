"""
Module-ID: agents.llm_config

Purpose: Configuration et logique métier pour les providers LLM.
         Extraction de la logique depuis ui/sidebar.py (DDD refactoring).

Role in pipeline: domain / configuration

Key components:
- LLMConfigOptions: Options disponibles pour la configuration LLM
- get_llm_options: Récupère les options de configuration
- validate_llm_config: Valide une configuration LLM
- extract_model_size: Parse la taille d'un modèle (ex: "14b" -> 14.0)
- filter_models_by_size: Filtre les modèles par taille

Dependencies: agents.llm_client, re

Conventions: Fonctions pures (pas de Streamlit), retournent des dicts/dataclasses

Read-if: Configuration LLM pour UI ou CLI
Skip-if: Logique de trading
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

# Import conditionnel des dépendances LLM
try:
    from agents.llm_client import LLMConfig, LLMProvider
    from agents.model_config import (
        KNOWN_MODELS,
        ModelCategory,
        RoleModelConfig,
        get_global_model_config,
        set_global_model_config,
    )
    LLM_AVAILABLE = True
    LLM_IMPORT_ERROR = None
except ImportError as e:
    LLM_AVAILABLE = False
    LLM_IMPORT_ERROR = str(e)
    LLMConfig = None
    LLMProvider = None
    KNOWN_MODELS = {}
    ModelCategory = None
    RoleModelConfig = None
    get_global_model_config = None
    set_global_model_config = None


# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"

RECOMMENDED_FOR_STRATEGY = [
    "deepseek-r1:8b",
    "qwen2.5:14b",
    "gemma3:27b",
    "llama3.3:70b",
]

OPENAI_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-3.5-turbo",
]

# Modèles à exclure par défaut des sélections aléatoires
EXCLUDED_HEAVY_MODELS: Set[str] = {"deepseek-r1:70b"}


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class LLMConfigOptions:
    """Options disponibles pour la configuration LLM."""
    available: bool = False
    import_error: Optional[str] = None

    providers: List[str] = field(default_factory=lambda: ["Ollama (Local)", "OpenAI"])
    ollama_models: List[str] = field(default_factory=list)
    openai_models: List[str] = field(default_factory=lambda: OPENAI_MODELS.copy())

    ollama_connected: bool = False
    default_ollama_host: str = DEFAULT_OLLAMA_HOST


@dataclass
class ModelSizeFilter:
    """Configuration du filtrage par taille de modèle."""
    limit_small: bool = False  # < 20B
    limit_large: bool = False  # >= 20B
    excluded_models: Set[str] = field(default_factory=lambda: EXCLUDED_HEAVY_MODELS.copy())


# ============================================================================
# MODEL SIZE UTILITIES
# ============================================================================

def extract_model_size_b(model_name: str) -> Optional[float]:
    """
    Extrait la taille en milliards de paramètres d'un nom de modèle.

    Args:
        model_name: Nom du modèle (ex: "llama3.3:70b", "qwen2.5:14b")

    Returns:
        Taille en milliards (ex: 70.0, 14.0) ou None si non trouvé
    """
    match = re.search(r"(\d+(?:\.\d+)?)b", model_name.lower())
    if match:
        return float(match.group(1))
    return None


def is_model_under_limit(model_name: str, limit: float) -> bool:
    """
    Vérifie si un modèle est sous une limite de taille.

    Args:
        model_name: Nom du modèle
        limit: Limite en milliards

    Returns:
        True si modèle < limite, False sinon
    """
    size = extract_model_size_b(model_name)
    if size is None:
        return False
    return size < limit


def is_model_over_limit(model_name: str, limit: float) -> bool:
    """
    Vérifie si un modèle est au-dessus d'une limite de taille.

    Args:
        model_name: Nom du modèle
        limit: Limite en milliards

    Returns:
        True si modèle >= limite, False sinon
    """
    size = extract_model_size_b(model_name)
    if size is None:
        return False
    return size >= limit


def filter_models_by_size(
    models: List[str],
    size_filter: ModelSizeFilter
) -> List[str]:
    """
    Filtre une liste de modèles selon les critères de taille.

    Args:
        models: Liste des noms de modèles
        size_filter: Configuration du filtrage

    Returns:
        Liste filtrée des modèles
    """
    # Exclure les modèles interdits
    filtered = [m for m in models if m not in size_filter.excluded_models]

    # Appliquer les filtres de taille (priorité aux >= 20B si les deux actifs)
    if size_filter.limit_small and size_filter.limit_large:
        # Priorité au filtre large
        result = [m for m in filtered if is_model_over_limit(m, 20)]
    elif size_filter.limit_large:
        result = [m for m in filtered if is_model_over_limit(m, 20)]
    elif size_filter.limit_small:
        result = [m for m in filtered if is_model_under_limit(m, 20)]
    else:
        result = filtered

    # Si le filtrage vide la liste, retourner la liste non filtrée par taille
    if not result and filtered:
        return filtered

    return result


# ============================================================================
# OLLAMA UTILITIES
# ============================================================================

def is_ollama_available() -> bool:
    """
    Vérifie si Ollama est disponible et connecté.

    Returns:
        True si Ollama répond, False sinon
    """
    try:
        import httpx
        response = httpx.get(f"{DEFAULT_OLLAMA_HOST}/api/tags", timeout=2.0)
        return response.status_code == 200
    except Exception:
        return False


def list_available_ollama_models() -> List[str]:
    """
    Liste les modèles Ollama installés localement.

    Returns:
        Liste des noms de modèles disponibles
    """
    try:
        import httpx
        response = httpx.get(f"{DEFAULT_OLLAMA_HOST}/api/tags", timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            models = data.get("models", [])
            return [m.get("name", "") for m in models if m.get("name")]
    except Exception:
        pass
    return []


def ensure_ollama_running() -> tuple[bool, str]:
    """
    Tente de démarrer Ollama s'il n'est pas en cours d'exécution.

    Returns:
        Tuple (success, message)
    """
    if is_ollama_available():
        return True, "Ollama déjà connecté"

    try:
        import subprocess
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Attendre un peu et vérifier
        import time
        for _ in range(10):
            time.sleep(0.5)
            if is_ollama_available():
                return True, "Ollama démarré avec succès"

        return False, "Ollama démarré mais ne répond pas"
    except Exception as e:
        return False, f"Erreur démarrage Ollama: {e}"


# ============================================================================
# CONFIGURATION FUNCTIONS
# ============================================================================

def get_llm_options() -> LLMConfigOptions:
    """
    Récupère toutes les options disponibles pour la configuration LLM.

    Returns:
        LLMConfigOptions avec providers, modèles, et état de connexion
    """
    options = LLMConfigOptions(
        available=LLM_AVAILABLE,
        import_error=LLM_IMPORT_ERROR,
    )

    if not LLM_AVAILABLE:
        return options

    # Vérifier Ollama
    options.ollama_connected = is_ollama_available()
    if options.ollama_connected:
        options.ollama_models = list_available_ollama_models()

    return options


def get_model_display_name(model_name: str) -> str:
    """
    Génère un nom d'affichage avec badge de catégorie.

    Args:
        model_name: Nom brut du modèle

    Returns:
        Nom avec badge (ex: "[L] qwen2.5:14b", "[H] llama3.3:70b")
    """
    if not LLM_AVAILABLE or KNOWN_MODELS is None:
        return model_name

    info = KNOWN_MODELS.get(model_name)
    if info:
        if info.category == ModelCategory.LIGHT:
            return f"[L] {model_name}"
        if info.category == ModelCategory.MEDIUM:
            return f"[M] {model_name}"
        return f"[H] {model_name}"
    return model_name


def create_display_mappings(model_names: List[str]) -> tuple[Dict[str, str], Dict[str, str]]:
    """
    Crée les mappings nom ↔ affichage pour une liste de modèles.

    Args:
        model_names: Liste des noms de modèles

    Returns:
        Tuple (name_to_display, display_to_name)
    """
    name_to_display = {n: get_model_display_name(n) for n in model_names}
    display_to_name = {v: k for k, v in name_to_display.items()}
    return name_to_display, display_to_name


def validate_llm_config(config: Any) -> tuple[bool, Optional[str]]:
    """
    Valide une configuration LLM.

    Args:
        config: Configuration LLM à valider

    Returns:
        Tuple (is_valid, error_message)
    """
    if config is None:
        return False, "Configuration LLM non définie"

    if not LLM_AVAILABLE:
        return False, f"Module LLM non disponible: {LLM_IMPORT_ERROR}"

    if not hasattr(config, 'provider') or not hasattr(config, 'model'):
        return False, "Configuration LLM invalide (provider/model manquant)"

    if config.provider == LLMProvider.OLLAMA:
        if not is_ollama_available():
            return False, "Ollama non connecté"

    if config.provider == LLMProvider.OPENAI:
        if not hasattr(config, 'api_key') or not config.api_key:
            return False, "Clé API OpenAI manquante"

    return True, None


def create_llm_config(
    provider: str,
    model: str,
    ollama_host: str = DEFAULT_OLLAMA_HOST,
    api_key: Optional[str] = None
) -> Optional[Any]:
    """
    Crée une configuration LLM.

    Args:
        provider: "Ollama (Local)" ou "OpenAI"
        model: Nom du modèle
        ollama_host: URL du serveur Ollama
        api_key: Clé API OpenAI (si applicable)

    Returns:
        LLMConfig ou None si indisponible
    """
    if not LLM_AVAILABLE or LLMConfig is None:
        return None

    if "Ollama" in provider:
        return LLMConfig(
            provider=LLMProvider.OLLAMA,
            model=model,
            ollama_host=ollama_host,
        )
    else:
        if not api_key:
            return None
        return LLMConfig(
            provider=LLMProvider.OPENAI,
            model=model,
            api_key=api_key,
        )


# ============================================================================
# MULTI-MODEL ROLE CONFIGURATION
# ============================================================================

def get_optimal_models_for_role(
    role: str,
    available_models: List[str]
) -> List[str]:
    """
    Retourne les modèles optimaux pour un rôle d'agent.

    Args:
        role: "analyst", "strategist", "critic", ou "validator"
        available_models: Modèles disponibles

    Returns:
        Liste de modèles recommandés (max 3)
    """
    # Configuration optimale basée sur benchmarks
    optimal_config = {
        "analyst": ["qwen2.5:14b", "gemma3:12b", "llama3.2:8b"],
        "strategist": ["gemma3:27b", "qwen2.5:14b", "mistral:7b"],
        "critic": ["llama3.3:70b", "deepseek-r1:32b", "gemma3:27b"],
        "validator": ["llama3.3:70b", "deepseek-r1:32b", "qwen2.5:32b"],
    }

    preferred = optimal_config.get(role, [])
    result = [m for m in preferred if m in available_models]

    # Fallback si aucun modèle optimal disponible
    if not result and available_models:
        result = available_models[:2]

    return result[:3]


def normalize_model_selection(
    selection: List[str],
    display_to_name: Dict[str, str],
    available_models: List[str]
) -> List[str]:
    """
    Normalise une sélection de modèles (display → name, filtrage).

    Args:
        selection: Liste de noms d'affichage sélectionnés
        display_to_name: Mapping affichage → nom
        available_models: Modèles disponibles

    Returns:
        Liste de noms de modèles normalisés et validés
    """
    names = [display_to_name.get(m, m) for m in selection]
    return [n for n in names if n in available_models]
