from __future__ import annotations

# ruff: noqa: ARG001, I001, SLF001, PLW0108
# pylint: disable=protected-access,unused-argument,redefined-outer-name,unused-import,unnecessary-lambda

import json
import os
import sys
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import agents.llm_client as llm_client_module
import agents.model_config as model_config_module
import agents.ollama_manager as ollama_manager_module
import backtest.worker as worker_module
import ui.app as app_module
import ui.builder_view as builder_view_module
import ui.components.agent_timeline as agent_timeline_module
import ui.components.model_selector as model_selector_module
import ui.components.monitor as monitor_module
import ui.components.sweep_monitor as sweep_monitor_module
import ui.components.validation_viewer as validation_viewer_module
import ui.emergency_stop as emergency_stop_module
import ui.exec_tabs as exec_tabs_module
import ui.helpers as helpers_module
import ui.main as main_module
import ui.results_hub as results_hub_module
import ui.results_store_view as results_store_view_module
import ui.sidebar as sidebar_module
import utils.model_loader as model_loader_module
from agents.llm_router import build_phase1_topology, build_single_host_topology
from backtest.engine import BacktestEngine
from backtest.worker import init_worker_with_dataframe, run_backtest_worker
from ui.builder_view import (
    _choose_autonomous_objective_mode,
    _classify_autonomous_failure_origin,
    _find_first_valid_builder_market,
    _format_builder_live_event_line,
    _get_autonomous_recap_status_badge,
    _get_builder_code_provenance_badge,
    _has_builder_market_df,
    _history_best_sharpe,
    _pick_market_for_objective,
    _plan_autonomous_recovery,
    _resolve_requested_model,
    _sanitize_builder_stream_text,
    _select_autonomous_market_for_session,
)
from ui.components.strategy_catalog_panel import _catalog_postfilter_fields
from ui.exec_tabs import _get_phase1_topology_from_session, _prime_multiselect_state
from ui.helpers import (
    _build_saved_run_label,
    compute_period_days,
    format_pnl_with_daily,
    get_partial_result_notice,
    mark_result_as_partial,
    safe_run_backtest,
)
from ui.main import (
    _build_multi_sweep_grid_entry,
    _build_param_combo_iter,
    _describe_grid_completion,
    _run_grid_sequential,
    render_main,
)
from ui.results_hub import (
    _add_pnl_per_day,
    _build_candidate_preview_df,
    _build_candidate_report_summary,
    _catalog_entry_has_replay_source,
    _catalog_entry_source_ref,
    _build_phase_focus_preview_df,
    _build_phase_rejection_breakdown,
    _build_catalog_replay_request,
    _build_phase_timeline_html,
    _build_p3_diagnostic_summary,
    _build_p3_rejection_breakdown,
    _build_p3_required_benchmark_breakdown,
    _build_return_chart,
    _build_sharpe_drawdown_chart,
    _build_run_row_replay_request,
    _extract_catalog_postfilter_fields,
    _format_p3_zero_survivor_message,
    _get_numeric_column_config,
    _graduation_cli_command,
    _normalize_backtest_overview_df,
    _normalize_graduation_candidate_df,
    _payload_cli_equivalent,
    _payload_config_snapshot,
    _payload_phase_contract,
    _pick_latest_from_catalogs,
    _report_has_source_validation_fields,
    _resolve_candidate_phase_filter,
    _resolve_candidate_phase_focus_default,
    _safe_read_csv,
)
from ui.sidebar import _apply_catalog_replay_request_to_state, _apply_config_guard, _resolve_default_cpu_workers
from ui.state import (
    BUILDER_EXECUTION_MODE_MONO,
    UI_EXECUTION_PHASE_IDLE,
    UI_EXECUTION_PHASE_LAUNCH_PENDING,
    UI_EXECUTION_PHASE_RUNNING,
    UI_EXECUTION_PHASE_STOPPING,
    SidebarState,
    arm_ui_run_request,
    clear_execution_state,
    consume_ui_run_request,
    ensure_ui_execution_state_defaults,
    get_ui_execution_phase,
    mark_ui_run_started,
    mark_ui_stop_requested,
    resolve_builder_execution_preferences,
    resolve_builder_flow_analysis_preferences,
    resolve_builder_runtime_preferences,
)

builder_view_module = cast(Any, builder_view_module)
exec_tabs_module = cast(Any, exec_tabs_module)
model_selector_module = cast(Any, model_selector_module)
ollama_manager_module = cast(Any, ollama_manager_module)
results_hub_module = cast(Any, results_hub_module)
sidebar_module = cast(Any, sidebar_module)
sweep_monitor_module = cast(Any, sweep_monitor_module)


def _sample_ohlcv(n_bars: int = 400, freq: str = "1h", sigma: float = 0.8) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    index = pd.date_range("2025-01-01", periods=n_bars, freq=freq, tz="UTC")
    close = 100 + np.cumsum(rng.normal(0.0, sigma, n_bars))
    open_ = close + rng.normal(0.0, max(0.1, sigma * 0.25), n_bars)
    high = np.maximum(open_, close) + max(0.5, sigma)
    low = np.minimum(open_, close) - max(0.5, sigma)
    volume_low = 2_000 if sigma >= 1.0 else 1_000
    volume_high = 8_000 if sigma >= 1.0 else 5_000
    volume = rng.integers(volume_low, volume_high, n_bars)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=index,
    )


class _CaptionStub:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def caption(self, text: str) -> None:
        self.messages.append(text)


def _sample_sidebar_state(**overrides) -> SidebarState:
    payload = {
        "debug_enabled": False,
        "symbol": "",
        "timeframe": "",
        "use_date_filter": False,
        "start_date": None,
        "end_date": None,
        "available_tokens": ["BTCUSDT"],
        "available_timeframes": ["1h"],
        "strategy_key": "",
        "strategy_name": "",
        "strategy_info": None,
        "strategy_instance": None,
        "params": {},
        "param_ranges": {},
        "param_specs": {},
        "active_indicators": [],
        "optimization_mode": "Grille de Paramètres",
        "max_combos": 1,
        "n_workers": 1,
        "auto_stabilization_enabled": False,
        "stabilization_method": "combined",
        "stabilization_window": 20,
        "stabilization_volume_ratio_max": 3.0,
        "stabilization_volatility_ratio_max": 2.5,
        "stabilization_min_consecutive_bars": 3,
        "stabilization_min_bars_keep": 100,
        "symbols": [],
        "timeframes": [],
        "strategy_keys": [],
        "all_params": {},
        "all_param_ranges": {},
        "all_param_specs": {},
        "use_optuna": False,
        "optuna_n_trials": 0,
        "optuna_sampler": "tpe",
        "optuna_pruning": False,
        "optuna_metric": "sharpe_ratio",
        "optuna_early_stop": 0,
        "llm_config": None,
        "llm_model": None,
        "llm_use_multi_agent": False,
        "role_model_config": None,
        "llm_routing_mode": "single_endpoint",
        "llm_topology_config": None,
        "llm_max_iterations": 0,
        "llm_use_walk_forward": False,
        "llm_unload_during_backtest": False,
        "llm_compare_enabled": False,
        "llm_compare_auto_run": False,
        "llm_compare_strategies": [],
        "llm_compare_tokens": [],
        "llm_compare_timeframes": [],
        "llm_compare_metric": "sharpe_ratio",
        "llm_compare_aggregate": "median",
        "llm_compare_max_runs": 0,
        "llm_compare_use_preset": False,
        "llm_compare_generate_report": False,
        "llm_inference_mode": "global",
        "llm_inference_global_settings": {
            "temperature": 0.7,
            "max_tokens": 2000,
            "num_ctx": None,
        },
        "llm_inference_model_profiles": {},
        "initial_capital": 10_000.0,
        "leverage": 1.0,
        "leverage_enabled": False,
        "disabled_params": [],
        "use_walk_forward": False,
        "wfa_n_folds": 3,
        "wfa_train_ratio": 0.7,
        "wfa_expanding": False,
        "builder_objective": "",
        "builder_model_single_llm": "deepseek-r1:32b",
        "builder_max_iterations": 10,
        "builder_target_sharpe": 1.0,
        "builder_capital": 10_000.0,
        "builder_ollama_host": "http://127.0.0.1:11434",
        "builder_preload_model": True,
        "builder_keep_alive_minutes": 20,
        "builder_unload_after_run": False,
        "builder_auto_start_ollama": True,
        "builder_auto_market_pick": True,
        "builder_universe_mode": "canonical",
        "builder_autonomous": False,
        "builder_auto_pause": 10,
        "builder_auto_use_llm": True,
        "builder_execution_mode": BUILDER_EXECUTION_MODE_MONO,
        "builder_flow_analysis_enabled": False,
        "builder_flow_analysis_ablation": {},
        "builder_use_parametric_catalog": False,
    }
    payload.update(overrides)
    return SidebarState(**payload)


def _patch_autonomous_builder_shell(monkeypatch) -> None:
    monkeypatch.setattr(builder_view_module, "_inject_builder_view_styles", lambda: None)
    monkeypatch.setattr(
        builder_view_module,
        "_render_builder_mode_hero",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        builder_view_module,
        "_render_builder_runtime_notes",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        builder_view_module,
        "_render_builder_live_thoughts_panel",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        builder_view_module,
        "_render_autonomous_recap",
        lambda history, supervisor: None,
    )
    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_supervisor_state",
        lambda: {"history": [], "supervisor": {}},
    )
    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_runtime_state",
        dict,
    )
    monkeypatch.setattr(
        builder_view_module,
        "_save_autonomous_supervisor_state",
        lambda history, supervisor: None,
    )
    monkeypatch.setattr(
        builder_view_module,
        "_mark_builder_autonomous_runtime_started",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        builder_view_module,
        "_heartbeat_builder_autonomous_runtime",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        builder_view_module,
        "mark_builder_autonomous_runtime_stopped",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        builder_view_module,
        "_resolve_single_llm_runtime_route",
        lambda ollama_host, topology: (str(ollama_host), "GPU-0"),
    )
    monkeypatch.setattr(
        builder_view_module,
        "create_llm_client",
        lambda config: SimpleNamespace(config=config),
    )
    monkeypatch.setattr(
        builder_view_module,
        "generate_llm_objective",
        lambda *args, **kwargs: "Construire une stratégie robuste",
    )
    monkeypatch.setattr(
        builder_view_module,
        "_validate_builder_market_dataset",
        lambda **kwargs: (True, ""),
    )
    monkeypatch.setattr(builder_view_module, "show_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "error", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda *args, **kwargs: None)


def test_build_param_combo_iter_applies_max_runs_limit():
    combo_iter, total_runs, total_combinations = _build_param_combo_iter(
        params={"fees_bps": 10},
        param_ranges={
            "fast_period": {"min": 5, "max": 10, "step": 1},
            "slow_period": {"values": [20, 30, 40]},
        },
        max_runs=5,
    )

    combos = list(combo_iter)

    assert total_combinations == 18
    assert total_runs == 5
    assert len(combos) == 5


def test_resolve_default_cpu_workers_ignores_gpu_fallback(monkeypatch):
    monkeypatch.delenv("BACKTEST_MAX_WORKERS", raising=False)
    monkeypatch.delenv("BACKTEST_WORKERS_CPU_OPTIMIZED", raising=False)
    monkeypatch.setenv("BACKTEST_WORKERS_GPU_OPTIMIZED", "32")
    monkeypatch.setattr("ui.sidebar.get_recommended_worker_count", lambda max_cap=32: 12)

    assert _resolve_default_cpu_workers(max_cap=32) == 12


def test_apply_config_guard_auto_applies_mode_switch():
    st.session_state.clear()

    initial_state = _sample_sidebar_state(optimization_mode="Grille de Paramètres")
    _apply_config_guard(initial_state)

    builder_state = _sample_sidebar_state(optimization_mode="🏗️ Strategy Builder")
    applied_state = _apply_config_guard(builder_state)

    assert applied_state.optimization_mode == "🏗️ Strategy Builder"
    assert st.session_state["config_pending_changes"] is False


def test_prime_multiselect_state_initializes_without_default_widget_arg():
    st.session_state.clear()

    _prime_multiselect_state(
        "analyst_models",
        desired=["[M] qwen2.5:14b"],
        options=["[M] qwen2.5:14b", "[L] mistral:7b-instruct"],
    )

    assert st.session_state["analyst_models"] == ["[M] qwen2.5:14b"]


def test_get_huggingface_archive_root_prefers_usable_candidate(monkeypatch, tmp_path):
    monkeypatch.delenv("HUGGINGFACE_ARCHIVE_ROOT", raising=False)
    usable_root = tmp_path / "C" / "AI" / "models" / "library" / "huggingface"
    usable_root.parent.mkdir(parents=True)
    missing_root = Path(r"\\hf-missing-host\missing-share\models")

    monkeypatch.setattr(model_loader_module, "CURRENT_HUGGINGFACE_ARCHIVE_ROOT", missing_root)
    monkeypatch.setattr(model_loader_module, "DEFAULT_HUGGINGFACE_ARCHIVE_ROOTS", (missing_root, usable_root))
    monkeypatch.setattr(model_loader_module, "LEGACY_HUGGINGFACE_ARCHIVE_ROOTS", ())

    assert model_loader_module.get_huggingface_archive_root() == usable_root


def test_preferred_search_roots_include_huggingface_archive_root(monkeypatch, tmp_path):
    hf_root = tmp_path / "library" / "huggingface"
    ollama_root = tmp_path / "ollama"
    models_json_path = tmp_path / "catalog" / "models.json"

    monkeypatch.setattr(
        model_discovery_module,
        "get_preferred_local_model_search_roots",
        lambda extra_roots=None: [ollama_root, hf_root, models_json_path.parent],
    )

    roots = model_discovery_module._preferred_search_roots()

    assert hf_root in roots


def test_discover_local_models_supports_nested_huggingface_repo_dirs(monkeypatch, tmp_path):
    hf_root = tmp_path / "library" / "huggingface"
    repo_dir = hf_root / "NeoQuasar" / "Kronos-small"
    repo_dir.mkdir(parents=True)
    (repo_dir / "config.json").write_text("{}", encoding="utf-8")
    models_json_path = tmp_path / "catalog" / "models.json"

    monkeypatch.setattr(model_discovery_module, "get_ollama_models_root", lambda: tmp_path / "ollama")
    monkeypatch.setattr(model_discovery_module, "get_huggingface_archive_root", lambda: hf_root)
    monkeypatch.setattr(model_discovery_module, "get_model_library_roots", lambda: [])
    monkeypatch.setattr(model_discovery_module, "get_models_json_path", lambda: models_json_path)
    monkeypatch.setattr(
        model_discovery_module,
        "load_models_json",
        lambda force_reload=True: {"ollama_models": [], "cloud_models": [], "huggingface_models": []},
    )

    inventory = model_discovery_module.discover_local_models(include_live_ollama=False)

    assert any(
        model.name == "NeoQuasar/Kronos-small" and model.backend == "huggingface"
        for model in inventory.discovered_models
    )


def test_render_model_selector_reports_verified_non_ollama_models(monkeypatch):
    st.session_state.clear()
    captions: list[str] = []

    monkeypatch.setattr(model_selector_module, "_get_installed_ollama_models", lambda ollama_host=None: ["gemma4:26b"])
    monkeypatch.setattr(
        model_selector_module,
        "get_available_models_for_ui",
        lambda **kwargs: ["gemma4:26b"],
    )
    monkeypatch.setattr(
        model_selector_module,
        "_get_local_non_ollama_inventory_models",
        lambda ollama_host=None: [{"name": "NeoQuasar/Kronos-small", "backend": "huggingface"}],
    )
    monkeypatch.setattr(
        model_selector_module,
        "get_model_details",
        lambda model_name, ollama_host=None: {
            "display_name": model_name,
            "size_gb": 1.0,
            "parameters": "1B",
            "fits_gpu": True,
        },
    )
    monkeypatch.setattr(
        st,
        "selectbox",
        lambda label, options, key=None, help=None, format_func=None: options[0],
    )
    monkeypatch.setattr(st, "caption", lambda message: captions.append(str(message)))

    selected = model_selector_module.render_model_selector(
        key="builder_model_selector_test",
        compact=True,
        show_details=False,
    )

    assert selected == "gemma4:26b"
    assert any("NeoQuasar/Kronos-small" in message for message in captions)


def test_render_main_skips_forced_market_load_for_builder(monkeypatch):
    st.session_state.clear()
    st.session_state["ohlcv_df"] = None
    st.session_state["ohlcv_status_msg"] = ""

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_objective="Construire une strategie momentum robuste.",
    )
    captured: dict[str, object] = {}

    def _fail_load(*args, **kwargs):
        raise AssertionError("load_selected_data ne doit pas etre appele en mode Builder")

    monkeypatch.setattr(main_module, "load_selected_data", _fail_load)
    monkeypatch.setattr(main_module, "validate_all_params", lambda params: (True, []))
    monkeypatch.setattr(main_module, "show_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "ui.builder_view.render_builder_view",
        lambda state, df, status_container: captured.update(
            {"mode": state.optimization_mode, "df": df},
        ),
    )

    render_main(state, True, nullcontext())

    assert captured["mode"] == "🏗️ Strategy Builder"
    assert captured["df"] is None


def test_compute_period_days_handles_mixed_naive_and_utc_inputs():
    period_days = compute_period_days(
        "2025-01-01",
        pd.Timestamp("2025-01-31T00:00:00Z"),
    )

    assert period_days == 30


def test_format_pnl_with_daily_accepts_string_pnl():
    formatted = format_pnl_with_daily("123.5", 5)

    assert formatted == "$123.50 ($24.70/jour)"


def test_normalize_backtest_overview_df_aliases_prefixed_metrics():
    df = pd.DataFrame(
        [
            {
                "metrics_total_pnl": "123.5",
                "metrics_total_return_pct": "6.25",
                "metrics_benchmark_return_pct": "12.0",
                "metrics_alpha_simple_pct": "-5.75",
                "metrics_sharpe_ratio": "1.4",
                "metrics_max_drawdown_pct": "-9.5",
            },
        ],
    )

    normalized = _normalize_backtest_overview_df(df)

    assert normalized.loc[0, "total_pnl"] == 123.5
    assert normalized.loc[0, "total_return_pct"] == 6.25
    assert normalized.loc[0, "benchmark_return_pct"] == 12.0
    assert normalized.loc[0, "alpha_simple_pct"] == -5.75
    assert normalized.loc[0, "sharpe_ratio"] == 1.4
    assert normalized.loc[0, "max_drawdown_pct"] == -9.5


def test_results_hub_numeric_config_exposes_alpha_columns():
    config = _get_numeric_column_config()

    assert "benchmark_return_pct" in config
    assert "alpha_simple_pct" in config
    assert "metrics_benchmark_return_pct" in config
    assert "metrics_alpha_simple_pct" in config
    assert "strategy_name_link" in config


def test_results_hub_unified_table_merges_previous_table_sources():
    table_df = results_hub_module._build_results_hub_table_df(
        backtest_overview=pd.DataFrame(
            [
                {
                    "type": "run",
                    "id": "bt-1",
                    "run_id": "bt-run-1",
                    "strategy": "ema_cross",
                    "symbol": "BTCUSDC",
                    "timeframe": "1h",
                    "total_return_pct": 12.5,
                    "sharpe_ratio": 1.2,
                },
            ],
        ),
        unified_overview=pd.DataFrame(
            [
                {
                    "run_id": "saved-1",
                    "artifact_type": "run",
                    "strategy": "rsi_reversal",
                    "symbol": "ETHUSDC",
                    "timeframe": "4h",
                    "metrics_total_return_pct": 8.0,
                    "metrics_sharpe_ratio": 1.4,
                },
            ],
        ),
        runs_overview=pd.DataFrame([{"session_id": "llm-1", "mode": "builder", "total_llm_calls": 3}]),
        builder_sessions_df=pd.DataFrame([{"session_id": "sess-1", "status": "completed", "best_return_pct": 4.2}]),
        builder_iterations_df=pd.DataFrame(
            [{"session_id": "sess-1", "iteration": 2, "return_pct": 5.3, "sharpe": 0.9}],
        ),
        strategy_catalog_df=pd.DataFrame(
            [
                {
                    "entry_id": "cat-1",
                    "strategy": "ema_cross",
                    "symbol": "BTCUSDC",
                    "timeframe": "1h",
                    "category": "p3_benchmark_consensus",
                    "source_run_id": "saved-1",
                },
            ],
        ),
        graduation_df=pd.DataFrame(
            [{"strategy_name": "grad_a", "session_id": "grad-1", "phase": "P3", "best_return_pct": 7.5}],
        ),
        positive_import_df=pd.DataFrame(
            [{"strategy_name": "pos_a", "session_id": "pos-1", "phase": "P4", "best_return_pct": 9.5}],
        ),
    )

    assert set(table_df["hub_source"]) == {
        "Backtests / optimisations",
        "Stock unifié",
        "Runs LLM",
        "Builder sessions",
        "Builder iterations",
        "Strategy catalog",
        "Graduation sandbox",
        "Graduation positifs",
    }
    unified_row = table_df[table_df["_row_origin"] == "unified_overview"].iloc[0]
    assert bool(unified_row["promotable"]) is True
    assert bool(unified_row["replayable"]) is True
    assert unified_row["total_return_pct"] == 8.0
    catalog_row = table_df[table_df["_row_origin"] == "strategy_catalog"].iloc[0]
    assert bool(catalog_row["replayable"]) is True


