"""
Module-ID: config.market_selection

Purpose: Config centralisée pour la sélection des marchés (tokens × timeframes).

Role in pipeline: Configuration / defaults

Key components: get_market_config, get_default_symbol, get_potential_tokens

Inputs: market_selection.json, env vars (BACKTEST_DEFAULT_SYMBOL, etc.)

Outputs: Dictionnaire de config avec fallbacks + overrides

Dependencies: Aucune (lecture JSON pure)

Conventions: Config JSON + overrides env vars

Read-if: Modification des defaults de sélection marché

Skip-if: Logique de sélection runtime (voir ui/sidebar.py, ui/builder_view.py)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

_CONFIG_PATH = Path(__file__).parent / "market_selection.json"
_CONFIG_CACHE: Dict[str, Any] | None = None


def get_market_config() -> Dict[str, Any]:
    """
    Charge la config de sélection marché depuis JSON + overrides env vars.

    Returns:
        Dictionnaire avec clés: defaults, diversity, hints, potential_tokens

    Cache:
        Config chargée 1× par process (pas de hot-reload)

    Env vars overrides:
        - BACKTEST_DEFAULT_SYMBOL: Override defaults.symbol
        - BACKTEST_DEFAULT_TIMEFRAME: Override defaults.timeframe
        - BACKTEST_DIVERSITY_WINDOW: Override diversity.window_size (int)
    """
    global _CONFIG_CACHE

    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    # Charger JSON
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Config marché manquante: {_CONFIG_PATH}\n"
            "Créer config/market_selection.json avec defaults/diversity/hints/potential_tokens."
        )

    with open(_CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)

    # Overrides env vars
    if "BACKTEST_DEFAULT_SYMBOL" in os.environ:
        config["defaults"]["symbol"] = os.environ["BACKTEST_DEFAULT_SYMBOL"].strip().upper()

    if "BACKTEST_DEFAULT_TIMEFRAME" in os.environ:
        config["defaults"]["timeframe"] = os.environ["BACKTEST_DEFAULT_TIMEFRAME"].strip()

    if "BACKTEST_DIVERSITY_WINDOW" in os.environ:
        try:
            config["diversity"]["window_size"] = int(os.environ["BACKTEST_DIVERSITY_WINDOW"])
        except ValueError:
            pass  # Ignorer override invalide

    _CONFIG_CACHE = config
    return config


def get_default_symbol() -> str:
    """Retourne le symbole par défaut (avec override env var)."""
    return str(get_market_config()["defaults"]["symbol"])


def get_default_timeframe() -> str:
    """Retourne le timeframe par défaut (avec override env var)."""
    return str(get_market_config()["defaults"]["timeframe"])


def get_potential_tokens() -> List[str]:
    """Retourne la liste des tokens à potentiel (blue-chip)."""
    return list(get_market_config()["potential_tokens"])


def get_diversity_window() -> int:
    """Retourne la taille de la fenêtre de diversité (recent_markets)."""
    return int(get_market_config()["diversity"]["window_size"])


def get_diversity_min_alternatives() -> int:
    """Retourne le nombre minimum d'alternatives pour activer la diversité."""
    return int(get_market_config()["diversity"]["min_alternatives"])


def get_hints_confidence_boost() -> float:
    """Retourne le boost de confiance appliqué quand hints détectés dans l'objectif."""
    return float(get_market_config()["hints"]["confidence_boost"])


def get_token_profile(symbol: str) -> Dict[str, Any]:
    """
    Retourne le profil d'un token (volatilité, liquidité, stratégies recommandées).

    Args:
        symbol: Symbole du token (ex: "BTCUSDC")

    Returns:
        Dict avec keys: volatility, liquidity, strategies
        Retourne un profil par défaut si le token n'est pas trouvé
    """
    config = get_market_config()
    profiles = config.get("token_profiles", {})

    # Profil par défaut pour tokens inconnus.
    # Conservative by design: avoid over-prioritizing unknown assets.
    default_profile = {
        "volatility": "medium",
        "liquidity": "low",
        "strategies": []
    }

    return profiles.get(symbol.upper(), default_profile)


def get_strategy_requirements(strategy_type: str) -> Dict[str, Any]:
    """
    Retourne les exigences pour un type de stratégie.

    Args:
        strategy_type: Type de stratégie (scalping, breakout, momentum, trend, mean_reversion)

    Returns:
        Dict avec keys: volatility_preferred, liquidity_min, timeframes
    """
    config = get_market_config()
    requirements = config.get("strategy_requirements", {})

    # Exigences par défaut
    default_reqs = {
        "volatility_preferred": ["medium"],
        "liquidity_min": "medium",
        "timeframes": ["1h", "4h"]
    }

    return requirements.get(strategy_type.lower(), default_reqs)


def rank_tokens_for_strategy(
    candidate_tokens: List[str],
    strategy_type: str,
) -> List[str]:
    """
    Trie les tokens par pertinence pour un type de stratégie donné.

    Args:
        candidate_tokens: Liste de tokens candidats
        strategy_type: Type de stratégie détecté (scalping, breakout, momentum, trend, mean_reversion)

    Returns:
        Liste de tokens triés par pertinence décroissante
    """
    reqs = get_strategy_requirements(strategy_type)
    preferred_volatility = reqs.get("volatility_preferred", ["medium"])
    min_liquidity = reqs.get("liquidity_min", "medium")

    # Score de pertinence pour chaque token
    scored_tokens: List[Tuple[str, int]] = []

    liquidity_rank = {"high": 3, "medium": 2, "low": 1}
    volatility_rank = {"high": 3, "medium": 2, "low": 1}

    for token in candidate_tokens:
        profile = get_token_profile(token)
        score = 0

        # Score volatilité (prioritaire)
        token_volatility = profile.get("volatility", "medium")
        if token_volatility in preferred_volatility:
            score += 10  # Bonus fort si volatilité exactement recommandée

        # Score liquidité (filtre)
        token_liquidity = profile.get("liquidity", "medium")
        if liquidity_rank.get(token_liquidity, 0) >= liquidity_rank.get(min_liquidity, 0):
            score += 5  # Bonus si liquidité suffisante
        else:
            score -= 10  # Pénalité si liquidité insuffisante

        # Score stratégies recommandées
        token_strategies = profile.get("strategies", [])
        if strategy_type in token_strategies:
            score += 3  # Bonus si stratégie dans la liste recommandée

        scored_tokens.append((token, score))

    # Trier par score décroissant.
    # IMPORTANT: garder un tri stable sur ordre d'entrée pour pouvoir
    # randomiser les égalités en amont (anti-biais "toujours le même token").
    scored_tokens.sort(key=lambda x: x[1], reverse=True)

    return [token for token, _ in scored_tokens]
