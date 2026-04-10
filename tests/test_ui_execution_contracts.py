from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

import ui.builder_view as builder_view_module
import ui.components.agent_timeline as agent_timeline_module
import ui.components.monitor as monitor_module
import agents.model_config as model_config_module
import agents.ollama_manager as ollama_manager_module
import backtest.worker as worker_module
import streamlit as st
import ui.emergency_stop as emergency_stop_module
import ui.components.sweep_monitor as sweep_monitor_module
import ui.components.validation_viewer as validation_viewer_module
from backtest.engine import BacktestEngine
from backtest.worker import init_worker_with_dataframe, run_backtest_worker
import ui.helpers as helpers_module
import ui.exec_tabs as exec_tabs_module
import ui.sidebar as sidebar_module
from ui.exec_tabs import _get_phase1_topology_from_session, _prime_multiselect_state
from ui.helpers import (
    compute_period_days,
    format_pnl_with_daily,
    get_partial_result_notice,
    mark_result_as_partial,
    safe_run_backtest,
    _build_saved_run_label,
)
from agents.llm_router import build_phase1_topology
from ui.main import (
    _build_multi_sweep_grid_entry,
    _build_param_combo_iter,
    _describe_grid_completion,
    _run_grid_sequential,
    render_main,
)
from ui.builder_view import (
    _get_autonomous_recap_status_badge,
    _get_builder_code_provenance_badge,
    _history_best_sharpe,
    _choose_autonomous_objective_mode,
    _classify_autonomous_failure_origin,
    _find_first_valid_builder_market,
    _has_builder_market_df,
    _pick_market_for_objective,
    _plan_autonomous_recovery,
    _resolve_requested_model,
    _select_autonomous_market_for_session,
    _sanitize_builder_stream_text,
)
import ui.components.model_selector as model_selector_module
import ui.main as main_module
from ui.results_hub import (
    _add_pnl_per_day,
    _build_catalog_replay_request,
    _build_run_row_replay_request,
    _extract_catalog_postfilter_fields,
    _get_numeric_column_config,
    _normalize_backtest_overview_df,
    _normalize_graduation_candidate_df,
    _safe_read_csv,
)
from ui.components.strategy_catalog_panel import _catalog_postfilter_fields
from ui.sidebar import _apply_catalog_replay_request_to_state, _apply_config_guard, _resolve_default_cpu_workers
from ui.state import (
    BUILDER_EXECUTION_MODE_DUAL_LANE,
    BUILDER_EXECUTION_MODE_EXPERT,
    BUILDER_EXECUTION_MODE_MONO,
    SidebarState,
    resolve_builder_dual_lane_preferences,
    resolve_builder_execution_preferences,
    resolve_builder_flow_analysis_preferences,
    resolve_builder_multi_llm_preferences,
    resolve_builder_runtime_preferences,
)


def _sample_ohlcv(n_bars: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    index = pd.date_range("2025-01-01", periods=n_bars, freq="1h", tz="UTC")
    close = 100 + np.cumsum(rng.normal(0.0, 0.8, n_bars))
    open_ = close + rng.normal(0.0, 0.2, n_bars)
    high = np.maximum(open_, close) + 0.5
    low = np.minimum(open_, close) - 0.5
    volume = rng.integers(1_000, 5_000, n_bars)
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
        "builder_dual_lane_primary_model": "deepseek-r1:32b",
        "builder_dual_lane_critic_model": "deepseek-r1:32b",
        "builder_multi_llm_enabled": False,
        "builder_multi_llm_profile": "24GB_balanced",
        "builder_multi_llm_role_overrides": {},
        "builder_flow_analysis_enabled": False,
        "builder_flow_analysis_ablation": {},
        "builder_use_parametric_catalog": False,
    }
    payload.update(overrides)
    return SidebarState(**payload)


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
            {"mode": state.optimization_mode, "df": df}
        ),
    )

    render_main(state, True, nullcontext())

    assert captured["mode"] == "🏗️ Strategy Builder"
    assert captured["df"] is None


def test_sample_sidebar_state_defaults_multi_llm_disabled():
    state = _sample_sidebar_state(optimization_mode="🏗️ Strategy Builder")

    assert state.builder_multi_llm_enabled is False
    assert state.builder_multi_llm_profile == "24GB_balanced"
    assert state.builder_multi_llm_role_overrides == {}


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
            }
        ]
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
                "multi_ctx_results": {"passed_count": 2, "total_contexts": 3},
            }
        ]
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
            }
        ]
    )

    normalized = _normalize_backtest_overview_df(df)
    enriched = _add_pnl_per_day(normalized)

    assert enriched.loc[0, "period_days"] == 30.0
    assert enriched.loc[0, "pnl_per_day"] == 10.0


def test_safe_read_csv_disables_low_memory_for_mixed_catalog_columns(tmp_path, monkeypatch):
    csv_path = tmp_path / "overview.csv"
    csv_path.write_text("a,b\n1,x\n2,y\n", encoding="utf-8")

    captured: dict[str, object] = {}

    def _fake_read_csv(path, *args, **kwargs):
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