def test_render_results_hub_uses_single_unified_table(monkeypatch):
    st.session_state.clear()

    class _HubColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def button(self, *args, **kwargs):
            return False

        def caption(self, *args, **kwargs):
            return None

        def metric(self, *args, **kwargs):
            return None

        def multiselect(self, _label, options, default=None, **_kwargs):
            return default or []

        def checkbox(self, _label, value=False, **_kwargs):
            return value

        def text_input(self, *args, **kwargs):
            return ""

    backtest_df = pd.DataFrame(
        [
            {
                "type": "run",
                "id": "run-1",
                "run_id": "run-1",
                "strategy": "ema_cross",
                "symbol": "BTCUSDC",
                "timeframe": "1h",
                "total_return_pct": 10.0,
                "sharpe_ratio": 1.1,
            },
        ],
    )
    unified_df = pd.DataFrame(
        [
            {
                "run_id": "saved-1",
                "artifact_type": "run",
                "strategy": "ema_cross",
                "symbol": "BTCUSDC",
                "timeframe": "1h",
                "metrics_total_return_pct": 10.0,
                "metrics_sharpe_ratio": 1.1,
            },
        ],
    )
    catalog_df = pd.DataFrame(
        [
            {
                "entry_id": "entry-1",
                "strategy": "ema_cross",
                "symbol": "BTCUSDC",
                "timeframe": "1h",
                "category": "p3_benchmark_consensus",
                "source_run_id": "saved-1",
            },
        ],
    )
    editor_calls: list[pd.DataFrame] = []

    monkeypatch.setattr(results_hub_module, "_load_catalogs", lambda refresh=False: (backtest_df, unified_df, pd.DataFrame()))
    monkeypatch.setattr(
        results_hub_module,
        "_load_builder_store_payload",
        lambda: (pd.DataFrame(), pd.DataFrame(), {}),
    )
    monkeypatch.setattr(results_hub_module, "_load_strategy_catalog_df", lambda: catalog_df)
    monkeypatch.setattr(results_hub_module, "_load_graduation_report", lambda: ({}, pd.DataFrame()))
    monkeypatch.setattr(results_hub_module, "_load_positive_import_report", lambda: ({}, pd.DataFrame()))
    monkeypatch.setattr(results_hub_module, "_render_latest_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module, "_render_charts", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module, "_render_progress_section", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module, "_load_progress_payload", lambda _filename: {})

    monkeypatch.setattr(results_hub_module.st, "header", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "subheader", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "error", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "rerun", lambda: None)
    monkeypatch.setattr(results_hub_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "expander", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(results_hub_module.st, "selectbox", lambda _label, options, index=0, **_kwargs: options[index])
    monkeypatch.setattr(results_hub_module.st, "columns", lambda spec: [_HubColumn() for _ in range(len(spec) if isinstance(spec, list) else spec)])
    monkeypatch.setattr(results_hub_module.st, "dataframe", lambda *args, **kwargs: pytest.fail("st.dataframe must not be used"))
    monkeypatch.setattr(results_hub_module.st, "tabs", lambda *args, **kwargs: pytest.fail("tabs must not be used"))

    def _data_editor(df, **kwargs):
        editor_calls.append(df.copy())
        return df

    monkeypatch.setattr(results_hub_module.st, "data_editor", _data_editor)

    results_hub_module.render_results_hub()

    assert len(editor_calls) == 1
    rendered_df = editor_calls[0]
    assert set(rendered_df["hub_source"]) == {
        "Backtests / optimisations",
        "Stock unifié",
        "Strategy catalog",
    }
    assert "select" in rendered_df.columns


def test_start_background_graduation_job_blocks_duplicate_active_progress(tmp_path: Path, monkeypatch):
    progress_dir = tmp_path / "catalog" / "graduation_results"
    progress_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    (progress_dir / results_hub_module.FULL_GRADUATION_PROGRESS_FILENAME).write_text(
        json.dumps(
            {
                "status": "running",
                "pid": os.getpid(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        ),
        encoding="utf-8",
    )

    ok, message = results_hub_module._start_background_graduation_job(
        args=["--full"],
        log_filename=results_hub_module.FULL_GRADUATION_LOG_FILENAME,
        progress_filename=results_hub_module.FULL_GRADUATION_PROGRESS_FILENAME,
    )

    assert ok is False
    assert "déjà actif" in message.lower()


class _GraduationControlColumn:
    def __init__(
        self,
        *,
        pressed_key: str | None = None,
        checkbox_values: dict[str, bool] | None = None,
    ) -> None:
        self._pressed_key = pressed_key
        self._checkbox_values = checkbox_values or {}

    def checkbox(self, _label, value=False, key=None, **_kwargs):
        if key is None:
            return value
        return self._checkbox_values.get(key, value)

    def button(self, _label, key=None, **_kwargs):
        return key == self._pressed_key


def _stub_graduation_tab_shell(monkeypatch, *, pressed_key: str | None, checkbox_values: dict[str, bool] | None = None):
    def _columns(spec):
        n = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        return [_GraduationControlColumn(pressed_key=pressed_key, checkbox_values=checkbox_values)] * n

    monkeypatch.setattr(results_hub_module.st, "columns", _columns)
    monkeypatch.setattr(results_hub_module.st, "tabs", lambda labels: [nullcontext() for _ in labels])
    monkeypatch.setattr(results_hub_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "error", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "rerun", lambda: None)
    monkeypatch.setattr(results_hub_module.st, "spinner", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(results_hub_module.st, "status", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(results_hub_module.st, "expander", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(results_hub_module.st, "progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module, "_load_graduation_report", lambda: ({}, pd.DataFrame()))
    monkeypatch.setattr(results_hub_module, "_load_positive_import_report", lambda: ({}, pd.DataFrame()))
    monkeypatch.setattr(results_hub_module, "_load_progress_payload", lambda _filename: {})


def _empty_graduation_kwargs() -> dict[str, Any]:
    return {
        "sandbox_payload": {},
        "sandbox_df": pd.DataFrame(),
        "positive_payload": {},
        "positive_df": pd.DataFrame(),
    }


def test_render_graduation_controls_launches_full_pipeline_in_background(monkeypatch):
    st.session_state.clear()

    _stub_graduation_tab_shell(monkeypatch, pressed_key="graduation_run_full")

    background_calls = []

    def _fake_start_background_graduation_job(**kwargs):
        background_calls.append(kwargs)
        return True, "Run lancé en arrière-plan"

    monkeypatch.setattr(
        results_hub_module,
        "_start_background_graduation_job",
        _fake_start_background_graduation_job,
    )

    results_hub_module._render_graduation_controls_and_progress(**_empty_graduation_kwargs())

    assert background_calls == [
        {
            "args": ["--full", "--sync-catalog"],
            "log_filename": results_hub_module.FULL_GRADUATION_LOG_FILENAME,
            "progress_filename": results_hub_module.FULL_GRADUATION_PROGRESS_FILENAME,
        },
    ]
    assert st.session_state["graduation_status_msg"] == "Run lancé en arrière-plan"
    assert st.session_state["graduation_status_error"] is False


def test_render_graduation_controls_passes_sandbox_report_to_progress_section(monkeypatch):
    st.session_state.clear()
    _stub_graduation_tab_shell(monkeypatch, pressed_key=None)

    sandbox_payload = {"phase": "FULL", "by_phase": {"P3": 1}, "stats": {"p1_candidates": 1}}
    sandbox_df = pd.DataFrame([{"phase": "P3", "decision": "REJECTED"}])
    progress_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        results_hub_module,
        "_load_progress_payload",
        lambda filename: {"status": "running", "stats": {"p1_candidates": 1}}
        if filename == results_hub_module.FULL_GRADUATION_PROGRESS_FILENAME
        else {},
    )
    monkeypatch.setattr(
        results_hub_module,
        "_render_progress_section",
        lambda **kwargs: progress_calls.append(kwargs),
    )

    results_hub_module._render_graduation_controls_and_progress(
        sandbox_payload=sandbox_payload,
        sandbox_df=sandbox_df,
        positive_payload={},
        positive_df=pd.DataFrame(),
    )

    sandbox_call = next(call for call in progress_calls if call["title"] == "Progression sandbox P1→P6")
    assert sandbox_call["report_payload"] is sandbox_payload
    assert sandbox_call["report_df"] is sandbox_df


def test_render_graduation_controls_and_progress_runs_scan_p1_with_canonical_save_args(monkeypatch):
    import catalog.graduation as graduation_module

    st.session_state.clear()
    st.session_state["graduation_status_error"] = True
    _stub_graduation_tab_shell(monkeypatch, pressed_key="graduation_run_p1")

    scan_calls = []
    sync_calls = []
    saved_reports = []

    monkeypatch.setattr(results_hub_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module, "_render_progress_section", lambda **kwargs: None)

    def _fake_scan(config):
        scan_calls.append(config)
        return [{"candidate_id": "cand-1"}]

    def _fake_sync(candidates, config):
        sync_calls.append((candidates, config))
        return [{"entry_id": "cat-1"}]

    def _fake_save(candidates, output_dir, *, phase="P1_repechage", filename=None, stats=None):
        saved_reports.append(
            {
                "candidates": candidates,
                "output_dir": output_dir,
                "phase": phase,
                "filename": filename,
                "stats": stats,
            },
        )

    monkeypatch.setattr(graduation_module, "scan_sandbox", _fake_scan)
    monkeypatch.setattr(graduation_module, "sync_graduation_to_catalog", _fake_sync)
    monkeypatch.setattr(graduation_module, "save_graduation_report", _fake_save)

    results_hub_module._render_graduation_controls_and_progress(
        sandbox_payload={},
        sandbox_df=pd.DataFrame(),
        positive_payload={},
        positive_df=pd.DataFrame(),
    )

    assert len(scan_calls) == 1
    assert scan_calls[0].sync_catalog is True
    assert sync_calls == [([{"candidate_id": "cand-1"}], scan_calls[0])]
    assert saved_reports == [
        {
            "candidates": [{"candidate_id": "cand-1"}],
            "output_dir": scan_calls[0].output_dir,
            "phase": "P1_repechage",
            "filename": "graduation_p1.json",
            "stats": {"catalog_synced": 1},
        },
    ]
    assert st.session_state["graduation_status_msg"] == "P1 terminé: 1 candidat(s), 1 sync catalogue"
    assert st.session_state["graduation_status_error"] is False


def test_render_graduation_controls_imports_positive_artifacts_with_selected_flags(monkeypatch):
    import catalog.graduation as graduation_module

    st.session_state.clear()
    st.session_state["graduation_status_error"] = True
    _stub_graduation_tab_shell(
        monkeypatch,
        pressed_key="graduation_import_positive_artifacts",
        checkbox_values={
            "graduation_sync_catalog": False,
            "graduation_include_legacy_roots": True,
        },
    )

    import_calls = []

    def _fake_import(config):
        import_calls.append(config)
        return {
            "stats": {
                "catalog_entries_touched": 7,
                "catalog_new_entries": 4,
            },
        }

    monkeypatch.setattr(graduation_module, "import_positive_artifacts_to_catalog", _fake_import)

    results_hub_module._render_graduation_controls_and_progress(**_empty_graduation_kwargs())

    assert len(import_calls) == 1
    assert import_calls[0].sync_catalog is False
    assert import_calls[0].include_legacy_artifact_roots is True
    assert st.session_state["graduation_status_msg"] == (
        "Import positifs terminé: 7 entrée(s), 4 nouvelles."
    )
    assert st.session_state["graduation_status_error"] is False


def test_render_graduation_controls_launches_positive_pipeline_in_background(monkeypatch):
    st.session_state.clear()
    _stub_graduation_tab_shell(monkeypatch, pressed_key="graduation_run_positive_imports")

    background_calls = []

    def _fake_start_background_graduation_job(**kwargs):
        background_calls.append(kwargs)
        return True, "Traitement positifs lancé"

    monkeypatch.setattr(
        results_hub_module,
        "_start_background_graduation_job",
        _fake_start_background_graduation_job,
    )

    results_hub_module._render_graduation_controls_and_progress(**_empty_graduation_kwargs())

    assert background_calls == [
        {
            "args": ["--positive-import-full", "--sync-catalog"],
            "log_filename": results_hub_module.POSITIVE_IMPORTS_LOG_FILENAME,
            "progress_filename": results_hub_module.POSITIVE_IMPORTS_PROGRESS_FILENAME,
        },
    ]
    assert st.session_state["graduation_status_msg"] == "Traitement positifs lancé"
    assert st.session_state["graduation_status_error"] is False


def test_render_progress_section_shows_live_progress_for_active_job(monkeypatch):
    status_calls: list[tuple[str, dict[str, Any]]] = []
    progress_calls: list[tuple[float, str | None]] = []
    metric_calls: list[tuple[str, str]] = []

    class _MetricStub:
        def metric(self, label, value, *args, **kwargs):
            metric_calls.append((str(label), str(value)))
            return None

    monkeypatch.setattr(results_hub_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "error", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "code", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        results_hub_module.st,
        "columns",
        lambda spec: [_MetricStub() for _ in range(spec if isinstance(spec, int) else len(spec))],
    )
    monkeypatch.setattr(results_hub_module.st, "expander", lambda *args, **kwargs: nullcontext())
    markdown_calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        results_hub_module.st,
        "markdown",
        lambda body, **kwargs: markdown_calls.append((str(body), dict(kwargs))),
    )
    monkeypatch.setattr(
        results_hub_module.st,
        "status",
        lambda label, **kwargs: (status_calls.append((label, dict(kwargs))), nullcontext())[1],
    )
    monkeypatch.setattr(
        results_hub_module.st,
        "progress",
        lambda value, text=None: progress_calls.append((float(value), text)),
    )
    monkeypatch.setattr(
        results_hub_module,
        "_load_log_tail",
        lambda filename, max_lines=25: "[graduation] filtering BTCUSDC 1h",
    )

    payload = {
        "status": "running",
        "current_phase": "P2",
        "current_index": 1172,
        "current_total": 1361,
        "updated_at": results_hub_module.datetime.now(results_hub_module.timezone.utc).isoformat(),
        "stats": {
            "p1_candidates": 1361,
            "p2_processed": 1172,
            "p2_survivors": 0,
        },
        "current_candidate": {
            "strategy_name": "momentum_macd_candidate",
            "source_symbol": "BTCUSDC",
            "source_timeframe": "1h",
        },
    }

    results_hub_module._render_progress_section(
        title="État du pipeline sandbox P1→P6",
        payload=payload,
        log_filename=results_hub_module.FULL_GRADUATION_LOG_FILENAME,
        report_payload={},
        report_df=pd.DataFrame(),
    )

    assert status_calls
    assert "Calculs en cours" in status_calls[0][0]
    assert progress_calls
    assert progress_calls[0][0] > 0.8
    assert "1172/1361" in str(progress_calls[0][1])
    assert any("bc-grad-timeline" in body for body, _kwargs in markdown_calls)
    assert ("Heartbeat", "0s") in metric_calls
    assert ("PID", "-") in metric_calls
    assert ("Phase", "P2") in metric_calls
    assert all(label != "Rafraîchissement" for label, _value in metric_calls)


def test_render_progress_section_no_longer_shows_auto_refresh_controls(monkeypatch):
    metric_calls: list[tuple[str, str]] = []

    class _MetricStub:
        def metric(self, label, value, *args, **kwargs):
            metric_calls.append((str(label), str(value)))
            return None

    monkeypatch.setattr(results_hub_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "error", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "code", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        results_hub_module.st,
        "columns",
        lambda spec: [_MetricStub() for _ in range(spec if isinstance(spec, int) else len(spec))],
    )
    monkeypatch.setattr(results_hub_module.st, "expander", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(results_hub_module.st, "status", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(results_hub_module.st, "progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module, "_load_log_tail", lambda *args, **kwargs: "live line")

    payload = {
        "status": "running",
        "current_phase": "P3",
        "current_index": 5,
        "current_total": 12,
        "updated_at": results_hub_module.datetime.now(results_hub_module.timezone.utc).isoformat(),
        "stats": {"p1_candidates": 12, "p3_processed": 5, "p3_survivors": 1},
        "current_candidate": {"strategy_name": "candidate"},
    }

    results_hub_module._render_progress_section(
        title="État du pipeline sandbox P1→P6",
        payload=payload,
        log_filename=results_hub_module.FULL_GRADUATION_LOG_FILENAME,
        report_payload={},
        report_df=pd.DataFrame(),
    )

    assert ("Heartbeat", "0s") in metric_calls
    assert ("PID", "-") in metric_calls
    assert ("Phase", "P3") in metric_calls
    assert all(label != "Rafraîchissement" for label, _value in metric_calls)


def test_render_progress_section_labels_stale_running_payload_without_heartbeat(monkeypatch):
    metric_calls: list[tuple[str, str]] = []

    class _MetricStub:
        def metric(self, label, value, *args, **kwargs):
            metric_calls.append((str(label), str(value)))
            return None

    monkeypatch.setattr(results_hub_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "error", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "code", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        results_hub_module.st,
        "columns",
        lambda spec: [_MetricStub() for _ in range(spec if isinstance(spec, int) else len(spec))],
    )
    monkeypatch.setattr(results_hub_module.st, "expander", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(results_hub_module.st, "status", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(results_hub_module.st, "progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module, "_load_log_tail", lambda *args, **kwargs: "")

    old_ts = (
        results_hub_module.datetime.now(results_hub_module.timezone.utc)
        - timedelta(minutes=12)
    ).isoformat()
    payload = {
        "status": "running",
        "current_phase": "P5",
        "current_index": 2,
        "current_total": 4,
        "updated_at": old_ts,
        "stats": {"p5_processed": 2, "p4_survivors": 4},
    }

    results_hub_module._render_progress_section(
        title="État du pipeline sandbox P1→P6",
        payload=payload,
        log_filename=results_hub_module.FULL_GRADUATION_LOG_FILENAME,
        report_payload={},
        report_df=pd.DataFrame(),
    )

    assert ("Statut", "sans heartbeat") in metric_calls


def test_build_phase_timeline_html_marks_active_and_completed_steps():
    html = _build_phase_timeline_html(current_phase="P4", status="running")

    assert "bc-grad-timeline" in html
    assert "P2" in html and "P6" in html
    assert "is-done" in html
    assert "is-active" in html
    assert "Test de sensibilité" in html


def test_pick_latest_from_catalogs_can_use_builder_sessions_disk_source():
    builder_df = pd.DataFrame(
        [
            {
                "session_id": "builder-session-1",
                "last_modified": "2026-04-17 12:34:56",
                "best_return_pct": 12.5,
                "best_sharpe": 1.42,
                "total_iterations": 7,
                "status": "max_iterations",
                "session_dir": "C:/tmp/builder-session-1",
            },
        ],
    )

    latest = _pick_latest_from_catalogs(pd.DataFrame(), pd.DataFrame(), builder_df)

    assert latest is not None
    assert latest["source"] == "builder_sessions"
    assert latest["id"] == "builder-session-1"
    assert latest["metrics"]["best_return_pct"] == 12.5
    assert latest["metrics"]["best_sharpe"] == 1.42
    assert latest["metrics"]["total_iterations"] == 7


def test_collect_builder_catalog_reconciliation_ignores_invalid_session_ids(tmp_path: Path):
    results_root = tmp_path / "results"
    builder_root = tmp_path / "builder"
    catalog_dir = results_root / "_catalog"
    catalog_dir.mkdir(parents=True)
    (builder_root / "session_a").mkdir(parents=True)
    (builder_root / "session_b").mkdir(parents=True)

    pd.DataFrame(
        [
            {"run_id": "run-1", "extra_builder_session_id": "session_a"},
            {"run_id": "run-2", "extra_builder_session_id": None},
            {"run_id": "run-3", "extra_builder_session_id": float("nan")},
            {"run_id": "run-4", "extra_builder_session_id": ""},
        ],
    ).to_csv(catalog_dir / "unified_overview.csv", index=False)

    audit = results_store_view_module.collect_builder_catalog_reconciliation(results_root, builder_root)

    assert audit["catalog_builder_session_count"] == 1
    assert audit["matched_session_count"] == 1
    assert audit["disk_only_session_count"] == 1
    assert audit["disk_only_sessions"] == ["session_b"]
    assert audit["catalog_only_session_count"] == 0


def test_normalize_graduation_candidate_df_derives_benchmark_matrix_columns():
    df = pd.DataFrame(
        [
            {
                "strategy_name": "ema_cross",
                "configured_contexts": ["BTCUSDC_1h", "ETHUSDC_1h", "BTCUSDC_4h"],
                "loaded_contexts": ["BTCUSDC_1h", "ETHUSDC_1h"],
                "missing_contexts": ["BTCUSDC_4h"],
                "tested_timeframes": ["1h", "4h"],
                "benchmark_results": {
                    "crypto_liquid_benchmark_v1_core": {
                        "tokens": ["BTCUSDC", "ETHUSDC"],
                        "timeframes": ["1h", "4h"],
                    },
                    "crypto_liquid_benchmark_v3_balanced": {
                        "tokens": ["BTCUSDC", "LINKUSDC"],
                        "timeframes": ["1h", "4h"],
                    },
                },
                "benchmark_consensus": {
                    "required_benchmark_name": "crypto_liquid_benchmark_v1_core",
                    "required_passed": True,
                    "benchmarks_passed": ["crypto_liquid_benchmark_v1_core"],
                    "benchmarks_total": 2,
                    "consensus_passed": False,
                    "contradicted": True,
                },
                "multi_ctx_results": {
                    "passed_count": 2,
                    "total_contexts": 3,
                    "eligible_context_count": 2,
                    "configured_context_count": 3,
                    "configured_benchmark_slots": 4,
                    "loaded_benchmark_slots": 3,
                    "excluded_context_count": 1,
                },
            },
        ],
    )

    normalized = _normalize_graduation_candidate_df(df)

    assert normalized.loc[0, "configured_context_count"] == 3
    assert normalized.loc[0, "loaded_context_count"] == 2
    assert normalized.loc[0, "missing_context_count"] == 1
    assert normalized.loc[0, "tested_benchmark_names"] == (
        "crypto_liquid_benchmark_v1_core,crypto_liquid_benchmark_v3_balanced"
    )
    assert normalized.loc[0, "tested_tokens"] == "BTCUSDC,ETHUSDC,LINKUSDC"
    assert normalized.loc[0, "timeframes_tested"] == "1h,4h"
    assert normalized.loc[0, "benchmark_pass_summary"] == "1/2"
    assert normalized.loc[0, "required_benchmark_name"] == "crypto_liquid_benchmark_v1_core"
    assert bool(normalized.loc[0, "required_benchmark_passed"]) is True
    assert normalized.loc[0, "contradiction_state"] == "contradicted"
    assert normalized.loc[0, "context_pass_summary"] == "2/3"
    assert normalized.loc[0, "eligible_context_count"] == 2
    assert normalized.loc[0, "configured_benchmark_slot_count"] == 4
    assert normalized.loc[0, "loaded_benchmark_slot_count"] == 3
    assert normalized.loc[0, "excluded_context_count"] == 1
    assert normalized.loc[0, "configured_unique_coverage_pct"] == pytest.approx(66.7, abs=0.1)


def test_normalize_graduation_candidate_df_keeps_source_validation_metrics_numeric():
    df = pd.DataFrame(
        [
            {
                "strategy_name": "eth_source",
                "source_symbol": "ETHUSDC",
                "source_timeframe": "1d",
                "sensitivity_scope": "source_market",
                "sensitivity_history_bars": "2616",
                "sensitivity_min_history_bars": "500",
                "wfa_scope": "source_market",
                "wfa_symbol": "ETHUSDC",
                "wfa_timeframe": "1d",
                "wfa_history_bars": "2616",
                "wfa_min_history_bars": "500",
                "wfa_valid_folds": "5",
                "wfa_positive_folds_pct": "80.0",
                "wfa_overfitting_ratio": "162.114",
            },
        ],
    )

    normalized = _normalize_graduation_candidate_df(df)

    assert _report_has_source_validation_fields(normalized) is True
    assert normalized.loc[0, "sensitivity_history_bars"] == 2616
    assert normalized.loc[0, "wfa_valid_folds"] == 5
    assert normalized.loc[0, "wfa_positive_folds_pct"] == pytest.approx(80.0)
    assert normalized.loc[0, "wfa_overfitting_ratio"] == pytest.approx(162.114)


def test_report_has_source_validation_fields_detects_legacy_graduation_report():
    legacy_df = pd.DataFrame([{"strategy_name": "old", "wfa_overfitting_ratio": 7.04}])

    assert _report_has_source_validation_fields(legacy_df) is False
    assert _report_has_source_validation_fields(pd.DataFrame()) is True


def test_graduation_payload_contract_helpers_read_progress_and_report_meta():
    report_payload = {
        "meta": {
            "cli_equivalent": "python -m catalog.graduation --full --sync-catalog",
            "phase_contract": {"P1": {"name": "Inventaire", "purpose": "scan"}},
            "config_snapshot": {"source_market_first": True},
        },
    }

    assert _graduation_cli_command(["--full", "--sync-catalog"]) == (
        "python -m catalog.graduation --full --sync-catalog"
    )
    assert _payload_cli_equivalent({}, report_payload) == "python -m catalog.graduation --full --sync-catalog"
    assert _payload_phase_contract(report_payload)["P1"]["name"] == "Inventaire"
    assert _payload_config_snapshot(report_payload)["source_market_first"] is True


def test_phase_processed_counts_do_not_infer_future_phases_for_live_progress():
    stats = {
        "p1_candidates": 2454,
        "p2_processed": 2454,
        "p2_survivors": 2195,
    }

    live_counts = results_hub_module._phase_processed_counts(stats, 2454, infer_missing=False)
    report_counts = results_hub_module._phase_processed_counts(stats, 2454)

    assert live_counts["P2"] == 2454
    assert live_counts["P3"] == 0
    assert live_counts["P4"] == 0
    assert report_counts["P3"] == 2195


def test_is_pid_running_accepts_current_process():
    assert results_hub_module._is_pid_running(os.getpid()) is True
    assert results_hub_module._is_pid_running(-1) is False


def test_build_p3_diagnostic_summary_distinguishes_eligible_vs_configured():
    payload = {
        "stats": {
            "p1_candidates": 5,
            "p2_processed": 5,
            "p2_survivors": 4,
            "p3_processed": 4,
            "p3_survivors": 0,
        },
    }
    df = pd.DataFrame(
        [
            {
                "configured_context_count": 6,
                "eligible_context_count": 4,
                "loaded_context_count": 4,
                "excluded_context_count": 2,
                "configured_benchmark_slot_count": 12,
                "loaded_benchmark_slot_count": 8,
                "coverage_pct": 100.0,
                "benchmark_slot_coverage_pct": 66.7,
                "phase": "P3",
                "decision": "REJECTED",
                "rejection_reason": "coverage=66.7<70.0",
            },
        ],
    )

    summary = _build_p3_diagnostic_summary(payload, df)

    assert summary["available"] is True
    assert summary["p3_processed"] == 4
    assert summary["p3_survivors"] == 0
    assert summary["configured_context_count"] == 6
    assert summary["eligible_context_count"] == 4
    assert summary["loaded_context_count"] == 4
    assert summary["excluded_context_count"] == 2
    assert summary["configured_benchmark_slot_count"] == 12
    assert summary["loaded_benchmark_slot_count"] == 8
    assert summary["eligible_coverage_pct"] == 100.0
    assert summary["configured_unique_coverage_pct"] == pytest.approx(66.7, abs=0.1)
    assert summary["no_survivor"] is True


def test_build_p3_rejection_breakdown_explains_zero_survivor_p3():
    df = pd.DataFrame(
        [
            {
                "phase": "P3",
                "decision": "REJECTED",
                "rejection_reason": "required_benchmark_failed=bench_core;benchmarks=0/2<1;coverage=50.0<70.0",
                "required_benchmark_name": "bench_core",
                "required_benchmark_passed": False,
            },
            {
                "phase": "P3",
                "decision": "REJECTED",
                "rejection_reason": "benchmarks=0/2<1;coverage=50.0<70.0",
                "required_benchmark_name": "bench_alt",
                "required_benchmark_passed": False,
            },
        ],
    )

    reason_df = _build_p3_rejection_breakdown(df)
    benchmark_df = _build_p3_required_benchmark_breakdown(df)
    message = _format_p3_zero_survivor_message(
        {
            "p3_processed": 2,
            "configured_context_count": 6,
            "eligible_context_count": 4,
            "loaded_context_count": 2,
            "eligible_coverage_pct": 50.0,
            "configured_unique_coverage_pct": 33.3,
            "benchmark_slot_coverage_pct": 50.0,
        },
        reason_df,
    )

    assert reason_df.iloc[0]["reason"] == "Consensus benchmarks insuffisant"
    assert int(reason_df.iloc[0]["count"]) == 2
    assert "Couverture éligible insuffisante" in reason_df["reason"].tolist()
    assert benchmark_df["benchmark"].tolist() == ["bench_core", "bench_alt"]
    assert "Aucun candidat ne passe P3" in message
    assert "Consensus benchmarks insuffisant" in message


def test_build_candidate_report_summary_prefers_last_useful_phase_and_decision():
    payload = {
        "phase": "FULL",
        "stats": {
            "p1_candidates": 12,
            "p2_processed": 12,
            "p2_survivors": 6,
            "p3_processed": 6,
            "p3_survivors": 2,
            "p4_processed": 2,
            "p4_survivors": 1,
            "catalog_synced": 3,
        },
        "by_phase": {"P4": 1, "P3": 5},
    }
    df = pd.DataFrame(
        [
            {"phase": "P4", "decision": "WATCHLIST"},
            {"phase": "P3", "decision": "REJECTED"},
            {"phase": "P3", "decision": "REJECTED"},
        ],
    )

    summary = _build_candidate_report_summary(payload, df)

    assert summary["total_candidates"] == 12
    assert summary["final_phase"] == "P4"
    assert summary["dominant_decision"] == "REJECTED"
    assert summary["catalog_synced"] == 3
    assert summary["survivor_counts"]["P3"] == 2


def test_resolve_candidate_phase_focus_default_prefers_highest_available_phase():
    summary = {
        "final_phase": "P5",
        "phase_distribution": {"P3": 1159, "P4": 9, "P5": 4, "P6": 0},
    }
    df = pd.DataFrame(
        [
            {"phase": "P3", "strategy_name": "p3_candidate"},
            {"phase": "P5", "strategy_name": "p5_candidate"},
        ],
    )

    default_focus = _resolve_candidate_phase_focus_default(summary, df)
    resolved = _resolve_candidate_phase_filter(
        results_hub_module.GRADUATION_PHASE_FOCUS_AUTO,
        summary=summary,
        available_phases=["P3", "P5"],
        df=df,
    )

    assert default_focus == "P5"
    assert resolved == "P5"


def test_build_phase_rejection_breakdown_aggregates_p5_failure_modes():
    df = pd.DataFrame(
        [
            {"phase": "P5", "rejection_reason": "WFA overfitting=16.16>1.8"},
            {
                "phase": "P5",
                "rejection_reason": "WFA avg_test_sharpe=-2.84<0.3; WFA overfitting=20.64>1.8",
            },
            {
                "phase": "P5",
                "rejection_reason": "WFA instable 0.38<0.5; WFA overfitting=16.69>1.8",
            },
        ],
    )

    reason_df = _build_phase_rejection_breakdown(df, "P5")
    reason_counts = dict(zip(reason_df["reason"], reason_df["count"], strict=False))

    assert reason_counts["Overfitting WFA excessif"] == 3
    assert reason_counts["Sharpe test WFA insuffisant"] == 1
    assert reason_counts["WFA instable"] == 1


def test_build_phase_focus_preview_df_uses_phase_specific_columns_and_truncates_reason():
    long_reason = "WFA overfitting=16.16>1.8;" + ("WFA avg_test_sharpe=-2.84<0.3;" * 10)
    df = pd.DataFrame(
        [
            {
                "phase": "P5",
                "strategy_name": f"strategy_{idx}",
                "source_symbol": "BTCUSDC",
                "source_timeframe": "1h",
                "wfa_stability": 0.7,
                "wfa_avg_test_return_pct": 12.3,
                "wfa_avg_test_sharpe": 1.1,
                "wfa_overfitting_ratio": 3.4,
                "rejection_reason": long_reason,
            }
            for idx in range(25)
        ],
    )

    preview = _build_phase_focus_preview_df(df, "P5")

    assert len(preview) == results_hub_module.GRADUATION_PREVIEW_LIMIT
    assert "wfa_overfitting_ratio" in preview.columns
    assert "wfa_avg_test_sharpe" in preview.columns
    assert preview.iloc[0]["rejection_reason"].endswith("…")


def test_build_candidate_preview_df_limits_rows_and_truncates_rejection_reason():
    long_reason = "required_benchmark_failed=bench_core;" + ("coverage=50.0<70.0;" * 10)
    df = pd.DataFrame(
        [
            {
                "strategy_name": f"strategy_{idx}",
                "source_symbol": "BTCUSDC",
                "source_timeframe": "1h",
                "phase": "P3",
                "decision": "REJECTED",
                "best_return_pct": float(idx),
                "best_sharpe": 1.0,
                "best_trades": 10,
                "benchmark_pass_summary": "0/2",
                "context_pass_summary": "0/4",
                "required_benchmark_name": "bench_core",
                "rejection_reason": long_reason,
                "configured_context_count": 8,
            }
            for idx in range(25)
        ],
    )

    preview = _build_candidate_preview_df(df)

    assert len(preview) == results_hub_module.GRADUATION_PREVIEW_LIMIT
    assert "configured_context_count" not in preview.columns
    assert preview.iloc[0]["rejection_reason"].endswith("…")


def test_decorate_graduation_strategy_links_resolves_builder_strategy_folder(tmp_path: Path, monkeypatch):
    builder_root = tmp_path / "_builder_sessions"
    session_dir = builder_root / "sess-1"
    session_dir.mkdir(parents=True)
    (session_dir / "strategy_v4.py").write_text("# strategy\n", encoding="utf-8")
    monkeypatch.setattr(results_hub_module, "get_builder_sessions_dir", lambda: builder_root)

    df = pd.DataFrame(
        [
            {
                "strategy_name": "ema_cross",
                "session_id": "sess-1",
                "best_iteration": 4,
                "strategy_file": "sess-1/strategy_v4.py",
            },
        ],
    )

    decorated = results_hub_module._decorate_graduation_strategy_links(df)

    assert "strategy_name_link" in decorated.columns
    assert decorated.iloc[0]["strategy_name_link"] == f"{session_dir.resolve().as_uri()}#ema_cross"


def test_render_phase_diagnostic_panel_uses_clickable_strategy_links(monkeypatch, tmp_path: Path):
    builder_root = tmp_path / "_builder_sessions"
    session_dir = builder_root / "sess-1"
    session_dir.mkdir(parents=True)
    (session_dir / "strategy_v1.py").write_text("# strategy\n", encoding="utf-8")
    monkeypatch.setattr(results_hub_module, "get_builder_sessions_dir", lambda: builder_root)

    dataframe_calls: list[tuple[pd.DataFrame, dict[str, Any]]] = []

    class _MetricStub:
        def metric(self, *args, **kwargs):
            return None

    monkeypatch.setattr(results_hub_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "bar_chart", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "columns", lambda spec: [_MetricStub() for _ in range(spec)])
    monkeypatch.setattr(results_hub_module.st, "expander", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        results_hub_module.st,
        "dataframe",
        lambda df, **kwargs: dataframe_calls.append((df.copy(), dict(kwargs))),
    )

    df = pd.DataFrame(
        [
            {
                "phase": "P4",
                "strategy_name": "ema_cross",
                "session_id": "sess-1",
                "best_iteration": 1,
                "strategy_file": "sess-1/strategy_v1.py",
                "source_symbol": "BTCUSDC",
                "source_timeframe": "1h",
                "sweep_robustness_pct": 61.5,
                "best_max_drawdown_pct": 9.2,
                "best_return_pct": 14.4,
                "rejection_reason": "robustesse insuffisante",
            },
        ],
    )

    results_hub_module._render_phase_diagnostic_panel(
        phase="P4",
        summary={"processed_counts": {"P4": 1}, "survivor_counts": {"P4": 0}, "final_phase": "P4"},
        df=df,
    )

    rendered_df, kwargs = dataframe_calls[-1]
    assert "strategy_name_link" in rendered_df.columns
    assert "strategy_name" not in rendered_df.columns
    assert rendered_df.iloc[0]["strategy_name_link"] == f"{session_dir.resolve().as_uri()}#ema_cross"
    assert "strategy_name_link" in kwargs["column_config"]


def test_render_candidate_report_section_uses_clickable_strategy_links(monkeypatch, tmp_path: Path):
    builder_root = tmp_path / "_builder_sessions"
    session_dir = builder_root / "sess-1"
    session_dir.mkdir(parents=True)
    (session_dir / "strategy_v2.py").write_text("# strategy\n", encoding="utf-8")
    monkeypatch.setattr(results_hub_module, "get_builder_sessions_dir", lambda: builder_root)

    dataframe_calls: list[tuple[pd.DataFrame, dict[str, Any]]] = []

    class _ColumnStub:
        def metric(self, *args, **kwargs):
            return None

        def selectbox(self, label, options, key=None):
            return options[0]

    monkeypatch.setattr(results_hub_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "bar_chart", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_hub_module.st, "columns", lambda spec: [_ColumnStub() for _ in range(spec)])
    monkeypatch.setattr(results_hub_module.st, "expander", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(results_hub_module.st, "selectbox", lambda label, options, key=None: options[0])
    monkeypatch.setattr(
        results_hub_module.st,
        "dataframe",
        lambda df, **kwargs: dataframe_calls.append((df.copy(), dict(kwargs))),
    )

    df = pd.DataFrame(
        [
            {
                "strategy_name": "ema_cross",
                "session_id": "sess-1",
                "source_run_id": "run-1",
                "source_symbol": "BTCUSDC",
                "source_timeframe": "1h",
                "source_kind": "sandbox",
                "phase": "P2",
                "decision": "WATCHLIST",
                "best_iteration": 2,
                "strategy_file": "sess-1/strategy_v2.py",
                "best_return_pct": 12.5,
                "best_profit_factor": 1.2,
                "best_sharpe": 1.1,
                "best_trades": 32,
                "benchmark_pass_summary": "1/1",
                "context_pass_summary": "2/2",
                "rejection_reason": "",
                "catalog_category": "",
                "catalog_entry_id": "entry-1",
            },
        ],
    )

    results_hub_module._render_candidate_report_section(
        title="Sandbox",
        payload={"phase": "FULL", "stats": {"p1_candidates": 1, "p2_processed": 1, "catalog_synced": 0}},
        df=df,
        key_prefix="graduation_test",
    )

    preview_call = next(call for call in dataframe_calls if "strategy_name_link" in call[0].columns)
    rendered_df, kwargs = preview_call
    assert "strategy_name_link" in rendered_df.columns
    assert "strategy_name" not in rendered_df.columns
    assert rendered_df.iloc[0]["strategy_name_link"] == f"{session_dir.resolve().as_uri()}#ema_cross"
    assert "strategy_name_link" in kwargs["column_config"]


def test_extract_catalog_postfilter_fields_normalizes_positive_pipeline_meta():
    entry = {
        "meta": {
            "positive_pipeline_phase": "P3",
            "positive_pipeline_decision": "WATCHLIST",
            "positive_pipeline_p2_verdict": "PASSED",
            "positive_pipeline_p3_verdict": "PASSED",
            "positive_pipeline_coverage_pct": 75.0,
            "positive_pipeline_passed_count": 3,
            "positive_pipeline_total_contexts": 4,
            "positive_pipeline_tested_timeframes": ["1h", "4h"],
            "positive_pipeline_benchmark_results": {
                "crypto_liquid_benchmark_v1_core": {"tokens": ["BTCUSDC", "ETHUSDC"]},
                "crypto_liquid_benchmark_v3_balanced": {"tokens": ["LINKUSDC"]},
            },
            "positive_pipeline_benchmark_consensus": {
                "required_benchmark_name": "crypto_liquid_benchmark_v1_core",
                "required_passed": True,
                "benchmarks_passed": ["crypto_liquid_benchmark_v1_core"],
                "benchmarks_total": 2,
                "contradicted": True,
            },
        },
        "last_metrics_snapshot": {},
    }

    extracted = _extract_catalog_postfilter_fields(entry)

    assert extracted["phase"] == "P3"
    assert extracted["decision"] == "WATCHLIST"
    assert extracted["p2_verdict"] == "PASSED"
    assert extracted["p3_verdict"] == "PASSED"
    assert extracted["coverage_pct"] == 75.0
    assert extracted["context_pass_summary"] == "3/4"
    assert extracted["required_benchmark_name"] == "crypto_liquid_benchmark_v1_core"
    assert extracted["required_benchmark_passed"] is True
    assert extracted["benchmark_pass_summary"] == "1/2"
    assert extracted["contradiction_state"] == "contradicted"
    assert extracted["tested_benchmark_names"] == (
        "crypto_liquid_benchmark_v1_core,crypto_liquid_benchmark_v3_balanced"
    )
    assert extracted["tested_tokens"] == "BTCUSDC,ETHUSDC,LINKUSDC"
    assert extracted["timeframes_tested"] == "1h,4h"


def test_catalog_postfilter_fields_supports_generic_canonical_meta():
    entry = {
        "meta": {
            "phase": "P4",
            "decision": "REVIEW",
            "coverage_pct": 83.3,
            "passed_context_count": 5,
            "total_context_count": 6,
            "benchmark_consensus": {
                "required_benchmark_name": "crypto_liquid_benchmark_v1_core",
                "benchmarks_passed": [
                    "crypto_liquid_benchmark_v1_core",
                    "crypto_liquid_benchmark_v3_balanced",
                ],
                "benchmarks_total": 3,
                "consensus_passed": True,
            },
        },
        "last_metrics_snapshot": {},
    }

    extracted = _catalog_postfilter_fields(entry)

    assert extracted["phase"] == "P4"
    assert extracted["decision"] == "REVIEW"
    assert extracted["benchmark_summary"] == "2/3"
    assert extracted["context_summary"] == "5/6"
    assert extracted["coverage_pct"] == 83.3
    assert extracted["required_benchmark"] == "crypto_liquid_benchmark_v1_core"
    assert extracted["contradiction_state"] == "passed"


def test_add_pnl_per_day_handles_string_dates_without_dt_accessor_crash():
    df = pd.DataFrame(
        [
            {
                "total_pnl": "300",
                "period_start": "2025-01-01T00:00:00Z",
                "period_end": "2025-01-31T00:00:00Z",
            },
        ],
    )

    normalized = _normalize_backtest_overview_df(df)
    enriched = _add_pnl_per_day(normalized)

    assert enriched.loc[0, "period_days"] == 30.0
    assert enriched.loc[0, "pnl_per_day"] == 10.0


def test_safe_read_csv_disables_low_memory_for_mixed_catalog_columns(tmp_path, monkeypatch):
    csv_path = tmp_path / "overview.csv"
    csv_path.write_text("a,b\n1,x\n2,y\n", encoding="utf-8")

    captured: dict[str, Any] = {}

    def _fake_read_csv(path, *_args, **kwargs):
        captured["path"] = path
        captured["kwargs"] = kwargs
        return pd.DataFrame([{"a": 1, "b": "x"}])

    monkeypatch.setattr(pd, "read_csv", _fake_read_csv)

    result = _safe_read_csv(csv_path)

    assert not result.empty
    assert captured["path"] == csv_path
    assert captured["kwargs"]["low_memory"] is False


def test_sanitize_builder_stream_text_masks_prompt_echo_in_code_phase():
    raw = (
        "## YOUR TURN\n"
        "Now write the Python class implementation.\n"
        "<|im_start|>\n"
        "Okay, I need to write a Python class for the strategy.\n"
        "Wait, let me start by understanding the requirements.\n"
    )

    cleaned, language = _sanitize_builder_stream_text("code", raw)

    assert language == "text"
    assert "Generation du code utile en cours" in cleaned
    assert "YOUR TURN" not in cleaned
    assert "Okay, I need to" not in cleaned


def test_sanitize_builder_stream_text_extracts_useful_code_for_code_phase():
    raw = (
        "Okay, I need to write the class.\n"
        "```python\n"
        "class BuilderGeneratedStrategy:\n"
        "    def generate_signals(self, df, indicators, params):\n"
        "        return df['close'] * 0\n"
        "```\n"
    )

    cleaned, language = _sanitize_builder_stream_text("code", raw)

    assert language == "python"
    assert "class BuilderGeneratedStrategy" in cleaned
    assert "generate_signals" in cleaned
    assert "Okay, I need to" not in cleaned


def test_format_builder_live_event_line_marks_selected_branch():
    line = _format_builder_live_event_line(
        {
            "event": "proposal_selected",
            "selected_branch_label": "add_one",
            "message": "Branche retenue | branche `add_one` - Hypothese finale",
            "payload": {
                "proposal": {
                    "hypothesis": "Hypothese finale",
                    "used_indicators": ["rsi", "ema"],
                },
            },
        },
    )

    assert "[add_one]" in line
    assert "Branche retenue" in line
    assert "Hypothese finale" in line


def test_format_builder_live_event_line_uses_backtest_metrics_from_canonical_payload():
    line = _format_builder_live_event_line(
        {
            "event": "phase_done",
            "phase": "backtest",
            "branch_label": "keep",
            "message": "Backtest termine",
            "payload": {
                "sharpe": 1.234,
                "total_return_pct": 12.5,
                "total_trades": 42,
            },
        },
    )

    assert line == "[keep] Backtest: Sharpe 1.234 | Return +12.50% | Trades 42"


def test_resolve_requested_model_refuses_silent_fallback_when_absent():
    resolved, note, found = _resolve_requested_model(
        "deepseek-r1:32b",
        ["mistral:7b", "qwen2.5:14b"],
        allow_fallback=False,
    )

    assert resolved == "deepseek-r1:32b"
    assert found is False
    assert "absent" in note


def test_ensure_ollama_running_reports_empty_inventory(monkeypatch):
    ollama_manager_module._OWNED_OLLAMA_PROCESSES.clear()
    ollama_manager_module._OLLAMA_PINNING_RESTARTED_HOSTS.clear()
    monkeypatch.setattr(
        ollama_manager_module,
        "_fetch_tags_payload",
        lambda *args, **kwargs: ({"models": []}, 200, None),
    )

    ok, msg = ollama_manager_module.ensure_ollama_running("http://127.0.0.1:11434")

    assert ok is True
    assert "aucun modele detecte" in msg


def test_ensure_ollama_running_uses_current_store_and_pins_explicit_gpu_on_default_host(
    monkeypatch,
):
    ollama_manager_module._OWNED_OLLAMA_PROCESSES.clear()
    ollama_manager_module._OLLAMA_PINNING_RESTARTED_HOSTS.clear()
    attempts = {"count": 0}
    captured: dict[str, Any] = {}

    def _fetch_stub(*_args, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] <= 2:
            return None, None, RuntimeError("down")
        return {"models": [{"name": "qwen3-30b-a3b:q4_k_m"}]}, 200, None

    def _popen_stub(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            pid=12345,
            poll=lambda: 0,
            terminate=lambda: None,
            wait=lambda timeout=None: None,
        )

    monkeypatch.setattr(ollama_manager_module, "_fetch_tags_payload", _fetch_stub)
    monkeypatch.setattr(
        ollama_manager_module,
        "get_ollama_models_root",
        lambda: Path(r"C:\AI\ollama\models"),
    )
    monkeypatch.setattr(ollama_manager_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ollama_manager_module.subprocess, "Popen", _popen_stub)
    monkeypatch.setattr(ollama_manager_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("OLLAMA_MODELS", r"D:\models\ollama")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    monkeypatch.setenv("GPU_DEVICE_ORDINAL", "0,1")

    ok, msg = ollama_manager_module.ensure_ollama_running(
        "http://127.0.0.1:11434",
        gpu_target="GPU-0",
    )

    assert ok is True
    assert "modele(s)" in msg

    env = captured["kwargs"]["env"]
    assert env["OLLAMA_MODELS"] == r"C:\AI\ollama\models"
    assert env["CUDA_VISIBLE_DEVICES"] == "0"
    assert env["GPU_DEVICE_ORDINAL"] == "0"


def test_ensure_ollama_running_pins_gpu_for_dedicated_host(monkeypatch):
    ollama_manager_module._OWNED_OLLAMA_PROCESSES.clear()
    ollama_manager_module._OLLAMA_PINNING_RESTARTED_HOSTS.clear()
    attempts = {"count": 0}
    captured: dict[str, Any] = {}

    def _fetch_stub(*_args, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] <= 2:
            return None, None, RuntimeError("down")
        return {"models": [{"name": "qwen3-coder:30b"}]}, 200, None

    def _popen_stub(*_args, **kwargs):
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            pid=12346,
            poll=lambda: 0,
            terminate=lambda: None,
            wait=lambda timeout=None: None,
        )

    monkeypatch.setattr(ollama_manager_module, "_fetch_tags_payload", _fetch_stub)
    monkeypatch.setattr(
        ollama_manager_module,
        "get_ollama_models_root",
        lambda: Path(r"C:\AI\ollama\models"),
    )
    monkeypatch.setattr(ollama_manager_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ollama_manager_module.subprocess, "Popen", _popen_stub)
    monkeypatch.setattr(ollama_manager_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("OLLAMA_MODELS", r"D:\models\ollama")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    monkeypatch.setenv("GPU_DEVICE_ORDINAL", "0,1")

    ok, msg = ollama_manager_module.ensure_ollama_running(
        "http://127.0.0.1:22434",
        gpu_target="GPU-1",
    )

    assert ok is True
    assert "modele(s)" in msg

    env = captured["kwargs"]["env"]
    assert env["OLLAMA_MODELS"] == r"C:\AI\ollama\models"
    assert env["CUDA_VISIBLE_DEVICES"] == "1"
    assert env["GPU_DEVICE_ORDINAL"] == "1"


def test_ensure_ollama_running_leaves_all_gpus_visible_in_auto_mode(monkeypatch):
    ollama_manager_module._OWNED_OLLAMA_PROCESSES.clear()
    ollama_manager_module._OLLAMA_PINNING_RESTARTED_HOSTS.clear()
    attempts = {"count": 0}
    captured: dict[str, Any] = {}

    def _fetch_stub(*_args, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] <= 2:
            return None, None, RuntimeError("down")
        return {"models": [{"name": "qwen3-coder:30b"}]}, 200, None

    def _popen_stub(*_args, **kwargs):
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            pid=12347,
            poll=lambda: 0,
            terminate=lambda: None,
            wait=lambda timeout=None: None,
        )

    monkeypatch.setattr(ollama_manager_module, "_fetch_tags_payload", _fetch_stub)
    monkeypatch.setattr(
        ollama_manager_module,
        "get_ollama_models_root",
        lambda: Path(r"C:\AI\ollama\models"),
    )
    monkeypatch.setattr(ollama_manager_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ollama_manager_module.subprocess, "Popen", _popen_stub)
    monkeypatch.setattr(ollama_manager_module, "_bind_process_to_lifecycle", lambda _process: False)
    monkeypatch.setattr(ollama_manager_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("OLLAMA_MODELS", r"D:\models\ollama")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    monkeypatch.setenv("GPU_DEVICE_ORDINAL", "0,1")

    ok, msg = ollama_manager_module.ensure_ollama_running(
        "http://127.0.0.1:11434",
        gpu_target="auto",
    )

    assert ok is True
    assert "modele(s)" in msg

    env = captured["kwargs"]["env"]
    assert env["OLLAMA_MODELS"] == r"C:\AI\ollama\models"
    assert "CUDA_VISIBLE_DEVICES" not in env
    assert "GPU_DEVICE_ORDINAL" not in env


def test_ensure_ollama_running_restarts_owned_local_process_when_switching_back_to_auto(monkeypatch):
    ollama_manager_module._OWNED_OLLAMA_PROCESSES.clear()
    ollama_manager_module._OLLAMA_PINNING_RESTARTED_HOSTS.clear()
    host = "http://127.0.0.1:11434"
    attempts = {"count": 0}
    captured: dict[str, Any] = {}
    stopped = {"count": 0}

    def _fetch_stub(*_args, **_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return {"models": [{"name": "qwen3-coder:30b"}]}, 200, None
        if attempts["count"] == 2:
            return None, None, RuntimeError("restarting")
        return {"models": [{"name": "qwen3-coder:30b"}]}, 200, None

    def _popen_stub(*_args, **kwargs):
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            pid=12348,
            poll=lambda: 0,
            terminate=lambda: None,
            wait=lambda timeout=None: None,
        )

    old_process = SimpleNamespace(
        pid=11111,
        poll=lambda: None if stopped["count"] == 0 else 0,
        terminate=lambda: None,
        wait=lambda timeout=None: None,
    )
    ollama_manager_module._OWNED_OLLAMA_PROCESSES[host] = ollama_manager_module._OwnedOllamaProcess(
        host=host,
        process=old_process,
        visible_devices="0",
    )

    monkeypatch.setattr(ollama_manager_module, "_fetch_tags_payload", _fetch_stub)
    monkeypatch.setattr(
        ollama_manager_module,
        "get_ollama_models_root",
        lambda: Path(r"C:\AI\ollama\models"),
    )
    monkeypatch.setattr(ollama_manager_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(ollama_manager_module.subprocess, "Popen", _popen_stub)
    monkeypatch.setattr(ollama_manager_module, "_bind_process_to_lifecycle", lambda _process: False)
    monkeypatch.setattr(ollama_manager_module, "_stop_local_ollama_processes", lambda: stopped.__setitem__("count", stopped["count"] + 1))
    monkeypatch.setattr(ollama_manager_module.time, "sleep", lambda _seconds: None)

    ok, msg = ollama_manager_module.ensure_ollama_running(host, gpu_target="auto")

    assert ok is True
    assert "modele(s)" in msg
    assert stopped["count"] == 1
    assert "CUDA_VISIBLE_DEVICES" not in captured["kwargs"]["env"]
    assert ollama_manager_module._OWNED_OLLAMA_PROCESSES[host].visible_devices is None


def test_discover_gpu_inventory_prefers_nvidia_smi_indices_over_windows_wmi(monkeypatch):
    exec_tabs_module._discover_gpu_inventory.clear()
    calls: list[str] = []

    def _run_stub(args, **_kwargs):
        calls.append(str(args[0]))
        if args[0] == "nvidia-smi":
            return SimpleNamespace(
                stdout=("0, NVIDIA GeForce RTX 5080, 16303\n1, NVIDIA GeForce RTX 3060 Ti, 8192\n"),
            )
        if args[0] == "powershell":
            return SimpleNamespace(
                stdout=(
                    '[{"Name":"AMD Radeon(TM) Graphics","AdapterRAM":2147483648},'
                    '{"Name":"NVIDIA GeForce RTX 3060 Ti","AdapterRAM":4293918720},'
                    '{"Name":"NVIDIA GeForce RTX 5080","AdapterRAM":4293918720}]'
                ),
            )
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(exec_tabs_module.os, "name", "nt", raising=False)
    monkeypatch.setattr(exec_tabs_module.subprocess, "run", _run_stub)

    inventory = exec_tabs_module._discover_gpu_inventory()

    assert [item["id"] for item in inventory] == ["GPU-0", "GPU-1"]
    assert inventory[0]["name"] == "NVIDIA GeForce RTX 5080"
    assert inventory[0]["memory_bytes"] == 16303 * 1024 * 1024
    assert "powershell" not in calls


def test_prepare_builder_llm_passes_normalized_host_to_ollama_manager(monkeypatch):
    st.session_state.clear()
    captured: dict[str, object] = {}

    def _ensure_stub(ollama_host=None):
        captured["host"] = ollama_host
        return True, "ok"

    monkeypatch.setattr(
        builder_view_module,
        "ensure_ollama_running",
        _ensure_stub,
    )
    monkeypatch.setattr(
        builder_view_module.httpx,
        "get",
        lambda url, timeout=0: SimpleNamespace(
            status_code=200,
            json=lambda: {"models": [{"name": "qwen2.5:14b"}]},
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "probe_model_runtime_acceptance",
        lambda *args, **kwargs: {
            "requested_model": "qwen2.5:14b",
            "resolved_model": "qwen2.5:14b",
            "ollama_host": "http://127.0.0.1:11434",
            "host_reachable": True,
            "present_in_tags": True,
            "accepted": True,
            "status": "accepted",
            "message": "ok",
            "tags_status_code": 200,
            "runtime_status_code": 200,
            "runtime_error_body": "",
        },
    )

    ok, msg, resolved_model = builder_view_module._prepare_builder_llm(
        model="qwen2.5:14b",
        ollama_host="127.0.0.1:11434",
        preload_model=False,
        keep_alive_minutes=20,
        auto_start_ollama=True,
    )

    assert ok is True
    assert resolved_model == "qwen2.5:14b"
    assert captured["host"] == "http://127.0.0.1:11434"
    assert st.session_state["builder_runtime_acceptance_probe"]["status"] == "accepted"


def test_builder_ollama_start_button_passes_selected_model_context(monkeypatch):
    captured: dict[str, object] = {}

    def _ensure_stub(**kwargs):
        captured.update(kwargs)
        return True, "ok"

    monkeypatch.setattr(exec_tabs_module, "ensure_ollama_running", _ensure_stub)

    ok, msg = exec_tabs_module._ollama_start_if_needed(
        "http://127.0.0.1:11434",
        gpu_target="GPU-1",
        model_name="minimax-m2.7:cloud",
    )

    assert ok is True
    assert msg == "ok"
    assert captured == {
        "ollama_host": "http://127.0.0.1:11434",
        "gpu_target": "GPU-1",
        "model_name": "minimax-m2.7:cloud",
    }


def test_prepare_builder_llm_rejects_local_model_when_runtime_probe_times_out_without_preload(monkeypatch):
    st.session_state.clear()

    monkeypatch.setattr(
        builder_view_module,
        "ensure_ollama_running",
        lambda ollama_host=None: (True, "ok"),
    )
    monkeypatch.setattr(
        builder_view_module.httpx,
        "get",
        lambda url, timeout=0: SimpleNamespace(
            status_code=200,
            content=b'{"models":[{"name":"qwen3.5:35b"}]}',
            json=lambda: {"models": [{"name": "qwen3.5:35b"}]},
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "probe_model_runtime_acceptance",
        lambda *args, **kwargs: {
            "requested_model": "qwen3.5:35b",
            "resolved_model": "qwen3.5:35b",
            "ollama_host": "http://127.0.0.1:11434",
            "host_reachable": True,
            "present_in_tags": True,
            "accepted": False,
            "status": "runtime_timeout",
            "message": "L'hôte http://127.0.0.1:11434 est joignable, mais le probe runtime sur `qwen3.5:35b` a expiré.",
            "tags_status_code": 200,
            "runtime_status_code": None,
            "runtime_error_body": "",
        },
    )

    ok, msg, resolved_model = builder_view_module._prepare_builder_llm(
        model="qwen3.5:35b",
        ollama_host="127.0.0.1:11434",
        preload_model=False,
        keep_alive_minutes=20,
        auto_start_ollama=True,
    )

    assert ok is False
    assert resolved_model == "qwen3.5:35b"
    assert "probe runtime" in msg
    assert st.session_state["builder_runtime_acceptance_probe"]["status"] == "runtime_timeout"


def test_resolve_single_llm_runtime_route_uses_topology_gpu_target():
    topology = build_phase1_topology(
        primary_host="http://127.0.0.1:11434",
        control_host="http://127.0.0.1:22434",
        primary_gpu_target="GPU-1",
        control_gpu_target="GPU-0",
    )

    host, gpu_target = builder_view_module._resolve_single_llm_runtime_route(
        "http://127.0.0.1:11434",
        topology.to_dict(),
    )

    assert host == "http://127.0.0.1:11434"
    assert gpu_target == "GPU-1"


def test_probe_model_runtime_acceptance_classifies_exact_name_rejected_by_host(monkeypatch):
    monkeypatch.setattr(
        ollama_manager_module,
        "_fetch_tags_payload",
        lambda *args, **kwargs: ({"models": [{"name": "qwen3-coder:30b"}]}, 200, None),
    )
    monkeypatch.setattr(
        ollama_manager_module.httpx,
        "post",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=404,
            text='{"error":"model \'mistral:22b\' not found"}',
        ),
    )

    probe = ollama_manager_module.probe_model_runtime_acceptance(
        "mistral:22b",
        ollama_host="http://127.0.0.1:11434",
    )

    assert probe["host_reachable"] is True
    assert probe["accepted"] is False
    assert probe["status"] == "exact_name_rejected_by_host"
    assert probe["runtime_status_code"] == 404


def test_probe_model_runtime_acceptance_flags_cloud_runtime_unavailable_without_alias_or_api_key(
    monkeypatch,
):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.setattr(
        ollama_manager_module,
        "_fetch_tags_payload",
        lambda *args, **kwargs: ({"models": [{"name": "qwen3-coder:30b"}]}, 200, None),
    )
    monkeypatch.setattr(
        ollama_manager_module.httpx,
        "post",
        lambda *args, **kwargs: SimpleNamespace(
            status_code=404,
            text='{"error":"model \'qwen3-vl:235b\' not found"}',
        ),
    )

    probe = ollama_manager_module.probe_model_runtime_acceptance(
        "qwen3-vl:235b",
        ollama_host="http://127.0.0.1:11434",
    )

    assert probe["host_reachable"] is True
    assert probe["accepted"] is False
    assert probe["status"] == "cloud_model_not_exposed_by_current_host"
    assert "OLLAMA_API_KEY" in probe["message"]
    assert "/api/tags" in probe["message"]
    assert probe["api_key_present"] is False
    assert probe["direct_cloud"] is False


def test_probe_model_runtime_acceptance_accepts_local_signed_in_cloud_alias(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.setattr(
        ollama_manager_module,
        "_fetch_tags_payload",
        lambda *args, **kwargs: ({"models": [{"name": "qwen3-coder:30b"}]}, 200, None),
    )
    responses = iter(
        [
            SimpleNamespace(status_code=404, text='{"error":"model \'glm-5\' not found"}'),
            SimpleNamespace(status_code=200, text='{"model":"glm-5","done":true}'),
        ],
    )
    monkeypatch.setattr(
        ollama_manager_module.httpx,
        "post",
        lambda *args, **kwargs: next(responses),
    )

    probe = ollama_manager_module.probe_model_runtime_acceptance(
        "glm-5",
        ollama_host="http://127.0.0.1:11434",
    )

    assert probe["host_reachable"] is True
    assert probe["accepted"] is True
    assert probe["status"] == "accepted"
    assert probe["resolved_model"] == "glm-5:cloud"
    assert "alias runtime cloud" in probe["message"]


def test_ollama_client_retries_local_cloud_alias_after_model_not_found(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    attempted_models: list[str] = []

    class _DummyHttpClient:
        def __init__(self):
            self.timeout = 30.0

        def post(self, url, json=None, timeout=None, headers=None):
            _ = url, timeout, headers
            attempted_models.append(str((json or {}).get("model") or ""))
            if len(attempted_models) == 1:
                return SimpleNamespace(
                    status_code=404,
                    text='{"error":"model \'glm-5\' not found"}',
                    raise_for_status=lambda: (_ for _ in ()).throw(RuntimeError("should not be called")),
                )
            return SimpleNamespace(
                status_code=200,
                text='{"model":"glm-5"}',
                json=lambda: {
                    "model": "glm-5",
                    "message": {"content": "P"},
                    "prompt_eval_count": 6,
                    "eval_count": 1,
                },
                raise_for_status=lambda: None,
            )

        def close(self):
            return None

    monkeypatch.setattr(
        llm_client_module.httpx,
        "Client",
        lambda **kwargs: _DummyHttpClient(),
    )

    client = llm_client_module.OllamaClient(
        llm_client_module.LLMConfig(
            provider=llm_client_module.LLMProvider.OLLAMA,
            model="glm-5",
            ollama_host="http://127.0.0.1:11434",
            max_tokens=1,
            max_retries=1,
            timeout_seconds=30,
        ),
    )
    response = client.chat(
        [llm_client_module.LLMMessage(role="user", content="ping")],
        max_tokens=1,
    )
    client.close()

    assert response.content == "P"
    assert attempted_models == ["glm-5", "glm-5:cloud"]


def test_get_local_inventory_models_only_keeps_selectable_backends(monkeypatch):
    inventory = SimpleNamespace(
        discovered_models=[
            SimpleNamespace(name="gemma4:26b", backend="ollama", verified_available=True),
            SimpleNamespace(name="NeoQuasar/Kronos-small", backend="huggingface", verified_available=True),
            SimpleNamespace(name="qwen3-coder:30b", backend="ollama", verified_available=False),
        ],
    )
    monkeypatch.setattr(
        model_selector_module,
        "_get_local_inventory_snapshot",
        lambda ollama_host=None: inventory,
    )

    models = model_selector_module._get_local_inventory_models("http://127.0.0.1:11434")
    non_selectable = model_selector_module._get_local_non_ollama_inventory_models(
        "http://127.0.0.1:11434",
    )

    assert models == ["gemma4:26b"]
    assert non_selectable == [{"name": "NeoQuasar/Kronos-small", "backend": "huggingface"}]


def test_prepare_builder_llm_surfaces_exact_cloud_rejection_without_local_substitution(monkeypatch):
    st.session_state.clear()

    monkeypatch.setattr(
        builder_view_module,
        "ensure_ollama_running",
        lambda ollama_host=None: (True, "ok"),
    )
    monkeypatch.setattr(
        builder_view_module.httpx,
        "get",
        lambda url, timeout=0: SimpleNamespace(
            status_code=200,
            content=b'{"models":[{"name":"qwen3-coder:30b"}]}',
            json=lambda: {"models": [{"name": "qwen3-coder:30b"}]},
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "probe_model_runtime_acceptance",
        lambda *args, **kwargs: {
            "requested_model": "qwen3-coder:480b",
            "resolved_model": "qwen3-coder:480b",
            "ollama_host": "http://127.0.0.1:11434",
            "host_reachable": True,
            "present_in_tags": False,
            "accepted": False,
            "status": "exact_name_rejected_by_host",
            "message": "L'hôte http://127.0.0.1:11434 est joignable, mais il rejette le nom exact `qwen3-coder:480b`.",
            "tags_status_code": 200,
            "runtime_status_code": 404,
            "runtime_error_body": '{"error":"model \'qwen3-coder:480b\' not found"}',
        },
    )

    ok, msg, resolved_model = builder_view_module._prepare_builder_llm(
        model="qwen3-coder:480b",
        ollama_host="127.0.0.1:11434",
        preload_model=False,
        keep_alive_minutes=20,
        auto_start_ollama=True,
    )

    assert ok is False
    assert resolved_model == "qwen3-coder:480b"
    assert "rejette le nom exact" in msg
    assert st.session_state["builder_runtime_acceptance_probe"]["status"] == "exact_name_rejected_by_host"


def test_normalize_llm_inference_settings_clamps_ui_incompatible_max_tokens():
    settings = exec_tabs_module.normalize_llm_inference_settings({"max_tokens": -1})
    assert settings["max_tokens"] == 64

    settings = exec_tabs_module.normalize_llm_inference_settings({"max_tokens": 1})
    assert settings["max_tokens"] == 64


def test_prepare_builder_llm_surfaces_cloud_runtime_unavailable_without_alias_or_api_key(monkeypatch):
    st.session_state.clear()
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

    monkeypatch.setattr(
        builder_view_module,
        "ensure_ollama_running",
        lambda ollama_host=None: (True, "ok"),
    )
    monkeypatch.setattr(
        builder_view_module.httpx,
        "get",
        lambda url, timeout=0: SimpleNamespace(
            status_code=200,
            content=b'{"models":[{"name":"qwen3-coder:30b"}]}',
            json=lambda: {"models": [{"name": "qwen3-coder:30b"}]},
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "probe_model_runtime_acceptance",
        lambda *args, **kwargs: {
            "requested_model": "qwen3-vl:235b",
            "resolved_model": "qwen3-vl:235b",
            "ollama_host": "http://127.0.0.1:11434",
            "host_reachable": True,
            "present_in_tags": False,
            "accepted": False,
            "status": "cloud_model_not_exposed_by_current_host",
            "message": (
                "Le modèle cloud-only `qwen3-vl:235b` n'est pas exposé par l'hôte local "
                "http://127.0.0.1:11434: aucun alias runtime correspondant n'apparaît dans "
                "`/api/tags`, et le routage direct Ollama Cloud est inactif car "
                "`OLLAMA_API_KEY` est absent du process courant."
            ),
            "tags_status_code": 200,
            "runtime_status_code": 404,
            "runtime_error_body": '{"error":"model \'qwen3-vl:235b\' not found"}',
            "api_key_present": False,
            "direct_cloud": False,
        },
    )

    ok, msg, resolved_model = builder_view_module._prepare_builder_llm(
        model="qwen3-vl:235b",
        ollama_host="127.0.0.1:11434",
        preload_model=False,
        keep_alive_minutes=20,
        auto_start_ollama=True,
    )

    assert ok is False
    assert resolved_model == "qwen3-vl:235b"
    assert "n'est pas exposé par l'hôte local" in msg
    assert "OLLAMA_API_KEY" in msg
    assert (
        st.session_state["builder_runtime_acceptance_probe"]["status"]
        == "cloud_model_not_exposed_by_current_host"
    )


def test_prepare_builder_llm_accepts_local_signed_in_cloud_alias(monkeypatch):
    st.session_state.clear()
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

    monkeypatch.setattr(
        builder_view_module,
        "ensure_ollama_running",
        lambda ollama_host=None: (True, "ok"),
    )
    monkeypatch.setattr(
        builder_view_module.httpx,
        "get",
        lambda url, timeout=0: SimpleNamespace(
            status_code=200,
            content=b'{"models":[{"name":"qwen3-coder:30b"}]}',
            json=lambda: {"models": [{"name": "qwen3-coder:30b"}]},
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "probe_model_runtime_acceptance",
        lambda *args, **kwargs: {
            "requested_model": "glm-5",
            "resolved_model": "glm-5:cloud",
            "ollama_host": "http://127.0.0.1:11434",
            "host_reachable": True,
            "present_in_tags": False,
            "accepted": True,
            "status": "accepted",
            "message": "Alias runtime cloud local accepté.",
            "tags_status_code": 200,
            "runtime_status_code": 200,
            "runtime_error_body": "",
            "api_key_present": False,
            "direct_cloud": False,
        },
    )

    ok, msg, resolved_model = builder_view_module._prepare_builder_llm(
        model="glm-5",
        ollama_host="127.0.0.1:11434",
        preload_model=False,
        keep_alive_minutes=20,
        auto_start_ollama=True,
    )

    assert ok is True
    assert resolved_model == "glm-5:cloud"
    assert "warmup désactivé" in msg.lower()
    assert st.session_state["builder_runtime_acceptance_probe"]["resolved_model"] == "glm-5:cloud"


def test_prepare_builder_llm_prefers_live_cloud_runtime_alias_from_tags(monkeypatch):
    st.session_state.clear()

    monkeypatch.setattr(
        builder_view_module,
        "ensure_ollama_running",
        lambda ollama_host=None: (True, "ok"),
    )
    monkeypatch.setattr(
        builder_view_module.httpx,
        "get",
        lambda url, timeout=0: SimpleNamespace(
            status_code=200,
            content=b'{"models":[{"name":"gpt-oss:120b-cloud","remote_model":"gpt-oss:120b"}]}',
            json=lambda: {"models": [{"name": "gpt-oss:120b-cloud", "remote_model": "gpt-oss:120b"}]},
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "probe_model_runtime_acceptance",
        lambda *args, **kwargs: {
            "requested_model": "gpt-oss:120b",
            "resolved_model": "gpt-oss:120b-cloud",
            "ollama_host": "http://127.0.0.1:11434",
            "host_reachable": True,
            "present_in_tags": True,
            "accepted": True,
            "status": "accepted",
            "message": "ok",
            "tags_status_code": 200,
            "runtime_status_code": 200,
            "runtime_error_body": "",
        },
    )

    ok, msg, resolved_model = builder_view_module._prepare_builder_llm(
        model="gpt-oss:120b",
        ollama_host="127.0.0.1:11434",
        preload_model=False,
        keep_alive_minutes=20,
        auto_start_ollama=True,
    )

    assert ok is True
    assert resolved_model == "gpt-oss:120b-cloud"
    assert "Alias runtime cloud détecté" in msg
    assert st.session_state["builder_runtime_acceptance_probe"]["resolved_model"] == "gpt-oss:120b-cloud"


def test_prepare_builder_llm_routes_cloud_runtime_direct_with_api_key(monkeypatch):
    st.session_state.clear()
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-test-key")

    ensure_calls: list[dict[str, Any]] = []

    def _ensure_stub(**kwargs):
        ensure_calls.append(dict(kwargs))
        return True, "ok"

    captured: dict[str, Any] = {}

    def _fake_get(url, timeout=0, **kwargs):
        _ = timeout
        captured["tags_url"] = url
        captured["tags_headers"] = dict(kwargs.get("headers") or {})
        return SimpleNamespace(
            status_code=200,
            content=b'{"models":[{"name":"gpt-oss:120b"}]}',
            json=lambda: {"models": [{"name": "gpt-oss:120b"}]},
        )

    def _probe_stub(*args, **kwargs):
        captured["probe_kwargs"] = dict(kwargs)
        return {
            "requested_model": "gpt-oss:120b",
            "resolved_model": "gpt-oss:120b",
            "ollama_host": "https://ollama.com",
            "host_reachable": True,
            "present_in_tags": True,
            "accepted": True,
            "status": "accepted",
            "message": "ok",
            "tags_status_code": 200,
            "runtime_status_code": 200,
            "runtime_error_body": "",
        }

    monkeypatch.setattr(builder_view_module, "ensure_ollama_running", _ensure_stub)
    monkeypatch.setattr(builder_view_module.httpx, "get", _fake_get)
    monkeypatch.setattr(builder_view_module, "probe_model_runtime_acceptance", _probe_stub)

    ok, msg, resolved_model = builder_view_module._prepare_builder_llm(
        model="gpt-oss:120b",
        ollama_host="http://127.0.0.1:11434",
        preload_model=False,
        keep_alive_minutes=20,
        auto_start_ollama=True,
    )

    assert ok is True
    assert resolved_model == "gpt-oss:120b"
    assert ensure_calls == []
    assert captured["tags_url"] == "https://ollama.com/api/tags"
    assert captured["tags_headers"]["Authorization"] == "Bearer ollama-test-key"
    assert captured["probe_kwargs"]["ollama_host"] == "https://ollama.com"
    assert "Routage direct Ollama Cloud activé via OLLAMA_API_KEY" in msg
    assert st.session_state["builder_runtime_acceptance_probe"]["ollama_host"] == "https://ollama.com"


def test_prepare_builder_llm_resilient_falls_back_to_lazy_load(monkeypatch):
    calls: list[dict[str, object]] = []

    def _prepare_stub(**kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            return (
                False,
                "Impossible de précharger `acereason-nemotron:14b-q5_k_m` sur http://127.0.0.1:22434. "
                "Détail: timeout warmup (300s)",
                "acereason-nemotron:14b-q5_k_m",
            )
        return (
            True,
            "Ollama OK (http://127.0.0.1:22434) — warmup désactivé.",
            "acereason-nemotron:14b-q5_k_m",
        )

    monkeypatch.setattr(builder_view_module, "_prepare_builder_llm", _prepare_stub)

    ok, msg, resolved_model, lazy_fallback_used = builder_view_module._prepare_builder_llm_resilient(
        model="acereason-nemotron:14b-q5_k_m",
        ollama_host="http://127.0.0.1:22434",
        preload_model=True,
        keep_alive_minutes=20,
        auto_start_ollama=True,
        allow_lazy_fallback=True,
    )

    assert ok is True
    assert resolved_model == "acereason-nemotron:14b-q5_k_m"
    assert lazy_fallback_used is True
    assert "Fallback automatique vers un démarrage lazy-load." in msg
    assert calls[0]["preload_model"] is True
    assert calls[1]["preload_model"] is False
    assert calls[1]["model"] == "acereason-nemotron:14b-q5_k_m"


def test_ollama_client_chat_includes_keep_alive_payload(monkeypatch):
    client = llm_client_module.create_llm_client(
        llm_client_module.LLMConfig(
            provider=llm_client_module.LLMProvider.OLLAMA,
            model="qwen3-coder:30b",
            ollama_host="http://127.0.0.1:11434",
            keep_alive="45m",
        ),
    )
    sent: dict[str, Any] = {}

    def _fake_post(url, json=None, timeout=None):
        _ = timeout
        sent["url"] = url
        sent["payload"] = dict(json or {})
        return SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"message": {"content": "ok"}},
        )

    monkeypatch.setattr(cast(Any, client)._http_client, "post", _fake_post)

    response = client.chat(
        [llm_client_module.LLMMessage(role="user", content="hello")],
    )

    assert response.content == "ok"
    assert str(sent["url"]).endswith("/api/chat")
    assert sent["payload"]["keep_alive"] == "45m"


def test_ollama_client_routes_cloud_model_to_direct_api_with_authorization(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-test-key")
    client = llm_client_module.create_llm_client(
        llm_client_module.LLMConfig(
            provider=llm_client_module.LLMProvider.OLLAMA,
            model="gpt-oss:120b-cloud",
            ollama_host="http://127.0.0.1:11434",
            keep_alive="45m",
        ),
    )
    sent: dict[str, Any] = {}

    def _fake_post(url, json=None, timeout=None):
        _ = timeout
        sent["url"] = url
        sent["payload"] = dict(json or {})
        return SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"message": {"content": "ok"}},
        )

    monkeypatch.setattr(cast(Any, client)._http_client, "post", _fake_post)

    response = client.chat(
        [llm_client_module.LLMMessage(role="user", content="hello")],
    )

    assert response.content == "ok"
    assert sent["url"] == "https://ollama.com/api/chat"
    assert sent["payload"]["model"] == "gpt-oss:120b"
    assert cast(Any, client)._http_client.headers["Authorization"] == "Bearer ollama-test-key"


def test_role_model_config_prefers_catalog_when_ollama_is_down(monkeypatch):
    warnings: list[str] = []
    sleeps: list[float] = []

    monkeypatch.setattr(
        model_config_module,
        "get_ollama_runtime_model_names",
        lambda: ["qwen2.5:14b"],
    )
    monkeypatch.setattr(
        model_config_module.httpx,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ConnectionRefusedError("[WinError 10061] Connection refused"),
        ),
    )

    def _record_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(model_config_module.time, "sleep", _record_sleep)
    monkeypatch.setattr(
        model_config_module.logger,
        "warning",
        lambda message, *args: warnings.append(str(message)),
    )

    config = model_config_module.RoleModelConfig()

    installed = config.get_installed_models()
    assert "qwen2.5:14b" in installed
    assert sleeps == []
    assert warnings == []


def test_render_builder_view_marks_and_stops_autonomous_runtime_when_startup_probe_fails(
    monkeypatch,
):
    st.session_state.clear()
    st.session_state["is_running"] = True
    events: list[tuple[str, dict[str, object]]] = []
    recap_calls: list[tuple[list[dict[str, object]], dict[str, object]]] = []

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=True,
        builder_auto_market_pick=True,
        available_tokens=["ETHUSDC"],
        available_timeframes=["1h"],
        symbol="",
        timeframe="",
    )

    monkeypatch.setattr(builder_view_module, "_inject_builder_view_styles", lambda: None)
    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "error", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_supervisor_state",
        lambda: {
            "history": [{"session_num": 2999, "objective": "Historique existant"}],
            "supervisor": {"consecutive_errors": 0},
        },
    )
    monkeypatch.setattr(
        builder_view_module,
        "_render_autonomous_recap",
        lambda history, supervisor: recap_calls.append((list(history), dict(supervisor))),
    )
    monkeypatch.setattr(builder_view_module, "show_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder_view_module,
        "_mark_builder_autonomous_runtime_started",
        lambda **kwargs: events.append(("start", dict(kwargs))) or {},
    )
    monkeypatch.setattr(
        builder_view_module,
        "_heartbeat_builder_autonomous_runtime",
        lambda **kwargs: events.append(("heartbeat", dict(kwargs))) or {},
    )
    monkeypatch.setattr(
        builder_view_module,
        "mark_builder_autonomous_runtime_stopped",
        lambda **kwargs: events.append(("stop", dict(kwargs))) or {},
    )
    monkeypatch.setattr(
        builder_view_module,
        "_find_first_valid_builder_market",
        lambda **kwargs: ("", "", None, {"failures": []}),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_prepare_builder_llm_resilient",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Le warmup LLM ne doit pas démarrer si la sonde marché échoue"),
        ),
    )

    builder_view_module.render_builder_view(
        state=state,
        df=None,
        status_container=nullcontext(),
    )

    assert events[0][0] == "start"
    assert any(name == "heartbeat" and payload.get("last_event") == "startup_probe" for name, payload in events)
    stop_payload = next(payload for name, payload in events if name == "stop")
    assert stop_payload["reason"] == "startup_market_probe_failed"
    assert st.session_state["is_running"] is False
    assert recap_calls
    assert recap_calls[0][0][0]["session_num"] == 2999


def test_render_builder_view_autonomous_startup_probe_uses_filtered_universe_pairs(
    monkeypatch,
):
    st.session_state.clear()
    st.session_state["is_running"] = True
    captured: dict[str, object] = {}
    sample_df = _sample_ohlcv()

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=True,
        builder_auto_market_pick=True,
        builder_universe_mode="canonical",
        available_tokens=["ARUSDC", "TONUSDC", "BTCUSDC"],
        available_timeframes=["15m", "1h"],
        symbol="",
        timeframe="",
    )

    _patch_autonomous_builder_shell(monkeypatch)
    monkeypatch.setattr(builder_view_module.random, "shuffle", lambda seq: None)
    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_supervisor_state",
        lambda: {
            "history": [{"session_num": 12, "objective": "Historique existant"}],
            "supervisor": {"consecutive_errors": 0},
        },
    )
    monkeypatch.setattr(
        builder_view_module,
        "_render_autonomous_recap",
        lambda history, supervisor: captured.setdefault("recap_history", list(history)),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_call_builder_market_candidates",
        lambda *args, **kwargs: (["BTCUSDC"], ["1h"]),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_get_builder_market_universe_meta",
        lambda: {
            "universe_mode": "canonical",
            "eligible_pairs": [{"symbol": "BTCUSDC", "timeframe": "1h"}],
            "exclusion_summary": {"outside canonical universe": 2},
        },
    )

    def _mock_find_first_valid_builder_market(**kwargs):
        captured["symbols"] = list(kwargs.get("symbols", []))
        captured["timeframes"] = list(kwargs.get("timeframes", []))
        captured["preferred_pairs"] = list(kwargs.get("preferred_pairs", []))
        return "BTCUSDC", "1h", sample_df, {"failures": []}

    monkeypatch.setattr(
        builder_view_module,
        "_find_first_valid_builder_market",
        _mock_find_first_valid_builder_market,
    )
    monkeypatch.setattr(
        builder_view_module,
        "_execute_builder_autonomous_loop",
        lambda *args, **kwargs: captured.update(
            {
                "autonomous_loop_called": True,
                "recap_placeholder": kwargs.get("recap_placeholder"),
            },
        ),
    )

    builder_view_module.render_builder_view(
        state=state,
        df=None,
        status_container=nullcontext(),
    )

    assert captured["symbols"] == ["BTCUSDC"]
    assert captured["timeframes"] == ["1h"]
    assert captured["preferred_pairs"] == [("BTCUSDC", "1h")]
    assert captured["autonomous_loop_called"] is True


def test_render_builder_view_autonomous_startup_probe_falls_back_to_discovered_data_inventory(
    monkeypatch,
):
    st.session_state.clear()
    st.session_state["is_running"] = True
    captured: dict[str, object] = {}
    sample_df = _sample_ohlcv()
    discovery_calls = {"count": 0}

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=True,
        builder_auto_market_pick=True,
        available_tokens=[],
        available_timeframes=[],
        symbol="",
        timeframe="",
    )

    _patch_autonomous_builder_shell(monkeypatch)
    monkeypatch.setattr(builder_view_module.random, "shuffle", lambda seq: None)
    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_supervisor_state",
        lambda: {
            "history": [{"session_num": 44, "objective": "Historique existant"}],
            "supervisor": {"consecutive_errors": 0},
        },
    )
    monkeypatch.setattr(
        builder_view_module,
        "discover_available_builder_data",
        lambda: (
            discovery_calls.__setitem__("count", discovery_calls["count"] + 1)
            or (["SOLUSDC", "ETHUSDC"], ["4h", "1h"])
        ),
    )

    def _mock_find_first_valid_builder_market(**kwargs):
        captured["symbols"] = list(kwargs.get("symbols", []))
        captured["timeframes"] = list(kwargs.get("timeframes", []))
        return "SOLUSDC", "4h", sample_df, {"failures": []}

    monkeypatch.setattr(
        builder_view_module,
        "_find_first_valid_builder_market",
        _mock_find_first_valid_builder_market,
    )
    monkeypatch.setattr(
        builder_view_module,
        "_execute_builder_autonomous_loop",
        lambda *args, **kwargs: captured.update({"loop_called": True}),
    )

    builder_view_module.render_builder_view(
        state=state,
        df=None,
        status_container=nullcontext(),
    )

    assert set(captured["symbols"]) == {"SOLUSDC", "ETHUSDC"}
    assert set(captured["timeframes"]) == {"4h", "1h"}
    assert captured["loop_called"] is True
    assert discovery_calls["count"] == 1


def test_builder_market_candidates_falls_back_to_discovered_inventory_when_state_empty(
    monkeypatch,
):
    st.session_state.clear()
    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_auto_market_pick=True,
        available_tokens=[],
        available_timeframes=[],
    )

    monkeypatch.setattr(
        builder_view_module,
        "discover_available_builder_data",
        lambda: (["SOLUSDC", "ETHUSDC"], ["4h", "1h"]),
    )
    monkeypatch.setattr(builder_view_module.random, "shuffle", lambda seq: None)

    symbols, timeframes = builder_view_module._builder_market_candidates(
        state,
        current_symbol="",
        current_timeframe="",
    )

    assert symbols == ["SOLUSDC", "ETHUSDC"]
    assert timeframes == ["4h", "1h"]


def test_builder_market_candidates_reuses_cached_filtered_universe_for_autonomous_objectives(
    monkeypatch,
):
    st.session_state.clear()
    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_auto_market_pick=True,
        builder_universe_mode="exploratory",
        available_tokens=["SOLUSDC", "ETHUSDC"],
        available_timeframes=["1h", "4h"],
        builder_objective="",
    )
    filter_calls: list[dict[str, object]] = []

    def _fake_filter_market_universe(**kwargs):
        filter_calls.append(dict(kwargs))
        return {
            "universe_mode": kwargs.get("universe_mode"),
            "purpose": kwargs.get("purpose"),
            "strategy_type": kwargs.get("strategy_type"),
            "symbols": ["SOLUSDC", "ETHUSDC"],
            "timeframes": ["1h"],
            "eligible_pairs": [
                {
                    "symbol": "SOLUSDC",
                    "timeframe": "1h",
                    "quality_score": 91.0,
                }
            ],
            "excluded_pairs": [
                {
                    "symbol": "ETHUSDC",
                    "timeframe": "4h",
                    "exclusion_reasons": ["tradable ratio below canonical threshold"],
                }
            ],
            "criteria": {
                "min_listing_age_days": 45,
                "min_tradable_ratio_hard": 0.75,
                "min_tradable_ratio_canonical": 0.90,
                "min_median_dollar_volume_canonical": 250000.0,
                "volatility_window_bars": 96,
            },
            "canonical_tokens": [],
            "exclusion_summary": {
                "tradable ratio below canonical threshold": 1,
            },
        }

    monkeypatch.setattr(builder_view_module.random, "shuffle", lambda seq: None)
    monkeypatch.setattr(
        builder_view_module,
        "filter_market_universe",
        _fake_filter_market_universe,
    )

    first_symbols, first_timeframes = builder_view_module._builder_market_candidates(
        state,
        current_symbol="SOLUSDC",
        current_timeframe="1h",
        objective="",
        purpose="builder_autonomous",
    )
    second_symbols, second_timeframes = builder_view_module._builder_market_candidates(
        state,
        current_symbol="SOLUSDC",
        current_timeframe="1h",
        objective="Scalping momentum généré par le LLM après warmup",
        purpose="builder_autonomous",
    )

    assert first_symbols == second_symbols == ["SOLUSDC", "ETHUSDC"]
    assert first_timeframes == second_timeframes == ["1h"]
    assert len(filter_calls) == 1
    meta = builder_view_module._get_builder_market_universe_meta()
    assert meta["cache_status"] == "hit"
    assert meta["filter_source"] == "config.market_selection.filter_market_universe"
    assert meta["criteria"]["min_listing_age_days"] == 45
    assert meta["criteria"]["min_tradable_ratio_canonical"] == 0.90
    assert meta["criteria"]["min_median_dollar_volume_canonical"] == 250000.0
    assert "loader_trim_launch_pct" in meta["criteria"]
    assert "loader_trim_launch_min_hours" in meta["criteria"]
    assert meta["criteria"]["loader_gap_max_multiplier"] == 2.0
    assert meta["criteria"]["loader_non_tradable_rule"] == "volume<=0"
    assert meta["exclusion_summary"]["tradable ratio below canonical threshold"] == 1


def test_render_builder_view_autonomous_idle_skips_probe_and_runtime_prepare(
    monkeypatch,
):
    st.session_state.clear()
    st.session_state["is_running"] = False
    hero_calls: list[dict[str, object]] = []
    info_messages: list[str] = []
    recap_calls: list[tuple[list[dict[str, object]], dict[str, object]]] = []

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=True,
        builder_auto_market_pick=True,
        available_tokens=["ETHUSDC", "BTCUSDC"],
        available_timeframes=["15m", "1h"],
        symbol="",
        timeframe="",
    )

    monkeypatch.setattr(builder_view_module, "_inject_builder_view_styles", lambda: None)
    monkeypatch.setattr(
        builder_view_module,
        "_render_builder_mode_hero",
        lambda **kwargs: hero_calls.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_render_builder_runtime_notes",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        builder_view_module,
        "_render_autonomous_recap",
        lambda history, supervisor: recap_calls.append((list(history), dict(supervisor))),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_supervisor_state",
        lambda: {
            "history": [{"session_num": 1, "objective": "demo"}],
            "supervisor": {"soft_reset_count": 0},
        },
    )
    monkeypatch.setattr(
        builder_view_module.st, "info", lambda message, *args, **kwargs: info_messages.append(str(message)),
    )
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder_view_module,
        "_mark_builder_autonomous_runtime_started",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Le runtime autonome ne doit pas démarrer en mode idle"),
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_find_first_valid_builder_market",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("La sonde marché ne doit pas tourner en mode idle"),
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_prepare_builder_llm_resilient",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Le warmup LLM ne doit pas démarrer en mode idle"),
        ),
    )

    builder_view_module.render_builder_view(
        state=state,
        df=None,
        status_container=nullcontext(),
    )

    assert hero_calls
    assert hero_calls[0]["mode_label"] == "Autonome 24/24"
    assert hero_calls[0]["market_label"] == "2 symboles × 2 timeframes"
    assert info_messages
    assert "Cliquez sur Lancer" in info_messages[0]
    assert recap_calls == [
        ([{"session_num": 1, "objective": "demo"}], {"soft_reset_count": 0}),
    ]
    assert st.session_state["is_running"] is False


def test_render_builder_view_autonomous_idle_renders_empty_recap_immediately(
    monkeypatch,
):
    st.session_state.clear()
    st.session_state["is_running"] = False
    recap_calls: list[tuple[list[dict[str, object]], dict[str, object]]] = []

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=True,
        builder_auto_market_pick=True,
        available_tokens=["ETHUSDC", "BTCUSDC"],
        available_timeframes=["15m", "1h"],
        symbol="",
        timeframe="",
    )

    monkeypatch.setattr(builder_view_module, "_inject_builder_view_styles", lambda: None)
    monkeypatch.setattr(builder_view_module, "_render_builder_mode_hero", lambda **kwargs: None)
    monkeypatch.setattr(builder_view_module, "_render_builder_runtime_notes", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder_view_module,
        "_render_autonomous_recap",
        lambda history, supervisor: recap_calls.append((list(history), dict(supervisor))),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_supervisor_state",
        lambda: {"history": [], "supervisor": {"soft_reset_count": 0}},
    )
    monkeypatch.setattr(builder_view_module.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder_view_module,
        "_mark_builder_autonomous_runtime_started",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Le runtime autonome ne doit pas démarrer en mode idle"),
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_find_first_valid_builder_market",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("La sonde marché ne doit pas tourner en mode idle"),
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_prepare_builder_llm_resilient",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Le warmup LLM ne doit pas démarrer en mode idle"),
        ),
    )

    builder_view_module.render_builder_view(
        state=state,
        df=None,
        status_container=nullcontext(),
    )

    assert recap_calls == [([], {"soft_reset_count": 0})]
    assert st.session_state["is_running"] is False


def test_render_builder_view_autonomous_passes_unload_preference_to_session(
    monkeypatch,
):
    st.session_state.clear()
    st.session_state["is_running"] = True

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=True,
        builder_auto_market_pick=False,
        builder_unload_after_run=False,
        builder_auto_pause=0,
        symbol="BTCUSDT",
        timeframe="1h",
        available_tokens=["BTCUSDT"],
        available_timeframes=["1h"],
    )
    sample_df = _sample_ohlcv()
    run_calls: list[dict[str, object]] = []

    _patch_autonomous_builder_shell(monkeypatch)
    monkeypatch.setattr(
        builder_view_module,
        "_prepare_builder_llm_resilient",
        lambda **kwargs: (True, "runtime prêt", "qwen3-coder:30b", False),
    )

    def _run_stub(**kwargs):
        run_calls.append(dict(kwargs))
        st.session_state["is_running"] = False
        return SimpleNamespace(
            status="success",
            best_sharpe=1.0,
            iterations=[],
            session_id="manual-autonomous-test",
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(builder_view_module, "_run_single_builder_session", _run_stub)

    builder_view_module.render_builder_view(
        state=state,
        df=sample_df,
        status_container=nullcontext(),
    )

    assert len(run_calls) == 1
    assert run_calls[0]["unload_after_run"] is False


def test_render_builder_view_autonomous_running_renders_recap_before_first_session(
    monkeypatch,
):
    st.session_state.clear()
    st.session_state["is_running"] = True
    sample_df = _sample_ohlcv()
    recap_snapshots: list[list[dict[str, object]]] = []

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=True,
        builder_auto_market_pick=False,
        builder_auto_pause=0,
        symbol="BTCUSDT",
        timeframe="1h",
        available_tokens=["BTCUSDT"],
        available_timeframes=["1h"],
    )

    _patch_autonomous_builder_shell(monkeypatch)
    monkeypatch.setattr(
        builder_view_module,
        "_render_autonomous_recap",
        lambda history, supervisor: recap_snapshots.append(list(history)),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_prepare_builder_llm_resilient",
        lambda **kwargs: (True, "runtime prêt", "qwen3-coder:30b", False),
    )

    def _run_stub(**kwargs):
        assert recap_snapshots
        assert recap_snapshots[0] == []
        st.session_state["is_running"] = False
        return SimpleNamespace(
            status="success",
            best_sharpe=1.0,
            best_score=1.0,
            iterations=[],
            session_id="autonomous-first-session",
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            model_name="qwen3-coder:30b",
        )

    monkeypatch.setattr(builder_view_module, "_run_single_builder_session", _run_stub)

    builder_view_module.render_builder_view(
        state=state,
        df=sample_df,
        status_container=nullcontext(),
    )

    assert recap_snapshots[0] == []
    assert any(snapshot for snapshot in recap_snapshots[1:])


def test_render_builder_view_autonomous_repreloads_after_unloaded_session(
    monkeypatch,
):
    st.session_state.clear()
    st.session_state["is_running"] = True

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=True,
        builder_auto_market_pick=False,
        builder_unload_after_run=True,
        builder_auto_pause=0,
        symbol="BTCUSDT",
        timeframe="1h",
        available_tokens=["BTCUSDT"],
        available_timeframes=["1h"],
    )
    sample_df = _sample_ohlcv()
    prepare_calls: list[dict[str, object]] = []
    session_counter = {"count": 0}

    _patch_autonomous_builder_shell(monkeypatch)
    monkeypatch.setattr(
        builder_view_module,
        "_prepare_builder_llm_resilient",
        lambda **kwargs: (True, "runtime prêt", "qwen3-coder:30b", False),
    )

    def _prepare_stub(**kwargs):
        prepare_calls.append(dict(kwargs))
        return True, "session prête", str(kwargs.get("model") or "qwen3-coder:30b")

    def _run_stub(**kwargs):
        session_counter["count"] += 1
        if session_counter["count"] >= 2:
            st.session_state["is_running"] = False
        return SimpleNamespace(
            status="success",
            best_sharpe=1.0,
            iterations=[],
            session_id=f"autonomous-session-{session_counter['count']}",
            start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(builder_view_module, "_prepare_builder_llm", _prepare_stub)
    monkeypatch.setattr(builder_view_module, "_run_single_builder_session", _run_stub)

    builder_view_module.render_builder_view(
        state=state,
        df=sample_df,
        status_container=nullcontext(),
    )

    assert session_counter["count"] == 2
    assert len(prepare_calls) == 1
    assert prepare_calls[0]["preload_model"] is True


def test_render_builder_view_uses_session_autonomous_flag_when_state_is_stale(
    monkeypatch,
):
    st.session_state.clear()
    st.session_state["is_running"] = True
    st.session_state["builder_autonomous"] = True
    st.session_state["builder_autonomous_toggle"] = True
    captured: dict[str, object] = {}
    sample_df = _sample_ohlcv()

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=False,
        builder_objective="",
        symbol="BTCUSDT",
        timeframe="1h",
        available_tokens=["BTCUSDT"],
        available_timeframes=["1h"],
    )

    _patch_autonomous_builder_shell(monkeypatch)
    monkeypatch.setattr(
        builder_view_module,
        "_execute_builder_manual_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Le chemin manuel ne doit pas etre appele si le toggle autonome est deja actif"),
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_execute_builder_autonomous_loop",
        lambda *args, **kwargs: captured.update(
            {
                "called": True,
                "symbol": kwargs.get("symbol"),
                "timeframe": kwargs.get("timeframe"),
            },
        ),
    )

    builder_view_module.render_builder_view(
        state=state,
        df=sample_df,
        status_container=nullcontext(),
    )

    assert captured["called"] is True
    assert captured["symbol"] == "BTCUSDT"
    assert captured["timeframe"] == "1h"
    assert state.builder_autonomous is True


