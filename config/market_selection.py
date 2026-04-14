"""
Module-ID: config.market_selection

Purpose: Config centralisée et logique canonique de sélection des marchés
         (tokens × timeframes) pour Builder / validation / graduation.

Role in pipeline: Configuration / garde-fous runtime

Key components: get_market_config, get_canonical_tokens, evaluate_market_dataset,
                filter_market_universe, infer_strategy_type

Inputs: market_selection.json, env vars (BACKTEST_DEFAULT_SYMBOL, etc.),
        OHLCV locaux quand un filtrage runtime est demandé

Outputs: Dictionnaire de config + décisions d'éligibilité traçables

Dependencies: pandas, numpy, data.config, data.loader

Conventions: Config JSON + overrides env vars + critères locaux prioritaires

Read-if: Modification des defaults de sélection marché

Skip-if: Exécution pure des backtests
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

_CONFIG_PATH = Path(__file__).parent / "market_selection.json"
_CONFIG_CACHE: Dict[str, Any] | None = None
logger = logging.getLogger(__name__)

UNIVERSE_MODE_CANONICAL = "canonical"
UNIVERSE_MODE_EXPLORATORY = "exploratory"
UNIVERSE_MODE_OPTIONS = (
    UNIVERSE_MODE_CANONICAL,
    UNIVERSE_MODE_EXPLORATORY,
)

_LIQUIDITY_RANK = {"high": 3, "medium": 2, "low": 1}
_DEFAULT_UNIVERSE_CONFIG: Dict[str, Any] = {
    "default_mode": UNIVERSE_MODE_CANONICAL,
    "purpose_defaults": {
        "builder": UNIVERSE_MODE_CANONICAL,
        "builder_manual": UNIVERSE_MODE_CANONICAL,
        "builder_auto_market": UNIVERSE_MODE_CANONICAL,
        "builder_autonomous": UNIVERSE_MODE_CANONICAL,
        "validation": UNIVERSE_MODE_CANONICAL,
        "graduation": UNIVERSE_MODE_CANONICAL,
    },
    "exploratory_opt_in_required": True,
    "canonical_source": "postfilter_benchmarks_union",
    "canonical_tokens": [],
    "local_filters": {
        "min_segment_bars_floor": 300,
        "canonical_segment_days_multiplier": 1.0,
        "canonical_min_segment_bars_by_timeframe": {
            "1w": 400,
        },
        "min_listing_age_days": 45,
        "min_tradable_ratio_hard": 0.75,
        "min_tradable_ratio_canonical": 0.90,
        "min_median_dollar_volume_canonical": 250000.0,
        "min_median_volume_canonical": 1000.0,
        "volatility_window_bars": 96,
        "annualized_volatility_bands_pct": {
            "low": 60.0,
            "medium": 140.0,
        },
    },
    "secondary_filters": {
        "market_cap_enabled": False,
        "market_cap_min": 0.0,
    },
}

_STRATEGY_TYPE_ALIASES = {
    "trend-following": "trend",
    "trend_following": "trend",
    "mean reversion": "mean_reversion",
    "mean-reversion": "mean_reversion",
    "reversion": "mean_reversion",
    "mr": "mean_reversion",
}
_STRATEGY_TYPE_PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("scalping", ("scalp", "scalping", "court terme", "rapide")),
    ("breakout", ("breakout", "cassure", "donchian", "sortie de range", "sortie range")),
    ("momentum", ("momentum", "directionnel", "acceleration", "accélération", "roc")),
    ("trend", ("trend", "tendance", "trend-following", "trend following", "suivi de tendance", "suivre")),
    (
        "mean_reversion",
        ("mean reversion", "mean_reversion", "mean-reversion", "retour a la moyenne", "retour à la moyenne", "survente", "surachat"),
    ),
)


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


def get_universe_config() -> Dict[str, Any]:
    """Retourne la configuration de l'univers marché avec fallbacks conservateurs."""
    payload = get_market_config().get("universe", {})
    if not isinstance(payload, dict):
        payload = {}

    merged: Dict[str, Any] = dict(_DEFAULT_UNIVERSE_CONFIG)
    for key, default_value in _DEFAULT_UNIVERSE_CONFIG.items():
        candidate_value = payload.get(key)
        if isinstance(default_value, dict):
            merged[key] = dict(default_value)
            if isinstance(candidate_value, dict):
                merged[key].update(candidate_value)
        else:
            merged[key] = candidate_value if candidate_value not in (None, "") else default_value
    return merged