def test_ensure_ollama_running_uses_current_store_and_clears_gpu_pinning_on_default_host(
    monkeypatch,
):
    ollama_manager_module._OWNED_OLLAMA_PROCESSES.clear()
    ollama_manager_module._OLLAMA_PINNING_RESTARTED_HOSTS.clear()
    attempts = {"count": 0}
    captured: dict[str, object] = {}

    def _fetch_stub(*args, **kwargs):
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
    assert "CUDA_VISIBLE_DEVICES" not in env
    assert "GPU_DEVICE_ORDINAL" not in env


def test_ensure_ollama_running_pins_gpu_for_dedicated_host(monkeypatch):
    ollama_manager_module._OWNED_OLLAMA_PROCESSES.clear()
    ollama_manager_module._OLLAMA_PINNING_RESTARTED_HOSTS.clear()
    attempts = {"count": 0}
    captured: dict[str, object] = {}

    def _fetch_stub(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] <= 2:
            return None, None, RuntimeError("down")
        return {"models": [{"name": "qwen3-coder:30b"}]}, 200, None

    def _popen_stub(*args, **kwargs):
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
    assert st.session_state["builder_runtime_acceptance_probe"]["status"] == "local_model_visible"


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
            text='{"error":"model \'qwen3-coder:480b\' not found"}',
        ),
    )

    probe = ollama_manager_module.probe_model_runtime_acceptance(
        "qwen3-coder:480b",
        ollama_host="http://127.0.0.1:11434",
    )

    assert probe["host_reachable"] is True
    assert probe["accepted"] is False
    assert probe["status"] == "exact_name_rejected_by_host"
    assert probe["runtime_status_code"] == 404


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

    ok, msg, resolved_model, lazy_fallback_used = (
        builder_view_module._prepare_builder_llm_resilient(
            model="acereason-nemotron:14b-q5_k_m",
            ollama_host="http://127.0.0.1:22434",
            preload_model=True,
            keep_alive_minutes=20,
            auto_start_ollama=True,
            allow_lazy_fallback=True,
        )
    )

    assert ok is True
    assert resolved_model == "acereason-nemotron:14b-q5_k_m"
    assert lazy_fallback_used is True
    assert "Fallback automatique vers un démarrage lazy-load." in msg
    assert calls[0]["preload_model"] is True
    assert calls[1]["preload_model"] is False
    assert calls[1]["model"] == "acereason-nemotron:14b-q5_k_m"


def test_prepare_multi_llm_role_runtime_with_failover_uses_next_candidate(monkeypatch):
    attempts: list[str] = []

    assignment = SimpleNamespace(
        role="builder_llm",
        available=True,
        requested_model="kimi-k2",
        resolved_model="kimi-k2",
        alternatives=["qwen3-coder:480b"],
    )
    route = SimpleNamespace(ollama_host="http://127.0.0.1:11434", gpu_target="")

    class _Manager:
        def resolve_role_assignment(self, role):
            return assignment if role == "builder_llm" else None

        def resolve_role_route(self, role):
            return route

        def select_next_role_candidate(self, role, *, rejected_model="", reason=""):
            if role != "builder_llm" or rejected_model != "kimi-k2":
                return None
            assignment.requested_model = "qwen3-coder:480b"
            assignment.resolved_model = "qwen3-coder:480b"
            assignment.alternatives = []
            return "qwen3-coder:480b"

    def _prepare_stub(**kwargs):
        model_name = str(kwargs.get("model") or "")
        attempts.append(model_name)
        if model_name == "kimi-k2":
            return False, "rejected", "kimi-k2"
        return True, "ok", "qwen3-coder:480b"

    monkeypatch.setattr(builder_view_module, "_prepare_builder_llm", _prepare_stub)

    ok, msg, resolved_model = builder_view_module._prepare_multi_llm_role_runtime_with_failover(
        _Manager(),
        role="builder_llm",
        preload_model=False,
        keep_alive_minutes=20,
        auto_start_ollama=True,
    )

    assert ok is True
    assert resolved_model == "qwen3-coder:480b"
    assert attempts == ["kimi-k2", "qwen3-coder:480b"]


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
            ConnectionRefusedError("[WinError 10061] Connection refused")
        ),
    )
    monkeypatch.setattr(model_config_module.time, "sleep", lambda seconds: sleeps.append(seconds))
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
            AssertionError("Le warmup LLM ne doit pas démarrer si la sonde marché échoue")
        ),
    )

    builder_view_module.render_builder_view(
        state=state,
        df=None,
        status_container=nullcontext(),
    )

    assert events[0][0] == "start"
    assert any(
        name == "heartbeat" and payload.get("last_event") == "startup_probe"
        for name, payload in events
    )
    stop_payload = next(payload for name, payload in events if name == "stop")
    assert stop_payload["reason"] == "startup_market_probe_failed"
    assert st.session_state["is_running"] is False


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
    monkeypatch.setattr(builder_view_module.st, "info", lambda message, *args, **kwargs: info_messages.append(str(message)))
    monkeypatch.setattr(builder_view_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        builder_view_module,
        "_mark_builder_autonomous_runtime_started",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Le runtime autonome ne doit pas démarrer en mode idle")
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_find_first_valid_builder_market",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("La sonde marché ne doit pas tourner en mode idle")
        ),
    )
    monkeypatch.setattr(
        builder_view_module,
        "_prepare_builder_llm_resilient",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Le warmup LLM ne doit pas démarrer en mode idle")
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
        ([{"session_num": 1, "objective": "demo"}], {"soft_reset_count": 0})
    ]
    assert st.session_state["is_running"] is False