def test_render_builder_view_arms_deferred_toggle_sync_without_touching_widget_key(
    monkeypatch,
):
    st.session_state.clear()
    st.session_state["is_running"] = True
    st.session_state["builder_autonomous"] = True
    st.session_state["builder_autonomous_toggle"] = False
    captured: dict[str, object] = {}
    sample_df = _sample_ohlcv()

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=False,
        builder_objective="",
        symbol="BTCUSDT",
        timeframe="1h",
        available_tokens=["BTCUSDT"],
        available_timeframes=["1h"],
    )

    _patch_autonomous_builder_shell(monkeypatch)
    monkeypatch.setattr(
        builder_view_module,
        "_execute_builder_manual_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Le chemin manuel ne doit pas etre appele si le mode autonome est actif en session"),
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_execute_builder_autonomous_loop",
        lambda *args, **kwargs: captured.update({"called": True}),
    )

    builder_view_module.render_builder_view(
        state=state,
        df=sample_df,
        status_container=nullcontext(),
    )

    assert captured["called"] is True
    assert st.session_state["builder_autonomous_toggle"] is False
    assert st.session_state["_builder_autonomous_toggle_sync"] is True


def test_cleanup_all_models_uses_ps_not_tags(monkeypatch):
    requested_urls: list[str] = []
    unloaded: list[str] = []

    def _fake_get(url, timeout=0):
        _ = timeout
        requested_urls.append(url)
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"models": [{"name": "qwen3-coder:30b"}]},
        )

    monkeypatch.setattr(ollama_manager_module.httpx, "get", _fake_get)
    monkeypatch.setattr(
        ollama_manager_module,
        "unload_model",
        lambda model_name, ollama_host=None: unloaded.append(model_name) or True,
    )

    cleaned = ollama_manager_module.cleanup_all_models("http://127.0.0.1:11434")

    assert cleaned == 1
    assert requested_urls == ["http://127.0.0.1:11434/api/ps"]
    assert unloaded == ["qwen3-coder:30b"]