def normalize_universe_mode(
    raw_value: Any,
    *,
    purpose: str = "builder",
) -> str:
    """Normalise le mode d'univers. Conservateur par défaut."""
    normalized = str(raw_value or "").strip().lower()
    if normalized in UNIVERSE_MODE_OPTIONS:
        return normalized

    universe_cfg = get_universe_config()
    purpose_defaults = universe_cfg.get("purpose_defaults", {})
    if isinstance(purpose_defaults, dict):
        purpose_default = str(purpose_defaults.get(str(purpose or "").strip(), "") or "").strip().lower()
        if purpose_default in UNIVERSE_MODE_OPTIONS:
            return purpose_default

    default_mode = str(universe_cfg.get("default_mode", UNIVERSE_MODE_CANONICAL) or "").strip().lower()
    if default_mode in UNIVERSE_MODE_OPTIONS:
        return default_mode
    return UNIVERSE_MODE_CANONICAL


def get_canonical_tokens() -> List[str]:
    """Retourne l'univers canonique ordonné utilisé pour les runs robustes."""
    universe_cfg = get_universe_config()
    explicit_tokens = universe_cfg.get("canonical_tokens", [])
    if isinstance(explicit_tokens, list):
        normalized_explicit = [
            str(token or "").strip().upper()
            for token in explicit_tokens
            if str(token or "").strip()
        ]
        if normalized_explicit:
            return list(dict.fromkeys(normalized_explicit))

    source = str(universe_cfg.get("canonical_source", "postfilter_benchmarks_union") or "").strip().lower()
    if source == "potential_tokens":
        return [
            str(token or "").strip().upper()
            for token in get_potential_tokens()
            if str(token or "").strip()
        ]

    payload = get_postfilter_benchmark_config()
    benchmarks = payload.get("benchmarks", {}) if isinstance(payload, dict) else {}
    ordered_tokens: List[str] = []
    if isinstance(benchmarks, dict):
        benchmark_names = get_postfilter_benchmark_names()
        if not benchmark_names:
            benchmark_names = list(benchmarks.keys())
        for benchmark_name in benchmark_names:
            benchmark = benchmarks.get(benchmark_name, {})
            tokens = benchmark.get("tokens", []) if isinstance(benchmark, dict) else []
            for token in tokens:
                normalized = str(token or "").strip().upper()
                if normalized:
                    ordered_tokens.append(normalized)
    if ordered_tokens:
        return list(dict.fromkeys(ordered_tokens))

    return [
        str(token or "").strip().upper()
        for token in get_potential_tokens()
        if str(token or "").strip()
    ]


def get_postfilter_benchmark_config() -> Dict[str, Any]:
    """Retourne la configuration des benchmarks canoniques de post-filtrage."""
    payload = get_market_config().get("postfilter_benchmarks", {})
    if not isinstance(payload, dict):
        return {}
    return payload


def get_postfilter_benchmark_names() -> List[str]:
    """Retourne la liste ordonnée des benchmarks canoniques à utiliser."""
    payload = get_postfilter_benchmark_config()
    names = payload.get("default_benchmark_names", [])
    if not isinstance(names, list):
        return []
    return [str(name).strip() for name in names if str(name).strip()]


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

    normalized_type = infer_strategy_type(strategy_type=strategy_type)
    if normalized_type == "unknown":
        normalized_type = str(strategy_type or "").strip().lower()
    return requirements.get(normalized_type, default_reqs)


