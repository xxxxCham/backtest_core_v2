"""
Module: data.token_classification

Purpose: Classification automatique des tokens par volatilité (ATR historique).

Functions:
- calculate_token_volatility(): Calcule ATR sur période donnée
- classify_token(): Classe token (high/medium/low volatility)
- get_tokens_by_profile(): Retourne tokens d'un profil donné
- load_token_profiles(): Charge config depuis token_profiles.json
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from data.loader import load_ohlcv
from utils.log import get_logger

logger = get_logger(__name__)


def load_token_profiles() -> Dict:
    """Charge la configuration des profils de tokens depuis JSON."""
    config_path = Path(__file__).parent.parent / "config" / "token_profiles.json"
    if not config_path.exists():
        logger.warning(f"Fichier token_profiles.json introuvable : {config_path}")
        return {"profiles": {}, "archetype_recommendations": {}}

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_token_volatility(
    symbol: str,
    timeframe: str = "1d",
    period_days: int = 30,
    atr_period: int = 14,
) -> Optional[float]:
    """
    Calcule la volatilité moyenne d'un token via ATR (Average True Range).

    Args:
        symbol: Token à analyser (ex: "BTCUSDC")
        timeframe: Timeframe pour l'analyse (recommandé: "1d")
        period_days: Nombre de jours d'historique à analyser
        atr_period: Période de calcul de l'ATR

    Returns:
        ATR moyen en % du prix (ex: 4.2 = 4.2% de volatilité daily), ou None si erreur
    """
    try:
        # Charger données historiques
        df = load_ohlcv(symbol, timeframe)
        if df is None or len(df) < atr_period + period_days:
            logger.warning(f"Données insuffisantes pour {symbol}/{timeframe}")
            return None

        # Prendre les N derniers jours
        df = df.tail(period_days)

        # Calculer True Range
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift(1))
        low_close = np.abs(df["low"] - df["close"].shift(1))

        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

        # ATR = moyenne mobile du True Range
        atr = true_range.rolling(window=atr_period).mean()

        # ATR en % du prix (normalize par le close moyen)
        avg_price = df["close"].mean()
        atr_pct = (atr.mean() / avg_price) * 100

        logger.info(f"{symbol} volatilité (ATR {atr_period}d): {atr_pct:.2f}%")
        return float(atr_pct)

    except Exception as e:
        logger.error(f"Erreur calcul volatilité {symbol}: {e}")
        return None


def classify_token(
    symbol: str,
    use_historical: bool = False,
    timeframe: str = "1d",
) -> str:
    """
    Classe un token selon sa volatilité.

    Args:
        symbol: Token à classer
        use_historical: Si True, calcule volatilité sur historique. Sinon, utilise liste manuelle.
        timeframe: Timeframe pour le calcul historique

    Returns:
        Profil du token: "high_volatility", "medium_volatility", "low_volatility"
    """
    config = load_token_profiles()
    profiles = config.get("profiles", {})

    # Méthode 1 : Liste manuelle (rapide)
    if not use_historical:
        for profile_name, profile_data in profiles.items():
            if symbol in profile_data.get("tokens", []):
                return profile_name
        # Fallback : medium par défaut
        return "medium_volatility"

    # Méthode 2 : Calcul historique (précis mais lent)
    atr_pct = calculate_token_volatility(symbol, timeframe)
    if atr_pct is None:
        # Fallback sur liste manuelle
        return classify_token(symbol, use_historical=False)

    # Classification par seuils
    if atr_pct >= 4.0:
        return "high_volatility"
    elif atr_pct >= 2.0:
        return "medium_volatility"
    else:
        return "low_volatility"


def get_tokens_by_profile(
    profile: str,
    fallback_to_all: bool = True,
) -> List[str]:
    """
    Retourne la liste des tokens d'un profil donné.

    Args:
        profile: Profil recherché ("high_volatility", "medium_volatility", "low_volatility", "any")
        fallback_to_all: Si True et profil inconnu, retourne tous les tokens

    Returns:
        Liste des tokens du profil
    """
    config = load_token_profiles()
    profiles = config.get("profiles", {})

    if profile == "any" or profile not in profiles:
        if fallback_to_all:
            # Retourner tous les tokens de tous les profils
            all_tokens = []
            for profile_data in profiles.values():
                all_tokens.extend(profile_data.get("tokens", []))
            return list(set(all_tokens))  # Dédupliquer
        return []

    return profiles[profile].get("tokens", [])


def get_recommended_timeframes(archetype: str) -> List[str]:
    """
    Retourne les timeframes recommandés pour un archetype de stratégie.

    Args:
        archetype: Type de stratégie ("scalping", "day_trading", "swing", "trend_following", etc.)

    Returns:
        Liste des timeframes recommandés (ex: ["3m", "5m"])
    """
    config = load_token_profiles()
    recommendations = config.get("archetype_recommendations", {})

    if archetype not in recommendations:
        logger.warning(f"Archetype inconnu: {archetype}, fallback TFs génériques")
        return ["15m", "1h", "4h"]  # Fallback générique

    return recommendations[archetype].get("timeframes", ["1h"])


def get_preferred_timeframe(archetype: str) -> str:
    """
    Retourne le timeframe préféré pour un archetype.

    Args:
        archetype: Type de stratégie

    Returns:
        Timeframe préféré (ex: "3m", "1h")
    """
    config = load_token_profiles()
    recommendations = config.get("archetype_recommendations", {})

    if archetype not in recommendations:
        return "1h"  # Fallback

    return recommendations[archetype].get("preferred_tf", "1h")


def get_recommended_token_profile(archetype: str) -> str:
    """
    Retourne le profil de token recommandé pour un archetype.

    Args:
        archetype: Type de stratégie

    Returns:
        Profil recommandé ("high_volatility", "medium_volatility", "low_volatility", "any")
    """
    config = load_token_profiles()
    recommendations = config.get("archetype_recommendations", {})

    if archetype not in recommendations:
        return "any"

    return recommendations[archetype].get("token_profile", "any")


if __name__ == "__main__":
    # Test rapide
    print("=== Test classification tokens ===")

    # Test liste manuelle
    print(f"\nBTC (manuel): {classify_token('BTCUSDC', use_historical=False)}")
    print(f"ADA (manuel): {classify_token('ADAUSDC', use_historical=False)}")

    # Test récupération par profil
    high_vol = get_tokens_by_profile("high_volatility")
    print(f"\nTokens haute volatilité: {high_vol}")

    # Test recommandations archetype
    scalping_tfs = get_recommended_timeframes("scalping")
    scalping_tokens = get_tokens_by_profile(get_recommended_token_profile("scalping"))
    print(f"\nScalping → TFs: {scalping_tfs}, Tokens: {scalping_tokens}")

    # Test calcul volatilité historique (optionnel, plus lent)
    # print(f"\nBTC volatilité historique: {calculate_token_volatility('BTCUSDC', '1d', period_days=30):.2f}%")
