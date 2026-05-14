"""Builder model statistics page backed by persisted autonomous Builder history."""

from __future__ import annotations

import io
import json
import math
import os
import threading
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd
import streamlit as st

from backtest.result_store import get_builder_sessions_dir
from ui.builder_runtime import build_unique_atomic_tmp_path

ROOT_DIR = Path(__file__).resolve().parent.parent
SANDBOX_ROOT = get_builder_sessions_dir()
_AUTONOMOUS_SUPERVISOR_STATE_FILE = SANDBOX_ROOT / "_autonomous_supervisor_state.json"
_MODEL_STATS_STATE_FILE = SANDBOX_ROOT / "_model_stats_state.json"
_MODEL_STATS_ARCHIVE_DIR = SANDBOX_ROOT / "_model_stats_archives"
_MODEL_STATS_VERSION = "1.0"
_MODEL_STATS_STATE_LOCK = threading.Lock()
_BUILDER_MODEL_PRIORITY_COLUMNS: tuple[str, ...] = (
    "model",
    "success_rate_pct",
    "negative_rate_pct",
    "failed_rate_pct",
    "sessions",
    "success_status",
    "negative_returns",
    "failed_status",
    "error_rate_pct",
    "error_status",
    "crash_rate_pct",
    "crash_status",
    "positive_rate_pct",
    "positive_returns",
    "flat_or_missing_returns",
    "max_iterations_status",
    "avg_return_pct",
    "median_return_pct",
    "best_return_pct",
    "worst_return_pct",
    "avg_sharpe",
    "median_sharpe",
    "best_sharpe",
    "avg_trades",
    "max_trades",
    "avg_session_duration_s",
    "avg_duration_s",
    "sessions_per_hour",
    "expected_return_per_hour_pct",
    "single_llm_sessions",
    "source_modes",
    "symbols",
    "timeframes",
    "first_session_num",
    "last_session_num",
    "first_session_id",
    "last_session_id",
)
_SESSION_PRIORITY_COLUMNS: tuple[str, ...] = (
    "session_num",
    "session_id",
    "status",
    "last_runtime_error_iteration",
    "last_runtime_error",
    "best_return_pct",
    "best_sharpe",
    "best_telemetry_score",
    "best_trades",
    "symbol",
    "timeframe",
    "source_mode",
    "orchestration_mode",
    "builder_model",
    "session_duration_seconds",
    "start_time",
    "end_time",
    "objective",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _default_active_window() -> dict[str, Any]:
    return {
        "reset_at": "",
        "last_reset_session_num": 0,
        "last_reset_history_len": 0,
        "last_archive_id": "",
    }


def _default_model_stats_state() -> dict[str, Any]:
    return {
        "version": _MODEL_STATS_VERSION,
        "updated_at": "",
        "active_window": _default_active_window(),
        "archives": [],
    }


def _sanitize_model_stats_state(payload: Any) -> dict[str, Any]:
    state = _default_model_stats_state()
    if not isinstance(payload, dict):
        return state

    state["version"] = str(payload.get("version") or state["version"])
    state["updated_at"] = str(payload.get("updated_at") or state["updated_at"])

    active_window = payload.get("active_window")
    if isinstance(active_window, dict):
        sanitized_window = _default_active_window()
        for key in sanitized_window.keys():
            if key in active_window:
                sanitized_window[key] = active_window[key]
        state["active_window"] = sanitized_window

    archives = payload.get("archives")
    if isinstance(archives, list):
        state["archives"] = [item for item in archives if isinstance(item, dict)]

    return state


def _write_json_atomically(target_path: Path, payload: dict[str, Any]) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False, default=str)

    with _MODEL_STATS_STATE_LOCK:
        tmp_path = build_unique_atomic_tmp_path(target_path)
        try:
            tmp_path.write_text(serialized, encoding="utf-8")
            os.replace(tmp_path, target_path)
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass


def load_autonomous_history(
    state_path: Path = _AUTONOMOUS_SUPERVISOR_STATE_FILE,
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    history = payload.get("history")
    if not isinstance(history, list):
        return []
    return [entry for entry in history if isinstance(entry, dict)]


def load_model_stats_state(
    state_path: Path = _MODEL_STATS_STATE_FILE,
) -> dict[str, Any]:
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return _default_model_stats_state()
    return _sanitize_model_stats_state(payload)


def save_model_stats_state(
    state: dict[str, Any],
    *,
    state_path: Path = _MODEL_STATS_STATE_FILE,
) -> dict[str, Any]:
    sanitized = _sanitize_model_stats_state(state)
    sanitized["updated_at"] = _utc_now_iso()
    _write_json_atomically(state_path, sanitized)
    return sanitized


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    return parsed if math.isfinite(parsed) else None


def _normalize_model_label(value: Any, *, fallback: str = "(inconnu)") -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


def _normalize_text_label(value: Any, *, fallback: str = "-") -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


def _round_or_none(value: float | None, ndigits: int = 2) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, ndigits)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _duration_from_record_payload(payload: dict[str, Any]) -> float | None:
    for key in ("session_duration_seconds", "duration_seconds", "duration"):
        duration = _safe_float(payload.get(key))
        if duration is not None and duration >= 0:
            return duration

    start_dt = _parse_datetime(payload.get("start_time") or payload.get("started_at"))
    end_dt = _parse_datetime(payload.get("end_time") or payload.get("finished_at"))
    if start_dt is None or end_dt is None:
        return None
    duration = (end_dt - start_dt).total_seconds()
    return duration if duration >= 0 and math.isfinite(duration) else None


