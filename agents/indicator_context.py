"""
Module-ID: agents.indicator_context

Purpose: Construire un contexte indicateurs (stratégie vs lecture seule) pour LLM.

Role in pipeline: orchestration support

Key components: build_indicator_context, DEFAULT_READ_ONLY_INDICATORS

Inputs: DataFrame OHLCV, stratégie, paramètres courants

Outputs: Dict avec sections texte + warnings

Dependencies: numpy, pandas, indicators.registry, strategies.*
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

from indicators.registry import calculate_indicator
from strategies.base import get_strategy
from strategies.indicators_mapping import (
    get_internal_indicators,
    get_required_indicators,
)

# Indicateurs contextuels (lecture seule). Modifiable côté code.
DEFAULT_READ_ONLY_INDICATORS: List[Tuple[str, Dict[str, Any]]] = [
    ("adx", {"period": 14}),
    ("atr", {"period": 14}),
    ("rsi", {"period": 14}),
    ("macd", {"fast_period": 12, "slow_period": 26, "signal_period": 9}),
    ("stochastic", {"k_period": 14, "d_period": 3, "smooth_k": 3}),
    ("stoch_rsi", {"rsi_period": 14, "stoch_period": 14, "k_smooth": 3, "d_smooth": 3, "oversold": 20, "overbought": 80}),
    ("cci", {"period": 20}),
    ("williams_r", {"period": 14}),
    ("momentum", {"period": 14}),
    ("roc", {"period": 12}),
    ("aroon", {"period": 14}),
    ("supertrend", {"atr_period": 10, "multiplier": 3.0}),
    ("vortex", {"period": 14, "threshold": 0.0}),
    ("psar", {"af_start": 0.02, "af_increment": 0.02, "af_max": 0.2}),
    ("ichimoku", {"tenkan_period": 9, "kijun_period": 26, "senkou_b_period": 52, "displacement": 26}),
    ("bollinger", {"period": 20, "std_dev": 2.0}),
    ("keltner", {"ema_period": 20, "atr_period": 10, "atr_multiplier": 2.0}),
    ("donchian", {"period": 20}),
    ("standard_deviation", {"period": 20}),
    ("vwap", {"period": 20}),
    ("obv", {}),
    ("mfi", {"period": 14}),
    ("volume_oscillator", {"short_period": 14, "long_period": 28, "method": "ema"}),
    ("amplitude_hunter", {"period": 20}),
    ("pivot_points", {"method": "classic"}),
    ("fibonacci_levels", {"period": 50}),
]

TUPLE_LABELS: Dict[str, Tuple[str, ...]] = {
    "bollinger": ("upper", "middle", "lower"),
    "stochastic": ("k", "d"),
}

DICT_KEY_ALIASES: Dict[str, str] = {
    "histogram": "hist",
}


def build_indicator_context(
    df: pd.DataFrame,
    strategy_name: str,
    params: Dict[str, Any],
    read_only_indicators: Optional[Iterable[Tuple[str, Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """
    Construit un contexte indicateurs séparé en:
    - strategy_indicators: indicateurs liés à la stratégie (modifiables via params)
    - read_only_indicators: indicateurs contexte (lecture seule)
    """
    warnings: List[str] = []

    # Strategy indicators
    strategy_lines: List[str] = []
    try:
        strategy_cls = get_strategy(strategy_name)
        strategy = strategy_cls()
    except Exception as exc:
        return {
            "strategy": "",
            "read_only": "",
            "warnings": [f"Impossible de charger la stratégie '{strategy_name}': {exc}"],
        }

    try:
        required = get_required_indicators(strategy_name)
        internal = get_internal_indicators(strategy_name)
    except Exception:
        required = list(getattr(strategy, "required_indicators", []) or [])
        internal = []

    strategy_indicators = list(dict.fromkeys(required + internal))

    for indicator_name in strategy_indicators:
        strategy_lines.extend(
            _summarize_indicator(
                df=df,
                indicator_name=indicator_name,
                params=params,
                strategy=strategy,
                warnings=warnings,
                is_strategy=True,
            )
        )

    # Read-only indicators
    read_only_lines: List[str] = []
    ro_specs = list(read_only_indicators) if read_only_indicators else list(DEFAULT_READ_ONLY_INDICATORS)

    for indicator_name, indicator_params in ro_specs:
        # Eviter doublons si deja present en strategie
        if indicator_name in strategy_indicators:
            continue
        read_only_lines.extend(
            _summarize_indicator(
                df=df,
                indicator_name=indicator_name,
                params=indicator_params,
                strategy=None,
                warnings=warnings,
                is_strategy=False,
            )
        )

    return {
        "strategy": "\n".join(strategy_lines).strip(),
        "read_only": "\n".join(read_only_lines).strip(),
        "warnings": warnings,
    }


def _summarize_indicator(
    df: pd.DataFrame,
    indicator_name: str,
    params: Dict[str, Any],
    strategy: Any,
    warnings: List[str],
    is_strategy: bool,
) -> List[str]:
    lines: List[str] = []

    # Parametrage base
    indicator_params: Dict[str, Any] = {}
    if is_strategy and strategy is not None:
        try:
            indicator_params = strategy.get_indicator_params(indicator_name, params)
        except Exception:
            indicator_params = {}
    else:
        indicator_params = dict(params or {})

    # Heuristiques EMA/SMA internes (fast/slow)
    if indicator_name in ("ema", "sma") and not indicator_params:
        fast = _first_param(params, ["fast_period", "fast"])
        slow = _first_param(params, ["slow_period", "slow"])
        if fast is not None:
            lines.extend(
                _summarize_single_indicator(
                    df, indicator_name, {"period": int(fast)}, f"{indicator_name}_fast", warnings
                )
            )
        if slow is not None:
            lines.extend(
                _summarize_single_indicator(
                    df, indicator_name, {"period": int(slow)}, f"{indicator_name}_slow", warnings
                )
            )
        if lines:
            return lines

    return _summarize_single_indicator(
        df, indicator_name, indicator_params, indicator_name, warnings
    )


def _summarize_single_indicator(
    df: pd.DataFrame,
    indicator_name: str,
    params: Dict[str, Any],
    label_name: str,
    warnings: List[str],
) -> List[str]:
    try:
        result = calculate_indicator(indicator_name, df, params)
    except Exception as exc:
        warnings.append(f"{indicator_name}: {exc}")
        return []

    label = _format_indicator_label(label_name, params)

    if result is None:
        return [f"- {label}: N/A"]

    if isinstance(result, dict):
        parts = []
        for key, values in result.items():
            last = _last_valid_value(values)
            if last is not None:
                key_label = DICT_KEY_ALIASES.get(key, key)
                parts.append(f"{key_label}={_fmt(last)}")
        if parts:
            return [f"- {label}: " + ", ".join(parts)]
        return [f"- {label}: N/A"]

    if isinstance(result, tuple):
        parts = []
        key_labels = TUPLE_LABELS.get(indicator_name, tuple(f"v{i}" for i in range(len(result))))
        for key, values in zip(key_labels, result):
            last = _last_valid_value(values)
            if last is not None:
                parts.append(f"{key}={_fmt(last)}")
        if parts:
            return [f"- {label}: " + ", ".join(parts)]
        return [f"- {label}: N/A"]

    stats = _series_stats(result)
    if not stats:
        return [f"- {label}: N/A"]

    return [
        "- "
        + f"{label}: last={_fmt(stats['last'])}, "
        + f"mean={_fmt(stats['mean'])}, "
        + f"min={_fmt(stats['min'])}, "
        + f"max={_fmt(stats['max'])}"
    ]


def _series_stats(values: Any) -> Optional[Dict[str, float]]:
    arr = _to_array(values)
    if arr is None or arr.size == 0:
        return None

    mask = np.isfinite(arr)
    if not mask.any():
        return None

    arr_valid = arr[mask]
    last = arr_valid[-1]

    return {
        "last": float(last),
        "mean": float(np.mean(arr_valid)),
        "min": float(np.min(arr_valid)),
        "max": float(np.max(arr_valid)),
    }


def _last_valid_value(values: Any) -> Optional[float]:
    arr = _to_array(values)
    if arr is None or arr.size == 0:
        return None
    mask = np.isfinite(arr)
    if not mask.any():
        return None
    return float(arr[mask][-1])


def _to_array(values: Any) -> Optional[np.ndarray]:
    if values is None:
        return None
    if isinstance(values, pd.Series):
        arr = values.values
    else:
        arr = np.asarray(values)
    if arr.ndim != 1:
        arr = arr.reshape(-1)
    return arr.astype("float64", copy=False)


def _format_indicator_label(name: str, params: Dict[str, Any]) -> str:
    if not params:
        return name
    parts = []
    for key in sorted(params.keys()):
        val = params[key]
        parts.append(f"{key}={_fmt(val)}")
    return f"{name}(" + ", ".join(parts) + ")"


def _fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    try:
        val = float(value)
    except Exception:
        return str(value)
    return f"{val:.4f}"


def _first_param(params: Dict[str, Any], keys: Iterable[str]) -> Optional[float]:
    for key in keys:
        if key in params:
            try:
                return float(params[key])
            except Exception:
                return None
    return None