def infer_strategy_type(
    *,
    strategy_type: str = "",
    strategy_key: str = "",
    objective: str = "",
) -> str:
    """
    Infère un type de stratégie simple et stable.

    Retourne l'un des types connus (`scalping`, `breakout`, `momentum`,
    `trend`, `mean_reversion`) ou `unknown`.
    """
    for raw_value in (strategy_type, strategy_key):
        normalized = str(raw_value or "").strip().lower().replace("__", "_")
        normalized = _STRATEGY_TYPE_ALIASES.get(normalized, normalized)
        if normalized in {"scalping", "breakout", "momentum", "trend", "mean_reversion"}:
            return normalized

    objective_text = str(objective or "").strip().lower()
    family_match = re.search(r"\bfamily\s*:\s*([a-zA-Z0-9_\- ]+)", objective_text)
    if family_match:
        family_value = family_match.group(1).strip().lower()
        family_value = _STRATEGY_TYPE_ALIASES.get(family_value, family_value.replace(" ", "_"))
        if family_value in {"scalping", "breakout", "momentum", "trend", "mean_reversion"}:
            return family_value

    for resolved_type, keywords in _STRATEGY_TYPE_PATTERNS:
        if any(keyword in objective_text for keyword in keywords):
            return resolved_type

    lower_key = str(strategy_key or "").strip().lower()
    for resolved_type, keywords in _STRATEGY_TYPE_PATTERNS:
        if any(keyword.replace(" ", "_") in lower_key for keyword in keywords):
            return resolved_type
    return "unknown"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(parsed) or math.isinf(parsed):
        return default
    return parsed


def _timeframe_to_timedelta(timeframe: str) -> Optional[pd.Timedelta]:
    raw = str(timeframe or "").strip()
    if len(raw) < 2:
        return None
    unit = raw[-1]
    try:
        amount = int(raw[:-1])
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    if unit == "m":
        return pd.Timedelta(minutes=amount)
    if unit == "h":
        return pd.Timedelta(hours=amount)
    if unit == "d":
        return pd.Timedelta(days=amount)
    if unit == "w":
        return pd.Timedelta(weeks=amount)
    if unit == "M":
        return pd.Timedelta(days=30 * amount)
    return None


def _bars_per_day(timeframe: str) -> float:
    delta = _timeframe_to_timedelta(timeframe)
    if delta is None:
        return 1.0
    total_seconds = max(delta.total_seconds(), 60.0)
    return 86400.0 / total_seconds


def _annualization_factor(timeframe: str) -> float:
    return max(1.0, _bars_per_day(timeframe) * 365.0)


def _max_contiguous_segment_bars(df: pd.DataFrame, timeframe: str) -> int:
    if df is None or df.empty:
        return 0
    expected = _timeframe_to_timedelta(timeframe)
    if expected is None:
        return int(len(df))
    idx = getattr(df, "index", None)
    if not isinstance(idx, pd.DatetimeIndex) or len(idx) <= 1:
        return int(len(df))
    diffs = idx[1:] - idx[:-1]
    major_gap = diffs > (expected * 3)
    if not np.any(major_gap):
        return int(len(df))
    cut_positions = np.where(major_gap)[0]
    starts = [0, *[int(pos) + 1 for pos in cut_positions]]
    ends = [*[int(pos) + 1 for pos in cut_positions], len(df)]
    lengths = [int(end - start) for start, end in zip(starts, ends)]
    return max(lengths) if lengths else int(len(df))


def _volatility_bucket(volatility_annual_pct: float) -> str:
    filters = get_universe_config().get("local_filters", {})
    bands = filters.get("annualized_volatility_bands_pct", {})
    low_band = _safe_float((bands or {}).get("low"), 60.0)
    medium_band = _safe_float((bands or {}).get("medium"), 140.0)
    if volatility_annual_pct <= low_band:
        return "low"
    if volatility_annual_pct <= medium_band:
        return "medium"
    return "high"


