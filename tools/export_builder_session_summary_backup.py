"""Export Builder session summaries into a local analysis artifact.

The canonical source remains one ``session_summary.json`` per Builder session:

    <artifacts_root>/_builder_sessions/<session_id>/session_summary.json

This script keeps that one-record-per-session structure in a compressed NDJSON
file, writes a CSV manifest for quick inspection, and emits flat analytics
tables for cohort analysis without reparsing the gzip archive.

By default, exports are written outside the repository next to the local
backtest results. This avoids duplicating Builder session backups inside the
code workspace.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.result_store import get_builder_sessions_dir

DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "backtest_results" / "_builder_session_summary_exports"
ROBUST_CANONICAL_MIN_TRADES = 10
AUDIT_CLASSIFICATIONS = ("already_valid", "repairable", "still_invalid", "risky_repair", "missing_code")

COMPACT_TOP_LEVEL_KEYS = [
    "summary_schema_version",
    "session_id",
    "objective",
    "model_name",
    "status",
    "generation_stats",
    "best_sharpe",
    "best_telemetry_score",
    "best_score",
    "symbol",
    "timeframe",
    "n_bars",
    "date_range_start",
    "date_range_end",
    "initial_capital",
    "fees_bps",
    "slippage_bps",
    "universe_mode",
    "universe_purpose",
    "universe_strategy_type",
    "start_time",
    "end_time",
    "session_duration_seconds",
    "auto_reset_count",
    "total_iterations",
    "builder_execution_mode",
    "orchestration_mode",
    "instrumentation_enabled",
    "ablation_config",
    "last_runtime_error",
    "last_runtime_error_iteration",
    "git_commit",
    "git_branch",
    "git_dirty",
    "code_provenance",
]

COMPACT_ITERATION_KEYS = [
    "iteration",
    "timestamp",
    "session_elapsed_seconds",
    "hypothesis",
    "change_type",
    "diagnostic_category",
    "used_indicators",
    "error",
    "decision",
    "evaluation_mode",
    "params_used",
    "sweep_total_tested",
    "sweep_success",
    "sweep_failed",
    "sharpe",
    "total_pnl",
    "return_pct",
    "max_drawdown_pct",
    "profit_factor",
    "win_rate_pct",
    "trades",
    "telemetry_score",
    "continuous_score",
    "is_fallback",
]

COMPACT_LEADERBOARD_KEYS = [
    "rank",
    "iteration",
    "decision",
    "evaluation_mode",
    "sweep_total_tested",
    "sharpe",
    "return_pct",
    "max_drawdown_pct",
    "profit_factor",
    "win_rate_pct",
    "trades",
    "change_type",
    "diagnostic_category",
    "is_fallback",
    "error",
    "hypothesis",
]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object JSON in {path}")
    return payload


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_text_lf(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _has_session_summaries(path: Path) -> bool:
    try:
        return any(path.expanduser().glob("*/session_summary.json"))
    except OSError:
        return False


def _default_source_root() -> Path:
    configured = get_builder_sessions_dir()
    documents_fallback = Path.home() / "Documents" / "backtest_results" / "_builder_sessions"
    for candidate in (configured, documents_fallback):
        if _has_session_summaries(candidate):
            return candidate
    return configured


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _validate_export_target(
    *,
    source_root: Path,
    output_dir: Path,
    allow_repo_output: bool = False,
) -> None:
    repo_root = REPO_ROOT.resolve()
    source_root = source_root.resolve()
    output_dir = output_dir.resolve()

    if _path_is_relative_to(output_dir, source_root):
        raise ValueError(
            "Refus d'exporter dans la racine des sessions Builder. "
            f"source_root={source_root} output_dir={output_dir}",
        )

    if _path_is_relative_to(output_dir, repo_root) and not allow_repo_output:
        raise ValueError(
            "Refus d'exporter des sauvegardes de sessions Builder dans le dépôt. "
            "Utilisez un chemin hors workspace, par exemple "
            f"{DEFAULT_OUTPUT_DIR}. "
            "Si vous voulez vraiment produire un artefact repo ponctuel, passez --allow-repo-output.",
        )


def _relative_ref(source_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(source_root).as_posix()
    except ValueError:
        return path.name


def _select_keys(payload: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: payload.get(key) for key in keys if key in payload}


def _compact_summary_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact = _select_keys(payload, COMPACT_TOP_LEVEL_KEYS)
    iterations = payload.get("iterations", [])
    if isinstance(iterations, list):
        compact["iterations"] = [
            _select_keys(row, COMPACT_ITERATION_KEYS)
            for row in iterations
            if isinstance(row, dict)
        ]
    leaderboard = payload.get("leaderboard", [])
    if isinstance(leaderboard, list):
        compact["leaderboard"] = [
            _select_keys(row, COMPACT_LEADERBOARD_KEYS)
            for row in leaderboard
            if isinstance(row, dict)
        ]
    return compact


def _summary_row(
    path: Path,
    payload: dict[str, Any],
    digest: str,
    size_bytes: int,
    index: int,
    *,
    source_root: Path | None = None,
) -> dict[str, Any]:
    session_dir = path.parent
    session_id = str(payload.get("session_id") or session_dir.name)
    generation_stats = payload.get("generation_stats") if isinstance(payload.get("generation_stats"), dict) else {}
    return {
        "record_index": index,
        "session_id": session_id,
        "source_path": _relative_ref(source_root, path) if source_root is not None else str(path),
        "source_dir": _relative_ref(source_root, session_dir) if source_root is not None else str(session_dir),
        "sha256": digest,
        "size_bytes": size_bytes,
        "start_time": payload.get("start_time", ""),
        "end_time": payload.get("end_time", ""),
        "status": payload.get("status", ""),
        "model_name": payload.get("model_name", ""),
        "symbol": payload.get("symbol", ""),
        "timeframe": payload.get("timeframe", ""),
        "total_iterations": payload.get("total_iterations", ""),
        "canonical_rate": generation_stats.get("canonical_rate", ""),
        "best_sharpe": payload.get("best_sharpe", ""),
        "best_score": payload.get("best_score", ""),
        "git_commit": payload.get("git_commit", ""),
    }


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _iterations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("iterations", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _iteration_metric(row: dict[str, Any], key: str, *aliases: str) -> Any:
    for candidate in (key, *aliases):
        if candidate in row:
            return row.get(candidate)
    metrics = row.get("metrics")
    if isinstance(metrics, dict):
        for candidate in (key, *aliases):
            if candidate in metrics:
                return metrics.get(candidate)
    return None


def _iteration_flags(row: dict[str, Any], target_sharpe: float | None) -> dict[str, bool]:
    is_fallback = _as_bool(row.get("is_fallback"))
    trades = _as_int(_iteration_metric(row, "trades", "total_trades", "metrics_total_trades"))
    return_pct = _as_float(
        _iteration_metric(row, "return_pct", "total_return_pct", "metrics_total_return_pct"),
    )
    sharpe = _as_float(_iteration_metric(row, "sharpe", "sharpe_ratio", "metrics_sharpe_ratio"))
    target = 1.0 if target_sharpe is None else target_sharpe
    return {
        "is_canonical": not is_fallback,
        "zero_trades": (trades or 0) == 0,
        "positive_return": return_pct is not None and return_pct > 0.0,
        "positive_sharpe": sharpe is not None and sharpe > 0.0,
        "target_reached": sharpe is not None and sharpe >= target,
        "canonical_robust_candidate": (
            not is_fallback
            and (trades or 0) >= ROBUST_CANONICAL_MIN_TRADES
            and return_pct is not None
            and return_pct > 0.0
            and sharpe is not None
            and sharpe > 0.0
        ),
    }


def _fallback_cause(row: dict[str, Any]) -> tuple[str, str]:
    if not _as_bool(row.get("is_fallback")):
        return "", ""
    phase_feedback = row.get("phase_feedback")
    if not isinstance(phase_feedback, dict):
        return "unknown", "is_fallback_without_phase_feedback"
    proposal = phase_feedback.get("proposal") if isinstance(phase_feedback.get("proposal"), dict) else {}
    code = phase_feedback.get("code") if isinstance(phase_feedback.get("code"), dict) else {}
    backtest = phase_feedback.get("backtest") if isinstance(phase_feedback.get("backtest"), dict) else {}
    if proposal.get("fallback_deterministic_used") or proposal.get("source") == "deterministic_fallback":
        reason_payload = (
            proposal.get("contract_retry_issues")
            or proposal.get("issues_after_retry")
            or proposal.get("issues")
            or proposal.get("error_code")
            or proposal.get("source")
            or "deterministic_fallback"
        )
        if isinstance(reason_payload, list):
            reason = "; ".join(str(item) for item in reason_payload[:5])
        else:
            reason = str(reason_payload)
        return "proposal", reason
    if code.get("fallback_deterministic_used") or code.get("source") == "deterministic_fallback":
        reason = str(
            code.get("validation_error_retry")
            or code.get("validation_error")
            or code.get("source")
            or "deterministic_fallback",
        )
        return "code", reason
    if backtest.get("runtime_fix_fallback_deterministic_used"):
        reason = str(
            backtest.get("runtime_fix_validation_error")
            or backtest.get("runtime_fix_retry_error")
            or backtest.get("runtime_error")
            or "runtime_fix_fallback",
        )
        return "runtime_fix", reason
    return "unknown", "fallback_marked_without_known_source"


def _session_analytics_row(
    path: Path,
    payload: dict[str, Any],
    digest: str,
    size_bytes: int,
    index: int,
    *,
    source_root: Path | None = None,
) -> dict[str, Any]:
    row = _summary_row(path, payload, digest, size_bytes, index, source_root=source_root)
    iterations = _iterations(payload)
    target_sharpe = _as_float(payload.get("target_sharpe"))
    fallback_count = 0
    zero_trade_count = 0
    robust_count = 0
    target_count = 0
    positive_return_count = 0
    positive_sharpe_count = 0
    diagnostic_counts: dict[str, int] = {}
    for iteration in iterations:
        flags = _iteration_flags(iteration, target_sharpe)
        fallback_count += int(not flags["is_canonical"])
        zero_trade_count += int(flags["zero_trades"])
        robust_count += int(flags["canonical_robust_candidate"])
        target_count += int(flags["target_reached"])
        positive_return_count += int(flags["is_canonical"] and flags["positive_return"])
        positive_sharpe_count += int(flags["is_canonical"] and flags["positive_sharpe"])
        diagnostic = str(iteration.get("diagnostic_category") or "").strip() or "empty"
        diagnostic_counts[diagnostic] = diagnostic_counts.get(diagnostic, 0) + 1

    row.update(
        {
            "summary_schema_version": payload.get("summary_schema_version", ""),
            "git_branch": payload.get("git_branch", ""),
            "git_dirty": payload.get("git_dirty", ""),
            "target_sharpe": payload.get("target_sharpe", ""),
            "n_bars": payload.get("n_bars", ""),
            "builder_execution_mode": payload.get("builder_execution_mode", ""),
            "orchestration_mode": payload.get("orchestration_mode", ""),
            "instrumentation_enabled": payload.get("instrumentation_enabled", ""),
            "fallback_iterations": fallback_count,
            "canonical_iterations": len(iterations) - fallback_count,
            "zero_trade_iterations": zero_trade_count,
            "canonical_positive_return_iterations": positive_return_count,
            "canonical_positive_sharpe_iterations": positive_sharpe_count,
            "target_reached_iterations": target_count,
            "canonical_robust_iterations": robust_count,
            "dominant_diagnostic": max(diagnostic_counts, key=diagnostic_counts.get) if diagnostic_counts else "",
        },
    )
    return row


def _iteration_analytics_rows(
    payload: dict[str, Any],
    record_index: int,
    session_id: str,
    source_path: str,
) -> list[dict[str, Any]]:
    target_sharpe = _as_float(payload.get("target_sharpe"))
    rows = []
    for index, iteration in enumerate(_iterations(payload), start=1):
        trades = _as_int(_iteration_metric(iteration, "trades", "total_trades", "metrics_total_trades"))
        return_pct = _as_float(
            _iteration_metric(iteration, "return_pct", "total_return_pct", "metrics_total_return_pct"),
        )
        sharpe = _as_float(_iteration_metric(iteration, "sharpe", "sharpe_ratio", "metrics_sharpe_ratio"))
        flags = _iteration_flags(iteration, target_sharpe)
        fallback_stage, fallback_reason = _fallback_cause(iteration)
        rows.append(
            {
                "record_index": record_index,
                "session_id": session_id,
                "source_path": source_path,
                "iteration_row_index": index,
                "iteration": iteration.get("iteration", index),
                "timestamp": iteration.get("timestamp", ""),
                "session_elapsed_seconds": iteration.get("session_elapsed_seconds", ""),
                "status": payload.get("status", ""),
                "model_name": payload.get("model_name", ""),
                "symbol": payload.get("symbol", ""),
                "timeframe": payload.get("timeframe", ""),
                "n_bars": payload.get("n_bars", ""),
                "git_commit": payload.get("git_commit", ""),
                "git_branch": payload.get("git_branch", ""),
                "builder_execution_mode": payload.get("builder_execution_mode", ""),
                "orchestration_mode": payload.get("orchestration_mode", ""),
                "evaluation_mode": iteration.get("evaluation_mode", ""),
                "decision": iteration.get("decision", ""),
                "change_type": iteration.get("change_type", ""),
                "diagnostic_category": iteration.get("diagnostic_category", ""),
                "is_fallback": not flags["is_canonical"],
                "is_canonical": flags["is_canonical"],
                "zero_trades": flags["zero_trades"],
                "positive_return": flags["positive_return"],
                "positive_sharpe": flags["positive_sharpe"],
                "target_reached": flags["target_reached"],
                "canonical_robust_candidate": flags["canonical_robust_candidate"],
                "fallback_stage": fallback_stage,
                "fallback_reason": fallback_reason,
                "trades": trades,
                "return_pct": return_pct,
                "sharpe": sharpe,
                "max_drawdown_pct": _as_float(
                    _iteration_metric(iteration, "max_drawdown_pct", "metrics_max_drawdown_pct"),
                ),
                "profit_factor": _as_float(_iteration_metric(iteration, "profit_factor", "metrics_profit_factor")),
                "win_rate_pct": _as_float(_iteration_metric(iteration, "win_rate_pct", "metrics_win_rate_pct")),
                "telemetry_score": _as_float(iteration.get("telemetry_score")),
                "used_indicators": json.dumps(iteration.get("used_indicators") or [], ensure_ascii=False),
                "error": iteration.get("error", ""),
            },
        )
    return rows


def _runtime_event_rows(
    payload: dict[str, Any],
    record_index: int,
    session_id: str,
    source_path: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for iteration in _iterations(payload):
        iteration_num = iteration.get("iteration", "")
        if iteration.get("error"):
            rows.append(
                {
                    "record_index": record_index,
                    "session_id": session_id,
                    "source_path": source_path,
                    "iteration": iteration_num,
                    "timestamp": iteration.get("timestamp", ""),
                    "event_kind": "iteration_error",
                    "phase": "",
                    "message": iteration.get("error", ""),
                    "payload_json": "",
                },
            )
        phase_feedback = iteration.get("phase_feedback")
        if not isinstance(phase_feedback, dict):
            continue
        for phase, feedback in phase_feedback.items():
            if not isinstance(feedback, dict):
                continue
            runtime_error = str(feedback.get("runtime_error") or "").strip()
            traceback_tail = str(feedback.get("runtime_traceback_tail") or "").strip()
            if runtime_error or traceback_tail:
                rows.append(
                    {
                        "record_index": record_index,
                        "session_id": session_id,
                        "source_path": source_path,
                        "iteration": iteration_num,
                        "timestamp": iteration.get("timestamp", ""),
                        "event_kind": "runtime_error",
                        "phase": phase,
                        "message": runtime_error,
                        "payload_json": json.dumps(
                            {
                                "runtime_error": runtime_error,
                                "runtime_traceback_tail": traceback_tail,
                            },
                            ensure_ascii=False,
                            default=str,
                        ),
                    },
                )
    return rows


def _strategy_code_path(session_dir: Path, iteration: Any) -> Path | None:
    iteration_num = _as_int(iteration)
    candidates: list[Path] = []
    if iteration_num is not None:
        candidates.extend(
            [
                session_dir / f"strategy_v{iteration_num:03d}.py",
                session_dir / f"strategy_v{iteration_num}.py",
            ],
        )
    candidates.append(session_dir / "strategy.py")
    return next((path for path in candidates if path.exists()), None)


def _mechanical_issue_kinds(code: str) -> list[str]:
    from agents.builder_code_repair import _INVALID_DICT_SUBKEY_REWRITE_HINTS

    text = str(code or "")
    issues: set[str] = set()
    if re.search(r"\b(?:parameters|default_params)\s*(?=\.get\s*\(|\[)", text):
        issues.add("param_source_alias")
    if re.search(r"^\s*signals(?:\.iloc)?\s*\[\s*(?:warmup\s*:\s*|:\s*)\]\s*=", text, flags=re.MULTILINE):
        issues.add("warmup_destructive")
    if re.search(r"\bmask_(?:long|short)\b", text):
        issues.add("mask_alias")
    if re.search(r"signals\s*\.loc\s*\[[^\]\n]+,\s*['\"](?:long|short)['\"]", text, flags=re.IGNORECASE):
        issues.add("signals_loc_2d")
    for indicator_name, subkey in _INVALID_DICT_SUBKEY_REWRITE_HINTS:
        if re.search(
            rf"indicators(?:\s*\[\s*['\"]{re.escape(indicator_name)}['\"]\s*\]|"
            rf"\.get\(\s*['\"]{re.escape(indicator_name)}['\"]\s*(?:,\s*[^)]*)?\))"
            rf"\s*\[\s*['\"]{re.escape(subkey)}['\"]\s*\]",
            text,
            flags=re.IGNORECASE,
        ):
            issues.add("invalid_dict_subkey")
            break
    try:
        compile(text, "<builder-code-audit>", "exec")
    except SyntaxError as exc:
        if "expected an indented block" in str(getattr(exc, "msg", "") or "").lower():
            issues.add("empty_block")
    return sorted(issues)


def _classify_repair_audit(
    *,
    code_path: Path | None,
    code: str,
    valid_before: bool,
    valid_after: bool,
    changed: bool,
) -> str:
    if code_path is None or not code:
        return "missing_code"
    if valid_before and valid_after:
        return "already_valid"
    if valid_before and (not valid_after or changed):
        return "risky_repair"
    if not valid_before and valid_after:
        return "repairable"
    return "still_invalid"


def _code_repair_audit_rows(
    payload: dict[str, Any],
    record_index: int,
    session_id: str,
    source_path: str,
) -> list[dict[str, Any]]:
    from agents.builder_code_repair import _auto_repair_vectorize, _repair_code
    from agents.builder_code_validation import validate_generated_code

    rows: list[dict[str, Any]] = []
    session_dir = Path(source_path).parent
    for index, iteration in enumerate(_iterations(payload), start=1):
        iteration_num = iteration.get("iteration", index)
        fallback_stage, fallback_reason = _fallback_cause(iteration)
        code_path = _strategy_code_path(session_dir, iteration_num)
        code = ""
        read_error = ""
        if code_path is not None:
            try:
                code = code_path.read_text(encoding="utf-8")
            except OSError as exc:
                read_error = str(exc)

        issue_kinds = _mechanical_issue_kinds(code) if code else []
        valid_before = False
        valid_after = False
        error_before = read_error
        error_after = ""
        repaired = code
        changed = False
        if code:
            valid_before, error_before = validate_generated_code(code)
            repaired = _repair_code(code, iteration.get("used_indicators") if isinstance(iteration, dict) else None)
            repaired, _ = _auto_repair_vectorize(repaired)
            changed = repaired != code
            valid_after, error_after = validate_generated_code(repaired)

        rows.append(
            {
                "record_index": record_index,
                "session_id": session_id,
                "source_path": source_path,
                "iteration_row_index": index,
                "iteration": iteration_num,
                "model_name": payload.get("model_name", ""),
                "symbol": payload.get("symbol", ""),
                "timeframe": payload.get("timeframe", ""),
                "fallback_stage": fallback_stage,
                "fallback_reason": fallback_reason,
                "code_path": str(code_path or ""),
                "code_lines": len(code.splitlines()) if code else 0,
                "issue_kinds": ";".join(issue_kinds),
                "valid_before": valid_before,
                "valid_after": valid_after,
                "repair_changed_code": changed,
                "classification": _classify_repair_audit(
                    code_path=code_path,
                    code=code,
                    valid_before=valid_before,
                    valid_after=valid_after,
                    changed=changed,
                ),
                "validation_error_before": error_before,
                "validation_error_after": error_after,
            },
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _row_bool(row: dict[str, Any], key: str) -> bool:
    return _as_bool(row.get(key))


def _row_float(row: dict[str, Any], key: str) -> float | None:
    return _as_float(row.get(key))


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _round_or_empty(value: float | None, digits: int = 4) -> float | str:
    if value is None:
        return ""
    return round(value, digits)


def _cohort_label(row: dict[str, Any], dimension: str) -> str:
    if dimension == "all":
        return "all"
    value = str(row.get(dimension) or "").strip()
    return value or "UNKNOWN"


def _build_benchmark_cohort_rows(iteration_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dimensions = [
        "all",
        "status",
        "model_name",
        "symbol",
        "timeframe",
        "diagnostic_category",
        "builder_execution_mode",
        "orchestration_mode",
        "git_commit",
    ]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in iteration_rows:
        for dimension in dimensions:
            grouped.setdefault((dimension, _cohort_label(row, dimension)), []).append(row)

    result: list[dict[str, Any]] = []
    for (dimension, cohort), rows in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        total = len(rows)
        canonical = sum(1 for row in rows if _row_bool(row, "is_canonical"))
        fallback = sum(1 for row in rows if _row_bool(row, "is_fallback"))
        zero_trades = sum(1 for row in rows if _row_bool(row, "zero_trades"))
        positive_return = sum(
            1 for row in rows if _row_bool(row, "is_canonical") and _row_bool(row, "positive_return")
        )
        positive_sharpe = sum(
            1 for row in rows if _row_bool(row, "is_canonical") and _row_bool(row, "positive_sharpe")
        )
        target_reached = sum(
            1 for row in rows if _row_bool(row, "is_canonical") and _row_bool(row, "target_reached")
        )
        robust_rows = [row for row in rows if _row_bool(row, "canonical_robust_candidate")]
        robust_returns = [value for row in robust_rows if (value := _row_float(row, "return_pct")) is not None]
        robust_sharpes = [value for row in robust_rows if (value := _row_float(row, "sharpe")) is not None]
        robust_trades = [value for row in robust_rows if (value := _row_float(row, "trades")) is not None]
        result.append(
            {
                "dimension": dimension,
                "cohort": cohort,
                "sessions": len({str(row.get("session_id") or "") for row in rows}),
                "iterations": total,
                "canonical_iterations": canonical,
                "fallback_iterations": fallback,
                "zero_trade_iterations": zero_trades,
                "canonical_positive_return_iterations": positive_return,
                "canonical_positive_sharpe_iterations": positive_sharpe,
                "canonical_target_reached_iterations": target_reached,
                "canonical_robust_iterations": len(robust_rows),
                "canonical_rate_pct": _round_or_empty((canonical / total * 100.0) if total else None, 2),
                "fallback_rate_pct": _round_or_empty((fallback / total * 100.0) if total else None, 2),
                "zero_trade_rate_pct": _round_or_empty((zero_trades / total * 100.0) if total else None, 2),
                "canonical_robust_rate_pct": _round_or_empty(
                    (len(robust_rows) / total * 100.0) if total else None,
                    2,
                ),
                "robust_avg_return_pct": _round_or_empty(_average(robust_returns), 4),
                "robust_avg_sharpe": _round_or_empty(_average(robust_sharpes), 4),
                "robust_avg_trades": _round_or_empty(_average(robust_trades), 2),
                "robust_best_return_pct": _round_or_empty(max(robust_returns) if robust_returns else None, 4),
                "robust_best_sharpe": _round_or_empty(max(robust_sharpes) if robust_sharpes else None, 4),
            },
        )
    return result


def _build_benchmark_candidate_rows(iteration_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [row for row in iteration_rows if _row_bool(row, "canonical_robust_candidate")]
    candidates.sort(
        key=lambda row: (
            _row_float(row, "sharpe") if _row_float(row, "sharpe") is not None else float("-inf"),
            _row_float(row, "return_pct") if _row_float(row, "return_pct") is not None else float("-inf"),
            _row_float(row, "trades") if _row_float(row, "trades") is not None else float("-inf"),
        ),
        reverse=True,
    )
    rows: list[dict[str, Any]] = []
    for rank, row in enumerate(candidates, start=1):
        selected = dict(row)
        selected["benchmark_rank"] = rank
        rows.append(selected)
    return rows


def _top_rows(
    rows: list[dict[str, Any]],
    *,
    dimension: str,
    metric: str = "canonical_robust_iterations",
    limit: int = 8,
) -> list[dict[str, Any]]:
    scoped = [row for row in rows if row.get("dimension") == dimension]
    return sorted(scoped, key=lambda row: int(float(row.get(metric) or 0)), reverse=True)[:limit]


def _top_rate_rows(
    rows: list[dict[str, Any]],
    *,
    dimension: str,
    metric: str,
    min_iterations: int = 10,
    limit: int = 8,
) -> list[dict[str, Any]]:
    scoped = [
        row
        for row in rows
        if row.get("dimension") == dimension and int(float(row.get("iterations") or 0)) >= min_iterations
    ]
    return sorted(
        scoped,
        key=lambda row: (
            float(row.get(metric) or 0.0),
            int(float(row.get("iterations") or 0)),
        ),
        reverse=True,
    )[:limit]


def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    if not rows:
        return ["_No rows._"]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        values = [str(row.get(column, "")) for column in columns]
        lines.append("| " + " | ".join(values) + " |")
    return lines


def _write_benchmark_report(
    path: Path,
    *,
    generated_at: str,
    source_root: Path,
    exported: int,
    skipped: int,
    iteration_rows: list[dict[str, Any]],
    cohort_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
) -> None:
    status_counts = Counter(str(row.get("status") or "UNKNOWN") for row in iteration_rows)
    diagnostic_counts = Counter(str(row.get("diagnostic_category") or "empty") for row in iteration_rows)
    fallback_stage_counts = Counter(
        str(row.get("fallback_stage") or "unknown") for row in iteration_rows if _row_bool(row, "is_fallback")
    )
    all_row = next((row for row in cohort_rows if row.get("dimension") == "all" and row.get("cohort") == "all"), {})
    top_candidates = candidate_rows[:10]
    lines = [
        "# Builder Session Benchmark Baseline",
        "",
        f"- Generated at: `{generated_at}`",
        f"- Source root: `{source_root}`",
        f"- Exported sessions: `{exported}`",
        f"- Skipped sessions: `{skipped}`",
        f"- Iterations: `{len(iteration_rows)}`",
        f"- Canonical robust candidates: `{len(candidate_rows)}`",
        "",
        "## Global Gates",
        "",
        *_markdown_table(
            [all_row],
            [
                "iterations",
                "canonical_iterations",
                "fallback_iterations",
                "zero_trade_iterations",
                "canonical_robust_iterations",
                "canonical_robust_rate_pct",
            ],
        ),
        "",
        "## Session Status",
        "",
        *_markdown_table(
            [{"status": status, "iterations": count} for status, count in status_counts.most_common()],
            ["status", "iterations"],
        ),
        "",
        "## Dominant Diagnostics",
        "",
        *_markdown_table(
            [{"diagnostic": diagnostic, "iterations": count} for diagnostic, count in diagnostic_counts.most_common(12)],
            ["diagnostic", "iterations"],
        ),
        "",
        "## Fallback Causes",
        "",
        *_markdown_table(
            [{"fallback_stage": stage, "iterations": count} for stage, count in fallback_stage_counts.most_common()],
            ["fallback_stage", "iterations"],
        ),
        "",
        "## Robust Cohorts By Model",
        "",
        *_markdown_table(
            _top_rows(cohort_rows, dimension="model_name"),
            [
                "cohort",
                "iterations",
                "canonical_robust_iterations",
                "canonical_robust_rate_pct",
                "robust_avg_sharpe",
                "robust_avg_return_pct",
            ],
        ),
        "",
        "## Fallback Hotspots By Model",
        "",
        *_markdown_table(
            _top_rate_rows(cohort_rows, dimension="model_name", metric="fallback_rate_pct"),
            [
                "cohort",
                "iterations",
                "fallback_iterations",
                "fallback_rate_pct",
                "canonical_robust_iterations",
            ],
        ),
        "",
        "## Zero-Trade Hotspots By Symbol",
        "",
        *_markdown_table(
            _top_rate_rows(cohort_rows, dimension="symbol", metric="zero_trade_rate_pct"),
            [
                "cohort",
                "iterations",
                "zero_trade_iterations",
                "zero_trade_rate_pct",
                "canonical_robust_iterations",
            ],
        ),
        "",
        "## Robust Cohorts By Symbol",
        "",
        *_markdown_table(
            _top_rows(cohort_rows, dimension="symbol"),
            [
                "cohort",
                "iterations",
                "canonical_robust_iterations",
                "canonical_robust_rate_pct",
                "robust_avg_sharpe",
                "robust_avg_return_pct",
            ],
        ),
        "",
        "## Top Robust Candidates",
        "",
        *_markdown_table(
            top_candidates,
            [
                "benchmark_rank",
                "session_id",
                "iteration",
                "model_name",
                "symbol",
                "timeframe",
                "sharpe",
                "return_pct",
                "trades",
                "diagnostic_category",
            ],
        ),
        "",
        "## Reading",
        "",
        "- `canonical_robust_candidate` means non-fallback, trades >= 10, return > 0 and Sharpe > 0.",
        "- Cohort rates are iteration-level rates, not session-level rates.",
        "- Historical `running` statuses are retained as persisted source state, not treated as active processes.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_code_repair_audit_report(path: Path, rows: list[dict[str, Any]], *, generated_at: str) -> None:
    classification_counts = Counter(str(row.get("classification") or "unknown") for row in rows)
    issue_counts = Counter(
        issue
        for row in rows
        for issue in str(row.get("issue_kinds") or "").split(";")
        if issue
    )
    model_repairable = Counter(
        str(row.get("model_name") or "UNKNOWN") for row in rows if row.get("classification") == "repairable"
    )
    lines = [
        "# Builder Code Repair Audit",
        "",
        f"- Generated at: `{generated_at}`",
        f"- Audited iterations: `{len(rows)}`",
        "",
        "## Classification",
        "",
        *_markdown_table(
            [
                {"classification": name, "iterations": classification_counts.get(name, 0)}
                for name in AUDIT_CLASSIFICATIONS
            ],
            ["classification", "iterations"],
        ),
        "",
        "## Mechanical Issue Kinds",
        "",
        *_markdown_table(
            [{"issue_kind": issue, "iterations": count} for issue, count in issue_counts.most_common(12)],
            ["issue_kind", "iterations"],
        ),
        "",
        "## Repairable By Model",
        "",
        *_markdown_table(
            [{"model_name": model, "repairable_iterations": count} for model, count in model_repairable.most_common(12)],
            ["model_name", "repairable_iterations"],
        ),
        "",
        "## Reading",
        "",
        "- `repairable` means invalid before dry-run repair and valid after `_repair_code` + `_auto_repair_vectorize`.",
        "- `risky_repair` means the source was already valid but dry-run repair changed it or made it invalid.",
        "- No source strategy file is modified by this audit.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def export_builder_session_summary_backup(
    source_root: Path,
    output_dir: Path,
    *,
    repair_audit: bool = False,
    include_full_payload: bool = False,
    allow_repo_output: bool = False,
) -> dict[str, Any]:
    source_root = source_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    _validate_export_target(
        source_root=source_root,
        output_dir=output_dir,
        allow_repo_output=allow_repo_output,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_paths = sorted(source_root.glob("*/session_summary.json"))
    manifest_path = output_dir / "manifest.csv"
    runs_summary_path = output_dir / "runs_summary.csv"
    run_iterations_path = output_dir / "run_iterations.csv"
    runtime_events_path = output_dir / "runtime_events.csv"
    benchmark_cohorts_path = output_dir / "benchmark_cohorts.csv"
    benchmark_candidates_path = output_dir / "benchmark_candidates.csv"
    benchmark_report_path = output_dir / "builder_benchmark_report.md"
    code_repair_audit_path = output_dir / "code_repair_audit.csv"
    code_repair_audit_report_path = output_dir / "code_repair_audit_report.md"
    archive_path = output_dir / "session_summaries.ndjson.gz"
    checksum_path = output_dir / "session_summaries.ndjson.gz.sha256"
    readme_path = output_dir / "README.md"

    rows: list[dict[str, Any]] = []
    runs_summary_rows: list[dict[str, Any]] = []
    run_iteration_rows: list[dict[str, Any]] = []
    runtime_event_rows: list[dict[str, Any]] = []
    code_repair_audit_rows: list[dict[str, Any]] = []
    exported = 0
    skipped: list[dict[str, str]] = []
    payload_mode = "full" if include_full_payload else "compact"

    with (
        archive_path.open("wb") as raw_archive,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw_archive, mtime=0) as gzip_file,
        io.TextIOWrapper(gzip_file, encoding="utf-8", newline="\n") as archive,
    ):
        for path in summary_paths:
            try:
                raw = path.read_bytes()
                payload = _read_json(path)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                skipped.append({"path": _relative_ref(source_root, path), "error": str(exc)})
                continue

            exported += 1
            digest = _sha256_bytes(raw)
            row = _summary_row(path, payload, digest, len(raw), exported, source_root=source_root)
            rows.append(row)
            runs_summary_rows.append(
                _session_analytics_row(path, payload, digest, len(raw), exported, source_root=source_root),
            )
            run_iteration_rows.extend(
                _iteration_analytics_rows(
                    payload,
                    exported,
                    str(row["session_id"]),
                    str(row["source_path"]),
                ),
            )
            runtime_event_rows.extend(
                _runtime_event_rows(
                    payload,
                    exported,
                    str(row["session_id"]),
                    str(row["source_path"]),
                ),
            )
            if repair_audit:
                code_repair_audit_rows.extend(
                    _code_repair_audit_rows(
                        payload,
                        exported,
                        str(row["session_id"]),
                        str(row["source_path"]),
                    ),
                )
            archive.write(
                json.dumps(
                    {
                        "record_index": exported,
                        "session_id": row["session_id"],
                        "source_path": row["source_path"],
                        "sha256": digest,
                        "payload_mode": payload_mode,
                        "payload": payload if include_full_payload else _compact_summary_payload(payload),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                )
                + "\n",
            )

    fieldnames = [
        "record_index",
        "session_id",
        "source_path",
        "source_dir",
        "sha256",
        "size_bytes",
        "start_time",
        "end_time",
        "status",
        "model_name",
        "symbol",
        "timeframe",
        "total_iterations",
        "canonical_rate",
        "best_sharpe",
        "best_score",
        "git_commit",
    ]
    _write_csv(manifest_path, rows, fieldnames)
    _write_csv(
        runs_summary_path,
        runs_summary_rows,
        [
            *fieldnames,
            "summary_schema_version",
            "git_branch",
            "git_dirty",
            "target_sharpe",
            "n_bars",
            "builder_execution_mode",
            "orchestration_mode",
            "instrumentation_enabled",
            "fallback_iterations",
            "canonical_iterations",
            "zero_trade_iterations",
            "canonical_positive_return_iterations",
            "canonical_positive_sharpe_iterations",
            "target_reached_iterations",
            "canonical_robust_iterations",
            "dominant_diagnostic",
        ],
    )
    run_iteration_fieldnames = [
        "record_index",
        "session_id",
        "source_path",
        "iteration_row_index",
        "iteration",
        "timestamp",
        "session_elapsed_seconds",
        "status",
        "model_name",
        "symbol",
        "timeframe",
        "n_bars",
        "git_commit",
        "git_branch",
        "builder_execution_mode",
        "orchestration_mode",
        "evaluation_mode",
        "decision",
        "change_type",
        "diagnostic_category",
        "is_fallback",
        "is_canonical",
        "zero_trades",
        "positive_return",
        "positive_sharpe",
        "target_reached",
        "canonical_robust_candidate",
        "fallback_stage",
        "fallback_reason",
        "trades",
        "return_pct",
        "sharpe",
        "max_drawdown_pct",
        "profit_factor",
        "win_rate_pct",
        "telemetry_score",
        "used_indicators",
        "error",
    ]
    _write_csv(run_iterations_path, run_iteration_rows, run_iteration_fieldnames)
    _write_csv(
        runtime_events_path,
        runtime_event_rows,
        [
            "record_index",
            "session_id",
            "source_path",
            "iteration",
            "timestamp",
            "event_kind",
            "phase",
            "message",
            "payload_json",
        ],
    )
    benchmark_cohort_rows = _build_benchmark_cohort_rows(run_iteration_rows)
    benchmark_candidate_rows = _build_benchmark_candidate_rows(run_iteration_rows)
    _write_csv(
        benchmark_cohorts_path,
        benchmark_cohort_rows,
        [
            "dimension",
            "cohort",
            "sessions",
            "iterations",
            "canonical_iterations",
            "fallback_iterations",
            "zero_trade_iterations",
            "canonical_positive_return_iterations",
            "canonical_positive_sharpe_iterations",
            "canonical_target_reached_iterations",
            "canonical_robust_iterations",
            "canonical_rate_pct",
            "fallback_rate_pct",
            "zero_trade_rate_pct",
            "canonical_robust_rate_pct",
            "robust_avg_return_pct",
            "robust_avg_sharpe",
            "robust_avg_trades",
            "robust_best_return_pct",
            "robust_best_sharpe",
        ],
    )
    _write_csv(
        benchmark_candidates_path,
        benchmark_candidate_rows,
        ["benchmark_rank", *run_iteration_fieldnames],
    )
    code_repair_audit_fieldnames = [
        "record_index",
        "session_id",
        "source_path",
        "iteration_row_index",
        "iteration",
        "model_name",
        "symbol",
        "timeframe",
        "fallback_stage",
        "fallback_reason",
        "code_path",
        "code_lines",
        "issue_kinds",
        "valid_before",
        "valid_after",
        "repair_changed_code",
        "classification",
        "validation_error_before",
        "validation_error_after",
    ]
    if repair_audit:
        _write_csv(code_repair_audit_path, code_repair_audit_rows, code_repair_audit_fieldnames)
    else:
        for optional_path in (code_repair_audit_path, code_repair_audit_report_path):
            if optional_path.exists():
                optional_path.unlink()

    archive_digest = _sha256_bytes(archive_path.read_bytes())
    _write_text_lf(checksum_path, f"{archive_digest}  {archive_path.name}\n")

    generated_at = datetime.now().isoformat(timespec="seconds")
    _write_benchmark_report(
        benchmark_report_path,
        generated_at=generated_at,
        source_root=source_root,
        exported=exported,
        skipped=len(skipped),
        iteration_rows=run_iteration_rows,
        cohort_rows=benchmark_cohort_rows,
        candidate_rows=benchmark_candidate_rows,
    )
    if repair_audit:
        _write_code_repair_audit_report(
            code_repair_audit_report_path,
            code_repair_audit_rows,
            generated_at=generated_at,
        )
    _write_text_lf(
        readme_path,
        "\n".join(
            [
                "# Builder Session Summary Local Export",
                "",
                f"- Generated at: `{generated_at}`",
                "- Canonical source root: local Builder sessions root (redacted; pass `--source-root` when exporting).",
                "- Canonical source shape: one `session_summary.json` per Builder session directory.",
                f"- Exported summaries: `{exported}`",
                f"- Skipped summaries: `{len(skipped)}`",
                f"- Archive: `{archive_path.name}`",
                f"- Manifest: `{manifest_path.name}`",
                f"- Runs summary CSV: `{runs_summary_path.name}`",
                f"- Iterations CSV: `{run_iterations_path.name}`",
                f"- Runtime events CSV: `{runtime_events_path.name}`",
                f"- Benchmark cohorts CSV: `{benchmark_cohorts_path.name}`",
                f"- Benchmark candidates CSV: `{benchmark_candidates_path.name}`",
                f"- Benchmark report: `{benchmark_report_path.name}`",
                f"- Code repair audit CSV: `{code_repair_audit_path.name}`" if repair_audit else "",
                f"- Code repair audit report: `{code_repair_audit_report_path.name}`" if repair_audit else "",
                f"- Payload mode: `{payload_mode}`",
                f"- Archive SHA256: `{archive_digest}`",
                "",
                "The compressed NDJSON archive stores one JSON object per source session summary.",
                "Each object contains `record_index`, `session_id`, a relative `source_path`, `sha256`, `payload_mode`, and `payload`.",
                (
                    "By default the payload is compact and excludes raw phase feedback, cross-session memory, and local absolute paths."
                    if not include_full_payload
                    else "This export was created with `--include-full-payload`; the archive keeps raw session payloads."
                ),
                "",
                "The flat CSV tables are derived views for analysis:",
                "",
                "- `runs_summary.csv`: one row per session with cohort fields and aggregate iteration counts.",
                "- `run_iterations.csv`: one row per Builder iteration with canonical/fallback, fallback cause and robustness gates.",
                "- `runtime_events.csv`: sparse runtime/error events extracted from iteration feedback.",
                "- `benchmark_cohorts.csv`: iteration-level cohort aggregates for model/symbol/timeframe/status diagnostics.",
                "- `benchmark_candidates.csv`: sorted canonical robust candidates for v2/v3 baseline comparisons.",
                "- `builder_benchmark_report.md`: human-readable baseline summary derived from the CSV tables.",
                (
                    "- `code_repair_audit.csv`: optional dry-run audit of strategy files through the code validator/repair path."
                    if repair_audit
                    else ""
                ),
                (
                    "- `code_repair_audit_report.md`: optional summary of repairability by issue kind/model."
                    if repair_audit
                    else ""
                ),
                "",
                "To inspect quickly:",
                "",
                "```powershell",
                "python - <<'PY'",
                "import gzip, json",
                f"path = r'{archive_path}'",
                "with gzip.open(path, 'rt', encoding='utf-8') as handle:",
                "    first = json.loads(next(handle))",
                "print(first['session_id'])",
                "PY",
                "```",
            ],
        )
        + "\n",
    )

    skipped_path = output_dir / "skipped.json"
    if skipped:
        _write_text_lf(skipped_path, json.dumps(skipped, indent=2, ensure_ascii=False) + "\n")
    elif skipped_path.exists():
        skipped_path.unlink()

    return {
        "source_root": str(source_root),
        "output_dir": str(output_dir),
        "exported": exported,
        "skipped": len(skipped),
        "archive_path": str(archive_path),
        "manifest_path": str(manifest_path),
        "runs_summary_path": str(runs_summary_path),
        "run_iterations_path": str(run_iterations_path),
        "runtime_events_path": str(runtime_events_path),
        "benchmark_cohorts_path": str(benchmark_cohorts_path),
        "benchmark_candidates_path": str(benchmark_candidates_path),
        "benchmark_report_path": str(benchmark_report_path),
        "code_repair_audit_path": str(code_repair_audit_path) if repair_audit else "",
        "code_repair_audit_report_path": str(code_repair_audit_report_path) if repair_audit else "",
        "run_iterations": len(run_iteration_rows),
        "runtime_events": len(runtime_event_rows),
        "benchmark_cohorts": len(benchmark_cohort_rows),
        "benchmark_candidates": len(benchmark_candidate_rows),
        "code_repair_audit_rows": len(code_repair_audit_rows),
        "payload_mode": payload_mode,
        "archive_sha256": archive_digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=_default_source_root(),
        help="Builder sessions root containing */session_summary.json.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where local Builder session export files will be written.",
    )
    parser.add_argument(
        "--repair-audit",
        action="store_true",
        help="Dry-run validate/repair persisted Builder strategy files and emit code_repair_audit outputs.",
    )
    parser.add_argument(
        "--include-full-payload",
        action="store_true",
        help="Store raw session_summary.json payloads instead of compact redacted payloads.",
    )
    parser.add_argument(
        "--allow-repo-output",
        action="store_true",
        help="Allow writing the export inside this repository. Disabled by default to avoid duplicate backups.",
    )
    args = parser.parse_args()
    result = export_builder_session_summary_backup(
        args.source_root,
        args.output_dir,
        repair_audit=args.repair_audit,
        include_full_payload=bool(args.include_full_payload),
        allow_repo_output=bool(args.allow_repo_output),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