def test_cleanup_all_models_uses_ps_not_tags(monkeypatch):
    requested_urls: list[str] = []
    unloaded: list[str] = []

    def _fake_get(url, timeout=0):
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
        lambda: [],
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
            }
        },
    )
    monkeypatch.setattr(model_selector_module, "get_model_by_id", lambda model_name: {})
    monkeypatch.setattr(model_selector_module, "_get_total_vram_gb", lambda: 24.0)

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
            }
        },
    )
    monkeypatch.setattr(
        model_selector_module,
        "get_model_by_id",
        lambda model_name: {
            "name": "Nemotron Cascade 14B Claude Opus Distill",
            "aliases": [
                "nemotron-cascade-14b-thinking-claude-4.5-opus-distill.q8_0:latest"
            ],
        },
    )

    details = model_selector_module.get_model_details("nemotron-cascade-14b-local")

    assert details["display_name"] == "Nemotron Cascade 14B Claude Opus Distill"
    assert (
        "nemotron-cascade-14b-thinking-claude-4.5-opus-distill.q8_0:latest"
        in details["aliases"]
    )
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
                    }
                ]
            }

    def _fake_get(url, timeout=0):
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

    assert list(fig.data[0].labels) == ["Terminés", "Prunés", "Erreurs", "Restants"]
    assert list(fig.data[0].values) == [2, 2, 1, 5]


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
        "kimi-k2: L'hôte http://127.0.0.1:11434 est joignable, mais il rejette le nom exact kimi-k2."
    )

    origin = _classify_autonomous_failure_origin(error)

    assert origin == "llm_runtime_model_name_mismatch"


def test_get_autonomous_recap_status_badge_keeps_failed_status_even_with_positive_best_return():
    badge = _get_autonomous_recap_status_badge(
        {"status": "failed", "best_return": 46.38}
    )

    assert badge == {"icon": "✖", "label": "echec", "tone": "crash"}


def test_get_autonomous_recap_status_badge_keeps_max_iterations_status_even_with_positive_best_return():
    badge = _get_autonomous_recap_status_badge(
        {"status": "max_iterations", "best_return": 12.5}
    )

    assert badge == {
        "icon": "⏱️",
        "label": "max_iterations",
        "tone": "neutral",
    }


def test_get_autonomous_recap_status_badge_marks_negative_return_with_red_minus():
    badge = _get_autonomous_recap_status_badge(
        {"status": "failed", "best_return": -9.55}
    )

    assert badge == {"icon": "−", "label": "negatif", "tone": "negative"}


def test_get_autonomous_recap_status_badge_marks_zero_failed_run_as_failure():
    badge = _get_autonomous_recap_status_badge(
        {"status": "failed", "best_return": 0.0}
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
                    }
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
                    }
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
                }
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
                }
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
                    }
                ],
            }
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
            }
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


def test_finalize_multi_llm_session_review_persists_continuity_context(tmp_path):
    session_dir = tmp_path / "builder_session_multi"
    session_dir.mkdir(parents=True)
    (session_dir / "session_summary.json").write_text(
        json.dumps({"session_id": session_dir.name, "status": "success"}),
        encoding="utf-8",
    )

    class _RoleOutput:
        def __init__(self, payload):
            self._payload = payload

        def to_dict(self):
            return dict(self._payload)

    class _Manager:
        def review_builder_session(self, **kwargs):
            return {
                "router_decision": {
                    "action": "iterate",
                    "reason": "tighten exits",
                    "confidence": 0.82,
                },
                "role_outputs": {
                    "critic_llm": _RoleOutput(
                        {
                            "role": "critic_llm",
                            "model": "deepseek-r1:14b",
                            "available": True,
                            "error": "",
                            "content": "Focus on exits and reduce lag.",
                            "metadata": {"score": 0.8},
                        }
                    )
                },
            }

        def consume_shared_memory(self):
            return {
                "continuity_context": {
                    "recent_sessions": [{"session_num": 7, "symbol": "BTCUSDT"}],
                    "best_recent_session": {"session_num": 7, "symbol": "BTCUSDT"},
                    "carry_over_focus": ["tighten exits"],
                    "recurring_risks": ["drawdown spike"],
                },
                "router_context": {"action": "iterate", "reason": "tighten exits"},
            }

    session = SimpleNamespace(session_dir=session_dir)

    payload = builder_view_module._finalize_multi_llm_session_review(
        objective="Builder multi role",
        session=session,
        target_sharpe=1.2,
        multi_llm_manager=_Manager(),
        persist_summary=True,
    )

    saved = json.loads((session_dir / "session_summary.json").read_text(encoding="utf-8"))

    assert payload["continuity_context"]["carry_over_focus"] == ["tighten exits"]
    assert session.multi_llm_router_decision["action"] == "iterate"
    assert session.multi_llm_shared_memory["router_context"]["action"] == "iterate"
    assert saved["multi_llm_router_decision"]["confidence"] == 0.82
    assert saved["continuity_context"]["recurring_risks"] == ["drawdown spike"]
    assert saved["multi_llm_role_outputs"]["critic_llm"]["content_excerpt"].startswith(
        "Focus on exits"
    )


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
                    }
                ],
            }
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
        }
    ]

    builder_view_module._render_autonomous_recap(history, {})

    assert any("+0.00%" in html or "0.00%" in html for html in rendered_html)
    assert any("22:52:41" in html for html in rendered_html)
    assert download_payloads
    assert session_dir.name in str(download_payloads[0])


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
                    }
                ],
            }
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
        }
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
                    }
                ],
            }
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
        }
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
    assert any(
        "1000 sessions affichées sur 1567 exécutées" in caption
        for caption in captured["captions"]
    )


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
        }
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
        }
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