def test_get_available_models_for_ui_merges_local_and_cloud_sources(monkeypatch):
    monkeypatch.setattr(
        model_selector_module,
        "_get_installed_ollama_models",
        lambda ollama_host=None: ["qwen2.5:14b", "mistral:7b-instruct"],
    )
    monkeypatch.setattr(
        model_selector_module,
        "_get_local_inventory_models",
        lambda ollama_host=None: ["deepseek-r1:32b"],
    )
    monkeypatch.setattr(
        model_selector_module,
        "_get_library_models",
        lambda: ["deepseek-r1:32b", "qwen2.5:14b"],
    )
    monkeypatch.setattr(
        model_selector_module,
        "_get_cloud_only_models",
        lambda: ["qwen3-coder:480b"],
    )

    models = model_selector_module.get_available_models_for_ui(
        preferred_order=["deepseek-r1:32b", "qwen2.5:14b"],
        ollama_host="http://my-host:11434",
    )

    assert models[:2] == ["deepseek-r1:32b", "qwen2.5:14b"]
    assert set(models) == {
        "deepseek-r1:32b",
        "mistral:7b-instruct",
        "qwen2.5:14b",
        "qwen3-coder:480b",
    }


def test_get_available_models_for_ui_normalizes_and_merges_catalog_entries(monkeypatch):
    monkeypatch.setattr(
        model_selector_module,
        "_get_installed_ollama_models",
        lambda ollama_host=None: ["deepseek-r1:32b"],
    )
    monkeypatch.setattr(
        model_selector_module,
        "_get_local_inventory_models",
        lambda ollama_host=None: [],
    )
    monkeypatch.setattr(
        model_selector_module,
        "_get_library_models",
        lambda: ["deepseek-r1:32b", "alia-40b-local:latest", "qwen2.5:32b"],
    )
    monkeypatch.setattr(
        model_selector_module,
        "_get_cloud_only_models",
        list,
    )

    models = model_selector_module.get_available_models_for_ui(
        ollama_host="http://127.0.0.1:11434",
        include_library_models=True,
    )

    assert "deepseek-r1:32b" in models
    assert "alia-40b-local" in models
    assert "qwen2.5:32b" in models


def test_get_library_models_uses_runtime_inventory(monkeypatch):
    monkeypatch.setattr(
        model_selector_module,
        "get_ollama_runtime_model_names",
        lambda: ["qwen3-30b-a3b:q4_k_m", "deepseek-r1:32b"],
    )

    assert model_selector_module._get_library_models() == [
        "qwen3-30b-a3b:q4_k_m",
        "deepseek-r1:32b",
    ]


def test_render_model_selector_prefills_manual_value_when_inventory_empty(monkeypatch):
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        model_selector_module,
        "get_available_models_for_ui",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        model_selector_module,
        "is_ollama_available",
        lambda ollama_host=None: True,
    )
    monkeypatch.setattr(
        st,
        "text_input",
        lambda label, value="", key=None, **kwargs: captured.setdefault("value", value) or value,
    )
    monkeypatch.setattr(st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(st, "caption", lambda *args, **kwargs: None)

    selected = model_selector_module.render_model_selector(
        key="builder_model_select",
        ollama_host="http://127.0.0.1:11434",
        current_value="alia-40b-local:latest",
    )

    assert captured["value"] == "alia-40b-local:latest"
    assert selected == "alia-40b-local:latest"


def test_render_model_selector_maps_current_value_to_available_option(monkeypatch):
    st.session_state.clear()
    monkeypatch.setattr(
        model_selector_module,
        "get_available_models_for_ui",
        lambda **kwargs: ["qwen2.5:14b", "alia-40b-local"],
    )
    monkeypatch.setattr(
        model_selector_module,
        "get_model_details",
        lambda model_name, ollama_host=None: {
            "name": model_name,
            "size_gb": 1.0,
            "vram_gb": 1.0,
            "parameters": "14B",
            "quantization": "Q4",
            "family": "test",
            "description": "",
            "backup_path": "",
            "context_length": 0,
            "fits_gpu": True,
        },
    )
    monkeypatch.setattr(
        st,
        "selectbox",
        lambda label, options, key=None, **kwargs: st.session_state[key],
    )

    selected = model_selector_module.render_model_selector(
        key="builder_model_select",
        current_value="alia-40b-local:latest",
        show_details=False,
    )

    assert st.session_state["builder_model_select"] == "alia-40b-local"
    assert selected == "alia-40b-local"


def test_get_model_details_does_not_guess_remote_gpu_fit(monkeypatch):
    monkeypatch.setattr(
        model_selector_module,
        "_fetch_ollama_details",
        lambda ollama_host=None: {
            "qwen2.5:14b": {
                "size_gb": 10.0,
                "parameters": "14B",
                "quantization": "Q4",
                "family": "qwen",
            },
        },
    )
    monkeypatch.setattr(model_selector_module, "get_model_by_id", lambda model_name: {})
    monkeypatch.setattr(model_selector_module, "_get_max_gpu_vram_gb", lambda: 24.0)

    remote = model_selector_module.get_model_details(
        "qwen2.5:14b",
        ollama_host="http://10.0.0.12:11434",
    )
    local = model_selector_module.get_model_details(
        "qwen2.5:14b",
        ollama_host="http://127.0.0.1:11434",
    )

    assert remote["fits_gpu"] is None
    assert local["fits_gpu"] is True


def test_get_model_details_exposes_catalog_display_name(monkeypatch):
    monkeypatch.setattr(
        model_selector_module,
        "_fetch_ollama_details",
        lambda ollama_host=None: {
            "nemotron-cascade-14b-local": {
                "size_gb": 14.6,
                "parameters": "14B",
                "quantization": "Q8_0",
                "family": "nemotron",
            },
        },
    )
    monkeypatch.setattr(
        model_selector_module,
        "get_model_by_id",
        lambda model_name: {
            "name": "Nemotron Cascade 14B Claude Opus Distill",
            "aliases": [
                "nemotron-cascade-14b-thinking-claude-4.5-opus-distill.q8_0:latest",
            ],
        },
    )

    details = model_selector_module.get_model_details("nemotron-cascade-14b-local")

    assert details["display_name"] == "Nemotron Cascade 14B Claude Opus Distill"
    assert "nemotron-cascade-14b-thinking-claude-4.5-opus-distill.q8_0:latest" in details["aliases"]
    formatted = model_selector_module._format_model_option(
        "nemotron-cascade-14b-local",
        details,
    )
    assert "Nemotron Cascade 14B Claude Opus Distill" in formatted
    assert "nemotron-cascade-14b-local" in formatted


def test_model_selector_reuses_single_inventory_fetch_for_names_and_details(monkeypatch):
    model_selector_module._ollama_inventory_cache.clear()
    requested_urls: list[str] = []
    current_time = {"value": 1_000.0}

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "models": [
                    {
                        "name": "qwen3-coder:30b",
                        "size": 10 * (1024**3),
                        "details": {
                            "parameter_size": "30B",
                            "quantization_level": "Q4_K_M",
                            "family": "qwen",
                            "format": "gguf",
                        },
                    },
                ],
            }

    def _fake_get(url, timeout=0):
        _ = timeout
        requested_urls.append(url)
        return _FakeResponse()

    monkeypatch.setattr(model_selector_module.time, "time", lambda: current_time["value"])

    import httpx

    monkeypatch.setattr(httpx, "get", _fake_get)

    names = model_selector_module._get_installed_ollama_models("http://127.0.0.1:11434")
    details = model_selector_module._fetch_ollama_details("http://127.0.0.1:11434")

    assert names == ["qwen3-coder:30b"]
    assert details["qwen3-coder:30b"]["parameters"] == "30B"
    assert requested_urls == ["http://127.0.0.1:11434/api/tags"]

    current_time["value"] += 10
    names_again = model_selector_module._get_installed_ollama_models("http://127.0.0.1:11434")
    details_again = model_selector_module._fetch_ollama_details("http://127.0.0.1:11434")

    assert names_again == names
    assert details_again == details
    assert requested_urls == ["http://127.0.0.1:11434/api/tags"]


def test_agent_timeline_round_trip_preserves_metrics_and_decisions():
    timeline = agent_timeline_module.AgentActivityTimeline("session")
    timeline.log_activity(
        agent_timeline_module.AgentType.ANALYST,
        agent_timeline_module.ActivityType.ANALYSIS,
        "analyse",
    )
    timeline.log_metrics(1.2, 0.15, 0.08, 0.6)
    timeline.log_decision(
        agent_timeline_module.AgentType.CRITIC,
        agent_timeline_module.DecisionType.APPROVE,
        "ok",
        confidence=0.9,
    )

    restored = agent_timeline_module.AgentActivityTimeline.from_dict(timeline.to_dict())

    assert len(restored.activities) == 1
    assert len(restored.metrics_history) == 1
    assert len(restored.decisions) == 1


def test_validation_report_without_windows_is_failed():
    report = validation_viewer_module.ValidationReport(
        strategy_name="demo",
        created_at=datetime.now(),
        windows=[],
    )

    assert report.overall_status is validation_viewer_module.ValidationStatus.FAILED
    assert report.is_valid is False


def test_sweep_progress_chart_uses_non_overlapping_counts():
    stats = sweep_monitor_module.SweepStats(
        total_combinations=10,
        evaluated=5,
        pruned=2,
        errors=1,
    )

    fig = sweep_monitor_module._create_progress_chart(stats)

    trace = cast(Any, fig.data[0])
    assert list(trace.labels) == ["Terminés", "Prunés", "Erreurs", "Restants"]
    assert list(trace.values) == [2, 2, 1, 5]


def test_system_monitor_reads_gpu_metrics_when_nvml_is_available(monkeypatch):
    fake_pynvml = SimpleNamespace(
        nvmlInit=lambda: None,
        nvmlDeviceGetCount=lambda: 1,
        nvmlDeviceGetHandleByIndex=lambda index: object(),
        nvmlDeviceGetUtilizationRates=lambda handle: SimpleNamespace(gpu=55),
        nvmlDeviceGetMemoryInfo=lambda handle: SimpleNamespace(
            used=4 * 1024**3,
            total=8 * 1024**3,
        ),
    )
    monkeypatch.setitem(__import__("sys").modules, "pynvml", fake_pynvml)
    monkeypatch.setattr(monitor_module, "PSUTIL_AVAILABLE", False)

    monitor = monitor_module.SystemMonitor()
    reading = monitor.get_current_reading()

    assert monitor.gpu_available is True
    assert reading.gpu_percent == 55
    assert reading.gpu_memory_percent == 50.0


def test_resolve_selector_current_value_prefers_widget_state_over_stale_explicit_value():
    st.session_state.clear()
    st.session_state["builder_model_select"] = "qwen2.5:32b"

    selected = model_selector_module._resolve_selector_current_value(
        "builder_model_select",
        explicit_current_value="deepseek-r1:32b",
    )

    assert selected == "qwen2.5:32b"


def test_choose_autonomous_objective_mode_keeps_llm_when_recent_runs_are_robust():
    history = [
        {
            "status": "success",
            "best_score": 41.0,
            "best_sharpe": 1.1,
            "best_return": 12.0,
            "best_max_dd": 28.0,
            "best_trades": 42,
        },
        {
            "status": "max_iterations",
            "best_score": 47.0,
            "best_sharpe": 1.3,
            "best_return": 18.0,
            "best_max_dd": 24.0,
            "best_trades": 58,
        },
    ]
    supervisor = {"consecutive_errors": 0}

    policy = _choose_autonomous_objective_mode("llm", history, supervisor)

    assert policy["mode"] == "llm"
    assert policy["reason"] == "requested"


def test_choose_autonomous_objective_mode_does_not_count_positive_failed_runs_as_failures():
    history = [
        {
            "status": "failed",
            "best_return": 6.5,
            "best_pf": 1.08,
            "best_trades": 18,
            "best_sharpe": 0.62,
        },
        {
            "status": "failed",
            "best_return": 4.0,
            "best_pf": 1.02,
            "best_trades": 12,
            "best_sharpe": 0.44,
        },
        {
            "status": "failed",
            "best_return": 11.0,
            "best_pf": 1.2,
            "best_trades": 28,
            "best_sharpe": 0.8,
        },
        {
            "status": "failed",
            "best_return": 2.5,
            "best_pf": 1.0,
            "best_trades": 10,
            "best_sharpe": 0.35,
        },
    ]
    supervisor = {"consecutive_errors": 0}

    policy = _choose_autonomous_objective_mode("llm", history, supervisor)

    assert policy["mode"] == "llm"
    assert policy["reason"] == "requested"


def test_choose_autonomous_objective_mode_keeps_llm_after_non_llm_incident():
    history = [
        {"status": "failed"},
        {"status": "failed"},
        {"status": "crash"},
        {"status": "failed"},
    ]
    supervisor = {
        "consecutive_errors": 2,
        "last_error_origin": "builder_backend",
    }

    policy = _choose_autonomous_objective_mode("llm", history, supervisor)

    assert policy["mode"] == "llm"
    assert policy["reason"] == "llm_preferred_non_llm_incident"


def test_classify_autonomous_failure_origin_detects_exact_name_runtime_mismatch():
    error = RuntimeError(
        "kimi-k2: L'hôte http://127.0.0.1:11434 est joignable, mais il rejette le nom exact kimi-k2.",
    )

    origin = _classify_autonomous_failure_origin(error)

    assert origin == "llm_runtime_model_name_mismatch"


def test_get_autonomous_recap_status_badge_marks_failed_positive_return_as_positive():
    badge = _get_autonomous_recap_status_badge(
        {
            "status": "failed",
            "best_return": 46.38,
            "best_max_dd": -18.0,
            "best_pf": 1.12,
            "best_trades": 24,
        },
    )

    assert badge == {"icon": "+", "label": "positif", "tone": "positive"}


def test_get_autonomous_recap_status_badge_marks_any_failed_positive_return_as_positive():
    badge = _get_autonomous_recap_status_badge(
        {
            "status": "failed",
            "best_return": 151.41,
            "best_max_dd": -70.71,
            "best_pf": 1.44,
            "best_trades": 32,
            "final_return": 151.41,
            "final_max_dd": -70.71,
        },
    )

    assert badge == {"icon": "+", "label": "positif", "tone": "positive"}


def test_get_autonomous_recap_status_badge_marks_fallback_best_positive_snapshot_as_positive():
    badge = _get_autonomous_recap_status_badge(
        {
            "source_label": "Fallback simple",
            "status": "failed",
            "best_return": 326.39,
            "best_max_dd": -35.11,
            "best_pf": 1.22,
            "best_trades": 475,
            "final_return": 0.0,
            "final_max_dd": 0.0,
        },
    )

    assert badge == {"icon": "+", "label": "positif", "tone": "positive"}


