"""
Module-ID: catalog.strategy_catalog

Purpose: Lightweight, versioned strategy catalog (lifecycle categories + tags).

Role in pipeline: metadata persistence / UI + CLI filtering

Key components: read_catalog, write_catalog, list_entries, upsert_entry, move_entries

Inputs: JSON file (config/strategy_catalog.json)

Outputs: Updated catalog JSON
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


CATALOG_SCHEMA_VERSION = 1
DEFAULT_CATALOG_PATH = Path("config/strategy_catalog.json")

CATEGORY_ORDER = [
    "p1_builder_inbox",
    "p2_auto_shortlist",
    "p3_watchlist",
    "p4_paper_candidate",
    "p5_live_active",
    "p6_live_validated",
    "p7_archived_rejected",
]

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
    tags: List[str] = field(default_factory=list)
    note: str = ""
    builder_state: Optional[str] = None
    last_metrics_snapshot: Optional[Dict[str, Any]] = None
    source: str = "registry"
    meta: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
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


def compute_params_hash(params: Optional[Dict[str, Any]]) -> str:
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


def _collect_prefixed_mapping(mapping: Mapping[str, Any], prefix: str) -> Dict[str, Any]:
    collected: Dict[str, Any] = {}
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


def _merge_tags(*tag_groups: Iterable[str]) -> List[str]:
    merged: List[str] = []
    for group in tag_groups:
        for tag in group or []:
            value = str(tag or "").strip()
            if not value or value in merged:
                continue
            merged.append(value)
    return merged


def _fallback_params_hash(params: Optional[Dict[str, Any]], fallback_key: Optional[str] = None) -> str:
    params_hash = compute_params_hash(params)
    if params_hash != "none":
        return params_hash
    seed = str(fallback_key or "").strip()
    if seed:
        return _sha1(seed)[:12]
    return "none"


def _coerce_boolish(value: Any) -> Optional[bool]:
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


def _ensure_catalog_shape(raw: Dict[str, Any]) -> Dict[str, Any]:
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


def read_catalog(path: Optional[Path] = None) -> Dict[str, Any]:
    catalog_path = Path(path or DEFAULT_CATALOG_PATH)
    if not catalog_path.exists():
        return _ensure_catalog_shape({})
    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    return _ensure_catalog_shape(raw)


def write_catalog(payload: Dict[str, Any], path: Optional[Path] = None) -> None:
    catalog_path = Path(path or DEFAULT_CATALOG_PATH)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    safe_payload = _ensure_catalog_shape(payload)
    safe_payload["updated_at"] = _now_iso()
    catalog_path.write_text(
        json.dumps(safe_payload, indent=2, default=str),
        encoding="utf-8",
    )


def _normalize_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        entry = {}
    strategy_name = str(entry.get("strategy_name", "") or "").strip()
    symbol = str(entry.get("symbol", "") or "").strip()
    timeframe = str(entry.get("timeframe", "") or "").strip()
    params_hash = str(entry.get("params_hash", "") or "none").strip() or "none"
    category = str(entry.get("category", "p1_builder_inbox") or "p1_builder_inbox")
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
        "tags": [str(t) for t in tags if str(t).strip()],
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
    path: Optional[Path] = None,
    categories: Optional[Iterable[str]] = None,
    tags: Optional[Iterable[str]] = None,
    status: Optional[str] = "active",
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    strategy_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    catalog = read_catalog(path)
    entries = [_normalize_entry(e) for e in catalog.get("entries", [])]

    if categories:
        wanted = {str(c).strip() for c in categories if str(c).strip()}
        entries = [e for e in entries if e.get("category") in wanted]
    if tags:
        wanted_tags = {str(t).strip() for t in tags if str(t).strip()}
        entries = [
            e for e in entries
            if wanted_tags.intersection(set(e.get("tags", [])))
        ]
    if status:
        entries = [e for e in entries if e.get("status") == status]
    if symbol:
        entries = [e for e in entries if e.get("symbol") == symbol]
    if timeframe:
        entries = [e for e in entries if e.get("timeframe") == timeframe]
    if strategy_name:
        entries = [e for e in entries if e.get("strategy_name") == strategy_name]

    return entries


def get_entry(entry_id: str, *, path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    if not entry_id:
        return None
    catalog = read_catalog(path)
    for raw in catalog.get("entries", []):
        entry = _normalize_entry(raw)
        if entry.get("id") == entry_id:
            return entry
    return None


def upsert_entry(entry: Dict[str, Any], *, path: Optional[Path] = None) -> Dict[str, Any]:
    catalog = read_catalog(path)
    entries = [_normalize_entry(e) for e in catalog.get("entries", [])]
    new_entry = _normalize_entry(entry)
    now = _now_iso()

    by_id = {e["id"]: e for e in entries}
    existing = by_id.get(new_entry["id"])
    if existing:
        created_at = existing.get("created_at") or now
        merged = {**existing, **new_entry}
        merged["created_at"] = created_at
        merged["updated_at"] = now
        by_id[new_entry["id"]] = merged
    else:
        new_entry["created_at"] = new_entry.get("created_at") or now
        new_entry["updated_at"] = now
        by_id[new_entry["id"]] = new_entry

    catalog["entries"] = list(by_id.values())
    write_catalog(catalog, path)
    return by_id[new_entry["id"]]


def move_entries(entry_ids: Iterable[str], category: str, *, path: Optional[Path] = None) -> int:
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


def tag_entries(entry_ids: Iterable[str], tag: str, *, path: Optional[Path] = None) -> int:
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


def note_entry(entry_id: str, note: str, *, path: Optional[Path] = None) -> bool:
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


def archive_entries(entry_ids: Iterable[str], *, path: Optional[Path] = None) -> int:
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


def _auto_shortlist_ok(metrics: Dict[str, Any], target_sharpe: Optional[float]) -> bool:
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
        _float(metrics.get("max_drawdown_pct") or metrics.get("max_drawdown") or 0.0, 0.0)
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


def build_entry_from_saved_run(
    saved_run: Mapping[str, Any],
    *,
    category: str = "p3_watchlist",
) -> Dict[str, Any]:
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
    mode = str(
        _first_non_empty(payload, "mode") or _first_non_empty(payload, "origin") or "backtest"
    ).strip() or "backtest"
    source_status = str(_first_non_empty(payload, "status") or "unknown").strip().lower() or "unknown"

    if source_status in {"partial", "failed", "error", "stopped", "interrupted"}:
        raise ValueError(f"Incomplete run cannot be promoted: status={source_status}")

    params_raw = payload.get("params")
    params = dict(params_raw or {}) if isinstance(params_raw, dict) else _collect_prefixed_mapping(payload, "params_")
    metrics_raw = payload.get("metrics")
    metrics = dict(metrics_raw or {}) if isinstance(metrics_raw, dict) else _collect_prefixed_mapping(payload, "metrics_")
    extra_raw = payload.get("extra_metadata")
    extra_metadata = (
        dict(extra_raw or {})
        if isinstance(extra_raw, dict)
        else _collect_prefixed_mapping(payload, "extra_")
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

    meta: Dict[str, Any] = {
        "source_run_id": run_id or None,
        "source_path": source_path or None,
        "source_artifact_type": artifact_type,
        "source_schema": schema or None,
        "source_mode": mode,
        "source_status": source_status,
        "source_parent_scope": _first_non_empty(payload, "parent_scope"),
        "loadable": loadable,
    }
    for key in ("builder_session_id", "builder_iteration", "builder_objective", "origin"):
        value = extra_metadata.get(key)
        if _is_missing(value):
            continue
        meta[key] = _normalize_value(value)

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


def upsert_from_saved_run(
    saved_run: Mapping[str, Any],
    *,
    target_category: str = "p3_watchlist",
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Promeut un run sauvegardé vers le strategy catalog existant."""
    entry = build_entry_from_saved_run(saved_run, category=target_category)
    existing = get_entry(entry["id"], path=path)
    if existing:
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
    return upsert_entry(entry, path=path)


