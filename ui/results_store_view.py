"""
Dedicated Streamlit view for browsing the centralized external results store.
"""

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


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _display_float(value: Any) -> float:
    coerced = _coerce_float(value)
    if coerced is None or pd.isna(coerced):
        return 0.0
    return float(coerced)


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
        float(int(getattr(trace, "iteration_num", 0) or 0)),
    )


def _summary_dict(summary: dict[str, Any], key: str) -> dict[str, Any]:
    value = summary.get(key)
    return dict(value or {}) if isinstance(value, dict) else {}


def _summary_list(summary: dict[str, Any], key: str) -> list[Any]:
    value = summary.get(key)
    return list(value or []) if isinstance(value, list) else []


def _render_multi_llm_session_memory_panel(summary: dict[str, Any]) -> None:
    if str(summary.get("orchestration_mode") or "") != "multi_llm":
        return

    shared_memory = _summary_dict(summary, "multi_llm_shared_memory")
    continuity = _summary_dict(summary, "continuity_context") or _summary_dict(
        shared_memory,
        "continuity_context",
    )
    router_decision = _summary_dict(summary, "multi_llm_router_decision")
    role_outputs = _summary_dict(summary, "multi_llm_role_outputs")
    assignments = _summary_list(summary, "multi_llm_assignments")

    if not continuity and not shared_memory and not router_decision and not assignments:
        st.info("Aucune mémoire multi-LLM persistée pour cette session.")
        return

    st.markdown("**Mémoire de campagne**")
    st.caption(
        "Référence partagée entre les rôles multi-LLM pour conserver les meilleurs runs récents, "
        "les focus à reprendre et les risques récurrents."
    )

    recent_sessions = list(continuity.get("recent_sessions", []) or [])
    carry_over_focus = list(continuity.get("carry_over_focus", []) or [])
    recurring_risks = list(continuity.get("recurring_risks", []) or [])
    router_context = _summary_dict(shared_memory, "router_context")

    metric_cols = st.columns(4)
    metric_cols[0].metric("Sessions récentes", len(recent_sessions))
    metric_cols[1].metric("Focus", len(carry_over_focus))
    metric_cols[2].metric("Risques", len(recurring_risks))
    metric_cols[3].metric(
        "Décision routeur",
        str(
            router_decision.get("action")
            or router_context.get("action")
            or "n/a"
        ),
    )

    best_recent = _summary_dict(continuity, "best_recent_session")
    if best_recent:
        st.caption(
            "Meilleur run récent transmis: "
            f"session #{best_recent.get('session_num', '?')} | "
            f"{best_recent.get('symbol', '?')} {best_recent.get('timeframe', '?')} | "
            f"Sharpe {best_recent.get('best_sharpe', 'n/a')}"
        )

    if carry_over_focus:
        st.markdown("**Focus à reprendre**")
        for item in carry_over_focus:
            st.markdown(f"- {item}")
    if recurring_risks:
        st.markdown("**Risques récurrents**")
        for item in recurring_risks:
            st.markdown(f"- {item}")

    st.markdown("**Analyse avancée multi-LLM**")
    if assignments:
        assignment_rows = [
            {
                "role": str(item.get("role", "") or ""),
                "demande": str(item.get("requested_model", "") or ""),
                "résolu": str(item.get("resolved_model", "") or ""),
                "host": str(item.get("host", "") or ""),
                "disponible": bool(item.get("available", False)),
            }
            for item in assignments
            if isinstance(item, dict)
        ]
        with st.expander("Rôles et résolutions effectives", expanded=False):
            st.dataframe(assignment_rows, width="stretch", hide_index=True)

    if role_outputs:
        role_rows = [
            {
                "role": role,
                "modèle": str(payload.get("model", "") or ""),
                "disponible": bool(payload.get("available", False)),
                "erreur": str(payload.get("error", "") or ""),
                "aperçu": str(payload.get("content_excerpt", "") or ""),
            }
            for role, payload in role_outputs.items()
            if isinstance(payload, dict)
        ]
        with st.expander("Sorties compactes des rôles", expanded=False):
            st.dataframe(role_rows, width="stretch", hide_index=True)

    if shared_memory:
        with st.expander("Mémoire partagée multi-LLM", expanded=False):
            st.json(shared_memory)


