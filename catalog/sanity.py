"""
Module-ID: catalog.sanity

Purpose: Pipeline de validation des variants (schema, registry, dataset, stop-loss, anti-lookahead).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from indicators.registry import get_indicator, list_indicators

from catalog.models import Variant

# Indicateurs nécessitant des colonnes exogènes (hors OHLCV standard)
_EXOGENE_INDICATORS = {"fear_greed", "onchain_smoothing", "pi_cycle"}

# Colonnes OHLCV standard
_OHLCV_COLUMNS = {"open", "high", "low", "close", "volume"}

# Indicateurs retournant un dict (clés autorisées)
_DICT_INDICATOR_ALLOWED_KEYS: Dict[str, set] = {
    "bollinger": {"upper", "middle", "lower"},
    "macd": {"macd", "signal", "histogram"},
    "stochastic": {"stoch_k", "stoch_d"},
    "adx": {"adx", "plus_di", "minus_di"},
    "supertrend": {"supertrend", "direction"},
    "ichimoku": {"tenkan", "kijun", "senkou_a", "senkou_b", "chikou", "cloud_position"},
    "psar": {"sar", "trend", "signal"},
    "vortex": {"vi_plus", "vi_minus", "signal", "oscillator"},
    "stoch_rsi": {"k", "d", "signal"},
    "aroon": {"aroon_up", "aroon_down"},
    "donchian": {"upper", "middle", "lower"},
    "keltner": {"middle", "upper", "lower"},
    "pivot_points": {"pivot", "r1", "s1", "r2", "s2", "r3", "s3"},
    "fibonacci_levels": {"high", "low"},
    "amplitude_hunter": {"range_pct", "score"},
}

# Patterns anti-lookahead dans les expressions DSL
_LOOKAHEAD_PATTERNS = [
    re.compile(r"\[t\s*\+\s*\d+\]", re.IGNORECASE),       # [t+1], [t + 2]
    re.compile(r"shift\s*\(\s*-\s*\d+\s*\)", re.IGNORECASE),  # shift(-1)
    re.compile(r"\[\s*i\s*\+\s*\d+\s*\]", re.IGNORECASE),  # [i+1]
    re.compile(r"\bfuture\b", re.IGNORECASE),
    re.compile(r"\btomorrow\b", re.IGNORECASE),
    re.compile(r"\.iloc\s*\[\s*.*\+\s*\d+", re.IGNORECASE),  # .iloc[x+1]
]

# Tokens DSL interdits (ambigus ou incompatibles contrat codegen)
_FORBIDDEN_DSL_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("crosses", re.compile(r"\bcrosses\b", re.IGNORECASE)),
    (".iloc[", re.compile(r"\.iloc\s*\[", re.IGNORECASE)),
    ("df[", re.compile(r"\bdf\s*\[", re.IGNORECASE)),
    ("shift(", re.compile(r"\bshift\s*\(", re.IGNORECASE)),
    ("future", re.compile(r"\bfuture\b", re.IGNORECASE)),
    ("repaint", re.compile(r"\brepaint\w*\b", re.IGNORECASE)),
]

# Valeurs placeholder interdites (ne doivent pas apparaître dans les champs logique)
_PLACEHOLDER_VALUES = {
    "", "-", "—", "n/a", "na", "none", "null",
    "brief description", "when to buy", "when to sell",
    "when to close", "explicit boolean rule",
}


def validate_variant(
    variant: Variant,
    profile: str = "ohlcv_only"
) -> Tuple[bool, List[str]]:
    """
    Valide un variant contre les règles de sanity.

    Args:
        variant: Variant à valider
        profile: Profil de dataset ("ohlcv_only" ou "full")

    Returns:
        Tuple (is_valid, list_of_rejection_reasons)
    """
    reasons: List[str] = []
    proposal = variant.proposal

    # --- 1. Validation schema ---
    _check_schema(proposal, reasons)
    if reasons:
        return False, reasons

    # --- 2. Validation registry ---
    _check_registry(proposal, reasons)

    # --- 3. Validation colonnes dataset ---
    if profile == "ohlcv_only":
        _check_dataset_columns(proposal, reasons)

    # --- 4. Stop-loss obligatoire ---
    _check_stop_loss(proposal, reasons)

    # --- 5. Anti-lookahead DSL ---
    _check_anti_lookahead(proposal, reasons)

    # --- 6. Tokens interdits DSL ---
    _check_forbidden_tokens(proposal, reasons)

    return len(reasons) == 0, reasons


def _check_schema(proposal: Dict[str, Any], reasons: List[str]) -> None:
    """Vérifie les champs obligatoires du proposal."""
    used = proposal.get("used_indicators")
    if not used or not isinstance(used, list) or len(used) == 0:
        reasons.append("used_indicators manquant ou vide")
        return

    entry_long = str(proposal.get("entry_long_logic", "")).strip().lower()
    if not entry_long or entry_long in _PLACEHOLDER_VALUES:
        reasons.append("entry_long_logic manquant ou placeholder")

    exit_logic = str(proposal.get("exit_logic", "")).strip().lower()
    if not exit_logic or exit_logic in _PLACEHOLDER_VALUES:
        reasons.append("exit_logic manquant ou placeholder")

    if not proposal.get("default_params"):
        reasons.append("default_params manquant ou vide")

    if not proposal.get("risk_management"):
        reasons.append("risk_management manquant")


def _check_registry(proposal: Dict[str, Any], reasons: List[str]) -> None:
    """Vérifie que tous les indicateurs existent dans le registry."""
    available = set(list_indicators())
    used = proposal.get("used_indicators", [])

    for ind in used:
        ind_lower = str(ind).strip().lower()
        if ind_lower not in available:
            reasons.append(f"Indicateur inconnu dans le registry: '{ind_lower}'")


def _check_dataset_columns(proposal: Dict[str, Any], reasons: List[str]) -> None:
    """Vérifie la compatibilité avec un dataset OHLCV-only."""
    used = proposal.get("used_indicators", [])

    for ind in used:
        ind_lower = str(ind).strip().lower()
        if ind_lower in _EXOGENE_INDICATORS:
            reasons.append(
                f"Indicateur '{ind_lower}' nécessite des colonnes exogènes "
                f"(incompatible profil ohlcv_only)"
            )
            continue

        info = get_indicator(ind_lower)
        if info is not None:
            missing = [
                col for col in info.required_columns
                if col not in _OHLCV_COLUMNS
            ]
            if missing:
                reasons.append(
                    f"Indicateur '{ind_lower}' nécessite colonnes hors OHLCV: {missing}"
                )


def _check_stop_loss(proposal: Dict[str, Any], reasons: List[str]) -> None:
    """Vérifie qu'un mécanisme de stop-loss est déclaré."""
    params = proposal.get("default_params", {})
    has_sl = any(
        k in params
        for k in ("stop_atr_mult", "stop_loss_pct", "sl_pct", "k_sl", "sl_level")
    )
    if not has_sl:
        risk_text = str(proposal.get("risk_management", "")).lower()
        if "stop" not in risk_text and "sl" not in risk_text:
            reasons.append("Aucun stop-loss déclaré (ni dans params ni dans risk_management)")


def _check_anti_lookahead(proposal: Dict[str, Any], reasons: List[str]) -> None:
    """Vérifie l'absence de patterns look-ahead dans les expressions DSL."""
    fields_to_check = [
        "entry_long_logic",
        "entry_short_logic",
        "exit_logic",
    ]

    for field_name in fields_to_check:
        text = str(proposal.get(field_name, ""))
        if not text:
            continue

        for pattern in _LOOKAHEAD_PATTERNS:
            match = pattern.search(text)
            if match:
                reasons.append(
                    f"Look-ahead détecté dans {field_name}: '{match.group()}'"
                )
                break


def _check_forbidden_tokens(proposal: Dict[str, Any], reasons: List[str]) -> None:
    """Rejette les tokens DSL interdits dans les champs de logique."""
    fields_to_check = [
        "entry_long_logic",
        "entry_short_logic",
        "exit_logic",
    ]

    for field_name in fields_to_check:
        text = str(proposal.get(field_name, "") or "")
        if not text:
            continue

        for token, pattern in _FORBIDDEN_DSL_PATTERNS:
            if pattern.search(text):
                reasons.append(f"Token interdit dans {field_name}: '{token}'")