def upsert_from_builder_session(session: Any, *, path: Optional[Path] = None) -> Dict[str, Any]:
    """Create or update a catalog entry from a builder session object."""
    session_id = str(getattr(session, "session_id", "") or "").strip()
    symbol = str(getattr(session, "symbol", "") or "UNKNOWN").strip()
    timeframe = str(getattr(session, "timeframe", "") or "1h").strip()
    status = str(getattr(session, "status", "") or "")
    builder_state = "completed"
    if status == "running":
        builder_state = "in_progress"
    elif status in ("failed", "max_iterations"):
        builder_state = "stopped"

    best_iter = getattr(session, "best_iteration", None)
    best_metrics = {}
    best_params = {}
    if best_iter and getattr(best_iter, "backtest_result", None):
        metrics = getattr(best_iter.backtest_result, "metrics", None)
        if isinstance(metrics, dict):
            best_metrics = metrics
        elif hasattr(metrics, "to_dict"):
            best_metrics = metrics.to_dict()
        meta = getattr(best_iter.backtest_result, "meta", {}) or {}
        if isinstance(meta, dict):
            best_params = meta.get("params", {}) or {}

    params_hash = _fallback_params_hash(best_params, fallback_key=session_id)
    entry_id = build_entry_id("builder_generated", symbol, timeframe, params_hash)

    category = "p1_builder_inbox"
    if _auto_shortlist_ok(best_metrics, getattr(session, "target_sharpe", None)):
        category = "p2_auto_shortlist"

    existing = get_entry(entry_id, path=path)
    if existing:
        existing_category = existing.get("category")
        if existing_category in CATEGORY_ORDER:
            if CATEGORY_ORDER.index(existing_category) >= CATEGORY_ORDER.index("p3_watchlist"):
                category = existing_category

    entry = {
        "id": entry_id,
        "strategy_name": "builder_generated",
        "symbol": symbol,
        "timeframe": timeframe,
        "params_hash": params_hash,
        "category": category,
        "status": "active",
        "builder_state": builder_state,
        "source": "builder",
        "tags": ["builder_out"],
        "note": str(getattr(session, "objective", "") or "")[:400],
        "last_metrics_snapshot": best_metrics or None,
        "meta": {
            "session_id": session_id,
            "best_sharpe": getattr(session, "best_sharpe", None),
            "total_iterations": len(getattr(session, "iterations", []) or []),
        },
    }
    return upsert_entry(entry, path=path)