def _trace_from_dict(payload: dict[str, Any]) -> PipelineTrace | None:
    if PipelineTrace is None or PhaseMeasurement is None or not isinstance(payload, dict):
        return None
    trace = PipelineTrace(
        iteration_num=int(payload.get("iteration_num", 0) or 0),
        session_id=str(payload.get("session_id", "") or ""),
        timestamp=float(payload.get("timestamp", 0.0) or 0.0),
    )
    for key, value in payload.items():
        if key == "phases":
            continue
        if hasattr(trace, key):
            setattr(trace, key, value)
    trace.phases = [
        PhaseMeasurement(**phase)
        for phase in list(payload.get("phases", []) or [])
        if isinstance(phase, dict)
    ]
    return trace


def _select_reference_trace(trace_payload: dict[str, Any]) -> PipelineTrace | None:
    traces = [
        _trace_from_dict(item)
        for item in list(trace_payload.get("traces", []) or [])
        if isinstance(item, dict)
    ]
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


def _compute_builder_best_return(summary: dict[str, Any]) -> float | None:
    candidates: list[float] = []
    direct_value = _coerce_float(summary.get("best_return_pct"))
    if direct_value is not None:
        candidates.append(direct_value)

    for iteration in summary.get("iterations") or []:
        value = _coerce_float((iteration or {}).get("return_pct"))
        if value is not None:
            candidates.append(value)
    if not candidates:
        return None
    return max(candidates)


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

        rows.append(
            {
                "session_id": session_dir.name,
                "status": str(summary.get("status") or "unknown"),
                "best_sharpe": _coerce_float(summary.get("best_sharpe")),
                "best_telemetry_score": _coerce_float(
                    summary.get("best_telemetry_score", summary.get("best_score"))
                ),
                "best_score": _coerce_float(summary.get("best_score")),
                "best_return_pct": _compute_builder_best_return(summary),
                "total_iterations": int(summary.get("total_iterations") or len(summary.get("iterations") or [])),
                "auto_reset_count": int(summary.get("auto_reset_count") or 0),
                "objective": str(summary.get("objective") or ""),
                "objective_excerpt": _shorten(str(summary.get("objective") or "")),
                "builder_execution_mode": str(
                    summary.get("builder_execution_mode") or "mono_single_llm"
                ),
                "orchestration_mode": str(
                    summary.get("orchestration_mode") or "single_llm"
                ),
                "instrumentation_enabled": bool(
                    summary.get("instrumentation_enabled", False)
                ),
                "instrumentation_summary": (
                    dict(summary.get("instrumentation_summary", {}) or {})
                    if isinstance(summary.get("instrumentation_summary"), dict)
                    else {}
                ),
                "multi_llm_profile": str(summary.get("multi_llm_profile") or ""),
                "multi_llm_assignments": _summary_list(summary, "multi_llm_assignments"),
                "multi_llm_router_decision": _summary_dict(summary, "multi_llm_router_decision"),
                "multi_llm_role_outputs": _summary_dict(summary, "multi_llm_role_outputs"),
                "multi_llm_shared_memory": _summary_dict(summary, "multi_llm_shared_memory"),
                "continuity_context": (
                    _summary_dict(summary, "continuity_context")
                    or _summary_dict(
                        _summary_dict(summary, "multi_llm_shared_memory"),
                        "continuity_context",
                    )
                ),
                "session_dir": str(session_dir),
                "summary_path": str(summary_path) if summary_path.exists() else "",
                "pipeline_traces_path": str(pipeline_traces_path) if pipeline_traces_path else "",
                "latest_strategy_path": str(latest_strategy_path) if latest_strategy_path else "",
                "strategy_versions": len(strategy_versions),
                "last_modified": _format_timestamp(last_modified),
            }
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
        ("Racine resultats", results_root),
        ("Racine artefacts", artifacts_root),
        ("Analyses", analysis_root),
        ("Sessions Builder", builder_root),
        ("Runs sauvegardes", saved_runs_root),
        ("Diagnostics sweeps", diagnostics_root),
        ("Profiling", profiling_root),
        ("Output", output_root),
        ("Resultats organises", organized_root),
        ("Archives", archive_root),
        ("Legacy runs", legacy_runs_dir),
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
            }
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
            }
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


