"""Module-ID: indicators.filters

Purpose: Configuration et logique métier pour les filtres de signaux.
         Extraction de la logique depuis ui/sidebar.py (DDD refactoring).

Role in pipeline: domain / configuration

Key components:
- MarkovFilterConfig: Configuration du filtre Markov Switching
- get_markov_options: Options disponibles pour le filtre
- validate_markov_config: Validation de la configuration
- build_markov_params: Construction des paramètres pour le backtest

Dependencies: indicators.markov_switching

Conventions: Fonctions pures (pas de Streamlit), retournent des dicts/dataclasses

Read-if: Configuration des filtres pour UI ou CLI
Skip-if: Logique de trading pure
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================

# Régimes Markov disponibles
MARKOV_REGIMES = {
    0: "Bull",
    1: "Bear",
    2: "Ranging",
    3: "Bull faible",  # Pour k_regimes=4
}

# Timeframes recommandés pour le calcul Markov
MARKOV_RECOMMENDED_TF = ["1h", "4h", "1d"]
MARKOV_UNSTABLE_TF = ["15m", "30m"]

# Nombre de régimes supportés
MARKOV_K_REGIMES_OPTIONS = [2, 3, 4]

# Configuration par défaut
DEFAULT_MARKOV_CONFIG = {
    "enabled": False,  # Désactivé par défaut
    "allowed_regimes": [0, 1, 2],  # Tous = pas d'effet
    "resample": "1h",
    "k_regimes": 3,
}


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class MarkovFilterConfig:
    """Configuration du filtre Markov Switching."""

    enabled: bool = False
    allowed_regimes: list[int] = field(default_factory=lambda: [0, 1, 2])
    forbidden_regimes: list[int] = field(default_factory=list)
    resample_tf: str = "1h"
    k_regimes: int = 3
    filter_mode: str = "allow"  # "allow" ou "forbid"

    @property
    def has_effect(self) -> bool:
        """Vérifie si le filtre a un effet (pas tous les régimes autorisés)."""
        if not self.enabled:
            return False
        all_regimes = set(range(self.k_regimes))
        return set(self.allowed_regimes) != all_regimes

    def to_params_dict(self) -> dict[str, Any]:
        """Convertit en dict pour injection dans les paramètres backtest."""
        return {
            "use_markov_filter": self.enabled,
            "markov_allowed_regimes": self.allowed_regimes,
            "markov_resample": self.resample_tf,
            "markov_regimes": self.k_regimes,
        }


@dataclass
class MarkovOptions:
    """Options disponibles pour la configuration Markov."""

    available_regimes: dict[int, str] = field(default_factory=lambda: MARKOV_REGIMES.copy())
    recommended_timeframes: list[str] = field(default_factory=lambda: MARKOV_RECOMMENDED_TF.copy())
    unstable_timeframes: list[str] = field(default_factory=lambda: MARKOV_UNSTABLE_TF.copy())
    k_regimes_options: list[int] = field(default_factory=lambda: MARKOV_K_REGIMES_OPTIONS.copy())


# ============================================================================
# CONFIGURATION FUNCTIONS
# ============================================================================


def get_markov_options() -> MarkovOptions:
    """Récupère les options disponibles pour le filtre Markov.

    Returns:
        MarkovOptions avec régimes, timeframes, etc.

    """
    return MarkovOptions()


def create_markov_config(
    enabled: bool = False,
    filter_mode: str = "allow",
    selected_regimes: list[int] | None = None,
    resample_tf: str = "1h",
    k_regimes: int = 3,
) -> MarkovFilterConfig:
    """Crée une configuration Markov à partir des sélections utilisateur.

    Args:
        enabled: Si le filtre est activé
        filter_mode: "allow" ou "forbid"
        selected_regimes: Régimes sélectionnés (cochés)
        resample_tf: Timeframe pour le calcul
        k_regimes: Nombre de régimes

    Returns:
        MarkovFilterConfig configurée

    """
    if selected_regimes is None:
        selected_regimes = [0, 1, 2]

    config = MarkovFilterConfig(
        enabled=enabled,
        resample_tf=resample_tf,
        k_regimes=k_regimes,
        filter_mode=filter_mode,
    )

    # Calculer les régimes autorisés selon le mode
    all_regimes = set(range(k_regimes))

    if filter_mode == "allow":
        config.allowed_regimes = selected_regimes
        config.forbidden_regimes = list(all_regimes - set(selected_regimes))
    else:  # forbid
        config.forbidden_regimes = selected_regimes
        config.allowed_regimes = list(all_regimes - set(selected_regimes))

    return config


def validate_markov_config(config: MarkovFilterConfig) -> tuple[bool, str | None]:
    """Valide une configuration Markov.

    Args:
        config: Configuration à valider

    Returns:
        Tuple (is_valid, error_message)

    """
    if not config.enabled:
        return True, None  # Désactivé = toujours valide

    # Vérifier qu'au moins un régime est autorisé
    if not config.allowed_regimes:
        return False, "Aucun régime autorisé - aucun trade possible"

    # Vérifier que les régimes sont valides
    valid_regimes = set(range(config.k_regimes))
    for regime in config.allowed_regimes:
        if regime not in valid_regimes:
            return False, f"Régime {regime} invalide pour k_regimes={config.k_regimes}"

    # Avertir si timeframe instable
    if config.resample_tf in MARKOV_UNSTABLE_TF:
        return True, f"⚠️ Timeframe {config.resample_tf} peut être instable pour Markov"

    return True, None


def get_regime_display_info(k_regimes: int) -> dict[int, dict[str, str]]:
    """Récupère les informations d'affichage pour chaque régime.

    Args:
        k_regimes: Nombre de régimes

    Returns:
        Dict {regime_id: {name, emoji, description}}

    """
    if k_regimes == 2:
        return {
            0: {"name": "Bull", "emoji": "🟢", "description": "Régime haussier"},
            1: {"name": "Bear", "emoji": "🔴", "description": "Régime baissier"},
        }
    if k_regimes == 3:
        return {
            0: {"name": "Bull", "emoji": "🟢", "description": "Forte volatilité positive"},
            1: {"name": "Bear", "emoji": "🔴", "description": "Forte volatilité négative"},
            2: {"name": "Ranging", "emoji": "🟡", "description": "Consolidation, faible volatilité"},
        }
    # k_regimes == 4
    return {
        0: {"name": "Bull fort", "emoji": "🟢", "description": "Tendance haussière forte"},
        1: {"name": "Bull faible", "emoji": "🟡", "description": "Tendance haussière modérée"},
        2: {"name": "Bear", "emoji": "🔴", "description": "Tendance baissière"},
        3: {"name": "Ranging", "emoji": "⚪", "description": "Consolidation"},
    }


def get_recommended_regimes_for_strategy(strategy_key: str) -> list[int]:
    """Récupère les régimes recommandés pour une stratégie.

    Args:
        strategy_key: Clé de la stratégie

    Returns:
        Liste des régimes recommandés

    """
    # Stratégies long → préférer Bull + Ranging
    if "long" in strategy_key.lower():
        return [0, 2]  # Bull, Ranging

    # Stratégies short → préférer Bear + Ranging
    if "short" in strategy_key.lower():
        return [1, 2]  # Bear, Ranging

    # Stratégies mean-reversion → préférer Ranging
    if "reversal" in strategy_key.lower() or "mean" in strategy_key.lower():
        return [2]  # Ranging

    # Par défaut: tous les régimes
    return [0, 1, 2]


# ============================================================================
# PARAMETER INJECTION
# ============================================================================


def inject_markov_params(
    params: dict[str, Any],
    config: MarkovFilterConfig,
) -> dict[str, Any]:
    """Injecte les paramètres Markov dans un dict de paramètres backtest.

    Args:
        params: Dict de paramètres existant
        config: Configuration Markov

    Returns:
        Dict de paramètres mis à jour

    """
    updated = dict(params)
    updated.update(config.to_params_dict())
    return updated


def extract_markov_config_from_params(params: dict[str, Any]) -> MarkovFilterConfig:
    """Extrait une configuration Markov depuis un dict de paramètres.

    Args:
        params: Dict de paramètres backtest

    Returns:
        MarkovFilterConfig extraite

    """
    return MarkovFilterConfig(
        enabled=params.get("use_markov_filter", False),
        allowed_regimes=params.get("markov_allowed_regimes", [0, 1, 2]),
        resample_tf=params.get("markov_resample", "1h"),
        k_regimes=params.get("markov_regimes", 3),
    )
