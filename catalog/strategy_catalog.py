"""Module-ID: catalog.strategy_catalog

Purpose: Lightweight, versioned strategy catalog (lifecycle categories + tags).

Role in pipeline: metadata persistence / UI + CLI filtering

Key components: read_catalog, write_catalog, list_entries, upsert_entry, move_entries

Inputs: JSON file (config/strategy_catalog.json)

Outputs: Updated catalog JSON
"""

# pylint: disable=broad-exception-caught

# ruff: noqa: BLE001

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.builder_diagnostics import _builder_iteration_selection_key, classify_builder_candidate_tier

CATALOG_SCHEMA_VERSION = 1
# Path absolu basé sur l'emplacement du module : évite la dépendance au cwd
# (Streamlit / sous-processus changent parfois cwd, ce qui produisait
# `OSError: [Errno 22] Invalid argument` sur Windows lors du write_text).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG_PATH = _PROJECT_ROOT / "config" / "strategy_catalog.json"
_CATALOG_WRITE_LOCK = threading.Lock()
_CATALOG_WRITE_RETRIES = int(os.getenv("STRATEGY_CATALOG_WRITE_RETRIES", "3"))
_CATALOG_WRITE_RETRY_DELAY_SEC = float(os.getenv("STRATEGY_CATALOG_WRITE_RETRY_DELAY_SEC", "0.1"))

CATEGORY_ORDER = [
    "p1_builder_inbox",
    "p2_positive_observed",
    # p3_manual_review : stratégies P3 dont l'univers naturel est inconnu (token absent
    # de config/token_taxonomy.json) ou dont le pool d'univers est trop petit. Elles ne
    # sont pas perdues — elles attendent une classification manuelle puis un re-run.
    "p3_manual_review",
    "p3_benchmark_consensus",
    "p4_param_robust",
    "p5_wfa_candidate",
    "p6_paper_candidate_low_confidence",
    "p6_paper_candidate",
    "p6_paper_candidate_strict",
    "p7_live_active",
    "p8_live_validated",
    "p9_archived_rejected",
]

CATEGORY_ALIASES = {
    "p2_auto_shortlist": "p2_positive_observed",
    "p3_watchlist": "p3_benchmark_consensus",
    "p4_paper_candidate": "p6_paper_candidate",
    "p6_watchlist": "p6_paper_candidate_low_confidence",
    "p6_low_confidence": "p6_paper_candidate_low_confidence",
    "p5_live_active": "p7_live_active",
    "p6_live_validated": "p8_live_validated",
    "p7_archived_rejected": "p9_archived_rejected",
}

STATUS_VALUES = ["active", "archived"]
BUILDER_STATES = ["completed", "in_progress", "stopped"]

AUTO_SHORTLIST_MIN_TRADES = int(os.getenv("CATALOG_AUTO_MIN_TRADES", "20"))
AUTO_SHORTLIST_MIN_RETURN_PCT = float(os.getenv("CATALOG_AUTO_MIN_RETURN_PCT", "0"))
AUTO_SHORTLIST_MAX_DD_PCT = float(os.getenv("CATALOG_AUTO_MAX_DD_PCT", "35"))
AUTO_SHORTLIST_MIN_PROFIT_FACTOR = float(os.getenv("CATALOG_AUTO_MIN_PF", "1.05"))
AUTO_SHORTLIST_MIN_SCORE = float(os.getenv("CATALOG_AUTO_MIN_SCORE", "45"))


@dataclass
class StrategyInstance:
    id: str
    strategy_name: str
    symbol: str
    timeframe: str
    params_hash: str
    category: str = "p1_builder_inbox"
    status: str = "active"
    tags: list[str] = field(default_factory=list)
    note: str = ""
    builder_state: str | None = None
    last_metrics_snapshot: dict[str, Any] | None = None
    source: str = "registry"
    meta: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "params_hash": self.params_hash,
            "category": self.category,
            "status": self.status,
            "tags": list(self.tags or []),
            "note": self.note or "",
            "builder_state": self.builder_state,
            "last_metrics_snapshot": self.last_metrics_snapshot or None,
            "source": self.source,
            "meta": self.meta or None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_normalize_value(v) for v in value)
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def compute_params_hash(params: dict[str, Any] | None) -> str:
    if not params:
        return "none"
    normalized = _normalize_value(params)
    payload = json.dumps(normalized, sort_keys=True, default=str)
    return _sha1(payload)[:12]


def build_entry_id(strategy_name: str, symbol: str, timeframe: str, params_hash: str) -> str:
    return f"{strategy_name}|{symbol}|{timeframe}|{params_hash}"