def test_render_autonomous_recap_prefers_final_metrics_and_session_status_over_best_return(monkeypatch):
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
        }
    ]

    builder_view_module._render_autonomous_recap(history, {})

    joined_html = "\n".join(rendered_html)
    assert "<th>Date/heure</th>" in joined_html
    assert "<th>Sharpe fin.</th>" in joined_html
    assert "<th>Return fin.</th>" in joined_html
    assert "22/03/2026 17:56:58" in joined_html
    assert "-2808.48%" in joined_html
    assert "-100.00%" in joined_html
    assert ">8214</td>" in joined_html
    assert "− negatif" in joined_html


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
        }
    ]

    builder_view_module._render_autonomous_recap(history, {})

    joined_html = "\n".join(rendered_html)
    assert "<th>Gain total EUR</th>" in joined_html
    assert "<th>Jours testes</th>" in joined_html
    assert "<th>EUR/j</th>" in joined_html
    assert "+15 281.00" in joined_html
    assert ">12.0</td>" in joined_html
    assert "+1 273.42" in joined_html


def test_trim_autonomous_history_keeps_last_1000_runs():
    trimmed = builder_view_module._trim_autonomous_history(
        [{"session_num": session_num} for session_num in range(1, 1002)]
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
        }
    )

    assert badge["kind"] == "runtime_fix_fallback"
    assert "fallback" in badge["badge"].lower()


def test_get_builder_code_provenance_badge_detects_retry_code_origin():
    badge = _get_builder_code_provenance_badge(
        {
            "code": {
                "source": "retry_code",
                "realign_attempts": 1,
            }
        }
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
            }
        ),
        diagnostic_category="",
        change_type="",
        hypothesis="",
        analysis="",
        code="",
    )

    builder_view_module.render_iteration_card(iteration)

    assert any(
        any("LLM corrigé" in label for label in labels)
        for labels in captured_badges
    )


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
            }
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

    assert any(
        any("Runtime-fix" in label for label in labels)
        for labels in captured_badges
    )


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
            }
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
            {"mode": state.optimization_mode, "autonomous": state.builder_autonomous}
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
            {"mode": state.optimization_mode, "autonomous": state.builder_autonomous}
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


def test_restore_builder_autonomous_ui_state_from_runtime_rehydrates_builder_mode(
    monkeypatch,
):
    st.session_state.clear()

    monkeypatch.setattr(
        builder_view_module,
        "_load_autonomous_runtime_state",
        lambda: {
            "active": True,
            "manual_stop": False,
            "resume_ui_state": {
                "builder_execution_mode": BUILDER_EXECUTION_MODE_DUAL_LANE,
                "builder_model_single_llm": "qwen3:30b",
                "builder_ollama_host": "http://127.0.0.1:22434",
                "builder_auto_pause": 17,
                "builder_auto_use_llm": True,
                "builder_auto_market_pick": True,
                "builder_universe_mode": "exploratory",
                "builder_preload_model": False,
                "builder_keep_alive_minutes": 35,
                "builder_unload_after_run": True,
                "builder_auto_start_ollama": False,
                "builder_multi_llm_enabled": True,
                "builder_multi_llm_profile": "24GB_light_test",
                "builder_multi_llm_role_overrides": {
                    "idea_llm": "qwen3:30b",
                    "builder_llm": "qwen3:30b",
                    "critic_llm": "deepseek-r1:14b",
                    "risk_llm": "deepseek-r1:14b",
                },
                "builder_dual_lane_primary_model": "qwen3:30b",
                "builder_dual_lane_critic_model": "deepseek-r1:14b",
            },
        },
    )

    should_resume, payload = builder_view_module.restore_builder_autonomous_ui_state_from_runtime()

    assert should_resume is True
    assert payload["active"] is True
    assert st.session_state["optimization_mode"] == "🏗️ Strategy Builder"
    assert st.session_state["exec_mode_selector"] == "🏗️ Strategy Builder"
    assert st.session_state["builder_autonomous"] is True
    assert st.session_state["_builder_autonomous_toggle_sync"] is True
    assert (
        st.session_state["builder_execution_mode"]
        == BUILDER_EXECUTION_MODE_DUAL_LANE
    )
    assert (
        st.session_state["builder_execution_mode_select"]
        == BUILDER_EXECUTION_MODE_DUAL_LANE
    )
    assert st.session_state["builder_ollama_host"] == "http://127.0.0.1:22434"
    assert st.session_state["builder_auto_pause_slider"] == 17
    assert st.session_state["builder_universe_mode"] == "exploratory"
    assert st.session_state["builder_multi_llm_profile_select"] == "24GB_light_test"
    assert (
        st.session_state["builder_dual_lane_primary_model_select"] == "qwen3:30b"
    )
    assert (
        st.session_state["builder_dual_lane_critic_model_select"]
        == "deepseek-r1:14b"
    )


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
        }
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
    captured: dict[str, object] = {}

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
            False,
            f"Aucun segment continu exploitable détecté: segment max=160 barres (< {int(builder_view_module.MIN_BUILDER_BARS)}) sur {symbol}/{timeframe}.",
        )
        if len(data) == len(gapped_df)
        else (True, ""),
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
            False,
            f"Dataset trop peu tradable pour Builder: 50.0% de barres non-tradables (> 25%) sur {symbol}/{timeframe}.",
        )
        if len(data) == len(low_quality_df)
        else (True, ""),
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
    assert get_partial_result_notice(result) == (
        "Résultat partiel issu d'une optimisation interrompue (3/10 tests)."
    )


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
    assert st.session_state["saved_runs_status"] == (
        "Auto-save skipped: interrupted partial result."
    )


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
            }
        ]
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
    assert "run_123" in msg


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


