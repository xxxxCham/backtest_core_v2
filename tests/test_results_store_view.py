from __future__ import annotations

import csv
import json
import logging
import runpy
import sys
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest

import ui.results_store_view as results_store_view_module
from ui.results_store_view import (
    collect_builder_catalog_reconciliation,
    collect_builder_iterations,
    collect_builder_linked_runs,
    collect_builder_sessions,
    collect_store_inventory,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_fake_streamlit(call_log: list[tuple[str, tuple[object, ...], dict[str, object]]]) -> ModuleType:
    fake_streamlit = ModuleType("streamlit")
    fake_streamlit.sidebar = SimpleNamespace(
        markdown=lambda *args, **kwargs: call_log.append(("sidebar.markdown", args, kwargs)),
    )
    fake_streamlit.set_page_config = lambda *args, **kwargs: call_log.append(
        ("set_page_config", args, kwargs),
    )
    fake_streamlit.title = lambda *args, **kwargs: call_log.append(("title", args, kwargs))
    fake_streamlit.caption = lambda *args, **kwargs: call_log.append(("caption", args, kwargs))
    fake_streamlit.warning = lambda *args, **kwargs: call_log.append(("warning", args, kwargs))
    fake_streamlit.markdown = lambda *args, **kwargs: call_log.append(("markdown", args, kwargs))
    return fake_streamlit


def _run_streamlit_page_script_once(
    monkeypatch: pytest.MonkeyPatch,
    *,
    relative_page_path: str,
    render_module_name: str,
    render_function_name: str,
) -> tuple[
    list[tuple[str, tuple[object, ...], dict[str, object]]],
    list[str],
    list[str],
]:
    streamlit_calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
    render_calls: list[str] = []
    observability_calls: list[str] = []

    fake_streamlit = _build_fake_streamlit(streamlit_calls)
    fake_render_module = ModuleType(render_module_name)
    setattr(fake_render_module, render_function_name, lambda: render_calls.append(render_function_name))
    fake_observability_module = ModuleType("utils.observability")
    setattr(fake_observability_module, "init_logging", lambda: observability_calls.append("init_logging"))

    import ui
    import utils

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setitem(sys.modules, render_module_name, fake_render_module)
    monkeypatch.setitem(sys.modules, "utils.observability", fake_observability_module)
    monkeypatch.setattr(ui, render_module_name.rsplit(".", 1)[-1], fake_render_module, raising=False)
    monkeypatch.setattr(utils, "observability", fake_observability_module, raising=False)

    runpy.run_path(str(REPO_ROOT / relative_page_path), run_name="__main__")
    return streamlit_calls, render_calls, observability_calls


def test_app_css_uses_full_width_layout_and_keeps_sidebar_controls_interactive() -> None:
    content = (REPO_ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    sidebar_content = (REPO_ROOT / "ui" / "sidebar.py").read_text(encoding="utf-8")

    assert "max-width: 1520px;" not in content
    assert "max-width: none;" in content
    assert "transform: translateX(0) !important;" not in content
    assert "pointer-events: none !important;" not in content
    assert '[data-testid="stToolbar"],' not in content
    assert '[data-testid="stToolbar"] {' in content
    assert 'button[kind="header"]' in content
    assert '[data-testid="stExpandSidebarButton"]' in content
    assert '[data-testid="stSidebar"][aria-expanded="true"]' in sidebar_content
    assert '[data-testid="stSidebar"] > div:first-child' not in sidebar_content


@pytest.mark.parametrize(
    "relative_page_path",
    [
        "ui/pages/results_store_page.py",
        "ui/pages/model_stats_page.py",
        "ui/pages/range_editor_page.py",
    ],
)
def test_page_navigation_css_does_not_force_sidebar_open(relative_page_path: str) -> None:
    content = (REPO_ROOT / relative_page_path).read_text(encoding="utf-8")

    assert "transform: translateX(0) !important;" not in content
    assert "pointer-events: none !important;" not in content
    assert '[data-testid="stToolbar"],' not in content
    assert '[data-testid="stToolbar"] {' in content
    assert 'button[kind="header"]' in content
    assert '[data-testid="stExpandSidebarButton"]' in content


def test_results_hub_is_only_exposed_via_dedicated_results_store_page() -> None:
    main_results_view = (REPO_ROOT / "ui" / "results.py").read_text(encoding="utf-8")
    dedicated_results_page = (REPO_ROOT / "ui" / "results_store_view.py").read_text(
        encoding="utf-8",
    )

    assert "Hub résultats, sauvegardes et catalogue" not in main_results_view
    assert "render_results_hub" not in main_results_view
    assert "render_results_hub(embedded=True)" in dedicated_results_page


def test_collect_builder_sessions_reads_summary_and_latest_strategy(tmp_path: Path) -> None:
    builder_root = tmp_path / "_builder_sessions"
    session_dir = builder_root / "session_alpha"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "strategy_v1.py").write_text("print('v1')\n", encoding="utf-8")
    (session_dir / "strategy_v2.py").write_text("print('v2')\n", encoding="utf-8")
    (session_dir / "strategy.py").write_text("print('latest')\n", encoding="utf-8")
    summary = {
        "session_id": "session_alpha",
        "status": "success",
        "model_name": "qwen-builder",
        "symbol": "BTCUSDC",
        "timeframe": "1h",
        "resume_parent_session_id": "",
        "resume_mode": "",
        "best_sharpe": 1.42,
        "best_score": 33.0,
        "total_iterations": 4,
        "objective": "Trouver une strategie momentum robuste.",
        "iterations": [
            {"iteration": 1, "return_pct": -2.0},
            {"iteration": 2, "return_pct": 8.5},
            {"iteration": 3, "return_pct": 12.25},
        ],
        "orchestration_mode": "single_llm",
    }
    (session_dir / "session_summary.json").write_text(json.dumps(summary), encoding="utf-8")

    rows = collect_builder_sessions(builder_root)

    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == "session_alpha"
    assert row["status"] == "success"
    assert row["model_name"] == "qwen-builder"
    assert row["symbol"] == "BTCUSDC"
    assert row["timeframe"] == "1h"
    assert row["resume_parent_session_id"] == ""
    assert row["best_return_pct"] == 12.25
    assert row["best_return_iteration"] == 3
    assert row["positive_iterations"] == 2
    assert row["positive_iteration_ids"] == [3, 2]
    assert "i3 +12.25%" in row["positive_iteration_summary"]
    assert row["strategy_versions"] == 2
    assert Path(row["latest_strategy_path"]).name == "strategy.py"


def test_collect_builder_max_iteration_resume_candidates_excludes_children_and_already_resumed() -> None:
    builder_df = pd.DataFrame(
        [
            {
                "session_id": "parent_a",
                "status": "max_iterations",
                "resume_parent_session_id": "",
                "last_modified": "2026-05-14 10:00:00",
            },
            {
                "session_id": "parent_b",
                "status": "max_iterations",
                "resume_parent_session_id": "",
                "last_modified": "2026-05-14 09:00:00",
            },
            {
                "session_id": "child_b",
                "status": "max_iterations",
                "resume_parent_session_id": "parent_b",
                "last_modified": "2026-05-14 11:00:00",
            },
            {
                "session_id": "success_c",
                "status": "success",
                "resume_parent_session_id": "",
                "last_modified": "2026-05-14 08:00:00",
            },
        ],
    )

    candidates = results_store_view_module._collect_builder_max_iteration_resume_candidates(builder_df)

    assert candidates["session_id"].tolist() == ["parent_a"]


def test_run_builder_max_iterations_resume_batch_uses_selected_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    summary_path = tmp_path / "session_summary.json"
    summary_path.write_text(
        json.dumps({"session_id": "parent_a", "objective": "test", "status": "max_iterations"}),
        encoding="utf-8",
    )
    candidates = pd.DataFrame(
        [
            {
                "session_id": "parent_a",
                "summary_path": str(summary_path),
                "symbol": "BTCUSDC",
                "timeframe": "1h",
            },
        ],
    )
    captured: dict[str, object] = {}

    class _FakeBuilder:
        def __init__(self, *, llm_config, backtest_completed_callback=None):
            captured["llm_config"] = llm_config
            captured["callback_present"] = backtest_completed_callback is not None

        def resume_from_summary(self, summary_path, data, **kwargs):
            captured["summary_path"] = str(summary_path)
            captured["data"] = data
            captured["resume_kwargs"] = dict(kwargs)
            return SimpleNamespace(
                session_id="child_a",
                resume_mode=kwargs["mode"],
                iterations=[object(), object()],
            )

    import agents.strategy_builder as strategy_builder_module
    import data.loader as data_loader_module
    import ui.builder_runtime as builder_runtime_module

    monkeypatch.setattr(results_store_view_module.st, "session_state", {
        "builder_ollama_host": "http://127.0.0.1:11434",
        "builder_keep_alive_minutes": 20,
        "llm_inference_global_settings": {},
        "llm_inference_model_profiles": {},
    }, raising=False)
    monkeypatch.setattr(strategy_builder_module, "StrategyBuilder", _FakeBuilder)
    monkeypatch.setattr(data_loader_module, "load_ohlcv", lambda symbol, timeframe: pd.DataFrame({"close": [1.0]}))
    monkeypatch.setattr(
        builder_runtime_module,
        "build_builder_base_llm_config",
        lambda **kwargs: captured.setdefault("llm_kwargs", dict(kwargs)) or SimpleNamespace(model=kwargs["model"]),
    )

    result = results_store_view_module._run_builder_max_iterations_resume_batch(
        candidates,
        model="selected-ui-model",
        mode="exact_continue",
    )

    assert result["resumed"] == 1
    assert captured["llm_kwargs"]["model"] == "selected-ui-model"
    assert captured["resume_kwargs"]["mode"] == "exact_continue"
    assert captured["resume_kwargs"]["extra_iterations"] == 10
    assert captured["resume_kwargs"]["restart_max_iterations"] == 20
    assert captured["callback_present"] is True


def test_display_int_and_coerce_int_tolerate_nan() -> None:
    assert results_store_view_module._coerce_int(float("nan")) is None
    assert results_store_view_module._display_int(float("nan")) == 0
    assert results_store_view_module._display_int("7") == 7


def test_builder_status_label_renames_running_without_changing_terminal_statuses() -> None:
    assert results_store_view_module._builder_status_label("running") == "À finir - stratégie non aboutie"
    assert results_store_view_module._builder_status_label("success") == "success"
    assert results_store_view_module._builder_status_label("") == "unknown"


def test_render_builder_tab_tolerates_nan_builder_counts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    metric_calls: list[tuple[str, object]] = []
    caption_calls: list[str] = []

    class _ColumnStub:
        def metric(self, label: object, value: object, *args: object, **kwargs: object) -> None:
            metric_calls.append((str(label), value))

        def __enter__(self) -> "_ColumnStub":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setattr(results_store_view_module.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_store_view_module.st, "write", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_store_view_module.st, "info", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_store_view_module.st, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_store_view_module.st, "dataframe", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_store_view_module.st, "code", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_store_view_module.st, "caption", lambda body, **kwargs: caption_calls.append(str(body)))
    monkeypatch.setattr(results_store_view_module.st, "text_input", lambda *args, **kwargs: "")
    monkeypatch.setattr(results_store_view_module.st, "multiselect", lambda label, options, default=None, **kwargs: list(options))
    monkeypatch.setattr(results_store_view_module.st, "selectbox", lambda label, options, **kwargs: list(options)[0])
    monkeypatch.setattr(results_store_view_module.st, "checkbox", lambda *args, **kwargs: False)
    monkeypatch.setattr(results_store_view_module.st, "button", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        results_store_view_module.st,
        "columns",
        lambda spec: [_ColumnStub() for _ in range(spec if isinstance(spec, int) else len(spec))],
    )
    monkeypatch.setattr(results_store_view_module.st, "expander", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(results_store_view_module, "_handle_open_action", lambda *args, **kwargs: None)
    monkeypatch.setattr(results_store_view_module, "_load_builder_linked_runs_df", lambda *args, **kwargs: pd.DataFrame())

    builder_df = pd.DataFrame(
        [
            {
                "session_id": "session_nan",
                "status": "success",
                "best_return_pct": 10.5,
                "best_return_iteration": float("nan"),
                "positive_iterations": float("nan"),
                "positive_iteration_summary": "",
                "best_sharpe": 1.23,
                "total_iterations": float("nan"),
                "strategy_versions": float("nan"),
                "last_modified": "2026-04-18 10:00:00",
                "objective_excerpt": "objectif",
                "session_dir": str(tmp_path / "session_nan"),
                "summary_path": "",
                "pipeline_traces_path": "",
                "latest_strategy_path": "",
                "instrumentation_enabled": False,
                "builder_execution_mode": "mono_single_llm",
                "orchestration_mode": "single_llm",
                "objective": "",
            },
        ],
    )

    results_store_view_module._render_builder_tab(
        builder_df,
        pd.DataFrame(),
        tmp_path,
        {
            "builder_session_dir_count": 1,
            "catalog_builder_session_count": float("nan"),
            "linked_builder_run_count": 0,
            "disk_only_session_count": 0,
            "catalog_only_session_count": 0,
            "disk_only_sessions": [],
            "catalog_only_sessions": [],
        },
    )

    assert ("Iterations", 0) in metric_calls
    assert ("Retours positifs", 0) in metric_calls
    assert ("Sessions cataloguées", 0) in metric_calls
    assert any(caption == "Fichiers stratégie: 0" for caption in caption_calls)
    assert all("best iter" not in caption for caption in caption_calls)


def test_collect_builder_iterations_reads_all_iteration_rows(tmp_path: Path) -> None:
    builder_root = tmp_path / "_builder_sessions"
    session_dir = builder_root / "session_alpha"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "strategy_v1.py").write_text("print('v1')\n", encoding="utf-8")
    (session_dir / "strategy_v2.py").write_text("print('v2')\n", encoding="utf-8")
    summary = {
        "session_id": "session_alpha",
        "status": "max_iterations",
        "objective": "Explorer plusieurs variantes momentum.",
        "iterations": [
            {
                "iteration": 1,
                "return_pct": -2.0,
                "sharpe": 0.1,
                "profit_factor": 0.9,
                "trades": 8,
                "params_used": {"fast_period": 8},
                "diagnostic_category": "weak_edge",
            },
            {
                "iteration": 2,
                "return_pct": 8.5,
                "sharpe": 0.9,
                "profit_factor": 1.2,
                "trades": 18,
                "params_used": {"fast_period": 12, "slow_period": 26},
                "diagnostic_category": "trend",
            },
        ],
        "leaderboard": [
            {"rank": 1, "iteration": 2},
            {"rank": 2, "iteration": 1},
        ],
    }
    (session_dir / "session_summary.json").write_text(json.dumps(summary), encoding="utf-8")

    rows = collect_builder_iterations(builder_root)

    assert len(rows) == 2
    by_iteration = {row["iteration"]: row for row in rows}
    assert by_iteration[1]["candidate_id"] == "builder:session_alpha:1"
    assert by_iteration[1]["positive_return"] is False
    assert by_iteration[2]["positive_return"] is True
    assert by_iteration[2]["leaderboard_rank"] == 1
    assert by_iteration[2]["params_used_preview"] == "fast_period=12, slow_period=26"
    assert Path(by_iteration[2]["strategy_path"]).name == "strategy_v2.py"


def test_collect_store_inventory_counts_expected_directories(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    artifacts_root = tmp_path / "artifacts"
    (results_root / "runs").mkdir(parents=True, exist_ok=True)
    (artifacts_root / "_analysis").mkdir(parents=True, exist_ok=True)
    (artifacts_root / "_builder_sessions" / "session_alpha").mkdir(parents=True, exist_ok=True)
    (artifacts_root / "_diagnostics" / "sweeps").mkdir(parents=True, exist_ok=True)
    (artifacts_root / "_analysis" / "analysis_report.html").write_text("<html></html>", encoding="utf-8")
    (artifacts_root / "_diagnostics" / "sweeps" / "diag.log").write_text("ok\n", encoding="utf-8")

    rows = collect_store_inventory(results_root, artifacts_root)

    by_label = {row["label"]: row for row in rows}
    assert by_label["Dossier analyses"]["exists"] is True
    assert by_label["Dossier analyses"]["items"] == 1
    assert by_label["Dossiers de session Builder"]["items"] == 1
    assert by_label["Dossier diagnostics sweeps"]["items"] == 1
    assert by_label["Dossiers de run legacy"]["exists"] is True


def test_collect_builder_catalog_reconciliation_reports_disk_and_catalog_gaps(tmp_path: Path) -> None:
    builder_root = tmp_path / "_builder_sessions"
    (builder_root / "session_a").mkdir(parents=True, exist_ok=True)
    (builder_root / "session_b").mkdir(parents=True, exist_ok=True)

    catalog_dir = tmp_path / "_catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = catalog_dir / "unified_overview.csv"
    fieldnames = ["run_id", "extra_builder_session_id"]
    with catalog_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            [
                {"run_id": "run_1", "extra_builder_session_id": "session_a"},
                {"run_id": "run_2", "extra_builder_session_id": "session_c"},
            ],
        )

    audit = collect_builder_catalog_reconciliation(tmp_path, builder_root)

    assert audit["builder_session_dir_count"] == 2
    assert audit["catalog_builder_session_count"] == 2
    assert audit["linked_builder_run_count"] == 2
    assert audit["matched_session_count"] == 1
    assert audit["disk_only_sessions"] == ["session_b"]
    assert audit["catalog_only_sessions"] == ["session_c"]


def test_collect_builder_linked_runs_filters_catalog_by_session_id(tmp_path: Path) -> None:
    catalog_dir = tmp_path / "_catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = catalog_dir / "unified_overview.csv"
    fieldnames = [
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
    ]
    rows = [
        {
            "run_id": "run_a",
            "timestamp": "2026-03-20T08:00:00+00:00",
            "status": "ok",
            "strategy": "ema_cross",
            "symbol": "BTCUSDC",
            "timeframe": "1h",
            "path": "run_a",
            "metrics_total_return_pct": "11.5",
            "metrics_sharpe_ratio": "1.1",
            "metrics_profit_factor": "1.3",
            "metrics_total_trades": "24",
            "extra_builder_session_id": "session_alpha",
            "extra_builder_iteration": "2",
        },
        {
            "run_id": "run_b",
            "timestamp": "2026-03-20T09:00:00+00:00",
            "status": "ok",
            "strategy": "ema_cross",
            "symbol": "BTCUSDC",
            "timeframe": "1h",
            "path": "run_b",
            "metrics_total_return_pct": "15.0",
            "metrics_sharpe_ratio": "1.4",
            "metrics_profit_factor": "1.5",
            "metrics_total_trades": "28",
            "extra_builder_session_id": "session_alpha",
            "extra_builder_iteration": "3",
        },
        {
            "run_id": "run_c",
            "timestamp": "2026-03-20T10:00:00+00:00",
            "status": "ok",
            "strategy": "rsi_reversal",
            "symbol": "ETHUSDC",
            "timeframe": "4h",
            "path": "run_c",
            "metrics_total_return_pct": "7.0",
            "metrics_sharpe_ratio": "0.9",
            "metrics_profit_factor": "1.1",
            "metrics_total_trades": "14",
            "extra_builder_session_id": "session_beta",
            "extra_builder_iteration": "1",
        },
    ]
    with catalog_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    linked_rows = collect_builder_linked_runs(tmp_path, "session_alpha")

    assert len(linked_rows) == 2
    assert linked_rows[0]["run_id"] == "run_b"
    assert linked_rows[1]["run_id"] == "run_a"


@pytest.mark.parametrize(
    ("relative_page_path", "render_module_name", "render_function_name"),
    [
        ("ui/pages/results_store_page.py", "ui.results_store_view", "render_results_store_page"),
        ("ui/pages/model_stats_page.py", "ui.model_stats_view", "render_model_stats_page"),
        ("ui/pages/range_editor_page.py", "ui.range_editor", "render_range_editor"),
    ],
)
def test_streamlit_page_scripts_render_once_when_executed_as_main(
    monkeypatch: pytest.MonkeyPatch,
    relative_page_path: str,
    render_module_name: str,
    render_function_name: str,
) -> None:
    streamlit_calls, render_calls, observability_calls = _run_streamlit_page_script_once(
        monkeypatch,
        relative_page_path=relative_page_path,
        render_module_name=render_module_name,
        render_function_name=render_function_name,
    )

    assert render_calls == [render_function_name]
    assert observability_calls == ["init_logging"]
    assert [call[0] for call in streamlit_calls].count("set_page_config") == 1


def test_asyncio_websocket_close_filter_only_drops_benign_closed_socket_noise() -> None:
    from utils.observability import _AsyncioBenignWebSocketCloseFilter

    filter_ = _AsyncioBenignWebSocketCloseFilter()
    benign_exc = type("WebSocketClosedError", (Exception,), {})("socket closed")
    benign_record = logging.LogRecord(
        name="asyncio",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Task exception was never retrieved",
        args=(),
        exc_info=(type(benign_exc), benign_exc, None),
    )
    assert filter_.filter(benign_record) is False

    unrelated_exc = RuntimeError("boom")
    unrelated_record = logging.LogRecord(
        name="asyncio",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Task exception was never retrieved",
        args=(),
        exc_info=(type(unrelated_exc), unrelated_exc, None),
    )
    assert filter_.filter(unrelated_record) is True

    other_logger_record = logging.LogRecord(
        name="backtest.ui",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Task exception was never retrieved",
        args=(),
        exc_info=(type(benign_exc), benign_exc, None),
    )
    assert filter_.filter(other_logger_record) is True