def _compute_tradable_ratio(df: pd.DataFrame) -> float:
    if df is None or df.empty:
        return 0.0
    try:
        if "_tradable" in df.columns:
            tradable = pd.Series(df["_tradable"]).fillna(False).astype(bool)
            return float(tradable.mean())
        if "volume" in df.columns:
            volume = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
            return float((volume > 0).mean())
    except Exception:
        return 0.0
    return 1.0


def _compute_median_volume(df: pd.DataFrame) -> float:
    if df is None or df.empty or "volume" not in df.columns:
        return 0.0
    try:
        volume = pd.to_numeric(df["volume"], errors="coerce")
        volume = volume.replace([np.inf, -np.inf], np.nan).dropna()
        volume = volume[volume > 0]
        if volume.empty:
            return 0.0
        return _safe_float(volume.median(), 0.0)
    except Exception:
        return 0.0


def _compute_median_dollar_volume(df: pd.DataFrame) -> float:
    if df is None or df.empty or "volume" not in df.columns:
        return 0.0
    price_column = "close" if "close" in df.columns else None
    if price_column is None:
        return 0.0
    try:
        volume = pd.to_numeric(df["volume"], errors="coerce")
        close = pd.to_numeric(df[price_column], errors="coerce")
        dollar_volume = (volume * close).replace([np.inf, -np.inf], np.nan).dropna()
        dollar_volume = dollar_volume[dollar_volume > 0]
        if dollar_volume.empty:
            return 0.0
        return _safe_float(dollar_volume.median(), 0.0)
    except Exception:
        return 0.0


def _compute_listing_age_days(df: pd.DataFrame, timeframe: str) -> float:
    if df is None or df.empty:
        return 0.0
    idx = getattr(df, "index", None)
    if isinstance(idx, pd.DatetimeIndex) and len(idx) >= 2:
        try:
            return max(0.0, float((idx.max() - idx.min()).total_seconds()) / 86400.0)
        except Exception:
            pass
    return max(0.0, float(len(df)) / max(_bars_per_day(timeframe), 1e-9))


def _compute_annualized_volatility_pct(df: pd.DataFrame, timeframe: str, window_bars: int) -> float:
    if df is None or df.empty or "close" not in df.columns:
        return 0.0
    try:
        close = pd.to_numeric(df["close"], errors="coerce").replace([np.inf, -np.inf], np.nan)
        close = close[close > 0].dropna()
        if len(close) < 3:
            return 0.0
        returns = np.log(close).diff().replace([np.inf, -np.inf], np.nan).dropna()
        if returns.empty:
            return 0.0
        window = max(5, int(window_bars or 0))
        rolling_std = returns.rolling(window=window, min_periods=max(5, min(window, 20))).std().dropna()
        sigma = _safe_float(rolling_std.median(), 0.0) if not rolling_std.empty else _safe_float(returns.std(), 0.0)
        return max(0.0, sigma * math.sqrt(_annualization_factor(timeframe)) * 100.0)
    except Exception:
        return 0.0


def _normalize_market_pairs(
    symbols: List[str],
    timeframes: List[str],
) -> List[Tuple[str, str]]:
    clean_symbols = list(
        dict.fromkeys(
            str(symbol or "").strip().upper()
            for symbol in symbols
            if str(symbol or "").strip()
        )
    )
    clean_timeframes = list(
        dict.fromkeys(
            str(timeframe or "").strip()
            for timeframe in timeframes
            if str(timeframe or "").strip()
        )
    )
    return [(symbol, timeframe) for symbol in clean_symbols for timeframe in clean_timeframes]


