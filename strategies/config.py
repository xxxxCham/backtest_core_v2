"""
Module-ID: strategies.config

Purpose: Configuration et logique métier pour les stratégies de trading.

Role in pipeline: domain / configuration

Key components:
- PARAM_CONSTRAINTS
- compute_search_space_stats
- validate_param / validate_param_dependencies
- build_param_range / compute_param_combinations
- build_strategy_options / get_strategy_description
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from strategies.base import StrategyBase, get_strategy, list_strategies
    STRATEGIES_AVAILABLE = True
except ImportError:
    StrategyBase = None
    get_strategy = None
    list_strategies = None
    STRATEGIES_AVAILABLE = False


# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================

PARAM_CONSTRAINTS: Dict[str, Dict[str, Any]] = {
    "fast_period": {"min": 2, "max": 100, "default": 10},
    "slow_period": {"min": 5, "max": 200, "default": 21},
    "bb_period": {"min": 5, "max": 100, "default": 20},
    "bb_std": {"min": 0.5, "max": 4.0, "default": 2.0, "step": 0.1},
    "atr_period": {"min": 5, "max": 50, "default": 14},
    "atr_mult": {"min": 0.5, "max": 5.0, "default": 1.5, "step": 0.1},
    "rsi_period": {"min": 5, "max": 50, "default": 14},
    "rsi_oversold": {"min": 10, "max": 40, "default": 30},
    "rsi_overbought": {"min": 60, "max": 90, "default": 70},
    "entry_level": {"min": -1.0, "max": 2.0, "default": 0.0, "step": 0.05},
    "sl_level": {"min": -2.0, "max": 1.0, "default": -0.5, "step": 0.05},
    "tp_level": {"min": 0.0, "max": 3.0, "default": 1.0, "step": 0.05},
    "k_sl": {"min": 0.5, "max": 5.0, "default": 1.5, "step": 0.1},
    "leverage": {"min": 1, "max": 10, "default": 1},
}


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class StrategyParamInfo:
    """Informations sur un paramètre de stratégie."""
    name: str
    param_type: str
    default: Any
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    step: Optional[float] = None
    optimize: bool = True
    description: str = ""


@dataclass
class SearchSpaceStats:
    """Statistiques sur l'espace de recherche."""
    total_combinations: int = 1
    per_param_counts: Dict[str, int] = field(default_factory=dict)
    is_continuous: bool = False
    has_overflow: bool = False
    overflow_param: Optional[str] = None


@dataclass
class ParamValidationResult:
    """Résultat de validation d'un paramètre."""
    is_valid: bool = True
    error_message: Optional[str] = None
    warning_message: Optional[str] = None


# ============================================================================
# STRATEGY DISCOVERY
# ============================================================================

def get_available_strategies() -> List[str]:
    if not STRATEGIES_AVAILABLE or list_strategies is None:
        return ["ema_cross", "bollinger_atr"]
    try:
        return list_strategies()
    except Exception:
        return ["ema_cross", "bollinger_atr"]


def get_strategy_instance(strategy_key: str) -> Optional[Any]:
    if not STRATEGIES_AVAILABLE or get_strategy is None:
        return None
    try:
        strategy_class = get_strategy(strategy_key)
        if strategy_class:
            return strategy_class()
    except Exception:
        pass
    return None


def get_strategy_description(strategy_key: str) -> str:
    inst = get_strategy_instance(strategy_key)
    if inst is None:
        return f"Stratégie: {strategy_key}"
    doc = getattr(inst, "__doc__", "") or ""
    first_line = doc.strip().split("\n")[0] if doc else ""
    return first_line if first_line else f"Stratégie: {strategy_key}"


# ============================================================================
# PARAMETER CONFIGURATION
# ============================================================================

def get_param_constraints(param_name: str) -> Dict[str, Any]:
    return PARAM_CONSTRAINTS.get(param_name, {"min": 0, "max": 100, "default": 0})


