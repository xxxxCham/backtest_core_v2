from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd

import ui.builder_view as builder_view_module
import agents.ollama_manager as ollama_manager_module
import backtest.worker as worker_module
import streamlit as st
from backtest.engine import BacktestEngine
from backtest.worker import init_worker_with_dataframe, run_backtest_worker
import ui.helpers as helpers_module
from ui.exec_tabs import _prime_multiselect_state
from ui.helpers import (
    compute_period_days,
    format_pnl_with_daily,
    get_partial_result_notice,
    mark_result_as_partial,
    safe_run_backtest,
    _build_saved_run_label,
)
from ui.main import (
    _build_multi_sweep_grid_entry,
    _build_param_combo_iter,
    _describe_grid_completion,
    _run_grid_numba_summary,
    _run_grid_sequential,
    render_main,
)
from ui.builder_view import (
    _choose_autonomous_objective_mode,
    _classify_autonomous_failure_origin,
    _find_first_valid_builder_market,
    _has_builder_market_df,
    _pick_market_for_objective,
    _plan_autonomous_recovery,
    _resolve_requested_model,
    _sanitize_builder_stream_text,
)
import ui.components.model_selector as model_selector_module
import ui.main as main_module
from ui.results_hub import (
    _add_pnl_per_day,
    _build_catalog_replay_request,
    _build_run_row_replay_request,
    _normalize_backtest_overview_df,
)
from ui.sidebar import _apply_catalog_replay_request_to_state, _apply_config_guard, _resolve_default_cpu_workers
from ui.state import SidebarState


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
        "initial_capital": 10_000.0,
        "leverage": 1.0,
        "leverage_enabled": False,
        "disabled_params": [],
        "use_walk_forward": False,
        "wfa_n_folds": 3,
        "wfa_train_ratio": 0.7,
        "wfa_expanding": False,
        "builder_objective": "",
        "builder_model": "deepseek-r1:32b",
        "builder_max_iterations": 10,
        "builder_target_sharpe": 1.0,
        "builder_capital": 10_000.0,
        "builder_ollama_host": "http://127.0.0.1:11434",
        "builder_preload_model": True,
        "builder_keep_alive_minutes": 20,
        "builder_unload_after_run": False,
        "builder_auto_start_ollama": True,
        "builder_auto_market_pick": True,
        "builder_autonomous": False,
        "builder_auto_pause": 10,
        "builder_auto_use_llm": True,
        "builder_multi_llm_enabled": False,
        "builder_multi_llm_profile": "24GB_balanced",
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
                "metrics_sharpe_ratio": "1.4",
                "metrics_max_drawdown_pct": "-9.5",
            }
        ]
    )

    normalized = _normalize_backtest_overview_df(df)

    assert normalized.loc[0, "total_pnl"] == 123.5
    assert normalized.loc[0, "total_return_pct"] == 6.25
    assert normalized.loc[0, "sharpe_ratio"] == 1.4
    assert normalized.loc[0, "max_drawdown_pct"] == -9.5


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
    monkeypatch.setattr(
        ollama_manager_module,
        "_fetch_tags_payload",
        lambda *args, **kwargs: ({"models": []}, 200, None),
    )

    ok, msg = ollama_manager_module.ensure_ollama_running("http://127.0.0.1:11434")

    assert ok is True
    assert "aucun modele detecte" in msg


def test_prepare_builder_llm_passes_normalized_host_to_ollama_manager(monkeypatch):
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


def test_get_available_models_for_ui_prefers_installed_models_only(monkeypatch):
    monkeypatch.setattr(
        model_selector_module,
        "list_ollama_models",
        lambda ollama_host=None: ["qwen2.5:14b", "mistral:7b-instruct"],
    )
    monkeypatch.setattr(
        model_selector_module,
        "_get_library_models",
        lambda: ["deepseek-r1:32b", "qwen2.5:14b"],
    )

    models = model_selector_module.get_available_models_for_ui(
        preferred_order=["deepseek-r1:32b", "qwen2.5:14b"],
        ollama_host="http://my-host:11434",
        include_library_models=False,
    )

    assert models == ["qwen2.5:14b", "mistral:7b-instruct"]


def test_get_available_models_for_ui_can_merge_library_models_when_enabled(monkeypatch):
    monkeypatch.setattr(
        model_selector_module,
        "list_ollama_models",
        lambda ollama_host=None: ["deepseek-r1:32b"],
    )
    monkeypatch.setattr(
        model_selector_module,
        "_get_library_models",
        lambda: ["deepseek-r1:32b", "alia-40b-local:latest", "qwen2.5:32b"],
    )

    models = model_selector_module.get_available_models_for_ui(
        ollama_host="http://127.0.0.1:11434",
        include_library_models=True,
    )

    assert "deepseek-r1:32b" in models
    assert "alia-40b-local:latest" in models
    assert "qwen2.5:32b" in models


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
        lambda label, value="", key=None, help=None: captured.setdefault("value", value) or value,
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
        lambda label, options, key=None, help=None, format_func=None: st.session_state[key],
    )

    selected = model_selector_module.render_model_selector(
        key="builder_model_select",
        current_value="alia-40b-local:latest",
        show_details=False,
    )

    assert st.session_state["builder_model_select"] == "alia-40b-local"
    assert selected == "alia-40b-local"


def test_resolve_selector_current_value_prefers_widget_state_over_stale_explicit_value():
    st.session_state.clear()
    st.session_state["builder_model_select"] = "qwen2.5:32b"

    selected = model_selector_module._resolve_selector_current_value(
        "builder_model_select",
        explicit_current_value="deepseek-r1:32b",
    )

    assert selected == "qwen2.5:32b"


def test_choose_autonomous_objective_mode_escalates_to_parametric_when_recent_runs_are_robust():
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

    assert policy["mode"] == "parametric"
    assert policy["reason"] == "healthy_complexity_escalation"


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
    assert plan["force_source_mode"] == "catalog"
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
