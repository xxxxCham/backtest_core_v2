from __future__ import annotations

import csv
import json
import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from ui.results_store_view import (
    collect_builder_linked_runs,
    collect_builder_sessions,
    collect_store_inventory,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_fake_streamlit(call_log: list[tuple[str, tuple[object, ...], dict[str, object]]]) -> ModuleType:
    fake_streamlit = ModuleType("streamlit")
    fake_streamlit.sidebar = SimpleNamespace(
        markdown=lambda *args, **kwargs: call_log.append(("sidebar.markdown", args, kwargs))
    )
    fake_streamlit.set_page_config = lambda *args, **kwargs: call_log.append(
        ("set_page_config", args, kwargs)
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
) -> tuple[list[tuple[str, tuple[object, ...], dict[str, object]]], list[str]]:
    streamlit_calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
    render_calls: list[str] = []

    fake_streamlit = _build_fake_streamlit(streamlit_calls)
    fake_render_module = ModuleType(render_module_name)
    setattr(fake_render_module, render_function_name, lambda: render_calls.append(render_function_name))

    import ui

    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    monkeypatch.setitem(sys.modules, render_module_name, fake_render_module)
    monkeypatch.setattr(ui, render_module_name.rsplit(".", 1)[-1], fake_render_module, raising=False)

    runpy.run_path(str(REPO_ROOT / relative_page_path), run_name="__main__")
    return streamlit_calls, render_calls


def test_app_css_uses_full_width_layout_and_keeps_sidebar_controls_interactive() -> None:
    content = (REPO_ROOT / "ui" / "app.py").read_text(encoding="utf-8")

    assert "max-width: 1520px;" not in content
    assert "max-width: none;" in content
    assert 'transform: translateX(0) !important;' not in content
    assert 'pointer-events: none !important;' not in content
    assert 'button[kind="header"]' in content


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

    assert 'transform: translateX(0) !important;' not in content
    assert 'pointer-events: none !important;' not in content
    assert 'button[kind="header"]' in content


def test_results_hub_is_only_exposed_via_dedicated_results_store_page() -> None:
    main_results_view = (REPO_ROOT / "ui" / "results.py").read_text(encoding="utf-8")
    dedicated_results_page = (REPO_ROOT / "ui" / "results_store_view.py").read_text(
        encoding="utf-8"
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
        "best_sharpe": 1.42,
        "best_score": 33.0,
        "total_iterations": 4,
        "objective": "Trouver une strategie momentum robuste.",
        "iterations": [
            {"iteration": 1, "return_pct": -2.0},
            {"iteration": 2, "return_pct": 8.5},
            {"iteration": 3, "return_pct": 12.25},
        ],
        "orchestration_mode": "multi_llm",
        "multi_llm_profile": "brain",
        "multi_llm_router_decision": {
            "action": "iterate",
            "reason": "tighten exits",
        },
        "multi_llm_assignments": [
            {
                "role": "builder_llm",
                "requested_model": "qwen3-coder:30b",
                "resolved_model": "qwen3-coder:30b",
                "available": True,
            }
        ],
        "multi_llm_shared_memory": {
            "continuity_context": {
                "recent_sessions": [{"session_num": 8, "symbol": "BTCUSDT"}],
                "best_recent_session": {"session_num": 8, "symbol": "BTCUSDT"},
                "carry_over_focus": ["tighten exits"],
                "recurring_risks": ["drawdown spike"],
            }
        },
    }
    (session_dir / "session_summary.json").write_text(json.dumps(summary), encoding="utf-8")

    rows = collect_builder_sessions(builder_root)

    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == "session_alpha"
    assert row["status"] == "success"
    assert row["best_return_pct"] == 12.25
    assert row["strategy_versions"] == 2
    assert Path(row["latest_strategy_path"]).name == "strategy.py"
    assert row["multi_llm_profile"] == "brain"
    assert row["multi_llm_router_decision"]["action"] == "iterate"
    assert row["continuity_context"]["carry_over_focus"] == ["tighten exits"]


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
    assert by_label["Analyses"]["exists"] is True
    assert by_label["Analyses"]["items"] == 1
    assert by_label["Sessions Builder"]["items"] == 1
    assert by_label["Diagnostics sweeps"]["items"] == 1
    assert by_label["Legacy runs"]["exists"] is True


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
    streamlit_calls, render_calls = _run_streamlit_page_script_once(
        monkeypatch,
        relative_page_path=relative_page_path,
        render_module_name=render_module_name,
        render_function_name=render_function_name,
    )

    assert render_calls == [render_function_name]
    assert [call[0] for call in streamlit_calls].count("set_page_config") == 1