def build_param_range(
    param_name: str,
    min_val: float,
    max_val: float,
    step: Optional[float] = None,
    param_type: str = "float",
) -> Dict[str, Any]:
    return {"min": min_val, "max": max_val, "step": step, "type": param_type}


def compute_param_combinations(param_range: Dict[str, Any]) -> int:
    min_val = param_range.get("min", 0)
    max_val = param_range.get("max", 0)
    step = param_range.get("step")

    if step is None or step <= 0:
        return -1
    if max_val <= min_val:
        return 1

    # Eviter erreurs de flottants
    try:
        count = int(round((max_val - min_val) / step)) + 1
        return max(count, 1)
    except Exception:
        return -1


def compute_search_space_stats(
    param_ranges: Dict[str, Dict[str, Any]],
    max_combinations: int = 100_000_000,
) -> SearchSpaceStats:
    stats = SearchSpaceStats()

    for param_name, param_range in param_ranges.items():
        count = compute_param_combinations(param_range)
        if count < 0:
            stats.is_continuous = True
            stats.per_param_counts[param_name] = -1
            continue

        stats.per_param_counts[param_name] = count

        if stats.total_combinations > max_combinations // max(count, 1):
            stats.has_overflow = True
            stats.overflow_param = param_name

        stats.total_combinations *= count

    if stats.total_combinations > max_combinations:
        stats.has_overflow = True
        stats.total_combinations = max_combinations

    return stats


# ============================================================================
# PARAMETER VALIDATION
# ============================================================================

def validate_param(
    param_name: str,
    value: Any,
    constraints: Optional[Dict[str, Any]] = None,
) -> ParamValidationResult:
    result = ParamValidationResult()
    if constraints is None:
        constraints = get_param_constraints(param_name)

    min_val = constraints.get("min")
    max_val = constraints.get("max")

    if min_val is not None and value < min_val:
        result.is_valid = False
        result.error_message = f"{param_name}: valeur {value} < minimum {min_val}"
        return result

    if max_val is not None and value > max_val:
        result.is_valid = False
        result.error_message = f"{param_name}: valeur {value} > maximum {max_val}"
        return result

    return result


def validate_param_dependencies(params: Dict[str, Any], strategy_key: str) -> List[str]:
    errors: List[str] = []

    if "fast_period" in params and "slow_period" in params:
        if params["slow_period"] <= params["fast_period"]:
            errors.append(
                f"slow_period ({params['slow_period']}) doit être > "
                f"fast_period ({params['fast_period']})"
            )

    if "rsi_oversold" in params and "rsi_overbought" in params:
        if params["rsi_overbought"] <= params["rsi_oversold"]:
            errors.append(
                f"rsi_overbought ({params['rsi_overbought']}) doit être > "
                f"rsi_oversold ({params['rsi_oversold']})"
            )

    if "entry_level" in params and "tp_level" in params:
        if "long" in strategy_key.lower() and params["tp_level"] <= params["entry_level"]:
            errors.append(
                f"tp_level ({params['tp_level']}) doit être > "
                f"entry_level ({params['entry_level']}) pour stratégie long"
            )

    return errors


# ============================================================================
# STRATEGY OPTIONS FORMATTING
# ============================================================================

def build_strategy_options(strategy_keys: List[str]) -> Dict[str, str]:
    options: Dict[str, str] = {}
    for key in strategy_keys:
        if "long" in key.lower():
            label = f"📈 {key}"
        elif "short" in key.lower():
            label = f"📉 {key}"
        else:
            label = f"📊 {key}"
        options[label] = key
    return options


__all__ = [
    "PARAM_CONSTRAINTS",
    "SearchSpaceStats",
    "StrategyParamInfo",
    "ParamValidationResult",
    "compute_search_space_stats",
    "compute_param_combinations",
    "validate_param",
    "validate_param_dependencies",
    "build_param_range",
    "get_param_constraints",
    "build_strategy_options",
    "get_strategy_description",
]
