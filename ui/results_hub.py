"""Module-ID: ui.results_hub

Purpose: Vue centralisee des resultats (backtests, sweeps, grids, runs LLM).

Role in pipeline: reporting / catalog

Key components: render_results_hub

Inputs: catalogues CSV, session_state last run

Outputs: Page Streamlit avec dernier run + catalogue filtrable

Dependencies: pandas, streamlit, backtest.storage, utils.run_tracker

Conventions: Non-destructif, lecture des catalogues CSV

Read-if: Ajout d'une page de synthese des resultats.

Skip-if: Vous utilisez seulement ui.results.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)

import pandas as pd
import streamlit as st

try:
    import plotly.express as px

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

from backtest.result_store import get_builder_sessions_dir, get_results_root_dir, get_saved_runs_dir
from backtest.storage import ResultStorage
from catalog.strategy_catalog import CATEGORY_ORDER, list_entries, upsert_from_saved_run
from ui.helpers import (
    as_listish,
    coerce_metric_float,
    coerce_metric_int,
    compute_period_days,
    first_present_non_empty,
    format_pnl_with_daily,
)
from utils.run_tracker import RunTracker

RESULTS_DIR = get_results_root_dir()
RUNS_DIR = get_saved_runs_dir()
GRADUATION_RESULTS_DIR = Path("catalog/graduation_results")
FULL_GRADUATION_PROGRESS_FILENAME = "graduation_full_progress.json"
FULL_GRADUATION_LOG_FILENAME = "graduation_full_run.log"
GRADUATION_P1_LOG_FILENAME = "graduation_p1_run.log"
POSITIVE_ARTIFACTS_IMPORT_LOG_FILENAME = "positive_artifacts_import.log"
POSITIVE_IMPORTS_PROGRESS_FILENAME = "positive_imports_progress.json"
POSITIVE_IMPORTS_LOG_FILENAME = "positive_imports_run.log"
GRADUATION_PROGRESS_FILENAMES = (
    FULL_GRADUATION_PROGRESS_FILENAME,
    POSITIVE_IMPORTS_PROGRESS_FILENAME,
)

CHART_MODE_COLUMNS = "Colonnes"
CHART_MODE_POINTS = "Points"
GRADUATION_PREVIEW_LIMIT = 12
GRADUATION_PHASE_FOCUS_AUTO = "Auto"


_CATALOG_CSV_DTYPE: dict[str, str] = {
    "run_id": "str",
    "strategy": "str",
    "symbol": "str",
    "timeframe": "str",
    "status": "str",
    "category": "str",
    "n_bars": "str",
    "n_trades": "str",
    "source_run_id": "str",
}


def _safe_read_csv(path: Path, dtype: dict[str, str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False, dtype=dtype or _CATALOG_CSV_DTYPE)
    except Exception as exc:
        logger.warning("Failed to read CSV %s: %s", path, exc)
        return pd.DataFrame()


def _clean_text_token(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


def _normalize_graduation_candidate_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()

    for text_col in ("phase", "decision", "source_kind"):
        if text_col in df.columns:
            df[text_col] = df[text_col].apply(_clean_text_token)

    context_col_map = {
        "configured_contexts": "configured_context_count",
        "loaded_contexts": "loaded_context_count",
        "missing_contexts": "missing_context_count",
    }
    for source_col, count_col in context_col_map.items():
        if source_col not in df.columns:
            continue
        if count_col in df.columns:
            numeric_counts = pd.to_numeric(df[count_col], errors="coerce")
            missing_mask = numeric_counts.isna()
            if missing_mask.any():
                df.loc[missing_mask, count_col] = df.loc[missing_mask, source_col].apply(
                    lambda value: len(as_listish(value)),
                )
        else:
            df[count_col] = df[source_col].apply(lambda value: len(as_listish(value)))

    if "tested_timeframes" in df.columns and "timeframes_tested" not in df.columns:
        df["timeframes_tested"] = df["tested_timeframes"].apply(
            lambda value: ",".join(sorted(as_listish(value))),
        )

    if "benchmark_results" in df.columns:

        def _benchmark_names(value: Any) -> list[str]:
            if isinstance(value, dict):
                return sorted(str(name).strip() for name in value.keys() if str(name).strip())
            return []

        def _benchmark_tokens(value: Any) -> list[str]:
            tokens: list[str] = []
            if not isinstance(value, dict):
                return tokens
            for payload in value.values():
                if not isinstance(payload, dict):
                    continue
                for token in payload.get("tokens", []) or []:
                    token_str = str(token).strip()
                    if token_str and token_str not in tokens:
                        tokens.append(token_str)
            return sorted(tokens)

        benchmark_names = df["benchmark_results"].apply(_benchmark_names)
        if "tested_benchmark_names" not in df.columns:
            df["tested_benchmark_names"] = benchmark_names.apply(lambda names: ",".join(names))
        if "configured_benchmark_count" not in df.columns:
            df["configured_benchmark_count"] = benchmark_names.apply(len)
        if "tested_tokens" not in df.columns:
            df["tested_tokens"] = df["benchmark_results"].apply(lambda value: ",".join(_benchmark_tokens(value)))

    if "benchmark_consensus" in df.columns:

        def _consensus_value(value: Any, key: str, default: Any = None) -> Any:
            if isinstance(value, dict):
                return value.get(key, default)
            return default

        if "required_benchmark_name" not in df.columns:
            df["required_benchmark_name"] = df["benchmark_consensus"].apply(
                lambda value: str(_consensus_value(value, "required_benchmark_name", "") or "").strip(),
            )
        if "required_benchmark_passed" not in df.columns:
            df["required_benchmark_passed"] = df["benchmark_consensus"].apply(
                lambda value: bool(_consensus_value(value, "required_passed", False)),
            )
        if "passed_benchmark_names" not in df.columns:
            df["passed_benchmark_names"] = df["benchmark_consensus"].apply(
                lambda value: ",".join(sorted(as_listish(_consensus_value(value, "benchmarks_passed", [])))),
            )
        if "benchmark_pass_summary" not in df.columns:
            df["benchmark_pass_summary"] = df["benchmark_consensus"].apply(
                lambda value: (
                    f"{len(as_listish(_consensus_value(value, 'benchmarks_passed', [])))}/"
                    f"{int(_consensus_value(value, 'benchmarks_total', 0) or 0)}"
                    if int(_consensus_value(value, "benchmarks_total", 0) or 0) > 0
                    else ""
                ),
            )
        if "contradiction_state" not in df.columns:

            def _state(value: Any) -> str:
                if not isinstance(value, dict):
                    return ""
                if bool(value.get("consensus_passed")):
                    return "passed"
                if bool(value.get("contradicted")):
                    return "contradicted"
                return "failed"

            df["contradiction_state"] = df["benchmark_consensus"].apply(_state)

    if "multi_ctx_results" in df.columns:

        def _ctx_metric(value: Any, key: str) -> int:
            if isinstance(value, dict):
                try:
                    return int(value.get(key) or 0)
                except Exception:
                    return 0
            return 0

        if "passed_context_count" not in df.columns:
            df["passed_context_count"] = df["multi_ctx_results"].apply(lambda value: _ctx_metric(value, "passed_count"))
        if "total_context_count" not in df.columns:
            df["total_context_count"] = df["multi_ctx_results"].apply(
                lambda value: _ctx_metric(value, "total_contexts"),
            )
        if "configured_context_count" not in df.columns:
            df["configured_context_count"] = df["multi_ctx_results"].apply(
                lambda value: _ctx_metric(value, "configured_context_count"),
            )
        if "loaded_context_count" not in df.columns:
            df["loaded_context_count"] = df["multi_ctx_results"].apply(
                lambda value: _ctx_metric(value, "loaded_context_count"),
            )
        if "eligible_context_count" not in df.columns:
            df["eligible_context_count"] = df["multi_ctx_results"].apply(
                lambda value: _ctx_metric(value, "eligible_context_count"),
            )
        if "configured_benchmark_slot_count" not in df.columns:
            df["configured_benchmark_slot_count"] = df["multi_ctx_results"].apply(
                lambda value: _ctx_metric(value, "configured_benchmark_slots"),
            )
        if "loaded_benchmark_slot_count" not in df.columns:
            df["loaded_benchmark_slot_count"] = df["multi_ctx_results"].apply(
                lambda value: _ctx_metric(value, "loaded_benchmark_slots"),
            )
        if "excluded_context_count" not in df.columns:
            df["excluded_context_count"] = df["multi_ctx_results"].apply(
                lambda value: _ctx_metric(value, "excluded_context_count"),
            )
        if "configured_unique_coverage_pct" not in df.columns:
            configured_counts = pd.to_numeric(df.get("configured_context_count"), errors="coerce")
            eligible_counts = pd.to_numeric(df.get("eligible_context_count"), errors="coerce")
            df["configured_unique_coverage_pct"] = [
                round((float(eligible) / float(configured)) * 100, 1)
                if pd.notna(configured) and float(configured) > 0 and pd.notna(eligible)
                else None
                for configured, eligible in zip(configured_counts, eligible_counts)
            ]
        if "benchmark_slot_coverage_pct" not in df.columns:
            configured_slots = pd.to_numeric(df.get("configured_benchmark_slot_count"), errors="coerce")
            loaded_slots = pd.to_numeric(df.get("loaded_benchmark_slot_count"), errors="coerce")
            df["benchmark_slot_coverage_pct"] = [
                round((float(loaded) / float(configured)) * 100, 1)
                if pd.notna(configured) and float(configured) > 0 and pd.notna(loaded)
                else None
                for configured, loaded in zip(configured_slots, loaded_slots)
            ]
        if "context_pass_summary" not in df.columns:
            df["context_pass_summary"] = df.apply(
                lambda row: (
                    f"{int(pd.to_numeric(row.get('passed_context_count'), errors='coerce') or 0)}/"
                    f"{int(pd.to_numeric(row.get('total_context_count'), errors='coerce') or 0)}"
                    if int(pd.to_numeric(row.get("total_context_count"), errors="coerce") or 0) > 0
                    else ""
                ),
                axis=1,
            )

    numeric_cols = [
        "best_return_pct",
        "best_profit_factor",
        "best_sharpe",
        "best_trades",
        "best_max_drawdown_pct",
        "best_win_rate_pct",
        "configured_context_count",
        "loaded_context_count",
        "missing_context_count",
        "eligible_context_count",
        "configured_benchmark_count",
        "configured_benchmark_slot_count",
        "loaded_benchmark_slot_count",
        "excluded_context_count",
        "passed_context_count",
        "total_context_count",
        "coverage_pct",
        "configured_unique_coverage_pct",
        "benchmark_slot_coverage_pct",
        "sweep_robustness_pct",
        "sensitivity_history_bars",
        "sensitivity_min_history_bars",
        "wfa_stability",
        "wfa_avg_test_return_pct",
        "wfa_avg_test_sharpe",
        "wfa_overfitting_ratio",
        "wfa_classic_overfitting_ratio",
        "wfa_robust_overfitting_score",
        "wfa_valid_folds",
        "wfa_positive_folds_pct",
        "wfa_history_bars",
        "wfa_min_history_bars",
    ]
    df = _coerce_numeric(df, numeric_cols)
    return df


def _load_candidate_report(*filenames: str) -> tuple[dict[str, Any], pd.DataFrame]:
    for name in filenames:
        path = GRADUATION_RESULTS_DIR / name
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        candidates = payload.get("candidates") or []
        df = pd.DataFrame(candidates)
        if not df.empty:
            df = _normalize_graduation_candidate_df(df)
        payload["_report_path"] = str(path)
        return payload, df
    return {}, pd.DataFrame()


def _load_graduation_report() -> tuple[dict[str, Any], pd.DataFrame]:
    return _load_candidate_report("graduation_full.json", "graduation_p1.json")


def _load_positive_import_report() -> tuple[dict[str, Any], pd.DataFrame]:
    return _load_candidate_report("positive_imports_graduation.json", "positive_artifacts_import.json")


def _report_has_source_validation_fields(df: pd.DataFrame) -> bool:
    if df.empty:
        return True
    return any(
        column in df.columns
        for column in (
            "wfa_scope",
            "wfa_symbol",
            "wfa_timeframe",
            "wfa_history_bars",
            "sensitivity_scope",
        )
    )


def _graduation_cli_command(args: list[str]) -> str:
    return " ".join(["python", "-m", "catalog.graduation", *[str(arg) for arg in args]])


def _payload_meta(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    meta = payload.get("meta")
    return meta if isinstance(meta, dict) else {}


def _payload_cli_equivalent(*payloads: dict[str, Any] | None) -> str:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        value = str(payload.get("cli_equivalent") or "").strip()
        if value:
            return value
        meta_value = str(_payload_meta(payload).get("cli_equivalent") or "").strip()
        if meta_value:
            return meta_value
    return ""


def _payload_phase_contract(*payloads: dict[str, Any] | None) -> dict[str, Any]:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        value = payload.get("phase_contract")
        if isinstance(value, dict) and value:
            return value
        meta_value = _payload_meta(payload).get("phase_contract")
        if isinstance(meta_value, dict) and meta_value:
            return meta_value
    return {}


def _payload_config_snapshot(*payloads: dict[str, Any] | None) -> dict[str, Any]:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        value = payload.get("config_snapshot")
        if isinstance(value, dict) and value:
            return value
        meta_value = _payload_meta(payload).get("config_snapshot")
        if isinstance(meta_value, dict) and meta_value:
            return meta_value
    return {}


def _payload_threshold_sensitivity(*payloads: dict[str, Any] | None) -> dict[str, Any]:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        value = payload.get("threshold_sensitivity")
        if isinstance(value, dict) and value:
            return value
        meta_value = _payload_meta(payload).get("threshold_sensitivity")
        if isinstance(meta_value, dict) and meta_value:
            return meta_value
    return {}


def _load_progress_payload(filename: str) -> dict[str, Any]:
    path = GRADUATION_RESULTS_DIR / filename
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    payload["_progress_path"] = str(path)
    return payload


def _load_log_tail(filename: str, *, max_lines: int = 25) -> str:
    path = GRADUATION_RESULTS_DIR / filename
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-max_lines:])


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
    except (TypeError, AttributeError):
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def _phase_processed_counts(
    stats: dict[str, Any],
    total_candidates: int,
    *,
    infer_missing: bool = True,
) -> dict[str, int]:
    if not infer_missing:
        return {
            "P2": _safe_int(stats.get("p2_processed")),
            "P3": _safe_int(stats.get("p3_processed")),
            "P4": _safe_int(stats.get("p4_processed")),
            "P5": _safe_int(stats.get("p5_processed")),
            "P6": _safe_int(stats.get("p6_processed")),
        }
    return {
        "P2": _safe_int(stats.get("p2_processed"), total_candidates),
        "P3": _safe_int(stats.get("p3_processed"), _safe_int(stats.get("p2_survivors"))),
        "P4": _safe_int(stats.get("p4_processed"), _safe_int(stats.get("p3_survivors"))),
        "P5": _safe_int(stats.get("p5_processed"), _safe_int(stats.get("p4_survivors"))),
        "P6": _safe_int(stats.get("p6_processed"), _safe_int(stats.get("p5_survivors"))),
    }


def _phase_survivor_counts(stats: dict[str, Any]) -> dict[str, int]:
    return {
        "P2": _safe_int(stats.get("p2_survivors")),
        "P3": _safe_int(stats.get("p3_survivors")),
        "P4": _safe_int(stats.get("p4_survivors")),
        "P5": _safe_int(stats.get("p5_survivors")),
        "P6": _safe_int(stats.get("p6_promoted")),
    }


def _phase_distribution_counts(payload: dict[str, Any], df: pd.DataFrame | None = None) -> dict[str, int]:
    raw = payload.get("by_phase")
    counts: dict[str, int] = {}
    if isinstance(raw, dict) and raw:
        for key, value in raw.items():
            label = _clean_text_token(key).upper()
            if not label:
                continue
            counts[label] = _safe_int(value)
    elif df is not None and not df.empty and "phase" in df.columns:
        grouped = (
            df["phase"]
            .dropna()
            .astype(str)
            .str.strip()
            .str.upper()
            .value_counts()
            .to_dict()
        )
        counts = {str(key): _safe_int(value) for key, value in grouped.items()}
    for phase in ("P2", "P3", "P4", "P5", "P6"):
        counts.setdefault(phase, 0)
    return counts


def _format_phase_counts(prefix: str, counts: dict[str, int]) -> str:
    parts = [f"{phase}={counts.get(phase, 0)}" for phase in ("P2", "P3", "P4", "P5", "P6")]
    return f"{prefix}: " + " • ".join(parts)


def _resolve_completed_phase(
    payload: dict[str, Any],
    processed_counts: dict[str, int],
    phase_distribution: dict[str, int],
) -> str:
    current_phase = _clean_text_token(payload.get("current_phase")).upper() or "?"
    if _clean_text_token(payload.get("status")).lower() != "completed":
        return current_phase
    for phase in ("P6", "P5", "P4", "P3", "P2"):
        if processed_counts.get(phase, 0) > 0 or phase_distribution.get(phase, 0) > 0:
            return phase
    return current_phase


def _resolve_progress_ratio(
    payload: dict[str, Any],
    display_phase: str,
    processed_counts: dict[str, int],
) -> tuple[int, int]:
    index = _safe_int(payload.get("current_index"))
    total = _safe_int(payload.get("current_total"))
    if _clean_text_token(payload.get("status")).lower() == "completed" and total == 0:
        total = processed_counts.get(display_phase, 0)
        if index == 0:
            index = total
    return index, total


def _progress_age_seconds(updated_at: str) -> float | None:
    if not updated_at:
        return None
    try:
        dt = datetime.fromisoformat(updated_at)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()


def _is_pid_running(pid: Any) -> bool:
    try:
        resolved = int(pid)
    except (TypeError, ValueError):
        return False
    if resolved <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            handle = kernel32.OpenProcess(0x1000, 0, resolved)  # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED still means the PID exists.
        except Exception:
            return False
    try:
        os.kill(resolved, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _background_progress_is_active(payload: dict[str, Any]) -> bool:
    status = str(payload.get("status") or "").strip().lower()
    if status not in {"starting", "running"}:
        return False
    if _is_pid_running(payload.get("pid")):
        return True
    age_seconds = _progress_age_seconds(str(payload.get("updated_at") or ""))
    return bool(age_seconds is not None and age_seconds < 15 and not payload.get("pid"))


def _active_graduation_progresses() -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for filename in GRADUATION_PROGRESS_FILENAMES:
        payload = _load_progress_payload(filename)
        if payload and _background_progress_is_active(payload):
            active.append({"filename": filename, "payload": payload})
    return active


def _progress_status_label(payload: dict[str, Any], age_seconds: float | None) -> str:
    raw_status = str(payload.get("status") or "?").strip() or "?"
    lowered = raw_status.lower()
    if lowered in {"starting", "running"} and not _background_progress_is_active(payload):
        if payload.get("pid"):
            return "processus arrêté"
        if age_seconds is not None and age_seconds > 180:
            return "sans heartbeat"
    return raw_status


def _truncate_rejection_reason(value: Any, *, max_len: int = 140) -> str:
    text = _clean_text_token(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _build_phase_timeline_html(*, current_phase: str, status: str) -> str:
    phase_labels = {
        "P2": "Sandbox",
        "P3": "Consensus benchmarks",
        "P4": "Test de sensibilité",
        "P5": "Walk-forward",
        "P6": "Promotion",
    }
    ordered = ("P2", "P3", "P4", "P5", "P6")
    current = _clean_text_token(current_phase).upper()
    current_index = ordered.index(current) if current in ordered else -1
    completed = _clean_text_token(status).lower() == "completed"
    blocks: list[str] = ["<div class='bc-grad-timeline'>"]
    for idx, phase in enumerate(ordered):
        classes = ["bc-grad-step"]
        if completed or (current_index >= 0 and idx < current_index):
            classes.append("is-done")
        if current_index >= 0 and idx == current_index and not completed:
            classes.append("is-active")
        label = phase_labels[phase]
        blocks.append(
            f"<div class='{' '.join(classes)}'><span class='bc-grad-phase'>{phase}</span>"
            f"<span class='bc-grad-label'>{label}</span></div>",
        )
    blocks.append("</div>")
    return "".join(blocks)


def _build_candidate_report_summary(
    payload: dict[str, Any],
    df: pd.DataFrame,
) -> dict[str, Any]:
    stats = dict(payload.get("stats") or {})
    total_candidates = _safe_int(payload.get("total_candidates"), _safe_int(stats.get("p1_candidates")))
    processed_counts = _phase_processed_counts(stats, total_candidates)
    survivor_counts = _phase_survivor_counts(stats)
    phase_distribution = _phase_distribution_counts(payload, df)
    final_phase = "P1"
    explicit_processed_counts = {
        "P2": _safe_int(stats.get("p2_processed")),
        "P3": _safe_int(stats.get("p3_processed")),
        "P4": _safe_int(stats.get("p4_processed")),
        "P5": _safe_int(stats.get("p5_processed")),
        "P6": _safe_int(stats.get("p6_processed")),
    }
    for phase in ("P6", "P5", "P4", "P3", "P2"):
        if phase_distribution.get(phase, 0) > 0 or explicit_processed_counts.get(phase, 0) > 0:
            final_phase = phase
            break

    dominant_decision = ""
    if not df.empty and "decision" in df.columns:
        decisions = (
            df["decision"].dropna().astype(str).str.strip()
        )
        if not decisions.empty:
            dominant_decision = str(decisions.value_counts().idxmax())

    return {
        "total_candidates": total_candidates,
        "processed_counts": processed_counts,
        "survivor_counts": survivor_counts,
        "phase_distribution": phase_distribution,
        "final_phase": final_phase,
        "dominant_decision": dominant_decision,
        "catalog_synced": _safe_int(stats.get("catalog_synced")),
    }


def _resolve_candidate_phase_focus_default(summary: dict[str, Any], df: pd.DataFrame) -> str:
    phase_distribution = dict(summary.get("phase_distribution") or {})
    available = set()
    if not df.empty and "phase" in df.columns:
        available = {
            str(value).strip().upper()
            for value in df["phase"].dropna().astype(str).tolist()
            if str(value).strip()
        }
    for phase in ("P6", "P5", "P4", "P3", "P2"):
        if phase_distribution.get(phase, 0) > 0 and (not available or phase in available):
            return phase
    final_phase = _clean_text_token(summary.get("final_phase")).upper()
    if final_phase and (not available or final_phase in available):
        return final_phase
    return sorted(available)[-1] if available else "Toutes"


def _resolve_candidate_phase_filter(
    requested_focus: str,
    *,
    summary: dict[str, Any],
    available_phases: list[str],
    df: pd.DataFrame,
) -> str:
    normalized = _clean_text_token(requested_focus)
    if not normalized or normalized == GRADUATION_PHASE_FOCUS_AUTO:
        return _resolve_candidate_phase_focus_default(summary, df)
    if normalized in available_phases:
        return normalized
    return _resolve_candidate_phase_focus_default(summary, df)


def _build_phase_rejection_breakdown(df: pd.DataFrame, phase: str) -> pd.DataFrame:
    if df.empty or "phase" not in df.columns:
        return pd.DataFrame(columns=["reason", "count"])
    filtered = df[df["phase"].astype(str).str.upper() == str(phase or "").upper()].copy()
    if filtered.empty or "rejection_reason" not in filtered.columns:
        return pd.DataFrame(columns=["reason", "count"])

    counts: dict[str, int] = {}
    for raw_reason in filtered["rejection_reason"].fillna("").astype(str):
        lowered = raw_reason.lower()
        matched = False
        if "overfitting" in lowered:
            counts["Overfitting WFA excessif"] = counts.get("Overfitting WFA excessif", 0) + 1
            matched = True
        if "avg_test_sharpe" in lowered or "test_sharpe" in lowered:
            counts["Sharpe test WFA insuffisant"] = counts.get("Sharpe test WFA insuffisant", 0) + 1
            matched = True
        if "instable" in lowered or "stability" in lowered:
            counts["WFA instable"] = counts.get("WFA instable", 0) + 1
            matched = True
        if not matched:
            label = _truncate_rejection_reason(raw_reason, max_len=60) or "Autre"
            counts[label] = counts.get(label, 0) + 1
    if not counts:
        return pd.DataFrame(columns=["reason", "count"])
    return pd.DataFrame(
        [{"reason": reason, "count": count} for reason, count in counts.items()],
    ).sort_values(["count", "reason"], ascending=[False, True], ignore_index=True)


def _build_p3_rejection_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "phase" not in df.columns:
        return pd.DataFrame(columns=["reason", "count"])
    filtered = df[df["phase"].astype(str).str.upper() == "P3"].copy()
    if filtered.empty or "rejection_reason" not in filtered.columns:
        return pd.DataFrame(columns=["reason", "count"])

    counts: dict[str, int] = {}
    for raw_reason in filtered["rejection_reason"].fillna("").astype(str):
        lowered = raw_reason.lower()
        if "required_benchmark_failed" in lowered or "benchmarks=" in lowered:
            counts["Consensus benchmarks insuffisant"] = counts.get("Consensus benchmarks insuffisant", 0) + 1
        if "coverage=" in lowered:
            counts["Couverture éligible insuffisante"] = counts.get("Couverture éligible insuffisante", 0) + 1
    if not counts:
        return pd.DataFrame(columns=["reason", "count"])
    return pd.DataFrame(
        [{"reason": reason, "count": count} for reason, count in counts.items()],
    ).sort_values(["count", "reason"], ascending=[False, True], ignore_index=True)


def _build_p3_required_benchmark_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "phase" not in df.columns or "required_benchmark_name" not in df.columns:
        return pd.DataFrame(columns=["benchmark", "count"])
    filtered = df[df["phase"].astype(str).str.upper() == "P3"].copy()
    if "required_benchmark_passed" in filtered.columns:
        filtered = filtered[filtered["required_benchmark_passed"] != True]  # noqa: E712
    benchmarks = (
        filtered["required_benchmark_name"]
        .fillna("")
        .astype(str)
        .str.strip()
    )
    benchmarks = benchmarks[benchmarks != ""]
    if benchmarks.empty:
        return pd.DataFrame(columns=["benchmark", "count"])
    return (
        benchmarks.value_counts()
        .rename_axis("benchmark")
        .reset_index(name="count")
    )


def _build_p3_diagnostic_summary(payload: dict[str, Any], df: pd.DataFrame) -> dict[str, Any]:
    stats = dict(payload.get("stats") or {})
    filtered = df[df["phase"].astype(str).str.upper() == "P3"].copy() if not df.empty and "phase" in df.columns else df
    row = filtered.iloc[0].to_dict() if isinstance(filtered, pd.DataFrame) and not filtered.empty else {}
    p3_processed = _safe_int(stats.get("p3_processed"))
    p3_survivors = _safe_int(stats.get("p3_survivors"))
    configured_context_count = _safe_int(row.get("configured_context_count"))
    eligible_context_count = _safe_int(row.get("eligible_context_count"))
    loaded_context_count = _safe_int(row.get("loaded_context_count"))
    excluded_context_count = _safe_int(row.get("excluded_context_count"))
    configured_benchmark_slot_count = _safe_int(row.get("configured_benchmark_slot_count"))
    loaded_benchmark_slot_count = _safe_int(row.get("loaded_benchmark_slot_count"))
    eligible_coverage_pct = coerce_metric_float(row.get("coverage_pct"))
    configured_unique_coverage_pct = coerce_metric_float(
        row.get("configured_unique_coverage_pct", row.get("benchmark_slot_coverage_pct")),
    )
    benchmark_slot_coverage_pct = coerce_metric_float(row.get("benchmark_slot_coverage_pct"))
    return {
        "available": bool(p3_processed or (isinstance(filtered, pd.DataFrame) and not filtered.empty)),
        "p3_processed": p3_processed,
        "p3_survivors": p3_survivors,
        "configured_context_count": configured_context_count,
        "eligible_context_count": eligible_context_count,
        "loaded_context_count": loaded_context_count,
        "excluded_context_count": excluded_context_count,
        "configured_benchmark_slot_count": configured_benchmark_slot_count,
        "loaded_benchmark_slot_count": loaded_benchmark_slot_count,
        "eligible_coverage_pct": eligible_coverage_pct,
        "configured_unique_coverage_pct": configured_unique_coverage_pct,
        "benchmark_slot_coverage_pct": benchmark_slot_coverage_pct,
        "no_survivor": bool(p3_processed > 0 and p3_survivors == 0),
    }


def _format_p3_zero_survivor_message(summary: dict[str, Any], reason_df: pd.DataFrame) -> str:
    headline = (
        f"Aucun candidat ne passe P3 sur {int(summary.get('p3_processed', 0) or 0)} candidat(s) traité(s)."
    )
    details = [
        f"Ctx configurés={int(summary.get('configured_context_count', 0) or 0)}",
        f"Ctx éligibles={int(summary.get('eligible_context_count', 0) or 0)}",
        f"Ctx chargés={int(summary.get('loaded_context_count', 0) or 0)}",
    ]
    coverage = summary.get("eligible_coverage_pct")
    if coverage is not None:
        details.append(f"Couverture éligible={float(coverage):.1f}%")
    cfg_cov = summary.get("configured_unique_coverage_pct")
    if cfg_cov is not None:
        details.append(f"Couverture configurée={float(cfg_cov):.1f}%")
    top_reasons = []
    if isinstance(reason_df, pd.DataFrame) and not reason_df.empty:
        top_reasons = [
            f"{row['reason']} ({int(row['count'])})"
            for _, row in reason_df.head(3).iterrows()
        ]
    suffix = f" Causes dominantes: {', '.join(top_reasons)}." if top_reasons else ""
    return f"{headline} {' | '.join(details)}.{suffix}"


def _build_phase_focus_preview_df(df: pd.DataFrame, phase: str) -> pd.DataFrame:
    if df.empty or "phase" not in df.columns:
        return pd.DataFrame()
    filtered = df[df["phase"].astype(str).str.upper() == str(phase or "").upper()].copy()
    if filtered.empty:
        return filtered
    sort_col = "best_return_pct" if "best_return_pct" in filtered.columns else None
    if sort_col:
        filtered = filtered.sort_values(sort_col, ascending=False, na_position="last")
    if "rejection_reason" in filtered.columns:
        filtered["rejection_reason"] = filtered["rejection_reason"].apply(_truncate_rejection_reason)
    common_cols = ["strategy_name", "session_id", "source_symbol", "source_timeframe", "phase", "decision"]
    phase_specific_cols = {
        "P4": ["sweep_robustness_pct", "best_max_drawdown_pct", "best_return_pct", "rejection_reason"],
        "P5": [
            "wfa_stability",
            "wfa_avg_test_return_pct",
            "wfa_avg_test_sharpe",
            "wfa_classic_overfitting_ratio",
            "wfa_robust_overfitting_score",
            "wfa_positive_folds_pct",
            "wfa_confidence_tier",
            "rejection_reason",
        ],
    }
    preferred_cols = common_cols + phase_specific_cols.get(str(phase or "").upper(), ["best_return_pct", "rejection_reason"])
    visible_cols = [col for col in preferred_cols if col in filtered.columns]
    return filtered[visible_cols].head(GRADUATION_PREVIEW_LIMIT).reset_index(drop=True)


def _render_threshold_sensitivity_section(*payloads: dict[str, Any] | None) -> None:
    sensitivity = _payload_threshold_sensitivity(*payloads)
    p5 = sensitivity.get("p5") if isinstance(sensitivity, dict) else {}
    if not isinstance(p5, dict) or not p5.get("available"):
        return

    with st.expander("Sensibilité des seuils P5", expanded=False):
        thresholds = p5.get("current_thresholds") if isinstance(p5.get("current_thresholds"), dict) else {}
        metric_cols = st.columns(4)
        metric_cols[0].metric("Candidats P5", int(p5.get("candidate_count") or 0))
        metric_cols[1].metric("Pass actuels", int(p5.get("observed_pass_count") or 0))
        metric_cols[2].metric("Folds + requis", f"{float(thresholds.get('min_positive_folds_pct') or 0):.0f}%")
        metric_cols[3].metric("Score robuste max", f"{float(thresholds.get('watchlist_max_robust_score') or 0):.0f}")
        st.caption(
            "Simulation conservatrice : rendement test > 0, Sharpe test minimal et seuil dur de folds positifs restent actifs ; "
            "seuls les seuils de folds positifs et de score robuste sont balayés.",
        )

        blocker_counts = p5.get("blocker_counts")
        if isinstance(blocker_counts, dict) and blocker_counts:
            st.dataframe(
                pd.DataFrame([{"blocage": key, "count": value} for key, value in blocker_counts.items()]),
                width="stretch",
                hide_index=True,
            )

        sweep_cols = st.columns(2)
        positive_sweep = p5.get("positive_folds_sweep")
        if isinstance(positive_sweep, list) and positive_sweep:
            sweep_cols[0].caption("Effet du seuil de folds positifs")
            sweep_cols[0].dataframe(pd.DataFrame(positive_sweep), width="stretch", hide_index=True)
        score_sweep = p5.get("robust_score_sweep")
        if isinstance(score_sweep, list) and score_sweep:
            sweep_cols[1].caption("Effet du plafond de score robuste")
            sweep_cols[1].dataframe(pd.DataFrame(score_sweep), width="stretch", hide_index=True)

        combined_grid = p5.get("combined_grid")
        if isinstance(combined_grid, list) and combined_grid:
            with st.expander("Grille combinée folds positifs × score robuste", expanded=False):
                st.dataframe(pd.DataFrame(combined_grid), width="stretch", hide_index=True)

        closest_misses = p5.get("closest_misses")
        if isinstance(closest_misses, list) and closest_misses:
            st.caption("Candidats proches des marges actuelles")
            st.dataframe(pd.DataFrame(closest_misses), width="stretch", hide_index=True)


def _build_candidate_preview_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    filtered = df.copy()
    if "best_return_pct" in filtered.columns:
        filtered = filtered.sort_values("best_return_pct", ascending=False, na_position="last")
    if "rejection_reason" in filtered.columns:
        filtered["rejection_reason"] = filtered["rejection_reason"].apply(_truncate_rejection_reason)
    preferred_cols = [
        "strategy_name",
        "session_id",
        "source_symbol",
        "source_timeframe",
        "phase",
        "decision",
        "best_return_pct",
        "best_sharpe",
        "best_trades",
        "benchmark_pass_summary",
        "context_pass_summary",
        "required_benchmark_name",
        "rejection_reason",
    ]
    visible_cols = [col for col in preferred_cols if col in filtered.columns]
    return filtered[visible_cols].head(GRADUATION_PREVIEW_LIMIT).reset_index(drop=True)


def _resolve_graduation_strategy_folder(row: dict[str, Any]) -> Path | None:
    builder_root = get_builder_sessions_dir()
    strategy_file = _clean_text_token(row.get("strategy_file"))
    session_id = _clean_text_token(row.get("session_id"))
    if strategy_file:
        candidate_path = Path(strategy_file)
        if not candidate_path.is_absolute():
            candidate_path = builder_root / candidate_path
        if candidate_path.exists():
            return candidate_path.parent
    if session_id:
        session_dir = builder_root / session_id
        if session_dir.exists():
            return session_dir
    return None


def _resolve_strategy_catalog_source_folder(row: Mapping[str, Any]) -> Path | None:
    builder_session_id = _clean_text_token(row.get("builder_session_id"))
    if builder_session_id:
        session_dir = Path(get_builder_sessions_dir()) / builder_session_id
        if session_dir.exists():
            return session_dir

    strategy_file = _clean_text_token(row.get("strategy_file"))
    if strategy_file:
        candidate_path = Path(strategy_file)
        if not candidate_path.is_absolute():
            candidate_path = Path.cwd() / candidate_path
        if candidate_path.exists():
            return candidate_path.parent

    source_path = _clean_text_token(row.get("source_path"))
    if not source_path:
        return None

    candidate_path = Path(source_path)
    if candidate_path.is_absolute() and candidate_path.exists():
        return candidate_path if candidate_path.is_dir() else candidate_path.parent

    for root in (Path.cwd(), RESULTS_DIR, RUNS_DIR):
        resolved = root / candidate_path
        if resolved.exists():
            return resolved if resolved.is_dir() else resolved.parent
    return None


def _decorate_strategy_catalog_links(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    decorated = df.copy()

    def _link_for_row(row: pd.Series) -> str:
        strategy_name = _clean_text_token(row.get("strategy")) or _clean_text_token(row.get("entry_id")) or "candidate"
        folder = _resolve_strategy_catalog_source_folder(row.to_dict())
        if folder is None:
            return strategy_name
        return f"{folder.resolve().as_uri()}#{strategy_name}"

    decorated["strategy_name_link"] = decorated.apply(_link_for_row, axis=1)
    return decorated


def _decorate_graduation_strategy_links(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    decorated = df.copy()

    def _link_for_row(row: pd.Series) -> str:
        strategy_name = _clean_text_token(row.get("strategy_name")) or _clean_text_token(row.get("session_id")) or "candidate"
        folder = _resolve_graduation_strategy_folder(row.to_dict())
        if folder is None:
            return strategy_name
        return f"{folder.resolve().as_uri()}#{strategy_name}"

    decorated["strategy_name_link"] = decorated.apply(_link_for_row, axis=1)
    return decorated


def _render_phase_diagnostic_panel(*, phase: str, summary: dict[str, Any], df: pd.DataFrame) -> None:
    preview_df = _build_phase_focus_preview_df(df, phase)
    preview_df = _decorate_graduation_strategy_links(preview_df)
    if "strategy_name_link" in preview_df.columns and "strategy_name" in preview_df.columns:
        preview_df = preview_df.drop(columns=["strategy_name"])
    metric_cols = st.columns(3)
    metric_cols[0].metric(f"{phase} traités", int((summary.get("processed_counts") or {}).get(phase, 0) or 0))
    metric_cols[1].metric(f"{phase} survivants", int((summary.get("survivor_counts") or {}).get(phase, 0) or 0))
    metric_cols[2].metric("Phase finale", str(summary.get("final_phase") or "-"))
    if preview_df.empty:
        st.caption(f"Aucun candidat à afficher pour {phase}.")
        return
    column_config = _get_numeric_column_config()
    st.dataframe(preview_df, width="stretch", hide_index=True, column_config=column_config)


def _render_progress_section(
    *,
    title: str,
    payload: dict[str, Any],
    log_filename: str,
    report_payload: dict[str, Any] | None = None,
    report_df: pd.DataFrame | None = None,
) -> None:
    st.markdown(f"### {title}")
    if not payload:
        st.write("ℹ️ Aucun état d'exécution en cours.")
        return

    stats = payload.get("stats") or {}
    candidate = payload.get("current_candidate") or {}
    total_candidates = _safe_int(stats.get("p1_candidates"), _safe_int(stats.get("import_candidates")))
    processed_counts = _phase_processed_counts(stats, total_candidates, infer_missing=False)
    survivor_counts = _phase_survivor_counts(stats)
    live_phase_distribution = _phase_distribution_counts(payload)
    report_phase_distribution = _phase_distribution_counts(report_payload or {}, report_df)
    has_live_phase_distribution = any(live_phase_distribution.get(phase, 0) for phase in ("P2", "P3", "P4", "P5", "P6"))
    phase_distribution = live_phase_distribution if has_live_phase_distribution else report_phase_distribution
    display_phase = _resolve_completed_phase(payload, processed_counts, phase_distribution)
    progress_index, progress_total = _resolve_progress_ratio(payload, display_phase, processed_counts)
    age_seconds = _progress_age_seconds(str(payload.get("updated_at") or ""))
    status_label = _progress_status_label(payload, age_seconds)
    age_label = ""
    if age_seconds is not None:
        age_label = f"{int(age_seconds)}s"

    st.markdown(_build_phase_timeline_html(current_phase=display_phase, status=str(payload.get("status") or "")), unsafe_allow_html=True)
    status_state = "running"
    status_title = "Calculs en cours"
    if status_label == "processus arrêté":
        status_state = "error"
        status_title = "Processus arrêté"
    elif status_label == "sans heartbeat":
        status_title = "Progression sans heartbeat"
    elif str(payload.get("status") or "").strip().lower() == "completed":
        status_state = "complete"
        status_title = "Run terminé"
    elif str(payload.get("status") or "").strip().lower() == "failed":
        status_state = "error"
        status_title = "Run échoué"
    with st.status(
        f"{status_title} · {display_phase} · {progress_index}/{progress_total}",
        state=status_state,
        expanded=False,
    ):
        if progress_total > 0:
            st.progress(
                min(1.0, max(0.0, progress_index / progress_total)),
                text=f"{display_phase} {progress_index}/{progress_total}",
            )

    heartbeat_cols = st.columns(2)
    heartbeat_cols[0].metric("Heartbeat", age_label or "-")
    heartbeat_cols[1].metric("PID", str(payload.get("pid") or "-"))

    cols = st.columns(8)
    cols[0].metric("Statut", status_label)
    cols[1].metric("Phase", display_phase)
    cols[2].metric("Avancement", f"{progress_index}/{progress_total}")
    cols[3].metric("Traités P2", processed_counts.get("P2", 0))
    cols[4].metric("Traités P3", processed_counts.get("P3", 0))
    cols[5].metric("Traités P4", processed_counts.get("P4", 0))
    cols[6].metric("Traités P5", processed_counts.get("P5", 0))
    cols[7].metric("P6 promues", survivor_counts.get("P6", 0))

    strategy_label = str(candidate.get("strategy_name") or candidate.get("session_id") or "").strip()
    if strategy_label:
        st.write(f"**Stratégie en cours** : `{strategy_label}`")
    source_parts = [
        str(candidate.get("source_symbol") or "").strip(),
        str(candidate.get("source_timeframe") or "").strip(),
        str(candidate.get("source_run_id") or "").strip(),
    ]
    source_parts = [part for part in source_parts if part]
    if source_parts:
        st.caption(" | ".join(source_parts))

    updated_at = str(payload.get("updated_at") or "").strip()
    if updated_at:
        st.caption(f"Dernière mise à jour: {updated_at} UTC" + (f" ({age_label})" if age_label else ""))
    cli_command = _payload_cli_equivalent(payload, report_payload)
    if cli_command:
        st.caption(f"Commande CLI équivalente: `{cli_command}`")
    st.caption(_format_phase_counts("Survivants", survivor_counts))
    if has_live_phase_distribution:
        st.caption(_format_phase_counts("Phase actuelle des candidats", phase_distribution))
    elif str(payload.get("status") or "").strip().lower() in {"starting", "running"}:
        st.caption(_format_phase_counts("Dernier rapport stable - phase finale des candidats", phase_distribution))
    else:
        st.caption(_format_phase_counts("Phase finale des candidats", phase_distribution))

    phase_contract = _payload_phase_contract(payload, report_payload)
    config_snapshot = _payload_config_snapshot(payload, report_payload)
    if phase_contract or config_snapshot:
        with st.expander("Contrat P1→P6 et paramètres CLI", expanded=False):
            if phase_contract:
                contract_rows = [
                    {
                        "phase": phase,
                        "nom": data.get("name", "") if isinstance(data, dict) else "",
                        "rôle": data.get("purpose", "") if isinstance(data, dict) else "",
                    }
                    for phase, data in phase_contract.items()
                ]
                st.dataframe(pd.DataFrame(contract_rows), width="stretch", hide_index=True)
            if config_snapshot:
                st.json(config_snapshot)

    _render_threshold_sensitivity_section(payload, report_payload)

    if status_label == "processus arrêté":
        st.error(
            "Le run est marqué `running`, mais son PID n'existe plus. "
            "Le dernier brouillon peut être incomplet ; relancez la graduation complète.",
        )
    elif payload.get("status") == "running" and age_seconds is not None and age_seconds > 180:
        st.warning("Le run est marqué `running` mais la progression n'a pas bougé depuis plus de 3 minutes.")
    elif payload.get("status") == "failed":
        st.error(str(payload.get("error") or "Le run a échoué."))
    elif payload.get("status") == "completed":
        st.success("Le run est terminé.")

    log_tail = _load_log_tail(log_filename)
    if log_tail:
        with st.expander("Dernières lignes du log", expanded=False):
            st.code(log_tail, language="text")

    with st.expander("État brut", expanded=False):
        st.json(payload)


def _start_background_graduation_job(
    *,
    args: list[str],
    log_filename: str,
    progress_filename: str | None = None,
) -> tuple[bool, str]:
    output_dir = GRADUATION_RESULTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    active_progresses = _active_graduation_progresses()
    if active_progresses:
        active = active_progresses[0]
        existing_progress = active.get("payload") or {}
        existing_pid = existing_progress.get("pid")
        active_pipeline = str(existing_progress.get("pipeline") or active.get("filename") or "graduation")
        pid_suffix = f" (PID {existing_pid})" if existing_pid else ""
        return (
            False,
            f"Un run de graduation est déjà actif: {active_pipeline}{pid_suffix}. "
            "Rafraîchissez la page pour suivre sa progression avant d'en lancer un autre.",
        )
    log_path = output_dir / log_filename
    command = [sys.executable, "-m", "catalog.graduation", *args]
    cli_command = _graduation_cli_command(args)
    try:
        with open(log_path, "a", encoding="utf-8") as log_handle:
            process = subprocess.Popen(
                command,
                cwd=str(Path.cwd()),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
    except Exception as exc:
        return False, f"Échec du lancement: {exc}"
    return True, f"Run lancé en arrière-plan (PID {process.pid}). Commande: `{cli_command}`. Log: {log_path}"


def _launch_full_graduation_from_ui(*, sync_catalog: bool) -> tuple[bool, str]:
    args = ["--full"]
    if sync_catalog:
        args.append("--sync-catalog")
    return _start_background_graduation_job(
        args=args,
        log_filename=FULL_GRADUATION_LOG_FILENAME,
        progress_filename=FULL_GRADUATION_PROGRESS_FILENAME,
    )


def _launch_p1_inventory_from_ui(*, sync_catalog: bool) -> tuple[bool, str]:
    args: list[str] = []
    if sync_catalog:
        args.append("--sync-catalog")
    return _start_background_graduation_job(
        args=args,
        log_filename=GRADUATION_P1_LOG_FILENAME,
    )


def _launch_positive_artifact_import_from_ui(
    *,
    sync_catalog: bool,
    include_legacy_artifact_roots: bool,
) -> tuple[bool, str]:
    args = ["--import-positive-artifacts"]
    if include_legacy_artifact_roots:
        args.append("--include-legacy-artifact-roots")
    if sync_catalog:
        args.append("--sync-catalog")
    return _start_background_graduation_job(
        args=args,
        log_filename=POSITIVE_ARTIFACTS_IMPORT_LOG_FILENAME,
    )


def _render_candidate_report_section(
    *,
    title: str,
    payload: dict[str, Any],
    df: pd.DataFrame,
    key_prefix: str,
) -> None:
    st.markdown(f"### {title}")
    if not payload:
        st.write("ℹ️ Aucun rapport disponible.")
        return

    stats = payload.get("stats") or {}
    total_candidates = _safe_int(payload.get("total_candidates"), _safe_int(stats.get("p1_candidates")))
    processed_counts = _phase_processed_counts(stats, total_candidates)
    survivor_counts = _phase_survivor_counts(stats)
    phase_distribution = _phase_distribution_counts(payload, df)
    metric_cols = st.columns(8)
    metric_cols[0].metric("Rapport", payload.get("phase", "?"))
    metric_cols[1].metric("Candidats", int(payload.get("total_candidates", 0)))
    metric_cols[2].metric("Traités P2", processed_counts.get("P2", 0))
    metric_cols[3].metric("Traités P3", processed_counts.get("P3", 0))
    metric_cols[4].metric("Traités P4", processed_counts.get("P4", 0))
    metric_cols[5].metric("Traités P5", processed_counts.get("P5", 0))
    metric_cols[6].metric("P6 promues", survivor_counts.get("P6", 0))
    metric_cols[7].metric("Sync", int(stats.get("catalog_synced", 0)))
    st.caption(f"Source: {payload.get('_report_path', '')}")
    cli_command = _payload_cli_equivalent(payload)
    if cli_command:
        st.caption(f"Commande CLI équivalente: `{cli_command}`")
    st.caption(_format_phase_counts("Survivants", survivor_counts))
    st.caption(_format_phase_counts("Phase finale des candidats", phase_distribution))
    if not _report_has_source_validation_fields(df):
        st.warning(
            "Ce rapport ne contient pas les champs de validation marché source ajoutés récemment. "
            "Relancez la graduation complète pour recalculer P4/P5 avec le mode source-first.",
        )
    phase_contract = _payload_phase_contract(payload)
    config_snapshot = _payload_config_snapshot(payload)
    if phase_contract or config_snapshot:
        with st.expander("Contrat P1→P6 et paramètres CLI", expanded=False):
            if phase_contract:
                contract_rows = [
                    {
                        "phase": phase,
                        "nom": data.get("name", "") if isinstance(data, dict) else "",
                        "rôle": data.get("purpose", "") if isinstance(data, dict) else "",
                    }
                    for phase, data in phase_contract.items()
                ]
                st.dataframe(pd.DataFrame(contract_rows), width="stretch", hide_index=True)
            if config_snapshot:
                st.json(config_snapshot)
    else:
        st.warning(
            "Ce rapport ne contient pas encore le contrat P1→P6 ni le snapshot des paramètres. "
            "Il a probablement été généré par une ancienne version du pipeline.",
        )

    _render_threshold_sensitivity_section(payload)

    if df.empty:
        st.write("ℹ️ Le rapport est présent mais ne contient aucun candidat.")
        return

    phase_options = (
        ["Toutes"] + sorted(df["phase"].dropna().astype(str).unique().tolist()) if "phase" in df.columns else ["Toutes"]
    )
    decision_options = (
        ["Toutes"] + sorted(df["decision"].dropna().astype(str).unique().tolist())
        if "decision" in df.columns
        else ["Toutes"]
    )
    source_options = (
        ["Toutes"] + sorted(df["source_kind"].dropna().astype(str).unique().tolist())
        if "source_kind" in df.columns
        else ["Toutes"]
    )

    filter_cols = st.columns(3)
    phase_filter = filter_cols[0].selectbox("Phase", phase_options, key=f"{key_prefix}_phase_filter")
    decision_filter = filter_cols[1].selectbox("Décision", decision_options, key=f"{key_prefix}_decision_filter")
    source_filter = filter_cols[2].selectbox("Source", source_options, key=f"{key_prefix}_source_filter")

    filtered = df.copy()
    if phase_filter != "Toutes" and "phase" in filtered.columns:
        filtered = filtered[filtered["phase"] == phase_filter]
    if decision_filter != "Toutes" and "decision" in filtered.columns:
        filtered = filtered[filtered["decision"] == decision_filter]
    if source_filter != "Toutes" and "source_kind" in filtered.columns:
        filtered = filtered[filtered["source_kind"] == source_filter]

    sort_col = "best_return_pct" if "best_return_pct" in filtered.columns else None
    if sort_col:
        filtered = filtered.sort_values(by=sort_col, ascending=False, na_position="last")

    preferred_cols = [
        "strategy_name",
        "session_id",
        "source_run_id",
        "source_symbol",
        "source_timeframe",
        "source_kind",
        "phase",
        "decision",
        "best_return_pct",
        "best_profit_factor",
        "best_sharpe",
        "best_trades",
        "benchmark_pass_summary",
        "required_benchmark_name",
        "required_benchmark_passed",
        "contradiction_state",
        "context_pass_summary",
        "configured_context_count",
        "loaded_context_count",
        "missing_context_count",
        "benchmark_slot_coverage_pct",
        "tested_benchmark_names",
        "tested_tokens",
        "timeframes_tested",
        "sweep_robustness_pct",
        "sensitivity_scope",
        "sensitivity_symbol",
        "sensitivity_timeframe",
        "sensitivity_history_bars",
        "wfa_stability",
        "wfa_avg_test_return_pct",
        "wfa_avg_test_sharpe",
        "wfa_classic_overfitting_ratio",
        "wfa_robust_overfitting_score",
        "wfa_overfitting_ratio",
        "wfa_valid_folds",
        "wfa_positive_folds_pct",
        "wfa_confidence_tier",
        "wfa_scope",
        "wfa_symbol",
        "wfa_timeframe",
        "wfa_history_bars",
        "rejection_reason",
        "catalog_category",
        "catalog_entry_id",
    ]
    visible_cols = [col for col in preferred_cols if col in filtered.columns]
    st.caption(f"Lignes visibles: {len(filtered)}/{len(df)}")
    preview_df = _decorate_graduation_strategy_links(filtered[visible_cols])
    if "strategy_name_link" in preview_df.columns and "strategy_name" in preview_df.columns:
        preview_df = preview_df.drop(columns=["strategy_name"])
        visible_cols = ["strategy_name_link", *[col for col in visible_cols if col != "strategy_name"]]
        preview_df = preview_df[[col for col in visible_cols if col in preview_df.columns]]
    st.dataframe(
        preview_df,
        width="stretch",
        hide_index=True,
        column_config=_get_numeric_column_config(),
    )

    if filtered.empty:
        return

    detail_labels = []
    detail_map: dict[str, dict[str, Any]] = {}
    for row in filtered.to_dict(orient="records"):
        strategy_name = str(row.get("strategy_name") or row.get("session_id") or "candidate")
        source_run_id = str(row.get("source_run_id") or "").strip()
        phase = str(row.get("phase") or "").strip()
        label = strategy_name
        if source_run_id:
            label += f" | {source_run_id}"
        if phase:
            label += f" | {phase}"
        if label in detail_map:
            label += f" | {row.get('catalog_entry_id') or row.get('session_id')}"
        detail_labels.append(label)
        detail_map[label] = row

    selected_label = st.selectbox(
        "Détail stratégie",
        options=detail_labels,
        key=f"{key_prefix}_detail_select",
    )
    selected_row = detail_map[selected_label]
    with st.expander("Détail du traitement", expanded=False):
        st.json(selected_row)


def _coerce_numeric(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


_BACKTEST_OVERVIEW_METRIC_ALIASES = {
    "total_pnl": "metrics_total_pnl",
    "total_return_pct": "metrics_total_return_pct",
    "annualized_return": "metrics_annualized_return",
    "benchmark_return_pct": "metrics_benchmark_return_pct",
    "alpha_simple_pct": "metrics_alpha_simple_pct",
    "sharpe_ratio": "metrics_sharpe_ratio",
    "sortino_ratio": "metrics_sortino_ratio",
    "max_drawdown_pct": "metrics_max_drawdown_pct",
    "volatility_annual": "metrics_volatility_annual",
    "max_drawdown_duration_days": "metrics_max_drawdown_duration_days",
    "total_trades": "metrics_total_trades",
    "win_rate_pct": "metrics_win_rate_pct",
    "profit_factor": "metrics_profit_factor",
    "avg_win": "metrics_avg_win",
    "avg_loss": "metrics_avg_loss",
    "largest_win": "metrics_largest_win",
    "largest_loss": "metrics_largest_loss",
    "avg_trade_duration_hours": "metrics_avg_trade_duration_hours",
    "expectancy": "metrics_expectancy",
    "risk_reward_ratio": "metrics_risk_reward_ratio",
    "calmar_ratio": "metrics_calmar_ratio",
    "tier_s": "metrics_tier_s",
    "data_coverage_pct": "metrics_data_coverage_pct",
}


def _normalize_backtest_overview_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    for plain_col, prefixed_col in _BACKTEST_OVERVIEW_METRIC_ALIASES.items():
        if prefixed_col not in df.columns:
            continue
        if plain_col not in df.columns:
            df[plain_col] = df[prefixed_col]
            continue
        current = pd.to_numeric(df[plain_col], errors="coerce")
        fallback = pd.to_numeric(df[prefixed_col], errors="coerce")
        missing_mask = current.isna() & fallback.notna()
        if missing_mask.any():
            df.loc[missing_mask, plain_col] = df.loc[missing_mask, prefixed_col]

    numeric_cols = [
        "total_pnl",
        "total_return_pct",
        "annualized_return",
        "benchmark_return_pct",
        "alpha_simple_pct",
        "sharpe_ratio",
        "sortino_ratio",
        "max_drawdown_pct",
        "volatility_annual",
        "max_drawdown_duration_days",
        "win_rate_pct",
        "profit_factor",
        "avg_win",
        "avg_loss",
        "largest_win",
        "largest_loss",
        "avg_trade_duration_hours",
        "expectancy",
        "risk_reward_ratio",
        "calmar_ratio",
        "tier_s",
        "data_coverage_pct",
        "total_trades",
        "n_bars",
        "n_trades",
        "n_completed",
        "n_failed",
        "n_trials",
        "n_pruned",
        "best_value",
        "total_time_sec",
        "total_combinations",
        "max_combos",
        "n_workers",
        *_BACKTEST_OVERVIEW_METRIC_ALIASES.values(),
    ]
    return _coerce_numeric(df, numeric_cols)


def _row_metric_value(row: pd.Series, key: str) -> Any:
    direct = _normalize_cell(row.get(key))
    if direct not in (None, ""):
        return direct
    prefixed = _normalize_cell(row.get(f"metrics_{key}"))
    if prefixed not in (None, ""):
        return prefixed
    return ""


def _load_catalogs(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if refresh:
        if RESULTS_DIR.exists():
            storage = ResultStorage(storage_dir=RESULTS_DIR, auto_save=False)
            storage.build_catalogs(force=True)
        if RUNS_DIR.exists():
            tracker = RunTracker(cache_file=RUNS_DIR / ".run_cache.json")
            tracker.build_catalogs()

    backtest_overview = _safe_read_csv(RESULTS_DIR / "_catalog" / "overview.csv")
    unified_overview = _safe_read_csv(RESULTS_DIR / "_catalog" / "unified_overview.csv")
    runs_overview = _safe_read_csv(RUNS_DIR / "_catalog" / "overview.csv")

    backtest_overview = _normalize_backtest_overview_df(backtest_overview)
    unified_overview = _coerce_numeric(
        unified_overview,
        [
            "n_bars",
            "n_trades",
            "duration_sec",
            "metrics_total_pnl",
            "metrics_total_return_pct",
            "metrics_sharpe_ratio",
            "metrics_max_drawdown_pct",
            "metrics_win_rate_pct",
            "metrics_profit_factor",
            "metrics_total_trades",
        ],
    )
    runs_overview = _coerce_numeric(
        runs_overview,
        [
            "total_iterations",
            "total_llm_tokens",
            "total_llm_calls",
            "iteration_history_count",
        ],
    )
    return backtest_overview, unified_overview, runs_overview


def _load_builder_store_payload() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    try:
        from ui.results_store_view import (
            _load_builder_catalog_reconciliation,
            _load_builder_iterations_df,
            _load_builder_sessions_df,
        )
    except Exception as exc:
        logger.warning("Failed to import builder store helpers in results_hub: %s", exc)
        return pd.DataFrame(), pd.DataFrame(), {}

    builder_root = Path(get_builder_sessions_dir())
    try:
        builder_df = _load_builder_sessions_df(str(builder_root))
    except Exception as exc:
        logger.warning("Failed to load builder sessions for results_hub: %s", exc)
        builder_df = pd.DataFrame()

    try:
        builder_iterations_df = _load_builder_iterations_df(str(builder_root))
    except Exception as exc:
        logger.warning("Failed to load builder iterations for results_hub: %s", exc)
        builder_iterations_df = pd.DataFrame()

    try:
        builder_catalog_audit = _load_builder_catalog_reconciliation(str(builder_root), str(RESULTS_DIR))
    except Exception as exc:
        logger.warning("Failed to audit builder/catalog reconciliation in results_hub: %s", exc)
        builder_catalog_audit = {}

    return builder_df, builder_iterations_df, builder_catalog_audit


def _path_to_uri(path: Path) -> str:
    try:
        return path.resolve().as_uri()
    except Exception:
        return str(path)


def _add_open_links_from_results_path(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "path" not in df.columns:
        return df
    df = df.copy()
    df["open_folder"] = df["path"].apply(
        lambda value: (
            ""
            if value is None or (isinstance(value, float) and pd.isna(value)) or value == ""
            else _path_to_uri(RESULTS_DIR / str(value))
        ),
    )
    return df


def _add_open_links_runs(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()

    def _row_to_uri(row: pd.Series) -> str:
        trace_path = row.get("trace_path", "")
        if isinstance(trace_path, str) and trace_path:
            return _path_to_uri(Path(trace_path).parent)
        session_id = row.get("session_id", "")
        if session_id:
            return _path_to_uri(RUNS_DIR / str(session_id))
        return ""

    df["open_folder"] = df.apply(_row_to_uri, axis=1)
    return df


def _add_pnl_per_day(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "total_pnl" not in df.columns:
        return df
    if "period_start" not in df.columns or "period_end" not in df.columns:
        return df
    df = df.copy()
    start_dt = pd.to_datetime(df["period_start"], errors="coerce", utc=True)
    end_dt = pd.to_datetime(df["period_end"], errors="coerce", utc=True)
    delta = end_dt - start_dt
    delta_seconds = pd.to_numeric(delta.dt.total_seconds(), errors="coerce")
    period_days = (delta_seconds // 86400).astype(float)
    period_days = period_days.where(delta_seconds >= 0)
    period_days = period_days.clip(lower=1.0)
    df["period_days"] = period_days
    df["pnl_per_day"] = df["total_pnl"] / df["period_days"]
    if "data_coverage_pct" in df.columns:
        coverage = pd.to_numeric(df["data_coverage_pct"], errors="coerce")
        effective_days = period_days * (coverage / 100.0)
        effective_days = effective_days.where(effective_days > 0)
        df["pnl_per_day_covered"] = df["total_pnl"] / effective_days
    return df


def _metric_from_snapshot(snapshot: dict[str, Any], *keys: str) -> Any:
    if not isinstance(snapshot, dict):
        return None
    for key in keys:
        value = snapshot.get(key)
        if value is not None and value != "":
            return value
    return None


def _extract_catalog_postfilter_fields(entry: dict[str, Any]) -> dict[str, Any]:
    metrics = entry.get("last_metrics_snapshot") or {}
    meta = entry.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}

    benchmark_consensus = first_present_non_empty(
        meta,
        "benchmark_consensus",
        "positive_pipeline_benchmark_consensus",
    )
    benchmark_results = first_present_non_empty(
        meta,
        "benchmark_results",
        "positive_pipeline_benchmark_results",
    )
    configured_contexts = first_present_non_empty(
        meta,
        "configured_contexts",
        "positive_pipeline_configured_contexts",
    )
    loaded_contexts = first_present_non_empty(
        meta,
        "loaded_contexts",
        "positive_pipeline_loaded_contexts",
    )
    missing_contexts = first_present_non_empty(
        meta,
        "missing_contexts",
        "positive_pipeline_missing_contexts",
    )
    tested_timeframes = first_present_non_empty(
        meta,
        "tested_timeframes",
        "positive_pipeline_tested_timeframes",
    )

    configured_context_list = as_listish(configured_contexts)
    loaded_context_list = as_listish(loaded_contexts)
    missing_context_list = as_listish(missing_contexts)
    tested_timeframe_list = sorted(as_listish(tested_timeframes))

    tested_benchmark_names: list[str] = []
    tested_tokens: list[str] = []
    if isinstance(benchmark_results, dict):
        tested_benchmark_names = sorted(str(name).strip() for name in benchmark_results.keys() if str(name).strip())
        for payload in benchmark_results.values():
            if not isinstance(payload, dict):
                continue
            for token in payload.get("tokens", []) or []:
                token_str = str(token).strip()
                if token_str and token_str not in tested_tokens:
                    tested_tokens.append(token_str)
    tested_tokens = sorted(tested_tokens)

    if not tested_tokens:
        source_symbol = str(first_present_non_empty(meta, "source_symbol", "positive_pipeline_source_symbol") or "").strip()
        if source_symbol:
            tested_tokens = [source_symbol]

    required_benchmark_name = ""
    required_benchmark_passed = False
    benchmark_pass_summary = ""
    contradiction_state = ""
    passed_benchmark_names: list[str] = []
    if isinstance(benchmark_consensus, dict):
        required_benchmark_name = str(benchmark_consensus.get("required_benchmark_name") or "").strip()
        required_benchmark_passed = bool(benchmark_consensus.get("required_passed", False))
        passed_benchmark_names = sorted(as_listish(benchmark_consensus.get("benchmarks_passed", [])))
        benchmarks_total = int(benchmark_consensus.get("benchmarks_total") or 0)
        benchmark_pass_summary = f"{len(passed_benchmark_names)}/{benchmarks_total}" if benchmarks_total > 0 else ""
        if bool(benchmark_consensus.get("consensus_passed")):
            contradiction_state = "passed"
        elif bool(benchmark_consensus.get("contradicted")):
            contradiction_state = "contradicted"
        elif benchmarks_total > 0:
            contradiction_state = "failed"

    passed_context_count = coerce_metric_int(
        first_present_non_empty(meta, "positive_pipeline_passed_count"),
        default=None,
    )
    total_context_count = coerce_metric_int(
        first_present_non_empty(meta, "positive_pipeline_total_contexts"),
        default=None,
    )
    if passed_context_count is None:
        passed_context_count = coerce_metric_int(_metric_from_snapshot(metrics, "multi_context_passed"), default=None)
    if total_context_count is None:
        total_context_count = coerce_metric_int(_metric_from_snapshot(metrics, "multi_context_total"), default=None)
    context_pass_summary = (
        f"{passed_context_count}/{total_context_count}"
        if passed_context_count is not None and total_context_count is not None and total_context_count > 0
        else ""
    )

    return {
        "phase": str(first_present_non_empty(meta, "phase", "positive_pipeline_phase") or "").strip(),
        "decision": str(first_present_non_empty(meta, "decision", "positive_pipeline_decision") or "").strip(),
        "p2_verdict": str(first_present_non_empty(meta, "p2_verdict", "positive_pipeline_p2_verdict") or "").strip(),
        "p3_verdict": str(first_present_non_empty(meta, "p3_verdict", "positive_pipeline_p3_verdict") or "").strip(),
        "p4_verdict": str(first_present_non_empty(meta, "p4_verdict", "positive_pipeline_p4_verdict") or "").strip(),
        "p5_verdict": str(first_present_non_empty(meta, "p5_verdict", "positive_pipeline_p5_verdict") or "").strip(),
        "p6_verdict": str(first_present_non_empty(meta, "p6_verdict", "positive_pipeline_p6_verdict") or "").strip(),
        "coverage_pct": coerce_metric_float(
            first_present_non_empty(meta, "coverage_pct", "positive_pipeline_coverage_pct"),
            default=None,
        ),
        "configured_context_count": len(configured_context_list),
        "loaded_context_count": len(loaded_context_list),
        "missing_context_count": len(missing_context_list),
        "context_pass_summary": context_pass_summary,
        "required_benchmark_name": required_benchmark_name,
        "required_benchmark_passed": required_benchmark_passed,
        "benchmark_pass_summary": benchmark_pass_summary,
        "contradiction_state": contradiction_state,
        "tested_benchmark_names": ",".join(tested_benchmark_names),
        "tested_tokens": ",".join(tested_tokens),
        "timeframes_tested": ",".join(tested_timeframe_list),
    }


def _load_strategy_catalog_df() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for entry in list_entries(status=None):
        metrics = entry.get("last_metrics_snapshot") or {}
        meta = entry.get("meta") or {}
        rows.append(
            {
                "entry_id": entry.get("id"),
                "strategy": entry.get("strategy_name"),
                "symbol": entry.get("symbol"),
                "timeframe": entry.get("timeframe"),
                "builder_session_id": meta.get("builder_session_id") or meta.get("session_id"),
                "builder_iteration": meta.get("builder_iteration") or meta.get("best_iteration"),
                "candidate_id": meta.get("candidate_id"),
                "category": entry.get("category"),
                "status": entry.get("status"),
                "source": entry.get("source"),
                "builder_state": entry.get("builder_state"),
                "tags": ", ".join(entry.get("tags") or []),
                "source_run_id": meta.get("source_run_id"),
                "source_path": meta.get("source_path"),
                "session_dir": meta.get("session_dir"),
                "strategy_file": meta.get("strategy_file"),
                "source_params": meta.get("source_params") if isinstance(meta.get("source_params"), dict) else None,
                "sharpe": _metric_from_snapshot(metrics, "sharpe_ratio", "sharpe"),
                "return_pct": _metric_from_snapshot(metrics, "total_return_pct", "total_return"),
                "pnl": _metric_from_snapshot(metrics, "total_pnl", "pnl"),
                "trades": _metric_from_snapshot(metrics, "total_trades", "trades"),
                **_extract_catalog_postfilter_fields(entry),
            },
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = _coerce_numeric(
        df,
        [
            "sharpe",
            "return_pct",
            "pnl",
            "trades",
            "builder_iteration",
            "coverage_pct",
            "configured_context_count",
            "loaded_context_count",
            "missing_context_count",
        ],
    )
    df["source_ref"] = df.apply(lambda row: _catalog_entry_source_ref(row.to_dict()), axis=1)
    return _decorate_strategy_catalog_links(df)


def _catalog_entry_source_ref(catalog_entry: Mapping[str, Any]) -> str:
    source_run_id = str(catalog_entry.get("source_run_id") or "").strip()
    if source_run_id:
        return f"run:{source_run_id}"

    builder_session_id = str(catalog_entry.get("builder_session_id") or "").strip()
    builder_iteration = _safe_int(catalog_entry.get("builder_iteration"))
    if builder_session_id:
        if builder_iteration > 0:
            return f"builder:{builder_session_id}#{builder_iteration}"
        return f"builder:{builder_session_id}"

    strategy_file = str(catalog_entry.get("strategy_file") or "").strip()
    if strategy_file:
        return f"file:{Path(strategy_file).name}"

    entry_id = str(catalog_entry.get("entry_id") or "").strip()
    if entry_id:
        return f"entry:{entry_id}"
    return ""


def _catalog_entry_has_replay_source(catalog_entry: Mapping[str, Any]) -> bool:
    if str(catalog_entry.get("source_run_id") or "").strip():
        return True

    params = catalog_entry.get("source_params")
    if not isinstance(params, dict):
        return False
    if not params:
        return False

    strategy_key = str(catalog_entry.get("strategy") or "").strip()
    symbol = str(catalog_entry.get("symbol") or "").strip()
    timeframe = str(catalog_entry.get("timeframe") or "").strip()
    return bool(strategy_key and symbol and timeframe)


def _decorate_unified_with_catalog(
    unified_df: pd.DataFrame,
    strategy_catalog_df: pd.DataFrame,
) -> pd.DataFrame:
    if unified_df.empty:
        return unified_df
    df = unified_df.copy()
    df["catalog_entry_id"] = ""
    df["catalog_category"] = ""
    df["catalog_status"] = ""
    if strategy_catalog_df.empty or "source_run_id" not in strategy_catalog_df.columns:
        return df

    catalog_map = {}
    for row_dict in strategy_catalog_df.to_dict(orient="records"):
        run_id = str(row_dict.get("source_run_id") or "").strip()
        if not run_id:
            continue
        catalog_map[run_id] = row_dict

    keys = df.get("run_id", pd.Series(dtype=str)).astype(str).str.strip()
    entry_map = {k: v.get("entry_id", "") for k, v in catalog_map.items()}
    category_map = {k: v.get("category", "") for k, v in catalog_map.items()}
    status_map = {k: v.get("status", "") for k, v in catalog_map.items()}
    phase_map = {k: v.get("phase", "") for k, v in catalog_map.items()}
    decision_map = {k: v.get("decision", "") for k, v in catalog_map.items()}
    benchmark_map = {k: v.get("benchmark_pass_summary", "") for k, v in catalog_map.items()}
    coverage_map = {k: v.get("coverage_pct", None) for k, v in catalog_map.items()}
    df["catalog_entry_id"] = keys.map(entry_map).fillna("")
    df["catalog_category"] = keys.map(category_map).fillna("")
    df["catalog_status"] = keys.map(status_map).fillna("")
    df["catalog_phase"] = keys.map(phase_map).fillna("")
    df["catalog_decision"] = keys.map(decision_map).fillna("")
    df["catalog_benchmark_pass_summary"] = keys.map(benchmark_map).fillna("")
    df["catalog_coverage_pct"] = pd.to_numeric(keys.map(coverage_map), errors="coerce")
    return df


def _normalize_cell(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple, set)):
        return value
    if isinstance(value, float) and pd.isna(value):
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _extract_prefixed_values(row: dict[str, Any], prefix: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in row.items():
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        normalized = _normalize_cell(value)
        if normalized in (None, ""):
            continue
        values[key[len(prefix):]] = normalized
    return values


def _build_run_row_replay_request(
    source_row: dict[str, Any],
    *,
    auto_run: bool,
) -> tuple[dict[str, Any] | None, str]:
    strategy_key = str(source_row.get("strategy") or "").strip()
    symbol = str(source_row.get("symbol") or "").strip()
    timeframe = str(source_row.get("timeframe") or "").strip()
    source_run_id = str(source_row.get("run_id") or "").strip()
    if not strategy_key or not symbol or not timeframe:
        return None, "Replay impossible: stratégie, symbole ou timeframe manquant."

    params = _extract_prefixed_values(source_row, "params_")
    initial_capital = params.pop("initial_capital", None)
    params.pop("fees_bps", None)
    params.pop("slippage_bps", None)

    request = {
        "strategy_key": strategy_key,
        "symbol": symbol,
        "timeframe": timeframe,
        "params": params,
        "initial_capital": initial_capital,
        "start_date": source_row.get("period_start"),
        "end_date": source_row.get("period_end"),
        "source_run_id": source_run_id,
        "auto_run": auto_run,
    }
    action_label = "relance" if auto_run else "chargement"
    return request, f"Replay prêt ({action_label}) depuis {source_run_id or strategy_key}."


def _build_catalog_replay_request(
    catalog_entry: dict[str, Any],
    unified_df: pd.DataFrame,
    *,
    auto_run: bool,
) -> tuple[dict[str, Any] | None, str]:
    source_run_id = str(catalog_entry.get("source_run_id") or "").strip()
    if source_run_id and not unified_df.empty and "run_id" in unified_df.columns:
        source_rows = unified_df[unified_df["run_id"].astype(str) == source_run_id]
        if not source_rows.empty:
            source_row = {key: _normalize_cell(value) for key, value in source_rows.iloc[0].to_dict().items()}
            source_row["strategy"] = str(catalog_entry.get("strategy") or source_row.get("strategy") or "").strip()
            return _build_run_row_replay_request(source_row, auto_run=auto_run)

    strategy_key = str(catalog_entry.get("strategy") or "").strip()
    symbol = str(catalog_entry.get("symbol") or "").strip()
    timeframe = str(catalog_entry.get("timeframe") or "").strip()
    params = dict(catalog_entry.get("source_params") or {}) if isinstance(catalog_entry.get("source_params"), dict) else {}
    if not strategy_key or not symbol or not timeframe or not params:
        if source_run_id:
            return None, f"Replay impossible: run source introuvable ({source_run_id})."
        return None, "Replay impossible: source_run_id absent et paramètres source indisponibles."

    initial_capital = params.pop("initial_capital", None)
    params.pop("fees_bps", None)
    params.pop("slippage_bps", None)
    request = {
        "strategy_key": strategy_key,
        "symbol": symbol,
        "timeframe": timeframe,
        "params": params,
        "initial_capital": initial_capital,
        "source_run_id": source_run_id,
        "auto_run": auto_run,
    }
    action_label = "relance" if auto_run else "chargement"
    source_ref = _catalog_entry_source_ref(catalog_entry) or strategy_key
    return request, f"Replay prêt ({action_label}) depuis {source_ref}."


def _pick_latest_from_catalogs(
    backtest_overview: pd.DataFrame,
    runs_overview: pd.DataFrame,
    builder_sessions_df: pd.DataFrame,
) -> dict[str, Any] | None:
    candidates = []

    if not backtest_overview.empty:
        df = backtest_overview.copy()
        df["timestamp_dt"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.dropna(subset=["timestamp_dt"])
        if not df.empty:
            latest = df.sort_values("timestamp_dt", ascending=False).iloc[0]
            candidates.append(
                {
                    "source": "backtest_results",
                    "kind": latest.get("type", ""),
                    "id": latest.get("id", ""),
                    "timestamp": latest.get("timestamp", ""),
                    "strategy": latest.get("strategy", ""),
                    "symbol": latest.get("symbol", ""),
                    "timeframe": latest.get("timeframe", ""),
                    "period_start": latest.get("period_start", ""),
                    "period_end": latest.get("period_end", ""),
                    "metrics": {
                        "total_pnl": _row_metric_value(latest, "total_pnl"),
                        "total_return_pct": _row_metric_value(latest, "total_return_pct"),
                        "sharpe_ratio": _row_metric_value(latest, "sharpe_ratio"),
                        "max_drawdown_pct": _row_metric_value(latest, "max_drawdown_pct"),
                        "win_rate_pct": _row_metric_value(latest, "win_rate_pct"),
                        "profit_factor": _row_metric_value(latest, "profit_factor"),
                    },
                    "path": latest.get("path", ""),
                    "timestamp_dt": latest.get("timestamp_dt"),
                },
            )

    if not runs_overview.empty:
        df = runs_overview.copy()
        df["timestamp_dt"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.dropna(subset=["timestamp_dt"])
        if not df.empty:
            latest = df.sort_values("timestamp_dt", ascending=False).iloc[0]
            candidates.append(
                {
                    "source": "runs",
                    "kind": latest.get("mode", ""),
                    "id": latest.get("session_id", ""),
                    "timestamp": latest.get("timestamp", ""),
                    "strategy": latest.get("strategy_name", ""),
                    "symbol": "",
                    "timeframe": "",
                    "metrics": {
                        "total_iterations": latest.get("total_iterations", ""),
                        "total_llm_tokens": latest.get("total_llm_tokens", ""),
                        "total_llm_calls": latest.get("total_llm_calls", ""),
                        "last_decision": latest.get("last_decision", ""),
                    },
                    "path": latest.get("trace_path", ""),
                    "timestamp_dt": latest.get("timestamp_dt"),
                },
            )

    if not builder_sessions_df.empty:
        df = builder_sessions_df.copy()
        df["timestamp_dt"] = pd.to_datetime(df["last_modified"], errors="coerce", utc=True)
        df = df.dropna(subset=["timestamp_dt"])
        if not df.empty:
            latest = df.sort_values("timestamp_dt", ascending=False).iloc[0]
            candidates.append(
                {
                    "source": "builder_sessions",
                    "kind": "builder_session",
                    "id": latest.get("session_id", ""),
                    "timestamp": latest.get("last_modified", ""),
                    "strategy": latest.get("session_id", ""),
                    "symbol": "",
                    "timeframe": "",
                    "metrics": {
                        "best_return_pct": latest.get("best_return_pct", ""),
                        "best_sharpe": latest.get("best_sharpe", ""),
                        "total_iterations": latest.get("total_iterations", ""),
                        "status": latest.get("status", ""),
                    },
                    "path": latest.get("session_dir", ""),
                    "timestamp_dt": latest.get("timestamp_dt"),
                },
            )

    if not candidates:
        return None

    candidates.sort(key=lambda x: x.get("timestamp_dt") or pd.Timestamp.min.tz_localize("UTC"), reverse=True)
    return candidates[0]


def _render_metric_row(items: tuple[tuple[str, Any], ...]) -> None:
    for column, (label, value) in zip(st.columns(len(items)), items):
        with column:
            st.metric(label, value)


def _render_backtest_metric_row(metrics: Mapping[str, Any], period_days: Any) -> None:
    _render_metric_row(
        (
            ("PnL", format_pnl_with_daily(metrics.get("total_pnl", 0), period_days)),
            ("Return", f"{coerce_metric_float(metrics.get('total_return_pct', 0)):.1f}%"),
            ("Sharpe", f"{coerce_metric_float(metrics.get('sharpe_ratio', 0)):.2f}"),
            ("Max DD", f"{coerce_metric_float(metrics.get('max_drawdown_pct', 0)):.1f}%"),
        ),
    )


def _render_latest_run(
    backtest_overview: pd.DataFrame,
    runs_overview: pd.DataFrame,
    builder_sessions_df: pd.DataFrame,
) -> None:
    st.subheader("🕒 Dernier run")

    session_result = st.session_state.get("last_run_result")
    session_meta = st.session_state.get("last_winner_meta")

    if session_result is not None:
        metrics = session_result.metrics
        meta = session_result.meta
        period_days = compute_period_days(
            meta.get("period_start"),
            meta.get("period_end"),
        )
        _render_backtest_metric_row(metrics, period_days)

        st.caption(
            f"Run: {meta.get('run_id', 'n/a')} | "
            f"{meta.get('strategy', 'n/a')} | "
            f"{meta.get('symbol', 'n/a')}/{meta.get('timeframe', 'n/a')}",
        )
        if session_meta and isinstance(session_meta, dict):
            st.caption(f"Origine: {session_meta.get('run_id', 'n/a')}")
        return

    latest = _pick_latest_from_catalogs(backtest_overview, runs_overview, builder_sessions_df)
    if latest is None:
        st.write("ℹ️ Aucun run détecté pour le moment.")
        return

    if latest["source"] == "backtest_results":
        metrics = latest.get("metrics", {})
        period_days = compute_period_days(
            latest.get("period_start"),
            latest.get("period_end"),
        )
        _render_backtest_metric_row(metrics, period_days)
        st.caption(
            f"{latest.get('kind', '')} | {latest.get('id', '')} | "
            f"{latest.get('strategy', '')} {latest.get('symbol', '')}/{latest.get('timeframe', '')} | "
            f"{latest.get('timestamp', '')}",
        )
    else:
        metrics = latest.get("metrics", {})
        if latest["source"] == "builder_sessions":
            _render_metric_row(
                (
                    ("Best return", f"{coerce_metric_float(metrics.get('best_return_pct', 0)):.1f}%"),
                    ("Best sharpe", f"{coerce_metric_float(metrics.get('best_sharpe', 0)):.2f}"),
                    ("Itérations", f"{int(coerce_metric_float(metrics.get('total_iterations', 0))):d}"),
                    ("Statut", str(metrics.get("status", "") or "n/a")),
                ),
            )
            st.caption(
                f"Session Builder disque: {latest.get('id', '')} | "
                f"{latest.get('timestamp', '')}",
            )
        else:
            st.write(f"ℹ️ Dernier run LLM ({RUNS_DIR})")
            st.caption(
                f"Mode: {latest.get('kind', '')} | Session: {latest.get('id', '')} | "
                f"Stratégie: {latest.get('strategy', '')} | {latest.get('timestamp', '')}",
            )
            if metrics:
                st.caption(
                    f"Iter: {metrics.get('total_iterations', 'n/a')} | "
                    f"LLM calls: {metrics.get('total_llm_calls', 'n/a')} | "
                    f"Tokens: {metrics.get('total_llm_tokens', 'n/a')} | "
                    f"Derniere decision: {metrics.get('last_decision', 'n/a')}",
                )


def _render_charts(df: pd.DataFrame) -> None:
    if df.empty:
        return

    numeric_cols = [c for c in ["total_return_pct", "sharpe_ratio", "max_drawdown_pct"] if c in df.columns]
    if not numeric_cols:
        return

    controls_col1, controls_col2 = st.columns(2)
    with controls_col1:
        return_chart_mode = st.radio(
            "Graphique rendement",
            options=[CHART_MODE_COLUMNS, CHART_MODE_POINTS],
            index=0,
            horizontal=True,
            key="results_hub_return_chart_mode",
        )
    with controls_col2:
        risk_chart_mode = st.radio(
            "Graphique Sharpe / drawdown",
            options=[CHART_MODE_POINTS, CHART_MODE_COLUMNS],
            index=0,
            horizontal=True,
            key="results_hub_risk_chart_mode",
        )

    if PLOTLY_AVAILABLE:
        if "total_return_pct" in df.columns:
            fig = _build_return_chart(df, return_chart_mode)
            st.plotly_chart(fig, width="stretch")
        if {"sharpe_ratio", "max_drawdown_pct"}.issubset(df.columns):
            fig = _build_sharpe_drawdown_chart(df, risk_chart_mode)
            st.plotly_chart(fig, width="stretch")
    else:
        if "total_return_pct" in df.columns:
            if return_chart_mode == CHART_MODE_POINTS:
                return_chart_df = df[["total_return_pct"]].dropna().reset_index(drop=True)
                return_chart_df["run_index"] = return_chart_df.index + 1
                st.scatter_chart(return_chart_df, x="run_index", y="total_return_pct", height=240)
            else:
                st.bar_chart(df["total_return_pct"].dropna(), height=240)
        if {"sharpe_ratio", "max_drawdown_pct"}.issubset(df.columns):
            risk_df = df[["max_drawdown_pct", "sharpe_ratio"]].dropna()
            if risk_chart_mode == CHART_MODE_COLUMNS:
                st.bar_chart(risk_df.set_index("max_drawdown_pct")["sharpe_ratio"], height=260)
            else:
                st.scatter_chart(risk_df, x="max_drawdown_pct", y="sharpe_ratio", height=260)


def _build_return_chart(df: pd.DataFrame, chart_mode: str):
    plot_cols = ["total_return_pct"]
    if "type" in df.columns:
        plot_cols.append("type")
    plot_df = df[plot_cols].dropna(subset=["total_return_pct"]).reset_index(drop=True)
    if chart_mode == CHART_MODE_POINTS:
        plot_df["run_index"] = plot_df.index + 1
        return px.scatter(
            plot_df,
            x="run_index",
            y="total_return_pct",
            color="type" if "type" in plot_df.columns else None,
            title="Distribution Return %",
            labels={"run_index": "Run #", "total_return_pct": "total_return_pct"},
        )
    return px.histogram(plot_df, x="total_return_pct", nbins=30, title="Distribution Return %")


def _build_sharpe_drawdown_chart(df: pd.DataFrame, chart_mode: str):
    hover_cols = [col for col in ["id", "strategy", "symbol", "timeframe"] if col in df.columns]
    plot_cols = ["max_drawdown_pct", "sharpe_ratio"] + (["type"] if "type" in df.columns else []) + hover_cols
    plot_df = df[plot_cols].dropna(subset=["max_drawdown_pct", "sharpe_ratio"])
    if chart_mode == CHART_MODE_COLUMNS:
        return px.bar(
            plot_df.sort_values("max_drawdown_pct"),
            x="max_drawdown_pct",
            y="sharpe_ratio",
            color="type" if "type" in plot_df.columns else None,
            title="Sharpe vs Max Drawdown",
            hover_data=hover_cols,
        )
    return px.scatter(
        plot_df,
        x="max_drawdown_pct",
        y="sharpe_ratio",
        color="type" if "type" in plot_df.columns else None,
        title="Sharpe vs Max Drawdown",
        hover_data=hover_cols,
    )


def _text_column_config(*specs: tuple[str, str, str]) -> dict[str, Any]:
    return {
        key: st.column_config.TextColumn(label, width=width)
        for key, label, width in specs
    }


def _number_column_config(
    format_specs: Mapping[str, tuple[tuple[str, str], ...]],
) -> dict[str, Any]:
    return {
        key: st.column_config.NumberColumn(label, format=fmt)
        for fmt, specs in format_specs.items()
        for key, label in specs
    }


_RESULTS_HUB_TEXT_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("hub_source", "Source", "medium"), ("hub_type", "Type", "medium"),
    ("hub_action_scope", "Action", "small"), ("type", "Type", "small"), ("id", "Id", "small"),
    ("run_id", "Run", "small"), ("session_id", "Session", "medium"),
    ("entry_id", "Entrée", "medium"), ("candidate_id", "Candidate", "medium"),
    ("path", "Path", "medium"), ("storage_path", "Storage", "medium"),
    ("timestamp", "Timestamp", "medium"), ("mode", "Mode", "small"), ("status", "Status", "small"),
    ("strategy", "Strategy", "large"), ("symbol", "Symbol", "small"), ("timeframe", "TF", "small"),
    ("source_ref", "Source", "medium"), ("source_run_id", "Run source", "small"),
    ("period_start", "Début", "medium"), ("period_end", "Fin", "medium"),
    ("artifact_type", "Artefact", "small"), ("category", "Catégorie", "small"),
    ("catalog_category", "Catégorie cat.", "small"), ("catalog_status", "Statut cat.", "small"),
    ("phase", "Phase", "small"), ("decision", "Décision", "small"),
    ("sensitivity_scope", "Scope P4", "small"), ("sensitivity_symbol", "Symbole P4", "small"),
    ("sensitivity_timeframe", "TF P4", "small"),
    ("wfa_scope", "Scope WFA", "small"), ("wfa_symbol", "Symbole WFA", "small"),
    ("wfa_timeframe", "TF WFA", "small"),
    ("benchmark_pass_summary", "Benchmarks", "small"), ("context_pass_summary", "Contextes", "small"),
    ("required_benchmark_name", "Benchmark requis", "medium"), ("contradiction_state", "Consensus", "small"),
    ("rejection_reason", "Rejet / diagnostic", "large"), ("params_used_preview", "Params", "large"),
)


_RESULTS_HUB_NUMBER_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "$%.2f": (
        ("total_pnl", "PnL ($)"), ("pnl_per_day", "PnL/jour ($)"),
        ("pnl_per_day_covered", "PnL/jour (données)"), ("metrics_total_pnl", "PnL ($)"),
        ("pnl", "PnL ($)"),
    ),
    "%.2f%%": (
        ("total_return_pct", "Return (%)"), ("benchmark_return_pct", "Buy & Hold (%)"),
        ("alpha_simple_pct", "Alpha simple (%)"), ("metrics_total_return_pct", "Return (%)"),
        ("metrics_benchmark_return_pct", "Buy & Hold (%)"), ("metrics_alpha_simple_pct", "Alpha simple (%)"),
        ("best_return_pct", "Best return (%)"), ("wfa_avg_test_return_pct", "WFA return test (%)"),
        ("wfa_positive_folds_pct", "WFA folds + (%)"), ("return_pct", "Return (%)"),
    ),
    "%.1f%%": (
        ("max_drawdown_pct", "Max DD (%)"), ("win_rate_pct", "Win Rate (%)"),
        ("data_coverage_pct", "Couverture données (%)"), ("catalog_coverage_pct", "Couverture validation (%)"),
        ("metrics_max_drawdown_pct", "Max DD (%)"), ("best_max_drawdown_pct", "Best DD (%)"),
        ("sweep_robustness_pct", "Robustesse sweep (%)"), ("coverage_pct", "Couverture ctx uniques (%)"),
        ("benchmark_slot_coverage_pct", "Couverture packs (%)"),
    ),
    "%.2f": (
        ("sharpe_ratio", "Sharpe"), ("profit_factor", "PF"), ("metrics_sharpe_ratio", "Sharpe"),
        ("metrics_profit_factor", "PF"), ("best_sharpe", "Best Sharpe"),
        ("best_profit_factor", "Best PF"), ("wfa_stability", "WFA stabilité"),
        ("wfa_avg_test_sharpe", "WFA Sharpe test"),
        ("wfa_classic_overfitting_ratio", "WFA ratio classique"),
        ("wfa_robust_overfitting_score", "WFA score robuste"),
        ("wfa_overfitting_ratio", "WFA score legacy"),
        ("sharpe", "Sharpe"),
    ),
    "%d": (
        ("total_trades", "Trades"), ("n_bars", "Bars"), ("n_trades", "Trades"),
        ("n_completed", "Complétés"), ("n_failed", "Échecs"), ("n_trials", "Trials"),
        ("n_pruned", "Prunés"), ("total_combinations", "Combinaisons"), ("max_combos", "Max combos"),
        ("n_workers", "Workers"), ("iteration", "Itération"), ("builder_iteration", "Iter builder"),
        ("leaderboard_rank", "Rank"), ("total_iterations", "Itérations"), ("total_llm_tokens", "Tokens LLM"),
        ("total_llm_calls", "Appels LLM"), ("metrics_total_trades", "Trades"), ("best_trades", "Best trades"),
        ("trades", "Trades"), ("configured_context_count", "Ctx uniques cfg"),
        ("loaded_context_count", "Ctx uniques chargés"), ("missing_context_count", "Ctx exclus/manquants"),
        ("sensitivity_history_bars", "Barres P4"), ("sensitivity_min_history_bars", "Min P4"),
        ("wfa_valid_folds", "Folds WFA"), ("wfa_history_bars", "Barres WFA"),
        ("wfa_min_history_bars", "Min WFA"),
    ),
    "%.4f": (("best_value", "Meilleure val."),),
    "%.1f": (("total_time_sec", "Durée (s)"),),
}


def _get_numeric_column_config() -> dict[str, Any]:
    """Configuration des colonnes pour un tableau dense et lisible dans st.dataframe."""
    config: dict[str, Any] = {
        "select": st.column_config.CheckboxColumn("Sel.", width="small"),
        "strategy_name_link": st.column_config.LinkColumn(
            "Stratégie",
            width="large",
            display_text=r".*#(.*)$",
        ),
        "replayable": st.column_config.CheckboxColumn("Replay", width="small"),
        "open_folder": st.column_config.LinkColumn("Dossier", display_text="📂 Ouvrir"),
        "_row_key": None,
        "_row_origin": None,
        "_origin_index": None,
    }
    config.update(_text_column_config(*_RESULTS_HUB_TEXT_COLUMNS))
    config.update(_number_column_config(_RESULTS_HUB_NUMBER_COLUMNS))
    return config


_RESULTS_HUB_TABLE_COLUMNS = [
    "select",
    "hub_source",
    "hub_type",
    "run_id",
    "id",
    "session_id",
    "entry_id",
    "strategy_name_link",
    "strategy",
    "symbol",
    "timeframe",
    "status",
    "mode",
    "artifact_type",
    "category",
    "catalog_category",
    "catalog_status",
    "phase",
    "decision",
    "total_pnl",
    "pnl_per_day",
    "pnl_per_day_covered",
    "total_return_pct",
    "return_pct",
    "best_return_pct",
    "sharpe_ratio",
    "sharpe",
    "best_sharpe",
    "max_drawdown_pct",
    "profit_factor",
    "best_profit_factor",
    "total_trades",
    "trades",
    "best_trades",
    "benchmark_return_pct",
    "alpha_simple_pct",
    "benchmark_pass_summary",
    "context_pass_summary",
    "required_benchmark_name",
    "contradiction_state",
    "coverage_pct",
    "catalog_coverage_pct",
    "configured_context_count",
    "loaded_context_count",
    "missing_context_count",
    "sweep_robustness_pct",
    "sensitivity_scope",
    "sensitivity_symbol",
    "sensitivity_timeframe",
    "sensitivity_history_bars",
    "wfa_stability",
    "wfa_avg_test_return_pct",
    "wfa_avg_test_sharpe",
    "wfa_classic_overfitting_ratio",
    "wfa_robust_overfitting_score",
    "wfa_overfitting_ratio",
    "wfa_valid_folds",
    "wfa_positive_folds_pct",
    "wfa_confidence_tier",
    "wfa_scope",
    "wfa_symbol",
    "wfa_timeframe",
    "wfa_history_bars",
    "rejection_reason",
    "source_ref",
    "source_run_id",
    "replayable",
    "promotable",
    "open_folder",
    "params_used_preview",
    "objective_excerpt",
    "_row_key",
    "_row_origin",
    "_origin_index",
]


def _first_non_empty(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        normalized = _normalize_cell(value)
        if normalized not in (None, ""):
            return normalized
    return ""


def _canonicalize_result_metrics(row: dict[str, Any]) -> None:
    metric_aliases = {
        "total_pnl": ["metrics_total_pnl", "pnl"],
        "total_return_pct": ["metrics_total_return_pct", "return_pct", "best_return_pct"],
        "benchmark_return_pct": ["metrics_benchmark_return_pct"],
        "alpha_simple_pct": ["metrics_alpha_simple_pct"],
        "sharpe_ratio": ["metrics_sharpe_ratio", "sharpe", "best_sharpe"],
        "max_drawdown_pct": ["metrics_max_drawdown_pct", "best_max_drawdown_pct"],
        "profit_factor": ["metrics_profit_factor", "best_profit_factor"],
        "total_trades": ["metrics_total_trades", "trades", "best_trades", "n_trades"],
    }
    for target, aliases in metric_aliases.items():
        if _normalize_cell(row.get(target)) not in (None, ""):
            continue
        fallback = _first_non_empty(row, *aliases)
        if fallback not in (None, ""):
            row[target] = fallback


def _append_hub_rows(
    rows: list[dict[str, Any]],
    source_df: pd.DataFrame,
    *,
    origin: str,
    source_label: str,
    type_label: str,
    action_scope: str = "",
) -> None:
    if source_df.empty:
        return
    for idx, raw_row in enumerate(source_df.to_dict(orient="records")):
        row = {key: _normalize_cell(value) for key, value in raw_row.items()}
        row["_row_origin"] = origin
        row["_origin_index"] = idx
        row["hub_source"] = source_label
        row["hub_type"] = str(_first_non_empty(row, "type", "artifact_type") or type_label)
        row["hub_action_scope"] = action_scope
        row["run_id"] = _first_non_empty(row, "run_id", "source_run_id") or row.get("run_id", "")
        row["id"] = _first_non_empty(row, "id", "session_id", "entry_id", "candidate_id", "run_id")
        row["strategy"] = _first_non_empty(row, "strategy", "strategy_name")
        row["symbol"] = _first_non_empty(row, "symbol", "source_symbol")
        row["timeframe"] = _first_non_empty(row, "timeframe", "source_timeframe")
        row["catalog_category"] = _first_non_empty(row, "catalog_category", "category")
        row["replayable"] = bool(row.get("replayable")) or action_scope in {"catalog_replay", "run_replay"}
        row["promotable"] = action_scope == "run_replay"
        _canonicalize_result_metrics(row)
        stable_id = _first_non_empty(row, "run_id", "session_id", "entry_id", "candidate_id", "id") or idx
        row["_row_key"] = f"{origin}:{stable_id}:{idx}"
        rows.append(row)


def _build_results_hub_table_df(
    *,
    backtest_overview: pd.DataFrame,
    unified_overview: pd.DataFrame,
    runs_overview: pd.DataFrame,
    builder_sessions_df: pd.DataFrame,
    builder_iterations_df: pd.DataFrame,
    strategy_catalog_df: pd.DataFrame,
    graduation_df: pd.DataFrame,
    positive_import_df: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    _append_hub_rows(
        rows,
        backtest_overview,
        origin="backtest_overview",
        source_label="Backtests / optimisations",
        type_label="résultat",
    )
    _append_hub_rows(
        rows,
        runs_overview,
        origin="runs_overview",
        source_label="Runs LLM",
        type_label="run_llm",
    )
    _append_hub_rows(
        rows,
        builder_sessions_df,
        origin="builder_sessions",
        source_label="Builder sessions",
        type_label="builder_session",
    )
    _append_hub_rows(
        rows,
        builder_iterations_df,
        origin="builder_iterations",
        source_label="Builder iterations",
        type_label="builder_iteration",
    )
    _append_hub_rows(
        rows,
        unified_overview,
        origin="unified_overview",
        source_label="Stock unifié",
        type_label="artefact",
        action_scope="run_replay",
    )
    catalog_df = strategy_catalog_df.copy()
    if not catalog_df.empty:
        catalog_df["replayable"] = catalog_df.apply(lambda row: _catalog_entry_has_replay_source(row.to_dict()), axis=1)
    _append_hub_rows(
        rows,
        catalog_df,
        origin="strategy_catalog",
        source_label="Strategy catalog",
        type_label="catalog_entry",
        action_scope="catalog_replay",
    )
    graduation_linked_df = _decorate_graduation_strategy_links(graduation_df)
    _append_hub_rows(
        rows,
        graduation_linked_df,
        origin="graduation_sandbox",
        source_label="Graduation complète",
        type_label="graduation_candidate",
    )
    positive_linked_df = _decorate_graduation_strategy_links(positive_import_df)
    _append_hub_rows(
        rows,
        positive_linked_df,
        origin="graduation_positive",
        source_label="Graduation positifs",
        type_label="graduation_candidate",
    )

    if not rows:
        return pd.DataFrame()

    table_df = pd.DataFrame(rows)
    table_df["select"] = False
    numeric_columns = [
        "total_pnl",
        "pnl_per_day",
        "pnl_per_day_covered",
        "total_return_pct",
        "return_pct",
        "best_return_pct",
        "sharpe_ratio",
        "sharpe",
        "best_sharpe",
        "max_drawdown_pct",
        "profit_factor",
        "best_profit_factor",
        "total_trades",
        "trades",
        "best_trades",
        "benchmark_return_pct",
        "alpha_simple_pct",
        "coverage_pct",
        "catalog_coverage_pct",
        "configured_context_count",
        "loaded_context_count",
        "missing_context_count",
        "sweep_robustness_pct",
        "wfa_stability",
        "wfa_avg_test_return_pct",
        "wfa_avg_test_sharpe",
        "wfa_classic_overfitting_ratio",
        "wfa_robust_overfitting_score",
        "wfa_overfitting_ratio",
    ]
    table_df = _coerce_numeric(table_df, numeric_columns)
    sort_cols = [col for col in ["total_pnl", "sharpe_ratio", "total_return_pct"] if col in table_df.columns]
    if sort_cols:
        table_df = table_df.sort_values(sort_cols, ascending=[False] * len(sort_cols), na_position="last")
    return table_df.reset_index(drop=True)


def _render_results_hub_unified_filters(table_df: pd.DataFrame) -> pd.DataFrame:
    if table_df.empty:
        return table_df

    source_options = sorted(table_df["hub_source"].dropna().astype(str).unique().tolist())
    type_options = sorted(table_df["hub_type"].dropna().astype(str).unique().tolist())
    strategy_options = sorted([value for value in table_df["strategy"].dropna().astype(str).unique().tolist() if value])
    symbol_options = sorted([value for value in table_df["symbol"].dropna().astype(str).unique().tolist() if value])
    timeframe_options = sorted([value for value in table_df["timeframe"].dropna().astype(str).unique().tolist() if value])
    catalog_options = sorted(
        [value for value in table_df["catalog_category"].dropna().astype(str).unique().tolist() if value],
    )

    filter_cols = st.columns(4)
    selected_sources = filter_cols[0].multiselect(
        "Sources",
        options=source_options,
        default=source_options,
        key="results_hub_unified_sources",
    )
    selected_types = filter_cols[1].multiselect(
        "Types",
        options=type_options,
        default=type_options,
        key="results_hub_unified_types",
    )
    selected_strategies = filter_cols[2].multiselect(
        "Stratégies",
        options=strategy_options,
        default=[],
        key="results_hub_unified_strategies",
    )
    selected_symbols = filter_cols[3].multiselect(
        "Symboles",
        options=symbol_options,
        default=[],
        key="results_hub_unified_symbols",
    )

    filter_cols_2 = st.columns(4)
    selected_timeframes = filter_cols_2[0].multiselect(
        "Timeframes",
        options=timeframe_options,
        default=[],
        key="results_hub_unified_timeframes",
    )
    selected_categories = filter_cols_2[1].multiselect(
        "Catégories catalogue",
        options=catalog_options,
        default=[],
        key="results_hub_unified_catalog_categories",
    )
    action_only = filter_cols_2[2].checkbox(
        "Actionnables uniquement",
        value=False,
        key="results_hub_unified_action_only",
    )
    search_term = filter_cols_2[3].text_input(
        "Recherche",
        placeholder="run, session, stratégie, diagnostic...",
        key="results_hub_unified_search",
    ).strip()

    filtered = table_df.copy()
    if selected_sources:
        filtered = filtered[filtered["hub_source"].astype(str).isin(selected_sources)]
    if selected_types:
        filtered = filtered[filtered["hub_type"].astype(str).isin(selected_types)]
    if selected_strategies:
        filtered = filtered[filtered["strategy"].astype(str).isin(selected_strategies)]
    if selected_symbols:
        filtered = filtered[filtered["symbol"].astype(str).isin(selected_symbols)]
    if selected_timeframes:
        filtered = filtered[filtered["timeframe"].astype(str).isin(selected_timeframes)]
    if selected_categories:
        filtered = filtered[filtered["catalog_category"].astype(str).isin(selected_categories)]
    if action_only:
        replayable = filtered.get("replayable", pd.Series(False, index=filtered.index)).fillna(False).astype(bool)
        promotable = filtered.get("promotable", pd.Series(False, index=filtered.index)).fillna(False).astype(bool)
        filtered = filtered[replayable | promotable]
    if search_term:
        lower_term = search_term.lower()
        searchable_cols = [
            col
            for col in [
                "hub_source",
                "hub_type",
                "run_id",
                "id",
                "session_id",
                "entry_id",
                "strategy",
                "symbol",
                "timeframe",
                "status",
                "phase",
                "decision",
                "rejection_reason",
                "objective_excerpt",
                "source_ref",
            ]
            if col in filtered.columns
        ]
        if searchable_cols:
            mask = pd.Series(False, index=filtered.index)
            for col in searchable_cols:
                mask = mask | filtered[col].astype(str).str.lower().str.contains(lower_term, na=False)
            filtered = filtered[mask]

    return filtered.reset_index(drop=True)


def _render_results_hub_summary(table_df: pd.DataFrame, filtered_df: pd.DataFrame) -> None:
    metric_cols = st.columns(5)
    metric_cols[0].metric("Lignes visibles", f"{len(filtered_df)}/{len(table_df)}")
    metric_cols[1].metric(
        "Sources",
        int(filtered_df["hub_source"].nunique()) if "hub_source" in filtered_df.columns and not filtered_df.empty else 0,
    )
    metric_cols[2].metric(
        "Replayables",
        int(filtered_df.get("replayable", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()),
    )
    metric_cols[3].metric(
        "Promouvables",
        int(filtered_df.get("promotable", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()),
    )
    best_return = pd.to_numeric(filtered_df.get("total_return_pct", pd.Series(dtype=float)), errors="coerce").max()
    metric_cols[4].metric("Best return", "-" if pd.isna(best_return) else f"{best_return:.2f}%")

    if not filtered_df.empty and "hub_source" in filtered_df.columns:
        source_counts = filtered_df["hub_source"].astype(str).value_counts().to_dict()
        st.caption("Répartition visible: " + " | ".join(f"{source}: {count}" for source, count in source_counts.items()))


def _render_results_hub_table(filtered_df: pd.DataFrame) -> pd.DataFrame:
    if filtered_df.empty:
        st.write("ℹ️ Aucun résultat ne correspond aux filtres.")
        return filtered_df

    display_cols = [col for col in _RESULTS_HUB_TABLE_COLUMNS if col in filtered_df.columns]
    display_df = filtered_df[display_cols].copy()
    if "strategy_name_link" in display_df.columns and "strategy" in display_df.columns:
        linked_mask = display_df["strategy_name_link"].astype(str).str.contains(r"://", na=False)
        display_df.loc[~linked_mask, "strategy_name_link"] = display_df.loc[~linked_mask, "strategy"]
    edited = st.data_editor(
        display_df,
        width="stretch",
        hide_index=True,
        column_config=_get_numeric_column_config(),
        disabled=[col for col in display_df.columns if col != "select"],
        key="results_hub_unified_table",
    )
    if not isinstance(edited, pd.DataFrame) or "select" not in edited.columns or "_row_key" not in edited.columns:
        return pd.DataFrame()
    selected_keys = edited.loc[edited["select"] == True, "_row_key"].astype(str).tolist()  # noqa: E712
    if not selected_keys:
        return pd.DataFrame()
    return filtered_df[filtered_df["_row_key"].astype(str).isin(selected_keys)].copy()


def _source_rows_by_run_id(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if df.empty or "run_id" not in df.columns:
        return {}
    return {
        str(row.get("run_id") or ""): row
        for row in df.to_dict(orient="records")
        if str(row.get("run_id") or "").strip()
    }


def _source_rows_by_entry_id(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if df.empty or "entry_id" not in df.columns:
        return {}
    return {
        str(row.get("entry_id") or ""): row
        for row in df.to_dict(orient="records")
        if str(row.get("entry_id") or "").strip()
    }


def _render_results_hub_actions(
    selected_df: pd.DataFrame,
    *,
    unified_overview: pd.DataFrame,
    strategy_catalog_df: pd.DataFrame,
) -> None:
    if selected_df.empty:
        st.caption("Sélectionnez une ou plusieurs lignes dans le tableau unique pour activer replay ou promotion.")
        return

    st.caption(f"Sélection active: {len(selected_df)} ligne(s).")
    source_rows = _source_rows_by_run_id(unified_overview)
    catalog_rows = _source_rows_by_entry_id(strategy_catalog_df)
    selected_records = selected_df.to_dict(orient="records")

    selected_run_rows = []
    for row in selected_records:
        if row.get("_row_origin") != "unified_overview":
            continue
        run_id = str(row.get("run_id") or "").strip()
        source_row = source_rows.get(run_id)
        if source_row is not None:
            selected_run_rows.append(source_row)

    selected_catalog_entry = None
    catalog_selected = [row for row in selected_records if row.get("_row_origin") == "strategy_catalog"]
    if len(catalog_selected) == 1:
        selected_catalog_entry = catalog_rows.get(str(catalog_selected[0].get("entry_id") or "").strip())

    target_category = st.selectbox(
        "Cible catalogue",
        CATEGORY_ORDER,
        index=CATEGORY_ORDER.index("p3_benchmark_consensus"),
        help="Utilisé par les actions de promotion depuis les lignes `Stock unifié`.",
        key="results_hub_unified_target_category",
    )

    action_cols = st.columns(4)
    with action_cols[0]:
        if st.button(
            "Précharger replay",
            disabled=selected_catalog_entry is None,
            use_container_width=True,
            key="results_hub_unified_preload_replay",
        ):
            replay_request, replay_msg = _build_catalog_replay_request(
                selected_catalog_entry or {},
                unified_overview,
                auto_run=False,
            )
            if replay_request is None:
                st.warning(replay_msg)
            else:
                st.session_state["_catalog_replay_request"] = replay_request
                st.session_state["saved_runs_status"] = replay_msg
                st.rerun()
    with action_cols[1]:
        if st.button(
            "Rejouer maintenant",
            type="primary",
            disabled=selected_catalog_entry is None,
            use_container_width=True,
            key="results_hub_unified_run_replay",
        ):
            replay_request, replay_msg = _build_catalog_replay_request(
                selected_catalog_entry or {},
                unified_overview,
                auto_run=True,
            )
            if replay_request is None:
                st.warning(replay_msg)
            else:
                st.session_state["_catalog_replay_request"] = replay_request
                st.session_state["saved_runs_status"] = replay_msg
                st.rerun()
    with action_cols[2]:
        if st.button(
            "Promouvoir sélection",
            disabled=not selected_run_rows,
            use_container_width=True,
            key="results_hub_unified_promote",
        ):
            promoted = 0
            failures: list[str] = []
            for row in selected_run_rows:
                try:
                    upsert_from_saved_run(row, target_category=target_category)
                    promoted += 1
                except Exception as exc:
                    failures.append(f"{row.get('run_id', '?')}: {exc}")
            if promoted:
                st.success(f"✅ {promoted} stratégie(s) synchronisée(s) vers le catalogue.")
            if failures:
                st.warning(" | ".join(failures[:5]))
            st.rerun()
    with action_cols[3]:
        if st.button(
            "Promouvoir + rejouer",
            disabled=len(selected_run_rows) != 1,
            use_container_width=True,
            key="results_hub_unified_promote_and_replay",
        ):
            selected_candidate_row = selected_run_rows[0] if selected_run_rows else None
            if selected_candidate_row is None:
                st.warning("Sélectionnez exactement un run source.")
            else:
                try:
                    upsert_from_saved_run(selected_candidate_row, target_category=target_category)
                    replay_request, replay_msg = _build_run_row_replay_request(
                        selected_candidate_row,
                        auto_run=True,
                    )
                except Exception as exc:
                    replay_request = None
                    replay_msg = str(exc)
                if replay_request is None:
                    st.warning(replay_msg)
                else:
                    st.session_state["_catalog_replay_request"] = replay_request
                    st.session_state["saved_runs_status"] = replay_msg
                    st.rerun()

    with st.expander("Détail ligne sélectionnée", expanded=False):
        st.json(selected_records[0] if len(selected_records) == 1 else selected_records)


def _render_graduation_controls_and_progress(
    *,
    sandbox_payload: dict[str, Any],
    sandbox_df: pd.DataFrame,
    positive_payload: dict[str, Any],
    positive_df: pd.DataFrame,
) -> None:
    st.markdown("### Filtrage intelligent des résultats")

    main_col_a, main_col_b, main_col_c = st.columns([1.2, 1.8, 1.8])
    if main_col_a.button(
        "🔄 Rafraîchir affichage",
        key="graduation_refresh",
        type="primary",
        use_container_width=True,
        help="Recharge l'état affiché (rapports, progress, logs). Ne relance aucun pipeline.",
    ):
        st.rerun()
    sync_catalog = main_col_b.checkbox(
        "Synchroniser le strategy catalog",
        value=True,
        key="graduation_sync_catalog",
    )
    if main_col_c.button(
        "▶️ Relancer P1→P6",
        key="graduation_run_full",
        use_container_width=True,
        help=(
            "Relance réellement la graduation complète via `python -m catalog.graduation --full`. "
            "Nécessaire après changement des règles P4/P5."
        ),
    ):
        ok, message = _launch_full_graduation_from_ui(sync_catalog=sync_catalog)
        st.session_state["graduation_status_msg"] = message
        st.session_state["graduation_status_error"] = not ok
        st.rerun()

    with st.expander("⚙️ Actions avancées", expanded=False):
        st.caption(
            "Diagnostic uniquement : l'action principale relance désormais la graduation unique P1→P6.",
        )
        if st.button(
            "Inventaire P1 brut",
            key="graduation_run_p1",
            use_container_width=True,
            help="Lance la commande CLI `python -m catalog.graduation` pour l'inventaire P1 brut.",
        ):
            ok, message = _launch_p1_inventory_from_ui(sync_catalog=sync_catalog)
            st.session_state["graduation_status_msg"] = message
            st.session_state["graduation_status_error"] = not ok
            st.rerun()

    status_msg = st.session_state.get("graduation_status_msg")
    if status_msg:
        if st.session_state.get("graduation_status_error"):
            st.error(status_msg)
        else:
            st.success(status_msg)

    _render_progress_section(
        title="Progression unique P1→P6",
        payload=_load_progress_payload(FULL_GRADUATION_PROGRESS_FILENAME),
        log_filename=FULL_GRADUATION_LOG_FILENAME,
        report_payload=sandbox_payload,
        report_df=sandbox_df,
    )


def render_results_hub(*, embedded: bool = False) -> None:
    if embedded:
        st.subheader("📚 Résultats, sauvegardes et catalogue")
    else:
        st.header("📚 Résultats & Catalogues")

    col_left, col_right = st.columns([1, 2])
    with col_left:
        refresh = st.button("🔄 Rafraîchir catalogues")
    with col_right:
        st.caption(
            "Catalogues CSV non-destructifs basés sur "
            f"`{RESULTS_DIR}`, `{RUNS_DIR}`, `{get_builder_sessions_dir()}` et `strategy_catalog.json`.",
        )

    backtest_overview, unified_overview, runs_overview = _load_catalogs(refresh=refresh)
    builder_sessions_df, builder_iterations_df, builder_catalog_audit = _load_builder_store_payload()
    backtest_overview = _add_open_links_from_results_path(backtest_overview)
    unified_overview = _add_open_links_from_results_path(unified_overview)
    runs_overview = _add_open_links_runs(runs_overview)
    backtest_overview = _add_pnl_per_day(backtest_overview)
    strategy_catalog_df = _load_strategy_catalog_df()
    unified_overview = _decorate_unified_with_catalog(unified_overview, strategy_catalog_df)
    sandbox_payload, sandbox_df = _load_graduation_report()
    positive_payload, positive_df = _load_positive_import_report()

    _render_latest_run(backtest_overview, runs_overview, builder_sessions_df)

    st.markdown("---")
    st.subheader("🗂️ Catalogue global unifié")

    if (
        backtest_overview.empty
        and unified_overview.empty
        and runs_overview.empty
        and builder_sessions_df.empty
        and builder_iterations_df.empty
        and strategy_catalog_df.empty
        and sandbox_df.empty
        and positive_df.empty
    ):
        st.write("ℹ️ Aucun catalogue disponible. Lancez un run puis cliquez sur Rafraîchir catalogues.")
        return

    table_df = _build_results_hub_table_df(
        backtest_overview=backtest_overview,
        unified_overview=unified_overview,
        runs_overview=runs_overview,
        builder_sessions_df=builder_sessions_df,
        builder_iterations_df=builder_iterations_df,
        strategy_catalog_df=strategy_catalog_df,
        graduation_df=sandbox_df,
        positive_import_df=positive_df,
    )
    filtered_df = _render_results_hub_unified_filters(table_df)
    _render_results_hub_summary(table_df, filtered_df)
    selected_df = _render_results_hub_table(filtered_df)
    _render_results_hub_actions(
        selected_df,
        unified_overview=unified_overview,
        strategy_catalog_df=strategy_catalog_df,
    )

    _render_charts(filtered_df)
    _render_graduation_controls_and_progress(
        sandbox_payload=sandbox_payload,
        sandbox_df=sandbox_df,
        positive_payload=positive_payload,
        positive_df=positive_df,
    )
