"""
UI Streamlit principale pour le moteur de backtest.

PROTECTION WINDOWS SPAWN:
Ce module crée des ProcessPoolExecutor pour les sweeps grille.
Sous Windows, multiprocessing utilise 'spawn' qui ré-exécute le module.
Les workers IMPORTENT ce fichier mais NE DOIVENT PAS exécuter Streamlit.
Protection: Tout code Streamlit est dans main() appelé uniquement par __main__.
"""
# ruff: noqa: I001,BLE001,SLF001
from __future__ import annotations

# pylint: disable=import-outside-toplevel,too-many-lines,broad-except,protected-access,function-redefined,assignment-from-none

# ============================================================================
# DÉSACTIVATION GPU POUR SWEEPS STREAMLIT
# ============================================================================
# DOIT être au tout début AVANT tout import pour éviter chargement VRAM inutile
# GPU queue ne fonctionne pas en multiprocess → CPU + cache RAM plus efficace
import os

os.environ["BACKTEST_USE_GPU"] = "0"
os.environ["BACKTEST_GPU_QUEUE_ENABLED"] = "0"
# ============================================================================

import gc
import logging
import math
import time
import traceback
from collections import deque
from itertools import chain, islice, product
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import streamlit as st

from backtest.worker import run_backtest_worker as _isolated_worker
from ui.cache_manager import clear_data_cache
from ui.components.charts import (
    render_comparison_chart,
    render_multi_sweep_heatmap,
    render_multi_sweep_ranking,
    render_ohlcv_with_trades_and_indicators,
    render_strategy_param_diagram,
)
from ui.components.sweep_monitor import (
    SweepMonitor,
    render_sweep_progress,
    render_sweep_summary,
)
from ui.constants import PARAM_CONSTRAINTS
from ui.context import (
    BacktestEngine,
    LiveOrchestrationViewer,
    LLM_AVAILABLE,
    LLM_IMPORT_ERROR,
    OrchestrationLogger,
    compute_search_space_stats,
    create_llm_client,
    create_optimizer_from_engine,
    create_orchestrator_with_backtest,
    generate_session_id,
    get_strategy_param_bounds,
    get_strategy_param_space,
    render_deep_trace_viewer,
    render_full_orchestration_viewer,
)
from ui.helpers import (
    _maybe_auto_save_run,
    ProgressMonitor,
    apply_auto_market_stabilization_filter,
    build_strategy_params_for_comparison,
    build_indicator_overlays,
    load_selected_data,
    render_progress_monitor,
    safe_copy_cleanup,
    safe_run_backtest,
    safe_load_data,
    safe_run_walk_forward,
    show_status,
    summarize_comparison_results,
    validate_all_params,
)
from ui.sidebar import apply_pending_sidebar_config, get_run_label_for_mode
from ui.state import (
    SidebarState,
    BUILDER_OPTIMIZATION_MODE,
    arm_ui_load_request,
    arm_ui_run_request,
    clear_builder_launch_state as _clear_builder_launch_state,
    clear_builder_runtime_state as _clear_builder_runtime_state,
    clear_execution_state,
    consume_ui_run_request,
    ensure_ui_execution_state_defaults,
    get_ui_execution_phase,
    mark_ui_run_started,
    persist_run_winner,
    should_preserve_builder_launch,
    UI_EXECUTION_PHASE_LAUNCH_PENDING,
    UI_EXECUTION_PHASE_RUNNING,
)
from utils.run_tracker import RunSignature, get_global_tracker


MAIN_ACTION_BAR_CSS = """
<style>
div[data-testid="stVerticalBlock"]:has(.bc-main-actions-anchor) {
    border: 1px solid rgba(59, 130, 246, 0.24);
    border-radius: 20px;
    padding: 1.05rem 1.05rem 0.45rem 1.05rem;
    background:
        radial-gradient(circle at top left, rgba(59, 130, 246, 0.16), transparent 42%),
        linear-gradient(180deg, rgba(9, 17, 31, 0.98), rgba(14, 26, 45, 0.97));
    margin: 0.75rem 0 1.2rem 0;
    box-shadow: 0 18px 36px rgba(2, 8, 23, 0.22);
}
div[data-testid="stVerticalBlock"]:has(.bc-main-actions-anchor) [data-testid="stButton"] > button {
    min-height: 3.35rem;
    border-radius: 14px;
    font-weight: 700;
    letter-spacing: 0.01em;
}
div[data-testid="stVerticalBlock"]:has(.bc-main-actions-anchor) [data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 55%, #3b82f6 100%);
    border: 1px solid #3b82f6;
    color: #ffffff !important;
    box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.25), 0 10px 24px rgba(30, 64, 175, 0.35);
}
div[data-testid="stVerticalBlock"]:has(.bc-main-actions-anchor) [data-testid="stButton"] > button[kind="secondary"] {
    background: linear-gradient(180deg, rgba(16, 31, 57, 0.96), rgba(22, 43, 79, 0.94));
    border: 1px solid rgba(96, 165, 250, 0.32);
    color: #dce9fb !important;
}
div[data-testid="stVerticalBlock"]:has(.bc-main-actions-anchor) h3 {
    margin-bottom: 0.35rem;
}
</style>
"""


# Fonction _run_backtest_multiprocess SUPPRIMÉE (obsolète)
# Utilisez run_backtest_worker de backtest.worker à la place
# Voir commit pour restauration si nécessaire