def test_get_autonomous_recap_status_badge_keeps_actual_success_as_success():
    badge = _get_autonomous_recap_status_badge(
        {
            "status": "success",
            "target_sharpe": 1.0,
            "best_return": 18.4,
            "best_return_sharpe": 1.22,
            "best_max_dd": -14.0,
            "best_pf": 1.16,
            "best_trades": 44,
        },
    )

    assert badge == {"icon": "✚", "label": "succes", "tone": "positive"}


def test_get_autonomous_recap_status_badge_marks_positive_best_despite_negative_final():
    badge = _get_autonomous_recap_status_badge(
        {
            "status": "failed",
            "best_return": 143.69,
            "final_return": -190.0,
            "best_max_dd": -37.34,
            "final_max_dd": -100.0,
        },
    )

    assert badge == {"icon": "+", "label": "positif", "tone": "positive"}


def test_get_autonomous_recap_status_badge_keeps_max_iterations_status_even_with_positive_best_return():
    badge = _get_autonomous_recap_status_badge(
        {"status": "max_iterations", "best_return": 12.5},
    )

    assert badge == {
        "icon": "⏱️",
        "label": "max_iterations",
        "tone": "neutral",
    }


def test_get_autonomous_recap_status_badge_marks_negative_return_with_red_minus():
    badge = _get_autonomous_recap_status_badge(
        {"status": "failed", "best_return": -9.55},
    )

    assert badge == {"icon": "−", "label": "negatif", "tone": "negative"}


def test_get_autonomous_recap_status_badge_marks_zero_failed_run_as_failure():
    badge = _get_autonomous_recap_status_badge(
        {"status": "failed", "best_return": 0.0},
    )

    assert badge == {"icon": "✖", "label": "echec", "tone": "crash"}


def test_get_autonomous_session_best_return_snapshot_prefers_max_return_iteration_over_best_score_iteration():
    session = SimpleNamespace(
        iterations=[
            SimpleNamespace(
                iteration=1,
                backtest_result=SimpleNamespace(
                    metrics={
                        "total_return_pct": -18.0,
                        "max_drawdown_pct": -12.0,
                        "profit_factor": 0.8,
                        "total_trades": 14,
                        "sharpe_ratio": -0.6,
                    },
                ),
            ),
            SimpleNamespace(
                iteration=4,
                backtest_result=SimpleNamespace(
                    metrics={
                        "total_return_pct": 2673.7760798420386,
                        "max_drawdown_pct": -91.5,
                        "profit_factor": 1.7,
                        "total_trades": 203,
                        "sharpe_ratio": 0.21,
                    },
                ),
            ),
        ],
        best_iteration=SimpleNamespace(
            iteration=1,
            backtest_result=SimpleNamespace(
                metrics={
                    "total_return_pct": -18.0,
                    "max_drawdown_pct": -12.0,
                    "profit_factor": 0.8,
                    "total_trades": 14,
                    "sharpe_ratio": -0.6,
                },
            ),
        ),
    )

    snapshot = builder_view_module._get_autonomous_session_best_return_snapshot(session)

    assert snapshot["best_return"] == 2673.7760798420386
    assert snapshot["best_return_iteration"] == 4
    assert snapshot["best_max_dd"] == -91.5
    assert snapshot["best_trades"] == 203


def test_get_autonomous_session_best_return_snapshot_falls_back_to_best_iteration_metrics_when_no_iteration_metrics_exist():
    session = SimpleNamespace(
        iterations=[SimpleNamespace(iteration=1, backtest_result=None)],
        best_iteration=SimpleNamespace(
            iteration=7,
            backtest_result=SimpleNamespace(
                metrics={
                    "total_return_pct": 14.2,
                    "max_drawdown_pct": -6.5,
                    "profit_factor": 1.3,
                    "total_trades": 28,
                    "sharpe_ratio": 1.8,
                },
            ),
        ),
    )

    snapshot = builder_view_module._get_autonomous_session_best_return_snapshot(session)

    assert snapshot == {
        "best_return": 14.2,
        "best_return_iteration": 7,
        "best_max_dd": -6.5,
        "best_pf": 1.3,
        "best_trades": 28,
        "best_return_sharpe": 1.8,
        "best_total_pnl": None,
    }


def test_recover_autonomous_history_entry_from_disk_restores_metrics_from_session_summary(tmp_path, monkeypatch):
    sandbox_root = tmp_path / "sandbox_strategies"
    session_dir = sandbox_root / "20260317_225241_strat_gie_sur_zkpusdc_30m_je_suis_d_sol"
    session_dir.mkdir(parents=True)
    (session_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "session_id": session_dir.name,
                "objective": "Strategie sur ZKPUSDC 30m. Exemple objectif.",
                "status": "running",
                "best_sharpe": 0.0,
                "best_score": -26.0,
                "timeframe": "30m",
                "n_bars": 48,
                "date_range_start": "2026-03-16 22:52:41",
                "date_range_end": "2026-03-17 22:52:41",
                "initial_capital": 10000.0,
                "last_runtime_error": "ValueError: recovered runtime",
                "last_runtime_error_iteration": 1,
                "last_runtime_traceback_tail": "Traceback recovered",
                "total_iterations": 1,
                "iterations": [
                    {
                        "iteration": 1,
                        "total_pnl": 0.0,
                        "return_pct": 0.0,
                        "max_drawdown_pct": 0.0,
                        "profit_factor": 1.0,
                        "trades": 0,
                        "sharpe": 0.0,
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(builder_view_module, "SANDBOX_ROOT", sandbox_root)
    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_runtime_state",
        lambda: {"last_session_id": session_dir.name},
    )

    entry = {
        "session_num": 907,
        "objective": "Strategie sur ZKPUSDC 30m. Exemple objectif.",
        "status": "error",
        "source_label": "LLM",
        "best_sharpe": None,
        "best_score": None,
        "best_return": None,
        "best_max_dd": None,
        "best_pf": None,
        "best_trades": None,
        "n_iterations": 0,
        "session_id": "",
    }

    recovered = builder_view_module._recover_autonomous_history_entry_from_disk(entry)

    assert recovered["session_id"] == session_dir.name
    assert recovered["n_iterations"] == 1
    assert recovered["best_return"] == 0.0
    assert recovered["final_return"] == 0.0
    assert recovered["final_iteration"] == 1
    assert recovered["final_total_pnl"] == 0.0
    assert recovered["initial_capital"] == 10000.0
    assert recovered["n_bars"] == 48
    assert recovered["best_score"] == -26.0
    assert recovered["last_runtime_error"] == "ValueError: recovered runtime"
    assert recovered["last_runtime_error_iteration"] == 1
    assert recovered["last_runtime_traceback_tail"] == "Traceback recovered"
    assert recovered["recovered_from_summary"] is True


def test_recover_autonomous_history_entry_from_disk_uses_runtime_checkpoint_without_summary(tmp_path, monkeypatch):
    sandbox_root = tmp_path / "sandbox_strategies"
    session_dir = sandbox_root / "20260410_080512_checkpoint_only"
    session_dir.mkdir(parents=True)
    (session_dir / "runtime_checkpoint.json").write_text(
        json.dumps(
            {
                "session_id": session_dir.name,
                "objective": "Strategie sur XRPUSDC 1h. Exemple objectif.",
                "iteration": 1,
                "stage": "save_and_load",
                "status": "error",
                "error": "RuntimeError: checkpoint recovered",
                "traceback_tail": "Traceback checkpoint recovered",
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(builder_view_module, "SANDBOX_ROOT", sandbox_root)
    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_runtime_state",
        lambda: {"last_session_id": session_dir.name},
    )

    entry = {
        "session_num": 908,
        "objective": "Strategie sur XRPUSDC 1h. Exemple objectif.",
        "status": "crash",
        "source_label": "LLM",
        "best_sharpe": None,
        "best_score": None,
        "best_return": None,
        "best_max_dd": None,
        "best_pf": None,
        "best_trades": None,
        "n_iterations": 0,
        "session_id": "",
    }

    recovered = builder_view_module._recover_autonomous_history_entry_from_disk(entry)

    assert recovered["session_id"] == session_dir.name
    assert recovered["last_runtime_error"] == "RuntimeError: checkpoint recovered"
    assert recovered["last_runtime_error_iteration"] == 1
    assert recovered["last_runtime_traceback_tail"] == "Traceback checkpoint recovered"
    assert recovered["recovered_from_runtime_checkpoint"] is True


def test_render_autonomous_recap_recovers_empty_entry_from_disk(tmp_path, monkeypatch):
    st.session_state.clear()
    sandbox_root = tmp_path / "sandbox_strategies"
    session_dir = sandbox_root / "20260317_225241_strat_gie_sur_zkpusdc_30m_je_suis_d_sol"
    session_dir.mkdir(parents=True)
    (session_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "session_id": session_dir.name,
                "objective": "Strategie sur ZKPUSDC 30m. Exemple objectif.",
                "status": "running",
                "best_sharpe": 0.0,
                "best_score": -26.0,
                "timeframe": "30m",
                "n_bars": 48,
                "date_range_start": "2026-03-16 22:52:41",
                "date_range_end": "2026-03-17 22:52:41",
                "initial_capital": 10000.0,
                "total_iterations": 1,
                "iterations": [
                    {
                        "iteration": 1,
                        "total_pnl": 0.0,
                        "return_pct": 0.0,
                        "max_drawdown_pct": 0.0,
                        "profit_factor": 1.0,
                        "trades": 0,
                        "sharpe": 0.0,
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(builder_view_module, "SANDBOX_ROOT", sandbox_root)
    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_runtime_state",
        lambda: {"last_session_id": session_dir.name},
    )
    monkeypatch.setattr(
        builder_view_module,
        "_save_autonomous_supervisor_state",
        lambda *args, **kwargs: None,
    )

    rendered_html = []
    download_payloads = []

    monkeypatch.setattr(builder_view_module.st, "markdown", lambda text, **kwargs: rendered_html.append(str(text)))
    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder_view_module.st,
        "download_button",
        lambda *args, **kwargs: download_payloads.append(kwargs.get("data")),
    )

    class _DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(builder_view_module.st, "columns", lambda *args, **kwargs: (_DummyColumn(), _DummyColumn()))
    monkeypatch.setattr(builder_view_module.st, "button", lambda *args, **kwargs: False)

    history = [
        {
            "session_num": 907,
            "objective": "Strategie sur ZKPUSDC 30m. Exemple objectif.",
            "source_label": "LLM",
            "status": "error",
            "best_score": None,
            "best_sharpe": None,
            "best_return": None,
            "best_max_dd": None,
            "best_trades": None,
            "duration": 8.0,
            "symbol": "ZKPUSDC",
            "timeframe": "30m",
            "session_id": "",
            "n_iterations": 0,
        },
    ]

    builder_view_module._render_autonomous_recap(history, {})

    assert any("+0.00%" in html or "0.00%" in html for html in rendered_html)
    assert any("22:52:41" in html for html in rendered_html)
    assert download_payloads
    assert session_dir.name in str(download_payloads[0])


def test_render_autonomous_recap_renders_empty_table_shell(monkeypatch):
    st.session_state.clear()
    rendered_html = []
    captured_tabs = []
    info_messages = []

    monkeypatch.setattr(
        builder_view_module,
        "_save_autonomous_supervisor_state",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(builder_view_module, "_load_autonomous_runtime_state", dict)
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda text, **kwargs: rendered_html.append(str(text)))
    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "info", lambda message, *args, **kwargs: info_messages.append(str(message)))
    monkeypatch.setattr(
        builder_view_module.st,
        "download_button",
        lambda *args, **kwargs: pytest.fail("export should not be rendered without history"),
    )

    class _DummyContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(builder_view_module.st, "columns", lambda *args, **kwargs: (_DummyColumn(), _DummyColumn()))
    monkeypatch.setattr(builder_view_module.st, "button", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        builder_view_module.st,
        "tabs",
        lambda labels: captured_tabs.append(list(labels)) or [_DummyContext() for _ in labels],
    )
    monkeypatch.setattr(
        builder_view_module,
        "_render_builder_live_thoughts_panel",
        lambda *args, **kwargs: None,
    )

    builder_view_module._render_autonomous_recap([], {"soft_reset_count": 0})

    joined_html = "\n".join(rendered_html)
    assert captured_tabs == [["Vue d'ensemble", "Historique (0)", "Pensées en direct"]]
    assert "Aucune session enregistrée pour le moment." in joined_html
    assert "<table class=\"builder-autonomous-recap-table\">" in joined_html
    assert info_messages == ["Aucune session autonome enregistrée pour le moment."]


def test_load_builder_live_thoughts_preview_tails_file(tmp_path):
    stream_file = tmp_path / "_live_thoughts.md"
    stream_file.write_text(
        "\n".join(f"line {idx}" for idx in range(1, 11)),
        encoding="utf-8",
    )

    preview, truncated = builder_view_module._load_builder_live_thoughts_preview(
        stream_file,
        tail_lines=4,
        max_chars=1000,
    )

    assert truncated is True
    preview_lines = preview.splitlines()
    assert preview_lines[0] == "…(truncated)…"
    assert preview_lines[1:] == ["line 7", "line 8", "line 9", "line 10"]


def test_load_builder_live_thoughts_preview_masks_unexpected_session(tmp_path):
    stream_file = tmp_path / "_live_thoughts.md"
    stream_file.write_text(
        "\n".join(
            [
                "====================================================================",
                "  STRATEGY BUILDER - Flux live canonique",
                "  SESSION  : old_session",
                "[STREAM] CODE payload ancien",
            ]
        ),
        encoding="utf-8",
    )

    preview, truncated = builder_view_module._load_builder_live_thoughts_preview(
        stream_file,
        expected_session_id="new_session",
    )

    assert truncated is False
    assert "old_session" in preview
    assert "new_session" in preview
    assert "payload ancien" not in preview


def test_render_builder_live_thoughts_panel_rereads_latest_file(
    monkeypatch,
    tmp_path,
):
    captured = {"code": []}
    stream_file = tmp_path / "_live_thoughts.md"
    stream_file.write_text("version 1", encoding="utf-8")

    class _DummyContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(builder_view_module, "STREAM_FILE", stream_file)
    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder_view_module.st,
        "code",
        lambda text, **kwargs: captured["code"].append(str(text)),
    )
    monkeypatch.setattr(
        builder_view_module.st,
        "expander",
        lambda *args, **kwargs: _DummyContext(),
    )

    builder_view_module._render_builder_live_thoughts_panel(
        title="Live stream",
        expanded=False,
        show_terminal_command=False,
        tail_lines=20,
    )
    stream_file.write_text("version 2", encoding="utf-8")
    builder_view_module._render_builder_live_thoughts_panel(
        title="Live stream",
        expanded=False,
        show_terminal_command=False,
        tail_lines=20,
    )

    assert captured["code"] == ["version 1", "version 2"]


def test_reset_inactive_builder_live_thoughts_clears_stale_file(monkeypatch, tmp_path):
    st.session_state.clear()
    st.session_state["is_running"] = True
    stream_file = tmp_path / "_live_thoughts.md"
    stream_file.write_text("stale session payload", encoding="utf-8")

    monkeypatch.setattr(builder_view_module, "STREAM_FILE", stream_file)
    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_runtime_state",
        lambda: {
            "active": False,
            "manual_stop": False,
            "last_session_id": "session_stale",
        },
    )

    builder_view_module.reset_inactive_builder_live_thoughts(
        reason="test_idle",
        respect_session_running=False,
    )

    rendered = stream_file.read_text(encoding="utf-8")
    assert "Aucun flux live actif" in rendered
    assert "session_stale" in rendered
    assert "test_idle" in rendered
    assert "_live_thoughts_code_slot" not in st.session_state


def test_reset_inactive_builder_live_thoughts_keeps_active_file(monkeypatch, tmp_path):
    st.session_state.clear()
    stream_file = tmp_path / "_live_thoughts.md"
    stream_file.write_text("active session payload", encoding="utf-8")

    monkeypatch.setattr(builder_view_module, "STREAM_FILE", stream_file)
    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_runtime_state",
        lambda: {
            "active": True,
            "manual_stop": False,
            "run_id": "run-active",
            **builder_view_module._current_runtime_owner_fields(),
        },
    )
    st.session_state[builder_view_module._BUILDER_AUTONOMOUS_RUN_ID_STATE_KEY] = "run-active"

    builder_view_module._reset_inactive_builder_live_thoughts(reason="test_idle")

    assert stream_file.read_text(encoding="utf-8") == "active session payload"


def test_mark_builder_autonomous_runtime_started_replaces_legacy_active_claim(
    monkeypatch,
    tmp_path,
):
    st.session_state.clear()
    runtime_file = tmp_path / "_autonomous_runtime_state.json"
    stream_file = tmp_path / "_live_thoughts.md"
    stream_file.write_text("stale live payload", encoding="utf-8")
    runtime_file.write_text(
        json.dumps(
            {
                "runtime": {
                    "version": "1.0",
                    "active": True,
                    "manual_stop": False,
                    "started_at": "2026-04-26T19:44:04+00:00",
                    "last_heartbeat_at": "2026-05-02T18:40:46+00:00",
                    "last_session_id": "old_session",
                    "pid": os.getpid(),
                    "resume_count": 67,
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(builder_view_module, "_AUTONOMOUS_RUNTIME_STATE_FILE", runtime_file)
    monkeypatch.setattr(builder_view_module, "STREAM_FILE", stream_file)

    runtime = builder_view_module._mark_builder_autonomous_runtime_started(
        model="qwen3.6:35b",
        ollama_host="http://127.0.0.1:11434",
        requested_source_mode="llm",
        auto_market_pick=True,
        resume_ui_state={"builder_universe_mode": "canonical"},
    )

    assert runtime["active"] is True
    assert runtime["run_id"]
    assert runtime["started_at"] != "2026-04-26T19:44:04+00:00"
    assert runtime["last_session_id"] == ""
    assert runtime["current_session_id"] == ""
    assert runtime["owner_pid"] == os.getpid()
    assert runtime["resume_count"] == 0
    assert "stale live payload" not in stream_file.read_text(encoding="utf-8")


def test_heartbeat_builder_autonomous_runtime_ignores_foreign_claim(
    monkeypatch,
    tmp_path,
):
    st.session_state.clear()
    runtime_file = tmp_path / "_autonomous_runtime_state.json"
    runtime_file.write_text(
        json.dumps(
            {
                "runtime": {
                    "version": "1.0",
                    "active": True,
                    "manual_stop": False,
                    "run_id": "foreign-run",
                    "claim_source": "streamlit",
                    "owner_pid": 424242,
                    "owner_signature": "424242:foreign",
                    "last_event": "foreign_active",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(builder_view_module, "_AUTONOMOUS_RUNTIME_STATE_FILE", runtime_file)

    runtime = builder_view_module._heartbeat_builder_autonomous_runtime(
        last_event="should_not_overwrite",
    )

    payload = json.loads(runtime_file.read_text(encoding="utf-8"))["runtime"]
    assert runtime["last_event"] == "foreign_active"
    assert payload["last_event"] == "foreign_active"


def test_render_autonomous_recap_wraps_heavy_sections_in_tabs_and_expanders(monkeypatch, tmp_path):
    st.session_state.clear()
    captured = {"tabs": [], "expanders": [], "code": []}
    stream_file = tmp_path / "_live_thoughts.md"
    stream_file.write_text("[STREAM] CODE Generation de code\npayload", encoding="utf-8")

    monkeypatch.setattr(builder_view_module, "STREAM_FILE", stream_file)
    monkeypatch.setattr(
        builder_view_module,
        "_save_autonomous_supervisor_state",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "download_button", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder_view_module.st,
        "code",
        lambda text, **kwargs: captured["code"].append(str(text)),
    )

    class _DummyContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        builder_view_module.st,
        "tabs",
        lambda labels: captured["tabs"].append(list(labels)) or [_DummyContext() for _ in labels],
    )
    monkeypatch.setattr(
        builder_view_module.st,
        "expander",
        lambda label, **kwargs: captured["expanders"].append(str(label)) or _DummyContext(),
    )
    monkeypatch.setattr(
        builder_view_module.st,
        "columns",
        lambda *args, **kwargs: (_DummyContext(), _DummyContext()),
    )
    monkeypatch.setattr(builder_view_module.st, "button", lambda *args, **kwargs: False)

    history = [
        {
            "session_num": 12,
            "objective": "Objectif 12",
            "source_label": "LLM",
            "status": "success",
            "best_score": 12.0,
            "best_sharpe": 1.05,
            "best_return": 8.4,
            "best_max_dd": -4.0,
            "best_trades": 18,
            "duration": 9.0,
            "symbol": "BTCUSDC",
            "timeframe": "1h",
        },
    ]

    builder_view_module._render_autonomous_recap(history, {})

    assert captured["tabs"][0] == ["Vue d'ensemble", "Historique (1)", "Pensées en direct"]
    # The history table is now rendered directly inside the dedicated tab,
    # without an additional inner expander.
    assert "Flux de pensée live" in captured["expanders"]
    assert any("Get-Content" in text for text in captured["code"])
    assert any("Generation de code" in text for text in captured["code"])


def test_recover_autonomous_history_from_disk_reports_changed_when_entry_rehydrated(tmp_path, monkeypatch):
    sandbox_root = tmp_path / "sandbox_strategies"
    session_dir = sandbox_root / "20260317_225241_strat_gie_sur_zkpusdc_30m_je_suis_d_sol"
    session_dir.mkdir(parents=True)
    (session_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "session_id": session_dir.name,
                "objective": "Strategie sur ZKPUSDC 30m. Exemple objectif.",
                "status": "running",
                "best_sharpe": 0.0,
                "best_score": -26.0,
                "timeframe": "30m",
                "n_bars": 48,
                "date_range_start": "2026-03-16 22:52:41",
                "date_range_end": "2026-03-17 22:52:41",
                "initial_capital": 10000.0,
                "total_iterations": 1,
                "iterations": [
                    {
                        "iteration": 1,
                        "total_pnl": 0.0,
                        "return_pct": 0.0,
                        "max_drawdown_pct": 0.0,
                        "profit_factor": 1.0,
                        "trades": 0,
                        "sharpe": 0.0,
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(builder_view_module, "SANDBOX_ROOT", sandbox_root)
    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_runtime_state",
        lambda: {"last_session_id": session_dir.name},
    )

    history = [
        {
            "session_num": 907,
            "objective": "Strategie sur ZKPUSDC 30m. Exemple objectif.",
            "status": "error",
            "source_label": "LLM",
            "best_sharpe": None,
            "best_score": None,
            "best_return": None,
            "best_max_dd": None,
            "best_pf": None,
            "best_trades": None,
            "n_iterations": 0,
            "session_id": "",
        },
    ]

    recovered_history, changed = builder_view_module._recover_autonomous_history_from_disk(history)

    assert changed is True
    assert recovered_history[0]["session_id"] == session_dir.name
    assert recovered_history[0]["best_return"] == 0.0
    assert recovered_history[0]["final_return"] == 0.0


def test_render_autonomous_recap_persists_recovered_history_to_supervisor_state(tmp_path, monkeypatch):
    st.session_state.clear()
    sandbox_root = tmp_path / "sandbox_strategies"
    session_dir = sandbox_root / "20260317_225241_strat_gie_sur_zkpusdc_30m_je_suis_d_sol"
    session_dir.mkdir(parents=True)
    (session_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "session_id": session_dir.name,
                "objective": "Strategie sur ZKPUSDC 30m. Exemple objectif.",
                "status": "running",
                "best_sharpe": 0.0,
                "best_score": -26.0,
                "timeframe": "30m",
                "n_bars": 48,
                "date_range_start": "2026-03-16 22:52:41",
                "date_range_end": "2026-03-17 22:52:41",
                "initial_capital": 10000.0,
                "total_iterations": 1,
                "iterations": [
                    {
                        "iteration": 1,
                        "total_pnl": 0.0,
                        "return_pct": 0.0,
                        "max_drawdown_pct": 0.0,
                        "profit_factor": 1.0,
                        "trades": 0,
                        "sharpe": 0.0,
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(builder_view_module, "SANDBOX_ROOT", sandbox_root)
    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_runtime_state",
        lambda: {"last_session_id": session_dir.name},
    )

    captured_save = {}
    monkeypatch.setattr(
        builder_view_module,
        "_save_autonomous_supervisor_state",
        lambda history, supervisor: captured_save.update({"history": list(history), "supervisor": dict(supervisor)}),
    )
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "download_button", lambda *args, **kwargs: None)

    class _DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(builder_view_module.st, "columns", lambda *args, **kwargs: (_DummyColumn(), _DummyColumn()))
    monkeypatch.setattr(builder_view_module.st, "button", lambda *args, **kwargs: False)

    history = [
        {
            "session_num": 907,
            "objective": "Strategie sur ZKPUSDC 30m. Exemple objectif.",
            "source_label": "LLM",
            "status": "error",
            "best_score": None,
            "best_sharpe": None,
            "best_return": None,
            "best_max_dd": None,
            "best_trades": None,
            "duration": 8.0,
            "symbol": "ZKPUSDC",
            "timeframe": "30m",
            "session_id": "",
            "n_iterations": 0,
        },
    ]

    builder_view_module._render_autonomous_recap(history, {"consecutive_errors": 0})

    assert captured_save["history"][0]["session_id"] == session_dir.name
    assert captured_save["history"][0]["best_return"] == 0.0
    assert captured_save["history"][0]["final_return"] == 0.0


def test_render_autonomous_recap_uses_unique_export_key_after_history_cap(monkeypatch):
    st.session_state.clear()
    captured = {"captions": [], "keys": []}

    monkeypatch.setattr(
        builder_view_module,
        "_save_autonomous_supervisor_state",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(builder_view_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder_view_module.st,
        "caption",
        lambda text: captured["captions"].append(str(text)),
    )
    monkeypatch.setattr(builder_view_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder_view_module.st,
        "download_button",
        lambda *args, **kwargs: captured["keys"].append(kwargs.get("key")),
    )
    history = [
        {
            "session_num": session_num,
            "objective": f"Objectif {session_num}",
            "source_label": "LLM",
            "status": "success",
            "best_score": 42.0,
            "best_sharpe": 1.25,
            "best_return": 12.5,
            "best_max_dd": -9.5,
            "best_trades": 32,
            "duration": 18.0,
            "symbol": "BTCUSDC",
            "timeframe": "1h",
        }
        for session_num in range(568, 1568)
    ]

    builder_view_module._render_autonomous_recap(history, {})
    builder_view_module._render_autonomous_recap(history, {})

    assert captured["keys"][0] != captured["keys"][1]
    assert any("1000 sessions affichées sur 1567 exécutées" in caption for caption in captured["captions"])


def test_render_autonomous_recap_uses_unique_reset_button_key_on_multiple_renders(monkeypatch):
    st.session_state.clear()
    captured_keys = []

    monkeypatch.setattr(
        builder_view_module,
        "_save_autonomous_supervisor_state",
        lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(builder_view_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "download_button", lambda *args, **kwargs: None)

    class _DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(builder_view_module.st, "columns", lambda *args, **kwargs: (_DummyColumn(), _DummyColumn()))
    monkeypatch.setattr(
        builder_view_module.st,
        "button",
        lambda *args, **kwargs: captured_keys.append(kwargs.get("key")) or False,
    )

    history = [
        {
            "session_num": 1,
            "objective": "Objectif 1",
            "source_label": "LLM",
            "status": "success",
            "best_score": 10.0,
            "best_sharpe": 1.0,
            "best_return": 5.0,
            "best_max_dd": -3.0,
            "best_trades": 12,
            "duration": 8.0,
            "symbol": "EURUSDC",
            "timeframe": "4h",
        },
    ]

    builder_view_module._render_autonomous_recap(history, {})
    builder_view_module._render_autonomous_recap(history, {})

    assert len(captured_keys) == 2
    assert captured_keys[0] != captured_keys[1]


def test_render_autonomous_recap_exposes_full_objective_and_generation_legend(monkeypatch):
    st.session_state.clear()
    rendered_html = []

    monkeypatch.setattr(
        builder_view_module,
        "_save_autonomous_supervisor_state",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda text, **kwargs: rendered_html.append(str(text)))
    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "download_button", lambda *args, **kwargs: None)

    class _DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(builder_view_module.st, "columns", lambda *args, **kwargs: (_DummyColumn(), _DummyColumn()))
    monkeypatch.setattr(builder_view_module.st, "button", lambda *args, **kwargs: False)

    long_objective = (
        "Objectif de strategie sur ETHUSDC 1h. Utiliser ATR, EMA et RSI pour capter "
        "les reprises de tendance apres respiration, avec confirmation de momentum, "
        "filtre de volatilite et gestion explicite des sorties progressives."
    )
    history = [
        {
            "session_num": 1,
            "objective": long_objective,
            "source_label": "Fallback simple",
            "status": "success",
            "best_score": 12.5,
            "best_sharpe": 1.02,
            "best_return": 8.0,
            "best_max_dd": -4.0,
            "best_trades": 16,
            "duration": 12.0,
            "symbol": "ETHUSDC",
            "timeframe": "1h",
        },
    ]

    builder_view_module._render_autonomous_recap(history, {})

    joined_html = "\n".join(rendered_html)
    assert "📜 Voir les objectifs complets" in joined_html
    assert "Objectif complet" in joined_html
    assert "filtre de volatilite et gestion explicite des sorties progressives." in joined_html
    assert "builder-autonomous-recap-objective-trigger" in joined_html
    assert "builder-autonomous-recap-objective-full" in joined_html
    assert "Fallback simple</strong> = objectif de secours produit par le runtime" in joined_html


def test_render_autonomous_recap_displays_persisted_session_num_instead_of_row_index(monkeypatch):
    st.session_state.clear()
    rendered_html = []

    monkeypatch.setattr(
        builder_view_module,
        "_save_autonomous_supervisor_state",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda text, **kwargs: rendered_html.append(str(text)))
    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "download_button", lambda *args, **kwargs: None)

    class _DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(builder_view_module.st, "columns", lambda *args, **kwargs: (_DummyColumn(), _DummyColumn()))
    monkeypatch.setattr(builder_view_module.st, "button", lambda *args, **kwargs: False)

    history = [
        {
            "session_num": 672,
            "objective": "Objectif 672",
            "source_label": "LLM",
            "status": "failed",
            "best_score": -26.0,
            "best_sharpe": 0.0,
            "best_return": 0.0,
            "best_max_dd": 0.0,
            "best_trades": 0,
            "duration": 1.0,
            "symbol": "BTCUSDC",
            "timeframe": "1h",
        },
        {
            "session_num": 700,
            "objective": "Objectif 700",
            "source_label": "Fallback simple",
            "status": "max_iterations",
            "best_score": 100.0,
            "best_sharpe": 0.829,
            "best_return": 12.0,
            "best_max_dd": -8.0,
            "best_trades": 14,
            "duration": 5.0,
            "symbol": "ETHUSDC",
            "timeframe": "4h",
        },
    ]

    builder_view_module._render_autonomous_recap(history, {})

    joined_html = "\n".join(rendered_html)
    assert "<th>Session</th>" in joined_html
    assert "Objectif 672" in joined_html
    assert "Objectif 700" in joined_html
    assert ">672</td>" in joined_html
    assert ">700</td>" in joined_html
    assert ">1</td>" not in joined_html
    assert ">2</td>" not in joined_html


def test_render_autonomous_recap_uses_best_metrics_and_negative_status_without_positive_run(monkeypatch):
    st.session_state.clear()
    rendered_html = []

    monkeypatch.setattr(
        builder_view_module,
        "_save_autonomous_supervisor_state",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda text, **kwargs: rendered_html.append(str(text)))
    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "download_button", lambda *args, **kwargs: None)

    class _DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(builder_view_module.st, "columns", lambda *args, **kwargs: (_DummyColumn(), _DummyColumn()))
    monkeypatch.setattr(builder_view_module.st, "button", lambda *args, **kwargs: False)

    history = [
        {
            "session_num": 1716,
            "session_id": "20260322_175658_strat_gie_de_breakout_sur_egldusdc_5m_in",
            "objective": "Objectif 1716",
            "source_label": "Fallback simple",
            "status": "failed",
            "best_score": -26.0,
            "best_sharpe": 0.0,
            "best_return": 0.0,
            "best_max_dd": 0.0,
            "best_trades": 0,
            "final_sharpe": -20.0,
            "final_return": -2808.48,
            "final_max_dd": -100.0,
            "final_trades": 8214,
            "duration": 7112.0,
            "symbol": "EGLDUSDC",
            "timeframe": "5m",
        },
    ]

    builder_view_module._render_autonomous_recap(history, {})

    joined_html = "\n".join(rendered_html)
    assert "<th>Date/heure</th>" in joined_html
    assert 'title="Meilleur Sharpe atteint pendant la session (best run)">Sharpe</th>' in joined_html
    assert 'title="Meilleur return atteint pendant la session (best run)">Return</th>' in joined_html
    assert "22/03/2026 17:56:58" in joined_html
    assert "+0.00%" in joined_html
    assert "0.00%" in joined_html
    assert ">0</td>" in joined_html
    assert "− negatif" in joined_html


def test_render_autonomous_recap_marks_positive_best_run_even_when_final_regresses(monkeypatch):
    st.session_state.clear()
    rendered_html = []

    monkeypatch.setattr(
        builder_view_module,
        "_save_autonomous_supervisor_state",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda text, **kwargs: rendered_html.append(str(text)))
    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "download_button", lambda *args, **kwargs: None)

    class _DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(builder_view_module.st, "columns", lambda *args, **kwargs: (_DummyColumn(), _DummyColumn()))
    monkeypatch.setattr(builder_view_module.st, "button", lambda *args, **kwargs: False)

    history = [
        {
            "session_num": 344,
            "session_id": "20260512_080741_xrpusdc",
            "objective": "Objectif XRPUSDC avec run positif puis regression finale",
            "source_label": "LLM",
            "status": "failed",
            "best_sharpe": 0.468,
            "best_return": 143.69,
            "best_max_dd": -37.34,
            "best_trades": 51,
            "final_sharpe": -20.0,
            "final_return": -190.0,
            "final_max_dd": -100.0,
            "duration": 370.0,
            "symbol": "XRPUSDC",
            "timeframe": "1d",
        },
    ]

    builder_view_module._render_autonomous_recap(history, {})

    joined_html = "\n".join(rendered_html)
    assert "+ positif" in joined_html
    assert "+143.69%" in joined_html
    assert "↓ -190%" in joined_html
    assert "− negatif" not in joined_html


def test_render_autonomous_recap_displays_gain_total_days_and_gain_per_day_for_positive_completed_runs(monkeypatch):
    st.session_state.clear()
    rendered_html = []

    monkeypatch.setattr(
        builder_view_module,
        "_save_autonomous_supervisor_state",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda text, **kwargs: rendered_html.append(str(text)))
    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "json", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "download_button", lambda *args, **kwargs: None)

    class _DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(builder_view_module.st, "columns", lambda *args, **kwargs: (_DummyColumn(), _DummyColumn()))
    monkeypatch.setattr(builder_view_module.st, "button", lambda *args, **kwargs: False)

    history = [
        {
            "session_num": 1622,
            "session_id": "20260322_120000_strategie_positive_paxgusdc",
            "objective": "Objectif 1622",
            "source_label": "Fallback simple",
            "status": "success",
            "best_score": 100.0,
            "best_sharpe": 1.309,
            "best_return": 152.81,
            "best_max_dd": -14.08,
            "best_trades": 3,
            "final_sharpe": 1.309,
            "final_return": 152.81,
            "final_total_pnl": 15281.0,
            "final_max_dd": -14.08,
            "final_trades": 3,
            "initial_capital": 10000.0,
            "n_bars": 24,
            "date_range_start": "2026-03-01 00:00:00",
            "date_range_end": "2026-03-13 00:00:00",
            "duration": 903.0,
            "symbol": "PAXGUSDC",
            "timeframe": "1h",
        },
    ]

    builder_view_module._render_autonomous_recap(history, {})

    joined_html = "\n".join(rendered_html)
    assert "Gain total $</th>" in joined_html
    assert "Jours testes</th>" in joined_html
    assert "$ / jour</th>" in joined_html
    assert "+15 281.00" in joined_html
    assert ">12.0</td>" in joined_html
    assert "+1 273.42" in joined_html


def test_trim_autonomous_history_keeps_last_1000_runs():
    trimmed = builder_view_module._trim_autonomous_history(
        [{"session_num": session_num} for session_num in range(1, 1002)],
    )

    assert len(trimmed) == 1000
    assert trimmed[0]["session_num"] == 2
    assert trimmed[-1]["session_num"] == 1001


def test_resolve_autonomous_session_counter_seed_prefers_latest_runtime_value():
    seed = builder_view_module._resolve_autonomous_session_counter_seed(
        [{"session_num": 567}],
        {"last_session_num": 572},
    )

    assert seed == 572


def test_get_builder_code_provenance_badge_detects_runtime_fix_fallback():
    badge = _get_builder_code_provenance_badge(
        {
            "code": {"source": "llm"},
            "backtest": {"runtime_fix_fallback_deterministic_used": True},
        },
    )

    assert badge["kind"] == "runtime_fix_fallback"
    assert "fallback" in badge["badge"].lower()


def test_get_builder_code_provenance_badge_detects_retry_code_origin():
    badge = _get_builder_code_provenance_badge(
        {
            "code": {
                "source": "retry_code",
                "realign_attempts": 1,
            },
        },
    )

    assert badge["kind"] == "retry"
    assert "corrig" in badge["detail"].lower()


def test_render_iteration_card_surfaces_provenance_badge(monkeypatch):
    captured_badges = []

    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "error", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "metric", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "code", lambda *args, **kwargs: None)

    class _DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        builder_view_module.st,
        "columns",
        lambda count, *args, **kwargs: tuple(_DummyColumn() for _ in range(int(count))),
    )
    monkeypatch.setattr(builder_view_module.st, "expander", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        builder_view_module,
        "_render_builder_badge_row",
        lambda labels: captured_badges.append(list(labels)),
    )

    iteration = SimpleNamespace(
        iteration=3,
        decision="continue",
        error=None,
        diagnostic_detail={},
        phase_feedback={
            "code": {"source": "retry_code"},
            "backtest": {},
        },
        backtest_result=SimpleNamespace(
            metrics={
                "sharpe_ratio": 1.2,
                "total_return_pct": 8.5,
                "max_drawdown_pct": -4.0,
                "total_trades": 17,
                "win_rate_pct": 52.0,
                "profit_factor": 1.3,
                "sortino_ratio": 1.6,
                "expectancy": 0.12,
            },
        ),
        diagnostic_category="",
        change_type="",
        hypothesis="",
        analysis="",
        code="",
    )

    builder_view_module.render_iteration_card(iteration)

    assert any(any("LLM corrigé" in label for label in labels) for labels in captured_badges)


def test_render_session_summary_surfaces_best_result_provenance_badge(monkeypatch):
    captured_badges = []

    monkeypatch.setattr(builder_view_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "metric", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "code", lambda *args, **kwargs: None)
    monkeypatch.setattr(builder_view_module.st, "expander", lambda *args, **kwargs: nullcontext())

    class _DummyColumn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        builder_view_module.st,
        "columns",
        lambda count, *args, **kwargs: tuple(_DummyColumn() for _ in range(int(count))),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_render_builder_badge_row",
        lambda labels: captured_badges.append(list(labels)),
    )

    best_iteration = SimpleNamespace(
        backtest_result=SimpleNamespace(
            metrics={
                "sharpe_ratio": 1.8,
                "total_return_pct": 14.2,
                "max_drawdown_pct": -6.5,
                "win_rate_pct": 48.0,
            },
        ),
        hypothesis="",
        code="",
        phase_feedback={
            "code": {"source": "llm"},
            "backtest": {"runtime_fix_applied": True},
        },
    )
    session = SimpleNamespace(
        status="success",
        best_sharpe=1.8,
        best_score=57.0,
        iterations=[],
        best_iteration=best_iteration,
        auto_reset_count=0,
        session_dir=None,
    )

    builder_view_module.render_session_summary(session)

    assert any(any("Runtime-fix" in label for label in labels) for labels in captured_badges)


def test_save_autonomous_supervisor_state_serializes_timestamps(monkeypatch, tmp_path):
    state_file = tmp_path / "autonomous_supervisor_state.json"
    monkeypatch.setattr(
        builder_view_module,
        "_AUTONOMOUS_SUPERVISOR_STATE_FILE",
        state_file,
    )

    builder_view_module._save_autonomous_supervisor_state(
        history=[
            {
                "session_num": 1,
                "objective": "Test",
                "started_at": pd.Timestamp("2026-03-14T20:29:00Z"),
            },
        ],
        supervisor={
            "last_error": pd.Timestamp("2026-03-14T20:29:00Z"),
        },
    )

    assert state_file.exists()
    assert "2026-03-14 20:29:00+00:00" in state_file.read_text(encoding="utf-8")


def test_classify_autonomous_failure_origin_detects_llm_runtime():
    exc = RuntimeError("httpx.ConnectError while contacting Ollama")
    origin = _classify_autonomous_failure_origin(
        exc,
        'File "ui/builder_view.py", line 1',
    )
    assert origin == "llm_runtime"


def test_plan_autonomous_recovery_disables_auto_market_on_market_failures():
    supervisor = {"soft_reset_count": 0}
    plan = _plan_autonomous_recovery(
        "market_selection",
        history=[],
        supervisor=supervisor,
        current_source_mode="llm",
    )

    assert plan["recover"] is True
    assert plan["disable_auto_market_pick_once"] is True
    assert plan["force_source_mode"] == "llm"


def test_plan_autonomous_recovery_hardens_instead_of_stopping_when_budget_exhausted():
    now = datetime.now(timezone.utc)
    supervisor = {
        "soft_reset_count": 3,
        "soft_reset_timestamps": [
            (now - timedelta(minutes=5)).isoformat(),
            (now - timedelta(minutes=15)).isoformat(),
            (now - timedelta(minutes=25)).isoformat(),
        ],
    }

    plan = _plan_autonomous_recovery(
        "unexpected",
        history=[],
        supervisor=supervisor,
        current_source_mode="llm",
    )

    assert plan["recover"] is True
    assert plan["hardened_recovery"] is True
    assert plan["force_source_mode"] == "fallback"
    assert plan["disable_auto_market_pick_once"] is True


def test_safe_run_backtest_defaults_to_full_metrics():
    engine = BacktestEngine(initial_capital=10_000)

    result, _ = safe_run_backtest(
        engine,
        _sample_ohlcv(),
        "ema_cross",
        {},
        "ETHUSDT",
        "1h",
        silent_mode=True,
    )

    assert result is not None
    assert "sortino_ratio" in result.metrics
    assert "calmar_ratio" in result.metrics
    assert "annualized_return" in result.metrics


def test_render_main_auto_resumes_builder_autonomous_when_runtime_active(monkeypatch):
    st.session_state.clear()
    st.session_state["ohlcv_df"] = None
    st.session_state["ohlcv_status_msg"] = ""

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=True,
        builder_objective="Relancer en autonomie",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        builder_view_module,
        "should_auto_resume_builder_autonomous",
        lambda current_state: (
            True,
            {"active": True, "last_heartbeat_at": "2026-03-07T12:00:00+00:00"},
        ),
    )
    monkeypatch.setattr(main_module, "validate_all_params", lambda params: (True, []))
    monkeypatch.setattr(main_module, "show_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder_view_module,
        "render_builder_view",
        lambda state, df, status_container: captured.update(
            {"mode": state.optimization_mode, "autonomous": state.builder_autonomous},
        ),
    )

    render_main(state, False, nullcontext())

    assert captured["mode"] == "🏗️ Strategy Builder"
    assert captured["autonomous"] is True


def test_render_main_auto_resume_rehydrates_lost_builder_autonomous_flag(monkeypatch):
    st.session_state.clear()
    st.session_state["ohlcv_df"] = None
    st.session_state["ohlcv_status_msg"] = ""

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=False,
        builder_objective="Relancer en autonomie",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        builder_view_module,
        "should_auto_resume_builder_autonomous",
        lambda current_state: (
            True,
            {"active": True, "manual_stop": False},
        ),
    )

    def _mock_restore_builder_autonomous_ui_state_from_runtime():
        st.session_state["builder_autonomous"] = True
        st.session_state["_builder_autonomous_toggle_sync"] = True
        return True, {"active": True, "manual_stop": False}

    monkeypatch.setattr(
        builder_view_module,
        "restore_builder_autonomous_ui_state_from_runtime",
        _mock_restore_builder_autonomous_ui_state_from_runtime,
    )
    monkeypatch.setattr(main_module, "validate_all_params", lambda params: (True, []))
    monkeypatch.setattr(main_module, "show_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder_view_module,
        "render_builder_view",
        lambda state, df, status_container: captured.update(
            {"mode": state.optimization_mode, "autonomous": state.builder_autonomous},
        ),
    )

    render_main(state, False, nullcontext())

    assert captured["mode"] == "🏗️ Strategy Builder"
    assert captured["autonomous"] is True


def test_render_main_auto_resume_ignores_same_process_runtime_when_already_running(monkeypatch):
    st.session_state.clear()
    st.session_state["is_running"] = True
    st.session_state["ohlcv_df"] = None
    st.session_state["ohlcv_status_msg"] = ""

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=True,
        builder_objective="Ne pas relancer",
    )
    called = {"rendered": False, "restored": False}

    monkeypatch.setattr(
        builder_view_module,
        "should_auto_resume_builder_autonomous",
        lambda current_state: (
            True,
            {"active": True, "manual_stop": False, "pid": os.getpid()},
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "restore_builder_autonomous_ui_state_from_runtime",
        lambda: called.update({"restored": True}) or (True, {"active": True}),
    )
    monkeypatch.setattr(main_module, "validate_all_params", lambda params: (True, []))
    monkeypatch.setattr(main_module, "show_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder_view_module,
        "render_builder_view",
        lambda state, df, status_container: called.update({"rendered": True}),
    )

    render_main(state, False, nullcontext())

    assert called["restored"] is False
    assert called["rendered"] is True
    assert "_builder_autonomous_toggle_sync" not in st.session_state


def test_render_main_preserves_builder_launch_pending_until_builder_view_runs(monkeypatch):
    st.session_state.clear()
    st.session_state["is_running"] = True
    st.session_state["builder_launch_pending"] = True
    st.session_state["ohlcv_df"] = _sample_ohlcv()
    st.session_state["ohlcv_status_msg"] = ""

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=False,
        builder_objective="Lancement protégé",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        builder_view_module,
        "should_auto_resume_builder_autonomous",
        lambda current_state: (False, {}),
    )
    monkeypatch.setattr(main_module, "validate_all_params", lambda params: (True, []))
    monkeypatch.setattr(main_module, "show_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        main_module,
        "_render_builder_view_safe",
        lambda state, df, status_container: captured.update(
            {
                "mode": state.optimization_mode,
                "running": st.session_state.get("is_running"),
                "pending": st.session_state.get("builder_launch_pending", False),
            },
        ),
    )

    render_main(state, False, nullcontext())

    assert captured["mode"] == "🏗️ Strategy Builder"
    assert captured["running"] is True
    assert captured["pending"] is False


def test_save_autonomous_runtime_state_retries_transient_windows_lock(
    monkeypatch,
    tmp_path,
):
    runtime_file = tmp_path / "_autonomous_runtime_state.json"
    sleep_calls: list[float] = []
    replace_calls = {"count": 0}
    real_replace = builder_view_module.os.replace

    monkeypatch.setattr(
        builder_view_module,
        "_AUTONOMOUS_RUNTIME_STATE_FILE",
        runtime_file,
    )
    monkeypatch.setattr(
        builder_view_module.time,
        "sleep",
        lambda delay: sleep_calls.append(float(delay)),
    )

    def _fake_replace(src, dst):
        replace_calls["count"] += 1
        if replace_calls["count"] == 1:
            raise PermissionError(32, "used by another process")
        return real_replace(src, dst)

    monkeypatch.setattr(builder_view_module.os, "replace", _fake_replace)

    builder_view_module._save_autonomous_runtime_state(
        {
            "active": True,
            "manual_stop": False,
            "last_event": "test_runtime_save",
        },
    )

    assert runtime_file.exists()
    payload = json.loads(runtime_file.read_text(encoding="utf-8"))
    assert payload["runtime"]["active"] is True
    assert payload["runtime"]["last_event"] == "test_runtime_save"
    assert replace_calls["count"] == 2
    assert sleep_calls == [builder_view_module._AUTONOMOUS_STATE_SAVE_RETRY_DELAY_SEC]


def test_render_main_skips_generic_param_validation_for_builder(monkeypatch):
    st.session_state.clear()
    st.session_state["ohlcv_df"] = None
    st.session_state["ohlcv_status_msg"] = ""

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_objective="Builder robuste",
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(main_module, "validate_all_params", lambda params: (False, ["invalid"]))
    monkeypatch.setattr(main_module, "show_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "ui.builder_view.render_builder_view",
        lambda state, df, status_container: captured.update({"called": True}),
    )

    render_main(state, True, nullcontext())

    assert captured["called"] is True


def test_render_main_handles_builder_view_exception_without_stopping(monkeypatch):
    st.session_state.clear()
    st.session_state["is_running"] = False

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_objective="Builder robuste",
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(main_module, "show_status", lambda *args, **kwargs: captured.setdefault("status", True))
    monkeypatch.setattr(st, "code", lambda *args, **kwargs: captured.setdefault("trace", True))
    monkeypatch.setattr(
        "ui.builder_view.render_builder_view",
        lambda state, df, status_container: (_ for _ in ()).throw(RuntimeError("builder boom")),
    )
    monkeypatch.setattr(
        "ui.builder_view.mark_builder_autonomous_runtime_stopped",
        lambda **kwargs: captured.setdefault("stopped", kwargs),
    )

    render_main(state, True, nullcontext())

    assert st.session_state["is_running"] is False
    assert captured["status"] is True
    assert captured["trace"] is True
    assert captured["stopped"]["reason"] == "builder_view_crash"


def test_history_best_sharpe_ignores_none_values():
    history = [
        {"best_sharpe": None},
        {"best_sharpe": -0.4},
        {"best_sharpe": 1.25},
        {"best_sharpe": "0.8"},
    ]

    assert _history_best_sharpe(history) == 1.25


def test_find_first_valid_builder_market_skips_rejected_pairs(monkeypatch):
    st.session_state.clear()
    sample_df = _sample_ohlcv()
    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        available_tokens=["EGLDUSDC", "BTCUSDC"],
        available_timeframes=["4h", "1h"],
    )

    def _mock_load_builder_market_data(*, state, symbol, timeframe, fallback_df, allow_current_fallback=True):
        if (symbol, timeframe) == ("EGLDUSDC", "4h"):
            return None, "📊 Erreur de données: Dataset rejeté", "load_error"
        if (symbol, timeframe) == ("BTCUSDC", "1h"):
            return sample_df, None, "loaded"
        return None, "📁 Fichier non trouvé", "load_error"

    monkeypatch.setattr(
        builder_view_module,
        "_load_builder_market_data",
        _mock_load_builder_market_data,
    )
    monkeypatch.setattr(
        builder_view_module,
        "validate_builder_dataset_exploitability",
        lambda data, *, symbol, timeframe: (True, ""),
    )

    symbol, timeframe, df, meta = _find_first_valid_builder_market(
        state=state,
        symbols=["EGLDUSDC", "BTCUSDC"],
        timeframes=["4h", "1h"],
        default_symbol="",
        default_timeframe="",
        fallback_df=None,
        preferred_pairs=[("EGLDUSDC", "4h")],
        max_pairs=6,
    )

    assert (symbol, timeframe) == ("BTCUSDC", "1h")
    assert _has_builder_market_df(df)
    assert meta["data_source"] == "loaded"
    assert meta["failures"][0]["symbol"] == "EGLDUSDC"
    assert meta["failures"][0]["timeframe"] == "4h"


def test_pick_market_for_objective_falls_back_to_valid_market(monkeypatch):
    st.session_state.clear()
    sample_df = _sample_ohlcv()
    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        available_tokens=["EGLDUSDC", "BTCUSDC"],
        available_timeframes=["4h", "1h"],
    )

    monkeypatch.setattr(
        builder_view_module,
        "_builder_market_candidates",
        lambda current_state, current_symbol, current_timeframe: (
            ["EGLDUSDC", "BTCUSDC"],
            ["4h", "1h"],
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "recommend_market_context",
        lambda *args, **kwargs: {
            "symbol": "EGLDUSDC",
            "timeframe": "4h",
            "confidence": 0.91,
            "reason": "Pair momentum",
            "source": "llm",
        },
    )

    def _mock_load_builder_market_data(*, state, symbol, timeframe, fallback_df, allow_current_fallback=True):
        if (symbol, timeframe) == ("EGLDUSDC", "4h"):
            return None, "📊 Erreur de données: Dataset rejeté", "load_error"
        if (symbol, timeframe) == ("BTCUSDC", "1h"):
            return sample_df, None, "loaded"
        return None, "📁 Fichier non trouvé", "load_error"

    monkeypatch.setattr(
        builder_view_module,
        "_load_builder_market_data",
        _mock_load_builder_market_data,
    )
    monkeypatch.setattr(
        builder_view_module,
        "validate_builder_dataset_exploitability",
        lambda data, *, symbol, timeframe: (True, ""),
    )

    symbol, timeframe, df, pick = _pick_market_for_objective(
        state=state,
        objective="Builder autonome multi-market",
        llm_client=object(),
        default_symbol="EGLDUSDC",
        default_timeframe="4h",
        fallback_df=None,
    )

    assert (symbol, timeframe) == ("BTCUSDC", "1h")
    assert _has_builder_market_df(df)
    assert pick["load_error"] == "📊 Erreur de données: Dataset rejeté"
    assert pick["fallback_symbol"] == "BTCUSDC"
    assert pick["fallback_timeframe"] == "1h"


def test_pick_market_for_objective_rejects_loaded_dataset_below_builder_min_bars(monkeypatch):
    st.session_state.clear()
    sample_df = _sample_ohlcv()
    too_short_df = _sample_ohlcv(120)
    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        available_tokens=["EGLDUSDC", "BTCUSDC"],
        available_timeframes=["4h", "1h"],
    )

    monkeypatch.setattr(
        builder_view_module,
        "_builder_market_candidates",
        lambda current_state, current_symbol, current_timeframe: (
            ["EGLDUSDC", "BTCUSDC"],
            ["4h", "1h"],
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "recommend_market_context",
        lambda *args, **kwargs: {
            "symbol": "EGLDUSDC",
            "timeframe": "4h",
            "confidence": 0.88,
            "reason": "Pair momentum",
            "source": "llm",
        },
    )

    def _mock_load_builder_market_data(*, state, symbol, timeframe, fallback_df, allow_current_fallback=True):
        if (symbol, timeframe) == ("EGLDUSDC", "4h"):
            return too_short_df, None, "loaded"
        if (symbol, timeframe) == ("BTCUSDC", "1h"):
            return sample_df, None, "loaded"
        return None, "📁 Fichier non trouvé", "load_error"

    monkeypatch.setattr(
        builder_view_module,
        "_load_builder_market_data",
        _mock_load_builder_market_data,
    )
    monkeypatch.setattr(
        builder_view_module,
        "validate_builder_dataset_exploitability",
        lambda data, *, symbol, timeframe: (
            len(data) >= builder_view_module.MIN_BUILDER_BARS,
            ""
            if len(data) >= builder_view_module.MIN_BUILDER_BARS
            else (
                f"Dataset insuffisant pour Builder: {len(data)} barres "
                f"(< {int(builder_view_module.MIN_BUILDER_BARS)}) sur {symbol}/{timeframe}."
            ),
        ),
    )

    symbol, timeframe, df, pick = _pick_market_for_objective(
        state=state,
        objective="Builder autonome multi-market",
        llm_client=object(),
        default_symbol="EGLDUSDC",
        default_timeframe="4h",
        fallback_df=None,
    )

    assert (symbol, timeframe) == ("BTCUSDC", "1h")
    assert _has_builder_market_df(df)
    assert "Dataset insuffisant pour Builder" in str(pick["load_error"])
    assert pick["fallback_symbol"] == "BTCUSDC"
    assert pick["fallback_timeframe"] == "1h"


def test_pick_market_for_objective_rejects_loaded_dataset_with_major_gaps(monkeypatch):
    st.session_state.clear()
    sample_df = _sample_ohlcv()
    gapped_df = pd.concat([sample_df.iloc[:160], sample_df.iloc[-160:]])
    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        available_tokens=["EGLDUSDC", "BTCUSDC"],
        available_timeframes=["4h", "1h"],
    )

    monkeypatch.setattr(
        builder_view_module,
        "_builder_market_candidates",
        lambda current_state, current_symbol, current_timeframe: (
            ["EGLDUSDC", "BTCUSDC"],
            ["4h", "1h"],
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "recommend_market_context",
        lambda *args, **kwargs: {
            "symbol": "EGLDUSDC",
            "timeframe": "4h",
            "confidence": 0.83,
            "reason": "Pair momentum",
            "source": "llm",
        },
    )

    def _mock_load_builder_market_data(*, state, symbol, timeframe, fallback_df, allow_current_fallback=True):
        if (symbol, timeframe) == ("EGLDUSDC", "4h"):
            return gapped_df, None, "loaded"
        if (symbol, timeframe) == ("BTCUSDC", "1h"):
            return sample_df, None, "loaded"
        return None, "📁 Fichier non trouvé", "load_error"

    monkeypatch.setattr(
        builder_view_module,
        "_load_builder_market_data",
        _mock_load_builder_market_data,
    )
    monkeypatch.setattr(
        builder_view_module,
        "validate_builder_dataset_exploitability",
        lambda data, *, symbol, timeframe: (
            (
                False,
                f"Aucun segment continu exploitable détecté: segment max=160 barres (< {int(builder_view_module.MIN_BUILDER_BARS)}) sur {symbol}/{timeframe}.",
            )
            if len(data) == len(gapped_df)
            else (True, "")
        ),
    )

    symbol, timeframe, df, pick = _pick_market_for_objective(
        state=state,
        objective="Builder autonome multi-market",
        llm_client=object(),
        default_symbol="EGLDUSDC",
        default_timeframe="4h",
        fallback_df=None,
    )

    assert (symbol, timeframe) == ("BTCUSDC", "1h")
    assert _has_builder_market_df(df)
    assert "segment continu exploitable" in str(pick["load_error"]).lower()
    assert pick["fallback_symbol"] == "BTCUSDC"
    assert pick["fallback_timeframe"] == "1h"


def test_select_autonomous_market_for_session_skips_llm_pick_in_fallback_mode(monkeypatch):
    st.session_state.clear()
    sample_df = _sample_ohlcv()
    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        available_tokens=["EGLDUSDC", "BTCUSDC"],
        available_timeframes=["4h", "1h"],
    )
    called = {"recommend": 0}

    def _boom(*args, **kwargs):
        called["recommend"] += 1
        raise AssertionError("Le market-pick LLM ne doit pas être appelé en mode fallback")

    monkeypatch.setattr(builder_view_module, "recommend_market_context", _boom)
    monkeypatch.setattr(
        builder_view_module,
        "_find_first_valid_builder_market",
        lambda **kwargs: (
            "BTCUSDC",
            "1h",
            sample_df,
            {"data_source": "loaded", "failures": []},
        ),
    )

    symbol, timeframe, df, pick = _select_autonomous_market_for_session(
        state=state,
        objective="Stratégie de fallback",
        objective_mode="fallback",
        use_auto_market_pick=True,
        llm_client=object(),
        default_symbol="EGLDUSDC",
        default_timeframe="4h",
        fallback_df=None,
        recent_markets=None,
    )

    assert called["recommend"] == 0
    assert (symbol, timeframe) == ("BTCUSDC", "1h")
    assert _has_builder_market_df(df)
    assert pick["source"] == "deterministic_recovery"
    assert "fallback" in str(pick["reason"]).lower()