def test_app_builder_mode_is_directly_rendered_from_mode_selection():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "🏗️ Strategy Builder"

    at.run(timeout=60)

    button_labels = [button.label for button in at.button]
    assert all(not label.startswith("→ Activer") for label in button_labels)
    assert any(
        text_area.label == "🎯 Objectif de la stratégie"
        for text_area in at.text_area
    )
    assert all(radio.label != "Mode d'exécution" for radio in at.radio)
    assert at.session_state["optimization_mode"] == "🏗️ Strategy Builder"


def test_app_builder_expert_mode_shows_only_expert_controls():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "🏗️ Strategy Builder"
    at.session_state["builder_autonomous"] = False
    at.session_state["builder_execution_mode"] = BUILDER_EXECUTION_MODE_EXPERT

    at.run(timeout=60)

    assert at.exception == []
    assert any(
        radio.label == "Architecture Builder"
        and radio.value == BUILDER_EXECUTION_MODE_EXPERT
        for radio in at.radio
    )
    if exec_tabs_module._MULTI_LLM_AVAILABLE:
        assert any(
            selectbox.label == "Profil multi-LLM"
            for selectbox in at.selectbox
        )
        assert any(
            multiselect.label == "builder_llm"
            for multiselect in at.multiselect
        )
    assert all(selectbox.label != "Modele LLM" for selectbox in at.selectbox)
    assert all(
        selectbox.label != "Modele lane principale"
        for selectbox in at.selectbox
    )


def test_app_builder_expert_mode_exposes_profile_save_toggle():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "🏗️ Strategy Builder"
    at.session_state["builder_execution_mode"] = BUILDER_EXECUTION_MODE_EXPERT

    at.run(timeout=60)

    assert at.exception == []
    if exec_tabs_module._MULTI_LLM_AVAILABLE:
        assert any(
            toggle.label == "💾 Enregistrer cette présélection"
            for toggle in at.toggle
        )


def test_app_builder_expert_mode_applies_deferred_profile_sync_before_widget():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "🏗️ Strategy Builder"
    at.session_state["builder_execution_mode"] = BUILDER_EXECUTION_MODE_EXPERT
    at.session_state["builder_multi_llm_profile"] = "24GB_balanced"
    at.session_state["_builder_multi_llm_profile_sync"] = "24GB_light_test"
    at.session_state["_builder_multi_llm_profile_saved_notice"] = (
        "Présélection `24GB_light_test` ajoutée aux profils multi-LLM."
    )

    at.run(timeout=60)

    assert at.exception == []
    assert at.session_state["builder_multi_llm_profile"] == "24GB_light_test"
    assert at.session_state["builder_multi_llm_profile_select"] == "24GB_light_test"
    assert "_builder_multi_llm_profile_sync" not in at.session_state
    assert "_builder_multi_llm_profile_saved_notice" not in at.session_state


def test_app_builder_expert_mode_loads_saved_custom_profile_into_role_multiselects():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "🏗️ Strategy Builder"
    at.session_state["builder_execution_mode"] = BUILDER_EXECUTION_MODE_EXPERT

    at.run(timeout=60)

    profile_select = next(
        selectbox for selectbox in at.selectbox if selectbox.label == "Profil multi-LLM"
    )
    profile_select.set_value("24GB_custom")
    at.run(timeout=60)

    assert at.exception == []
    assert at.session_state["builder_multi_llm_profile_select"] == "24GB_custom"
    assert next(m for m in at.multiselect if m.label == "idea_llm").value == [
        "alia-40b-local",
        "llama3.3:70b-instruct-q4_K_M",
        "qwen3-48b-savant",
        "gpt-oss:20b",
        "nemotron-3-nano:30b",
        "glm-4.7-flash-23b-local",
    ]
    assert next(m for m in at.multiselect if m.label == "builder_llm").value == [
        "gpt-oss:20b",
        "nemotron-orchestrator-8b",
        "qwen3-vl:32b",
    ]


