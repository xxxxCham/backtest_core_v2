"""
Backtest Core - Strategies Package.

Imports are best-effort to avoid hard failures when optional strategy files
are missing in a local workspace.
"""

from __future__ import annotations

import logging
from importlib import import_module
from typing import Dict

from .base import StrategyBase, StrategyResult, get_strategy, list_strategies
from .indicators_mapping import (
    STRATEGY_INDICATORS_MAP,
    get_all_indicators,
    get_required_indicators,
    get_strategy_info,
)

logger = logging.getLogger(__name__)

__all__ = [
    "StrategyBase",
    "StrategyResult",
    "get_strategy",
    "list_strategies",
    "get_required_indicators",
    "get_all_indicators",
    "get_strategy_info",
    "STRATEGY_INDICATORS_MAP",
]

_OPTIONAL_STRATEGY_IMPORT_ERRORS: Dict[str, str] = {}


def _optional_strategy(module_name: str, class_name: str) -> None:
    full_module_name = f"{__name__}.{module_name}"

    try:
        module = import_module(f".{module_name}", __name__)
    except ModuleNotFoundError as exc:
        # Silence only true "module not found" for optional modules.
        if exc.name == full_module_name:
            _OPTIONAL_STRATEGY_IMPORT_ERRORS[module_name] = (
                f"module_missing:{full_module_name}"
            )
            logger.debug("Optional strategy module not found: %s", full_module_name)
            return
        _OPTIONAL_STRATEGY_IMPORT_ERRORS[module_name] = (
            f"dependency_missing:{exc.name}"
        )
        logger.warning(
            "Optional strategy '%s' skipped due to missing dependency '%s'",
            module_name,
            exc.name,
        )
        return
    except Exception as exc:
        _OPTIONAL_STRATEGY_IMPORT_ERRORS[module_name] = (
            f"import_error:{type(exc).__name__}:{exc}"
        )
        logger.warning(
            "Optional strategy '%s' import failed (%s: %s)",
            module_name,
            type(exc).__name__,
            exc,
        )
        return

    try:
        cls = getattr(module, class_name)
    except AttributeError:
        _OPTIONAL_STRATEGY_IMPORT_ERRORS[module_name] = (
            f"class_missing:{class_name}"
        )
        logger.warning(
            "Optional strategy module '%s' loaded but class '%s' is missing",
            full_module_name,
            class_name,
        )
        return

    globals()[class_name] = cls
    __all__.append(class_name)


def get_optional_strategy_import_errors() -> Dict[str, str]:
    """Retourne l'état des imports optionnels non chargés."""
    return dict(_OPTIONAL_STRATEGY_IMPORT_ERRORS)


__all__.append("get_optional_strategy_import_errors")


_optional_strategy("bollinger_atr", "BollingerATRStrategy")
_optional_strategy("bollinger_best_longe_3i", "BollingerBestLonge3iStrategy")
_optional_strategy("bollinger_best_short_3i", "BollingerBestShort3iStrategy")
_optional_strategy("ema_cross", "EMACrossStrategy")
_optional_strategy("ema_rsi_regime", "EMARSIRegimeStrategy")
_optional_strategy("macd_cross", "MACDCrossStrategy")
_optional_strategy("rsi_reversal", "RSIReversalStrategy")
_optional_strategy("scalp_bb_vwap_rsi", "ScalpBollingerVwapRsiStrategy")
_optional_strategy("scalp_donchian_adx_breakout", "ScalpDonchianAdxBreakoutStrategy")
_optional_strategy("scalp_ema_rsi_pullback", "ScalpEmaRsiPullbackStrategy")
_optional_strategy("scalp_ema_bb_rsi_labs", "ScalpEmaBbRsiLabsStrategy")
_optional_strategy("scalping_bollinger_vwap_atr", "ScalpingBollingerVwapAtrStrategy")
_optional_strategy("breakout_donchian_adx", "BreakoutDonchianAdxStrategy")
_optional_strategy("mean_reversion_bollinger_rsi", "MeanReversionBollingerRsiStrategy")
_optional_strategy("momentum_macd", "MomentumMacdStrategy")
_optional_strategy("trend_supertrend", "TrendSupertrendStrategy")
_optional_strategy("vol_amplitude_breakout", "VolAmplitudeBreakoutStrategy")