@st.cache_data(show_spinner=False)
def _load_builder_sessions_df(builder_root: str) -> pd.DataFrame:
    rows = collect_builder_sessions(Path(builder_root))
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
) -> None:
    raw_run_count = sum(
        1
        for child in results_root.iterdir()
        if child.is_dir() and not child.name.startswith("_") and child.name != "runs"
    ) if results_root.exists() else 0
    legacy_runs_count = _count_children(results_root / "runs")
    catalog_path = results_root / "_catalog" / "overview.csv"
    catalog_rows = 0
    if catalog_path.exists():
        try:
            catalog_rows = max(sum(1 for _ in catalog_path.open(encoding="utf-8")) - 1, 0)
        except OSError:
            catalog_rows = 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Runs catalogues", catalog_rows)
    col2.metric("Dossiers resultats", raw_run_count)
    col3.metric("Sessions Builder", int(len(builder_df)))
    col4.metric("Fichiers analyse", int(len(analysis_files_df)))

    st.caption(
        f"Resultats: `{results_root}` | Artefacts: `{artifacts_root}` | Legacy runs: {legacy_runs_count}"
    )

    analysis_root = artifacts_root / "_analysis"
    builder_root = artifacts_root / "_builder_sessions"
    output_root = artifacts_root / "_output"
    quick_cols = st.columns(5)
    quick_actions = [
        ("Ouvrir store", results_root),
        ("Ouvrir artefacts", artifacts_root),
        ("Ouvrir analyses", analysis_root),
        ("Ouvrir Builder", builder_root),
        ("Ouvrir output", output_root),
    ]
    for idx, (label, path) in enumerate(quick_actions):
        with quick_cols[idx]:
            _handle_open_action(path, button_label=label, key=f"store-open-{idx}")

    if not inventory_df.empty:
        with st.expander("Chemins suivis par la page", expanded=False):
            st.dataframe(inventory_df, width="stretch", hide_index=True)