def _apply_thread_limit(thread_limit: int, label: str = "") -> None:
    if thread_limit <= 0:
        return

    os.environ["BACKTEST_WORKER_THREADS"] = str(thread_limit)
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "BLIS_NUM_THREADS",
    ):
        os.environ[var] = str(thread_limit)

    try:
        from threadpoolctl import threadpool_limits

        threadpool_limits(thread_limit)
    except Exception:
        pass

    try:
        _torch = __import__("torch")  # type: ignore[misc]
        _torch.set_num_threads(thread_limit)
        _torch.set_num_interop_threads(max(1, thread_limit // 2))
    except Exception:
        pass

    if label:
        logger = logging.getLogger(__name__)
        logger.info("Thread limit %s appliqué: %s", label, thread_limit)


def _init_sweep_worker(thread_limit: int) -> None:
    """Initializer ProcessPoolExecutor - applique limites threads AVANT tout calcul."""
    _apply_thread_limit(thread_limit, label="worker")

    # Forcer avec threadpoolctl (plus efficace que les env vars seules)
    try:
        import threadpoolctl
        info_before = threadpoolctl.threadpool_info()
        threadpoolctl.threadpool_limits(limits=max(1, thread_limit), user_api="blas")
        info_after = threadpoolctl.threadpool_info()

        # Log pour debug
        _logger_worker = logging.getLogger(__name__)
        num_threads_before = sum(pool.get("num_threads", 0) for pool in info_before)
        num_threads_after = sum(pool.get("num_threads", 0) for pool in info_after)
        _logger_worker.debug("Worker threads BLAS: %s → %s", num_threads_before, num_threads_after)
    except ImportError:
        pass  # threadpoolctl non installé - les env vars suffiront


def _timeframe_to_minutes(timeframe: str) -> int:
    """Convertit un timeframe en minutes pour tri/estimation."""
    if not timeframe or len(timeframe) < 2:
        return 0
    unit = timeframe[-1]
    try:
        amount = int(timeframe[:-1])
    except ValueError:
        return 0
    multipliers = {"m": 1, "h": 60, "d": 1440, "w": 10080, "M": 43200}
    return amount * multipliers.get(unit, 60)


def _build_multi_sweep_plan(symbols: List[str], timeframes: List[str]) -> List[tuple[str, str]]:
    """Construit un plan multi-sweep avec un ordre stable et léger."""
    combos = [(symbol, tf) for symbol in symbols for tf in timeframes]
    combos.sort(key=lambda item: (_timeframe_to_minutes(item[1]), item[0]), reverse=True)
    return combos


def _estimate_grid_size(param_ranges: Dict[str, Any]) -> int:
    """Estime le nombre de combinaisons de la grille sans la matérialiser."""
    if not param_ranges:
        return 1
    total = 1
    for r in param_ranges.values():
        try:
            if isinstance(r, dict):
                if "count" in r:
                    total *= max(1, int(r["count"]))
                    continue
                values = r.get("values")
                if isinstance(values, (list, tuple)):
                    total *= max(1, len(values))
                    continue
            pmin, pmax, step = r["min"], r["max"], r["step"]
            if isinstance(pmin, int) and isinstance(step, int):
                count = max(1, ((int(pmax) - int(pmin)) // max(1, int(step))) + 1)
            else:
                if float(step) <= 0:
                    count = 1
                else:
                    span = float(pmax) - float(pmin)
                    count = int(math.floor(span / float(step))) + 1
            total *= max(1, int(count))
        except Exception:
            total *= 1
            logger.debug("param range parsing error in _compute_grid_total", exc_info=True)
    return max(1, int(total))


def _compute_max_safe_combos(total_sweeps: int, max_combos: int) -> int:
    """Limite adaptative pour multi-sweep (mémoire)."""
    if total_sweeps <= 0:
        return max_combos
    adaptive = max(50_000, 500_000 // max(1, total_sweeps))
    if max_combos and max_combos > 0:
        return min(max_combos, adaptive)
    return adaptive


def _build_param_combo_iter(
    params: Dict[str, Any],
    param_ranges: Dict[str, Any],
    max_runs: Optional[int],
) -> tuple[Any, int, int]:
    """Construit un itérateur lazy de combinaisons + stats."""
    param_names = list(param_ranges.keys())
    param_values_lists = []

    if param_names:
        for pname in param_names:
            r = param_ranges[pname]
            pmin = r.get("min") if isinstance(r, dict) else None
            values = r.get("values") if isinstance(r, dict) else None
            if values is None:
                pmin, pmax, step = r["min"], r["max"], r["step"]

                if isinstance(pmin, int) and isinstance(step, int):
                    values = list(range(int(pmin), int(pmax) + 1, max(1, int(step))))
                else:
                    values = list(
                        np.arange(float(pmin), float(pmax) + float(step) / 2, float(step))
                    )
                    values = [round(v, 2) for v in values if v <= pmax]

            if not values:
                values = [pmin]

            param_values_lists.append(values)

        total_combinations = max(
            1, math.prod(len(values) for values in param_values_lists)
        )
        combo_iter = (
            {**params, **dict(zip(param_names, combo))}
            for combo in product(*param_values_lists)
        )
    else:
        total_combinations = 1
        combo_iter = iter([params.copy()])  # type: ignore[assignment]

    if max_runs and max_runs > 0 and total_combinations > max_runs:
        combo_iter = islice(combo_iter, max_runs)  # type: ignore[assignment]
        total_runs = max_runs
    else:
        total_runs = total_combinations

    return combo_iter, total_runs, total_combinations


def _run_grid_numba_summary(
    *,
    df: pd.DataFrame,
    engine: "BacktestEngine",  # type: ignore[valid-type]
    strategy_key: str,
    symbol: str,
    timeframe: str,
    params: Dict[str, Any],
    param_ranges: Dict[str, Any],
    max_runs: Optional[int],
    debug_enabled: bool,
    progress_placeholder: Any,
) -> Optional[Dict[str, Any]]:
    """Extension hook: optional fast-path for Numba sweeps.

    By default this workspace keeps the historical sequential path unless a
    caller explicitly monkeypatches or replaces this helper.
    """

    _ = (
        df,
        engine,
        strategy_key,
        symbol,
        timeframe,
        params,
        param_ranges,
        max_runs,
        debug_enabled,
        progress_placeholder,
    )
    return None


def _run_grid_sequential(
    df: pd.DataFrame,
    engine: "BacktestEngine",  # type: ignore[valid-type]
    strategy_key: str,
    symbol: str,
    timeframe: str,
    params: Dict[str, Any],
    param_ranges: Dict[str, Any],
    max_runs: Optional[int],
    debug_enabled: bool,
    progress_placeholder: Any,
) -> Dict[str, Any]:
    """Exécute une grille séquentielle et retourne le meilleur résultat."""
    if st.session_state.get("stop_requested", False):
        return {
            "best_params": {},
            "best_metrics": {},
            "completed": 0,
            "failed": 0,
            "stopped": True,
            "total_runs": 0,
            "total_combinations": 0,
        }

    numba_summary = _run_grid_numba_summary(  # type: ignore[assignment]
        df=df,
        engine=engine,
        strategy_key=strategy_key,
        symbol=symbol,
        timeframe=timeframe,
        params=params,
        param_ranges=param_ranges,
        max_runs=max_runs,
        debug_enabled=debug_enabled,
        progress_placeholder=progress_placeholder,
    )
    if isinstance(numba_summary, dict):
        numba_summary.setdefault("stopped", False)
        return numba_summary

    combo_iter, total_runs, total_combinations = _build_param_combo_iter(
        params=params,
        param_ranges=param_ranges,
        max_runs=max_runs,
    )

    best_params: Dict[str, Any] = {}
    best_metrics: Dict[str, Any] = {}
    best_score = (float("-inf"), float("-inf"))
    completed = 0
    failed = 0
    stopped = False
    last_render = time.perf_counter()

    fast_metrics = False
    try:
        fast_threshold = int(os.getenv("BACKTEST_SWEEP_FAST_METRICS_THRESHOLD", "500"))
        fast_metrics = total_runs >= fast_threshold
    except (TypeError, ValueError):
        fast_metrics = False

    for param_combo in combo_iter:
        if st.session_state.get("stop_requested", False):
            stopped = True
            break

        completed += 1
        result, msg = safe_run_backtest(
            engine,
            df,
            strategy_key,
            param_combo,
            symbol,
            timeframe,
            silent_mode=not debug_enabled,
            fast_metrics=fast_metrics,
        )

        if result is None:
            failed += 1
        else:
            metrics = result.metrics or {}
            sharpe = metrics.get("sharpe_ratio", float("-inf"))
            pnl = metrics.get("total_pnl", float("-inf"))
            score = (sharpe, pnl)
            if score > best_score:
                best_score = score
                best_params = param_combo
                best_metrics = metrics

        now = time.perf_counter()
        if completed == 1 or completed % 200 == 0 or now - last_render >= 5.0:
            progress_placeholder.caption(
                f"Grille en cours: {completed}/{total_runs} (max {total_combinations:,})"
            )
            last_render = now

    return {
        "best_params": best_params,
        "best_metrics": best_metrics,
        "completed": completed,
        "failed": failed,
        "stopped": stopped,
        "total_runs": total_runs,
        "total_combinations": total_combinations,
    }


def _build_multi_sweep_grid_entry(
    *,
    strategy_key: str,
    symbol: str,
    timeframe: str,
    sweep_summary: Dict[str, Any],
) -> Dict[str, Any]:
    """Normalize one multi-sweep result row for downstream rendering/tests."""

    stopped = bool(sweep_summary.get("stopped", False))
    status = "stopped" if stopped else "completed"
    return {
        "strategy_key": strategy_key,
        "symbol": symbol,
        "timeframe": timeframe,
        "status": status,
        "params": dict(sweep_summary.get("best_params", {}) or {}),
        "metrics": dict(sweep_summary.get("best_metrics", {}) or {}),
        "completed": int(sweep_summary.get("completed", 0) or 0),
        "failed": int(sweep_summary.get("failed", 0) or 0),
        "total_runs": int(sweep_summary.get("total_runs", 0) or 0),
        "error": "Interrompu par l'utilisateur" if stopped else "",
    }


def _describe_grid_completion(
    *,
    grid_interrupted: bool,
    results_count: int,
) -> tuple[str, str]:
    """Return UI status level + message for grid completion summaries."""

    if grid_interrupted and results_count <= 0:
        return "warning", "Optimisation interrompue avant tout résultat."
    if grid_interrupted:
        return "warning", f"Optimisation interrompue: {results_count} tests effectués"
    return "success", f"Optimisation: {results_count} tests"


def _run_grid_parallel_basic(
    df: pd.DataFrame,
    strategy_key: str,
    symbol: str,
    timeframe: str,
    params: Dict[str, Any],
    param_ranges: Dict[str, Any],
    max_runs: Optional[int],
    initial_capital: float,
    n_workers: int,
    worker_thread_limit: int,
    debug_enabled: bool,
    progress_placeholder: Any,
    stats_placeholder: Any,
) -> Dict[str, Any]:
    """Exécute une grille en parallèle (pool par sweep) avec progress live."""
    from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

    from backtest.worker import init_worker_with_dataframe

    combo_iter, total_runs, total_combinations = _build_param_combo_iter(
        params=params,
        param_ranges=param_ranges,
        max_runs=max_runs,
    )

    try:
        fast_threshold = int(os.getenv("BACKTEST_SWEEP_FAST_METRICS_THRESHOLD", "500"))
    except (TypeError, ValueError):
        fast_threshold = 500
    fast_metrics = total_runs >= fast_threshold

    monitor = ProgressMonitor(total_runs=total_runs)
    best_params: Dict[str, Any] = {}
    best_metrics: Dict[str, Any] = {}
    best_score = (float("-inf"), float("-inf"))

    completed = 0
    failed = 0
    last_render = time.perf_counter()

    max_inflight = max(1, min(total_runs, n_workers * 2))
    pending: Dict[Any, Dict[str, Any]] = {}

    def submit_next(executor: ProcessPoolExecutor) -> bool:
        try:
            param_combo = next(combo_iter)
        except StopIteration:
            return False
        future = executor.submit(_isolated_worker, param_combo)
        pending[future] = param_combo
        return True

    with ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=init_worker_with_dataframe,
        initargs=(
            df,
            strategy_key,
            symbol,
            timeframe,
            initial_capital,
            debug_enabled,
            worker_thread_limit,
            fast_metrics,
            False,  # ✅ CRITIQUE: is_path (DataFrame fourni directement, pas un chemin)
        ),
    ) as executor:
        for _ in range(max_inflight):
            if not submit_next(executor):
                break

        while pending:
            if st.session_state.get("stop_requested", False):
                break

            # ✅ FIX #12: Réduire timeout de 0.25s à 0.05s
            done, _ = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
            if not done:
                continue

            for future in done:
                param_combo = pending.pop(future)
                result = None
                try:
                    result = future.result(timeout=300)
                except Exception as exc:
                    result = {"params_dict": param_combo, "error": f"{type(exc).__name__}: {exc}"}

                completed += 1
                monitor.runs_completed = completed

                if result and "error" not in result:
                    metrics = {
                        "total_pnl": result.get("total_pnl", 0.0),
                        "sharpe_ratio": result.get("sharpe", 0.0),
                        "max_drawdown": result.get("max_dd", 0.0),
                        "win_rate": result.get("win_rate", 0.0),
                        "profit_factor": result.get("profit_factor", 0.0),
                    }
                    score = (metrics.get("sharpe_ratio", float("-inf")),
                             metrics.get("total_pnl", float("-inf")))
                    if score > best_score:
                        best_score = score
                        best_params = param_combo
                        best_metrics = metrics
                else:
                    failed += 1

                submit_next(executor)

                now = time.perf_counter()
                if completed == 1 or completed % 200 == 0 or now - last_render >= 2.0:
                    render_progress_monitor(monitor, progress_placeholder)
                    if best_metrics:
                        stats_placeholder.caption(
                            f"⚡ {completed}/{total_runs} | "
                            f"Sharpe {best_metrics.get('sharpe_ratio', 0):.2f} | "
                            f"PnL ${best_metrics.get('total_pnl', 0):,.2f}"
                        )
                    last_render = now

    return {
        "best_params": best_params,
        "best_metrics": best_metrics,
        "completed": completed,
        "failed": failed,
        "total_runs": total_runs,
        "total_combinations": total_combinations,
    }


def _inject_main_action_bar_styles() -> None:
    st.markdown(MAIN_ACTION_BAR_CSS, unsafe_allow_html=True)


def _extract_topology_hosts(topology: Any) -> List[str]:
    if topology is None:
        return []

    endpoints = getattr(topology, "endpoints", None)
    if endpoints is None and isinstance(topology, dict):
        endpoints = topology.get("endpoints")
    if not isinstance(endpoints, dict):
        return []

    hosts: List[str] = []
    for endpoint in endpoints.values():
        if isinstance(endpoint, dict):
            host = str(endpoint.get("ollama_host", "") or "").strip()
        else:
            host = str(getattr(endpoint, "ollama_host", "") or "").strip()
        if host:
            hosts.append(host.rstrip("/"))
    return hosts


def _collect_runtime_cleanup_hosts(state: SidebarState) -> List[str]:
    candidates = [
        str(getattr(state, "builder_ollama_host", "") or "").strip(),
        str(st.session_state.get("exec_llm_ollama_host", "") or "").strip(),
    ]
    llm_config = getattr(state, "llm_config", None)
    if llm_config is not None:
        candidates.append(str(getattr(llm_config, "ollama_host", "") or "").strip())
    candidates.extend(
        _extract_topology_hosts(getattr(state, "llm_topology_config", None))
    )

    ordered: List[str] = []
    seen: set[str] = set()
    for host in candidates:
        normalized = host.rstrip("/")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _reset_builder_runtime_state() -> None:
    _clear_builder_runtime_state(st.session_state)


def _reset_builder_launch_state() -> None:
    _clear_builder_launch_state(st.session_state)


def _execute_clean_stop(state: SidebarState) -> None:
    from ui.builder_view import mark_builder_autonomous_runtime_stopped
    from ui.emergency_stop import execute_emergency_stop

    logger = logging.getLogger(__name__)
    cleanup_stats = execute_emergency_stop(
        st.session_state,
        ollama_hosts=_collect_runtime_cleanup_hosts(state),
        cache_callbacks=(
            st.cache_data.clear,
            st.cache_resource.clear,
            lambda: safe_copy_cleanup(logger),
        ),
    )

    if (
        state.optimization_mode == BUILDER_OPTIMIZATION_MODE
        or bool(st.session_state.get("builder_autonomous", False))
    ):
        try:
            mark_builder_autonomous_runtime_stopped(
                reason="manual_stop",
                manual_stop=True,
            )
        except Exception as exc:  # noqa: BLE001
            cleanup_stats.setdefault("errors", []).append(
                f"builder_runtime_stop: {exc}"
            )

    _reset_builder_runtime_state()
    clear_execution_state(st.session_state, clear_builder_launch=True)

    cleaned_components = len(cleanup_stats.get("components_cleaned", []))
    error_count = len(cleanup_stats.get("errors", []))
    unloaded_by_host = [
        f"{host}: {count}"
        for host, count in dict(cleanup_stats.get("ollama_unloaded", {}) or {}).items()
    ]
    hard_stopped_hosts = [
        f"{host}: {count}"
        for host, count in dict(cleanup_stats.get("ollama_stopped", {}) or {}).items()
    ]
    remaining_hosts = [
        f"{host}: {', '.join(models[:3])}"
        for host, models in dict(cleanup_stats.get("ollama_remaining", {}) or {}).items()
    ]
    host_summary = (
        " | ".join(unloaded_by_host)
        if unloaded_by_host
        else "aucun endpoint Ollama actif détecté"
    )
    hard_stop_summary = (
        " | ".join(hard_stopped_hosts)
        if hard_stopped_hosts
        else "aucun daemon Ollama local à couper"
    )
    st.session_state["main_action_feedback"] = {
        "tone": "success" if error_count == 0 else "warning",
        "message": (
            "Exécution arrêtée proprement. Runtime, caches et contexte Builder/LLM "
            "réinitialisés avec coupure locale d'Ollama si nécessaire."
        ),
        "details": (
            f"Nettoyage: {cleaned_components} composant(s) | "
            f"erreurs: {error_count} | "
            f"déchargement Ollama: {host_summary} | "
            f"arrêt dur: {hard_stop_summary}"
            + (
                f" | modèles restants: {' | '.join(remaining_hosts)}"
                if remaining_hosts
                else ""
            )
        ),
    }


def _process_load_request(state: SidebarState) -> None:
    is_builder_autonomous = (
        state.optimization_mode == BUILDER_OPTIMIZATION_MODE
        and bool(state.builder_autonomous)
    )
    if is_builder_autonomous and (not state.symbol or not state.timeframe):
        st.session_state["ohlcv_df"] = None
        st.session_state["ohlcv_status_msg"] = (
            "Mode autonome actif: aucune présélection requise."
        )
        st.info(
            "Mode autonome actif: aucun token/timeframe n'est requis. "
            "Le Builder choisira un marché valide au lancement."
        )
        return

    df_loaded, msg = load_selected_data(
        state.symbol,
        state.timeframe,
        state.start_date,
        state.end_date,
    )
    if df_loaded is None:
        if is_builder_autonomous:
            st.session_state["ohlcv_df"] = None
            st.session_state["ohlcv_status_msg"] = f"Présélection ignorée: {msg}"
            st.warning(
                f"Présélection {state.symbol or '—'} {state.timeframe or '—'} rejetée: {msg}. "
                "Le Builder autonome choisira un autre marché valide au lancement."
            )
        else:
            st.error(f"Erreur chargement: {msg}")
        return

    st.success(f"Données chargées: {msg}")


def _queue_main_load_action() -> None:
    if bool(st.session_state.get("config_pending_changes", False)):
        apply_pending_sidebar_config()
    arm_ui_load_request(st.session_state)


def _queue_main_run_action(fallback_optimization_mode: str = "") -> None:
    if bool(st.session_state.get("config_pending_changes", False)):
        apply_pending_sidebar_config()

    optimization_mode = str(
        st.session_state.get("optimization_mode", fallback_optimization_mode) or ""
    )
    arm_ui_run_request(
        st.session_state,
        builder_mode=optimization_mode == BUILDER_OPTIMIZATION_MODE,
    )


def render_primary_action_bar(state: SidebarState) -> None:
    _inject_main_action_bar_styles()

    feedback = st.session_state.pop("main_action_feedback", None)
    if isinstance(feedback, dict):
        tone = str(feedback.get("tone", "info") or "info").strip().lower()
        message = str(feedback.get("message", "") or "").strip()
        details = str(feedback.get("details", "") or "").strip()
        if tone == "success":
            st.success(message)
        elif tone == "warning":
            st.warning(message)
        elif tone == "error":
            st.error(message)
        elif message:
            st.info(message)
        if details:
            st.caption(details)

    if st.session_state.pop("load_ohlcv_requested", False):
        _process_load_request(state)

    pending = bool(st.session_state.get("config_pending_changes", False))
    is_running = bool(st.session_state.get("is_running", False))
    run_label = get_run_label_for_mode(
        str(st.session_state.get("optimization_mode", state.optimization_mode))
    )

    st.markdown('<div class="bc-main-actions-anchor"></div>', unsafe_allow_html=True)
    st.markdown("### Actions d'exécution")
    if pending:
        st.caption(
            "⚠️ Modifications non appliquées: elles seront appliquées au prochain chargement ou lancement."
        )
    else:
        st.caption("Configuration prête pour chargement, lancement ou arrêt propre.")

    col_load, col_run, col_stop = st.columns([1.05, 1.15, 0.9])
    with col_load:
        st.button(
            "⬇️ Charger marché & aperçu",
            key="main_load_ohlcv_action",
            type="secondary",
            disabled=is_running,
            use_container_width=True,
            on_click=_queue_main_load_action,
            help=(
                "Charge le marché sélectionné et met à jour l'aperçu OHLCV + indicateurs. "
                "En mode Builder autonome, la présélection reste facultative."
            ),
        )

    with col_run:
        st.button(
            run_label,
            key="main_run_action",
            type="primary",
            disabled=is_running,
            use_container_width=True,
            on_click=_queue_main_run_action,
            args=(str(state.optimization_mode or ""),),
        )

    with col_stop:
        if st.button(
            "🛑 Arrêter et nettoyer",
            key="main_stop_action",
            type="secondary",
            disabled=not is_running,
            use_container_width=True,
            help=(
                "Arrête le run courant, décharge les modèles Ollama détectés, vide les caches "
                "et réinitialise le runtime Builder/LLM pour un nouveau lancement propre."
            ),
        ):
            _execute_clean_stop(state)
            st.rerun()


def render_controls() -> tuple[bool, Any]:
    st.title("📈 Backtest Core - Moteur Simplifié")

    status_container = st.container()

    st.markdown(
        """
Interface avec validation des paramètres et feedback utilisateur.
Le système de granularité limite le nombre de valeurs testables.
"""
    )

    ensure_ui_execution_state_defaults(st.session_state)

    st.markdown("---")

    run_requested = consume_ui_run_request(st.session_state)

    return run_requested, status_container


def render_setup_previews(state: SidebarState) -> None:
    st.markdown("---")
    st.subheader("Schema indicateurs & parametres")
    if state.strategy_instance is None:
        st.info("Selectionnez une strategie pour afficher le schema.")
    else:
        diagram_params = {
            **state.strategy_instance.default_params,
            **state.params,
        }
        render_strategy_param_diagram(
            state.strategy_key,
            diagram_params,
            key=f"diagram_{state.strategy_key}",
        )

    st.markdown("---")
    st.subheader("Apercu OHLCV + indicateurs")
    preview_df = st.session_state.get("ohlcv_df")
    if preview_df is None:
        st.info("Chargez les donnees pour afficher l'apercu.")
    else:
        preview_overlays = build_indicator_overlays(
            state.strategy_key,
            preview_df,
            state.params,
        )
        render_ohlcv_with_trades_and_indicators(
            df=preview_df,
            trades_df=pd.DataFrame(),
            overlays=preview_overlays,
            active_indicators=state.active_indicators,
            title="OHLCV + indicateurs (apercu)",
            key="ohlcv_indicator_preview",
            height=650,
        )


def _render_builder_view_safe(
    *,
    state: SidebarState,
    df: Any,
    status_container: Any,
) -> None:
    from ui.builder_view import (
        mark_builder_autonomous_runtime_stopped,
        render_builder_view,
    )

    try:
        render_builder_view(
            state=state,
            df=df,
            status_container=status_container,
        )
    except Exception as exc:
        logging.getLogger(__name__).error(
            "builder_view_unhandled_exception error=%s\n%s",
            exc,
            traceback.format_exc(),
        )
        clear_execution_state(st.session_state)
        try:
            mark_builder_autonomous_runtime_stopped(
                reason="builder_view_crash",
                manual_stop=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        except Exception:
            logging.getLogger(__name__).warning("mark_builder_autonomous_runtime_stopped failed", exc_info=True)
        with status_container:
            show_status("error", f"Erreur Builder UI: {exc}")
            st.code(traceback.format_exc())


def _abort_main_run(
    status_container: Any,
    msg: str,
    *,
    level: str = "error",
    live_status: Any = None,
    tb: bool = False,
    extra: Any = None,
) -> None:
    """Point de sortie unique pour les aborts de run dans render_main et ses extractions."""
    if live_status is not None:
        try:
            live_status.update(label=f"❌ {msg}", state="error")
        except Exception:
            pass
    with status_container:
        show_status(level, msg)
        if extra is not None:
            extra()
        if tb:
            st.code(traceback.format_exc())
    clear_execution_state(st.session_state)
    st.stop()


def _finalize_run_result(
    result: Any,
    df: Any,
    params: Dict[str, Any],
    origin: str,
    *,
    attach_wfa: Any,
    status_container: Any | None = None,
) -> None:
    """Bloc commun de finalisation après un backtest réussi.

    Enchaîne WFA metrics → persist_run_winner → auto-save.
    """
    result, _, wfa_msg = attach_wfa(result, df, params)
    if wfa_msg:
        if status_container is not None:
            with status_container:
                show_status("info", wfa_msg)
        else:
            show_status("info", wfa_msg)
    persist_run_winner(
        st.session_state,
        result=result,
        params=params,
        metrics=result.metrics,
        origin=origin,
        meta=result.meta,
    )
    _maybe_auto_save_run(result)


def _run_grid_search_mode(
    *,
    df,
    engine,
    state,
    status_container,
    strategy_key,
    params,
    param_ranges,
    symbol,
    timeframe,
    debug_enabled,
    n_workers,
    max_combos,
    resolve_workers,
    resolve_threads,
    format_combo_limit,
    attach_wfa_metrics,
):
    """Grid search optimization — extracted from render_main."""
    # Alias closures to their original names used throughout the body
    _resolve_workers = resolve_workers
    _resolve_threads = resolve_threads
    _format_combo_limit = format_combo_limit
    _attach_wfa_metrics = attach_wfa_metrics

    n_workers_effective = _resolve_workers(n_workers)
    # Lire threads depuis UI ou fallback env
    try:
        worker_thread_limit = int(st.session_state.get(
            "grid_worker_threads",
            int(os.environ.get("BACKTEST_WORKER_THREADS", "1"))))
    except (TypeError, ValueError):
        worker_thread_limit = 1
    worker_thread_limit = _resolve_threads(worker_thread_limit)
    _apply_thread_limit(worker_thread_limit, label="main")

    with st.spinner("📊 Génération de la grille..."):
        try:
            param_names = list(param_ranges.keys())
            param_values_lists: List[List[Any]] = []

            if param_names:
                for pname in param_names:
                    r = param_ranges[pname]
                    pmin = r.get("min") if isinstance(r, dict) else None
                    _raw_values = r.get("values") if isinstance(r, dict) else None
                    if _raw_values is None:
                        pmin, pmax, step = r["min"], r["max"], r["step"]

                        if isinstance(pmin, int) and isinstance(step, int):
                            built: List[Any] = list(range(int(pmin), int(pmax) + 1, int(step)))
                        else:
                            _arr = np.arange(float(pmin), float(pmax) + float(step) / 2, float(step))  # type: ignore[arg-type]
                            built = [round(float(v), 2) for v in _arr if v <= pmax]

                        values_for_param: List[Any] = built
                    else:
                        if isinstance(_raw_values, (list, tuple)):
                            values_for_param = list(_raw_values)
                        else:
                            values_for_param = [_raw_values]

                    if not values_for_param:
                        values_for_param = [pmin]

                    param_values_lists.append(values_for_param)

                total_combinations = max(
                    1, math.prod(len(values) for values in param_values_lists)
                )
                combo_iter = (
                    {**params, **dict(zip(param_names, combo))}
                    for combo in product(*param_values_lists)
                )
            else:
                total_combinations = 1
                combo_iter = iter([params.copy()])  # type: ignore[assignment]

            total_runs = total_combinations

            if total_runs < total_combinations:
                show_status(
                    "info",
                    f"Grille: {total_runs:,} / {total_combinations:,} combinaisons ({n_workers_effective} workers × {worker_thread_limit} threads)",
                )
            else:
                show_status("info", f"Grille: {total_runs:,} combinaisons ({n_workers_effective} workers × {worker_thread_limit} threads)")

        except Exception as exc:
            _abort_main_run(status_container, f"Échec génération grille: {exc}")

    # ✅ CRITIQUE: Définir fast_metrics ICI pour qu'il soit accessible aux fonctions imbriquées
    # Déterminer si on utilise les métriques rapides (sweeps >500 runs)
    try:
        fast_threshold = int(os.getenv("BACKTEST_SWEEP_FAST_METRICS_THRESHOLD", "500"))
    except (TypeError, ValueError):
        fast_threshold = 500
    fast_metrics = total_runs >= fast_threshold

    results_list = []
    param_combos_map = {}

    monitor = ProgressMonitor(total_runs=total_runs)
    monitor_placeholder = st.empty()

    sweep_monitor = SweepMonitor(
        total_combinations=total_runs,
        objectives=["total_pnl", "theoretical_pnl", "sharpe_ratio", "total_return_pct", "max_drawdown"],
        top_k=15,
    )
    sweep_monitor.start()
    sweep_placeholder = st.empty()

    logger = logging.getLogger(__name__)
    error_counts: Dict[str, int] = {}
    error_logged: set[str] = set()
    try:
        error_log_limit = int(os.environ.get("BACKTEST_SWEEP_ERROR_LOG_LIMIT", "3"))
    except (TypeError, ValueError):
        error_log_limit = 3

    st.markdown("### 📊 Progression en temps réel")
    render_progress_monitor(monitor, monitor_placeholder)

    def _normalize_param_combo(param_combo: Dict[str, Any]) -> Dict[str, Any]:
        return {
            k: float(v) if hasattr(v, "item") else v for k, v in param_combo.items()
        }

    def _params_to_str(param_combo: Dict[str, Any]) -> str:
        return str(_normalize_param_combo(param_combo))

    def run_single_backtest(param_combo: Dict[str, Any]):
        try:
            # ✅ CRITIQUE: Utiliser fast_metrics pour sweeps séquentiels aussi
            result_i, msg_i = safe_run_backtest(
                engine,
                df,
                strategy_key,
                param_combo,
                symbol,
                timeframe,
                silent_mode=not debug_enabled,
                fast_metrics=fast_metrics,  # ✅ Activer métriques rapides
            )

            params_str = _params_to_str(param_combo)

            if result_i:
                m = result_i.metrics
                # Log des clés disponibles si debug activé
                if debug_enabled and not m:
                    logger.warning("Metrics vides pour params=%s", params_str)
                return {
                    "params": params_str,
                    "params_dict": param_combo,
                    "total_pnl": m.get("total_pnl", 0.0),
                    "theoretical_pnl": m.get("theoretical_pnl", 0.0),
                    "sharpe": m.get("sharpe_ratio", 0.0),
                    "max_dd": m.get("max_drawdown_pct", m.get("max_drawdown", 0.0)),
                    "win_rate": m.get("win_rate", 0.0),
                    "trades": m.get("total_trades", 0),
                    "profit_factor": m.get("profit_factor", 0.0),
                }
            return {
                "params": params_str,
                "params_dict": param_combo,
                "error": msg_i,
            }
        except Exception as exc:
            params_str = _params_to_str(param_combo)
            # Log complet de l'erreur avec traceback
            if debug_enabled:
                logger.error("Backtest error params=%s: %s", params_str, traceback.format_exc())
            return {
                "params": params_str,
                "params_dict": param_combo,
                "error": f"{type(exc).__name__}: {exc}",
            }

    def record_sweep_result(
        result: Dict[str, Any],
        fallback_params: Dict[str, Any],
    ) -> str:
        param_combo_result = result.get("params_dict") or fallback_params
        params_str = result.get("params") or _params_to_str(param_combo_result)
        result["params"] = params_str
        param_combos_map[params_str] = param_combo_result

        if "error" not in result:
            metrics = {
                "sharpe_ratio": result.get("sharpe", 0.0),
                "total_pnl": result.get("total_pnl", 0.0),
                "theoretical_pnl": result.get("theoretical_pnl", 0.0),
                "total_return_pct": result.get("total_pnl", 0.0) / state.initial_capital * 100 if state.initial_capital else 0.0,
                "max_drawdown": abs(result.get("max_dd", 0.0)),
                "win_rate": result.get("win_rate", 0.0),
                "total_trades": result.get("trades", 0),
                "profit_factor": result.get("profit_factor", 0.0),
                "consecutive_losses_max": result.get("consecutive_losses_max", 0),
                "avg_win_loss_ratio": result.get("avg_win_loss_ratio", 0.0),
                "robustness_score": result.get("robustness_score", 0.0),
            }
            sweep_monitor.update(params=param_combo_result, metrics=metrics)
        else:
            error_msg = str(result.get("error") or "Erreur inconnue")
            error_counts[error_msg] = error_counts.get(error_msg, 0) + 1
            if len(error_logged) < error_log_limit and error_msg not in error_logged:
                logger.error("Sweep error sample: %s", error_msg)
                error_logged.add(error_msg)
            sweep_monitor.update(params=param_combo_result, metrics={}, error=True)

        result_clean = {k: v for k, v in result.items() if k != "params_dict"}
        results_list.append(result_clean)
        return params_str

    completed_params = set()
    completed = 0
    last_render_time = time.perf_counter()
    start_time = time.perf_counter()
    from utils.sweep_diagnostics import SweepDiagnostics
    diag = SweepDiagnostics(run_id=f"grid_{strategy_key}")

    def run_sequential_combos(combo_source, key_prefix: str) -> None:
        _ = key_prefix  # paramètre stable d'API
        nonlocal completed, last_render_time
        for param_combo in combo_source:
            params_str = _params_to_str(param_combo)
            if params_str in completed_params:
                continue

            completed += 1
            monitor.runs_completed = completed

            result = run_single_backtest(param_combo)
            params_str = record_sweep_result(result, param_combo)
            completed_params.add(params_str)

            current_time = time.perf_counter()
            # ⚡ AFFICHAGE MINIMAL: Désactivation render_sweep_progress pendant le sweep (économie CPU/WebSocket)
            # Les graphiques temps réel consomment énormément de ressources (Plotly + HTML + WebSocket)
            # On garde juste une progression textuelle, l'affichage complet sera fait à la fin
            if completed % 1000 == 0 or current_time - last_render_time >= 30.0:
                with sweep_placeholder.container():
                    progress_pct = (completed / total_runs * 100) if total_runs > 0 else 0
                    elapsed = time.perf_counter() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    remaining = (total_runs - completed) / rate if rate > 0 else 0

                    # Barre de progression simple (pas d'HTML custom lourd)
                    st.progress(progress_pct / 100.0)
                    st.text(f"⚡ {completed:,}/{total_runs:,} runs ({progress_pct:.1f}%) | {rate:.1f} bt/s | ETA: {int(remaining//60)}m{int(remaining % 60)}s")

                    # Afficher uniquement le meilleur PnL (pas de graphiques ni tableaux)
                    if hasattr(sweep_monitor, '_results') and sweep_monitor._results:
                        best_result = max(sweep_monitor._results, key=lambda r: r.metrics.get("total_pnl", float("-inf")))
                        best_pnl = best_result.metrics.get("total_pnl", 0)
                        pnl_color = "green" if best_pnl > 0 else "red"
                        st.markdown(f"💰 **Meilleur PnL**: :{pnl_color}[**${best_pnl:+,.2f}**]")

                last_render_time = current_time
                time.sleep(0.01)

    if n_workers_effective > 1:
        os.environ.setdefault("BACKTEST_INDICATOR_DISK_CACHE", "0")

    if n_workers_effective > 1 and total_runs > 1:
        from concurrent.futures import (
            FIRST_COMPLETED,
            ProcessPoolExecutor,
            TimeoutError as FutureTimeoutError,
            wait,
        )

        try:
            from concurrent.futures import BrokenProcessPool  # type: ignore[attr-defined]
        except ImportError:  # pragma: no cover - fallback for older runtimes
            BrokenProcessPool = RuntimeError

        diag.log_pool_start(n_workers_effective, worker_thread_limit, total_runs)

        logger = logging.getLogger(__name__)
        stall_timeout_sec = float(os.getenv("BACKTEST_SWEEP_STALL_SEC", "60"))
        stall_startup_sec = float(os.getenv("BACKTEST_SWEEP_STALL_STARTUP_SEC", "180"))
        # ✅ FIX #1: Augmenter max_inflight pour alimenter tous les workers
        # Avant: n_workers × 2 = 48 tâches pour 24 workers (workers idle 50% du temps)
        # Après: n_workers × 8 = 192 tâches pour 24 workers (workers toujours alimentés)
        max_inflight = max(1, min(total_runs, n_workers_effective * 8))
        pending = {}
        failed_pending: List[Any] = []
        pool_failed = False
        pool_fail_reason = None
        pool_error: Exception | None = None
        pool_start_time = time.perf_counter()
        last_completion_time = time.perf_counter()
        recent_durations_sec: deque = deque(maxlen=20)
        pickle_error_count = 0  # Compteur d'erreurs de pickling
        combo_counter = 0  # Compteur pour diagnostics

        # Import de l'initializer optimisé qui charge le DataFrame une seule fois par worker
        from backtest.worker import init_worker_with_dataframe

        # ✅ FIX #5: Définir executor AVANT submit_next() pour éviter closure sur variable non définie
        executor = ProcessPoolExecutor(
            max_workers=n_workers_effective,
            initializer=init_worker_with_dataframe,
            initargs=(
                df,  # DataFrame chargé UNE SEULE FOIS par worker
                strategy_key,
                symbol,
                timeframe,
                state.initial_capital,
                debug_enabled,
                worker_thread_limit,
                fast_metrics,  # ✅ CRITIQUE: Activer métriques rapides pour sweeps
                False,         # is_path (DataFrame fourni directement, pas un chemin)
            ),
        )

        # ✅ FIX #5 (suite): Définir submit_next() APRÈS executor
        def submit_next() -> bool:
            nonlocal combo_counter
            try:
                param_combo = next(combo_iter)
            except StopIteration:
                return False
            combo_counter += 1
            diag.log_submit(combo_counter, param_combo)
            submit_ts = time.perf_counter()
            future = executor.submit(_isolated_worker, param_combo)
            pending[future] = (param_combo, submit_ts)
            return True

        try:
            for _ in range(max_inflight):
                if not submit_next():
                    break

            while pending:
                # ✅ FIX #2: Réduire timeout de 0.5s à 0.05s (10× plus rapide)
                # Avant: Latence de 500ms entre chaque vérification
                # Après: Latence de 50ms (workers alimentés 10× plus vite)
                done, _ = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
                if not done:
                    now = time.perf_counter()
                    if completed == 0:
                        stall_threshold_sec = stall_startup_sec
                        stalled = (now - pool_start_time) >= stall_threshold_sec
                    else:
                        avg_duration = (
                            sum(recent_durations_sec) / len(recent_durations_sec)
                            if recent_durations_sec else 0.0
                        )
                        stall_threshold_sec = max(
                            stall_timeout_sec,
                            avg_duration * 3 if avg_duration > 0 else stall_timeout_sec,
                        )
                        stalled = (now - last_completion_time) >= stall_threshold_sec

                    if stalled:
                        pool_failed = True
                        pool_fail_reason = "stall"
                        pool_error = TimeoutError(
                            f"Aucune completion depuis {stall_threshold_sec:.0f}s"
                        )
                        diag.log_stall(stall_threshold_sec, len(pending))
                        logger.error(
                            "Sweep multiprocess bloque depuis %ss, bascule sequentielle.",
                            int(stall_threshold_sec),
                        )
                        break
                    continue

                for future in done:
                    param_combo, submit_ts = pending.pop(future)
                    result = None
                    should_record = True

                    try:
                        # Timeout 300s pour éviter freeze si Windows interrupt (Task Manager, focus change, etc.)
                        result = future.result(timeout=300)
                        duration_ms = (time.perf_counter() - submit_ts) * 1000
                        recent_durations_sec.append(duration_ms / 1000.0)

                        # Log completion
                        combo_idx = combo_counter - len(pending) - len(failed_pending)
                        diag.log_completion(combo_idx, param_combo, result, duration_ms)

                        # Détecter erreur de pickling dans le résultat
                        if isinstance(result, dict) and result.get("error", ""):
                            error_msg = str(result.get("error", ""))
                            if "pickle" in error_msg.lower() or "not the same object" in error_msg:
                                pickle_error_count += 1
                                if pickle_error_count >= 10:
                                    pool_failed = True
                                    pool_fail_reason = "pickle"
                                    pool_error = RuntimeError(
                                        "Erreur de pickling détectée - Streamlit a rechargé le module. "
                                        "Relancez le sweep après le rechargement."
                                    )
                                    logger.error(
                                        "Erreur de pickling répétée (%d fois), arrêt du sweep.",
                                        pickle_error_count,
                                    )
                                    failed_pending.append(param_combo)
                                    should_record = False
                                    break

                    except BrokenProcessPool as exc:
                        combo_idx = combo_counter - len(pending) - len(failed_pending)
                        diag.log_pool_broken("BrokenProcessPool", exc)
                        pool_failed = True
                        pool_fail_reason = "broken"
                        pool_error = exc
                        failed_pending.append(param_combo)
                        should_record = False

                        break

                    except FutureTimeoutError:
                        # Worker timeout (>300s) - probablement bloqué par interruption Windows
                        combo_idx = combo_counter - len(pending) - len(failed_pending)
                        diag.log_timeout(combo_idx, param_combo, 300)
                        logger.warning("Worker timeout (>300s) combo: %s", param_combo)
                        result = {
                            "params": _params_to_str(param_combo),
                            "params_dict": param_combo,
                            "error": "Worker timeout (>300s, probablement bloqué par interruption Windows)",
                        }
                        # should_record reste True - on enregistre le timeout comme erreur

                    except Exception as exc:
                        combo_idx = combo_counter - len(pending) - len(failed_pending)
                        diag.log_future_exception(combo_idx, param_combo, exc)
                        error_str = f"{type(exc).__name__}: {exc}"
                        # Détecter erreur de pickling dans l'exception
                        if "pickle" in error_str.lower() or "not the same object" in error_str:
                            pickle_error_count += 1
                            if pickle_error_count >= 10:
                                pool_failed = True
                                pool_fail_reason = "pickle"
                                pool_error = RuntimeError(
                                    "Erreur de pickling - le module a été rechargé pendant le sweep."
                                )
                                failed_pending.append(param_combo)
                                should_record = False
                                break
                        result = {
                            "params": _params_to_str(param_combo),
                            "params_dict": param_combo,
                            "error": error_str,
                        }
                        # should_record reste True - on enregistre l'erreur

                    # Enregistrer le résultat (sauf si break anticipé)
                    if should_record and result is not None:
                        completed += 1
                        monitor.runs_completed = completed
                        params_str = record_sweep_result(result, param_combo)
                        completed_params.add(params_str)
                        last_completion_time = time.perf_counter()

                    # ⚡ CRITIQUE: Soumettre la combinaison suivante UNE SEULE FOIS après traitement complet
                    # (sauf si pool_failed ou break - dans ce cas on sort de la boucle de toute façon)
                    if not pool_failed:
                        submit_next()

                    current_time = time.perf_counter()
                    # ⚡ AFFICHAGE MINIMAL: Désactivation render_sweep_progress pendant le sweep (économie CPU/WebSocket)
                    # Les graphiques temps réel consomment énormément de ressources (Plotly + HTML + WebSocket)
                    # On garde juste une progression textuelle, l'affichage complet sera fait à la fin
                    if completed % 1000 == 0 or current_time - last_render_time >= 30.0:
                        with sweep_placeholder.container():
                            progress_pct = (completed / total_runs * 100) if total_runs > 0 else 0
                            elapsed = time.perf_counter() - start_time
                            rate = completed / elapsed if elapsed > 0 else 0
                            remaining = (total_runs - completed) / rate if rate > 0 else 0

                            # Barre de progression simple (pas d'HTML custom lourd)
                            st.progress(progress_pct / 100.0)
                            st.text(f"⚡ {completed:,}/{total_runs:,} runs ({progress_pct:.1f}%) | {rate:.1f} bt/s | ETA: {int(remaining//60)}m{int(remaining % 60)}s")

                            # Afficher uniquement le meilleur PnL (pas de graphiques ni tableaux)
                            if hasattr(sweep_monitor, '_results') and sweep_monitor._results:
                                best_result = max(sweep_monitor._results, key=lambda r: r.metrics.get("total_pnl", float("-inf")))
                                best_pnl = best_result.metrics.get("total_pnl", 0)
                                pnl_color = "green" if best_pnl > 0 else "red"
                                st.markdown(f"💰 **Meilleur PnL**: :{pnl_color}[**${best_pnl:+,.2f}**]")

                        last_render_time = current_time
                        time.sleep(0.01)

                if pool_failed:
                    diag.log_pool_broken(pool_fail_reason or "unknown", pool_error)  # type: ignore[arg-type]
                    break
        finally:
            diag.log_pool_shutdown(success=not pool_failed)
            try:
                executor.shutdown(
                    wait=not pool_failed,
                    cancel_futures=pool_failed,
                )
            except Exception:
                logger.exception("Erreur shutdown ProcessPoolExecutor")

        if pool_failed:
            with status_container:
                if pool_fail_reason == "pickle":
                    show_status(
                        "error",
                        "⚠️ Erreur de pickling: le module a été rechargé par Streamlit pendant le sweep. "
                        "Relancez le sweep - il reprendra depuis les combinaisons non testées.",
                    )
                else:
                    show_status(
                        "warning",
                        "Pool multiprocess interrompu, reprise en mode séquentiel.",
                    )
                if pool_error:
                    st.caption(f"Détails: {pool_error}")

            pending_combos = failed_pending + [item[0] for item in pending.values()]
            if pool_fail_reason == "stall" and pending_combos:
                logger.warning(
                    "Stall détecté: %d combinaisons en attente seront relancées en séquentiel.",
                    len(pending_combos),
                )

            diag.log_sequential_fallback(pool_fail_reason, len(pending_combos))
            fallback_iter = chain(pending_combos, combo_iter)
            run_sequential_combos(fallback_iter, "sweep_fallback")
    else:
        run_sequential_combos(combo_iter, "sweep_sequential")

    render_progress_monitor(monitor, monitor_placeholder)
    sweep_placeholder.empty()
    with sweep_placeholder.container():
        render_sweep_progress(
            sweep_monitor,
            key="sweep_final",
            show_top_results=True,
            show_evolution=True,
        )

    st.markdown("---")
    st.markdown("### 🎯 Résumé de l'Optimisation")
    render_sweep_summary(sweep_monitor, key="sweep_summary")

    # Finalize diagnostics
    diag.log_final_summary()
    st.caption(f"📋 Logs diagnostiques: `{diag.log_file}`")

    monitor_placeholder.empty()
    sweep_placeholder.empty()

    with status_container:
        show_status("success", f"Optimisation: {len(results_list)} tests")

    results_df = pd.DataFrame(results_list)

    if "trades" in results_df.columns:
        logger = logging.getLogger(__name__)
        logger.info("=" * 80)
        logger.info("🔍 DEBUG GRID SEARCH - Analyse de la colonne 'trades'")
        logger.info("   Type: %s", results_df["trades"].dtype)
        logger.info("   Shape: %s", results_df["trades"].shape)
        logger.info(
            "   Premières valeurs: %s",
            results_df["trades"].head(10).tolist(),
        )
        logger.info(
            "   Stats: min=%s, max=%s, mean=%.2f",
            results_df["trades"].min(),
            results_df["trades"].max(),
            results_df["trades"].mean(),
        )

        trades_values = results_df["trades"].values
        fractional = [
            x for x in trades_values if isinstance(x, float) and not x.is_integer()
        ]
        if fractional:
            logger.warning(
                "   ⚠️  %s valeurs fractionnaires détectées: %s",
                len(fractional),
                fractional[:5],
            )
        else:
            logger.info("   ✅ Toutes les valeurs sont des entiers")
        logger.info("=" * 80)

    error_items = []
    if error_counts:
        total_errors = sum(error_counts.values())
        with st.expander("❌ Erreurs (extraits)", expanded=True):
            st.caption(
                f"{total_errors} erreurs detectees. "
                "Consultez le terminal pour les premiers messages."
            )
            error_items = sorted(
                error_counts.items(), key=lambda item: item[1], reverse=True
            )
            error_df = pd.DataFrame(
                [
                    {"error": msg, "count": count}
                    for msg, count in error_items[:10]
                ]
            )
            st.dataframe(error_df, use_container_width=True)

    error_column = results_df.get("error")
    if error_column is not None:
        valid_results = results_df[error_column.isna()]
    else:
        valid_results = results_df

    if not valid_results.empty:
        valid_results = valid_results.sort_values("sharpe", ascending=False)

        st.subheader("🏆 Top 10 Combinaisons")

        with st.expander("🔍 Debug Info - Types de données"):
            st.text(f"Nombre de résultats: {len(valid_results)}")
            st.text("Types des colonnes:")
            st.text(str(valid_results.dtypes))
            if "trades" in valid_results.columns:
                st.text("\nStatistiques 'trades':")
                st.text(f"  Type: {valid_results['trades'].dtype}")
                st.text(f"  Min: {valid_results['trades'].min()}")
                st.text(f"  Max: {valid_results['trades'].max()}")
                st.text(
                    f"  Mean: {valid_results['trades'].mean():.2f}"
                )

        st.dataframe(valid_results.head(10), use_container_width=True)

        best = valid_results.iloc[0]
        st.info(f"🥇 Meilleure: {best['params']}")

        best_params = param_combos_map.get(best["params"], {})
        result, _ = safe_run_backtest(
            engine,
            df,
            strategy_key,
            best_params,
            symbol,
            timeframe,
            silent_mode=not debug_enabled,
        )
        if result is not None:
            _finalize_run_result(result, df, best_params, "grid", attach_wfa=_attach_wfa_metrics)
    else:
        def _grid_diagnostic():
            st.markdown("### 🔍 Diagnostic")
            st.warning(
                f"Sur {len(results_list)} combinaisons évaluées, "
                f"toutes ont échoué."
            )
            if error_items:
                top_error, top_count = error_items[0]
                st.error(
                    f"**Erreur principale** ({top_count} occurrences sur {sum(error_counts.values())} erreurs):"
                )
                st.code(top_error, language="text")
            elif results_list:
                errors_in_results = [
                    r.get("error") for r in results_list if r.get("error")
                ]
                if errors_in_results:
                    st.error("**Première erreur détectée:**")
                    st.code(errors_in_results[0], language="text")
                    if len(errors_in_results) > 1:
                        st.caption(f"+ {len(errors_in_results)-1} autres erreurs similaires")
                else:
                    st.info(
                        "Aucune erreur explicite, mais les résultats sont invalides. "
                        "Vérifiez que les données OHLCV sont chargées et valides."
                    )

        _abort_main_run(status_container, "Aucun résultat valide", extra=_grid_diagnostic)




def _run_llm_optimization_mode(
    *,
    df,
    engine,
    state,
    status_container,
    strategy_key,
    params,
    symbol,
    timeframe,
    debug_enabled,
    n_workers,
    max_combos,
    llm_config,
    llm_model,
    llm_max_iterations,
    llm_use_multi_agent,
    llm_use_walk_forward,
    llm_unload_during_backtest,
    llm_compare_enabled,
    llm_compare_auto_run,
    llm_compare_strategies,
    llm_compare_tokens,
    llm_compare_timeframes,
    llm_compare_metric,
    llm_compare_aggregate,
    llm_compare_max_runs,
    llm_compare_use_preset,
    llm_compare_generate_report,
    resolve_workers,
    format_combo_limit,
    prepare_market_df,
    attach_wfa_metrics,
):
    """LLM optimization mode — extracted from render_main."""
    # Alias closures to their original names used throughout the body
    _resolve_workers = resolve_workers
    _format_combo_limit = format_combo_limit
    _prepare_market_df = prepare_market_df
    _attach_wfa_metrics = attach_wfa_metrics

    if not LLM_AVAILABLE:
        _abort_main_run(
            status_container, "Module agents LLM non disponible",
            extra=lambda: st.code(LLM_IMPORT_ERROR),
        )

    if llm_config is None:
        _abort_main_run(
            status_container, "Configuration LLM incomplète",
            extra=lambda: st.info("Configurez le provider LLM dans la sidebar"),
        )

    session_id = generate_session_id()  # type: ignore[misc]
    orchestration_logger = OrchestrationLogger(session_id=session_id)  # type: ignore[misc]

    try:
        param_bounds = get_strategy_param_bounds(strategy_key)  # type: ignore[misc]
        if not param_bounds:
            param_bounds = {}
            for pname in params.keys():
                if pname in PARAM_CONSTRAINTS:
                    c = PARAM_CONSTRAINTS[pname]
                    param_bounds[pname] = (c["min"], c["max"])
    except Exception as exc:
        show_status("warning", f"Bornes par défaut utilisées: {exc}")
        param_bounds = {}
        for pname in params.keys():
            if pname in PARAM_CONSTRAINTS:
                c = PARAM_CONSTRAINTS[pname]
                param_bounds[pname] = (c["min"], c["max"])

    try:
        full_param_space = get_strategy_param_space(strategy_key, include_step=True)  # type: ignore[misc]
        llm_space_stats = compute_search_space_stats(full_param_space)  # type: ignore[misc]
    except Exception:
        llm_space_stats = None

    max_iterations = min(llm_max_iterations, max_combos)

    comparison_summary: List[Dict[str, Any]] = []
    should_run_comparison = llm_compare_enabled and (
        llm_compare_auto_run or st.session_state.get("llm_compare_run_now", False)
    )
    if should_run_comparison:
        st.subheader("Comparaison multi-strategies")
        if not llm_compare_strategies:
            st.warning("Aucune strategie selectionnee pour la comparaison.")
        elif not llm_compare_tokens or not llm_compare_timeframes:
            st.warning("Selectionnez au moins un token et un timeframe.")
        else:
            start_str = str(state.start_date) if state.start_date else None
            end_str = str(state.end_date) if state.end_date else None
            progress_bar = st.progress(0)
            comparison_results: List[Dict[str, Any]] = []
            comparison_errors: List[str] = []
            data_cache: Dict[tuple[str, str], pd.DataFrame] = {}

            for token in llm_compare_tokens:
                for tf in llm_compare_timeframes:
                    df_cmp, msg = safe_load_data(token, tf, start_str, end_str)
                    if df_cmp is None:
                        comparison_errors.append(f"{token}/{tf}: {msg}")
                    else:
                        df_cmp, _ = _prepare_market_df(
                            df_cmp,
                            symbol_value=token,
                            timeframe_value=tf,
                            show_ui=False,
                        )
                        data_cache[(token, tf)] = df_cmp

            valid_pairs = list(data_cache.keys())
            total_runs = len(valid_pairs) * len(llm_compare_strategies)
            total_runs = max(0, min(total_runs, llm_compare_max_runs))
            run_index = 0

            with st.spinner("Comparaison en cours..."):
                for strategy_name_cmp in llm_compare_strategies:
                    params_cmp = build_strategy_params_for_comparison(
                        strategy_name_cmp,
                        use_preset=llm_compare_use_preset,
                    )
                    for token, tf in valid_pairs:
                        if run_index >= total_runs:
                            break
                        df_cmp = data_cache[(token, tf)]
                        result_cmp, status = safe_run_backtest(
                            engine,
                            df_cmp,
                            strategy_name_cmp,
                            params_cmp,
                            token,
                            tf,
                            silent_mode=not debug_enabled,
                        )
                        if result_cmp is None:
                            comparison_errors.append(
                                f"{strategy_name_cmp} {token}/{tf}: {status}"
                            )
                        else:
                            comparison_results.append(
                                {
                                    "strategy": strategy_name_cmp,
                                    "symbol": token,
                                    "timeframe": tf,
                                    "metrics": result_cmp.metrics,
                                    "trades": len(result_cmp.trades),
                                }
                            )
                        run_index += 1
                        if total_runs > 0:
                            progress_bar.progress(run_index / total_runs)
                    if run_index >= total_runs:
                        break

            if comparison_errors:
                st.warning(
                    "Comparaison: "
                    + "; ".join(comparison_errors[:8])
                    + (" ..." if len(comparison_errors) > 8 else "")
                )

            if comparison_results:
                comparison_summary = summarize_comparison_results(
                    comparison_results,
                    aggregate=llm_compare_aggregate,
                    primary_metric=llm_compare_metric,
                    expected_runs=len(valid_pairs),
                )
                st.caption(
                    f"Runs effectues: {len(comparison_results)} / {total_runs}"
                )
                st.dataframe(pd.DataFrame(comparison_summary), use_container_width=True)

                chart_rows = []
                for row in comparison_summary:
                    chart_rows.append(
                        {
                            "name": row["strategy"],
                            "metrics": {
                                llm_compare_metric: row.get(llm_compare_metric)
                            },
                        }
                    )
                render_comparison_chart(
                    chart_rows,
                    metric=llm_compare_metric,
                    title="Comparaison agregree",
                    key="llm_strategy_comparison",
                )

                if llm_compare_generate_report:
                    try:
                        llm_client = create_llm_client(llm_config)  # type: ignore[misc]
                        if not llm_client.is_available():
                            st.warning("LLM indisponible pour la justification.")
                        else:
                            summary_lines = [
                                "strategy | runs | sharpe | return_pct | max_drawdown | win_rate"
                            ]
                            for row in comparison_summary:
                                summary_lines.append(
                                    f"{row.get('strategy')} | "
                                    f"{row.get('runs')} | "
                                    f"{row.get('sharpe_ratio', float('nan')):.2f} | "
                                    f"{row.get('total_return_pct', float('nan')):.2f} | "
                                    f"{row.get('max_drawdown', float('nan')):.2f} | "
                                    f"{row.get('win_rate', float('nan')):.1f}"
                                )

                            system_prompt = (
                                "You are a senior quantitative strategist. "
                                "Compare strategy robustness across assets and timeframes."
                            )
                            user_message = (
                                "Comparison scope:\n"
                                f"- tokens: {', '.join(llm_compare_tokens)}\n"
                                f"- timeframes: {', '.join(llm_compare_timeframes)}\n"
                                f"- aggregation: {llm_compare_aggregate}\n"
                                f"- primary metric: {llm_compare_metric}\n\n"
                                "Summary table (metrics are percent where applicable):\n"
                                + "\n".join(summary_lines)
                                + "\n\n"
                                "Provide:\n"
                                "1) Ranking with short justification.\n"
                                "2) Notes on robustness and risk.\n"
                                "3) Which strategies deserve further optimization."
                            )

                            response = llm_client.simple_chat(
                                user_message=user_message,
                                system_prompt=system_prompt,
                                temperature=0.3,
                            )
                            st.markdown("**Justification LLM**")
                            st.write(response.content)
                    except Exception as exc:
                        st.warning(f"Justification LLM indisponible: {exc}")
            st.session_state["llm_compare_run_now"] = False

    st.subheader("🤖 Optimisation par Agents LLM")

    col_info, col_timeline = st.columns([1, 2])

    with col_info:
        st.markdown(
            f"""
    **Stratégie:** `{strategy_key}`
    **Paramètres initiaux:** `{params}`
    **Max itérations:** {llm_max_iterations}
    **Walk-Forward:** {'✅' if llm_use_walk_forward else '❌'}
    """
        )

        st.markdown("**Bornes des paramètres:**")
        for pname, (pmin, pmax) in param_bounds.items():
            st.caption(f"• {pname}: [{pmin}, {pmax}]")

        if llm_space_stats:
            st.markdown("---")
            if llm_space_stats.is_continuous:
                st.info("ℹ️ **Espace continu** : exploration adaptative par LLM")
            else:
                st.caption(
                    "📊 Espace discret estimé: "
                    f"~{llm_space_stats.total_combinations:,} combinaisons"
                )
                st.caption("_(Le LLM explore de façon intelligente sans énumérer)_")

    col_timeline.empty()

    strategist = None
    executor = None
    orchestrator = None

    run_tracker = get_global_tracker()
    data_identifier = (
        f"df_{len(df)}rows_{df.index[0]}_{df.index[-1]}"
        if len(df) > 0
        else "empty_df"
    )
    run_signature = RunSignature(
        strategy_name=strategy_key,
        data_path=data_identifier,
        initial_params=params,
        llm_model=llm_model,
        mode="multi_agents" if llm_use_multi_agent else "autonomous",
        session_id=session_id,
    )

    # Enregistrer le run (pour statistiques) sans bloquer l'exécution
    # Note: Le tracking des duplications durant la session est géré par session_param_tracker
    run_tracker.register(run_signature)

    with st.spinner("🔌 Connexion au LLM..."):
        try:
            if llm_use_multi_agent:
                live_events_placeholder = st.empty()
                live_viewer = LiveOrchestrationViewer(  # type: ignore[misc]
                    container_key="live_orch_viewer_multi"
                )

                def on_orchestration_event(entry):
                    live_viewer.add_event(entry)
                    live_viewer.render(live_events_placeholder, show_header=True)

                orchestration_logger.set_on_event_callback(on_orchestration_event)

                n_workers_effective = _resolve_workers(n_workers)
                orchestrator = create_orchestrator_with_backtest(  # type: ignore[misc]
                    llm_config=llm_config,
                    strategy_name=strategy_key,
                    data=df,
                    initial_params=params,
                    data_symbol=symbol,
                    data_timeframe=timeframe,
                    role_model_config=state.role_model_config,
                    llm_topology_config=state.llm_topology_config,
                    use_walk_forward=llm_use_walk_forward,
                    orchestration_logger=orchestration_logger,
                    session_id=session_id,
                    n_workers=n_workers_effective,
                    max_iterations=max_iterations,
                    initial_capital=state.initial_capital,
                    config=engine.config,
                )
                show_status(
                    "success",
                    "Connexion LLM établie (mode multi-agents)",
                )
            else:
                strategist, executor = create_optimizer_from_engine(  # type: ignore[misc]
                    llm_config=llm_config,
                    strategy_name=strategy_key,
                    data=df,
                    initial_capital=state.initial_capital,
                    use_walk_forward=llm_use_walk_forward,
                    verbose=True,
                    unload_llm_during_backtest=llm_unload_during_backtest,
                    orchestration_logger=orchestration_logger,
                )
                show_status("success", "Connexion LLM établie")
        except Exception as exc:
            _abort_main_run(status_container, f"Echec connexion LLM: {exc}", tb=True)

    if llm_use_multi_agent:
        st.markdown("---")
        st.markdown("### Progression multi-agents")
        n_workers_effective = _resolve_workers(n_workers)
        st.caption(
            f"Limite: {_format_combo_limit(max_combos)} backtests max, "
            f"{n_workers_effective} workers, {max_iterations} iterations max"
        )

        if orchestrator is None:
            _abort_main_run(status_container, "Orchestrator non initialise")

        try:
            with st.spinner("Optimisation multi-agents en cours..."):
                orchestrator_result = orchestrator.run()

            try:
                orchestration_logger.save_to_jsonl()
            except Exception:
                logger.warning("orchestration_logger.save_to_jsonl() failed — diagnostic data lost", exc_info=True)

            if orchestrator_result.errors:
                st.warning(
                    f"Orchestration errors: {len(orchestrator_result.errors)}"
                )
            if orchestrator_result.warnings:
                st.warning(
                    f"Orchestration warnings: {len(orchestrator_result.warnings)}"
                )

            if orchestrator_result.success:
                st.success("Optimisation multi-agents terminee")
            else:
                st.warning(
                    "Optimisation multi-agents terminee "
                    f"(decision: {orchestrator_result.decision})"
                )

            if orchestrator_result.final_params:
                st.subheader("Resultat multi-agents")
                st.json(orchestrator_result.final_params)
            else:
                st.warning("Aucun parametre final retourne")

            if orchestrator_result.final_metrics:
                metrics = orchestrator_result.final_metrics
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    st.metric("Sharpe", f"{metrics.sharpe_ratio:.3f}")
                with col_b:
                    st.metric("Return", f"{metrics.total_return:.2%}")
                with col_c:
                    st.metric("Max Drawdown", f"{metrics.max_drawdown:.2%}")

            if orchestrator_result.iteration_history:
                st.markdown("---")
                st.dataframe(
                    pd.DataFrame(orchestrator_result.iteration_history),
                    use_container_width=True,
                )

            best_params = orchestrator_result.final_params or {}
            if best_params:
                result, _ = safe_run_backtest(
                    engine,
                    df,
                    strategy_key,
                    best_params,
                    symbol,
                    timeframe,
                    silent_mode=not debug_enabled,
                )
                if result is not None:
                    _finalize_run_result(result, df, best_params, "llm", attach_wfa=_attach_wfa_metrics)
        except Exception as exc:
            _abort_main_run(status_container, f"Erreur optimisation multi-agents: {exc}", tb=True)
    else:
        st.markdown("---")
        st.markdown("### 📊 Progression de l'optimisation LLM")

        live_status = st.status(
            "🚀 Démarrage de l'optimisation...",
            expanded=True,
        )
        live_events_placeholder = st.empty()
        orchestration_placeholder = st.empty()

        max_iterations = min(llm_max_iterations, max_combos)

        live_viewer = LiveOrchestrationViewer(  # type: ignore[misc]
            container_key="live_orch_viewer"
        )

        def on_orchestration_event(entry):  # noqa: F811  # pylint: disable=function-redefined
            live_viewer.add_event(entry)
            live_viewer.render(live_events_placeholder, show_header=True)

        orchestration_logger.set_on_event_callback(on_orchestration_event)

        n_workers_effective = _resolve_workers(n_workers)
        st.caption(
            "🔧 Limite: "
            f"{_format_combo_limit(max_combos)} backtests max, {n_workers_effective} workers, "
            f"{max_iterations} itérations max"
        )

        try:
            with live_status:
                st.write("🤖 **Agent LLM actif** - Optimisation autonome")
                st.write(
                    f"📊 Stratégie: `{strategy_key}` | Modèle: `{llm_model}`"
                )

                session = strategist.optimize(  # type: ignore[union-attr]
                    executor=executor,
                    initial_params=params,
                    param_bounds=param_bounds,
                    max_iterations=max_iterations,
                    min_sharpe=-5.0,
                    max_drawdown=0.50,
                )

                live_status.update(
                    label=(
                        "✅ Optimisation terminée en "
                        f"{session.current_iteration} itérations"
                    ),
                    state="complete",
                    expanded=False,
                )

            st.success(
                f"✅ Optimisation terminée en {session.current_iteration} itérations"
            )

            with st.expander("📝 Historique des itérations", expanded=True):
                for i, exp in enumerate(session.all_results):
                    icon = "🟢" if exp.sharpe_ratio > 0 else "🔴"
                    col_it1, col_it2, col_it3 = st.columns([2, 1, 1])
                    with col_it1:
                        st.markdown(f"**Itération {i+1}** {icon}")
                        st.caption(
                            f"Params: `{exp.request.parameters}`"
                        )
                    with col_it2:
                        st.metric("Sharpe", f"{exp.sharpe_ratio:.3f}")
                    with col_it3:
                        st.metric("Return", f"{exp.total_return:.2%}")

            try:
                orchestration_logger.save_to_jsonl()
            except Exception:
                logging.getLogger(__name__).warning("orchestration_logger.save_to_jsonl failed", exc_info=True)

            with orchestration_placeholder:
                st.markdown("---")

                tab_simple, tab_deep = st.tabs(
                    ["📋 Logs d'orchestration", "🔍 Deep Trace (avancé)"]
                )

                with tab_simple:
                    render_full_orchestration_viewer(  # type: ignore[misc]
                        orchestration_logger=orchestration_logger,
                        max_entries=50,
                    )

                with tab_deep:
                    if LLM_AVAILABLE:
                        render_deep_trace_viewer(  # type: ignore[misc]
                            logger=orchestration_logger
                        )
                    else:
                        st.warning(
                            "Module LLM non disponible pour Deep Trace avancé"
                        )

            st.markdown("---")
            st.subheader("🏆 Résultat de l'optimisation LLM")

            col_best, col_improve = st.columns(2)

            with col_best:
                st.markdown("**Meilleurs paramètres trouvés:**")
                st.json(session.best_result.request.parameters)

                st.metric(
                    "Meilleur Sharpe",
                    f"{session.best_result.sharpe_ratio:.3f}",
                )
                st.metric(
                    "Return",
                    f"{session.best_result.total_return:.2%}",
                )

            with col_improve:
                if session.all_results:
                    initial_sharpe = session.all_results[0].sharpe_ratio
                    best_sharpe = session.best_result.sharpe_ratio
                    improvement = (
                        (best_sharpe - initial_sharpe) / abs(initial_sharpe) * 100
                    ) if initial_sharpe != 0 else 0

                    st.metric(
                        "Amélioration Sharpe",
                        f"{improvement:+.1f}%",
                        delta=f"{best_sharpe - initial_sharpe:+.3f}",
                    )
                    st.metric("Itérations utilisées", session.current_iteration)

                    if session.final_reasoning:
                        st.info(f"🛑 Arrêt: {session.final_reasoning}")

            best_params = session.best_result.request.parameters
            result, _ = safe_run_backtest(
                engine,
                df,
                strategy_key,
                best_params,
                symbol,
                timeframe,
                silent_mode=not debug_enabled,
            )
            if result is not None:
                _finalize_run_result(result, df, best_params, "llm", attach_wfa=_attach_wfa_metrics)

        except Exception as exc:
            _abort_main_run(
                status_container, f"Erreur optimisation LLM: {exc}",
                live_status=live_status, tb=True,
            )


def render_main(
    state: SidebarState,
    run_button: bool,
    status_container: Any,
) -> None:
    # Guard against stale lock states after an upstream interruption (sidebar/import errors).
    execution_phase = get_ui_execution_phase(st.session_state)
    if (
        execution_phase in {UI_EXECUTION_PHASE_LAUNCH_PENDING, UI_EXECUTION_PHASE_RUNNING}
        and not run_button
    ):
        if not should_preserve_builder_launch(state, st.session_state):
            clear_execution_state(st.session_state)

    params = state.params
    param_ranges = state.param_ranges
    strategy_key = state.strategy_key
    symbol = state.symbol
    timeframe = state.timeframe
    optimization_mode = state.optimization_mode
    debug_enabled = state.debug_enabled
    max_combos = state.max_combos
    n_workers = state.n_workers
    auto_stabilization_enabled = state.auto_stabilization_enabled
    stabilization_method = state.stabilization_method
    stabilization_window = state.stabilization_window
    stabilization_volume_ratio_max = state.stabilization_volume_ratio_max
    stabilization_volatility_ratio_max = state.stabilization_volatility_ratio_max
    stabilization_min_consecutive_bars = state.stabilization_min_consecutive_bars
    stabilization_min_bars_keep = state.stabilization_min_bars_keep

    llm_config = state.llm_config
    llm_model = state.llm_model
    llm_use_multi_agent = state.llm_use_multi_agent
    llm_max_iterations = state.llm_max_iterations
    llm_use_walk_forward = state.llm_use_walk_forward
    llm_unload_during_backtest = state.llm_unload_during_backtest
    llm_compare_enabled = state.llm_compare_enabled
    llm_compare_auto_run = state.llm_compare_auto_run
    llm_compare_strategies = state.llm_compare_strategies
    llm_compare_tokens = state.llm_compare_tokens
    llm_compare_timeframes = state.llm_compare_timeframes
    llm_compare_metric = state.llm_compare_metric
    llm_compare_aggregate = state.llm_compare_aggregate
    llm_compare_max_runs = state.llm_compare_max_runs
    llm_compare_use_preset = state.llm_compare_use_preset
    llm_compare_generate_report = state.llm_compare_generate_report

    use_gpu_indicators = bool(st.session_state.get("use_gpu_indicators", False))
    gpu_workers_override = bool(st.session_state.get("gpu_workers_override", False))

    def _resolve_workers(default_workers: int) -> int:
        if use_gpu_indicators and gpu_workers_override:
            try:
                return max(1, int(st.session_state.get("gpu_n_workers", default_workers)))
            except (TypeError, ValueError):
                return max(1, int(default_workers)) if default_workers else 1
        try:
            return max(1, int(default_workers))
        except (TypeError, ValueError):
            return 1

    def _resolve_threads(default_threads: int) -> int:
        if use_gpu_indicators and gpu_workers_override:
            try:
                return max(1, int(st.session_state.get("gpu_worker_threads", default_threads)))
            except (TypeError, ValueError):
                return max(1, int(default_threads)) if default_threads else 1
        try:
            return max(1, int(default_threads))
        except (TypeError, ValueError):
            return 1

    def _format_combo_limit(value: int) -> str:
        return "illimitée" if value >= 1_000_000_000_000 else f"{value:,}"

    def _prepare_market_df(
        raw_df: pd.DataFrame,
        *,
        symbol_value: str,
        timeframe_value: str,
        show_ui: bool = True,
    ) -> tuple[pd.DataFrame, Optional[Dict[str, Any]]]:
        filtered_df, stab_info = apply_auto_market_stabilization_filter(
            raw_df,
            enabled=auto_stabilization_enabled,
            method=stabilization_method,
            window=stabilization_window,
            volume_ratio_max=stabilization_volume_ratio_max,
            volatility_ratio_max=stabilization_volatility_ratio_max,
            min_consecutive_bars=stabilization_min_consecutive_bars,
            min_bars_keep=stabilization_min_bars_keep,
        )
        if stab_info.get("applied"):
            if show_ui:
                st.caption(
                    f"🛡️ Stabilisation {symbol_value}/{timeframe_value}: "
                    f"-{stab_info.get('cut_bars', 0)} barres, départ {stab_info.get('start_ts', 'n/a')}"
                )
            return filtered_df, stab_info
        return raw_df, None

    def _attach_wfa_metrics(
        run_result: Any,
        run_df: pd.DataFrame,
        run_params: Dict[str, Any],
    ) -> tuple[Any, Optional[Any], str]:
        if not state.use_walk_forward:
            return run_result, None, ""
        summary, message = safe_run_walk_forward(
            run_df,
            strategy_key,
            run_params,
            n_folds=state.wfa_n_folds,
            train_ratio=state.wfa_train_ratio,
            expanding=state.wfa_expanding,
        )
        if summary is None:
            return run_result, None, message

        robust_ratio = float(summary.avg_overfitting_ratio)
        degradation = float(summary.degradation_pct)
        test_sharpe = float(summary.avg_test_sharpe)
        confidence = float(summary.confidence_score)

        # Score anti-overfit simple: privilégie test_sharpe, ratio robuste faible et faible dégradation.
        sharpe_component = max(0.0, min(1.0, (test_sharpe + 2.0) / 4.0))
        ratio_component = max(0.0, min(1.0, 1.0 - max(0.0, robust_ratio - 1.0) / 2.0))
        degradation_component = max(0.0, min(1.0, 1.0 - degradation / 100.0))
        anti_overfit_score = (
            0.4 * sharpe_component
            + 0.35 * ratio_component
            + 0.25 * degradation_component
        )

        run_result.metrics["wfa_enabled"] = True
        run_result.metrics["wfa_is_robust"] = bool(summary.is_robust)
        run_result.metrics["wfa_n_valid_folds"] = int(summary.n_valid_folds)
        run_result.metrics["wfa_avg_train_sharpe"] = float(summary.avg_train_sharpe)
        run_result.metrics["wfa_avg_test_sharpe"] = test_sharpe
        run_result.metrics["wfa_overfitting_ratio"] = robust_ratio
        run_result.metrics["wfa_degradation_pct"] = degradation
        run_result.metrics["wfa_test_stability_std"] = float(summary.test_stability_std)
        run_result.metrics["wfa_confidence_score"] = confidence
        run_result.metrics["anti_overfit_score"] = float(anti_overfit_score)
        run_result.meta["walk_forward"] = summary.to_dict()

        verdict = "✅ robuste" if summary.is_robust else "⚠️ overfitting probable"
        return run_result, summary, (
            f"WFA {verdict} | folds={summary.n_valid_folds} | "
            f"test_sharpe={summary.avg_test_sharpe:.2f} | "
            f"ratio={summary.avg_overfitting_ratio:.2f} | "
            f"dégradation={summary.degradation_pct:.1f}% | "
            f"anti_overfit={anti_overfit_score:.2f}"
        )

    if not run_button and optimization_mode == BUILDER_OPTIMIZATION_MODE:
        from ui.builder_view import (
            restore_builder_autonomous_ui_state_from_runtime,
            should_auto_resume_builder_autonomous,
        )

        resume_autonomous, _runtime_state = should_auto_resume_builder_autonomous(state)
        runtime_pid = int((_runtime_state or {}).get("pid") or 0)
        same_process_runtime_active = (
            bool(st.session_state.get("is_running"))
            and runtime_pid > 0
            and runtime_pid == os.getpid()
        )
        if resume_autonomous and not same_process_runtime_active:
            if not bool(getattr(state, "builder_autonomous", False)):
                restore_builder_autonomous_ui_state_from_runtime()
                try:
                    state.builder_autonomous = True
                except Exception:
                    logging.getLogger(__name__).warning("failed to set builder_autonomous on state", exc_info=True)
            run_button = True
            mark_ui_run_started(st.session_state)
            st.session_state["builder_autonomous"] = True

    if (
        not run_button
        and optimization_mode == BUILDER_OPTIMIZATION_MODE
        and bool(st.session_state.get("builder_launch_pending", False))
        and bool(st.session_state.get("is_running", False))
    ):
        run_button = True

    if run_button:
        mark_ui_run_started(st.session_state)

        if optimization_mode != BUILDER_OPTIMIZATION_MODE:
            is_valid, errors = validate_all_params(params)

            if not is_valid:
                _abort_main_run(
                    status_container, "Paramètres invalides",
                    extra=lambda: [st.error(f"  • {e}") for e in errors],
                )

        is_multi_sweep = (len(state.symbols) > 1 or len(state.timeframes) > 1)
        if is_multi_sweep and optimization_mode in ("Backtest Simple", "Grille de Paramètres"):
            sweep_plan = _build_multi_sweep_plan(state.symbols, state.timeframes)
            total_sweeps = len(sweep_plan)
            st.session_state["multi_sweep_plan"] = sweep_plan

            st.info(
                f"🔄 **Mode multi-sweep séquentiel**\n\n"
                f"- {len(state.symbols)} token(s)\n"
                f"- {len(state.timeframes)} timeframe(s)\n"
                f"- {total_sweeps} sweep(s) au total\n\n"
                "Exécution **un par un** pour éviter la saturation mémoire."
            )

            with st.expander("📋 Plan des sweeps", expanded=False):
                plan_df = pd.DataFrame(
                    [{"symbol": sym, "timeframe": tf} for sym, tf in sweep_plan]
                )
                st.dataframe(plan_df, width="stretch")

            n_workers_effective = 1  # default; overridden for grid mode
            if optimization_mode == "Grille de Paramètres":
                n_workers_effective = _resolve_workers(n_workers)
                try:
                    worker_thread_limit = int(
                        st.session_state.get(
                            "grid_worker_threads",
                            int(os.environ.get("BACKTEST_WORKER_THREADS", "1")),
                        )
                    )
                except (TypeError, ValueError):
                    worker_thread_limit = 1
                worker_thread_limit = _resolve_threads(worker_thread_limit)
                _apply_thread_limit(worker_thread_limit, label="main")
                max_runs_per_sweep = None
            else:
                max_runs_per_sweep = None

            overall_progress = st.progress(0.0)
            status_placeholder = st.empty()
            sweep_results: List[Dict[str, Any]] = []
            logger = logging.getLogger(__name__)

            start_str = None
            end_str = None
            if state.use_date_filter and state.start_date and state.end_date:
                start_str = state.start_date.strftime("%Y-%m-%d")
                end_str = state.end_date.strftime("%Y-%m-%d")

            for idx, (sym, tf) in enumerate(sweep_plan, start=1):
                if st.session_state.get("stop_requested", False):
                    st.warning("🛑 Arrêt demandé par l'utilisateur")
                    break

                status_placeholder.info(
                    f"⏳ Sweep {idx}/{total_sweeps}: {strategy_key} × {sym} × {tf}"
                )

                df, msg = safe_load_data(sym, tf, start=start_str, end=end_str)
                if df is None:
                    sweep_results.append({
                        "strategy": strategy_key,
                        "symbol": sym,
                        "timeframe": tf,
                        "status": "error",
                        "error": msg,
                    })
                    overall_progress.progress(idx / total_sweeps)
                    continue

                df, _ = _prepare_market_df(
                    df,
                    symbol_value=sym,
                    timeframe_value=tf,
                    show_ui=False,
                )

                combo_engine = BacktestEngine(initial_capital=state.initial_capital)  # type: ignore[misc]

                if optimization_mode == "Backtest Simple":
                    result, result_msg = safe_run_backtest(
                        combo_engine,
                        df,
                        strategy_key,
                        params,
                        sym,
                        tf,
                        silent_mode=not debug_enabled,
                    )

                    if result is None:
                        sweep_results.append({
                            "strategy": strategy_key,
                            "symbol": sym,
                            "timeframe": tf,
                            "status": "error",
                            "error": result_msg,
                        })
                    else:
                        sweep_results.append({
                            "strategy": strategy_key,
                            "symbol": sym,
                            "timeframe": tf,
                            "status": "ok",
                            "best_params": result.meta.get("params", params),
                            "metrics": result.metrics or {},
                        })
                        _maybe_auto_save_run(result)
                else:
                    progress_placeholder = st.empty()
                    stats_placeholder = st.empty()
                    if n_workers_effective > 1 and max_runs_per_sweep != 1:
                        sweep_summary = _run_grid_parallel_basic(
                            df=df,
                            strategy_key=strategy_key,
                            symbol=sym,
                            timeframe=tf,
                            params=params,
                            param_ranges=param_ranges,
                            max_runs=max_runs_per_sweep,
                            initial_capital=state.initial_capital,
                            n_workers=n_workers_effective,
                            worker_thread_limit=worker_thread_limit,
                            debug_enabled=debug_enabled,
                            progress_placeholder=progress_placeholder,
                            stats_placeholder=stats_placeholder,
                        )
                    else:
                        sweep_summary = _run_grid_sequential(
                            df=df,
                            engine=combo_engine,
                            strategy_key=strategy_key,
                            symbol=sym,
                            timeframe=tf,
                            params=params,
                            param_ranges=param_ranges,
                            max_runs=max_runs_per_sweep,
                            debug_enabled=debug_enabled,
                            progress_placeholder=progress_placeholder,
                        )
                    progress_placeholder.empty()
                    stats_placeholder.empty()

                    sweep_results.append({
                        "strategy": strategy_key,
                        "symbol": sym,
                        "timeframe": tf,
                        "status": "ok",
                        "best_params": sweep_summary.get("best_params", {}),
                        "metrics": sweep_summary.get("best_metrics", {}),
                        "completed": sweep_summary.get("completed", 0),
                        "failed": sweep_summary.get("failed", 0),
                        "total_runs": sweep_summary.get("total_runs", 0),
                    })

                # Nettoyage mémoire entre sweeps
                try:
                    del df
                except Exception:
                    pass
                clear_data_cache()
                safe_copy_cleanup(logger)
                gc.collect()

                overall_progress.progress(idx / total_sweeps)

            status_placeholder.empty()
            st.session_state["multi_sweep_results"] = sweep_results

            if sweep_results:
                summary_rows = []
                for item in sweep_results:
                    metrics = item.get("metrics", {}) or {}
                    summary_rows.append({
                        "strategy": item.get("strategy"),
                        "symbol": item.get("symbol"),
                        "timeframe": item.get("timeframe"),
                        "status": item.get("status"),
                        "total_pnl": metrics.get("total_pnl", 0.0),
                        "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
                        "max_drawdown": metrics.get("max_drawdown_pct", metrics.get("max_drawdown", 0.0)),
                        "win_rate": metrics.get("win_rate_pct", metrics.get("win_rate", 0.0)),
                        "total_runs": item.get("total_runs"),
                        "completed": item.get("completed"),
                        "failed": item.get("failed"),
                        "error": item.get("error"),
                    })

                results_df = pd.DataFrame(summary_rows)
                st.markdown("### ✅ Résumé Multi-Sweep")
                st.dataframe(results_df, width="stretch")

                ok_df = results_df[results_df["status"] == "ok"].copy()
                if not ok_df.empty:
                    best_row = ok_df.loc[ok_df["total_pnl"].idxmax()]
                    st.success(
                        f"🏆 Meilleur résultat: {best_row['symbol']} {best_row['timeframe']} "
                        f"| PnL ${best_row['total_pnl']:,.2f} | Sharpe {best_row['sharpe_ratio']:.2f}"
                    )

                    tab_table, tab_heatmap, tab_rank = st.tabs(
                        ["📊 Tableau", "🔥 Heatmap", "🏆 Classement"]
                    )
                    with tab_table:
                        st.dataframe(ok_df, width="stretch")
                    with tab_heatmap:
                        render_multi_sweep_heatmap(ok_df, metric="total_pnl")
                    with tab_rank:
                        render_multi_sweep_ranking(ok_df, metric="total_pnl", top_n=min(15, len(ok_df)))
                else:
                    st.warning("Aucun sweep réussi.")

            clear_execution_state(st.session_state)
            return

        if optimization_mode == BUILDER_OPTIMIZATION_MODE:
            from ui.builder_view import (
                should_auto_resume_builder_autonomous,
            )

            resume_autonomous, _runtime_state = should_auto_resume_builder_autonomous(state)
            if resume_autonomous and not st.session_state.get("is_running", False):
                mark_ui_run_started(st.session_state)

            st.session_state.pop("builder_launch_pending", None)
            _render_builder_view_safe(
                state=state,
                df=st.session_state.get("ohlcv_df"),
                status_container=status_container,
            )
            return

        with st.spinner("📥 Chargement des données..."):
            df = st.session_state.get("ohlcv_df")
            data_msg = st.session_state.get("ohlcv_status_msg", "")

            if df is None:
                df, data_msg = load_selected_data(
                    symbol,
                    timeframe,
                    state.start_date,
                    state.end_date,
                )

            if df is None:
                data_dir_hint = None
                try:
                    from data.loader import _get_data_dir

                    data_dir_hint = str(_get_data_dir())
                except Exception:
                    data_dir_hint = None
                _data_hint = data_dir_hint
                _abort_main_run(
                    status_container, f"Échec chargement: {data_msg}",
                    extra=lambda: st.info(
                        f"💡 Vérifiez les fichiers dans `{_data_hint}`"
                        if _data_hint
                        else "💡 Vérifiez la configuration de vos chemins de données."
                    ),
                )

            if df is not None:
                df, stabilization_info = _prepare_market_df(
                    df,
                    symbol_value=symbol,
                    timeframe_value=timeframe,
                )
                with status_container:
                    show_status("success", f"Données chargées: {data_msg}")
                    if stabilization_info is not None:
                        show_status(
                            "info",
                            (
                                f"Stabilisation auto appliquée: "
                                f"-{stabilization_info.get('cut_bars', 0)} barres "
                                f"(départ {stabilization_info.get('start_ts', 'n/a')})"
                            ),
                        )

        engine = BacktestEngine(initial_capital=state.initial_capital)  # type: ignore[misc]

        if optimization_mode == "Backtest Simple":
            with st.spinner("⚙️ Exécution du backtest..."):
                result, result_msg = safe_run_backtest(
                    engine,
                    df,
                    strategy_key,
                    params,
                    symbol,
                    timeframe,
                    silent_mode=not debug_enabled,
                )

            if result is None:
                _abort_main_run(status_container, f"Échec backtest: {result_msg}")

            with status_container:
                show_status("success", f"Backtest terminé: {result_msg}")
            _finalize_run_result(
                result, df, result.meta.get("params", params), "backtest",
                attach_wfa=_attach_wfa_metrics, status_container=status_container,
            )

        elif optimization_mode == "Grille de Paramètres":
            _run_grid_search_mode(
                df=df, engine=engine, state=state,
                status_container=status_container,
                strategy_key=strategy_key, params=params,
                param_ranges=param_ranges,
                symbol=symbol, timeframe=timeframe,
                debug_enabled=debug_enabled,
                n_workers=n_workers, max_combos=max_combos,
                resolve_workers=_resolve_workers,
                resolve_threads=_resolve_threads,
                format_combo_limit=_format_combo_limit,
                attach_wfa_metrics=_attach_wfa_metrics,
            )

        elif optimization_mode == "🤖 Optimisation LLM":
            _run_llm_optimization_mode(
                df=df, engine=engine, state=state,
                status_container=status_container,
                strategy_key=strategy_key, params=params,
                symbol=symbol, timeframe=timeframe,
                debug_enabled=debug_enabled,
                n_workers=n_workers, max_combos=max_combos,
                llm_config=llm_config, llm_model=llm_model,
                llm_max_iterations=llm_max_iterations,
                llm_use_multi_agent=llm_use_multi_agent,
                llm_use_walk_forward=llm_use_walk_forward,
                llm_unload_during_backtest=llm_unload_during_backtest,
                llm_compare_enabled=llm_compare_enabled,
                llm_compare_auto_run=llm_compare_auto_run,
                llm_compare_strategies=llm_compare_strategies,
                llm_compare_tokens=llm_compare_tokens,
                llm_compare_timeframes=llm_compare_timeframes,
                llm_compare_metric=llm_compare_metric,
                llm_compare_aggregate=llm_compare_aggregate,
                llm_compare_max_runs=llm_compare_max_runs,
                llm_compare_use_preset=llm_compare_use_preset,
                llm_compare_generate_report=llm_compare_generate_report,
                resolve_workers=_resolve_workers,
                format_combo_limit=_format_combo_limit,
                prepare_market_df=_prepare_market_df,
                attach_wfa_metrics=_attach_wfa_metrics,
            )

        elif optimization_mode == BUILDER_OPTIMIZATION_MODE:
            _render_builder_view_safe(
                state=state,
                df=df,
                status_container=status_container,
            )

        else:
            _abort_main_run(status_container, f"Mode non reconnu: {optimization_mode}")

    clear_execution_state(st.session_state)
