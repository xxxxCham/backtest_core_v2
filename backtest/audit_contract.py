"""Minimal audit contract for strict backtest parameter verification."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from strategies.base import StrategyBase

ENGINE_AUDIT_PARAMS = {
    "initial_capital",
    "fees_bps",
    "slippage_bps",
    "leverage",
    "k_sl",
    "sl_level",
    "tp_level",
    "execution_model",
}
ENGINE_CRITICAL_PARAMS = {"initial_capital", "fees_bps", "slippage_bps"}


class AuditContractError(ValueError):
    """Base error for audit contract violations."""


class UnknownAuditParamError(AuditContractError):
    """Raised when strict audit mode receives undeclared parameters."""


class SilentOverrideAuditError(AuditContractError):
    """Raised when an engine-critical value is silently overridden."""


class AuditParamCoercionError(AuditContractError):
    """Raised when a parameter cannot be coerced to its declared type."""


def _json_default(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
    return str(value)


def dump_json(path: str | Path, payload: Any) -> None:
    """Write a stable JSON payload."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=False, default=_json_default)


def stable_json_dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default)


def stable_hash_payload(payload: Any) -> str:
    return hashlib.sha256(stable_json_dumps(payload).encode("utf-8")).hexdigest()


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return round(value, 12)
    if isinstance(value, (np.datetime64,)):
        return pd.Timestamp(value).isoformat()
    if pd.isna(value) if value is not None and not isinstance(value, (list, dict, tuple, set)) else False:
        return None
    return value


def _series_payload(series: pd.Series) -> dict[str, Any]:
    items = []
    for index, value in series.items():
        items.append({"index": _normalize_scalar(index), "value": _normalize_scalar(value)})
    return {"name": series.name, "items": items}


def stable_hash_series(series: pd.Series) -> str:
    return stable_hash_payload(_series_payload(series))


def _dataframe_payload(df: pd.DataFrame) -> dict[str, Any]:
    columns = sorted(str(col) for col in df.columns)
    records: list[dict[str, Any]] = []
    if not df.empty:
        normalized = df.copy()
        normalized.columns = [str(col) for col in normalized.columns]
        normalized = normalized.loc[:, columns]
        for _, row in normalized.iterrows():
            records.append({col: _normalize_scalar(row[col]) for col in columns})
    return {"columns": columns, "records": records}


def stable_hash_dataframe(df: pd.DataFrame) -> str:
    return stable_hash_payload(_dataframe_payload(df))


def stable_hash_mapping(mapping: dict[str, Any]) -> str:
    return stable_hash_payload(mapping or {})


def _get_parameter_specs(strategy: StrategyBase) -> dict[str, Any]:
    try:
        specs = getattr(strategy, "parameter_specs", {}) or {}
    except Exception:
        specs = {}
    return dict(specs) if isinstance(specs, dict) else {}


def _declared_type_for_param(param_name: str, specs: dict[str, Any], defaults: dict[str, Any]) -> str | None:
    spec = specs.get(param_name)
    if spec is not None:
        param_type = getattr(spec, "param_type", None)
        if param_type:
            return str(param_type).lower()
        if isinstance(spec, dict):
            param_type = spec.get("type") or spec.get("param_type")
            if param_type:
                return str(param_type).lower()

    if param_name in defaults:
        value = defaults[param_name]
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int) and not isinstance(value, bool):
            return "int"
        if isinstance(value, float):
            return "float"
    return None


def _coerce_value(param_name: str, value: Any, declared_type: str | None) -> tuple[Any, dict[str, Any] | None]:
    if declared_type not in {"int", "float", "bool"}:
        return value, None

    original_type = type(value).__name__
    try:
        if declared_type == "bool":
            if isinstance(value, bool):
                return value, None
            if isinstance(value, str):
                text = value.strip().lower()
                if text in {"1", "true", "yes", "on"}:
                    coerced = True
                elif text in {"0", "false", "no", "off"}:
                    coerced = False
                else:
                    raise ValueError(value)
            else:
                coerced = bool(value)
        elif declared_type == "int":
            if isinstance(value, int) and not isinstance(value, bool):
                return value, None
            coerced = int(round(float(value)))
        else:
            if isinstance(value, float) and math.isfinite(value):
                return value, None
            if isinstance(value, int) and not isinstance(value, bool):
                coerced = float(value)
            else:
                coerced = float(value)
    except (TypeError, ValueError) as exc:
        raise AuditParamCoercionError(
            f"param '{param_name}' cannot be coerced to {declared_type}: {value!r}",
        ) from exc

    if coerced == value and type(coerced).__name__ == original_type:
        return value, None
    return coerced, {
        "param": param_name,
        "from_type": original_type,
        "to_type": type(coerced).__name__,
        "from_value": value,
        "to_value": coerced,
    }