def _ordered_builder_model_columns(columns: Sequence[str]) -> list[str]:
    ordered = [column for column in _BUILDER_MODEL_PRIORITY_COLUMNS if column in columns]
    trailing = [column for column in columns if column not in ordered]
    return ordered + trailing


def _reorder_builder_model_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "model" not in frame.columns:
        return frame
    return frame.loc[:, _ordered_builder_model_columns(list(frame.columns))]


def _ordered_session_columns(columns: Sequence[str]) -> list[str]:
    ordered = [column for column in _SESSION_PRIORITY_COLUMNS if column in columns]
    trailing = [column for column in columns if column not in ordered]
    return ordered + trailing


def _reorder_session_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "session_num" not in frame.columns:
        return frame
    ordered_columns = [
        column for column in _ordered_session_columns(list(frame.columns)) if column != "last_runtime_traceback_tail"
    ]
    return frame.loc[:, ordered_columns]


def _load_session_summary(summary_path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _extract_last_runtime_feedback_from_summary(
    summary: dict[str, Any],
) -> dict[str, Any]:
    runtime_error = str(summary.get("last_runtime_error") or "").strip()
    runtime_traceback_tail = str(
        summary.get("last_runtime_traceback_tail") or "",
    ).strip()
    runtime_iteration = _safe_int(summary.get("last_runtime_error_iteration"), 0)
    if runtime_error or runtime_traceback_tail:
        return {
            "last_runtime_error": runtime_error or None,
            "last_runtime_error_iteration": runtime_iteration or None,
            "last_runtime_traceback_tail": runtime_traceback_tail or None,
        }

    raw_iterations = summary.get("iterations", [])
    iterations = raw_iterations if isinstance(raw_iterations, list) else []
    for row in reversed(iterations):
        if not isinstance(row, dict):
            continue
        phase_feedback = row.get("phase_feedback")
        if not isinstance(phase_feedback, dict):
            continue
        backtest_feedback = phase_feedback.get("backtest")
        if not isinstance(backtest_feedback, dict):
            continue
        runtime_error = str(backtest_feedback.get("runtime_error") or "").strip()
        runtime_traceback_tail = str(
            backtest_feedback.get("runtime_traceback_tail") or "",
        ).strip()
        if runtime_error or runtime_traceback_tail:
            return {
                "last_runtime_error": runtime_error or None,
                "last_runtime_error_iteration": _safe_int(row.get("iteration"), 0) or None,
                "last_runtime_traceback_tail": runtime_traceback_tail or None,
            }

    return {
        "last_runtime_error": None,
        "last_runtime_error_iteration": None,
        "last_runtime_traceback_tail": None,
    }


def _resolve_entry_runtime_feedback(
    entry: dict[str, Any],
    *,
    summary_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    runtime_error = str(entry.get("last_runtime_error") or "").strip()
    runtime_traceback_tail = str(entry.get("last_runtime_traceback_tail") or "").strip()
    runtime_iteration = _safe_int(entry.get("last_runtime_error_iteration"), 0)
    if runtime_error or runtime_traceback_tail or runtime_iteration > 0:
        return {
            "last_runtime_error": runtime_error or None,
            "last_runtime_error_iteration": runtime_iteration or None,
            "last_runtime_traceback_tail": runtime_traceback_tail or None,
        }

    session_id = str(entry.get("session_id") or "").strip()
    if not session_id:
        return {
            "last_runtime_error": None,
            "last_runtime_error_iteration": None,
            "last_runtime_traceback_tail": None,
        }

    cache = summary_cache if isinstance(summary_cache, dict) else {}
    if session_id in cache:
        return dict(cache[session_id])

    summary_path = SANDBOX_ROOT / session_id / "session_summary.json"
    summary = _load_session_summary(summary_path) if summary_path.exists() else None
    resolved = (
        _extract_last_runtime_feedback_from_summary(summary)
        if isinstance(summary, dict)
        else {
            "last_runtime_error": None,
            "last_runtime_error_iteration": None,
            "last_runtime_traceback_tail": None,
        }
    )
    cache[session_id] = dict(resolved)
    return resolved


def _mean_or_none(values: Sequence[float], ndigits: int = 2) -> float | None:
    if not values:
        return None
    return _round_or_none(sum(values) / len(values), ndigits)


def _median_or_none(values: Sequence[float], ndigits: int = 2) -> float | None:
    if not values:
        return None
    return _round_or_none(float(median(values)), ndigits)


def _latest_session_num(history: Iterable[dict[str, Any]]) -> int:
    latest = 0
    for entry in history:
        latest = max(latest, _safe_int(entry.get("session_num"), 0))
    return latest


def _extract_active_entries(
    history: list[dict[str, Any]],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    active_window = state.get("active_window") if isinstance(state, dict) else {}
    baseline = 0
    if isinstance(active_window, dict):
        baseline = _safe_int(active_window.get("last_reset_session_num"), 0)
    if baseline <= 0:
        return list(history or [])
    return [entry for entry in list(history or []) if _safe_int(entry.get("session_num"), 0) > baseline]


def _build_record(entry: dict[str, Any], *, model: str) -> dict[str, Any]:
    instrumentation_summary = (
        dict(entry.get("instrumentation_summary", {}) or {})
        if isinstance(entry.get("instrumentation_summary"), dict)
        else {}
    )
    start_time = _normalize_text_label(entry.get("start_time") or entry.get("started_at"), fallback="")
    end_time = _normalize_text_label(entry.get("end_time") or entry.get("finished_at"), fallback="")
    session_duration_seconds = _duration_from_record_payload(entry)
    return {
        "model": _normalize_model_label(model),
        "session_num": _safe_int(entry.get("session_num"), 0),
        "session_id": _normalize_text_label(entry.get("session_id"), fallback=""),
        "status": _normalize_text_label(entry.get("status"), fallback="inconnu").lower(),
        "best_return": _safe_float(entry.get("best_return")),
        "best_sharpe": _safe_float(entry.get("best_sharpe")),
        "best_trades": _safe_float(entry.get("best_trades")),
        "duration": session_duration_seconds,
        "session_duration_seconds": session_duration_seconds,
        "start_time": start_time,
        "end_time": end_time,
        "symbol": _normalize_text_label(entry.get("symbol")),
        "timeframe": _normalize_text_label(entry.get("timeframe")),
        "source_mode": _normalize_text_label(entry.get("source_mode")),
        "builder_execution_mode": _normalize_text_label(entry.get("builder_execution_mode")),
        "orchestration_mode": _normalize_text_label(entry.get("orchestration_mode")),
        "instrumentation_enabled": bool(entry.get("instrumentation_enabled", False)),
        "trace_fallback_rate": _safe_float(instrumentation_summary.get("fallback_rate")),
        "trace_repair_rate": _safe_float(instrumentation_summary.get("repair_rate")),
        "objective": _normalize_text_label(entry.get("objective"), fallback=""),
    }


def extract_builder_model_records(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _build_record(entry, model=entry.get("model_name"))
        for entry in list(history or [])
        if isinstance(entry, dict)
    ]


def _compact_session_rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    runtime_feedback_cache: dict[str, dict[str, Any]] = {}
    for entry in list(entries or []):
        if not isinstance(entry, dict):
            continue
        runtime_feedback = _resolve_entry_runtime_feedback(
            entry,
            summary_cache=runtime_feedback_cache,
        )
        start_time = _normalize_text_label(entry.get("start_time") or entry.get("started_at"), fallback="")
        end_time = _normalize_text_label(entry.get("end_time") or entry.get("finished_at"), fallback="")
        rows.append(
            {
                "session_num": _safe_int(entry.get("session_num"), 0),
                "session_id": _normalize_text_label(entry.get("session_id"), fallback=""),
                "status": _normalize_text_label(entry.get("status"), fallback="inconnu"),
                "last_runtime_error_iteration": runtime_feedback.get("last_runtime_error_iteration"),
                "last_runtime_error": runtime_feedback.get("last_runtime_error"),
                "best_return_pct": _safe_float(entry.get("best_return")),
                "best_sharpe": _safe_float(entry.get("best_sharpe")),
                "best_telemetry_score": _safe_float(
                    entry.get("best_telemetry_score", entry.get("best_score")),
                ),
                "best_trades": _safe_float(entry.get("best_trades")),
                "symbol": _normalize_text_label(entry.get("symbol")),
                "timeframe": _normalize_text_label(entry.get("timeframe")),
                "source_mode": _normalize_text_label(entry.get("source_mode")),
                "orchestration_mode": _normalize_text_label(entry.get("orchestration_mode")),
                "builder_model": _normalize_model_label(entry.get("model_name")),
                "session_duration_seconds": _duration_from_record_payload(entry),
                "start_time": start_time,
                "end_time": end_time,
                "objective": _normalize_text_label(entry.get("objective"), fallback=""),
                "last_runtime_traceback_tail": runtime_feedback.get("last_runtime_traceback_tail"),
            },
        )
    rows.sort(
        key=lambda row: (row.get("session_num") or 0, row.get("session_id") or ""),
        reverse=True,
    )
    return rows


def aggregate_model_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}

    for record in list(records or []):
        model = _normalize_model_label(record.get("model"))
        bucket = buckets.setdefault(
            model,
            {
                "count": 0,
                "status_counts": Counter(),
                "positive": 0,
                "negative": 0,
                "flat_or_missing": 0,
                "returns": [],
                "sharpes": [],
                "trades": [],
                "durations": [],
                "single_llm": 0,
                "source_modes": set(),
                "symbols": set(),
                "timeframes": set(),
                "first_session_num": None,
                "last_session_num": None,
                "first_session_id": "",
                "last_session_id": "",
            },
        )

        bucket["count"] += 1
        status = _normalize_text_label(record.get("status"), fallback="inconnu").lower()
        bucket["status_counts"][status] += 1

        session_num = _safe_int(record.get("session_num"), 0)
        session_id = _normalize_text_label(record.get("session_id"), fallback="")
        if bucket["first_session_num"] is None or (session_num and session_num < bucket["first_session_num"]):
            bucket["first_session_num"] = session_num
            bucket["first_session_id"] = session_id
        if bucket["last_session_num"] is None or session_num >= bucket["last_session_num"]:
            bucket["last_session_num"] = session_num
            bucket["last_session_id"] = session_id

        best_return = _safe_float(record.get("best_return"))
        if best_return is None:
            bucket["flat_or_missing"] += 1
        elif best_return > 0:
            bucket["positive"] += 1
            bucket["returns"].append(best_return)
        elif best_return < 0:
            bucket["negative"] += 1
            bucket["returns"].append(best_return)
        else:
            bucket["flat_or_missing"] += 1
            bucket["returns"].append(best_return)

        best_sharpe = _safe_float(record.get("best_sharpe"))
        if best_sharpe is not None:
            bucket["sharpes"].append(best_sharpe)

        best_trades = _safe_float(record.get("best_trades"))
        if best_trades is not None:
            bucket["trades"].append(best_trades)

        duration = _safe_float(record.get("duration"))
        if duration is not None:
            bucket["durations"].append(duration)

        orchestration_mode = _normalize_text_label(record.get("orchestration_mode"))
        if orchestration_mode == "single_llm":
            bucket["single_llm"] += 1

        bucket["source_modes"].add(_normalize_text_label(record.get("source_mode")))
        bucket["symbols"].add(_normalize_text_label(record.get("symbol")))
        bucket["timeframes"].add(_normalize_text_label(record.get("timeframe")))

    rows: list[dict[str, Any]] = []
    for model, bucket in buckets.items():
        total = int(bucket["count"])
        avg_return_pct = _mean_or_none(bucket["returns"], 2)
        avg_duration_s = _mean_or_none(bucket["durations"], 1)
        positive_rate_pct = _round_or_none((bucket["positive"] / total) * 100.0, 2) if total else None
        sessions_per_hour = (
            _round_or_none(3600.0 / avg_duration_s, 3)
            if avg_duration_s is not None and avg_duration_s > 0
            else None
        )
        expected_return_per_hour_pct = (
            _round_or_none(avg_return_pct * sessions_per_hour * (positive_rate_pct / 100.0), 2)
            if avg_return_pct is not None and sessions_per_hour is not None and positive_rate_pct is not None
            else None
        )
        rows.append(
            {
                "model": model,
                "sessions": total,
                "positive_returns": int(bucket["positive"]),
                "negative_returns": int(bucket["negative"]),
                "flat_or_missing_returns": int(bucket["flat_or_missing"]),
                "success_status": int(bucket["status_counts"].get("success", 0)),
                "failed_status": int(bucket["status_counts"].get("failed", 0)),
                "max_iterations_status": int(bucket["status_counts"].get("max_iterations", 0)),
                "error_status": int(bucket["status_counts"].get("error", 0)),
                "crash_status": int(bucket["status_counts"].get("crash", 0)),
                "positive_rate_pct": positive_rate_pct,
                "negative_rate_pct": _round_or_none((bucket["negative"] / total) * 100.0, 2) if total else None,
                "success_rate_pct": _round_or_none(
                    (bucket["status_counts"].get("success", 0) / total) * 100.0,
                    2,
                )
                if total
                else None,
                "failed_rate_pct": _round_or_none(
                    (bucket["status_counts"].get("failed", 0) / total) * 100.0,
                    2,
                )
                if total
                else None,
                "error_rate_pct": _round_or_none(
                    (bucket["status_counts"].get("error", 0) / total) * 100.0,
                    2,
                )
                if total
                else None,
                "crash_rate_pct": _round_or_none(
                    (bucket["status_counts"].get("crash", 0) / total) * 100.0,
                    2,
                )
                if total
                else None,
                "avg_return_pct": avg_return_pct,
                "median_return_pct": _median_or_none(bucket["returns"], 2),
                "best_return_pct": _round_or_none(max(bucket["returns"]), 2) if bucket["returns"] else None,
                "worst_return_pct": _round_or_none(min(bucket["returns"]), 2) if bucket["returns"] else None,
                "avg_sharpe": _mean_or_none(bucket["sharpes"], 3),
                "median_sharpe": _median_or_none(bucket["sharpes"], 3),
                "best_sharpe": _round_or_none(max(bucket["sharpes"]), 3) if bucket["sharpes"] else None,
                "avg_trades": _mean_or_none(bucket["trades"], 1),
                "max_trades": _round_or_none(max(bucket["trades"]), 1) if bucket["trades"] else None,
                "avg_session_duration_s": avg_duration_s,
                "avg_duration_s": avg_duration_s,
                "sessions_per_hour": sessions_per_hour,
                "expected_return_per_hour_pct": expected_return_per_hour_pct,
                "single_llm_sessions": int(bucket["single_llm"]),
                "source_modes": ", ".join(sorted(bucket["source_modes"])) or "-",
                "symbols": ", ".join(sorted(bucket["symbols"])) or "-",
                "timeframes": ", ".join(sorted(bucket["timeframes"])) or "-",
                "first_session_num": bucket["first_session_num"],
                "last_session_num": bucket["last_session_num"],
                "first_session_id": bucket["first_session_id"],
                "last_session_id": bucket["last_session_id"],
            },
        )

    rows.sort(
        key=lambda row: (
            -(1 if row.get("expected_return_per_hour_pct") is not None else 0),
            -(float(row.get("expected_return_per_hour_pct") or 0.0)),
            -(1 if row.get("sessions_per_hour") is not None else 0),
            -_safe_int(row.get("positive_returns"), 0),
            -(1 if row.get("avg_return_pct") is not None else 0),
            -(float(row.get("avg_return_pct") or 0.0)),
            -_safe_int(row.get("sessions"), 0),
            str(row.get("model", "") or ""),
        ),
    )
    return rows


def summarize_window(entries: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(
        _normalize_text_label(entry.get("status"), fallback="inconnu").lower()
        for entry in list(entries or [])
        if isinstance(entry, dict)
    )

    positive_returns = 0
    negative_returns = 0
    flat_or_missing_returns = 0
    distinct_builder_models = set()
    single_llm_sessions = 0
    instrumented_sessions = 0
    fallback_rates: list[float] = []
    repair_rates: list[float] = []

    for entry in list(entries or []):
        if not isinstance(entry, dict):
            continue
        distinct_builder_models.add(_normalize_model_label(entry.get("model_name")))
        best_return = _safe_float(entry.get("best_return"))
        if best_return is None:
            flat_or_missing_returns += 1
        elif best_return > 0:
            positive_returns += 1
        elif best_return < 0:
            negative_returns += 1
        else:
            flat_or_missing_returns += 1

        orchestration_mode = _normalize_text_label(entry.get("orchestration_mode"))
        if orchestration_mode == "single_llm":
            single_llm_sessions += 1
        if bool(entry.get("instrumentation_enabled", False)):
            instrumented_sessions += 1
            instrumentation_summary = entry.get("instrumentation_summary", {})
            if isinstance(instrumentation_summary, dict):
                fallback_rate = _safe_float(instrumentation_summary.get("fallback_rate"))
                repair_rate = _safe_float(instrumentation_summary.get("repair_rate"))
                if fallback_rate is not None:
                    fallback_rates.append(fallback_rate)
                if repair_rate is not None:
                    repair_rates.append(repair_rate)

    return {
        "sessions": len(entries or []),
        "distinct_builder_models": len(distinct_builder_models),
        "positive_returns": positive_returns,
        "negative_returns": negative_returns,
        "flat_or_missing_returns": flat_or_missing_returns,
        "success_status": int(status_counts.get("success", 0)),
        "failed_status": int(status_counts.get("failed", 0)),
        "max_iterations_status": int(status_counts.get("max_iterations", 0)),
        "error_status": int(status_counts.get("error", 0)),
        "crash_status": int(status_counts.get("crash", 0)),
        "single_llm_sessions": single_llm_sessions,
        "instrumented_sessions": instrumented_sessions,
        "avg_trace_fallback_rate": _mean_or_none(fallback_rates, 4),
        "avg_trace_repair_rate": _mean_or_none(repair_rates, 4),
        "latest_session_num": _latest_session_num(entries),
    }


def build_model_stats_report(
    history: list[dict[str, Any]],
    *,
    state: dict[str, Any] | None = None,
    scope: str = "active",
) -> dict[str, Any]:
    sanitized_state = _sanitize_model_stats_state(state or _default_model_stats_state())
    active_entries = _extract_active_entries(history, sanitized_state)
    target_entries = active_entries if scope == "active" else list(history or [])
    builder_records = extract_builder_model_records(target_entries)

    return {
        "scope": scope,
        "state": sanitized_state,
        "entries": target_entries,
        "active_entries": active_entries,
        "overview": summarize_window(target_entries),
        "builder_rows": aggregate_model_records(builder_records),
        "session_rows": _compact_session_rows(target_entries),
    }


def _archive_meta_from_report(
    report: dict[str, Any],
    *,
    archive_id: str,
    archived_at: str,
    note: str,
    archive_path: Path,
) -> dict[str, Any]:
    overview = report.get("overview", {}) if isinstance(report, dict) else {}
    entries = report.get("entries", []) if isinstance(report, dict) else []
    first_session_num = min((_safe_int(item.get("session_num"), 0) for item in entries), default=0)
    last_session_num = max((_safe_int(item.get("session_num"), 0) for item in entries), default=0)
    try:
        stored_path = str(archive_path.relative_to(ROOT_DIR))
    except ValueError:
        stored_path = str(archive_path)
    return {
        "id": archive_id,
        "created_at": archived_at,
        "note": note,
        "sessions": int(overview.get("sessions", 0) or 0),
        "distinct_builder_models": int(overview.get("distinct_builder_models", 0) or 0),
        "positive_returns": int(overview.get("positive_returns", 0) or 0),
        "negative_returns": int(overview.get("negative_returns", 0) or 0),
        "max_iterations_status": int(overview.get("max_iterations_status", 0) or 0),
        "error_status": int(overview.get("error_status", 0) or 0),
        "crash_status": int(overview.get("crash_status", 0) or 0),
        "window_first_session_num": first_session_num,
        "window_last_session_num": last_session_num,
        "path": stored_path,
    }


def archive_active_window(
    history: list[dict[str, Any]],
    *,
    state: dict[str, Any] | None = None,
    note: str = "",
    state_path: Path = _MODEL_STATS_STATE_FILE,
    archive_dir: Path = _MODEL_STATS_ARCHIVE_DIR,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    sanitized_state = _sanitize_model_stats_state(state or _default_model_stats_state())
    report = build_model_stats_report(history, state=sanitized_state, scope="active")
    active_entries = report.get("entries", []) or []
    if not active_entries:
        return sanitized_state, None

    archived_at = _utc_now_iso()
    latest_session_num = _latest_session_num(history)
    archive_id = f"builder_model_stats_{archived_at.replace(':', '-').replace('+00:00', 'Z')}_{latest_session_num}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{archive_id}.json"

    archive_payload = {
        "version": _MODEL_STATS_VERSION,
        "archived_at": archived_at,
        "note": note.strip(),
        "active_window_before_reset": dict(sanitized_state.get("active_window") or {}),
        "overview": dict(report.get("overview", {}) or {}),
        "builder_model_rows": list(report.get("builder_rows", []) or []),
        "sessions": list(report.get("session_rows", []) or []),
    }
    _write_json_atomically(archive_path, archive_payload)

    archive_meta = _archive_meta_from_report(
        report,
        archive_id=archive_id,
        archived_at=archived_at,
        note=note.strip(),
        archive_path=archive_path,
    )

    updated_state = _sanitize_model_stats_state(sanitized_state)
    updated_state["archives"] = [archive_meta, *list(updated_state.get("archives", []) or [])]
    updated_state["active_window"] = {
        "reset_at": archived_at,
        "last_reset_session_num": latest_session_num,
        "last_reset_history_len": len(history or []),
        "last_archive_id": archive_id,
    }
    saved_state = save_model_stats_state(updated_state, state_path=state_path)
    return saved_state, archive_meta


def load_archive_payload(
    archive_meta: dict[str, Any],
    *,
    root_dir: Path = ROOT_DIR,
) -> dict[str, Any]:
    archive_path = root_dir / str(archive_meta.get("path") or "")
    try:
        return json.loads(archive_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _rows_to_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    frame = pd.DataFrame(rows)
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue()


def _format_reset_caption(state: dict[str, Any]) -> str:
    active_window = state.get("active_window") or {}
    reset_at = str(active_window.get("reset_at") or "").strip()
    reset_session_num = _safe_int(active_window.get("last_reset_session_num"), 0)
    if not reset_at and reset_session_num <= 0:
        return "Fenêtre active : depuis le début de l'historique Builder persistant."
    pieces = ["Fenêtre active"]
    if reset_at:
        pieces.append(f"reset le {reset_at}")
    if reset_session_num > 0:
        pieces.append(f"sessions strictement après #{reset_session_num}")
    return " | ".join(pieces)


def _render_overview_cards(overview: dict[str, Any], *, archives_count: int) -> None:
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("Sessions", int(overview.get("sessions", 0) or 0))
    with col2:
        st.metric("Modèles builder", int(overview.get("distinct_builder_models", 0) or 0))
    with col3:
        st.metric("Returns +", int(overview.get("positive_returns", 0) or 0))
    with col4:
        st.metric("Returns -", int(overview.get("negative_returns", 0) or 0))
    with col5:
        st.metric("Max itérations", int(overview.get("max_iterations_status", 0) or 0))
    with col6:
        st.metric("Archives", archives_count)

    col7, col8, col9, col10 = st.columns(4)
    with col7:
        st.metric("Success", int(overview.get("success_status", 0) or 0))
    with col8:
        st.metric("Failed", int(overview.get("failed_status", 0) or 0))
    with col9:
        st.metric("Errors", int(overview.get("error_status", 0) or 0))
    with col10:
        st.metric("Crash", int(overview.get("crash_status", 0) or 0))

    col11, col12, col13, col14 = st.columns(4)
    with col11:
        st.metric("Sessions tracées", int(overview.get("instrumented_sessions", 0) or 0))
    with col12:
        st.metric("Mono", int(overview.get("single_llm_sessions", 0) or 0))
    with col13:
        st.metric("Modèles", int(overview.get("distinct_builder_models", 0) or 0))
    with col14:
        fallback_rate = _safe_float(overview.get("avg_trace_fallback_rate"))
        repair_rate = _safe_float(overview.get("avg_trace_repair_rate"))
        summary = "n/a"
        if fallback_rate is not None or repair_rate is not None:
            summary = f"fb {float(fallback_rate or 0.0) * 100:.1f}% | rep {float(repair_rate or 0.0) * 100:.1f}%"
        st.metric("Flux moyen", summary)


def _render_table_section(
    *,
    title: str,
    rows: list[dict[str, Any]],
    csv_name: str,
    empty_message: str,
) -> None:
    st.markdown(f"### {title}")
    if not rows:
        st.info(empty_message)
        return

    frame = pd.DataFrame(rows)
    if title == "Builder models":
        frame = _reorder_builder_model_frame(frame)
    elif title == "Sessions Builder brutes":
        frame = _reorder_session_frame(frame)
    st.dataframe(frame, width="stretch", hide_index=True)
    st.download_button(
        f"⬇️ Export CSV - {title}",
        data=_rows_to_csv(rows if title == "Sessions Builder brutes" else frame.to_dict(orient="records")),
        file_name=csv_name,
        mime="text/csv",
        key=f"download_{csv_name}",
    )


def _render_session_runtime_error_panel(rows: list[dict[str, Any]]) -> None:
    persisted_errors = [
        row
        for row in list(rows or [])
        if str(row.get("last_runtime_error") or "").strip() or str(row.get("last_runtime_traceback_tail") or "").strip()
    ]
    st.markdown("#### Dernier runtime error persisté")
    if not persisted_errors:
        st.info("Aucun runtime error persisté dans ce périmètre pour le moment.")
        return

    selected_row = st.selectbox(
        "Session à inspecter",
        options=persisted_errors,
        format_func=lambda row: (
            f"#{_safe_int(row.get('session_num'), 0)} | "
            f"{_normalize_model_label(row.get('builder_model'))} | "
            f"{_normalize_text_label(row.get('status'), fallback='inconnu')}"
            + (
                f" | iter {_safe_int(row.get('last_runtime_error_iteration'), 0)}"
                if _safe_int(row.get("last_runtime_error_iteration"), 0) > 0
                else ""
            )
        ),
        key="builder_model_stats_runtime_error_select",
    )
    st.caption(
        "Erreur relue depuis l'historique autonome persistant, avec fallback sur "
        "`session_summary.json` de la session correspondante.",
    )
    if selected_row.get("last_runtime_error"):
        st.code(str(selected_row.get("last_runtime_error")), language="text")
    if selected_row.get("last_runtime_traceback_tail"):
        st.code(str(selected_row.get("last_runtime_traceback_tail")), language="text")


def _render_archives_section(state: dict[str, Any]) -> None:
    archives = list(state.get("archives", []) or [])
    st.markdown("### Archives de statistiques")
    if not archives:
        st.info("Aucune archive pour le moment. Utilisez le reset pour figer une fenêtre et repartir à zéro.")
        return

    archive_frame = pd.DataFrame(archives)
    st.dataframe(archive_frame, width="stretch", hide_index=True)

    selected_archive = st.selectbox(
        "Archive à inspecter",
        options=archives,
        format_func=lambda item: (
            f"{item.get('created_at', '')} | "
            f"{item.get('sessions', 0)} sessions | "
            f"{item.get('id', '')}" + (f" | {item.get('note')}" if item.get("note") else "")
        ),
        key="builder_model_stats_archive_select",
    )
    archive_payload = load_archive_payload(selected_archive)
    if not archive_payload:
        st.warning("Impossible de relire cette archive.")
        return

    st.caption(
        "Archive sélectionnée : " + (str(selected_archive.get("path") or "").strip() or "(chemin indisponible)"),
    )

    json_payload = json.dumps(archive_payload, indent=2, ensure_ascii=False)
    archive_builder_rows = list(archive_payload.get("builder_model_rows", []) or [])
    archive_builder_frame = _reorder_builder_model_frame(pd.DataFrame(archive_builder_rows))
    col_download_json, col_download_csv = st.columns(2)
    with col_download_json:
        st.download_button(
            "⬇️ Télécharger l'archive JSON",
            data=json_payload,
            file_name=f"{selected_archive.get('id', 'builder_model_stats_archive')}.json",
            mime="application/json",
            key="builder_model_stats_archive_json_download",
        )
    with col_download_csv:
        st.download_button(
            "⬇️ Export CSV builder",
            data=_rows_to_csv(archive_builder_frame.to_dict(orient="records")),
            file_name=f"{selected_archive.get('id', 'builder_model_stats_archive')}_builder.csv",
            mime="text/csv",
            key="builder_model_stats_archive_csv_download",
        )

    if archive_builder_rows:
        st.markdown("#### Builder models archivés")
        st.dataframe(archive_builder_frame, width="stretch", hide_index=True)


def _consume_pending_archive_notice() -> dict[str, Any] | None:
    pending_notice = st.session_state.pop(
        "builder_model_stats_pending_archive_notice",
        None,
    )
    clear_note = bool(
        st.session_state.pop("builder_model_stats_clear_archive_note", False),
    )
    if clear_note:
        st.session_state["builder_model_stats_archive_note"] = ""
    return pending_notice if isinstance(pending_notice, dict) else None


def render_model_stats_page() -> None:
    st.title("📊 Statistiques des modèles")
    st.caption(
        "Périmètre strictement limité au mode Builder autonome et à son historique persistant.",
    )

    history = load_autonomous_history()
    state = load_model_stats_state()
    archives = list(state.get("archives", []) or [])

    st.info(
        f"Source actuelle : `{_AUTONOMOUS_SUPERVISOR_STATE_FILE}`."
        " Aucune donnée du mode optimisation LLM n'est agrégée ici.",
    )
    st.caption(_format_reset_caption(state))

    scope = st.radio(
        "Périmètre affiché",
        options=("active", "full"),
        format_func=lambda value: (
            "Fenêtre active (depuis le dernier reset)" if value == "active" else "Historique Builder persistant complet"
        ),
        horizontal=True,
        key="builder_model_stats_scope",
    )

    report = build_model_stats_report(history, state=state, scope=scope)
    overview = report.get("overview", {}) or {}
    _render_overview_cards(overview, archives_count=len(archives))

    st.markdown("---")
    st.markdown("## Gestion de la fenêtre active")
    pending_archive_notice = _consume_pending_archive_notice()
    if pending_archive_notice:
        st.success(
            "Archive créée : "
            f"{pending_archive_notice.get('id')} "
            f"({pending_archive_notice.get('sessions', 0)} sessions).",
        )
    note = st.text_input(
        "Note d'archive / contexte de reset",
        value="",
        key="builder_model_stats_archive_note",
        help="Exemple : refonte scoring, nouveau prompt Builder, changement du contrat de validation.",
    )
    st.caption(
        "Le reset archive la fenêtre active actuelle, puis redémarre les nouvelles stats Builder à partir du dernier numéro de session observé.",
    )
    if st.button(
        "🗃️ Archiver puis reset des statistiques Builder",
        type="secondary",
        disabled=not bool(report.get("active_entries")),
        key="builder_model_stats_archive_reset_btn",
    ):
        _updated_state, archive_meta = archive_active_window(
            history,
            state=state,
            note=note,
        )
        if archive_meta is None:
            st.info("Aucune session Builder active à archiver pour le moment.")
        else:
            st.session_state["builder_model_stats_pending_archive_notice"] = {
                "id": archive_meta.get("id", ""),
                "sessions": int(archive_meta.get("sessions", 0) or 0),
            }
            st.session_state["builder_model_stats_clear_archive_note"] = True
            st.rerun()

    tabs = st.tabs(["Builder models", "Sessions", "Archives"])

    with tabs[0]:
        _render_table_section(
            title="Builder models",
            rows=list(report.get("builder_rows", []) or []),
            csv_name="builder_model_stats.csv",
            empty_message="Aucune donnée Builder exploitable sur ce périmètre.",
        )

    with tabs[1]:
        session_rows = list(report.get("session_rows", []) or [])
        _render_table_section(
            title="Sessions Builder brutes",
            rows=session_rows,
            csv_name="builder_model_sessions.csv",
            empty_message="Aucune session Builder à afficher sur ce périmètre.",
        )
        _render_session_runtime_error_panel(session_rows)

    with tabs[2]:
        _render_archives_section(state)


__all__ = [
    "ROOT_DIR",
    "SANDBOX_ROOT",
    "_MODEL_STATS_ARCHIVE_DIR",
    "_MODEL_STATS_STATE_FILE",
    "_default_model_stats_state",
    "_extract_active_entries",
    "aggregate_model_records",
    "archive_active_window",
    "build_model_stats_report",
    "extract_builder_model_records",
    "load_archive_payload",
    "load_autonomous_history",
    "load_model_stats_state",
    "render_model_stats_page",
    "save_model_stats_state",
    "summarize_window",
]
