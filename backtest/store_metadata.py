from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd


EXPECTED_RUN_ARTIFACTS = ("equity", "trades", "returns")


def load_metadata_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def is_native_result_metadata(meta: dict[str, Any]) -> bool:
    return "timestamp" in meta and isinstance(meta.get("metrics"), dict)


def is_v3_result_metadata(meta: dict[str, Any]) -> bool:
    return "created_at" in meta and int(meta.get("schema_version", 0) or 0) >= 3


def normalize_status_for_legacy(status: Any) -> str:
    text = str(status or "ok").strip().lower()
    if text == "success":
        return "ok"
    return str(status or "ok")


def normalize_status_for_store(status: Any) -> str:
    text = str(status or "ok").strip().lower()
    if text in {"", "ok", "success"}:
        return "success"
    return str(status or "success")


def coerce_iso_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, pd.Timestamp):
        dt = value.to_pydatetime()
    elif value:
        text = str(value).strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            dt = datetime.now(timezone.utc)
    else:
        dt = datetime.now(timezone.utc)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except Exception:
        return None
    if pd.isna(number):
        return None
    return number


def safe_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return None


def _pick(meta: dict[str, Any], index_row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in meta and meta.get(key) not in (None, ""):
            return meta.get(key)
        if key in index_row and index_row.get(key) not in (None, ""):
            return index_row.get(key)
    return None


def _coerce_metrics(metrics_payload: Any) -> dict[str, Any]:
    if isinstance(metrics_payload, dict):
        return dict(metrics_payload)
    if hasattr(metrics_payload, "to_dict"):
        try:
            data = metrics_payload.to_dict()
            if isinstance(data, dict):
                return dict(data)
        except Exception:
            return {}
    try:
        return dict(metrics_payload)
    except Exception:
        return {}


def find_run_artifacts(run_dir: Path) -> dict[str, Path]:
    artifacts: dict[str, Path] = {}
    for stem in EXPECTED_RUN_ARTIFACTS:
        for suffix in (".parquet", ".csv"):
            candidate = run_dir / f"{stem}{suffix}"
            if candidate.exists():
                artifacts[stem] = candidate
                break
    return artifacts


def list_missing_run_artifacts(run_dir: Path) -> list[str]:
    artifacts = find_run_artifacts(run_dir)
    return [stem for stem in EXPECTED_RUN_ARTIFACTS if stem not in artifacts]


def derive_migration_status(incoming_status: Any, *, missing_artifacts: list[str], metadata_valid: bool = True) -> str:
    if not metadata_valid:
        return "invalid"
    if "equity" in missing_artifacts:
        return "invalid"
    if missing_artifacts:
        return "partial"
    normalized = normalize_status_for_store(incoming_status)
    if normalized == "invalid":
        return "invalid"
    return "success"


def build_store_row_from_metadata(
    meta: dict[str, Any],
    *,
    run_id_hint: str | None = None,
    artifact_path: str | None = None,
    index_row: dict[str, Any] | None = None,
    metrics_payload: dict[str, Any] | None = None,
    config_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    index_row = dict(index_row or {})
    config_payload = dict(config_payload or {})
    metrics_payload = _coerce_metrics(metrics_payload)

    if is_native_result_metadata(meta):
        metrics = _coerce_metrics(meta.get("metrics"))
        params = dict(meta.get("params", {}) or {})
        extra = dict(meta.get("extra_metadata", {}) or {})
        source_schema = "native"
        created_at = _pick(meta, index_row, "timestamp", "created_at")
    elif is_v3_result_metadata(meta):
        metrics = {
            "total_return_pct": meta.get("total_return_pct"),
            "sharpe_ratio": meta.get("sharpe_ratio"),
            "max_drawdown_pct": meta.get("max_drawdown_pct"),
            "total_trades": meta.get("n_trades"),
        }
        params = dict(meta.get("params", {}) or {})
        extra = dict(meta.get("extra", {}) or {})
        source_schema = "v3"
        created_at = _pick(meta, index_row, "created_at", "timestamp")
    else:
        metrics = metrics_payload or {
            "total_return_pct": _pick(meta, index_row, "total_return_pct"),
            "sharpe_ratio": _pick(meta, index_row, "sharpe_ratio"),
            "max_drawdown_pct": _pick(meta, index_row, "max_drawdown_pct"),
            "total_trades": _pick(meta, index_row, "n_trades", "total_trades"),
        }
        params = dict(meta.get("params", {}) or config_payload.get("params", {}) or {})
        extra = dict(meta.get("extra", {}) or meta.get("extra_metadata", {}) or {})
        source_schema = "legacy_manifest"
        created_at = _pick(meta, index_row, "created_at", "timestamp")

    if not params and config_payload:
        params = dict(config_payload.get("params", {}) or config_payload)

    merged_extra = dict(extra)
    if config_payload:
        for key, value in config_payload.items():
            if key == "params":
                continue
            merged_extra.setdefault(key, value)

    run_id = str(_pick(meta, index_row, "run_id") or run_id_hint or "")
    return {
        "run_id": run_id,
        "created_at": coerce_iso_timestamp(created_at),
        "mode": str(_pick(meta, index_row, "mode") or "backtest"),
        "status": normalize_status_for_store(_pick(meta, index_row, "status") or "success"),
        "strategy": str(_pick(meta, index_row, "strategy") or "unknown"),
        "symbol": str(_pick(meta, index_row, "symbol") or "unknown"),
        "timeframe": str(_pick(meta, index_row, "timeframe") or "unknown"),
        "n_trades": safe_int(_pick({"n_trades": meta.get("n_trades", metrics.get("total_trades"))}, index_row, "n_trades")) or 0,
        "total_return_pct": safe_float(_pick({"total_return_pct": metrics.get("total_return_pct")}, index_row, "total_return_pct")),
        "sharpe_ratio": safe_float(_pick({"sharpe_ratio": metrics.get("sharpe_ratio")}, index_row, "sharpe_ratio")),
        "max_drawdown_pct": safe_float(_pick({"max_drawdown_pct": metrics.get("max_drawdown_pct")}, index_row, "max_drawdown_pct")),
        "period_start": _pick(meta, index_row, "period_start"),
        "period_end": _pick(meta, index_row, "period_end"),
        "duration_sec": safe_float(_pick(meta, index_row, "duration_sec")) or 0.0,
        "params": params,
        "extra": merged_extra,
        "artifact_path": artifact_path,
        "source_schema": source_schema,
    }


__all__ = [
    "EXPECTED_RUN_ARTIFACTS",
    "build_store_row_from_metadata",
    "coerce_iso_timestamp",
    "derive_migration_status",
    "find_run_artifacts",
    "is_native_result_metadata",
    "is_v3_result_metadata",
    "list_missing_run_artifacts",
    "load_metadata_payload",
    "normalize_status_for_legacy",
    "normalize_status_for_store",
    "safe_float",
    "safe_int",
]
