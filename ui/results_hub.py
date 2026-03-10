"""
Module-ID: ui.results_hub

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

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

try:
    import plotly.express as px
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

from backtest.storage import ResultStorage
from catalog.strategy_catalog import CATEGORY_ORDER, list_entries, upsert_from_saved_run
from ui.helpers import coerce_metric_float, compute_period_days, format_pnl_with_daily
from utils.run_tracker import RunTracker

RESULTS_DIR = Path("backtest_results")
RUNS_DIR = Path("runs")


def _safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


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


def _load_catalogs(refresh: bool = False) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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


def _path_to_uri(path: Path) -> str:
    try:
        return path.resolve().as_uri()
    except Exception:
        return str(path)


def _add_open_links_backtest(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "path" not in df.columns:
        return df
    df = df.copy()
    df["open_folder"] = df["path"].apply(
        lambda value: ""
        if value is None or (isinstance(value, float) and pd.isna(value)) or value == ""
        else _path_to_uri(RESULTS_DIR / str(value))
    )
    return df


def _add_open_links_unified(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "path" not in df.columns:
        return df
    df = df.copy()
    df["open_folder"] = df["path"].apply(
        lambda value: ""
        if value is None or (isinstance(value, float) and pd.isna(value)) or value == ""
        else _path_to_uri(RESULTS_DIR / str(value))
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


def _metric_from_snapshot(snapshot: Dict[str, Any], *keys: str) -> Any:
    if not isinstance(snapshot, dict):
        return None
    for key in keys:
        value = snapshot.get(key)
        if value is not None and value != "":
            return value
    return None


def _load_strategy_catalog_df() -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for entry in list_entries(status=None):
        metrics = entry.get("last_metrics_snapshot") or {}
        meta = entry.get("meta") or {}
        rows.append(
            {
                "entry_id": entry.get("id"),
                "strategy": entry.get("strategy_name"),
                "symbol": entry.get("symbol"),
                "timeframe": entry.get("timeframe"),
                "category": entry.get("category"),
                "status": entry.get("status"),
                "source": entry.get("source"),
                "builder_state": entry.get("builder_state"),
                "tags": ", ".join(entry.get("tags") or []),
                "source_run_id": meta.get("source_run_id"),
                "source_path": meta.get("source_path"),
                "sharpe": _metric_from_snapshot(metrics, "sharpe_ratio", "sharpe"),
                "return_pct": _metric_from_snapshot(metrics, "total_return_pct", "total_return"),
                "pnl": _metric_from_snapshot(metrics, "total_pnl", "pnl"),
                "trades": _metric_from_snapshot(metrics, "total_trades", "trades"),
            }
        )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return _coerce_numeric(df, ["sharpe", "return_pct", "pnl", "trades"])


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
    for _, row in strategy_catalog_df.iterrows():
        run_id = str(row.get("source_run_id") or "").strip()
        if not run_id:
            continue
        catalog_map[run_id] = row

    for idx, run_id in df.get("run_id", pd.Series(dtype=str)).items():
        key = str(run_id or "").strip()
        if not key or key not in catalog_map:
            continue
        catalog_row = catalog_map[key]
        df.at[idx, "catalog_entry_id"] = catalog_row.get("entry_id", "")
        df.at[idx, "catalog_category"] = catalog_row.get("category", "")
        df.at[idx, "catalog_status"] = catalog_row.get("status", "")
    return df


def _normalize_cell(value: Any) -> Any:
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


def _extract_prefixed_values(row: Dict[str, Any], prefix: str) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for key, value in row.items():
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        normalized = _normalize_cell(value)
        if normalized in (None, ""):
            continue
        values[key[len(prefix):]] = normalized
    return values


def _build_run_row_replay_request(
    source_row: Dict[str, Any],
    *,
    auto_run: bool,
) -> Tuple[Optional[Dict[str, Any]], str]:
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
    catalog_entry: Dict[str, Any],
    unified_df: pd.DataFrame,
    *,
    auto_run: bool,
) -> Tuple[Optional[Dict[str, Any]], str]:
    source_run_id = str(catalog_entry.get("source_run_id") or "").strip()
    if not source_run_id:
        return None, "Replay impossible: source_run_id absent."
    if unified_df.empty or "run_id" not in unified_df.columns:
        return None, "Replay impossible: catalogue unifié indisponible."

    source_rows = unified_df[unified_df["run_id"].astype(str) == source_run_id]
    if source_rows.empty:
        return None, f"Replay impossible: run source introuvable ({source_run_id})."

    source_row = {
        key: _normalize_cell(value)
        for key, value in source_rows.iloc[0].to_dict().items()
    }
    source_row["strategy"] = str(catalog_entry.get("strategy") or source_row.get("strategy") or "").strip()
    return _build_run_row_replay_request(source_row, auto_run=auto_run)


def _sort_by_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    sort_cols = []
    if "total_pnl" in df.columns:
        sort_cols.append("total_pnl")
    if "sharpe_ratio" in df.columns:
        sort_cols.append("sharpe_ratio")
    if sort_cols:
        df = df.sort_values(sort_cols, ascending=[False] * len(sort_cols), na_position="last")
    return df


def _pick_latest_from_catalogs(
    backtest_overview: pd.DataFrame,
    runs_overview: pd.DataFrame,
) -> Optional[Dict[str, object]]:
    candidates = []

    if not backtest_overview.empty:
        df = backtest_overview.copy()
        df["timestamp_dt"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.dropna(subset=["timestamp_dt"])
        if not df.empty:
            latest = df.sort_values("timestamp_dt", ascending=False).iloc[0]
            candidates.append({
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
            })

    if not runs_overview.empty:
        df = runs_overview.copy()
        df["timestamp_dt"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.dropna(subset=["timestamp_dt"])
        if not df.empty:
            latest = df.sort_values("timestamp_dt", ascending=False).iloc[0]
            candidates.append({
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
            })

    if not candidates:
        return None

    candidates.sort(key=lambda x: x.get("timestamp_dt") or pd.Timestamp.min, reverse=True)
    return candidates[0]


def _render_latest_run(backtest_overview: pd.DataFrame, runs_overview: pd.DataFrame) -> None:
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
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                "PnL",
                format_pnl_with_daily(metrics.get("total_pnl", 0), period_days),
            )
        with col2:
            st.metric("Return", f"{coerce_metric_float(metrics.get('total_return_pct', 0)):.1f}%")
        with col3:
            st.metric("Sharpe", f"{coerce_metric_float(metrics.get('sharpe_ratio', 0)):.2f}")
        with col4:
            st.metric("Max DD", f"{coerce_metric_float(metrics.get('max_drawdown_pct', 0)):.1f}%")

        st.caption(
            f"Run: {meta.get('run_id', 'n/a')} | "
            f"{meta.get('strategy', 'n/a')} | "
            f"{meta.get('symbol', 'n/a')}/{meta.get('timeframe', 'n/a')}"
        )
        if session_meta and isinstance(session_meta, dict):
            st.caption(f"Origine: {session_meta.get('run_id', 'n/a')}")
        return

    latest = _pick_latest_from_catalogs(backtest_overview, runs_overview)
    if latest is None:
        st.write("ℹ️ Aucun run détecté pour le moment.")
        return

    if latest["source"] == "backtest_results":
        col1, col2, col3, col4 = st.columns(4)
        metrics = latest.get("metrics", {})
        period_days = compute_period_days(
            latest.get("period_start"),
            latest.get("period_end"),
        )
        with col1:
            st.metric(
                "PnL",
                format_pnl_with_daily(metrics.get("total_pnl", 0), period_days),
            )
        with col2:
            st.metric("Return", f"{coerce_metric_float(metrics.get('total_return_pct', 0)):.1f}%")
        with col3:
            st.metric("Sharpe", f"{coerce_metric_float(metrics.get('sharpe_ratio', 0)):.2f}")
        with col4:
            st.metric("Max DD", f"{coerce_metric_float(metrics.get('max_drawdown_pct', 0)):.1f}%")
        st.caption(
            f"{latest.get('kind', '')} | {latest.get('id', '')} | "
            f"{latest.get('strategy', '')} {latest.get('symbol', '')}/{latest.get('timeframe', '')} | "
            f"{latest.get('timestamp', '')}"
        )
    else:
        st.write("ℹ️ Dernier run LLM (runs/)")
        metrics = latest.get("metrics", {})
        st.caption(
            f"Mode: {latest.get('kind', '')} | Session: {latest.get('id', '')} | "
            f"Stratégie: {latest.get('strategy', '')} | {latest.get('timestamp', '')}"
        )
        if metrics:
            st.caption(
                f"Iter: {metrics.get('total_iterations', 'n/a')} | "
                f"LLM calls: {metrics.get('total_llm_calls', 'n/a')} | "
                f"Tokens: {metrics.get('total_llm_tokens', 'n/a')} | "
                f"Derniere decision: {metrics.get('last_decision', 'n/a')}"
            )


def _render_overview_filters(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    types = sorted([t for t in df.get("type", pd.Series()).dropna().unique().tolist() if t])
    strategies = sorted([s for s in df.get("strategy", pd.Series()).dropna().unique().tolist() if s])
    symbols = sorted([s for s in df.get("symbol", pd.Series()).dropna().unique().tolist() if s])
    timeframes = sorted([t for t in df.get("timeframe", pd.Series()).dropna().unique().tolist() if t])

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        selected_types = st.multiselect("Type", options=types, default=types)
    with col2:
        selected_strategies = st.multiselect("Stratégie", options=strategies, default=strategies)
    with col3:
        selected_symbols = st.multiselect("Symbole", options=symbols, default=symbols)
    with col4:
        selected_timeframes = st.multiselect("Timeframe", options=timeframes, default=timeframes)

    if selected_types:
        df = df[df["type"].isin(selected_types)]
    if selected_strategies:
        df = df[df["strategy"].isin(selected_strategies)]
    if selected_symbols:
        df = df[df["symbol"].isin(selected_symbols)]
    if selected_timeframes:
        df = df[df["timeframe"].isin(selected_timeframes)]
    return df


def _render_charts(df: pd.DataFrame) -> None:
    if df.empty:
        return

    numeric_cols = [c for c in ["total_return_pct", "sharpe_ratio", "max_drawdown_pct"] if c in df.columns]
    if not numeric_cols:
        return

    if PLOTLY_AVAILABLE:
        if "total_return_pct" in df.columns:
            fig = px.histogram(df, x="total_return_pct", nbins=30, title="Distribution Return %")
            st.plotly_chart(fig, width="stretch")
        if {"sharpe_ratio", "max_drawdown_pct"}.issubset(df.columns):
            fig = px.scatter(
                df,
                x="max_drawdown_pct",
                y="sharpe_ratio",
                color="type" if "type" in df.columns else None,
                title="Sharpe vs Max Drawdown",
                hover_data=["id", "strategy", "symbol", "timeframe"],
            )
            st.plotly_chart(fig, width="stretch")
    else:
        st.bar_chart(df["total_return_pct"].dropna(), height=200)


def _get_numeric_column_config() -> Dict[str, Any]:
    """Configuration des colonnes numériques pour tri correct dans st.dataframe."""
    return {
        "open_folder": st.column_config.LinkColumn("Dossier", display_text="📂 Ouvrir"),
        "total_pnl": st.column_config.NumberColumn("PnL ($)", format="$%.2f"),
        "pnl_per_day": st.column_config.NumberColumn("PnL/jour ($)", format="$%.2f"),
        "pnl_per_day_covered": st.column_config.NumberColumn("PnL/jour (données)", format="$%.2f"),
        "total_return_pct": st.column_config.NumberColumn("Return (%)", format="%.2f%%"),
        "sharpe_ratio": st.column_config.NumberColumn("Sharpe", format="%.2f"),
        "max_drawdown_pct": st.column_config.NumberColumn("Max DD (%)", format="%.1f%%"),
        "win_rate_pct": st.column_config.NumberColumn("Win Rate (%)", format="%.1f%%"),
        "data_coverage_pct": st.column_config.NumberColumn("Couverture données (%)", format="%.1f%%"),
        "profit_factor": st.column_config.NumberColumn("PF", format="%.2f"),
        "total_trades": st.column_config.NumberColumn("Trades", format="%d"),
        "n_bars": st.column_config.NumberColumn("Bars", format="%d"),
        "n_trades": st.column_config.NumberColumn("Trades", format="%d"),
        "n_completed": st.column_config.NumberColumn("Complétés", format="%d"),
        "n_failed": st.column_config.NumberColumn("Échecs", format="%d"),
        "n_trials": st.column_config.NumberColumn("Trials", format="%d"),
        "n_pruned": st.column_config.NumberColumn("Prunés", format="%d"),
        "best_value": st.column_config.NumberColumn("Meilleure val.", format="%.4f"),
        "total_time_sec": st.column_config.NumberColumn("Durée (s)", format="%.1f"),
        "total_combinations": st.column_config.NumberColumn("Combinaisons", format="%d"),
        "max_combos": st.column_config.NumberColumn("Max combos", format="%d"),
        "n_workers": st.column_config.NumberColumn("Workers", format="%d"),
        "total_iterations": st.column_config.NumberColumn("Itérations", format="%d"),
        "total_llm_tokens": st.column_config.NumberColumn("Tokens LLM", format="%d"),
        "total_llm_calls": st.column_config.NumberColumn("Appels LLM", format="%d"),
        "metrics_total_pnl": st.column_config.NumberColumn("PnL ($)", format="$%.2f"),
        "metrics_total_return_pct": st.column_config.NumberColumn("Return (%)", format="%.2f%%"),
        "metrics_sharpe_ratio": st.column_config.NumberColumn("Sharpe", format="%.2f"),
        "metrics_max_drawdown_pct": st.column_config.NumberColumn("Max DD (%)", format="%.1f%%"),
        "metrics_profit_factor": st.column_config.NumberColumn("PF", format="%.2f"),
        "metrics_total_trades": st.column_config.NumberColumn("Trades", format="%d"),
        "return_pct": st.column_config.NumberColumn("Return (%)", format="%.2f%%"),
        "sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f"),
        "pnl": st.column_config.NumberColumn("PnL ($)", format="$%.2f"),
        "trades": st.column_config.NumberColumn("Trades", format="%d"),
    }


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
            "Catalogues CSV non-destructifs basés sur backtest_results/, runs/ et strategy_catalog.json."
        )

    backtest_overview, unified_overview, runs_overview = _load_catalogs(refresh=refresh)
    backtest_overview = _add_open_links_backtest(backtest_overview)
    unified_overview = _add_open_links_unified(unified_overview)
    runs_overview = _add_open_links_runs(runs_overview)
    backtest_overview = _add_pnl_per_day(backtest_overview)
    strategy_catalog_df = _load_strategy_catalog_df()
    unified_overview = _decorate_unified_with_catalog(unified_overview, strategy_catalog_df)

    _render_latest_run(backtest_overview, runs_overview)

    st.markdown("---")
    st.subheader("🗂️ Catalogue global")

    if backtest_overview.empty and unified_overview.empty and runs_overview.empty and strategy_catalog_df.empty:
        st.write("ℹ️ Aucun catalogue disponible. Lancez un run puis cliquez sur Rafraîchir catalogues.")
        return

    # Configuration des colonnes numériques pour tri correct
    numeric_col_config = _get_numeric_column_config()

    tabs = st.tabs([
        "Vue d'ensemble",
        "Backtests",
        "Sweeps",
        "Grids",
        "Optuna",
        "Runs LLM",
        "Catégories",
        "Comparaison",
        "Stock unifié",
        "Promotion / Catalogue",
    ])

    with tabs[0]:
        df = backtest_overview.copy()
        if df.empty:
            st.write("ℹ️ Aucun résultat backtest/sweep/grid.")
        else:
            df = _render_overview_filters(df)
            df = _sort_by_metrics(df)
            st.dataframe(
                df,
                width="stretch",
                hide_index=True,
                column_config=numeric_col_config,
            )
            _render_charts(df)

    with tabs[1]:
        df = backtest_overview[backtest_overview["type"] == "run"].copy() if not backtest_overview.empty else pd.DataFrame()
        if df.empty:
            st.write("ℹ️ Aucun backtest enregistré.")
        else:
            df = _sort_by_metrics(df)
            st.dataframe(
                df,
                width="stretch",
                hide_index=True,
                column_config=numeric_col_config,
            )

    with tabs[2]:
        df = backtest_overview[backtest_overview["type"] == "sweep"].copy() if not backtest_overview.empty else pd.DataFrame()
        if df.empty:
            st.write("ℹ️ Aucun sweep enregistré.")
        else:
            df = _sort_by_metrics(df)
            st.dataframe(
                df,
                width="stretch",
                hide_index=True,
                column_config=numeric_col_config,
            )

    with tabs[3]:
        df = backtest_overview[backtest_overview["type"] == "grid"].copy() if not backtest_overview.empty else pd.DataFrame()
        if df.empty:
            st.write("ℹ️ Aucun grid enregistré.")
        else:
            df = _sort_by_metrics(df)
            st.dataframe(
                df,
                width="stretch",
                hide_index=True,
                column_config=numeric_col_config,
            )

    with tabs[4]:
        df = backtest_overview[backtest_overview["type"] == "optuna"].copy() if not backtest_overview.empty else pd.DataFrame()
        if df.empty:
            st.write("ℹ️ Aucun Optuna enregistré.")
        else:
            df = _sort_by_metrics(df)
            st.dataframe(
                df,
                width="stretch",
                hide_index=True,
                column_config=numeric_col_config,
            )

    with tabs[5]:
        if runs_overview.empty:
            st.write("ℹ️ Aucun run LLM enregistré.")
        else:
            df = runs_overview.copy()
            df["timestamp_dt"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
            df = df.sort_values("timestamp_dt", ascending=False, na_position="last").drop(columns=["timestamp_dt"])
            st.dataframe(
                df,
                width="stretch",
                hide_index=True,
                column_config=numeric_col_config,
            )

    with tabs[6]:
        if backtest_overview.empty:
            st.write("ℹ️ Aucune donnée pour les catégories.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("**Par stratégie**")
                st.dataframe(
                    backtest_overview["strategy"].value_counts().rename_axis("strategy").reset_index(name="count"),
                    width="stretch",
                    hide_index=True,
                )
            with col2:
                st.markdown("**Par symbole**")
                st.dataframe(
                    backtest_overview["symbol"].value_counts().rename_axis("symbol").reset_index(name="count"),
                    width="stretch",
                    hide_index=True,
                )
            st.markdown("**Par timeframe**")
            st.dataframe(
                backtest_overview["timeframe"].value_counts().rename_axis("timeframe").reset_index(name="count"),
                width="stretch",
                hide_index=True,
            )

    with tabs[7]:
        df = backtest_overview[backtest_overview["type"] == "run"].copy() if not backtest_overview.empty else pd.DataFrame()
        if df.empty:
            st.write("ℹ️ Aucun backtest disponible pour comparaison.")
        else:
            df = _sort_by_metrics(df)
            options = df["id"].dropna().unique().tolist()
            selected = st.multiselect("Sélectionner des runs", options=options)
            if selected:
                selected_df = df[df["id"].isin(selected)]
                st.dataframe(
                    selected_df,
                    width="stretch",
                    hide_index=True,
                    column_config=numeric_col_config,
                )

    with tabs[8]:
        if unified_overview.empty:
            st.write("ℹ️ Aucun artefact unifié disponible.")
        else:
            df = unified_overview.copy()
            type_options = sorted([t for t in df.get("artifact_type", pd.Series()).dropna().unique().tolist() if t])
            status_options = sorted([t for t in df.get("status", pd.Series()).dropna().unique().tolist() if t])
            cat_options = sorted([t for t in df.get("catalog_category", pd.Series()).dropna().unique().tolist() if t])

            col1, col2, col3 = st.columns(3)
            with col1:
                selected_types = st.multiselect("Type artefact", options=type_options, default=type_options)
            with col2:
                selected_status = st.multiselect("Statut source", options=status_options, default=status_options)
            with col3:
                selected_catalog_state = st.multiselect(
                    "État catalogue",
                    options=cat_options,
                    default=cat_options,
                )

            if selected_types:
                df = df[df["artifact_type"].isin(selected_types)]
            if selected_status:
                df = df[df["status"].isin(selected_status)]
            if selected_catalog_state:
                df = df[df["catalog_category"].isin(selected_catalog_state)]

            sort_cols = [c for c in ["timestamp", "metrics_total_pnl", "metrics_sharpe_ratio"] if c in df.columns]
            if sort_cols:
                ascending = [False] * len(sort_cols)
                df = df.sort_values(sort_cols, ascending=ascending, na_position="last")

            st.dataframe(
                df,
                width="stretch",
                hide_index=True,
                column_config=numeric_col_config,
            )

    with tabs[9]:
        st.caption(
            "Promouvoir = enregistrer la stratégie comme candidate de rejouage/revue "
            "dans le strategy catalog existant, sans dupliquer le stockage de base."
        )

        if unified_overview.empty:
            st.write("ℹ️ Aucun run sauvegardé à promouvoir.")
        else:
            candidates = unified_overview.copy()
            incomplete_statuses = {"partial", "failed", "error", "stopped", "interrupted"}
            if "status" in candidates.columns:
                candidates = candidates[
                    ~candidates["status"].astype(str).str.lower().isin(incomplete_statuses)
                ]
            candidates = candidates[candidates["strategy"].notna()]
            candidates = candidates[candidates["symbol"].notna()]
            candidates = candidates[candidates["timeframe"].notna()]

            if candidates.empty:
                st.write("ℹ️ Aucun candidat propre à promouvoir.")
            else:
                display_cols = [
                    "run_id",
                    "artifact_type",
                    "strategy",
                    "symbol",
                    "timeframe",
                    "mode",
                    "status",
                    "catalog_category",
                    "metrics_total_return_pct",
                    "metrics_sharpe_ratio",
                    "metrics_total_trades",
                ]
                promo_df = candidates[display_cols].copy()
                promo_df.insert(0, "select", False)
                edited = st.data_editor(
                    promo_df,
                    width="stretch",
                    hide_index=True,
                    column_config=numeric_col_config,
                    disabled=[c for c in promo_df.columns if c != "select"],
                )

                selected_run_ids = edited.loc[edited["select"] == True, "run_id"].tolist()  # noqa: E712
                selected_candidate_row = None
                if len(selected_run_ids) == 1:
                    selected_candidate_row = next(
                        (
                            row
                            for row in candidates.to_dict(orient="records")
                            if str(row.get("run_id") or "") == str(selected_run_ids[0])
                        ),
                        None,
                    )
                target_category = st.selectbox(
                    "Cible catalogue",
                    CATEGORY_ORDER,
                    index=CATEGORY_ORDER.index("p3_watchlist"),
                    help="`p3_watchlist` est la file naturelle de rejouage/revue. Les paliers supérieurs restent une décision manuelle.",
                )
                promo_col_a, promo_col_b = st.columns(2)
                if promo_col_a.button(
                    "Promouvoir la sélection",
                    disabled=not selected_run_ids,
                    use_container_width=True,
                ):
                    source_rows = {
                        str(row.get("run_id") or ""): row
                        for row in candidates.to_dict(orient="records")
                    }
                    promoted = 0
                    failures: List[str] = []
                    for run_id in selected_run_ids:
                        row = source_rows.get(str(run_id))
                        if not row:
                            failures.append(f"{run_id}: source introuvable")
                            continue
                        try:
                            upsert_from_saved_run(row, target_category=target_category)
                            promoted += 1
                        except Exception as exc:
                            failures.append(f"{run_id}: {exc}")
                    if promoted:
                        st.success(f"✅ {promoted} stratégie(s) synchronisée(s) vers le catalogue.")
                    if failures:
                        st.warning(" | ".join(failures[:5]))
                    st.rerun()
                if promo_col_b.button(
                    "Promouvoir + rejouer",
                    type="primary",
                    disabled=selected_candidate_row is None,
                    use_container_width=True,
                ):
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

        st.markdown("### Strategy catalog")
        if strategy_catalog_df.empty:
            st.write("ℹ️ Le strategy catalog est vide.")
        else:
            strategy_catalog_df = strategy_catalog_df.sort_values(
                ["category", "strategy", "symbol", "timeframe"],
                ascending=[True, True, True, True],
                na_position="last",
            )
            catalog_select_df = strategy_catalog_df.copy()
            catalog_select_df.insert(0, "select", False)
            catalog_select_df["replayable"] = catalog_select_df["source_run_id"].fillna("").astype(str) != ""
            edited_catalog = st.data_editor(
                catalog_select_df,
                width="stretch",
                hide_index=True,
                column_config=numeric_col_config,
                disabled=[c for c in catalog_select_df.columns if c != "select"],
            )

            selected_catalog_ids = edited_catalog.loc[
                edited_catalog["select"] == True,  # noqa: E712
                "entry_id",
            ].tolist()
            selected_catalog_entry = None
            if len(selected_catalog_ids) == 1:
                selected_catalog_entry = next(
                    (
                        row
                        for row in strategy_catalog_df.to_dict(orient="records")
                        if row.get("entry_id") == selected_catalog_ids[0]
                    ),
                    None,
                )

            action_col_a, action_col_b = st.columns(2)
            with action_col_a:
                if st.button(
                    "Précharger replay",
                    disabled=selected_catalog_entry is None,
                    use_container_width=True,
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
            with action_col_b:
                if st.button(
                    "Rejouer maintenant",
                    type="primary",
                    disabled=selected_catalog_entry is None,
                    use_container_width=True,
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