def build_effective_config(
    *,
    strategy: StrategyBase,
    provided_params: dict[str, Any] | None,
    initial_capital: float,
    fees_bps: float,
    slippage_bps: float,
    strict_params: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build and validate the effective params used by the engine.

    Returns ``(effective_config, effective_params)``.
    """
    provided = dict(provided_params or {})
    strategy_defaults = dict(getattr(strategy, "default_params", {}) or {})
    specs = _get_parameter_specs(strategy)
    engine_defaults = {
        "initial_capital": initial_capital,
        "fees_bps": fees_bps,
        "slippage_bps": slippage_bps,
    }

    accepted_params = sorted(set(strategy_defaults) | set(specs) | ENGINE_AUDIT_PARAMS)
    unused_params = sorted(key for key in provided if key not in accepted_params)

    overridden_params: list[dict[str, Any]] = []
    for key, engine_value in engine_defaults.items():
        if key in strategy_defaults and strategy_defaults[key] != engine_value:
            overridden_params.append(
                {
                    "param": key,
                    "from_source": "engine_defaults",
                    "to_source": "strategy_defaults",
                    "from_value": engine_value,
                    "to_value": strategy_defaults[key],
                },
            )

    base_params = {**engine_defaults, **strategy_defaults}
    for key, value in provided.items():
        if key in base_params and base_params[key] != value:
            overridden_params.append(
                {
                    "param": key,
                    "from_source": "defaults",
                    "to_source": "provided_params",
                    "from_value": base_params[key],
                    "to_value": value,
                },
            )

    effective_params = {**base_params, **provided}
    coerced_params: list[dict[str, Any]] = []
    reference_defaults = {**engine_defaults, **strategy_defaults}
    for key, value in list(effective_params.items()):
        declared_type = _declared_type_for_param(key, specs, reference_defaults)
        coerced, coercion = _coerce_value(key, value, declared_type)
        effective_params[key] = coerced
        if coercion is not None:
            coerced_params.append(coercion)

    silent_critical_overrides = [
        item
        for item in overridden_params
        if item["param"] in ENGINE_CRITICAL_PARAMS
        and item["to_source"] == "strategy_defaults"
        and item["param"] not in provided
    ]

    effective_config = {
        "provided_params": provided,
        "strategy_defaults": strategy_defaults,
        "engine_defaults": engine_defaults,
        "effective_params": effective_params,
        "unused_params": unused_params,
        "overridden_params": overridden_params,
        "coerced_params": coerced_params,
        "accepted_params": accepted_params,
        "strict_params": bool(strict_params),
    }

    if strict_params and unused_params:
        raise UnknownAuditParamError(f"unused params: {unused_params}")
    if strict_params and silent_critical_overrides:
        raise SilentOverrideAuditError(f"silent critical overrides: {silent_critical_overrides}")

    return effective_config, effective_params


def recompute_basic_metrics(
    *,
    equity: pd.Series,
    trades: pd.DataFrame,
    initial_capital: float,
) -> dict[str, Any]:
    if equity is None or equity.empty:
        total_pnl = 0.0
        max_drawdown_pct = 0.0
    else:
        final_equity = float(equity.iloc[-1])
        total_pnl = final_equity - float(initial_capital)
        values = np.asarray(equity.values, dtype=np.float64)
        running_max = np.maximum.accumulate(values)
        with np.errstate(divide="ignore", invalid="ignore"):
            drawdown = np.where(running_max > 0.0, (values - running_max) / running_max, 0.0)
        max_drawdown_pct = float(np.min(drawdown) * 100.0) if drawdown.size else 0.0
        max_drawdown_pct = max(-100.0, max_drawdown_pct)

    total_return_pct = (total_pnl / float(initial_capital) * 100.0) if initial_capital else 0.0

    if trades is None or trades.empty:
        total_trades = 0
        win_rate_pct = 0.0
        profit_factor = 1.0
    else:
        pnl = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0)
        total_trades = int(len(pnl))
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        win_rate_pct = float(len(wins) / total_trades * 100.0) if total_trades else 0.0
        gross_profit = float(wins.sum())
        gross_loss = abs(float(losses.sum()))
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        else:
            profit_factor = float("inf") if gross_profit > 0 else 1.0

    return {
        "total_pnl": float(total_pnl),
        "total_return_pct": float(total_return_pct),
        "total_trades": total_trades,
        "win_rate_pct": float(win_rate_pct),
        "profit_factor": float(profit_factor),
        "max_drawdown_pct": float(max_drawdown_pct),
    }


def reconcile_metrics(
    engine_metrics: dict[str, Any],
    recomputed_metrics: dict[str, Any],
    *,
    float_tolerance: float = 1e-6,
    count_tolerance: float = 1e-8,
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    for key in ("total_pnl", "total_return_pct", "win_rate_pct", "profit_factor", "max_drawdown_pct"):
        engine_value = float(engine_metrics.get(key, 0.0))
        recomputed_value = float(recomputed_metrics.get(key, 0.0))
        if math.isinf(engine_value) or math.isinf(recomputed_value):
            passed = math.isinf(engine_value) and math.isinf(recomputed_value) and engine_value == recomputed_value
            delta = 0.0 if passed else float("inf")
        else:
            delta = abs(engine_value - recomputed_value)
            passed = delta <= float_tolerance
        checks[key] = {
            "engine": engine_value,
            "recomputed": recomputed_value,
            "delta": delta,
            "passed": passed,
        }

    engine_count = int(float(engine_metrics.get("total_trades", 0) or 0))
    recomputed_count = int(float(recomputed_metrics.get("total_trades", 0) or 0))
    count_delta = abs(engine_count - recomputed_count)
    checks["total_trades"] = {
        "engine": engine_count,
        "recomputed": recomputed_count,
        "delta": count_delta,
        "passed": count_delta <= count_tolerance,
    }

    failures = [key for key, payload in checks.items() if not payload["passed"]]
    return {
        "passed": not failures,
        "failures": failures,
        "checks": checks,
    }


def audit_hashes(
    *,
    signals: pd.Series,
    trades: pd.DataFrame,
    equity: pd.Series,
    metrics: dict[str, Any],
) -> dict[str, str]:
    return {
        "signals_hash": stable_hash_series(signals),
        "trades_hash": stable_hash_dataframe(trades),
        "equity_hash": stable_hash_series(equity),
        "metrics_hash": stable_hash_mapping(metrics),
    }