def test_app_builder_expert_mode_manual_role_multiselect_persists_selection():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "🏗️ Strategy Builder"
    at.session_state["builder_execution_mode"] = BUILDER_EXECUTION_MODE_EXPERT

    at.run(timeout=60)

    at.session_state["builder_multi_llm_role_override_select_builder_llm"] = [
        "gpt-oss:20b",
        "devstral-small-2:24b",
    ]
    at.run(timeout=60)

    assert at.exception == []
    assert any(multiselect.label == "builder_llm" for multiselect in at.multiselect)


def test_app_builder_mono_mode_shows_only_single_model_selector():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "🏗️ Strategy Builder"
    at.session_state["builder_execution_mode"] = BUILDER_EXECUTION_MODE_MONO

    at.run(timeout=60)

    assert at.exception == []
    assert any(selectbox.label == "Modele LLM" for selectbox in at.selectbox)
    assert all(
        expander.label != "🧩 Configuration Expert Multi-Role"
        for expander in at.expander
    )
    assert all(
        selectbox.label != "Modele lane principale"
        for selectbox in at.selectbox
    )


def test_app_builder_multi_llm_purges_legacy_builder_model_state():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "🏗️ Strategy Builder"
    at.session_state["builder_execution_mode"] = BUILDER_EXECUTION_MODE_MONO
    at.session_state["builder_model"] = "alia-40b-local:latest"

    at.run(timeout=60)

    assert at.exception == []
    assert "builder_model" not in at.session_state
    assert str(at.session_state["builder_model_single_llm"]).startswith(
        "alia-40b-local"
    )


def test_app_builder_dual_lane_shows_only_lane_controls():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "🏗️ Strategy Builder"
    at.session_state["builder_execution_mode"] = BUILDER_EXECUTION_MODE_DUAL_LANE

    at.run(timeout=60)

    assert at.exception == []
    assert any(
        selectbox.label == "Modele lane principale"
        for selectbox in at.selectbox
    )
    assert any(
        selectbox.label == "Modele lane critique"
        for selectbox in at.selectbox
    )
    assert all(selectbox.label != "Modele LLM" for selectbox in at.selectbox)
    assert all(
        expander.label != "🧩 Configuration Expert Multi-Role"
        for expander in at.expander
    )
    assert (
        at.session_state["builder_llm_routing_mode"]
        == exec_tabs_module.LLM_ROUTING_MODE_COOPERATIVE
    )
    assert at.session_state["builder_multi_llm_enabled"] is True


def test_app_builder_mode_switch_hides_previous_mode_controls():
    at = AppTest.from_file("ui/app.py")
    at.session_state["optimization_mode"] = "🏗️ Strategy Builder"
    at.session_state["builder_execution_mode"] = BUILDER_EXECUTION_MODE_MONO

    at.run(timeout=60)

    builder_mode_radio = next(
        radio for radio in at.radio if radio.label == "Architecture Builder"
    )
    builder_mode_radio.set_value(BUILDER_EXECUTION_MODE_DUAL_LANE)
    at.run(timeout=60)

    assert at.exception == []
    assert any(
        selectbox.label == "Modele lane principale"
        for selectbox in at.selectbox
    )
    assert all(selectbox.label != "Modele LLM" for selectbox in at.selectbox)


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
    assert (
        sidebar_module.request_execution_mode_change("Backtest Simple")
        is False
    )


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

    assert (
        builder_topology.endpoints["control"].ollama_host
        == "http://127.0.0.1:22434"
    )
    assert (
        exec_topology.endpoints["control"].ollama_host
        == "http://127.0.0.1:44434"
    )
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

    assert (
        topology.endpoints["control"].ollama_host
        == "http://127.0.0.1:55434"
    )
    assert topology.endpoints["builder_primary"].gpu_target == "GPU-1"
    assert topology.endpoints["control"].gpu_target == "GPU-0"


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
                }
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
    assert st.session_state["stop_requested"] is True
    assert st.session_state["run_backtest_requested"] is False
    assert st.session_state["load_ohlcv_requested"] is False
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
        lambda ollama_host=None: unload_calls.append(str(ollama_host or "")) or (
            1 if str(ollama_host or "").endswith("11434") else 0
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
        lambda ollama_host=None, force=True, owned_only=False, timeout_s=3.0: stop_calls.append(
            (str(ollama_host or ""), bool(owned_only))
        ) or 1,
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
        }
    )

    assert resolved == {
        "builder_auto_start_ollama": False,
        "builder_preload_model": False,
        "builder_keep_alive_minutes": 60,
        "builder_unload_after_run": True,
    }


