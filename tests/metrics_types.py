from __future__ import annotations

from typing import Any, Dict, Literal, Mapping, TypedDict, Union, cast, overload

Unit = Literal["pct", "frac"]
MetricValue = Union[int, float]

# TypedDict keeps payloads dict-like for boundary transport.


class PerformanceMetricsPct(TypedDict, total=False):
    total_pnl: float
    total_return_pct: float
    annualized_return: float
    cagr: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown_pct: float
    volatility_annual: float
    total_trades: int
    win_rate_pct: float
    profit_factor: float
    expectancy: float


class AgentBacktestMetricsFrac(TypedDict, total=False):
    sharpe_ratio: float
    sortino_ratio: float
    total_return: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_trades: int
    calmar_ratio: float
    sqn: float
    recovery_factor: float


class UIMetricsPct(PerformanceMetricsPct, total=False):
    sqn: float
    recovery_factor: float


_ALIAS_TO_PCT = {
    "total_return": "total_return_pct",
    "max_drawdown": "max_drawdown_pct",
    "win_rate": "win_rate_pct",
}
_ALIAS_TO_FRAC = {
    "total_return_pct": "total_return",
    "max_drawdown_pct": "max_drawdown",
    "win_rate_pct": "win_rate",
}


def _coerce_numeric(value: Any, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{key} must be a number, got {type(value).__name__}")
    return float(value)


def _validate_range(payload: Mapping[str, Any], key: str, lo: float, hi: float) -> None:
    if key not in payload:
        return
    value = _coerce_numeric(payload[key], key)
    if value < lo or value > hi:
        raise ValueError(f"{key} out of range [{lo}, {hi}]: {value}")


def _validate_invariants(payload: Mapping[str, Any], unit: Unit) -> None:
    if unit == "pct":
        _validate_range(payload, "win_rate_pct", 0.0, 100.0)
        _validate_range(payload, "max_drawdown_pct", -100.0, 0.0)
    else:
        _validate_range(payload, "win_rate", 0.0, 1.0)
        _validate_range(payload, "max_drawdown", -1.0, 0.0)


def _apply_aliases(payload: Mapping[str, Any], unit: Unit) -> Dict[str, Any]:
    normalized: Dict[str, Any] = dict(payload)
    mapping = _ALIAS_TO_PCT if unit == "pct" else _ALIAS_TO_FRAC
    for alias, canonical in mapping.items():
        if alias not in normalized:
            continue
        if canonical in normalized and normalized[canonical] != normalized[alias]:
            raise ValueError(f"Conflicting values for {canonical} and {alias}")
        if canonical not in normalized:
            normalized[canonical] = normalized[alias]
        if alias != canonical:
            normalized.pop(alias, None)
    return normalized


@overload
def normalize_metrics(
    payload: Mapping[str, Any], unit: Literal["pct"]
) -> PerformanceMetricsPct:
    ...


@overload
def normalize_metrics(
    payload: Mapping[str, Any], unit: Literal["frac"]
) -> AgentBacktestMetricsFrac:
    ...


def normalize_metrics(payload: Mapping[str, Any], unit: Unit) -> Dict[str, Any]:
    normalized = _apply_aliases(payload, unit)
    _validate_invariants(normalized, unit)
    return normalized


def pct_to_frac(pct_payload: Mapping[str, Any]) -> AgentBacktestMetricsFrac:
    normalized = normalize_metrics(pct_payload, "pct")
    converted: Dict[str, Any] = dict(normalized)
    if "total_return_pct" in normalized:
        converted["total_return"] = normalized["total_return_pct"] / 100.0
        converted.pop("total_return_pct", None)
    if "max_drawdown_pct" in normalized:
        converted["max_drawdown"] = normalized["max_drawdown_pct"] / 100.0
        converted.pop("max_drawdown_pct", None)
    if "win_rate_pct" in normalized:
        converted["win_rate"] = normalized["win_rate_pct"] / 100.0
        converted.pop("win_rate_pct", None)
    _validate_invariants(converted, "frac")
    return cast(AgentBacktestMetricsFrac, converted)


def frac_to_pct(frac_payload: Mapping[str, Any]) -> PerformanceMetricsPct:
    normalized = normalize_metrics(frac_payload, "frac")
    converted: Dict[str, Any] = dict(normalized)
    if "total_return" in normalized:
        converted["total_return_pct"] = normalized["total_return"] * 100.0
        converted.pop("total_return", None)
    if "max_drawdown" in normalized:
        converted["max_drawdown_pct"] = normalized["max_drawdown"] * 100.0
        converted.pop("max_drawdown", None)
    if "win_rate" in normalized:
        converted["win_rate_pct"] = normalized["win_rate"] * 100.0
        converted.pop("win_rate", None)
    _validate_invariants(converted, "pct")
    return cast(PerformanceMetricsPct, converted)


__all__ = [
    "AgentBacktestMetricsFrac",
    "PerformanceMetricsPct",
    "UIMetricsPct",
    "frac_to_pct",
    "normalize_metrics",
    "pct_to_frac",
]