def _sha1(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _is_missing(value: Any) -> bool:
    if value is None or value == "":
        return True
    try:
        return bool(value != value)
    except Exception:
        return False


def _first_non_empty(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key not in mapping:
            continue
        value = mapping.get(key)
        if _is_missing(value):
            continue
        return value
    return None


def _collect_prefixed_mapping(mapping: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    collected: dict[str, Any] = {}
    for key, value in mapping.items():
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        if _is_missing(value):
            continue
        name = key[len(prefix):].strip()
        if not name:
            continue
        collected[name] = _normalize_value(value)
    return collected


def _merge_tags(*tag_groups: Iterable[str]) -> list[str]:
    merged: list[str] = []
    for group in tag_groups:
        for tag in group or []:
            value = str(tag or "").strip()
            if not value or value in merged:
                continue
            merged.append(value)
    return merged


def _fallback_params_hash(params: dict[str, Any] | None, fallback_key: str | None = None) -> str:
    params_hash = compute_params_hash(params)
    if params_hash != "none":
        return params_hash
    seed = str(fallback_key or "").strip()
    if seed:
        return _sha1(seed)[:12]
    return "none"


def _coerce_boolish(value: Any) -> bool | None:
    if _is_missing(value):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(value)


def _ensure_catalog_shape(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    schema_version = int(raw.get("schema_version", CATALOG_SCHEMA_VERSION))
    entries = raw.get("entries", [])
    if not isinstance(entries, list):
        entries = []
    return {
        "schema_version": schema_version,
        "updated_at": raw.get("updated_at") or _now_iso(),
        "entries": entries,
    }


def read_catalog(path: Path | None = None) -> dict[str, Any]:
    catalog_path = Path(path or DEFAULT_CATALOG_PATH)
    if not catalog_path.exists():
        return _ensure_catalog_shape({})
    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    return _ensure_catalog_shape(raw)


def _is_transient_catalog_write_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, "winerror", None)
    errno = getattr(exc, "errno", None)
    return winerror == 32 or errno in {13, 32}


def _cleanup_catalog_tmp_file(tmp_path: Path) -> None:
    try:
        if tmp_path.exists():
            tmp_path.unlink()
    except Exception:
        pass


def _build_catalog_tmp_path(target_path: Path) -> Path:
    suffix = f".{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    return target_path.with_name(f"{target_path.name}{suffix}")


def _write_catalog_text_atomically(
    target_path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    last_exc: BaseException | None = None

    with _CATALOG_WRITE_LOCK:
        for attempt in range(_CATALOG_WRITE_RETRIES):
            tmp_path = _build_catalog_tmp_path(target_path)
            try:
                tmp_path.write_text(content, encoding=encoding)
                os.replace(tmp_path, target_path)
                return
            except Exception as exc:
                last_exc = exc
                _cleanup_catalog_tmp_file(tmp_path)
                should_retry = (
                    attempt < (_CATALOG_WRITE_RETRIES - 1)
                    and _is_transient_catalog_write_error(exc)
                )
                if should_retry:
                    time.sleep(_CATALOG_WRITE_RETRY_DELAY_SEC * (attempt + 1))
                    continue
                break

    if last_exc is not None:
        raise last_exc


def write_catalog(payload: dict[str, Any], path: Path | None = None) -> None:
    catalog_path = Path(path or DEFAULT_CATALOG_PATH)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    safe_payload = _ensure_catalog_shape(payload)
    safe_payload["updated_at"] = _now_iso()
    _write_catalog_text_atomically(
        catalog_path,
        json.dumps(safe_payload, indent=2, default=str),
        encoding="utf-8",
    )


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, dict):
        entry = {}
    strategy_name = str(entry.get("strategy_name", "") or "").strip()
    symbol = str(entry.get("symbol", "") or "").strip()
    timeframe = str(entry.get("timeframe", "") or "").strip()
    params_hash = str(entry.get("params_hash", "") or "none").strip() or "none"
    category = str(entry.get("category", "p1_builder_inbox") or "p1_builder_inbox")
    category = CATEGORY_ALIASES.get(category, category)
    if category not in CATEGORY_ORDER:
        category = "p1_builder_inbox"
    status = str(entry.get("status", "active") or "active")
    if status not in STATUS_VALUES:
        status = "active"
    builder_state = entry.get("builder_state")
    if builder_state and builder_state not in BUILDER_STATES:
        builder_state = None
    tags = entry.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]
    note = str(entry.get("note", "") or "")
    source = str(entry.get("source", "registry") or "registry")
    last_metrics_snapshot = entry.get("last_metrics_snapshot")
    if last_metrics_snapshot is not None and not isinstance(last_metrics_snapshot, dict):
        last_metrics_snapshot = None
    meta = entry.get("meta")
    if meta is not None and not isinstance(meta, dict):
        meta = {"value": str(meta)}
    entry_id = str(entry.get("id", "") or "").strip()
    if not entry_id:
        entry_id = build_entry_id(strategy_name, symbol, timeframe, params_hash)
    created_at = entry.get("created_at") or _now_iso()
    updated_at = entry.get("updated_at") or _now_iso()
    return {
        "id": entry_id,
        "strategy_name": strategy_name,
        "symbol": symbol,
        "timeframe": timeframe,
        "params_hash": params_hash,
        "category": category,
        "status": status,
        "tags": _merge_tags(tags),
        "note": note,
        "builder_state": builder_state,
        "last_metrics_snapshot": last_metrics_snapshot,
        "source": source,
        "meta": meta,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def list_entries(
    *,
    path: Path | None = None,
    categories: Iterable[str] | None = None,
    tags: Iterable[str] | None = None,
    status: str | None = "active",
    symbol: str | None = None,
    timeframe: str | None = None,
    strategy_name: str | None = None,
) -> list[dict[str, Any]]:
    catalog = read_catalog(path)
    entries = [_normalize_entry(e) for e in catalog.get("entries", [])]

    if categories:
        wanted = {str(c).strip() for c in categories if str(c).strip()}
        entries = [e for e in entries if e.get("category") in wanted]
    if tags:
        wanted_tags = {str(t).strip() for t in tags if str(t).strip()}
        entries = [e for e in entries if wanted_tags.intersection(set(e.get("tags", [])))]
    if status:
        entries = [e for e in entries if e.get("status") == status]
    if symbol:
        entries = [e for e in entries if e.get("symbol") == symbol]
    if timeframe:
        entries = [e for e in entries if e.get("timeframe") == timeframe]
    if strategy_name:
        entries = [e for e in entries if e.get("strategy_name") == strategy_name]

    return entries


def get_entry(entry_id: str, *, path: Path | None = None) -> dict[str, Any] | None:
    if not entry_id:
        return None
    catalog = read_catalog(path)
    for raw in catalog.get("entries", []):
        entry = _normalize_entry(raw)
        if entry.get("id") == entry_id:
            return entry
    return None


def _merge_entry_for_upsert(
    existing: dict[str, Any] | None,
    new_entry: dict[str, Any],
    *,
    now: str,
) -> dict[str, Any]:
    normalized = _normalize_entry(new_entry)
    if not existing:
        normalized["created_at"] = normalized.get("created_at") or now
        normalized["updated_at"] = now
        return normalized

    merged = {**existing, **normalized}
    merged["created_at"] = existing.get("created_at") or now
    merged["updated_at"] = now
    return merged


def _upsert_entries_into_catalog(catalog: dict[str, Any], entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    current_entries = [_normalize_entry(entry) for entry in catalog.get("entries", [])]
    by_id = {entry["id"]: entry for entry in current_entries}
    now = _now_iso()
    saved_entries: list[dict[str, Any]] = []

    for raw_entry in entries:
        normalized = _normalize_entry(raw_entry)
        merged = _merge_entry_for_upsert(by_id.get(normalized["id"]), normalized, now=now)
        by_id[normalized["id"]] = merged
        saved_entries.append(merged)

    catalog["entries"] = list(by_id.values())
    return saved_entries


def upsert_entries(entries: Iterable[dict[str, Any]], *, path: Path | None = None) -> list[dict[str, Any]]:
    pending_entries = list(entries)
    if not pending_entries:
        return []

    catalog = read_catalog(path)
    saved_entries = _upsert_entries_into_catalog(catalog, pending_entries)
    write_catalog(catalog, path)
    return saved_entries


def upsert_entry(entry: dict[str, Any], *, path: Path | None = None) -> dict[str, Any]:
    return upsert_entries([entry], path=path)[0]


def move_entries(entry_ids: Iterable[str], category: str, *, path: Path | None = None) -> int:
    if category not in CATEGORY_ORDER:
        raise ValueError(f"Invalid category: {category}")
    catalog = read_catalog(path)
    entries = [_normalize_entry(e) for e in catalog.get("entries", [])]
    ids = {str(eid).strip() for eid in entry_ids if str(eid).strip()}
    changed = 0
    for entry in entries:
        if entry.get("id") in ids:
            entry["category"] = category
            entry["updated_at"] = _now_iso()
            changed += 1
    catalog["entries"] = entries
    write_catalog(catalog, path)
    return changed


def tag_entries(entry_ids: Iterable[str], tag: str, *, path: Path | None = None) -> int:
    tag = str(tag).strip()
    if not tag:
        return 0
    catalog = read_catalog(path)
    entries = [_normalize_entry(e) for e in catalog.get("entries", [])]
    ids = {str(eid).strip() for eid in entry_ids if str(eid).strip()}
    changed = 0
    for entry in entries:
        if entry.get("id") in ids:
            tags = set(entry.get("tags", []))
            if tag not in tags:
                tags.add(tag)
                entry["tags"] = sorted(tags)
                entry["updated_at"] = _now_iso()
                changed += 1
    catalog["entries"] = entries
    write_catalog(catalog, path)
    return changed


def note_entry(entry_id: str, note: str, *, path: Path | None = None) -> bool:
    if not entry_id:
        return False
    catalog = read_catalog(path)
    entries = [_normalize_entry(e) for e in catalog.get("entries", [])]
    updated = False
    for entry in entries:
        if entry.get("id") == entry_id:
            entry["note"] = str(note or "")
            entry["updated_at"] = _now_iso()
            updated = True
            break
    catalog["entries"] = entries
    write_catalog(catalog, path)
    return updated


def archive_entries(entry_ids: Iterable[str], *, path: Path | None = None) -> int:
    catalog = read_catalog(path)
    entries = [_normalize_entry(e) for e in catalog.get("entries", [])]
    ids = {str(eid).strip() for eid in entry_ids if str(eid).strip()}
    changed = 0
    for entry in entries:
        if entry.get("id") in ids:
            entry["status"] = "archived"
            entry["updated_at"] = _now_iso()
            changed += 1
    catalog["entries"] = entries
    write_catalog(catalog, path)
    return changed


def _auto_shortlist_ok(metrics: dict[str, Any], target_sharpe: float | None) -> bool:
    if not metrics:
        return False
    sharpe = _float(metrics.get("sharpe_ratio") or metrics.get("sharpe") or 0.0, 0.0)
    total_return = _float(
        metrics.get("total_return_pct") or metrics.get("total_return") or 0.0,
        0.0,
    )
    if metrics.get("total_return_pct") is None:
        total_return *= 100.0
    trades = int(metrics.get("total_trades") or metrics.get("trades") or 0)
    max_dd = abs(
        _float(metrics.get("max_drawdown_pct") or metrics.get("max_drawdown") or 0.0, 0.0),
    )
    profit_factor = _float(metrics.get("profit_factor") or 0.0, 0.0)
    required_sharpe = target_sharpe if target_sharpe is not None else 1.0
    max_dd_excess = max(0.0, max_dd - AUTO_SHORTLIST_MAX_DD_PCT)
    quality_score = (
        30.0 * max(-1.0, min(2.0, sharpe / max(required_sharpe, 0.5)))
        + 24.0 * max(-1.0, min(2.0, total_return / 20.0))
        + 14.0 * max(-1.0, min(2.0, (profit_factor - 1.0) / 0.35))
        + 8.0 * max(0.0, min(1.0, trades / 60.0))
        - 20.0 * max(0.0, min(2.0, max_dd_excess / 12.0))
    )
    if max_dd > (AUTO_SHORTLIST_MAX_DD_PCT + 25.0):
        return False
    return (
        trades >= AUTO_SHORTLIST_MIN_TRADES
        and total_return >= AUTO_SHORTLIST_MIN_RETURN_PCT
        and profit_factor >= AUTO_SHORTLIST_MIN_PROFIT_FACTOR
        and sharpe >= required_sharpe
        and quality_score >= AUTO_SHORTLIST_MIN_SCORE
    )


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def compute_builder_candidate_params_hash(
    params: dict[str, Any] | None,
    *,
    session_id: str,
    iteration_num: int,
) -> str:
    fallback_key = f"{str(session_id or '').strip()}:{int(iteration_num or 0)}"
    return _fallback_params_hash(params, fallback_key=fallback_key)


def build_builder_candidate_entry_id(
    *,
    session_id: str,
    symbol: str,
    timeframe: str,
    iteration_num: int,
    params_hash: str,
) -> str:
    safe_symbol = str(symbol or "UNKNOWN").strip() or "UNKNOWN"
    safe_timeframe = str(timeframe or "1h").strip() or "1h"
    candidate_scope = f"builder:{str(session_id or '').strip()}:{int(iteration_num or 0)}"
    return f"builder_generated|{safe_symbol}|{safe_timeframe}|{params_hash}|{candidate_scope}"


def _builder_iteration_phase_feedback(iteration: Any) -> dict[str, Any]:
    raw = getattr(iteration, "phase_feedback", None)
    if hasattr(raw, "to_dict"):
        try:
            payload = raw.to_dict()
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    return dict(raw or {}) if isinstance(raw, dict) else {}


def _builder_iteration_backtest_feedback(iteration: Any) -> dict[str, Any]:
    feedback = _builder_iteration_phase_feedback(iteration).get("backtest", {})
    return dict(feedback or {}) if isinstance(feedback, dict) else {}


def _builder_iteration_has_blocking_error(iteration: Any) -> bool:
    feedback = _builder_iteration_backtest_feedback(iteration)
    return bool(
        str(getattr(iteration, "error", "") or "").strip()
        or str(feedback.get("runtime_error") or "").strip()
        or str(feedback.get("runtime_traceback_tail") or "").strip()
    )


def _builder_iteration_metrics(iteration: Any) -> dict[str, Any]:
    result = getattr(iteration, "backtest_result", None)
    if result is None:
        return {}
    metrics = getattr(result, "metrics", None)
    if isinstance(metrics, dict):
        return dict(metrics)
    if hasattr(metrics, "to_dict"):
        try:
            payload = metrics.to_dict()
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    return {}


def _builder_iteration_params(iteration: Any) -> dict[str, Any]:
    result = getattr(iteration, "backtest_result", None)
    if result is not None:
        meta = getattr(result, "meta", {}) or {}
        if isinstance(meta, dict):
            params = meta.get("params")
            if isinstance(params, dict) and params:
                return dict(params)
    feedback = _builder_iteration_backtest_feedback(iteration)
    params_used = feedback.get("params_used")
    if isinstance(params_used, dict) and params_used:
        return dict(params_used)
    return {}


def _builder_iteration_num(iteration: Any) -> int:
    try:
        return int(getattr(iteration, "iteration", 0) or 0)
    except Exception:
        return 0


def _builder_iteration_return_pct(iteration: Any) -> float:
    metrics = _builder_iteration_metrics(iteration)
    return _float(
        metrics.get("total_return_pct", metrics.get("return_pct")),
        float("-inf"),
    )


def _builder_iteration_sort_key(iteration: Any, *, target_sharpe: float | None = None) -> tuple[Any, ...]:
    metrics = _builder_iteration_metrics(iteration)
    return_pct = _builder_iteration_return_pct(iteration)
    sharpe = _float(metrics.get("sharpe_ratio", metrics.get("sharpe")), float("-inf"))
    profit_factor = _float(metrics.get("profit_factor"), float("-inf"))
    trades = _float(metrics.get("total_trades", metrics.get("trades")), -1.0)
    return (
        *_builder_iteration_selection_key(
            metrics,
            is_fallback=bool(getattr(iteration, "is_fallback", False)),
            target_sharpe=float(target_sharpe if target_sharpe is not None else 1.0),
        ),
        1.0 if return_pct > 0.0 else 0.0,
        return_pct,
        sharpe,
        profit_factor,
        trades,
        float(_builder_iteration_num(iteration)),
    )


def _select_builder_catalog_iterations(session: Any) -> tuple[list[Any], str]:
    iterations = [iteration for iteration in list(getattr(session, "iterations", []) or []) if iteration is not None]
    positive_iterations = [
        iteration
        for iteration in iterations
        if _builder_iteration_return_pct(iteration) > 0.0 and not _builder_iteration_has_blocking_error(iteration)
    ]
    if positive_iterations:
        positive_iterations.sort(
            key=lambda iteration: _builder_iteration_sort_key(
                iteration,
                target_sharpe=getattr(session, "target_sharpe", None),
            ),
            reverse=True,
        )
        return positive_iterations, "positive"

    best_iteration = getattr(session, "best_iteration", None)
    if best_iteration is None and iterations:
        best_iteration = max(
            iterations,
            key=lambda iteration: _builder_iteration_sort_key(
                iteration,
                target_sharpe=getattr(session, "target_sharpe", None),
            ),
        )
    return ([best_iteration] if best_iteration is not None else []), "fallback"


def _build_builder_iteration_catalog_entry(
    session: Any,
    iteration: Any,
    *,
    selection_scope: str,
    positive_iteration_nums: list[int],
) -> dict[str, Any]:
    session_id = str(getattr(session, "session_id", "") or "").strip()
    symbol = str(getattr(session, "symbol", "") or "UNKNOWN").strip() or "UNKNOWN"
    timeframe = str(getattr(session, "timeframe", "") or "1h").strip() or "1h"
    status = str(getattr(session, "status", "") or "")
    builder_state = "completed"
    if status == "running":
        builder_state = "in_progress"
    elif status in ("failed", "max_iterations"):
        builder_state = "stopped"

    iteration_num = _builder_iteration_num(iteration)
    metrics = _builder_iteration_metrics(iteration)
    params = _builder_iteration_params(iteration)
    params_hash = compute_builder_candidate_params_hash(
        params,
        session_id=session_id,
        iteration_num=iteration_num,
    )
    entry_id = build_builder_candidate_entry_id(
        session_id=session_id,
        symbol=symbol,
        timeframe=timeframe,
        iteration_num=iteration_num,
        params_hash=params_hash,
    )
    return_pct = _builder_iteration_return_pct(iteration)
    has_blocking_error = _builder_iteration_has_blocking_error(iteration)
    category = "p2_positive_observed" if return_pct > 0.0 and not has_blocking_error else "p1_builder_inbox"
    candidate_classification = (
        classify_builder_candidate_tier(
            metrics,
            target_sharpe=float(getattr(session, "target_sharpe", 1.0) or 1.0),
        )
        if metrics and not has_blocking_error
        else {"tier": "failed", "reason": "runtime_error" if has_blocking_error else "missing_metrics"}
    )
    candidate_tier = str(candidate_classification.get("tier") or "")
    candidate_reason = str(candidate_classification.get("reason") or "")

    tags = ["builder_out", "builder_iteration"]
    if return_pct > 0.0 and not has_blocking_error:
        tags.append("positive_return")
        tags.append("positive_candidate")
    if candidate_tier == "promising":
        tags.append("promising_candidate")
    elif candidate_tier == "success":
        tags.append("success_candidate")
    if _auto_shortlist_ok(metrics, getattr(session, "target_sharpe", None)):
        tags.append("auto_shortlist_pass")
    if selection_scope == "fallback":
        tags.append("builder_session_fallback")
    universe_mode = str(getattr(session, "universe_mode", "") or "").strip()
    if universe_mode:
        tags.append(f"universe_{universe_mode}")

    strategy_file = ""
    session_dir = getattr(session, "session_dir", None)
    if isinstance(session_dir, Path):
        versioned = session_dir / f"strategy_v{iteration_num}.py"
        latest = session_dir / "strategy.py"
        selected_path = versioned if iteration_num > 0 and versioned.exists() else latest if latest.exists() else None
        if selected_path is not None:
            strategy_file = str(selected_path)

    note_parts = [f"session_id: {session_id}", f"iteration: {iteration_num}"]
    objective = str(getattr(session, "objective", "") or "").strip()
    if objective:
        note_parts.append(objective[:300])

    return {
        "id": entry_id,
        "strategy_name": "builder_generated",
        "symbol": symbol,
        "timeframe": timeframe,
        "params_hash": params_hash,
        "category": category,
        "status": "active",
        "builder_state": builder_state,
        "source": "builder",
        "tags": tags,
        "note": " | ".join(note_parts),
        "last_metrics_snapshot": metrics or None,
        "meta": {
            "session_id": session_id,
            "builder_session_id": session_id,
            "builder_iteration": iteration_num,
            "candidate_id": f"builder:{session_id}:{iteration_num}" if iteration_num > 0 else session_id,
            "selection_scope": selection_scope,
            "positive_return_pct": return_pct if return_pct > 0.0 else None,
            "source_symbol": symbol,
            "source_timeframe": timeframe,
            "source_params": params or None,
            "strategy_file": strategy_file or None,
            "builder_objective": objective or None,
            "session_status": status or None,
            "best_sharpe": getattr(session, "best_sharpe", None),
            "best_raw_sharpe": getattr(session, "best_raw_sharpe", None),
            "candidate_tier": candidate_tier or None,
            "candidate_reason": candidate_reason or None,
            "total_iterations": len(getattr(session, "iterations", []) or []),
            "session_positive_iteration_count": len(positive_iteration_nums),
            "session_positive_iterations": positive_iteration_nums,
            "universe_mode": universe_mode,
            "universe_purpose": str(getattr(session, "universe_purpose", "") or ""),
            "universe_strategy_type": str(getattr(session, "universe_strategy_type", "") or ""),
        },
    }


def build_entry_from_saved_run(
    saved_run: Mapping[str, Any],
    *,
    category: str = "p3_benchmark_consensus",
) -> dict[str, Any]:
    """Normalise un run sauvegardé/artefact en entrée du strategy catalog."""
    if category not in CATEGORY_ORDER:
        raise ValueError(f"Invalid category: {category}")

    payload = dict(saved_run or {})
    strategy_name = str(_first_non_empty(payload, "strategy", "strategy_name") or "").strip()
    symbol = str(_first_non_empty(payload, "symbol") or "UNKNOWN").strip() or "UNKNOWN"
    timeframe = str(_first_non_empty(payload, "timeframe") or "unknown").strip() or "unknown"
    run_id = str(_first_non_empty(payload, "run_id", "id") or "").strip()
    source_path = str(_first_non_empty(payload, "path") or "").strip()
    artifact_type = str(_first_non_empty(payload, "artifact_type") or "saved_run").strip()
    schema = str(_first_non_empty(payload, "schema") or "").strip()
    mode = (
        str(
            _first_non_empty(payload, "mode") or _first_non_empty(payload, "origin") or "backtest",
        ).strip()
        or "backtest"
    )
    source_status = str(_first_non_empty(payload, "status") or "unknown").strip().lower() or "unknown"

    if source_status in {"partial", "failed", "error", "stopped", "interrupted"}:
        raise ValueError(f"Incomplete run cannot be promoted: status={source_status}")

    params_raw = payload.get("params")
    params = dict(params_raw or {}) if isinstance(params_raw, dict) else _collect_prefixed_mapping(payload, "params_")
    metrics_raw = payload.get("metrics")
    metrics = (
        dict(metrics_raw or {}) if isinstance(metrics_raw, dict) else _collect_prefixed_mapping(payload, "metrics_")
    )
    extra_raw = payload.get("extra_metadata")
    extra_metadata = (
        dict(extra_raw or {}) if isinstance(extra_raw, dict) else _collect_prefixed_mapping(payload, "extra_")
    )

    params_hash = _fallback_params_hash(
        params,
        fallback_key=run_id or extra_metadata.get("builder_session_id") or source_path,
    )
    entry_id = build_entry_id(strategy_name or "saved_run_candidate", symbol, timeframe, params_hash)

    loadable = _coerce_boolish(payload.get("loadable"))

    tags = ["promoted_run", "replay_candidate"]
    if artifact_type == "external_run":
        tags.append("external_artifact")
    else:
        tags.append("saved_run")
    if mode:
        tags.append(f"mode_{mode}")
    origin = str(extra_metadata.get("origin") or "").strip()
    if origin == "builder" or mode == "builder":
        tags.append("builder_out")

    note_parts = []
    if run_id:
        note_parts.append(f"source_run_id: {run_id}")
    if source_path:
        note_parts.append(f"path: {source_path}")
    note_parts.append(f"source_mode: {mode}")
    note_parts.append(f"artifact: {artifact_type}")

    meta: dict[str, Any] = {
        "source_run_id": run_id or None,
        "source_path": source_path or None,
        "source_artifact_type": artifact_type,
        "source_schema": schema or None,
        "source_mode": mode,
        "source_status": source_status,
        "source_parent_scope": _first_non_empty(payload, "parent_scope"),
        "loadable": loadable,
    }
    for key in (
        "builder_session_id",
        "builder_iteration",
        "builder_objective",
        "origin",
        "universe_mode",
        "universe_purpose",
        "universe_strategy_type",
    ):
        value = extra_metadata.get(key)
        if _is_missing(value):
            continue
        meta[key] = _normalize_value(value)
    universe_mode = str(meta.get("universe_mode") or "").strip()
    if universe_mode:
        tags.append(f"universe_{universe_mode}")

    return {
        "id": entry_id,
        "strategy_name": strategy_name or "saved_run_candidate",
        "symbol": symbol,
        "timeframe": timeframe,
        "params_hash": params_hash,
        "category": category,
        "status": "active",
        "tags": tags,
        "note": " | ".join(note_parts),
        "source": "saved_run" if artifact_type == "saved_run" else "external_run",
        "last_metrics_snapshot": metrics or None,
        "meta": meta,
    }


def prepare_saved_run_entry(
    saved_run: Mapping[str, Any],
    *,
    target_category: str = "p3_benchmark_consensus",
    existing_entry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    entry = build_entry_from_saved_run(saved_run, category=target_category)
    if not existing_entry:
        return entry

    existing = _normalize_entry(dict(existing_entry))
    existing_category = existing.get("category")
    if existing_category in CATEGORY_ORDER:
        if CATEGORY_ORDER.index(existing_category) > CATEGORY_ORDER.index(target_category):
            entry["category"] = existing_category
    entry["tags"] = _merge_tags(existing.get("tags") or [], entry.get("tags") or [])
    if existing.get("note"):
        entry["note"] = existing["note"]
    existing_meta = existing.get("meta") or {}
    merged_meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
    merged_meta.update(entry.get("meta") or {})
    entry["meta"] = merged_meta
    if existing.get("builder_state"):
        entry["builder_state"] = existing.get("builder_state")
    if existing.get("last_metrics_snapshot") and not entry.get("last_metrics_snapshot"):
        entry["last_metrics_snapshot"] = existing.get("last_metrics_snapshot")
    return entry


def upsert_from_saved_runs(
    saved_runs: Iterable[Mapping[str, Any]],
    *,
    target_category: str = "p3_benchmark_consensus",
    path: Path | None = None,
) -> list[dict[str, Any]]:
    pending_runs = list(saved_runs)
    if not pending_runs:
        return []

    catalog = read_catalog(path)
    existing_entries = [_normalize_entry(entry) for entry in catalog.get("entries", [])]
    existing_by_id = {entry["id"]: entry for entry in existing_entries}
    prepared_entries: list[dict[str, Any]] = []

    for saved_run in pending_runs:
        base_entry = build_entry_from_saved_run(saved_run, category=target_category)
        prepared = prepare_saved_run_entry(
            saved_run,
            target_category=target_category,
            existing_entry=existing_by_id.get(base_entry["id"]),
        )
        prepared_entries.append(prepared)
        existing_by_id[prepared["id"]] = _normalize_entry(prepared)

    saved_entries = _upsert_entries_into_catalog(catalog, prepared_entries)
    write_catalog(catalog, path)
    return saved_entries


def upsert_from_saved_run(
    saved_run: Mapping[str, Any],
    *,
    target_category: str = "p3_benchmark_consensus",
    path: Path | None = None,
) -> dict[str, Any]:
    """Promeut un run sauvegardé vers le strategy catalog existant."""
    return upsert_from_saved_runs(
        [saved_run],
        target_category=target_category,
        path=path,
    )[0]


def upsert_from_builder_session(session: Any, *, path: Path | None = None) -> dict[str, Any]:
    """Create or update canonical catalog entries from a builder session object."""
    session_id = str(getattr(session, "session_id", "") or "").strip()
    desired_iterations, selection_scope = _select_builder_catalog_iterations(session)
    positive_iteration_nums = sorted(
        _builder_iteration_num(iteration)
        for iteration in list(getattr(session, "iterations", []) or [])
        if _builder_iteration_return_pct(iteration) > 0.0
    )

    if not desired_iterations:
        raise ValueError(f"Builder session has no catalogable iteration: session_id={session_id or '<missing>'}")

    catalog = read_catalog(path)
    existing_entries = [_normalize_entry(entry) for entry in catalog.get("entries", [])]
    existing_by_id = {entry["id"]: entry for entry in existing_entries}

    stale_entry_ids: list[str] = []
    for existing in existing_entries:
        if existing.get("source") != "builder":
            continue
        meta = existing.get("meta") or {}
        if not isinstance(meta, dict):
            continue
        existing_session_id = str(
            meta.get("builder_session_id") or meta.get("session_id") or "",
        ).strip()
        if existing_session_id != session_id:
            continue
        stale_entry_ids.append(str(existing.get("id") or ""))

    pending_entries: list[dict[str, Any]] = []
    active_ids: set[str] = set()
    for iteration in desired_iterations:
        entry = _build_builder_iteration_catalog_entry(
            session,
            iteration,
            selection_scope=selection_scope,
            positive_iteration_nums=positive_iteration_nums,
        )
        existing = existing_by_id.get(entry["id"])
        if existing:
            existing_category = existing.get("category")
            if existing_category in CATEGORY_ORDER and CATEGORY_ORDER.index(existing_category) >= CATEGORY_ORDER.index(
                "p3_benchmark_consensus",
            ):
                entry["category"] = existing_category
            entry["tags"] = _merge_tags(existing.get("tags") or [], entry.get("tags") or [])
            existing_meta = existing.get("meta") or {}
            if isinstance(existing_meta, dict):
                merged_meta = dict(existing_meta)
                merged_meta.update(entry.get("meta") or {})
                entry["meta"] = merged_meta
            if existing.get("note"):
                entry["note"] = existing["note"]
        pending_entries.append(entry)
        active_ids.add(entry["id"])
        existing_by_id[entry["id"]] = _normalize_entry(entry)

    stale_ids = [entry_id for entry_id in stale_entry_ids if entry_id and entry_id not in active_ids]
    if stale_ids:
        for stale_id in stale_ids:
            existing = existing_by_id.get(stale_id)
            if not existing:
                continue
            archived_entry = dict(existing)
            archived_entry["status"] = "archived"
            pending_entries.append(archived_entry)

    saved_entries = _upsert_entries_into_catalog(catalog, pending_entries)
    write_catalog(catalog, path)
    saved_active_entries = [entry for entry in saved_entries if entry.get("id") in active_ids]

    saved_active_entries.sort(
        key=lambda entry: (
            *_builder_iteration_selection_key(
                dict(entry.get("last_metrics_snapshot") or {}),
                is_fallback=bool((entry.get("last_metrics_snapshot") or {}).get("is_fallback", False)),
                target_sharpe=1.0,
            ),
            1.0 if _float((entry.get("last_metrics_snapshot") or {}).get("total_return_pct"), float("-inf")) > 0.0 else 0.0,
            _float((entry.get("last_metrics_snapshot") or {}).get("total_return_pct"), float("-inf")),
            _float((entry.get("last_metrics_snapshot") or {}).get("sharpe_ratio"), float("-inf")),
            _float((entry.get("meta") or {}).get("builder_iteration"), 0.0),
        ),
        reverse=True,
    )
    return saved_active_entries[0]