def evaluate_market_dataset(
    df: Optional[pd.DataFrame],
    *,
    symbol: str,
    timeframe: str,
    universe_mode: Any = None,
    purpose: str = "builder",
    strategy_type: str = "",
    strategy_key: str = "",
    objective: str = "",
    token_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Évalue l'éligibilité d'un marché à partir des données locales disponibles."""
    normalized_symbol = str(symbol or "").strip().upper()
    normalized_timeframe = str(timeframe or "").strip()
    normalized_mode = normalize_universe_mode(universe_mode, purpose=purpose)
    normalized_strategy = infer_strategy_type(
        strategy_type=strategy_type,
        strategy_key=strategy_key,
        objective=objective,
    )
    profile = (
        dict(token_profile)
        if isinstance(token_profile, dict)
        else get_token_profile(normalized_symbol)
    )
    requirements = get_strategy_requirements(normalized_strategy)
    universe_cfg = get_universe_config()
    local_filters = dict(universe_cfg.get("local_filters", {}) or {})
    secondary_filters = dict(universe_cfg.get("secondary_filters", {}) or {})

    try:
        from data.config import get_min_period_days_for_timeframes

        timeframe_min_days = int(
            get_min_period_days_for_timeframes([normalized_timeframe])
        )
    except Exception:
        timeframe_min_days = 30

    min_segment_bars_floor = max(
        1,
        int(_safe_float(local_filters.get("min_segment_bars_floor"), 300)),
    )
    timeframe_segment_overrides = dict(
        local_filters.get("canonical_min_segment_bars_by_timeframe", {}) or {}
    )
    canonical_segment_days_multiplier = max(
        0.25,
        _safe_float(local_filters.get("canonical_segment_days_multiplier"), 1.0),
    )
    recommended_segment_bars = int(
        math.ceil(
            max(1.0, float(timeframe_min_days) * canonical_segment_days_multiplier)
            * _bars_per_day(normalized_timeframe)
        )
    )
    min_segment_bars_required = (
        max(min_segment_bars_floor, recommended_segment_bars)
        if normalized_mode == UNIVERSE_MODE_CANONICAL
        else min_segment_bars_floor
    )
    timeframe_specific_min_segment_bars = max(
        0,
        int(_safe_float(timeframe_segment_overrides.get(normalized_timeframe), 0.0)),
    )
    if normalized_mode == UNIVERSE_MODE_CANONICAL and timeframe_specific_min_segment_bars > 0:
        min_segment_bars_required = max(
            min_segment_bars_required,
            timeframe_specific_min_segment_bars,
        )
    min_listing_age_days = max(
        _safe_float(local_filters.get("min_listing_age_days"), 45.0),
        float(timeframe_min_days) if normalized_mode == UNIVERSE_MODE_CANONICAL else 0.0,
    )
    min_tradable_ratio_hard = max(
        0.0,
        min(1.0, _safe_float(local_filters.get("min_tradable_ratio_hard"), 0.75)),
    )
    min_tradable_ratio_canonical = max(
        min_tradable_ratio_hard,
        min(1.0, _safe_float(local_filters.get("min_tradable_ratio_canonical"), 0.90)),
    )
    min_median_dollar_volume = max(
        0.0,
        _safe_float(local_filters.get("min_median_dollar_volume_canonical"), 250000.0),
    )
    min_median_volume = max(
        0.0,
        _safe_float(local_filters.get("min_median_volume_canonical"), 1000.0),
    )
    volatility_window_bars = max(
        5,
        int(_safe_float(local_filters.get("volatility_window_bars"), 96)),
    )

    applied_criteria: Dict[str, Any] = {
        "purpose": str(purpose or "builder"),
        "universe_mode": normalized_mode,
        "strategy_type": normalized_strategy,
        "canonical_tokens": get_canonical_tokens() if normalized_mode == UNIVERSE_MODE_CANONICAL else [],
        "min_segment_bars_required": min_segment_bars_required,
        "timeframe_specific_min_segment_bars": timeframe_specific_min_segment_bars,
        "min_listing_age_days": min_listing_age_days,
        "min_tradable_ratio_hard": min_tradable_ratio_hard,
        "min_tradable_ratio_canonical": min_tradable_ratio_canonical,
        "min_median_dollar_volume_canonical": min_median_dollar_volume,
        "min_median_volume_canonical": min_median_volume,
        "volatility_preferred": list(requirements.get("volatility_preferred", ["medium"])),
        "liquidity_min": str(requirements.get("liquidity_min", "medium") or "medium"),
        "volatility_window_bars": volatility_window_bars,
    }

    result: Dict[str, Any] = {
        "accepted": False,
        "symbol": normalized_symbol,
        "timeframe": normalized_timeframe,
        "universe_mode": normalized_mode,
        "purpose": str(purpose or "builder"),
        "strategy_type": normalized_strategy,
        "warnings": [],
        "exclusion_reasons": [],
        "applied_criteria": applied_criteria,
        "local_metrics": {
            "n_bars": 0,
            "listing_age_days": 0.0,
            "max_contiguous_bars": 0,
            "min_contiguous_bars_required": min_segment_bars_required,
            "tradable_ratio": 0.0,
            "median_volume": 0.0,
            "median_dollar_volume": 0.0,
            "liquidity_metric_used": "volume",
            "liquidity_metric_value": 0.0,
            "volatility_annual_pct": 0.0,
            "volatility_bucket": "unknown",
            "market_cap": _safe_float(profile.get("market_cap"), 0.0),
            "market_cap_used": False,
        },
        "token_profile": profile,
        "quality_score": 0.0,
    }

    if df is None or getattr(df, "empty", True):
        result["exclusion_reasons"].append("data unavailable")
        return result

    local_metrics = result["local_metrics"]
    n_bars = int(len(df))
    local_metrics["n_bars"] = n_bars
    local_metrics["listing_age_days"] = _compute_listing_age_days(df, normalized_timeframe)
    local_metrics["max_contiguous_bars"] = _max_contiguous_segment_bars(df, normalized_timeframe)
    local_metrics["tradable_ratio"] = _compute_tradable_ratio(df)
    local_metrics["median_volume"] = _compute_median_volume(df)
    local_metrics["median_dollar_volume"] = _compute_median_dollar_volume(df)
    local_metrics["volatility_annual_pct"] = _compute_annualized_volatility_pct(
        df,
        normalized_timeframe,
        volatility_window_bars,
    )
    local_metrics["volatility_bucket"] = _volatility_bucket(local_metrics["volatility_annual_pct"])

    if local_metrics["median_dollar_volume"] > 0:
        local_metrics["liquidity_metric_used"] = "median_dollar_volume"
        local_metrics["liquidity_metric_value"] = local_metrics["median_dollar_volume"]
    else:
        local_metrics["liquidity_metric_used"] = "median_volume"
        local_metrics["liquidity_metric_value"] = local_metrics["median_volume"]

    exclusion_reasons: List[str] = result["exclusion_reasons"]
    warnings: List[str] = result["warnings"]

    if n_bars < min_segment_bars_floor:
        exclusion_reasons.append(
            f"dataset insufficient ({n_bars} bars < {min_segment_bars_floor})"
        )

    if local_metrics["max_contiguous_bars"] < min_segment_bars_required:
        exclusion_reasons.append(
            "continuous segment insufficient "
            f"({local_metrics['max_contiguous_bars']} bars < {min_segment_bars_required})"
        )

    if local_metrics["tradable_ratio"] < min_tradable_ratio_hard:
        exclusion_reasons.append(
            f"tradable ratio too low ({local_metrics['tradable_ratio']:.1%} < {min_tradable_ratio_hard:.0%})"
        )

    canonical_tokens = set(applied_criteria["canonical_tokens"] or [])
    if normalized_mode == UNIVERSE_MODE_CANONICAL and canonical_tokens:
        if normalized_symbol not in canonical_tokens:
            exclusion_reasons.append("outside canonical universe")

    if (
        normalized_mode == UNIVERSE_MODE_CANONICAL
        and local_metrics["listing_age_days"] < min_listing_age_days
    ):
        exclusion_reasons.append(
            "listing too recent "
            f"({local_metrics['listing_age_days']:.1f}d < {min_listing_age_days:.1f}d)"
        )

    if (
        normalized_mode == UNIVERSE_MODE_CANONICAL
        and local_metrics["tradable_ratio"] < min_tradable_ratio_canonical
    ):
        exclusion_reasons.append(
            "tradable ratio below canonical threshold "
            f"({local_metrics['tradable_ratio']:.1%} < {min_tradable_ratio_canonical:.0%})"
        )

    if normalized_mode == UNIVERSE_MODE_CANONICAL:
        if local_metrics["median_dollar_volume"] > 0:
            if local_metrics["median_dollar_volume"] < min_median_dollar_volume:
                exclusion_reasons.append(
                    "median dollar volume insufficient "
                    f"({local_metrics['median_dollar_volume']:.0f} < {min_median_dollar_volume:.0f})"
                )
        elif local_metrics["median_volume"] < min_median_volume:
            exclusion_reasons.append(
                "median volume insufficient "
                f"({local_metrics['median_volume']:.0f} < {min_median_volume:.0f})"
            )
        else:
            warnings.append("median dollar volume unavailable, fallback to median volume")

    preferred_volatility = list(requirements.get("volatility_preferred", ["medium"]))
    if (
        normalized_mode == UNIVERSE_MODE_CANONICAL
        and preferred_volatility
        and local_metrics["volatility_bucket"] not in preferred_volatility
    ):
        exclusion_reasons.append(
            "volatility profile mismatch "
            f"({local_metrics['volatility_bucket']} not in {preferred_volatility})"
        )

    market_cap_enabled = bool(secondary_filters.get("market_cap_enabled", False))
    market_cap_min = max(0.0, _safe_float(secondary_filters.get("market_cap_min"), 0.0))
    market_cap = _safe_float(profile.get("market_cap"), 0.0)
    local_metrics["market_cap"] = market_cap
    if market_cap_enabled:
        local_metrics["market_cap_used"] = market_cap > 0
        if market_cap <= 0:
            warnings.append("market cap unavailable, ignored")
        elif market_cap < market_cap_min:
            warnings.append(
                f"market cap below secondary threshold ({market_cap:.0f} < {market_cap_min:.0f})"
            )

    liquidity_rank = _LIQUIDITY_RANK.get(str(profile.get("liquidity", "low")).strip().lower(), 1)
    min_liquidity_rank = _LIQUIDITY_RANK.get(
        str(requirements.get("liquidity_min", "medium") or "medium").strip().lower(),
        2,
    )
    quality_score = 0.0
    quality_score += min(float(local_metrics["tradable_ratio"]) * 40.0, 40.0)
    quality_score += min(float(local_metrics["max_contiguous_bars"]) / max(min_segment_bars_required, 1) * 20.0, 20.0)
    quality_score += min(float(local_metrics["listing_age_days"]) / max(min_listing_age_days or 1.0, 1.0) * 10.0, 10.0)
    if local_metrics["median_dollar_volume"] > 0 and min_median_dollar_volume > 0:
        quality_score += min(local_metrics["median_dollar_volume"] / min_median_dollar_volume * 20.0, 20.0)
    elif local_metrics["median_volume"] > 0 and min_median_volume > 0:
        quality_score += min(local_metrics["median_volume"] / min_median_volume * 20.0, 20.0)
    if local_metrics["volatility_bucket"] in preferred_volatility:
        quality_score += 5.0
    quality_score += max(0, liquidity_rank - min_liquidity_rank) * 2.0
    result["quality_score"] = round(quality_score, 3)
    result["accepted"] = not exclusion_reasons
    return result


def filter_market_universe(
    *,
    symbols: List[str],
    timeframes: List[str],
    universe_mode: Any = None,
    purpose: str = "builder",
    strategy_type: str = "",
    strategy_key: str = "",
    objective: str = "",
    data_loader: Optional[Callable[[str, str], Optional[pd.DataFrame]]] = None,
) -> Dict[str, Any]:
    """Filtre un univers marché avec des règles partagées Builder/validation."""
    normalized_mode = normalize_universe_mode(universe_mode, purpose=purpose)
    normalized_strategy = infer_strategy_type(
        strategy_type=strategy_type,
        strategy_key=strategy_key,
        objective=objective,
    )
    pairs = _normalize_market_pairs(symbols, timeframes)
    if data_loader is None:
        from data.loader import load_ohlcv

        data_loader = load_ohlcv

    eligible_pairs: List[Dict[str, Any]] = []
    excluded_pairs: List[Dict[str, Any]] = []
    canonical_tokens = set(get_canonical_tokens()) if normalized_mode == UNIVERSE_MODE_CANONICAL else set()

    for order, (symbol, timeframe) in enumerate(pairs):
        if canonical_tokens and symbol not in canonical_tokens:
            excluded_pairs.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "accepted": False,
                    "order": order,
                    "exclusion_reasons": ["outside canonical universe"],
                }
            )
            continue
        try:
            df = data_loader(symbol, timeframe)
        except Exception as exc:
            excluded_pairs.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "accepted": False,
                    "order": order,
                    "exclusion_reasons": [f"data load failed: {exc}"],
                }
            )
            continue

        evaluation = evaluate_market_dataset(
            df,
            symbol=symbol,
            timeframe=timeframe,
            universe_mode=normalized_mode,
            purpose=purpose,
            strategy_type=normalized_strategy,
            strategy_key=strategy_key,
            objective=objective,
        )
        evaluation["order"] = order
        if evaluation.get("accepted"):
            eligible_pairs.append(evaluation)
        else:
            excluded_pairs.append(evaluation)

    eligible_pairs.sort(
        key=lambda item: (
            -_safe_float(item.get("quality_score"), 0.0),
            int(item.get("order", 0)),
        )
    )
    ordered_symbols = list(
        dict.fromkeys(
            str(item.get("symbol") or "").strip().upper()
            for item in eligible_pairs
            if str(item.get("symbol") or "").strip()
        )
    )
    ordered_timeframes = list(
        dict.fromkeys(
            str(item.get("timeframe") or "").strip()
            for item in eligible_pairs
            if str(item.get("timeframe") or "").strip()
        )
    )
    exclusion_summary: Dict[str, int] = {}
    for item in excluded_pairs:
        for reason in list(item.get("exclusion_reasons", []) or []):
            exclusion_summary[reason] = int(exclusion_summary.get(reason, 0)) + 1

    payload = {
        "universe_mode": normalized_mode,
        "purpose": str(purpose or "builder"),
        "strategy_type": normalized_strategy,
        "symbols": ordered_symbols,
        "timeframes": ordered_timeframes,
        "eligible_pairs": eligible_pairs,
        "excluded_pairs": excluded_pairs,
        "criteria": dict((eligible_pairs[0] if eligible_pairs else {}).get("applied_criteria", {}) or {}),
        "canonical_tokens": list(canonical_tokens),
        "exclusion_summary": exclusion_summary,
    }
    logger.info(
        "market_universe_filter purpose=%s mode=%s strategy_type=%s eligible=%d excluded=%d",
        payload["purpose"],
        normalized_mode,
        normalized_strategy,
        len(eligible_pairs),
        len(excluded_pairs),
    )
    return payload


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

    for token in candidate_tokens:
        profile = get_token_profile(token)
        score = 0

        # Score volatilité (prioritaire)
        token_volatility = profile.get("volatility", "medium")
        if token_volatility in preferred_volatility:
            score += 10  # Bonus fort si volatilité exactement recommandée

        # Score liquidité (filtre)
        token_liquidity = profile.get("liquidity", "medium")
        if _LIQUIDITY_RANK.get(token_liquidity, 0) >= _LIQUIDITY_RANK.get(min_liquidity, 0):
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