def test_resolve_builder_execution_preferences_prefers_live_mode_widget():
    resolved = resolve_builder_execution_preferences(
        {
            "builder_execution_mode": BUILDER_EXECUTION_MODE_MONO,
            "builder_execution_mode_select": BUILDER_EXECUTION_MODE_DUAL_LANE,
        }
    )

    assert resolved == {
        "builder_execution_mode": BUILDER_EXECUTION_MODE_DUAL_LANE,
        "builder_multi_llm_enabled": True,
        "builder_llm_routing_mode": "cooperative_multi_gpu",
    }


def test_resolve_builder_execution_preferences_migrates_legacy_multi_llm_state():
    resolved = resolve_builder_execution_preferences(
        {
            "builder_multi_llm_enabled_toggle": True,
            "builder_llm_routing_mode": "single_endpoint",
        }
    )

    assert resolved == {
        "builder_execution_mode": BUILDER_EXECUTION_MODE_EXPERT,
        "builder_multi_llm_enabled": True,
        "builder_llm_routing_mode": "single_endpoint",
    }


def test_resolve_builder_dual_lane_preferences_prefers_live_widget_values():
    resolved = resolve_builder_dual_lane_preferences(
        {
            "builder_model_single_llm": "qwen3:30b",
            "builder_multi_llm_role_overrides": {
                "builder_llm": "gemma4:26b",
                "critic_llm": "deepseek-r1:14b",
            },
            "builder_dual_lane_primary_model": "mistral:7b-instruct",
            "builder_dual_lane_critic_model": "llama3.1:8b",
            "builder_dual_lane_primary_model_select": "qwen2.5:14b",
            "builder_dual_lane_critic_model_select": "mistral:22b",
        }
    )

    assert resolved == {
        "builder_dual_lane_primary_model": "qwen2.5:14b",
        "builder_dual_lane_critic_model": "mistral:22b",
    }


def test_resolve_builder_multi_llm_preferences_prefers_live_widget_values():
    resolved = resolve_builder_multi_llm_preferences(
        {
            "builder_execution_mode": BUILDER_EXECUTION_MODE_EXPERT,
            "builder_multi_llm_enabled": False,
            "builder_multi_llm_profile": "24GB_balanced",
            "builder_multi_llm_role_overrides": {
                "builder_llm": ["qwen3-coder:30b", "gemma4:26b"],
                "critic_llm": "deepseek-r1-distill:14b",
            },
            "builder_multi_llm_enabled_toggle": True,
            "builder_multi_llm_profile_select": "24GB_light_test",
            "builder_multi_llm_role_override_select_builder_llm": [
                "gemma4:26b",
                "qwen3-coder:30b",
            ],
            "builder_multi_llm_role_override_select_critic_llm": [],
            "builder_multi_llm_role_override_select_risk_llm": [
                "mistral:7b-instruct",
                "deepseek-r1:14b",
            ],
        }
    )

    assert resolved == {
        "builder_execution_mode": BUILDER_EXECUTION_MODE_EXPERT,
        "builder_multi_llm_enabled": True,
        "builder_multi_llm_profile": "24GB_light_test",
        "builder_multi_llm_role_overrides": {
            "builder_llm": ["gemma4:26b", "qwen3-coder:30b"],
            "risk_llm": ["mistral:7b-instruct", "deepseek-r1:14b"],
        },
    }


def test_resolve_builder_multi_llm_preferences_maps_dual_lane_to_four_roles():
    resolved = resolve_builder_multi_llm_preferences(
        {
            "builder_execution_mode": BUILDER_EXECUTION_MODE_DUAL_LANE,
            "builder_dual_lane_primary_model_select": "qwen3:30b",
            "builder_dual_lane_critic_model_select": "deepseek-r1:14b",
        }
    )

    assert resolved == {
        "builder_execution_mode": BUILDER_EXECUTION_MODE_DUAL_LANE,
        "builder_multi_llm_enabled": True,
        "builder_multi_llm_profile": "24GB_balanced",
        "builder_multi_llm_role_overrides": {
            "idea_llm": ["qwen3:30b"],
            "builder_llm": ["qwen3:30b"],
            "critic_llm": ["deepseek-r1:14b"],
            "risk_llm": ["deepseek-r1:14b"],
        },
    }


def test_resolve_builder_multi_llm_preferences_uses_profile_role_pools_after_profile_switch():
    resolved = resolve_builder_multi_llm_preferences(
        {
            "builder_execution_mode": BUILDER_EXECUTION_MODE_EXPERT,
            "builder_multi_llm_profile_select": "24GB_diverse_roles",
            "_builder_multi_llm_applied_profile": "24GB_balanced",
            "builder_multi_llm_role_overrides": {
                "builder_llm": ["gemma4:26b"],
            },
            "builder_multi_llm_role_override_select_builder_llm": [
                "gemma4:26b",
            ],
        }
    )

    assert resolved["builder_multi_llm_enabled"] is True
    assert resolved["builder_multi_llm_profile"] == "24GB_diverse_roles"
    assert resolved["builder_multi_llm_role_overrides"]["idea_llm"][:3] == [
        "qwen3.5:35b",
        "mistral:22b",
        "lfm2:24b",
    ]
    assert resolved["builder_multi_llm_role_overrides"]["builder_llm"] == [
        "gpt-oss:20b",
        "devstral-small-2:24b",
        "qwen3-coder:30b",
        "qwen3-30b-a3b:q4_k_m",
    ]


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
        ollama_host="http://127.0.0.1:65535"
    )

    assert "qwen3-coder:30b" in models
    assert "devstral-small-2:24b" in models
    assert "qwen3-coder:480b" in models


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
        lambda: [],
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
            )
        ],
        live_ollama_reachable=True,
    )

    models = exec_tabs_module._available_runtime_role_models(inventory, "builder_llm")

    assert "qwen3-coder:30b" in models
    assert "qwen3-coder:480b" in models
    assert "devstral-2:123b" in models


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
        }
    )

    assert resolved["builder_flow_analysis_enabled"] is True
    assert resolved["builder_flow_analysis_ablation"]["code_repair"] is True
    assert resolved["builder_flow_analysis_ablation"]["precheck"] is False
    assert resolved["builder_flow_analysis_ablation"]["runtime_fix"] is False


