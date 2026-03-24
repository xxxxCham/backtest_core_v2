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
                "best_score": _coerce_float(summary.get("best_score")),
                "best_return_pct": _compute_builder_best_return(summary),
                "total_iterations": int(summary.get("total_iterations") or len(summary.get("iterations") or [])),
                "auto_reset_count": int(summary.get("auto_reset_count") or 0),
                "objective": str(summary.get("objective") or ""),
                "objective_excerpt": _shorten(str(summary.get("objective") or "")),
                "session_dir": str(session_dir),
                "summary_path": str(summary_path) if summary_path.exists() else "",
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
                "best_score",
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
    latest_strategy_path = Path(str(selected_row.get("latest_strategy_path") or ""))

    info_cols = st.columns(5)
    info_cols[0].metric("Statut", str(selected_row.get("status") or "?"))
    info_cols[1].metric("Best return %", f"{_display_float(selected_row.get('best_return_pct')):.2f}")
    info_cols[2].metric("Best sharpe", f"{_display_float(selected_row.get('best_sharpe')):.2f}")
    info_cols[3].metric("Iterations", int(selected_row.get("total_iterations") or 0))
    info_cols[4].metric("Versions code", int(selected_row.get("strategy_versions") or 0))

    st.caption(str(session_dir))
    if selected_row.get("objective"):
        st.markdown("**Recette / objectif source**")
        st.write(str(selected_row["objective"]))

    action_cols = st.columns(4)
    with action_cols[0]:
        _handle_open_action(session_dir, button_label="Ouvrir dossier session", key=f"open-session-{selected_session_id}")
    with action_cols[1]:
        if str(selected_row.get("summary_path") or ""):
            _handle_open_action(summary_path, button_label="Ouvrir session_summary.json", key=f"open-summary-{selected_session_id}")
    with action_cols[2]:
        if str(selected_row.get("latest_strategy_path") or ""):
            _handle_open_action(latest_strategy_path, button_label="Ouvrir strategy.py", key=f"open-strategy-{selected_session_id}")
    with action_cols[3]:
        _handle_open_action(results_root, button_label="Ouvrir store resultats", key=f"open-results-{selected_session_id}")

    preview_candidates = {
        "session_summary.json": summary_path,
        "strategy.py": latest_strategy_path,
        "leaderboard_builder.md": session_dir / "leaderboard_builder.md",
        "leaderboard_builder.csv": session_dir / "leaderboard_builder.csv",
    }
    preview_candidates = {label: path for label, path in preview_candidates.items() if path and path.exists()}
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
