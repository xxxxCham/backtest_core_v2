"""Dedicated Streamlit view for browsing the centralized external results store."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from backtest.result_store import (
    get_artifacts_root_dir,
    get_builder_sessions_dir,
    get_results_analysis_dir,
    get_results_root_dir,
)
from ui.helpers import _maybe_auto_save_run, coerce_metric_float, coerce_metric_int
from ui.model_stats_view import (
    build_model_stats_report,
    load_autonomous_history,
    load_model_stats_state,
)
from ui.results_hub import render_results_hub

try:
    from agents.pipeline_instrumentation import (
        DivergenceAnalyzer,
        PhaseMeasurement,
        PipelineTrace,
    )
except ImportError:
    DivergenceAnalyzer = None
    PhaseMeasurement = None
    PipelineTrace = None


def _coerce_int(value: Any) -> int | None:
    return coerce_metric_int(value, default=None)


def _display_float(value: Any) -> float:
    coerced = coerce_metric_float(value, default=None)
    if coerced is None or pd.isna(coerced):
        return 0.0
    return float(coerced)


def _display_int(value: Any, default: int = 0) -> int:
    coerced = coerce_metric_int(value, default=None)
    if coerced is None:
        return default
    return coerced


_BUILDER_STATUS_LABELS = {
    "running": "À finir - stratégie non aboutie",
}


def _builder_status_label(status: Any) -> str:
    raw_status = str(status or "unknown").strip() or "unknown"
    return _BUILDER_STATUS_LABELS.get(raw_status, raw_status)


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolve_pipeline_traces_path(
    session_dir: Path,
    summary: dict[str, Any],
) -> Path | None:
    raw_value = str(summary.get("pipeline_traces_path") or "").strip()
    if raw_value:
        candidate = Path(raw_value)
        if not candidate.is_absolute():
            candidate = session_dir / candidate
        if candidate.exists():
            return candidate
    fallback = session_dir / "pipeline_traces.json"
    return fallback if fallback.exists() else None


def _trace_strategy_sort_key(trace: PipelineTrace) -> tuple[float, ...]:
    metrics = dict(getattr(trace, "backtest_metrics", {}) or {})
    sharpe = _display_float(metrics.get("sharpe_ratio"))
    total_return = _display_float(metrics.get("total_return_pct"))
    max_drawdown = abs(_display_float(metrics.get("max_drawdown_pct")))
    profit_factor = _display_float(metrics.get("profit_factor"))
    trades = _display_float(metrics.get("total_trades"))
    return (
        1.0 if bool(getattr(trace, "is_best_so_far", False)) else 0.0,
        1.0 if total_return > 0.0 else 0.0,
        sharpe,
        total_return,
        profit_factor,
        -max_drawdown,
        trades,
        float(_display_int(getattr(trace, "iteration_num", 0))),
    )


def _trace_from_dict(payload: dict[str, Any]) -> PipelineTrace | None:
    if PipelineTrace is None or PhaseMeasurement is None or not isinstance(payload, dict):
        return None
    trace = PipelineTrace(
        iteration_num=_display_int(payload.get("iteration_num", 0)),
        session_id=str(payload.get("session_id", "") or ""),
        timestamp=float(payload.get("timestamp", 0.0) or 0.0),
    )
    for key, value in payload.items():
        if key == "phases":
            continue
        if hasattr(trace, key):
            setattr(trace, key, value)
    trace.phases = [
        PhaseMeasurement(**phase) for phase in list(payload.get("phases", []) or []) if isinstance(phase, dict)
    ]
    return trace


def _select_reference_trace(trace_payload: dict[str, Any]) -> PipelineTrace | None:
    traces = [_trace_from_dict(item) for item in list(trace_payload.get("traces", []) or []) if isinstance(item, dict)]
    traces = [trace for trace in traces if trace is not None]
    if not traces:
        return None
    best_trace = max(traces, key=_trace_strategy_sort_key)
    return best_trace


def _shorten(text: str, limit: int = 120) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}..."


def _format_timestamp(ts: float | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _count_children(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    try:
        return sum(1 for _ in path.iterdir())
    except OSError:
        return 0


def _latest_child_mtime(path: Path) -> float | None:
    if not path.exists():
        return None
    try:
        if path.is_file():
            return path.stat().st_mtime
        mtimes = [child.stat().st_mtime for child in path.iterdir()]
        if mtimes:
            return max(mtimes)
        return path.stat().st_mtime
    except OSError:
        return None


def _pick_latest_strategy_file(session_dir: Path) -> Path | None:
    direct_path = session_dir / "strategy.py"
    if direct_path.exists():
        return direct_path
    strategy_versions = sorted(session_dir.glob("strategy_v*.py"))
    if strategy_versions:
        return strategy_versions[-1]
    return None


def _pick_strategy_file_for_iteration(session_dir: Path, iteration_num: Any) -> Path | None:
    resolved_iteration = _display_int(iteration_num)
    if resolved_iteration > 0:
        versioned = session_dir / f"strategy_v{resolved_iteration}.py"
        if versioned.exists():
            return versioned
    return _pick_latest_strategy_file(session_dir)


def _compute_builder_best_return(summary: dict[str, Any]) -> float | None:
    candidates: list[float] = []
    direct_value = coerce_metric_float(summary.get("best_return_pct"), default=None)
    if direct_value is not None:
        candidates.append(direct_value)

    for iteration in summary.get("iterations") or []:
        value = coerce_metric_float((iteration or {}).get("return_pct"), default=None)
        if value is not None:
            candidates.append(value)
    if not candidates:
        return None
    return max(candidates)


def _collect_positive_iteration_metrics(summary: dict[str, Any]) -> tuple[int, list[int], str, int | None]:
    positive_rows: list[tuple[int, float]] = []
    for iteration in summary.get("iterations") or []:
        if not isinstance(iteration, dict):
            continue
        iteration_num = _display_int(iteration.get("iteration"))
        return_pct = coerce_metric_float(iteration.get("return_pct"), default=None)
        if return_pct is None or return_pct <= 0.0:
            continue
        positive_rows.append((iteration_num, return_pct))

    positive_rows.sort(key=lambda item: (item[1], item[0]), reverse=True)
    summary_parts = [f"i{iteration_num} {return_pct:+.2f}%" for iteration_num, return_pct in positive_rows[:5]]
    summary_text = ", ".join(summary_parts)
    if len(positive_rows) > 5:
        summary_text += ", ..."
    best_iteration = positive_rows[0][0] if positive_rows else None
    return (
        len(positive_rows),
        [iteration_num for iteration_num, _ in positive_rows],
        summary_text,
        best_iteration,
    )


def _format_params_preview(params: Any, *, max_items: int = 5) -> str:
    if not isinstance(params, dict) or not params:
        return ""
    parts = [f"{key}={value}" for key, value in sorted(params.items(), key=lambda item: str(item[0]))]
    if len(parts) > max_items:
        return ", ".join(parts[:max_items]) + ", ..."
    return ", ".join(parts)


def collect_builder_sessions(builder_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not builder_root.exists():
        return rows

    for session_dir in sorted(builder_root.iterdir(), key=lambda item: item.name, reverse=True):
        if not session_dir.is_dir() or session_dir.name.startswith("_"):
            continue

        summary_path = session_dir / "session_summary.json"
        summary = _safe_read_json(summary_path) if summary_path.exists() else {}
        pipeline_traces_path = _resolve_pipeline_traces_path(session_dir, summary)
        latest_strategy_path = _pick_latest_strategy_file(session_dir)
        strategy_versions = sorted(session_dir.glob("strategy_v*.py"))
        last_modified_candidates = [
            _latest_child_mtime(summary_path) if summary_path.exists() else None,
            _latest_child_mtime(latest_strategy_path) if latest_strategy_path else None,
            _latest_child_mtime(session_dir),
        ]
        last_modified_values = [value for value in last_modified_candidates if value is not None]
        last_modified = max(last_modified_values) if last_modified_values else None
        positive_iterations, positive_iteration_ids, positive_iteration_summary, best_return_iteration = (
            _collect_positive_iteration_metrics(summary)
        )

        rows.append(
            {
                "session_id": session_dir.name,
                "status": str(summary.get("status") or "unknown"),
                "model_name": str(summary.get("model_name") or ""),
                "symbol": str(summary.get("symbol") or ""),
                "timeframe": str(summary.get("timeframe") or ""),
                "best_sharpe": coerce_metric_float(summary.get("best_sharpe"), default=None),
                "best_telemetry_score": coerce_metric_float(
                    summary.get("best_telemetry_score", summary.get("best_score")),
                    default=None,
                ),
                "best_score": coerce_metric_float(summary.get("best_score"), default=None),
                "best_return_pct": _compute_builder_best_return(summary),
                "best_return_iteration": best_return_iteration,
                "total_iterations": _display_int(
                    summary.get("total_iterations"),
                    default=len(summary.get("iterations") or []),
                ),
                "positive_iterations": positive_iterations,
                "positive_iteration_ids": positive_iteration_ids,
                "positive_iteration_summary": positive_iteration_summary,
                "auto_reset_count": _display_int(summary.get("auto_reset_count")),
                "objective": str(summary.get("objective") or ""),
                "objective_excerpt": _shorten(str(summary.get("objective") or "")),
                "builder_execution_mode": str(
                    summary.get("builder_execution_mode") or "mono_single_llm",
                ),
                "orchestration_mode": str(
                    summary.get("orchestration_mode") or "single_llm",
                ),
                "resume_parent_session_id": str(summary.get("resume_parent_session_id") or ""),
                "resume_mode": str(summary.get("resume_mode") or ""),
                "resume_from_iteration": _display_int(summary.get("resume_from_iteration")),
                "resume_extra_iterations": _display_int(summary.get("resume_extra_iterations")),
                "resume_original_status": str(summary.get("resume_original_status") or ""),
                "resume_original_model_name": str(summary.get("resume_original_model_name") or ""),
                "resume_requested_model_name": str(summary.get("resume_requested_model_name") or ""),
                "instrumentation_enabled": bool(
                    summary.get("instrumentation_enabled", False),
                ),
                "instrumentation_summary": (
                    dict(summary.get("instrumentation_summary", {}) or {})
                    if isinstance(summary.get("instrumentation_summary"), dict)
                    else {}
                ),
                "session_dir": str(session_dir),
                "summary_path": str(summary_path) if summary_path.exists() else "",
                "pipeline_traces_path": str(pipeline_traces_path) if pipeline_traces_path else "",
                "latest_strategy_path": str(latest_strategy_path) if latest_strategy_path else "",
                "strategy_versions": len(strategy_versions),
                "last_modified": _format_timestamp(last_modified),
            },
        )
    return rows


def collect_builder_iterations(builder_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not builder_root.exists():
        return rows

    for session_dir in sorted(builder_root.iterdir(), key=lambda item: item.name, reverse=True):
        if not session_dir.is_dir() or session_dir.name.startswith("_"):
            continue

        summary_path = session_dir / "session_summary.json"
        summary = _safe_read_json(summary_path) if summary_path.exists() else {}
        iterations = summary.get("iterations") if isinstance(summary.get("iterations"), list) else []
        leaderboard_rows = summary.get("leaderboard") if isinstance(summary.get("leaderboard"), list) else []
        rank_by_iteration: dict[int, int] = {}
        for row in leaderboard_rows:
            if not isinstance(row, dict):
                continue
            iteration_num = _display_int(row.get("iteration"))
            rank = _display_int(row.get("rank"))
            if iteration_num > 0 and rank > 0:
                rank_by_iteration[iteration_num] = rank

        session_last_modified = _format_timestamp(_latest_child_mtime(session_dir))
        objective = str(summary.get("objective") or "")
        objective_excerpt = _shorten(objective)
        session_status = str(summary.get("status") or "unknown")

        for iteration_payload in iterations:
            if not isinstance(iteration_payload, dict):
                continue
            iteration_num = _display_int(iteration_payload.get("iteration"))
            strategy_path = _pick_strategy_file_for_iteration(session_dir, iteration_num)
            params_used = iteration_payload.get("params_used") if isinstance(iteration_payload.get("params_used"), dict) else {}
            return_pct = coerce_metric_float(iteration_payload.get("return_pct"), default=None)
            rows.append(
                {
                    "candidate_id": f"builder:{session_dir.name}:{iteration_num}" if iteration_num > 0 else session_dir.name,
                    "session_id": session_dir.name,
                    "status": session_status,
                    "iteration": iteration_num,
                    "leaderboard_rank": rank_by_iteration.get(iteration_num),
                    "return_pct": return_pct,
                    "positive_return": bool(return_pct is not None and return_pct > 0.0),
                    "sharpe": coerce_metric_float(iteration_payload.get("sharpe"), default=None),
                    "profit_factor": coerce_metric_float(iteration_payload.get("profit_factor"), default=None),
                    "max_drawdown_pct": coerce_metric_float(iteration_payload.get("max_drawdown_pct"), default=None),
                    "trades": _display_int(iteration_payload.get("trades")),
                    "change_type": str(iteration_payload.get("change_type") or ""),
                    "diagnostic_category": str(iteration_payload.get("diagnostic_category") or ""),
                    "evaluation_mode": str(iteration_payload.get("evaluation_mode") or ""),
                    "decision": str(iteration_payload.get("decision") or ""),
                    "error": str(iteration_payload.get("error") or ""),
                    "is_fallback": bool(iteration_payload.get("is_fallback", False)),
                    "params_used": dict(params_used),
                    "params_used_preview": _format_params_preview(params_used),
                    "objective_excerpt": objective_excerpt,
                    "session_dir": str(session_dir),
                    "summary_path": str(summary_path) if summary_path.exists() else "",
                    "strategy_path": str(strategy_path) if strategy_path else "",
                    "last_modified": session_last_modified,
                },
            )

    return rows


def collect_store_inventory(results_root: Path, artifacts_root: Path) -> list[dict[str, Any]]:
    legacy_runs_dir = results_root / "runs"
    analysis_root = artifacts_root / "_analysis"
    builder_root = artifacts_root / "_builder_sessions"
    saved_runs_root = artifacts_root / "_saved_runs"
    diagnostics_root = artifacts_root / "_diagnostics" / "sweeps"
    profiling_root = artifacts_root / "_profiling"
    output_root = artifacts_root / "_output"
    organized_root = artifacts_root / "_organized_results"
    archive_root = artifacts_root / "_archive_results"
    entries = [
        ("Dossier racine résultats", results_root),
        ("Dossier racine artefacts", artifacts_root),
        ("Dossier analyses", analysis_root),
        ("Dossiers de session Builder", builder_root),
        ("Dossiers de run sauvegardé", saved_runs_root),
        ("Dossier diagnostics sweeps", diagnostics_root),
        ("Dossier profiling", profiling_root),
        ("Dossier output", output_root),
        ("Dossier résultats organisés", organized_root),
        ("Dossier archives résultats", archive_root),
        ("Dossiers de run legacy", legacy_runs_dir),
    ]

    rows: list[dict[str, Any]] = []
    for label, path in entries:
        latest_mtime = _latest_child_mtime(path)
        rows.append(
            {
                "label": label,
                "path": str(path),
                "exists": path.exists(),
                "items": _count_children(path),
                "last_modified": _format_timestamp(latest_mtime),
            },
        )
    return rows


def collect_analysis_files(analysis_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not analysis_root.exists():
        return rows

    for path in sorted(analysis_root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append(
            {
                "name": path.name,
                "path": str(path),
                "size_kb": round(stat.st_size / 1024.0, 1),
                "last_modified": _format_timestamp(stat.st_mtime),
                "suffix": path.suffix.lower(),
            },
        )
    return rows


def collect_builder_linked_runs(results_root: Path, session_id: str) -> list[dict[str, Any]]:
    catalog_path = results_root / "_catalog" / "unified_overview.csv"
    if not catalog_path.exists():
        return []

    wanted_cols = {
        "run_id",
        "timestamp",
        "status",
        "strategy",
        "symbol",
        "timeframe",
        "path",
        "metrics_total_return_pct",
        "metrics_sharpe_ratio",
        "metrics_profit_factor",
        "metrics_total_trades",
        "extra_builder_session_id",
        "extra_builder_iteration",
    }
    try:
        df = pd.read_csv(
            catalog_path,
            low_memory=False,
            usecols=lambda name: name in wanted_cols,
        )
    except Exception:
        return []

    if "extra_builder_session_id" not in df.columns:
        return []

    df = df[df["extra_builder_session_id"].astype(str) == str(session_id)].copy()
    if df.empty:
        return []

    for column in [
        "metrics_total_return_pct",
        "metrics_sharpe_ratio",
        "metrics_profit_factor",
        "metrics_total_trades",
        "extra_builder_iteration",
    ]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    if "timestamp" in df.columns:
        df["timestamp_dt"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.sort_values(
            ["timestamp_dt", "metrics_total_return_pct"],
            ascending=[False, False],
            na_position="last",
        ).drop(columns=["timestamp_dt"])

    return df.to_dict("records")


def collect_builder_catalog_reconciliation(results_root: Path, builder_root: Path) -> dict[str, Any]:
    builder_session_dirs = sorted(
        [
            child.name
            for child in builder_root.iterdir()
            if child.is_dir() and not child.name.startswith("_")
        ],
    ) if builder_root.exists() else []
    builder_session_set = set(builder_session_dirs)

    audit: dict[str, Any] = {
        "catalog_path": "",
        "catalog_row_count": 0,
        "catalog_run_count": 0,
        "builder_session_dir_count": len(builder_session_dirs),
        "catalog_builder_session_count": 0,
        "linked_builder_run_count": 0,
        "matched_session_count": 0,
        "disk_only_session_count": len(builder_session_dirs),
        "catalog_only_session_count": 0,
        "disk_only_sessions": list(builder_session_dirs),
        "catalog_only_sessions": [],
    }

    catalog_path = results_root / "_catalog" / "unified_overview.csv"
    if not catalog_path.exists():
        return audit

    audit["catalog_path"] = str(catalog_path)
    wanted_cols = {"run_id", "extra_builder_session_id"}
    try:
        df = pd.read_csv(
            catalog_path,
            low_memory=False,
            usecols=lambda name: name in wanted_cols,
        )
    except Exception:
        return audit

    audit["catalog_row_count"] = int(len(df))
    if "run_id" in df.columns:
        run_ids = df["run_id"].astype(str).str.strip()
        run_ids = run_ids[(run_ids != "") & (run_ids.str.lower() != "nan")]
        audit["catalog_run_count"] = int(run_ids.nunique())

    if "extra_builder_session_id" not in df.columns:
        return audit

    session_ids = df["extra_builder_session_id"].where(
        df["extra_builder_session_id"].notna(),
        "",
    )
    session_ids = session_ids.astype(str).str.strip()
    invalid_session_markers = {"", "nan", "none", "null"}
    session_ids = session_ids[~session_ids.str.lower().isin(invalid_session_markers)]
    catalog_session_set = {str(session_id) for session_id in session_ids.tolist() if str(session_id).strip()}

    audit["catalog_builder_session_count"] = len(catalog_session_set)
    audit["linked_builder_run_count"] = int(len(session_ids))
    audit["matched_session_count"] = len(builder_session_set & catalog_session_set)
    audit["disk_only_sessions"] = sorted(builder_session_set - catalog_session_set)
    audit["catalog_only_sessions"] = sorted(str(session_id) for session_id in (catalog_session_set - builder_session_set))
    audit["disk_only_session_count"] = len(audit["disk_only_sessions"])
    audit["catalog_only_session_count"] = len(audit["catalog_only_sessions"])
    return audit


@st.cache_data(show_spinner=False)
def _load_builder_sessions_df(builder_root: str) -> pd.DataFrame:
    rows = collect_builder_sessions(Path(builder_root))
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def _load_builder_iterations_df(builder_root: str) -> pd.DataFrame:
    rows = collect_builder_iterations(Path(builder_root))
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def _load_store_inventory_df(results_root: str, artifacts_root: str) -> pd.DataFrame:
    rows = collect_store_inventory(Path(results_root), Path(artifacts_root))
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def _load_analysis_files_df(analysis_root: str) -> pd.DataFrame:
    rows = collect_analysis_files(Path(analysis_root))
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def _load_builder_linked_runs_df(results_root: str, session_id: str) -> pd.DataFrame:
    rows = collect_builder_linked_runs(Path(results_root), session_id)
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def _load_builder_catalog_reconciliation(builder_root: str, results_root: str) -> dict[str, Any]:
    return collect_builder_catalog_reconciliation(Path(results_root), Path(builder_root))


@st.cache_data(show_spinner=False)
def _load_model_classification_report(scope: str) -> dict[str, Any]:
    history = load_autonomous_history()
    state = load_model_stats_state()
    return build_model_stats_report(history, state=state, scope=scope)


def _read_preview(path: Path, max_chars: int = 8000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n... preview truncated ..."


def _open_path_in_system(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"Introuvable: {path}"
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        return False, f"Echec ouverture: {exc}"
    return True, f"Ouverture demandee: {path}"


def _handle_open_action(path: Path, *, button_label: str, key: str) -> None:
    if st.button(button_label, key=key):
        ok, message = _open_path_in_system(path)
        if ok:
            st.success(message)
        else:
            st.warning(message)


def _render_store_summary(
    *,
    results_root: Path,
    artifacts_root: Path,
    inventory_df: pd.DataFrame,
    builder_df: pd.DataFrame,
    analysis_files_df: pd.DataFrame,
    builder_catalog_audit: dict[str, Any],
) -> None:
    raw_run_count = (
        sum(
            1
            for child in results_root.iterdir()
            if child.is_dir() and not child.name.startswith("_") and child.name != "runs"
        )
        if results_root.exists()
        else 0
    )
    legacy_runs_count = _count_children(results_root / "runs")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Runs catalogués (run_id)", _display_int(builder_catalog_audit.get("catalog_run_count", 0)))
    col2.metric("Dossiers de résultat", raw_run_count)
    col3.metric("Dossiers de session Builder", len(builder_df))
    col4.metric(
        "Sessions Builder cataloguées",
        _display_int(builder_catalog_audit.get("catalog_builder_session_count", 0)),
    )
    col5.metric("Fichiers d'analyse", len(analysis_files_df))

    st.caption(
        " | ".join(
            [
                f"Résultats: `{results_root}`",
                f"Artefacts: `{artifacts_root}`",
                f"Dossiers de run legacy: {legacy_runs_count}",
                f"Lignes unified_overview.csv: {_display_int(builder_catalog_audit.get('catalog_row_count', 0))}",
            ],
        ),
    )

    analysis_root = artifacts_root / "_analysis"
    builder_root = artifacts_root / "_builder_sessions"
    output_root = artifacts_root / "_output"
    quick_cols = st.columns(5)
    quick_actions = [
        ("Ouvrir dossier résultats", results_root),
        ("Ouvrir dossier artefacts", artifacts_root),
        ("Ouvrir dossier analyses", analysis_root),
        ("Ouvrir dossier Builder", builder_root),
        ("Ouvrir dossier output", output_root),
    ]
    for idx, (label, path) in enumerate(quick_actions):
        with quick_cols[idx]:
            _handle_open_action(path, button_label=label, key=f"store-open-{idx}")

    if not inventory_df.empty:
        with st.expander("Dossiers suivis par la page", expanded=False):
            st.dataframe(inventory_df, width="stretch", hide_index=True)


def _render_builder_catalog_audit(audit: dict[str, Any]) -> None:
    st.markdown("**Audit de réconciliation session / run / catalogue**")
    metric_cols = st.columns(5)
    metric_cols[0].metric("Dossiers de session", _display_int(audit.get("builder_session_dir_count", 0)))
    metric_cols[1].metric("Sessions cataloguées", _display_int(audit.get("catalog_builder_session_count", 0)))
    metric_cols[2].metric("Runs Builder catalogués", _display_int(audit.get("linked_builder_run_count", 0)))
    metric_cols[3].metric("Dossiers sans run", _display_int(audit.get("disk_only_session_count", 0)))
    metric_cols[4].metric("Sessions sans dossier", _display_int(audit.get("catalog_only_session_count", 0)))

    catalog_path = str(audit.get("catalog_path") or "").strip()
    if catalog_path:
        st.caption(f"Source catalogue Builder: `{catalog_path}`")

    disk_only_sessions = list(audit.get("disk_only_sessions") or [])
    catalog_only_sessions = list(audit.get("catalog_only_sessions") or [])
    if not disk_only_sessions and not catalog_only_sessions:
        st.success("Aucun écart détecté entre les dossiers de session Builder et les sessions Builder référencées dans le catalogue.")
        return

    if disk_only_sessions:
        with st.expander(
            f"Dossiers de session présents sur disque sans run catalogué ({len(disk_only_sessions)})",
            expanded=False,
        ):
            st.dataframe(
                pd.DataFrame({"session_id": disk_only_sessions}),
                width="stretch",
                hide_index=True,
            )

    if catalog_only_sessions:
        with st.expander(
            f"Sessions Builder référencées par le catalogue sans dossier local ({len(catalog_only_sessions)})",
            expanded=False,
        ):
            st.dataframe(
                pd.DataFrame({"session_id": catalog_only_sessions}),
                width="stretch",
                hide_index=True,
            )


def _resume_cell_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _collect_builder_max_iteration_resume_candidates(builder_df: pd.DataFrame) -> pd.DataFrame:
    if builder_df.empty:
        return pd.DataFrame()

    frame = builder_df.copy()
    if "session_id" not in frame.columns or "status" not in frame.columns:
        return pd.DataFrame()

    if "resume_parent_session_id" not in frame.columns:
        frame["resume_parent_session_id"] = ""
    resumed_parent_ids = {
        _resume_cell_text(value)
        for value in frame["resume_parent_session_id"].tolist()
        if _resume_cell_text(value)
    }

    status_series = frame["status"].map(_resume_cell_text)
    session_series = frame["session_id"].map(_resume_cell_text)
    parent_series = frame["resume_parent_session_id"].map(_resume_cell_text)
    mask = (
        status_series.eq("max_iterations")
        & parent_series.eq("")
        & ~session_series.isin(resumed_parent_ids)
    )
    candidates = frame[mask].copy()
    if candidates.empty:
        return candidates
    return candidates.sort_values("last_modified", ascending=False, na_position="last")


def _selected_builder_resume_model() -> str:
    session_state = getattr(st, "session_state", {})
    for key in ("builder_model_single_llm", "builder_model_select", "builder_model_effective"):
        value = _resume_cell_text(session_state.get(key) if hasattr(session_state, "get") else "")
        if value:
            return value
    return ""


def _builder_resume_runtime_settings() -> dict[str, Any]:
    session_state = getattr(st, "session_state", {})
    get_state = session_state.get if hasattr(session_state, "get") else lambda key, default=None: default
    try:
        keep_alive_minutes = int(get_state("builder_keep_alive_minutes", 20) or 20)
    except (TypeError, ValueError):
        keep_alive_minutes = 20
    return {
        "ollama_host": _resume_cell_text(get_state("builder_ollama_host", "")) or "http://127.0.0.1:11434",
        "keep_alive_minutes": max(0, keep_alive_minutes),
        "llm_inference_global_settings": (
            dict(get_state("llm_inference_global_settings", {}) or {})
            if isinstance(get_state("llm_inference_global_settings", {}), dict)
            else {}
        ),
        "llm_inference_model_profiles": (
            dict(get_state("llm_inference_model_profiles", {}) or {})
            if isinstance(get_state("llm_inference_model_profiles", {}), dict)
            else {}
        ),
    }


def _run_builder_max_iterations_resume_batch(
    candidates_df: pd.DataFrame,
    *,
    model: str,
    mode: str,
    status_callback: Any = None,
) -> dict[str, Any]:
    from agents.strategy_builder import StrategyBuilder
    from data.loader import load_ohlcv
    from ui.builder_runtime import build_builder_base_llm_config

    runtime_settings = _builder_resume_runtime_settings()
    llm_config = build_builder_base_llm_config(
        model=model,
        ollama_host=runtime_settings["ollama_host"],
        keep_alive_minutes=runtime_settings["keep_alive_minutes"],
        llm_inference_global_settings=runtime_settings["llm_inference_global_settings"],
        llm_inference_model_profiles=runtime_settings["llm_inference_model_profiles"],
    )
    results: list[dict[str, Any]] = []
    total = len(candidates_df)
    for offset, row in enumerate(candidates_df.to_dict("records"), start=1):
        session_id = _resume_cell_text(row.get("session_id"))
        symbol = _resume_cell_text(row.get("symbol"))
        timeframe = _resume_cell_text(row.get("timeframe"))
        summary_path = _resume_cell_text(row.get("summary_path"))
        if callable(status_callback):
            status_callback(offset, total, session_id)
        if not summary_path or not Path(summary_path).exists():
            results.append({"session_id": session_id, "status": "skipped", "reason": "summary_missing"})
            continue
        if not symbol or not timeframe:
            results.append({"session_id": session_id, "status": "skipped", "reason": "market_context_missing"})
            continue
        try:
            data = load_ohlcv(symbol, timeframe)
            builder = StrategyBuilder(
                llm_config=llm_config,
                backtest_completed_callback=_maybe_auto_save_run,
            )
            session = builder.resume_from_summary(
                summary_path,
                data,
                mode="exact_continue" if mode == "exact_continue" else "objective_restart",
                extra_iterations=10,
                restart_max_iterations=20,
            )
            results.append(
                {
                    "session_id": session_id,
                    "status": "resumed",
                    "new_session_id": session.session_id,
                    "resume_mode": session.resume_mode,
                    "total_iterations": len(session.iterations),
                },
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "session_id": session_id,
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                },
            )
    return {
        "total": total,
        "resumed": sum(1 for row in results if row.get("status") == "resumed"),
        "skipped": sum(1 for row in results if row.get("status") == "skipped"),
        "errors": sum(1 for row in results if row.get("status") == "error"),
        "rows": results,
    }


def _render_builder_max_iterations_resume_panel(builder_df: pd.DataFrame) -> None:
    candidates = _collect_builder_max_iteration_resume_candidates(builder_df)
    if candidates.empty:
        return

    selected_model = _selected_builder_resume_model()
    with st.expander(
        f"Reprendre les sessions max_iterations ({len(candidates)})",
        expanded=False,
    ):
        st.caption(
            "Fonction séparée du Builder standard: elle relance uniquement les sessions terminées en "
            "`max_iterations` qui n'ont pas déjà une session enfant de reprise."
        )
        preview_columns = [
            column
            for column in [
                "session_id",
                "symbol",
                "timeframe",
                "total_iterations",
                "best_return_pct",
                "positive_iterations",
                "model_name",
                "last_modified",
                "objective_excerpt",
            ]
            if column in candidates.columns
        ]
        st.dataframe(candidates[preview_columns], width="stretch", hide_index=True)
        st.caption(f"Modèle utilisé pour la reprise: `{selected_model or 'aucun modèle sélectionné'}`")
        mode = st.radio(
            "Mode de reprise",
            options=["exact_continue", "objective_restart"],
            format_func=lambda value: (
                "Reprendre après la dernière itération (+10)"
                if value == "exact_continue"
                else "Relancer depuis l'objectif (20 itérations max)"
            ),
            horizontal=True,
            key="results-store-builder-resume-mode",
        )
        confirmed = st.checkbox(
            "Confirmer la reprise batch de toutes les sessions max_iterations listées",
            value=False,
            key="results-store-builder-resume-confirm",
        )
        disabled = not selected_model or not confirmed
        if st.button(
            "Reprendre toutes les max_iterations",
            key="results-store-builder-resume-all",
            disabled=disabled,
            width="stretch",
        ):
            progress = st.progress(0.0)
            status_line = st.empty()

            def _update(offset: int, total: int, session_id: str) -> None:
                progress.progress(min(offset / max(total, 1), 1.0))
                status_line.caption(f"Reprise {offset}/{total}: `{session_id}`")

            result = _run_builder_max_iterations_resume_batch(
                candidates,
                model=selected_model,
                mode=str(mode),
                status_callback=_update,
            )
            progress.progress(1.0)
            if result["errors"]:
                st.warning(
                    f"Reprise terminée avec erreurs: {result['resumed']} reprises, "
                    f"{result['skipped']} ignorées, {result['errors']} erreurs."
                )
            else:
                st.success(
                    f"Reprise terminée: {result['resumed']} sessions reprises, "
                    f"{result['skipped']} ignorées."
                )
            st.dataframe(pd.DataFrame(result["rows"]), width="stretch", hide_index=True)


def _render_builder_tab(
    builder_df: pd.DataFrame,
    builder_iterations_df: pd.DataFrame,
    results_root: Path,
    builder_catalog_audit: dict[str, Any],
) -> None:
    st.markdown("### Sessions Builder")
    if builder_df.empty:
        st.info("Aucune session Builder detectee dans le store externe.")
        return

    st.caption("Chaque ligne ci-dessous correspond à un dossier de session Builder détecté dans `_builder_sessions`.")
    _render_builder_catalog_audit(builder_catalog_audit)
    _render_builder_max_iterations_resume_panel(builder_df)

    filtered = builder_df.copy()
    filtered["status_label"] = filtered["status"].map(_builder_status_label)
    search_term = st.text_input(
        "Recherche session / recette / objectif",
        placeholder="session id, symbole, objectif, statut...",
        key="results-store-builder-search",
    ).strip()
    status_options = sorted(filtered["status"].dropna().astype(str).unique().tolist())
    selected_status = st.multiselect(
        "Statuts Builder",
        options=status_options,
        default=status_options,
        format_func=_builder_status_label,
        key="results-store-builder-status",
    )
    if selected_status:
        filtered = filtered[filtered["status"].astype(str).isin(selected_status)]
    if search_term:
        lower_term = search_term.lower()
        filtered = filtered[
            filtered["session_id"].astype(str).str.lower().str.contains(lower_term, na=False)
            | filtered["objective"].astype(str).str.lower().str.contains(lower_term, na=False)
            | filtered["status"].astype(str).str.lower().str.contains(lower_term, na=False)
            | filtered["status_label"].astype(str).str.lower().str.contains(lower_term, na=False)
        ]

    filtered = filtered.sort_values("last_modified", ascending=False, na_position="last")
    display_filtered = filtered.copy()
    display_filtered["status"] = display_filtered["status_label"]
    st.dataframe(
        display_filtered[
            [
                "session_id",
                "status",
                "best_return_pct",
                "best_return_iteration",
                "positive_iterations",
                "positive_iteration_summary",
                "best_sharpe",
                "total_iterations",
                "strategy_versions",
                "last_modified",
                "objective_excerpt",
            ]
        ],
        width="stretch",
        hide_index=True,
    )

    if filtered.empty:
        st.info("Aucune session Builder ne correspond aux filtres.")
        return

    selected_session_id = st.selectbox(
        "Explorer une session Builder",
        options=filtered["session_id"].tolist(),
        key="results-store-builder-select",
    )
    selected_row = filtered[filtered["session_id"] == selected_session_id].iloc[0].to_dict()
    session_dir = Path(str(selected_row.get("session_dir") or ""))
    summary_path = Path(str(selected_row.get("summary_path") or ""))
    pipeline_traces_path = Path(str(selected_row.get("pipeline_traces_path") or ""))
    latest_strategy_path = Path(str(selected_row.get("latest_strategy_path") or ""))

    info_cols = st.columns(6)
    info_cols[0].metric("Statut", _builder_status_label(selected_row.get("status")))
    info_cols[1].metric("Best return %", f"{_display_float(selected_row.get('best_return_pct')):.2f}")
    info_cols[2].metric("Best sharpe", f"{_display_float(selected_row.get('best_sharpe')):.2f}")
    info_cols[3].metric("Iterations", _display_int(selected_row.get("total_iterations")))
    info_cols[4].metric("Retours positifs", _display_int(selected_row.get("positive_iterations")))
    info_cols[5].metric(
        "Traces live",
        "oui" if bool(selected_row.get("instrumentation_enabled")) else "non",
    )
    best_return_iteration = coerce_metric_int(selected_row.get("best_return_iteration"), default=None)
    st.caption(
        "Fichiers stratégie: "
        f"{_display_int(selected_row.get('strategy_versions'))}"
        + (
            f" | best iter: {best_return_iteration}"
            if best_return_iteration is not None and best_return_iteration > 0
            else ""
        ),
    )
    if str(selected_row.get("positive_iteration_summary") or "").strip():
        st.caption(f"Itérations positives: {selected_row.get('positive_iteration_summary')}")

    st.caption(str(session_dir))
    st.caption(
        "Mode: "
        f"{selected_row.get('builder_execution_mode') or 'mono_single_llm'} | "
        f"Famille: {selected_row.get('orchestration_mode') or 'single_llm'}",
    )
    if selected_row.get("objective"):
        st.markdown("**Recette / objectif source**")
        st.write(str(selected_row["objective"]))

    action_cols = st.columns(5)
    with action_cols[0]:
        _handle_open_action(
            session_dir, button_label="Ouvrir dossier session", key=f"open-session-{selected_session_id}",
        )
    with action_cols[1]:
        if str(selected_row.get("summary_path") or ""):
            _handle_open_action(
                summary_path, button_label="Ouvrir session_summary.json", key=f"open-summary-{selected_session_id}",
            )
    with action_cols[2]:
        if str(selected_row.get("pipeline_traces_path") or ""):
            _handle_open_action(
                pipeline_traces_path,
                button_label="Ouvrir pipeline_traces.json",
                key=f"open-traces-{selected_session_id}",
            )
    with action_cols[3]:
        if str(selected_row.get("latest_strategy_path") or ""):
            _handle_open_action(
                latest_strategy_path, button_label="Ouvrir strategy.py", key=f"open-strategy-{selected_session_id}",
            )
    with action_cols[4]:
        _handle_open_action(
            results_root, button_label="Ouvrir dossier résultats", key=f"open-results-{selected_session_id}",
        )

    preview_candidates = {
        "session_summary.json": summary_path,
        "pipeline_traces.json": pipeline_traces_path,
        "strategy.py": latest_strategy_path,
        "leaderboard_builder.md": session_dir / "leaderboard_builder.md",
        "leaderboard_builder.csv": session_dir / "leaderboard_builder.csv",
    }
    preview_candidates = {
        label: path for label, path in preview_candidates.items() if path and path.exists() and path.is_file()
    }
    if preview_candidates:
        preview_label = st.selectbox(
            "Apercu fichier session",
            options=list(preview_candidates.keys()),
            key=f"preview-file-{selected_session_id}",
        )
        preview_path = preview_candidates[preview_label]
        preview_text = _read_preview(preview_path)
        language = "python" if preview_path.suffix == ".py" else "json" if preview_path.suffix == ".json" else "text"
        st.code(preview_text or "Aucun apercu disponible.", language=language)

    st.markdown("**Détail des itérations de cette session**")
    session_iterations_df = builder_iterations_df[
        builder_iterations_df["session_id"].astype(str) == str(selected_session_id)
    ].copy() if not builder_iterations_df.empty and "session_id" in builder_iterations_df.columns else pd.DataFrame()
    if session_iterations_df.empty:
        st.info("Aucune itération détaillée disponible pour cette session.")
    else:
        positive_only_session = st.checkbox(
            "Afficher uniquement les itérations positives de cette session",
            value=False,
            key=f"results-store-builder-session-positive-only-{selected_session_id}",
        )
        if positive_only_session and "positive_return" in session_iterations_df.columns:
            session_iterations_df = session_iterations_df[session_iterations_df["positive_return"] == True]  # noqa: E712
        session_iterations_df = session_iterations_df.sort_values(
            ["return_pct", "sharpe", "iteration"],
            ascending=[False, False, True],
            na_position="last",
        )
        display_iteration_cols = [
            column
            for column in [
                "iteration",
                "leaderboard_rank",
                "return_pct",
                "sharpe",
                "profit_factor",
                "max_drawdown_pct",
                "trades",
                "decision",
                "diagnostic_category",
                "params_used_preview",
            ]
            if column in session_iterations_df.columns
        ]
        st.dataframe(session_iterations_df[display_iteration_cols], width="stretch", hide_index=True)

    st.markdown("**Comparer deux sessions instrumentées**")
    comparison_candidates = filtered[filtered["session_id"] != selected_session_id]["session_id"].tolist()
    if not comparison_candidates:
        st.info("Aucune autre session Builder disponible pour une comparaison.")
    else:
        compare_session_id = st.selectbox(
            "Session de référence",
            options=comparison_candidates,
            key=f"compare-builder-session-{selected_session_id}",
        )
        compare_row = filtered[filtered["session_id"] == compare_session_id].iloc[0].to_dict()
        if st.button(
            "Comparer les traces de flux",
            key=f"compare-builder-traces-button-{selected_session_id}",
            disabled=DivergenceAnalyzer is None,
        ):
            if not bool(selected_row.get("instrumentation_enabled")) or not bool(
                compare_row.get("instrumentation_enabled"),
            ):
                st.warning("Les deux sessions doivent avoir l'analyse de flux activée.")
            elif str(selected_row.get("builder_execution_mode") or "") != str(
                compare_row.get("builder_execution_mode") or "",
            ):
                st.warning(
                    "Comparaison refusée: les sessions n'utilisent pas le même `builder_execution_mode`.",
                )
            else:
                trace_a_payload = _safe_read_json(Path(str(selected_row.get("pipeline_traces_path") or "")))
                trace_b_payload = _safe_read_json(Path(str(compare_row.get("pipeline_traces_path") or "")))
                trace_a = _select_reference_trace(trace_a_payload)
                trace_b = _select_reference_trace(trace_b_payload)
                if trace_a is None or trace_b is None:
                    st.warning("Impossible de charger une trace de référence dans l'une des deux sessions.")
                else:
                    analyzer = DivergenceAnalyzer()
                    divergences = analyzer.compare(trace_a, trace_b)
                    root_phase = analyzer.root_cause_phase(divergences)
                    st.caption(
                        f"Phase racine probable: `{root_phase}` | "
                        f"trace A=`{selected_session_id}` vs trace B=`{compare_session_id}`",
                    )
                    st.code(analyzer.format_report(divergences), language="text")

    linked_runs_df = _load_builder_linked_runs_df(str(results_root), selected_session_id)
    st.markdown("**Runs catalogués reliés à cette session**")
    if linked_runs_df.empty:
        st.info("Aucun run catalogué relié à cette session Builder.")
    else:
        display_cols = [
            column
            for column in [
                "timestamp",
                "run_id",
                "strategy",
                "symbol",
                "timeframe",
                "status",
                "metrics_total_return_pct",
                "metrics_sharpe_ratio",
                "metrics_profit_factor",
                "metrics_total_trades",
                "extra_builder_iteration",
            ]
            if column in linked_runs_df.columns
        ]
        st.dataframe(linked_runs_df[display_cols], width="stretch", hide_index=True)


def _render_artifacts_tab(inventory_df: pd.DataFrame, analysis_files_df: pd.DataFrame) -> None:
    st.markdown("### Artefacts centralises")
    if inventory_df.empty:
        st.info("Aucun dossier d'artefacts detecte.")
    else:
        st.dataframe(inventory_df, width="stretch", hide_index=True)

    st.markdown("### Fichiers d'analyse")
    if analysis_files_df.empty:
        st.info("Aucun fichier genere dans `_analysis`.")
        return

    st.dataframe(analysis_files_df, width="stretch", hide_index=True)
    selected_analysis = st.selectbox(
        "Apercu artefact d'analyse",
        options=analysis_files_df["name"].tolist(),
        key="results-store-analysis-select",
    )
    selected_row = analysis_files_df[analysis_files_df["name"] == selected_analysis].iloc[0].to_dict()
    selected_path = Path(str(selected_row["path"]))
    action_cols = st.columns(2)
    with action_cols[0]:
        _handle_open_action(selected_path, button_label="Ouvrir fichier", key=f"open-analysis-file-{selected_analysis}")
    with action_cols[1]:
        _handle_open_action(
            selected_path.parent, button_label="Ouvrir dossier _analysis", key=f"open-analysis-dir-{selected_analysis}",
        )
    preview_text = _read_preview(selected_path)
    language = "html" if selected_path.suffix == ".html" else "text"
    st.code(preview_text or "Aucun apercu disponible.", language=language)


def _render_model_classification_tab() -> None:
    st.markdown("### Classement des modeles Builder")
    st.caption(
        "Stats Builder-only, calculees depuis l'historique autonome et alignees avec la page dediee des statistiques des modeles.",
    )
    scope_label = st.radio(
        "Perimetre",
        options=["Fenetre active", "Historique complet"],
        horizontal=True,
        key="results-store-model-scope",
    )
    scope = "active" if scope_label == "Fenetre active" else "full"
    report = _load_model_classification_report(scope)
    overview = dict(report.get("overview", {}) or {})
    rows_df = pd.DataFrame(list(report.get("builder_rows", []) or []))

    metric_cols = st.columns(5)
    metric_cols[0].metric("Modeles", len(rows_df))
    metric_cols[1].metric("Sessions", _display_int(overview.get("sessions", 0)))
    metric_cols[2].metric("Retours positifs", _display_int(overview.get("positive_returns", 0)))
    metric_cols[3].metric("Succes", _display_int(overview.get("success_status", 0)))
    metric_cols[4].metric("Max iterations", _display_int(overview.get("max_iterations_status", 0)))

    if rows_df.empty:
        st.info("Aucune statistique Builder par modele disponible pour le moment.")
        return

    display_cols = [
        column
        for column in [
            "model",
            "sessions",
            "positive_returns",
            "positive_rate_pct",
            "expected_return_per_hour_pct",
            "sessions_per_hour",
            "avg_session_duration_s",
            "success_status",
            "success_rate_pct",
            "negative_returns",
            "max_iterations_status",
            "error_status",
            "avg_return_pct",
            "median_return_pct",
            "best_return_pct",
            "worst_return_pct",
            "avg_sharpe",
            "best_sharpe",
            "avg_trades",
            "profiles",
            "symbols",
            "timeframes",
            "first_session_id",
            "last_session_id",
        ]
        if column in rows_df.columns
    ]
    st.caption(
        "Productivité: `profit/heure` = return moyen par session × sessions/heure × taux de retours positifs. "
        "Les sessions anciennes sans durée restent exclues de ce calcul.",
    )
    st.dataframe(rows_df[display_cols], width="stretch", hide_index=True)


def render_results_store_page() -> None:
    results_root = Path(get_results_root_dir())
    artifacts_root = Path(get_artifacts_root_dir())
    builder_root = Path(get_builder_sessions_dir())
    analysis_root = Path(get_results_analysis_dir())

    inventory_df = _load_store_inventory_df(str(results_root), str(artifacts_root))
    builder_df = _load_builder_sessions_df(str(builder_root))
    builder_iterations_df = _load_builder_iterations_df(str(builder_root))
    analysis_files_df = _load_analysis_files_df(str(analysis_root))
    builder_catalog_audit = _load_builder_catalog_reconciliation(str(builder_root), str(results_root))

    st.title("📚 Hub resultats")
    st.caption(
        "Page dediee au store centralise: catalogues, runs, sessions Builder, analyses et artefacts.",
    )

    _render_store_summary(
        results_root=results_root,
        artifacts_root=artifacts_root,
        inventory_df=inventory_df,
        builder_df=builder_df,
        analysis_files_df=analysis_files_df,
        builder_catalog_audit=builder_catalog_audit,
    )

    tabs = st.tabs(
        [
            "Catalogue global",
            "Sessions Builder",
            "Classement modeles",
            "Artefacts",
        ],
    )

    with tabs[0]:
        render_results_hub(embedded=True)

    with tabs[1]:
        _render_builder_tab(builder_df, builder_iterations_df, results_root, builder_catalog_audit)

    with tabs[2]:
        _render_model_classification_tab()

    with tabs[3]:
        _render_artifacts_tab(inventory_df, analysis_files_df)


__all__ = [
    "collect_analysis_files",
    "collect_builder_linked_runs",
    "collect_builder_catalog_reconciliation",
    "collect_builder_iterations",
    "collect_builder_sessions",
    "collect_store_inventory",
    "render_results_store_page",
]