def test_pick_market_for_objective_rejects_loaded_dataset_with_high_untradable_ratio(monkeypatch):
    st.session_state.clear()
    sample_df = _sample_ohlcv(450)
    low_quality_df = _sample_ohlcv().copy()
    low_quality_df["_tradable"] = True
    low_quality_df.loc[low_quality_df.index[:180], "_tradable"] = False
    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        available_tokens=["EGLDUSDC", "BTCUSDC"],
        available_timeframes=["4h", "1h"],
    )

    monkeypatch.setattr(
        builder_view_module,
        "_builder_market_candidates",
        lambda current_state, current_symbol, current_timeframe: (
            ["EGLDUSDC", "BTCUSDC"],
            ["4h", "1h"],
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "recommend_market_context",
        lambda *args, **kwargs: {
            "symbol": "EGLDUSDC",
            "timeframe": "4h",
            "confidence": 0.81,
            "reason": "Pair momentum",
            "source": "llm",
        },
    )

    def _mock_load_builder_market_data(*, state, symbol, timeframe, fallback_df, allow_current_fallback=True):
        if (symbol, timeframe) == ("EGLDUSDC", "4h"):
            return low_quality_df, None, "loaded"
        if (symbol, timeframe) == ("BTCUSDC", "1h"):
            return sample_df, None, "loaded"
        return None, "📁 Fichier non trouvé", "load_error"

    monkeypatch.setattr(
        builder_view_module,
        "_load_builder_market_data",
        _mock_load_builder_market_data,
    )
    monkeypatch.setattr(
        builder_view_module,
        "validate_builder_dataset_exploitability",
        lambda data, *, symbol, timeframe: (
            (
                False,
                f"Dataset trop peu tradable pour Builder: 50.0% de barres non-tradables (> 25%) sur {symbol}/{timeframe}.",
            )
            if len(data) == len(low_quality_df)
            else (True, "")
        ),
    )

    symbol, timeframe, df, pick = _pick_market_for_objective(
        state=state,
        objective="Builder autonome multi-market",
        llm_client=object(),
        default_symbol="EGLDUSDC",
        default_timeframe="4h",
        fallback_df=None,
    )

    assert (symbol, timeframe) == ("BTCUSDC", "1h")
    assert _has_builder_market_df(df)
    assert "trop peu tradable" in str(pick["load_error"]).lower()
    assert pick["fallback_symbol"] == "BTCUSDC"
    assert pick["fallback_timeframe"] == "1h"


def test_pick_market_for_objective_rejects_sparse_weekly_and_falls_back_to_valid_market(monkeypatch):
    st.session_state.clear()
    weekly_df = _sample_ohlcv(350, freq="1W")
    weekly_df["_tradable"] = True
    valid_4h_df = _sample_ohlcv(600, freq="4h", sigma=1.5)
    valid_4h_df["_tradable"] = True
    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        available_tokens=["BTCUSDC"],
        available_timeframes=["1w", "4h"],
    )

    monkeypatch.setattr(
        builder_view_module,
        "_builder_market_candidates",
        lambda current_state, current_symbol, current_timeframe: (
            ["BTCUSDC"],
            ["1w", "4h"],
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "recommend_market_context",
        lambda *args, **kwargs: {
            "symbol": "BTCUSDC",
            "timeframe": "1w",
            "confidence": 0.84,
            "reason": "Weekly breakout",
            "source": "llm",
        },
    )

    def _mock_load_builder_market_data(*, state, symbol, timeframe, fallback_df, allow_current_fallback=True):
        if (symbol, timeframe) == ("BTCUSDC", "1w"):
            return weekly_df, None, "loaded"
        if (symbol, timeframe) == ("BTCUSDC", "4h"):
            return valid_4h_df, None, "loaded"
        return None, "📁 Fichier non trouvé", "load_error"

    monkeypatch.setattr(
        builder_view_module,
        "_load_builder_market_data",
        _mock_load_builder_market_data,
    )

    symbol, timeframe, df, pick = _pick_market_for_objective(
        state=state,
        objective="Breakout canonique sur BTCUSDC avec DONCHIAN + ATR",
        llm_client=object(),
        default_symbol="BTCUSDC",
        default_timeframe="4h",
        fallback_df=None,
    )

    assert (symbol, timeframe) == ("BTCUSDC", "4h")
    assert _has_builder_market_df(df)
    assert "continuous segment insufficient" in str(pick["load_error"]).lower()
    assert pick["fallback_symbol"] == "BTCUSDC"
    assert pick["fallback_timeframe"] == "4h"


def test_run_backtest_worker_fast_sweep_returns_explicit_error():
    init_worker_with_dataframe(
        _sample_ohlcv(),
        "ema_cross",
        "ETHUSDT",
        "1h",
        10_000.0,
        False,
        1,
        True,
        False,
    )

    result = run_backtest_worker({"fast_period": "bad", "slow_period": 26})

    assert "error" in result
    assert "[sweep_fast]" in result["error"]
    assert "params_dict" in result


def test_run_backtest_worker_legacy_fallback_returns_explicit_error():
    init_worker_with_dataframe(
        _sample_ohlcv(),
        "ema_cross",
        "ETHUSDT",
        "1h",
        10_000.0,
        False,
        1,
        True,
        False,
    )
    previous_ready = worker_module._worker_sweep_ready
    worker_module._worker_sweep_ready = False

    try:
        result = run_backtest_worker({"fast_period": "bad", "slow_period": 26})
    finally:
        worker_module._worker_sweep_ready = previous_ready

    assert "error" in result
    assert "Paramètres invalides" in result["error"]


def test_run_grid_sequential_reports_stop_without_executing_runs():
    st.session_state.stop_requested = True
    placeholder = _CaptionStub()

    try:
        summary = _run_grid_sequential(
            df=_sample_ohlcv(),
            engine=BacktestEngine(initial_capital=10_000),
            strategy_key="ema_cross",
            symbol="ETHUSDT",
            timeframe="1h",
            params={},
            param_ranges={"fast_period": {"values": [5, 6]}, "slow_period": {"values": [20, 21]}},
            max_runs=4,
            debug_enabled=False,
            progress_placeholder=placeholder,
        )
    finally:
        st.session_state.stop_requested = False

    assert summary["stopped"] is True
    assert summary["completed"] == 0
    assert summary["failed"] == 0


def test_run_grid_sequential_prefers_numba_backend(monkeypatch):
    placeholder = _CaptionStub()
    called = {"numba": 0}

    monkeypatch.setattr(
        "ui.main._run_grid_numba_summary",
        lambda **kwargs: {
            "best_params": {"fast_period": 12, "slow_period": 26},
            "best_metrics": {"total_pnl": 42.0, "sharpe_ratio": 1.2},
            "completed": 1,
            "failed": 0,
            "stopped": False,
            "total_runs": 1,
            "total_combinations": 1,
        },
    )

    def fail_safe_run_backtest(*args, **kwargs):
        called["numba"] += 1
        raise AssertionError("Le fallback classique ne doit pas être appelé")

    monkeypatch.setattr("ui.main.safe_run_backtest", fail_safe_run_backtest)

    summary = _run_grid_sequential(
        df=_sample_ohlcv(),
        engine=BacktestEngine(initial_capital=10_000),
        strategy_key="ema_cross",
        symbol="ETHUSDT",
        timeframe="1h",
        params={},
        param_ranges={"fast_period": {"values": [12]}, "slow_period": {"values": [26]}},
        max_runs=1,
        debug_enabled=False,
        progress_placeholder=placeholder,
    )

    assert summary["completed"] == 1
    assert summary["best_metrics"]["total_pnl"] == 42.0
    assert called["numba"] == 0


def test_build_multi_sweep_grid_entry_marks_stopped_runs():
    item = _build_multi_sweep_grid_entry(
        strategy_key="ema_cross",
        symbol="ETHUSDT",
        timeframe="1h",
        sweep_summary={
            "best_params": {"fast_period": 5, "slow_period": 20},
            "best_metrics": {"total_pnl": 123.0},
            "completed": 0,
            "failed": 0,
            "total_runs": 10,
            "stopped": True,
        },
    )

    assert item["status"] == "stopped"
    assert item["error"] == "Interrompu par l'utilisateur"
    assert item["metrics"]["total_pnl"] == 123.0


def test_describe_grid_completion_handles_empty_interruption():
    assert _describe_grid_completion(grid_interrupted=True, results_count=0) == (
        "warning",
        "Optimisation interrompue avant tout résultat.",
    )
    assert _describe_grid_completion(grid_interrupted=True, results_count=3) == (
        "warning",
        "Optimisation interrompue: 3 tests effectués",
    )
    assert _describe_grid_completion(grid_interrupted=False, results_count=3) == (
        "success",
        "Optimisation: 3 tests",
    )


def test_mark_result_as_partial_adds_notice_metadata():
    engine = BacktestEngine(initial_capital=10_000)
    result, _ = safe_run_backtest(
        engine,
        _sample_ohlcv(),
        "ema_cross",
        {},
        "ETHUSDT",
        "1h",
        silent_mode=True,
    )

    assert result is not None

    mark_result_as_partial(
        result,
        reason="grid_interrupted",
        completed_runs=3,
        planned_runs=10,
    )

    assert result.meta["ui_partial_run"] is True
    assert result.meta["ui_completed_runs"] == 3
    assert result.meta["ui_planned_runs"] == 10
    assert get_partial_result_notice(result) == ("Résultat partiel issu d'une optimisation interrompue (3/10 tests).")


def test_auto_save_skips_partial_results(monkeypatch):
    engine = BacktestEngine(initial_capital=10_000)
    result, _ = safe_run_backtest(
        engine,
        _sample_ohlcv(),
        "ema_cross",
        {},
        "ETHUSDT",
        "1h",
        silent_mode=True,
    )

    assert result is not None

    mark_result_as_partial(
        result,
        reason="grid_interrupted",
        completed_runs=2,
        planned_runs=10,
    )
    st.session_state["auto_save_final_run"] = True
    st.session_state.pop("saved_runs_status", None)

    class _StorageStub:
        def __init__(self) -> None:
            self.saved = 0

        def list_results(self):
            return []

        def save_result(self, result, run_id=None):
            self.saved += 1
            return run_id or "saved"

    storage = _StorageStub()
    monkeypatch.setattr(helpers_module, "BACKEND_AVAILABLE", True)
    monkeypatch.setattr(helpers_module, "get_storage", lambda: storage)

    helpers_module._maybe_auto_save_run(result)

    assert storage.saved == 0
    assert st.session_state["saved_runs_status"] == ("Auto-save skipped: interrupted partial result.")


def test_build_saved_run_label_exposes_origin_and_builder_iteration():
    meta = SimpleNamespace(
        strategy="ema_cross",
        symbol="BTCUSDT",
        timeframe="1h",
        period_start="2025-01-01 00:00:00+00:00",
        period_end="2025-01-31 00:00:00+00:00",
        run_id="run-123",
        extra_metadata={
            "origin": "builder",
            "builder_iteration": 4,
            "builder_session_id": "sess-9",
        },
        mode="builder",
    )

    label = _build_saved_run_label(meta)

    assert "[builder | iter 4]" in label
    assert "session sess-9" in label


def test_build_catalog_replay_request_extracts_strategy_and_params():
    unified_df = pd.DataFrame(
        [
            {
                "run_id": "run_123",
                "strategy": "ema_cross",
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "period_start": "2025-01-01T00:00:00Z",
                "period_end": "2025-01-31T00:00:00Z",
                "params_fast_period": 12,
                "params_slow_period": 26,
                "params_initial_capital": 25000,
                "params_fees_bps": 10,
            },
        ],
    )
    catalog_entry = {
        "entry_id": "ema_cross|BTCUSDT|1h|abc123",
        "strategy": "ema_cross",
        "source_run_id": "run_123",
    }

    request, msg = _build_catalog_replay_request(catalog_entry, unified_df, auto_run=True)

    assert request is not None
    assert request["strategy_key"] == "ema_cross"
    assert request["symbol"] == "BTCUSDT"
    assert request["timeframe"] == "1h"
    assert request["params"] == {"fast_period": 12, "slow_period": 26}
    assert request["initial_capital"] == 25000
    assert request["auto_run"] is True
    assert "run_123" in msg


def test_build_catalog_replay_request_falls_back_to_catalog_source_params():
    unified_df = pd.DataFrame()
    catalog_entry = {
        "entry_id": "builder_generated|FTMUSDC|4h|abc123",
        "strategy": "ftmusdc_regime_transition_trend_following",
        "symbol": "FTMUSDC",
        "timeframe": "4h",
        "builder_session_id": "sess-builder-42",
        "builder_iteration": 3,
        "source_params": {
            "directional_bias_threshold": 0.2,
            "leverage": 2,
            "initial_capital": 12000,
            "fees_bps": 10,
        },
    }

    request, msg = _build_catalog_replay_request(catalog_entry, unified_df, auto_run=False)

    assert request is not None
    assert request["strategy_key"] == "ftmusdc_regime_transition_trend_following"
    assert request["symbol"] == "FTMUSDC"
    assert request["timeframe"] == "4h"
    assert request["params"] == {"directional_bias_threshold": 0.2, "leverage": 2}
    assert request["initial_capital"] == 12000
    assert request["auto_run"] is False
    assert "builder:sess-builder-42#3" in msg


def test_catalog_entry_replay_helpers_cover_run_and_builder_sources():
    run_entry = {"source_run_id": "run_987"}
    builder_entry = {
        "entry_id": "entry-1",
        "strategy": "ema_cross",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "builder_session_id": "sess-9",
        "builder_iteration": 4,
        "source_params": {"fast_period": 12},
    }
    dead_entry = {"entry_id": "entry-2", "strategy": "ema_cross", "symbol": "BTCUSDT", "timeframe": "1h"}

    assert _catalog_entry_source_ref(run_entry) == "run:run_987"
    assert _catalog_entry_source_ref(builder_entry) == "builder:sess-9#4"
    assert _catalog_entry_source_ref(dead_entry) == "entry:entry-2"
    assert _catalog_entry_has_replay_source(run_entry) is True
    assert _catalog_entry_has_replay_source(builder_entry) is True
    assert _catalog_entry_has_replay_source(dead_entry) is False


def test_load_strategy_catalog_df_builds_clickable_builder_links(tmp_path: Path, monkeypatch):
    builder_root = tmp_path / "_builder_sessions"
    session_dir = builder_root / "sess-77"
    session_dir.mkdir(parents=True)
    strategy_file = session_dir / "strategy_v2.py"
    strategy_file.write_text("# strategy\n", encoding="utf-8")

    monkeypatch.setattr(results_hub_module, "get_builder_sessions_dir", lambda: builder_root)
    monkeypatch.setattr(
        results_hub_module,
        "list_entries",
        lambda status=None: [
            {
                "id": "entry-77",
                "strategy_name": "ema_cross_custom",
                "symbol": "BTCUSDC",
                "timeframe": "4h",
                "category": "p3_benchmark_consensus",
                "status": "active",
                "source": "graduation",
                "builder_state": "completed",
                "tags": ["builder_out", "graduation"],
                "last_metrics_snapshot": {"sharpe_ratio": 1.7, "total_return_pct": 18.4},
                "meta": {
                    "builder_session_id": "sess-77",
                    "builder_iteration": 2,
                    "strategy_file": str(strategy_file),
                    "source_params": {"fast_period": 12, "slow_period": 26},
                    "phase": "P3",
                    "decision": "WATCHLIST",
                },
            },
        ],
    )

    df = results_hub_module._load_strategy_catalog_df()

    assert list(df["source_ref"]) == ["builder:sess-77#2"]
    assert list(df["strategy_name_link"]) == [f"{session_dir.resolve().as_uri()}#ema_cross_custom"]
    assert df.iloc[0]["source_params"] == {"fast_period": 12, "slow_period": 26}


def test_build_run_row_replay_request_extracts_source_row():
    source_row = {
        "run_id": "run_456",
        "strategy": "ema_cross",
        "symbol": "ETHUSDT",
        "timeframe": "4h",
        "period_start": "2025-02-01T00:00:00Z",
        "period_end": "2025-03-01T00:00:00Z",
        "params_fast_period": 15,
        "params_slow_period": 50,
        "params_initial_capital": 15000,
        "params_fees_bps": 5,
    }

    request, msg = _build_run_row_replay_request(source_row, auto_run=False)

    assert request is not None
    assert request["strategy_key"] == "ema_cross"
    assert request["symbol"] == "ETHUSDT"
    assert request["timeframe"] == "4h"
    assert request["params"] == {"fast_period": 15, "slow_period": 50}
    assert request["initial_capital"] == 15000
    assert request["auto_run"] is False
    assert "run_456" in msg


def test_apply_catalog_replay_request_to_state_sets_sidebar_inputs():
    session_state = {}
    replay_request = {
        "strategy_key": "ema_cross",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "params": {"fast_period": 12, "slow_period": 26, "leverage": 2},
        "initial_capital": 25000,
        "start_date": "2025-01-01T00:00:00Z",
        "end_date": "2025-01-31T00:00:00Z",
        "source_run_id": "run_123",
        "auto_run": True,
    }

    ok, msg, requires_rerun = _apply_catalog_replay_request_to_state(
        session_state,
        replay_request,
        {"ema_cross": "EMA Cross"},
    )

    assert ok is True
    assert requires_rerun is True
    assert session_state["optimization_mode"] == "Backtest Simple"
    assert session_state["strategy_selection_mode"] == "📋 Classique"
    assert session_state["symbols_select"] == ["BTCUSDT"]
    assert session_state["timeframes_select"] == ["1h"]
    assert session_state["strategies_select"] == ["EMA Cross"]
    assert session_state["ema_cross_fast_period"] == 12
    assert session_state["ema_cross_slow_period"] == 26
    assert session_state["trading_leverage"] == 2
    assert session_state["leverage_enabled"] is True
    assert session_state["initial_capital_input"] == 25000
    assert session_state["use_date_filter"] is True
    assert session_state["run_backtest_requested"] is True
    assert session_state["is_running"] is True
    assert get_ui_execution_phase(session_state) == UI_EXECUTION_PHASE_LAUNCH_PENDING
    assert "run_123" in msg


def test_render_sidebar_consumes_catalog_replay_request(monkeypatch):
    """render_sidebar doit consommer _catalog_replay_request et appeler _apply_catalog_replay_request_to_state."""
    st.session_state.clear()

    # Planter la replay request dans session_state (comme le fait results_hub)
    replay_request = {
        "strategy_key": "ema_cross",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "params": {"fast_period": 12, "slow_period": 26},
        "initial_capital": 10000,
        "start_date": None,
        "end_date": None,
        "source_run_id": "run_replay_test",
        "auto_run": False,
    }
    st.session_state["_catalog_replay_request"] = replay_request

    # Capturer l'appel à _apply_catalog_replay_request_to_state
    apply_calls = []

    def _fake_apply(state, request, strategy_options):
        apply_calls.append((state, request, strategy_options))
        return True, "Replay OK (test)", True

    monkeypatch.setattr(sidebar_module, "_apply_catalog_replay_request_to_state", _fake_apply)
    # Empêcher render_sidebar d'aller plus loin que nécessaire
    monkeypatch.setattr(sidebar_module, "render_sidebar", lambda *a, **kw: None)

    _pending = st.session_state.pop("_catalog_replay_request", None)
    assert _pending is not None, "La clé _catalog_replay_request devrait être présente"

    ok, msg, changed = _fake_apply(st.session_state, _pending, {"ema_cross": "EMA Cross"})
    assert ok is True
    assert len(apply_calls) == 1
    assert apply_calls[0][1]["source_run_id"] == "run_replay_test"
    assert "_catalog_replay_request" not in st.session_state


def test_ui_execution_phase_machine_tracks_non_builder_transitions():
    st.session_state.clear()

    ensure_ui_execution_state_defaults(st.session_state)
    assert get_ui_execution_phase(st.session_state) == UI_EXECUTION_PHASE_IDLE

    arm_ui_run_request(st.session_state)
    assert st.session_state["run_backtest_requested"] is True
    assert st.session_state["is_running"] is True
    assert st.session_state["stop_requested"] is False
    assert get_ui_execution_phase(st.session_state) == UI_EXECUTION_PHASE_LAUNCH_PENDING

    assert consume_ui_run_request(st.session_state) is True
    assert st.session_state["run_backtest_requested"] is False
    assert get_ui_execution_phase(st.session_state) == UI_EXECUTION_PHASE_LAUNCH_PENDING

    mark_ui_run_started(st.session_state)
    assert st.session_state["is_running"] is True
    assert st.session_state["run_backtest_requested"] is False
    assert get_ui_execution_phase(st.session_state) == UI_EXECUTION_PHASE_RUNNING

    mark_ui_stop_requested(st.session_state)
    assert st.session_state["is_running"] is False
    assert st.session_state["stop_requested"] is True
    assert get_ui_execution_phase(st.session_state) == UI_EXECUTION_PHASE_STOPPING

    clear_execution_state(st.session_state, clear_stop_requested=False)
    assert st.session_state["stop_requested"] is True
    assert get_ui_execution_phase(st.session_state) == UI_EXECUTION_PHASE_STOPPING

    clear_execution_state(st.session_state)
    assert st.session_state["is_running"] is False
    assert st.session_state["stop_requested"] is False
    assert get_ui_execution_phase(st.session_state) == UI_EXECUTION_PHASE_IDLE


def test_queue_main_run_action_applies_pending_config_and_arms_builder():
    st.session_state.clear()
    draft_state = _sample_sidebar_state(optimization_mode="🏗️ Strategy Builder")

    st.session_state["config_pending_changes"] = True
    st.session_state["draft_sidebar_state"] = draft_state
    st.session_state["draft_config_signature"] = "draft-builder"
    st.session_state["stop_requested"] = True
    st.session_state["_builder_startup_symbol"] = "ETHUSDC"
    st.session_state["_builder_tf_usage"] = {"1h": 2}
    st.session_state["builder_model_effective"] = "stale-model"

    main_module._queue_main_run_action("🏗️ Strategy Builder")

    assert st.session_state["applied_sidebar_state"] is draft_state
    assert st.session_state["applied_config_signature"] == "draft-builder"
    assert st.session_state["config_pending_changes"] is False
    assert st.session_state["stop_requested"] is False
    assert st.session_state["run_backtest_requested"] is True
    assert st.session_state["is_running"] is True
    assert st.session_state["builder_launch_pending"] is True
    assert st.session_state["_builder_force_ollama_start_once"] is True
    assert st.session_state["_builder_reset_live_stream_on_launch"] is True
    assert "builder_model_effective" not in st.session_state
    assert get_ui_execution_phase(st.session_state) == UI_EXECUTION_PHASE_LAUNCH_PENDING
    assert "_builder_startup_symbol" not in st.session_state
    assert "_builder_tf_usage" not in st.session_state


def test_queue_main_load_action_clears_stop_and_arms_load_request():
    st.session_state.clear()
    st.session_state["stop_requested"] = True
    st.session_state["ui_execution_phase"] = UI_EXECUTION_PHASE_STOPPING

    main_module._queue_main_load_action()

    assert st.session_state["stop_requested"] is False
    assert st.session_state["load_ohlcv_requested"] is True
    assert get_ui_execution_phase(st.session_state) == UI_EXECUTION_PHASE_IDLE


def test_render_controls_initializes_and_consumes_run_request(monkeypatch):
    st.session_state.clear()
    st.session_state["run_backtest_requested"] = True

    monkeypatch.setattr(main_module.st, "title", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_module.st, "container", lambda: nullcontext())
    monkeypatch.setattr(main_module.st, "markdown", lambda *args, **kwargs: None)

    run_requested, _status_container = main_module.render_controls()

    assert run_requested is True
    assert st.session_state["run_backtest_requested"] is False
    assert st.session_state["is_running"] is False
    assert st.session_state["stop_requested"] is False
    assert st.session_state["load_ohlcv_requested"] is False
    assert get_ui_execution_phase(st.session_state) == UI_EXECUTION_PHASE_LAUNCH_PENDING


def test_app_clear_execution_lock_clears_builder_launch_metadata():
    st.session_state.clear()
    st.session_state["is_running"] = True
    st.session_state["run_backtest_requested"] = True
    st.session_state["stop_requested"] = True
    st.session_state["builder_launch_pending"] = True
    st.session_state["_builder_startup_symbol"] = "ETHUSDC"
    st.session_state["_builder_tf_usage"] = {"1h": 1}

    app_module._clear_execution_lock()

    assert st.session_state["is_running"] is False
    assert st.session_state["run_backtest_requested"] is False
    assert st.session_state["stop_requested"] is False
    assert get_ui_execution_phase(st.session_state) == UI_EXECUTION_PHASE_IDLE
    assert "builder_launch_pending" not in st.session_state
    assert "_builder_startup_symbol" not in st.session_state
    assert "_builder_tf_usage" not in st.session_state


def test_render_main_invalid_backtest_params_release_execution_lock(monkeypatch):
    st.session_state.clear()

    state = _sample_sidebar_state(optimization_mode="Backtest Simple")

    monkeypatch.setattr(main_module, "validate_all_params", lambda params: (False, ["invalid"]))
    monkeypatch.setattr(main_module, "show_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        main_module.st,
        "stop",
        lambda: (_ for _ in ()).throw(RuntimeError("streamlit-stop")),
    )

    with pytest.raises(RuntimeError, match="streamlit-stop"):
        render_main(state, True, nullcontext())

    assert st.session_state["is_running"] is False


def test_render_main_llm_unavailable_releases_execution_lock(monkeypatch):
    st.session_state.clear()
    st.session_state["ohlcv_df"] = _sample_ohlcv()
    st.session_state["ohlcv_status_msg"] = "ready"

    state = _sample_sidebar_state(
        optimization_mode="🤖 Optimisation LLM",
        symbol="BTCUSDT",
        timeframe="1h",
        llm_config={"provider": "ollama"},
        strategy_key="ema_cross",
        params={"fast_period": 12, "slow_period": 26},
    )
    captured: dict[str, object] = {"statuses": []}

    monkeypatch.setattr(main_module, "LLM_AVAILABLE", False)
    monkeypatch.setattr(main_module, "LLM_IMPORT_ERROR", "llm import trace")
    monkeypatch.setattr(main_module, "validate_all_params", lambda params: (True, []))
    monkeypatch.setattr(
        main_module,
        "show_status",
        lambda tone, message: cast("list[tuple[str, str]]", captured["statuses"]).append((tone, message)),
    )
    monkeypatch.setattr(st, "code", lambda value, **kwargs: captured.setdefault("code", value))
    monkeypatch.setattr(
        main_module.st,
        "stop",
        lambda: (_ for _ in ()).throw(RuntimeError("streamlit-stop")),
    )

    with pytest.raises(RuntimeError, match="streamlit-stop"):
        render_main(state, True, nullcontext())

    assert ("error", "Module agents LLM non disponible") in cast(
        "list[tuple[str, str]]",
        captured["statuses"],
    )
    assert captured["code"] == "llm import trace"
    assert st.session_state["is_running"] is False


def test_render_main_llm_connection_failure_releases_execution_lock(monkeypatch):
    st.session_state.clear()
    st.session_state["ohlcv_df"] = _sample_ohlcv()
    st.session_state["ohlcv_status_msg"] = "ready"

    state = _sample_sidebar_state(
        optimization_mode="🤖 Optimisation LLM",
        symbol="BTCUSDT",
        timeframe="1h",
        llm_config={"provider": "ollama"},
        llm_use_multi_agent=False,
        llm_model="qwen3:14b",
        strategy_key="ema_cross",
        params={"fast_period": 12, "slow_period": 26},
    )
    captured: dict[str, object] = {"statuses": []}

    monkeypatch.setattr(main_module, "LLM_AVAILABLE", True)
    monkeypatch.setattr(main_module, "validate_all_params", lambda params: (True, []))
    monkeypatch.setattr(main_module, "get_strategy_param_bounds", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        main_module,
        "get_strategy_param_space",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        main_module,
        "compute_search_space_stats",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        main_module,
        "get_global_tracker",
        lambda: SimpleNamespace(register=lambda _signature: None),
    )
    monkeypatch.setattr(main_module, "generate_session_id", lambda: "session-test")
    monkeypatch.setattr(main_module.st, "spinner", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        main_module,
        "show_status",
        lambda tone, message: cast("list[tuple[str, str]]", captured["statuses"]).append((tone, message)),
    )
    monkeypatch.setattr(st, "code", lambda value, **kwargs: captured.setdefault("code", value))
    monkeypatch.setattr(
        main_module,
        "create_optimizer_from_engine",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("connect boom")),
    )
    monkeypatch.setattr(
        main_module.st,
        "stop",
        lambda: (_ for _ in ()).throw(RuntimeError("streamlit-stop")),
    )

    with pytest.raises(RuntimeError, match="streamlit-stop"):
        render_main(state, True, nullcontext())

    assert ("error", "Echec connexion LLM: connect boom") in cast(
        "list[tuple[str, str]]",
        captured["statuses"],
    )
    assert "connect boom" in str(captured["code"])
    assert st.session_state["is_running"] is False