def _render_builder_tab(builder_df: pd.DataFrame, results_root: Path) -> None:
    st.markdown("### Sessions Builder")
    if builder_df.empty:
        st.info("Aucune session Builder detectee dans le store externe.")
        return

    filtered = builder_df.copy()
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
        ]

    filtered = filtered.sort_values("last_modified", ascending=False, na_position="last")
    st.dataframe(
        filtered[
            [
                "session_id",
                "status",
                "best_return_pct",
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
    info_cols[0].metric("Statut", str(selected_row.get("status") or "?"))
    info_cols[1].metric("Best return %", f"{_display_float(selected_row.get('best_return_pct')):.2f}")
    info_cols[2].metric("Best sharpe", f"{_display_float(selected_row.get('best_sharpe')):.2f}")
    info_cols[3].metric("Iterations", int(selected_row.get("total_iterations") or 0))
    info_cols[4].metric("Versions code", int(selected_row.get("strategy_versions") or 0))
    info_cols[5].metric(
        "Traces flux",
        "oui" if bool(selected_row.get("instrumentation_enabled")) else "non",
    )

    st.caption(str(session_dir))
    st.caption(
        "Mode: "
        f"{selected_row.get('builder_execution_mode') or 'mono_single_llm'} | "
        f"Famille: {selected_row.get('orchestration_mode') or 'single_llm'}"
    )
    if selected_row.get("objective"):
        st.markdown("**Recette / objectif source**")
        st.write(str(selected_row["objective"]))

    if str(selected_row.get("orchestration_mode") or "") == "multi_llm":
        _render_multi_llm_session_memory_panel(selected_row)

    action_cols = st.columns(5)
    with action_cols[0]:
        _handle_open_action(session_dir, button_label="Ouvrir dossier session", key=f"open-session-{selected_session_id}")
    with action_cols[1]:
        if str(selected_row.get("summary_path") or ""):
            _handle_open_action(summary_path, button_label="Ouvrir session_summary.json", key=f"open-summary-{selected_session_id}")
    with action_cols[2]:
        if str(selected_row.get("pipeline_traces_path") or ""):
            _handle_open_action(pipeline_traces_path, button_label="Ouvrir pipeline_traces.json", key=f"open-traces-{selected_session_id}")
    with action_cols[3]:
        if str(selected_row.get("latest_strategy_path") or ""):
            _handle_open_action(latest_strategy_path, button_label="Ouvrir strategy.py", key=f"open-strategy-{selected_session_id}")
    with action_cols[4]:
        _handle_open_action(results_root, button_label="Ouvrir store resultats", key=f"open-results-{selected_session_id}")

    preview_candidates = {
        "session_summary.json": summary_path,
        "pipeline_traces.json": pipeline_traces_path,
        "strategy.py": latest_strategy_path,
        "leaderboard_builder.md": session_dir / "leaderboard_builder.md",
        "leaderboard_builder.csv": session_dir / "leaderboard_builder.csv",
    }
    preview_candidates = {
        label: path
        for label, path in preview_candidates.items()
        if path and path.exists() and path.is_file()
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

    st.markdown("**Comparer deux sessions instrumentées**")
    comparison_candidates = filtered[
        filtered["session_id"] != selected_session_id
    ]["session_id"].tolist()
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
            if not bool(selected_row.get("instrumentation_enabled")) or not bool(compare_row.get("instrumentation_enabled")):
                st.warning("Les deux sessions doivent avoir l'analyse de flux activée.")
            elif str(selected_row.get("builder_execution_mode") or "") != str(compare_row.get("builder_execution_mode") or ""):
                st.warning(
                    "Comparaison refusée: les sessions n'utilisent pas le même `builder_execution_mode`."
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
                        f"trace A=`{selected_session_id}` vs trace B=`{compare_session_id}`"
                    )
                    st.code(analyzer.format_report(divergences), language="text")

    linked_runs_df = _load_builder_linked_runs_df(str(results_root), selected_session_id)
    st.markdown("**Resultats relies a cette session**")
    if linked_runs_df.empty:
        st.info("Aucun run catalogue relie a cette session Builder.")
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
        _handle_open_action(selected_path.parent, button_label="Ouvrir dossier _analysis", key=f"open-analysis-dir-{selected_analysis}")
    preview_text = _read_preview(selected_path)
    language = "html" if selected_path.suffix == ".html" else "text"
    st.code(preview_text or "Aucun apercu disponible.", language=language)


def _render_model_classification_tab() -> None:
    st.markdown("### Classement des modeles Builder")
    st.caption(
        "Stats Builder-only, calculees depuis l'historique autonome et alignees avec la page dediee des statistiques des modeles."
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
    metric_cols[0].metric("Modeles", int(len(rows_df)))
    metric_cols[1].metric("Sessions", int(overview.get("sessions", 0) or 0))
    metric_cols[2].metric("Retours positifs", int(overview.get("positive_returns", 0) or 0))
    metric_cols[3].metric("Succes", int(overview.get("success_status", 0) or 0))
    metric_cols[4].metric("Max iterations", int(overview.get("max_iterations_status", 0) or 0))

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
    st.dataframe(rows_df[display_cols], width="stretch", hide_index=True)


def render_results_store_page() -> None:
    results_root = Path(get_results_root_dir())
    artifacts_root = Path(get_artifacts_root_dir())
    builder_root = Path(get_builder_sessions_dir())
    analysis_root = Path(get_results_analysis_dir())

    inventory_df = _load_store_inventory_df(str(results_root), str(artifacts_root))
    builder_df = _load_builder_sessions_df(str(builder_root))
    analysis_files_df = _load_analysis_files_df(str(analysis_root))

    st.title("📚 Hub resultats")
    st.caption(
        "Page dediee au store centralise: catalogues, runs, sessions Builder, analyses et artefacts."
    )

    _render_store_summary(
        results_root=results_root,
        artifacts_root=artifacts_root,
        inventory_df=inventory_df,
        builder_df=builder_df,
        analysis_files_df=analysis_files_df,
    )

    tabs = st.tabs(
        [
            "Catalogue global",
            "Sessions Builder",
            "Classement modeles",
            "Artefacts",
        ]
    )

    with tabs[0]:
        render_results_hub(embedded=True)

    with tabs[1]:
        _render_builder_tab(builder_df, results_root)

    with tabs[2]:
        _render_model_classification_tab()

    with tabs[3]:
        _render_artifacts_tab(inventory_df, analysis_files_df)


__all__ = [
    "collect_analysis_files",
    "collect_builder_linked_runs",
    "collect_builder_sessions",
    "collect_store_inventory",
    "render_results_store_page",
]