def test_sync_builder_multi_llm_profile_role_pools_hydrates_and_clears_session_state():
    st.session_state.clear()

    seeded = exec_tabs_module._sync_builder_multi_llm_profile_role_pools(
        "24GB_diverse_roles"
    )

    assert seeded["builder_llm"] == [
        "gpt-oss:20b",
        "devstral-small-2:24b",
        "qwen3-coder:30b",
        "qwen3-30b-a3b:q4_k_m",
    ]
    assert st.session_state["builder_multi_llm_role_overrides"]["critic_llm"][0] == (
        "qwen3.5:35b"
    )
    assert st.session_state[
        "builder_multi_llm_role_override_select_risk_llm"
    ] == [
        "fin-llama-33b:33b",
        "qwen3.5:35b",
        "deepseek-r1:32b",
        "deepseek-r1-distill:14b",
        "qwq:32b",
    ]

    cleared = exec_tabs_module._sync_builder_multi_llm_profile_role_pools(
        "24GB_balanced"
    )

    assert cleared == {}
    assert st.session_state["builder_multi_llm_role_overrides"] == {}
    assert st.session_state["builder_multi_llm_role_override_select_builder_llm"] == []


def test_sync_builder_multi_llm_profile_role_pools_refreshes_same_profile_when_definition_changes(monkeypatch):
    st.session_state.clear()
    st.session_state["_builder_multi_llm_applied_profile"] = "cloud_power_roles"
    st.session_state["_builder_multi_llm_applied_profile_signature"] = "old-signature"
    st.session_state["builder_multi_llm_role_overrides"] = {
        "idea_llm": ["glm-4.7"],
        "builder_llm": ["glm-4.7"],
    }
    st.session_state["builder_multi_llm_role_override_select_idea_llm"] = ["glm-4.7"]
    st.session_state["builder_multi_llm_role_override_select_builder_llm"] = ["glm-4.7"]

    monkeypatch.setattr(
        exec_tabs_module,
        "get_profile_role_pools",
        lambda name: {
            "idea_llm": ["deepseek-v3.1", "gpt-oss:120b"],
            "builder_llm": ["gpt-oss:120b", "deepseek-v3.1"],
        },
    )
    monkeypatch.setattr(
        exec_tabs_module,
        "get_profile_definition",
        lambda name: {
            "name": name,
            "updated_at": "2026-03-28T21:45:00Z",
            "roles": {},
        },
    )

    refreshed = exec_tabs_module._sync_builder_multi_llm_profile_role_pools(
        "cloud_power_roles"
    )

    assert refreshed["idea_llm"] == ["deepseek-v3.1", "gpt-oss:120b"]
    assert refreshed["builder_llm"] == ["gpt-oss:120b", "deepseek-v3.1"]
    assert st.session_state["builder_multi_llm_role_override_select_idea_llm"] == [
        "deepseek-v3.1",
        "gpt-oss:120b",
    ]


def test_pick_builder_session_role_overrides_selects_one_model_per_role(monkeypatch):
    picks = iter(
        [
            "gemma4:26b",
            "qwen3-coder:30b",
            "deepseek-r1:14b",
            "mistral:7b-instruct",
        ]
    )
    monkeypatch.setattr(builder_view_module.random, "choice", lambda pool: next(picks))

    selected = builder_view_module._pick_builder_session_role_overrides(
        {
            "idea_llm": ["gemma4:26b", "qwen2.5:14b"],
            "builder_llm": ["qwen3-coder:30b", "qwen2.5-coder:14b"],
            "critic_llm": ["deepseek-r1:14b"],
            "risk_llm": ["mistral:7b-instruct", "llama3.1:8b"],
        }
    )

    assert selected == {
        "idea_llm": "gemma4:26b",
        "builder_llm": "qwen3-coder:30b",
        "critic_llm": "deepseek-r1:14b",
        "risk_llm": "mistral:7b-instruct",
    }


def test_pick_builder_session_role_overrides_prefers_runtime_visible_cloud_candidates(monkeypatch):
    monkeypatch.setattr(builder_view_module.random, "choice", lambda pool: pool[0])

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

    assert selected["builder_llm"] == "gpt-oss:120b"
    assert selected["critic_llm"] == "deepseek-v3.1"