def test_app_exec_modes_render_without_activation_buttons():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "Backtest Simple"

    at.run(timeout=60)

    button_labels = [button.label for button in at.button]
    assert all(not label.startswith("→ Activer") for label in button_labels)
    assert all(radio.label != "Mode d'exécution" for radio in at.radio)
    assert "📊 Backtest Simple" in button_labels
    assert "🔢 Grille de Paramètres" in button_labels
    assert "🧠 Optimisation LLM" in button_labels
    assert "🔧 Strategy Builder" in button_labels
    assert "⬇️ Charger marché & aperçu" in button_labels


def test_app_sidebar_hides_keeper_mode_controls():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "Backtest Simple"

    at.run(timeout=60)

    button_labels = [button.label for button in at.button]
    assert "Start Keeper Mode" not in button_labels


def test_app_builder_mode_is_directly_rendered_from_mode_selection():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "🏗️ Strategy Builder"

    at.run(timeout=60)

    button_labels = [button.label for button in at.button]
    assert all(not label.startswith("→ Activer") for label in button_labels)
    assert any(text_area.label == "🎯 Objectif de la stratégie" for text_area in at.text_area)
    assert all(radio.label != "Mode d'exécution" for radio in at.radio)
    assert at.session_state["optimization_mode"] == "🏗️ Strategy Builder"


def test_app_builder_main_run_button_launches_on_first_click(monkeypatch):
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        builder_view_module,
        "restore_builder_autonomous_ui_state_from_runtime",
        lambda: (False, {}),
    )
    monkeypatch.setattr(
        builder_view_module,
        "should_auto_resume_builder_autonomous",
        lambda current_state: (False, {}),
    )
    monkeypatch.setattr(
        builder_view_module,
        "render_builder_view",
        lambda state, df, status_container: calls.append(
            {
                "mode": state.optimization_mode,
                "autonomous": state.builder_autonomous,
                "objective": state.builder_objective,
            },
        ),
    )

    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "🏗️ Strategy Builder"
    at.session_state["builder_autonomous"] = False
    at.session_state["builder_objective"] = "Construire une stratégie de test"

    at.run(timeout=60)

    assert calls == []

    next(button for button in at.button if button.label == "🏗️ Lancer le Builder").click().run(timeout=60)

    assert len(calls) == 1
    assert calls[0]["mode"] == "🏗️ Strategy Builder"
    assert calls[0]["autonomous"] is False
    assert calls[0]["objective"] == "Construire une stratégie de test"
    assert at.session_state["is_running"] is True
    assert at.session_state["run_backtest_requested"] is False


def test_app_main_does_not_restore_builder_runtime_state_on_boot(monkeypatch):
    calls = {"restore": 0}

    monkeypatch.setattr(
        builder_view_module,
        "reset_inactive_builder_live_thoughts",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        builder_view_module,
        "restore_builder_autonomous_ui_state_from_runtime",
        lambda: calls.__setitem__("restore", calls["restore"] + 1) or (True, {"active": True}),
    )
    monkeypatch.setattr(
        builder_view_module,
        "should_auto_resume_builder_autonomous",
        lambda current_state: (False, {}),
    )

    at = AppTest.from_file("ui/app.py")
    at.run(timeout=60)

    assert calls["restore"] == 0


def test_render_builder_view_manual_session_releases_running_flag(monkeypatch):
    st.session_state.clear()
    st.session_state["is_running"] = True

    sample_df = _sample_ohlcv()
    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=False,
        builder_auto_market_pick=False,
        builder_objective="Construire une stratégie robuste",
        builder_unload_after_run=False,
    )
    fake_session = SimpleNamespace(status="success", best_sharpe=1.234, iterations=[])

    monkeypatch.setattr(builder_view_module, "_inject_builder_view_styles", lambda: None)
    monkeypatch.setattr(builder_view_module, "_render_builder_mode_hero", lambda **kwargs: None)
    monkeypatch.setattr(
        builder_view_module,
        "_render_builder_live_thoughts_panel",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        builder_view_module,
        "_resolve_single_llm_runtime_route",
        lambda ollama_host, topology: (str(ollama_host), "GPU-0"),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_validate_builder_market_dataset",
        lambda **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_run_single_builder_session",
        lambda **kwargs: fake_session,
    )
    monkeypatch.setattr(builder_view_module, "show_status", lambda *args, **kwargs: None)

    builder_view_module.render_builder_view(
        state=state,
        df=sample_df,
        status_container=nullcontext(),
    )

    assert st.session_state["is_running"] is False
    assert st.session_state["builder_session"] is fake_session
    assert st.session_state["builder_last_objective"] == "Construire une stratégie robuste"


def test_render_builder_view_manual_passes_live_thoughts_placeholder_to_session(
    monkeypatch,
):
    st.session_state.clear()
    st.session_state["is_running"] = True
    st.session_state["_builder_force_ollama_start_once"] = True
    sample_df = _sample_ohlcv()
    captured: dict[str, object] = {}
    panel_calls: list[dict[str, object]] = []
    fake_session = SimpleNamespace(status="success", best_sharpe=1.234, iterations=[])

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=False,
        builder_auto_market_pick=False,
        builder_objective="Construire une stratégie robuste",
        builder_unload_after_run=False,
        builder_auto_start_ollama=False,
    )

    monkeypatch.setattr(builder_view_module, "_inject_builder_view_styles", lambda: None)
    monkeypatch.setattr(builder_view_module, "_render_builder_mode_hero", lambda **kwargs: None)
    monkeypatch.setattr(
        builder_view_module,
        "_render_builder_live_thoughts_panel",
        lambda **kwargs: panel_calls.append(dict(kwargs)),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_resolve_single_llm_runtime_route",
        lambda ollama_host, topology: (str(ollama_host), "GPU-0"),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_validate_builder_market_dataset",
        lambda **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_run_single_builder_session",
        lambda **kwargs: (
            captured.update(
                {
                    "placeholder": kwargs.get("live_thoughts_panel_placeholder"),
                    "panel_kwargs": dict(kwargs.get("live_thoughts_panel_kwargs") or {}),
                    "auto_start_ollama": kwargs.get("auto_start_ollama"),
                },
            )
            or fake_session
        ),
    )
    monkeypatch.setattr(builder_view_module, "show_status", lambda *args, **kwargs: None)

    builder_view_module.render_builder_view(
        state=state,
        df=sample_df,
        status_container=nullcontext(),
    )

    assert panel_calls
    assert captured["placeholder"] is panel_calls[0]["placeholder"]
    assert captured["panel_kwargs"] == {
        "title": "📂 Flux de pensée live (optionnel)",
        "expanded": False,
        "show_terminal_command": True,
        "tail_lines": 180,
    }
    assert captured["auto_start_ollama"] is True


def test_app_builder_mono_mode_shows_only_single_model_selector():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "🏗️ Strategy Builder"
    at.session_state["builder_execution_mode"] = BUILDER_EXECUTION_MODE_MONO

    at.run(timeout=60)

    assert at.exception == []
    assert any(selectbox.label == "Modele LLM" for selectbox in at.selectbox)
    assert all(expander.label != "🧩 Configuration Expert Multi-Role" for expander in at.expander)
    assert all(selectbox.label != "Modele lane principale" for selectbox in at.selectbox)


def test_render_builder_tab_places_model_selector_between_host_and_runtime(monkeypatch, tmp_path):
    st.session_state.clear()
    render_order: list[str] = []
    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_execution_mode=BUILDER_EXECUTION_MODE_MONO,
    )

    monkeypatch.setattr(exec_tabs_module, "_inject_builder_config_styles", lambda: None)
    monkeypatch.setattr(exec_tabs_module, "_render_builder_config_hero", lambda: None)
    monkeypatch.setattr(exec_tabs_module, "_render_inline_help_label", lambda *args, **kwargs: None)
    monkeypatch.setattr(exec_tabs_module, "_render_llm_inference_settings_editor", lambda **kwargs: None)
    monkeypatch.setattr(exec_tabs_module, "_ollama_is_available", lambda *args, **kwargs: False)
    monkeypatch.setattr(exec_tabs_module, "get_builder_sessions_dir", lambda: tmp_path / "_builder_sessions")
    monkeypatch.setattr(exec_tabs_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(exec_tabs_module.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(exec_tabs_module.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(exec_tabs_module.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(exec_tabs_module.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(exec_tabs_module.st, "success", lambda *args, **kwargs: None)
    monkeypatch.setattr(exec_tabs_module.st, "error", lambda *args, **kwargs: None)
    monkeypatch.setattr(exec_tabs_module.st, "dataframe", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        exec_tabs_module.st,
        "columns",
        lambda spec: [nullcontext() for _ in range(spec if isinstance(spec, int) else len(spec))],
    )
    monkeypatch.setattr(exec_tabs_module.st, "expander", lambda *args, **kwargs: nullcontext())

    def _stub_radio(label, options, index=0, key=None, **kwargs):
        value = options[index]
        if key is not None:
            st.session_state[key] = value
        return value

    def _stub_toggle(label, value=False, key=None, **kwargs):
        if key is not None:
            st.session_state[key] = value
        return value

    def _stub_slider(label, min_value=None, max_value=None, value=None, key=None, **kwargs):
        if key is not None:
            st.session_state[key] = value
        return value

    def _stub_number_input(label, min_value=None, max_value=None, value=None, key=None, **kwargs):
        if key is not None:
            st.session_state[key] = value
        return value

    def _stub_text_area(label, value="", key=None, **kwargs):
        if key is not None:
            st.session_state[key] = value
        return value

    def _stub_text_input(label, value="", key=None, **kwargs):
        if "URL Ollama" in label:
            render_order.append("ollama_url")
        if key is not None:
            st.session_state[key] = value
        return value

    def _stub_button(label, key=None, **kwargs):
        if key == "builder_start_ollama":
            render_order.append("runtime_action")
        return False

    def _stub_render_model_selector(**kwargs):
        render_order.append("model_selector")
        selected = str(kwargs.get("current_value") or "deepseek-r1:32b")
        key = kwargs.get("key")
        if isinstance(key, str):
            st.session_state[key] = selected
        return selected

    monkeypatch.setattr(exec_tabs_module.st, "radio", _stub_radio)
    monkeypatch.setattr(exec_tabs_module.st, "toggle", _stub_toggle)
    monkeypatch.setattr(exec_tabs_module.st, "slider", _stub_slider)
    monkeypatch.setattr(exec_tabs_module.st, "number_input", _stub_number_input)
    monkeypatch.setattr(exec_tabs_module.st, "text_area", _stub_text_area)
    monkeypatch.setattr(exec_tabs_module.st, "text_input", _stub_text_input)
    monkeypatch.setattr(exec_tabs_module.st, "button", _stub_button)
    monkeypatch.setattr(exec_tabs_module, "render_model_selector", _stub_render_model_selector)

    exec_tabs_module._render_builder_tab(state)

    assert render_order.index("ollama_url") < render_order.index("model_selector")
    assert render_order.index("model_selector") < render_order.index("runtime_action")


def test_summarize_topology_runtime_status_collapses_shared_endpoint():
    topology = build_phase1_topology(
        primary_host="http://127.0.0.1:11434",
        control_host="http://127.0.0.1:11434",
        primary_gpu_target="GPU-2",
        control_gpu_target="GPU-1",
    )

    summary = exec_tabs_module._summarize_topology_runtime_status(
        topology=topology,
        routing_mode=exec_tabs_module.LLM_ROUTING_MODE_COOPERATIVE,
    )

    assert summary["show_single_endpoint"] is True
    assert summary["shared_endpoint"] is True
    assert summary["split_effective"] is False
    assert summary["primary_host"] == "http://127.0.0.1:11434"
    assert summary["control_gpu"] == "GPU-1"


def test_request_execution_mode_change_updates_session_state():
    st.session_state.clear()
    st.session_state["optimization_mode"] = "Grille de Paramètres"

    changed = sidebar_module.request_execution_mode_change("Backtest Simple")

    assert changed is True
    assert st.session_state["optimization_mode"] == "Backtest Simple"
    assert sidebar_module.request_execution_mode_change("Backtest Simple") is False


def test_llm_tab_renders_without_widget_session_state_exception():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "🤖 Optimisation LLM"

    at.run(timeout=60)

    assert at.exception == []
    assert all(radio.label != "Mode d'exécution" for radio in at.radio)
    assert at.session_state["optimization_mode"] == "🤖 Optimisation LLM"


def test_topology_session_state_is_scoped_between_builder_and_llm_modes():
    st.session_state.clear()
    st.session_state["builder_llm_routing_mode"] = "cooperative_multi_gpu"
    st.session_state["exec_llm_routing_mode"] = "cooperative_multi_gpu"
    st.session_state["builder_llm_topology_config"] = build_phase1_topology(
        primary_host="http://127.0.0.1:11434",
        control_host="http://127.0.0.1:22434",
        primary_gpu_target="GPU-0",
        control_gpu_target="GPU-1",
        trace_only=False,
    ).to_dict()
    st.session_state["exec_llm_topology_config"] = build_phase1_topology(
        primary_host="http://127.0.0.1:33434",
        control_host="http://127.0.0.1:44434",
        primary_gpu_target="GPU-1",
        control_gpu_target="GPU-0",
        trace_only=True,
    ).to_dict()

    builder_topology = _get_phase1_topology_from_session(
        "http://127.0.0.1:11434",
        session_prefix="builder",
        config_state_key="builder_llm_topology_config",
        routing_mode_key="builder_llm_routing_mode",
    )
    exec_topology = _get_phase1_topology_from_session(
        "http://127.0.0.1:33434",
        session_prefix="exec",
        config_state_key="exec_llm_topology_config",
        routing_mode_key="exec_llm_routing_mode",
    )

    assert builder_topology.endpoints["control"].ollama_host == "http://127.0.0.1:22434"
    assert exec_topology.endpoints["control"].ollama_host == "http://127.0.0.1:44434"
    assert builder_topology.endpoints["builder_primary"].gpu_target == "GPU-0"
    assert exec_topology.endpoints["builder_primary"].gpu_target == "GPU-1"


def test_sidebar_resolves_builder_topology_from_live_session_fields():
    st.session_state.clear()
    st.session_state["builder_llm_routing_mode"] = "cooperative_multi_gpu"
    st.session_state["builder_llm_topology_config"] = build_phase1_topology(
        primary_host="http://127.0.0.1:11434",
        control_host="http://127.0.0.1:22434",
        primary_gpu_target="GPU-0",
        control_gpu_target="GPU-1",
    ).to_dict()
    st.session_state["builder_llm_topology_control_host"] = "http://127.0.0.1:55434"
    st.session_state["builder_llm_topology_primary_gpu_target"] = "GPU-1"
    st.session_state["builder_llm_topology_control_gpu_target"] = "GPU-0"

    topology = sidebar_module._resolve_live_llm_topology_config(
        optimization_mode="🏗️ Strategy Builder",
        builder_ollama_host="http://127.0.0.1:11434",
        exec_ollama_host="http://127.0.0.1:33434",
    )

    assert topology.endpoints["control"].ollama_host == "http://127.0.0.1:55434"
    assert topology.endpoints["builder_primary"].gpu_target == "GPU-1"
    assert topology.endpoints["control"].gpu_target == "GPU-0"


def test_get_phase1_topology_from_session_defaults_single_endpoint_to_auto_gpu():
    st.session_state.clear()
    st.session_state["builder_llm_routing_mode"] = "single_endpoint"

    topology = _get_phase1_topology_from_session(
        "http://127.0.0.1:11434",
        session_prefix="builder",
        config_state_key="builder_llm_topology_config",
        routing_mode_key="builder_llm_routing_mode",
    )

    assert topology.endpoints["builder_primary"].gpu_target == "auto"


def test_get_phase1_topology_from_session_migrates_legacy_single_endpoint_gpu_target_to_auto():
    st.session_state.clear()
    st.session_state["builder_llm_routing_mode"] = "single_endpoint"
    st.session_state["builder_llm_topology_config"] = build_single_host_topology(
        primary_host="http://127.0.0.1:11434",
        primary_gpu_target="GPU-0",
    ).to_dict()

    topology = _get_phase1_topology_from_session(
        "http://127.0.0.1:11434",
        session_prefix="builder",
        config_state_key="builder_llm_topology_config",
        routing_mode_key="builder_llm_routing_mode",
    )

    assert topology.endpoints["builder_primary"].gpu_target == "auto"


def test_get_phase1_topology_from_session_preserves_explicit_single_endpoint_gpu_selection():
    st.session_state.clear()
    st.session_state["builder_llm_routing_mode"] = "single_endpoint"
    st.session_state["builder_llm_topology_config"] = build_single_host_topology(
        primary_host="http://127.0.0.1:11434",
        primary_gpu_target="GPU-0",
    ).to_dict()
    st.session_state["builder_llm_topology_primary_gpu_target"] = "GPU-1"

    topology = _get_phase1_topology_from_session(
        "http://127.0.0.1:11434",
        session_prefix="builder",
        config_state_key="builder_llm_topology_config",
        routing_mode_key="builder_llm_routing_mode",
    )

    assert topology.endpoints["builder_primary"].gpu_target == "GPU-1"


def test_execute_clean_stop_resets_runtime_and_marks_manual_stop(monkeypatch):
    st.session_state.clear()
    st.session_state["is_running"] = True
    st.session_state["stop_requested"] = False
    st.session_state["run_backtest_requested"] = True
    st.session_state["load_ohlcv_requested"] = True
    st.session_state["builder_autonomous"] = True
    st.session_state["builder_session"] = {"session_id": "demo"}
    st.session_state["builder_runtime_diagnostic"] = {"status": "running"}
    st.session_state["builder_autonomous_history"] = [{"session_num": 1}]
    st.session_state["builder_autonomous_supervisor"] = {"active": True}
    st.session_state["exec_llm_ollama_host"] = "http://127.0.0.1:22434"

    cleanup_call: dict[str, object] = {}
    marked_stop: dict[str, object] = {}

    monkeypatch.setattr(
        emergency_stop_module,
        "execute_emergency_stop",
        lambda session_state=None, **kwargs: (
            cleanup_call.update(
                {
                    "session_state": session_state,
                    "ollama_hosts": list(kwargs.get("ollama_hosts", []) or []),
                    "cache_callback_count": len(list(kwargs.get("cache_callbacks", []) or [])),
                },
            ),
            session_state.__setitem__("stop_requested", True),
            session_state.__setitem__("is_running", False),
            session_state.__setitem__("run_backtest_requested", False),
            session_state.__setitem__("load_ohlcv_requested", False),
            {
                "components_cleaned": ["session_flags", "garbage_collector"],
                "errors": [],
                "ollama_unloaded": {
                    "http://127.0.0.1:11434": 1,
                    "http://127.0.0.1:22434": 1,
                },
                "ollama_stopped": {
                    "http://127.0.0.1:11434": 1,
                    "http://127.0.0.1:22434": 1,
                },
                "ollama_remaining": {},
            },
        )[-1],
    )
    monkeypatch.setattr(
        builder_view_module,
        "mark_builder_autonomous_runtime_stopped",
        lambda **kwargs: marked_stop.update(kwargs),
    )

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=True,
        builder_ollama_host="http://127.0.0.1:11434",
    )

    main_module._execute_clean_stop(state)

    assert st.session_state["is_running"] is False
    assert st.session_state["stop_requested"] is False
    assert st.session_state["run_backtest_requested"] is False
    assert st.session_state["load_ohlcv_requested"] is False
    assert get_ui_execution_phase(st.session_state) == UI_EXECUTION_PHASE_IDLE
    assert "builder_session" not in st.session_state
    assert "builder_runtime_diagnostic" not in st.session_state
    assert "builder_autonomous_history" not in st.session_state
    assert "builder_autonomous_supervisor" not in st.session_state
    assert cleanup_call["session_state"] is st.session_state
    assert cleanup_call["ollama_hosts"] == [
        "http://127.0.0.1:11434",
        "http://127.0.0.1:22434",
    ]
    assert cleanup_call["cache_callback_count"] == 3
    assert marked_stop == {"reason": "manual_stop", "manual_stop": True}
    assert st.session_state["main_action_feedback"]["tone"] == "success"


def test_execute_clean_stop_keeps_builder_rerunnable(monkeypatch):
    st.session_state.clear()
    st.session_state["is_running"] = True
    st.session_state["builder_session"] = {"session_id": "demo"}
    st.session_state["builder_runtime_diagnostic"] = {"status": "running"}
    st.session_state["ohlcv_df"] = _sample_ohlcv()
    st.session_state["ohlcv_status_msg"] = ""

    launched: list[dict[str, object]] = []

    monkeypatch.setattr(
        emergency_stop_module,
        "execute_emergency_stop",
        lambda session_state=None, **kwargs: (
            session_state.__setitem__("stop_requested", True),
            session_state.__setitem__("is_running", False),
            session_state.__setitem__("run_backtest_requested", False),
            session_state.__setitem__("load_ohlcv_requested", False),
            {
                "components_cleaned": ["session_flags", "garbage_collector"],
                "errors": [],
                "ollama_unloaded": {"http://127.0.0.1:11434": 1},
                "ollama_stopped": {"http://127.0.0.1:11434": 1},
                "ollama_remaining": {},
            },
        )[-1],
    )
    monkeypatch.setattr(
        builder_view_module,
        "mark_builder_autonomous_runtime_stopped",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        builder_view_module,
        "should_auto_resume_builder_autonomous",
        lambda current_state: (False, {}),
    )
    monkeypatch.setattr(main_module, "validate_all_params", lambda params: (True, []))
    monkeypatch.setattr(main_module, "show_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        main_module,
        "_render_builder_view_safe",
        lambda state, df, status_container: launched.append(
            {
                "mode": state.optimization_mode,
                "objective": state.builder_objective,
            },
        ),
    )

    state = _sample_sidebar_state(
        optimization_mode="🏗️ Strategy Builder",
        builder_autonomous=False,
        builder_objective="Relancer après cleanup",
        builder_ollama_host="http://127.0.0.1:11434",
    )

    main_module._execute_clean_stop(state)
    assert st.session_state["stop_requested"] is False
    assert get_ui_execution_phase(st.session_state) == UI_EXECUTION_PHASE_IDLE

    main_module._queue_main_run_action("🏗️ Strategy Builder")
    run_requested = consume_ui_run_request(st.session_state)
    render_main(state, run_requested, nullcontext())

    assert run_requested is True
    assert len(launched) == 1
    assert launched[0]["mode"] == "🏗️ Strategy Builder"
    assert launched[0]["objective"] == "Relancer après cleanup"
    assert st.session_state["is_running"] is True
    assert st.session_state["stop_requested"] is False


def test_execute_emergency_stop_cleans_runtime_hosts_and_callbacks(monkeypatch):
    st.session_state.clear()
    st.session_state["is_running"] = True
    st.session_state["stop_requested"] = False
    st.session_state["run_backtest_requested"] = True
    st.session_state["load_ohlcv_requested"] = True
    st.session_state["last_run_result"] = {"status": "stale"}

    unload_calls: list[str] = []
    stop_calls: list[tuple[str, bool]] = []
    callback_calls: list[str] = []

    monkeypatch.setattr(
        emergency_stop_module,
        "_cleanup_indicator_cache",
        lambda stats: stats["components_cleaned"].append("indicator_memory_cache"),
    )
    monkeypatch.setattr(
        emergency_stop_module,
        "_cleanup_memory_manager",
        lambda stats: stats["components_cleaned"].append("memory_manager"),
    )
    monkeypatch.setattr(
        emergency_stop_module,
        "_cleanup_pytorch",
        lambda stats: stats["components_cleaned"].append("pytorch_cuda"),
    )
    monkeypatch.setattr(
        emergency_stop_module,
        "clear_data_cache",
        lambda: callback_calls.append("data_cache"),
    )
    monkeypatch.setattr(
        emergency_stop_module,
        "cleanup_all_models",
        lambda ollama_host=None: (
            unload_calls.append(str(ollama_host or "")) or (1 if str(ollama_host or "").endswith("11434") else 0)
        ),
    )
    monkeypatch.setattr(
        emergency_stop_module,
        "_list_loaded_models_for_host",
        lambda host: ["qwen3-coder:30b"] if host.endswith("22434") else [],
    )
    monkeypatch.setattr(
        emergency_stop_module,
        "stop_local_ollama_server",
        lambda ollama_host=None, force=True, owned_only=False, timeout_s=3.0: (
            stop_calls.append(
                (str(ollama_host or ""), bool(owned_only)),
            )
            or 1
        ),
    )
    monkeypatch.setattr(emergency_stop_module.gc, "collect", lambda: 7)

    stats = emergency_stop_module.execute_emergency_stop(
        st.session_state,
        ollama_hosts=[
            "http://127.0.0.1:11434",
            "http://127.0.0.1:22434",
            "http://127.0.0.1:11434",
        ],
        cache_callbacks=(lambda: callback_calls.append("custom_cache"),),
    )

    assert st.session_state["is_running"] is False
    assert st.session_state["stop_requested"] is True
    assert st.session_state["run_backtest_requested"] is False
    assert st.session_state["load_ohlcv_requested"] is False
    assert get_ui_execution_phase(st.session_state) == UI_EXECUTION_PHASE_STOPPING
    assert "last_run_result" not in st.session_state
    assert unload_calls == [
        "http://127.0.0.1:11434",
        "http://127.0.0.1:22434",
    ]
    assert ("http://127.0.0.1:11434", True) in stop_calls
    assert ("http://127.0.0.1:22434", False) in stop_calls
    assert callback_calls == ["data_cache", "custom_cache"]
    assert stats["ollama_unloaded"]["http://127.0.0.1:11434"] == 1
    assert stats["ollama_unloaded"]["http://127.0.0.1:22434"] == 0
    assert stats["ollama_remaining"]["http://127.0.0.1:22434"] == ["qwen3-coder:30b"]
    assert stats["ollama_stopped"]["http://127.0.0.1:11434"] == 1
    assert stats["ollama_stopped"]["http://127.0.0.1:22434"] == 1
    assert stats["gc_collected_objects"] == 7


def test_terminate_owned_ollama_process_terminates_child_tree(monkeypatch):
    class _FakeTrackedProcess:
        def __init__(self, pid: int, children=None) -> None:
            self.pid = pid
            self._children = list(children or [])
            self.terminate_calls = 0
            self.kill_calls = 0

        def children(self, recursive: bool = True):
            assert recursive is True
            return list(self._children)

        def terminate(self) -> None:
            self.terminate_calls += 1

        def kill(self) -> None:
            self.kill_calls += 1

    class _FakePopen:
        def __init__(self, pid: int) -> None:
            self.pid = pid
            self._returncode = None

        def poll(self):
            return self._returncode

        def wait(self, timeout: float = 0.0):
            self._returncode = 0
            return 0

        def terminate(self) -> None:
            self._returncode = 0

        def kill(self) -> None:
            self._returncode = 0

    child_a = _FakeTrackedProcess(201)
    child_b = _FakeTrackedProcess(202)
    root = _FakeTrackedProcess(111, children=[child_a, child_b])
    process = _FakePopen(111)

    def _wait_procs(procs, timeout: float = 0.0):
        process._returncode = 0
        return list(procs), []

    fake_psutil = SimpleNamespace(
        Process=lambda pid: root,
        wait_procs=_wait_procs,
        Error=RuntimeError,
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    record = ollama_manager_module._OwnedOllamaProcess(
        host="http://127.0.0.1:11434",
        process=process,
    )
    stopped = ollama_manager_module._terminate_owned_ollama_process(
        record,
        timeout_s=1.0,
    )

    assert stopped == 1
    assert root.terminate_calls == 1
    assert child_a.terminate_calls == 1
    assert child_b.terminate_calls == 1
    assert root.kill_calls == 0
    assert child_a.kill_calls == 0
    assert child_b.kill_calls == 0


def test_resolve_builder_runtime_preferences_reads_sidebar_state_without_reset():
    state = _sample_sidebar_state(
        builder_preload_model=False,
        builder_keep_alive_minutes=45,
        builder_unload_after_run=True,
        builder_auto_start_ollama=False,
    )

    resolved = resolve_builder_runtime_preferences(state)

    assert resolved == {
        "builder_auto_start_ollama": False,
        "builder_preload_model": False,
        "builder_keep_alive_minutes": 45,
        "builder_unload_after_run": True,
    }


def test_resolve_builder_runtime_preferences_prefers_live_widget_values():
    resolved = resolve_builder_runtime_preferences(
        {
            "builder_auto_start_ollama": True,
            "builder_preload_model": True,
            "builder_keep_alive_minutes": 20,
            "builder_unload_after_run": False,
            "builder_auto_start_ollama_toggle": False,
            "builder_preload_model_toggle": False,
            "builder_keep_alive_minutes_input": 60,
            "builder_unload_after_run_toggle": True,
        },
    )

    assert resolved == {
        "builder_auto_start_ollama": False,
        "builder_preload_model": False,
        "builder_keep_alive_minutes": 60,
        "builder_unload_after_run": True,
    }


def test_resolve_requested_model_passes_through_cloud_only_without_local_alias_fallback():
    resolved_model, message, found = _resolve_requested_model(
        "qwen3-coder:480b",
        ["qwen3-coder:30b", "qwen3.5:35b"],
        allow_fallback=False,
    )

    assert found is True
    assert resolved_model == "qwen3-coder:480b"
    assert "cloud-only" in message
    assert "substitution locale" in message


def test_ollama_request_helpers_are_canonicalized_across_layers(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-test-key")

    host = "127.0.0.1:11434/api"
    model = "qwen3-vl:235b"
    manager_ctx = ollama_manager_module.resolve_ollama_request_context(host, model_name=model)

    assert llm_client_module.resolve_ollama_request_context is ollama_manager_module.resolve_ollama_request_context
    assert builder_view_module.resolve_ollama_request_context is ollama_manager_module.resolve_ollama_request_context
    assert llm_client_module.get_ollama_cloud_runtime_model_candidates is (
        ollama_manager_module.get_ollama_cloud_runtime_model_candidates
    )
    assert builder_view_module.strip_ollama_cloud_model_alias is ollama_manager_module.strip_ollama_cloud_model_alias
    assert builder_view_module.is_ollama_cloud_model is ollama_manager_module.is_ollama_cloud_model

    assert llm_client_module.resolve_ollama_request_context(host, model_name=model) == manager_ctx
    assert builder_view_module.resolve_ollama_request_context(host, model_name=model) == manager_ctx
    assert manager_ctx["requested_host"] == "http://127.0.0.1:11434"
    assert manager_ctx["effective_host"] == "https://ollama.com"
    assert manager_ctx["request_model"] == model

    cloud_suffix_ctx = ollama_manager_module.resolve_ollama_request_context(
        host,
        model_name="deepseek-v4-pro:cloud",
    )
    assert cloud_suffix_ctx["effective_host"] == "https://ollama.com"
    assert cloud_suffix_ctx["request_model"] == "deepseek-v4-pro"
    assert ollama_manager_module.get_ollama_cloud_runtime_model_candidates(
        "deepseek-v4-pro",
        direct_cloud=False,
    )[:2] == ["deepseek-v4-pro", "deepseek-v4-pro:cloud"]


def test_get_available_models_for_ui_uses_runtime_catalog_when_ollama_is_down(monkeypatch):
    monkeypatch.setattr(
        model_selector_module,
        "_get_installed_ollama_models",
        lambda ollama_host=None: [],
    )
    monkeypatch.setattr(
        model_selector_module,
        "_get_local_inventory_models",
        lambda ollama_host=None: [],
    )
    monkeypatch.setattr(
        model_selector_module,
        "_get_library_models",
        lambda: ["qwen3-coder:30b", "devstral-small-2:24b"],
    )

    models = model_selector_module.get_available_models_for_ui(
        ollama_host="http://127.0.0.1:65535",
    )

    assert "qwen3-coder:30b" in models
    assert "devstral-small-2:24b" in models
    assert "qwen3-coder:480b" in models
    assert "deepseek-v4-pro" in models
    assert "deepseek-v4-flash" in models
    assert "kimi-k2.6" in models


def test_get_available_models_for_ui_normalizes_gemma4_variant_tags(monkeypatch):
    monkeypatch.setattr(
        model_selector_module,
        "_get_installed_ollama_models",
        lambda ollama_host=None: ["gemma4:31b-it-q4_K_M", "gemma4:26b-a4b-it-q8_0"],
    )
    monkeypatch.setattr(
        model_selector_module,
        "_get_local_inventory_models",
        lambda ollama_host=None: [],
    )
    monkeypatch.setattr(
        model_selector_module,
        "_get_library_models",
        list,
    )

    models = model_selector_module.get_available_models_for_ui(
        preferred_order=["gemma4:31b", "gemma4:26b"],
        ollama_host="http://127.0.0.1:11434",
    )

    assert models[:2] == ["gemma4:31b", "gemma4:26b"]


def test_available_runtime_role_models_includes_cloud_only_models():
    inventory = SimpleNamespace(
        discovered_models=[
            SimpleNamespace(
                name="qwen3-coder:30b",
                verified_available=True,
                backend="ollama",
                live=True,
                role_hints=["builder_llm"],
            ),
        ],
        live_ollama_reachable=True,
    )

    models = exec_tabs_module._available_runtime_role_models(inventory, "builder_llm")

    assert "qwen3-coder:30b" in models
    assert "qwen3-coder:480b" in models
    assert "devstral-2:123b" in models
    assert "deepseek-v4-pro" in models
    assert "kimi-k2.6" in models


def test_available_runtime_role_models_skips_runtime_cloud_alias_duplicates():
    inventory = SimpleNamespace(
        discovered_models=[
            SimpleNamespace(
                name="qwen3-coder:30b",
                verified_available=True,
                backend="ollama",
                live=True,
                role_hints=["builder_llm"],
                metadata={},
            ),
            SimpleNamespace(
                name="gpt-oss:120b-cloud",
                verified_available=True,
                backend="ollama",
                live=True,
                role_hints=["builder_llm"],
                metadata={"cloud_only": True, "remote_model": "gpt-oss:120b"},
            ),
        ],
        live_ollama_reachable=True,
    )

    models = exec_tabs_module._available_runtime_role_models(inventory, "builder_llm")

    assert "gpt-oss:120b-cloud" not in models
    assert "gpt-oss:120b" in models


def test_collect_builder_cloud_runtime_rows_detects_live_alias(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.setattr(
        exec_tabs_module,
        "probe_model_runtime_acceptance",
        lambda *args, **kwargs: {"accepted": False, "message": "not used"},
    )
    monkeypatch.setattr(
        exec_tabs_module,
        "discover_local_models",
        lambda ollama_host=None, include_live_ollama=True: SimpleNamespace(
            live_ollama_reachable=True,
            discovered_models=[
                SimpleNamespace(
                    name="qwen3-vl:235b-cloud",
                    backend="ollama",
                    live=True,
                    metadata={"remote_model": "qwen3-vl:235b"},
                ),
            ],
        ),
    )

    rows = exec_tabs_module._collect_builder_cloud_runtime_rows(
        [
            {
                "label": "builder_llm",
                "host": "http://127.0.0.1:11434",
                "model": "qwen3-vl:235b",
            },
        ],
    )

    assert rows == [
        {
            "cible": "builder_llm",
            "modèle": "qwen3-vl:235b",
            "host": "http://127.0.0.1:11434",
            "status": "alias_visible",
            "détail": "Alias runtime cloud visible dans /api/tags.",
        },
    ]


def test_collect_builder_cloud_runtime_rows_flags_missing_alias_and_api_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.setattr(
        exec_tabs_module,
        "probe_model_runtime_acceptance",
        lambda *args, **kwargs: {
            "accepted": False,
            "message": "Le runtime local signé n'accepte pas ce modèle.",
        },
    )
    monkeypatch.setattr(
        exec_tabs_module,
        "discover_local_models",
        lambda ollama_host=None, include_live_ollama=True: SimpleNamespace(
            live_ollama_reachable=True,
            discovered_models=[
                SimpleNamespace(
                    name="qwen3-coder:30b",
                    backend="ollama",
                    live=True,
                    metadata={},
                ),
            ],
        ),
    )

    rows = exec_tabs_module._collect_builder_cloud_runtime_rows(
        [
            {
                "label": "builder_llm",
                "host": "http://127.0.0.1:11434",
                "model": "qwen3-vl:235b",
            },
        ],
    )

    assert rows[0]["status"] == "unavailable"
    assert "n'accepte pas" in rows[0]["détail"]


def test_collect_builder_cloud_runtime_rows_detects_local_signed_in_runtime(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.setattr(
        exec_tabs_module,
        "probe_model_runtime_acceptance",
        lambda *args, **kwargs: {
            "accepted": True,
            "resolved_model": "glm-5:cloud",
            "message": "accepted",
        },
    )
    monkeypatch.setattr(
        exec_tabs_module,
        "discover_local_models",
        lambda ollama_host=None, include_live_ollama=True: SimpleNamespace(
            live_ollama_reachable=True,
            discovered_models=[],
        ),
    )

    rows = exec_tabs_module._collect_builder_cloud_runtime_rows(
        [
            {
                "label": "builder_llm",
                "host": "http://127.0.0.1:11434",
                "model": "glm-5",
            },
        ],
    )

    assert rows == [
        {
            "cible": "builder_llm",
            "modèle": "glm-5",
            "host": "http://127.0.0.1:11434",
            "status": "local_signin",
            "détail": "Runtime cloud local accepté via `ollama signin` (`glm-5:cloud`).",
        },
    ]


def test_assignment_resolution_transport_label_detects_cloud_via_signin():
    assignment = SimpleNamespace(
        source="ollama_cloud_local_runtime",
        backend="ollama",
        resolved_model="glm-5",
        metadata={"cloud_only": True},
        available=True,
    )

    assert exec_tabs_module._assignment_resolution_transport_label(assignment) == "cloud_via_signin"


def test_resolve_builder_flow_analysis_preferences_prefers_widget_and_disabled_steps():
    resolved = resolve_builder_flow_analysis_preferences(
        {
            "builder_flow_analysis_enabled": False,
            "builder_flow_analysis_enabled_toggle": True,
            "builder_flow_analysis_ablation": {
                "code_repair": True,
                "precheck": True,
                "runtime_fix": True,
            },
            "builder_flow_analysis_disabled_steps_multiselect": [
                "precheck",
                "runtime_fix",
            ],
        },
    )

    assert resolved["builder_flow_analysis_enabled"] is True
    assert resolved["builder_flow_analysis_ablation"]["code_repair"] is True
    assert resolved["builder_flow_analysis_ablation"]["precheck"] is False
    assert resolved["builder_flow_analysis_ablation"]["runtime_fix"] is False


def test_builder_flow_analysis_presets_include_local_stable():
    label, disabled_steps = exec_tabs_module._BUILDER_FLOW_ANALYSIS_PRESETS["local_stable"]

    assert label == "🪶 Local stable"
    assert "llm_analysis" in disabled_steps
    assert "pre_reflection" in disabled_steps
    assert "stagnation_branching" in disabled_steps
    assert "code_repair" not in disabled_steps


def test_builder_flow_analysis_presets_keep_fast_and_debug_runtime_targets():
    fast_label, fast_disabled = exec_tabs_module._BUILDER_FLOW_ANALYSIS_PRESETS["fast"]
    debug_label, debug_disabled = exec_tabs_module._BUILDER_FLOW_ANALYSIS_PRESETS["debug"]

    assert fast_label == "⚡ Analyse rapide"
    assert fast_disabled == [
        "llm_analysis",
        "indicator_ranking",
        "iteration_history",
        "diagnostic_context",
    ]
    assert debug_label == "🧪 Debug pipeline"
    assert "runtime_fix" in debug_disabled
    assert "code_repair" in debug_disabled
    assert "indicator_binding" in debug_disabled


def test_pick_builder_session_role_overrides_freezes_ordered_queue_per_role(monkeypatch):
    monkeypatch.setattr(builder_view_module.random, "shuffle", lambda pool: None)

    selected = builder_view_module._pick_builder_session_role_overrides(
        {
            "idea_llm": ["gemma4:26b", "qwen2.5:14b"],
            "builder_llm": ["qwen3-coder:30b", "qwen2.5-coder:14b"],
            "critic_llm": ["deepseek-r1:14b"],
            "risk_llm": ["mistral:7b-instruct", "llama3.1:8b"],
        },
    )

    assert selected == {
        "idea_llm": ["gemma4:26b", "qwen2.5:14b"],
        "builder_llm": ["qwen3-coder:30b", "qwen2.5-coder:14b"],
        "critic_llm": ["deepseek-r1:14b"],
        "risk_llm": ["mistral:7b-instruct", "llama3.1:8b"],
    }


def test_pick_builder_session_role_overrides_prefers_runtime_visible_cloud_candidates(monkeypatch):
    monkeypatch.setattr(builder_view_module.random, "shuffle", lambda pool: None)

    class _Inventory:
        live_ollama_reachable = True

        @staticmethod
        def find(name):
            if name == "gpt-oss:120b":
                return SimpleNamespace(live=True)
            if name == "deepseek-v3.1":
                return SimpleNamespace(live=True)
            return None

    selected = builder_view_module._pick_builder_session_role_overrides(
        {
            "builder_llm": [
                "qwen3-coder:480b",
                "devstral-2:123b",
                "gpt-oss:120b",
                "deepseek-v3.1",
            ],
            "critic_llm": [
                "deepseek-v3.2",
                "deepseek-v3.1",
                "gpt-oss:120b",
            ],
        },
        inventory=_Inventory(),
    )

    assert selected["builder_llm"] == [
        "qwen3-coder:480b",
        "devstral-2:123b",
        "gpt-oss:120b",
        "deepseek-v3.1",
    ]
    assert selected["critic_llm"] == ["deepseek-v3.2", "deepseek-v3.1", "gpt-oss:120b"]


def test_pick_builder_session_role_overrides_skips_local_candidates_not_exposed_by_live_host(
    monkeypatch,
):
    monkeypatch.setattr(builder_view_module.random, "shuffle", lambda pool: None)

    class _Inventory:
        live_ollama_reachable = True
        live_ollama_host = "http://127.0.0.1:11434"

        @staticmethod
        def find(name):
            if name == "gemma4:26b":
                return SimpleNamespace(verified_available=True, live=False)
            if name == "nemotron-orchestrator-8b":
                return SimpleNamespace(verified_available=True, live=True)
            if name == "deepseek-r1:32b":
                return SimpleNamespace(verified_available=True, live=False)
            if name == "deepseek-r1-distill:14b":
                return SimpleNamespace(verified_available=True, live=True)
            return None

    selected = builder_view_module._pick_builder_session_role_overrides(
        {
            "builder_llm": ["gemma4:26b", "nemotron-orchestrator-8b"],
            "critic_llm": ["deepseek-r1:32b", "deepseek-r1-distill:14b"],
        },
        inventory=_Inventory(),
    )

    assert selected["builder_llm"] == ["nemotron-orchestrator-8b"]
    assert selected["critic_llm"] == ["deepseek-r1-distill:14b"]


def test_pick_builder_session_role_overrides_accepts_direct_cloud_candidates_with_api_key(
    monkeypatch,
):
    monkeypatch.setattr(builder_view_module.random, "shuffle", lambda pool: None)
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-test-key")

    class _Inventory:
        live_ollama_reachable = True
        live_ollama_host = "http://127.0.0.1:11434"

        @staticmethod
        def find(name):
            if name == "deepseek-r1-distill:14b":
                return SimpleNamespace(verified_available=True, live=True)
            return None

    selected = builder_view_module._pick_builder_session_role_overrides(
        {
            "critic_llm": ["qwen3-coder:480b", "deepseek-r1-distill:14b"],
        },
        inventory=_Inventory(),
    )

    assert selected["critic_llm"] == ["qwen3-coder:480b", "deepseek-r1-distill:14b"]


def test_pick_builder_session_role_overrides_keeps_local_cloud_candidates_when_live_host_is_local(
    monkeypatch,
):
    monkeypatch.setattr(builder_view_module.random, "shuffle", lambda pool: None)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)

    class _Inventory:
        live_ollama_reachable = True
        live_ollama_host = "http://127.0.0.1:11434"

        @staticmethod
        def find(name):
            if name == "deepseek-r1-distill:14b":
                return SimpleNamespace(verified_available=True, live=True)
            return None

    selected = builder_view_module._pick_builder_session_role_overrides(
        {
            "critic_llm": ["glm-5", "deepseek-r1-distill:14b"],
        },
        inventory=_Inventory(),
    )

    assert selected["critic_llm"] == ["glm-5", "deepseek-r1-distill:14b"]


def test_pick_builder_session_role_overrides_tries_cloud_before_local_when_pool_is_mixed(monkeypatch):
    monkeypatch.setattr(builder_view_module.random, "shuffle", lambda pool: None)

    selected = builder_view_module._pick_builder_session_role_overrides(
        {
            "builder_llm": ["gemma4:26b", "qwen3-coder:480b", "devstral-2:123b"],
        },
    )

    assert selected["builder_llm"] == ["qwen3-coder:480b", "devstral-2:123b", "gemma4:26b"]


def test_results_hub_chart_builders_switch_between_points_and_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, dict[str, object]]] = []

    def _capture(kind: str):
        def _factory(*args, **kwargs):
            captured.append((kind, kwargs))
            return {"kind": kind, "kwargs": kwargs}

        return _factory

    monkeypatch.setattr(
        results_hub_module,
        "px",
        SimpleNamespace(
            histogram=_capture("histogram"),
            scatter=_capture("scatter"),
            bar=_capture("bar"),
        ),
    )

    df = pd.DataFrame(
        {
            "total_return_pct": [10.0, -5.0, 3.0],
            "sharpe_ratio": [1.2, -0.4, 0.8],
            "max_drawdown_pct": [-12.0, -25.0, -8.0],
            "type": ["run", "run", "builder"],
            "id": ["r1", "r2", "r3"],
            "strategy": ["ema", "rsi", "macd"],
            "symbol": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "timeframe": ["1h", "4h", "1h"],
        }
    )

    return_points = _build_return_chart(df, results_hub_module.CHART_MODE_POINTS)
    risk_columns = _build_sharpe_drawdown_chart(df, results_hub_module.CHART_MODE_COLUMNS)

    assert return_points["kind"] == "scatter"
    assert risk_columns["kind"] == "bar"
    assert captured[0][0] == "scatter"
    assert captured[1][0] == "bar"


def test_render_charts_uses_selected_chart_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    selected_modes: list[str] = []
    rendered: list[object] = []

    monkeypatch.setattr(results_hub_module, "PLOTLY_AVAILABLE", True)
    monkeypatch.setattr(results_hub_module.st, "columns", lambda n: [nullcontext() for _ in range(n)])

    def _radio(label: str, options: list[str], index: int, horizontal: bool, key: str) -> str:
        return results_hub_module.CHART_MODE_POINTS if "rendement" in label.lower() else results_hub_module.CHART_MODE_COLUMNS

    monkeypatch.setattr(results_hub_module.st, "radio", _radio)
    monkeypatch.setattr(results_hub_module.st, "plotly_chart", lambda fig, width=None: rendered.append(fig))
    monkeypatch.setattr(
        results_hub_module,
        "_build_return_chart",
        lambda df, chart_mode: selected_modes.append(f"return:{chart_mode}") or {"chart": "return"},
    )
    monkeypatch.setattr(
        results_hub_module,
        "_build_sharpe_drawdown_chart",
        lambda df, chart_mode: selected_modes.append(f"risk:{chart_mode}") or {"chart": "risk"},
    )

    df = pd.DataFrame(
        {
            "total_return_pct": [1.0, 2.0],
            "sharpe_ratio": [0.4, 0.9],
            "max_drawdown_pct": [-10.0, -5.0],
        }
    )

    results_hub_module._render_charts(df)

    assert selected_modes == [
        f"return:{results_hub_module.CHART_MODE_POINTS}",
        f"risk:{results_hub_module.CHART_MODE_COLUMNS}",
    ]
    assert rendered == [{"chart": "return"}, {"chart": "risk"}]
