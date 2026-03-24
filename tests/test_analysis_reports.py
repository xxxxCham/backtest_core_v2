from __future__ import annotations

import builtins
import csv
import json
from pathlib import Path

import backtest.result_store as result_store_module
from backtest.result_store import (
    get_artifacts_root_dir,
    get_builder_sessions_dir,
    get_output_root_dir,
    get_results_analysis_dir,
    get_profiling_results_dir,
    get_results_archive_dir,
    get_results_organized_dir,
    get_saved_runs_dir,
    get_sweep_diagnostics_dir,
    get_workspace_results_analysis_dir,
    get_workspace_results_root_dir,
)
from tools.analyze_results import extract_all_results, refresh_analysis_artifacts


def _write_run(root: Path, run_id: str, *, strategy: str, symbol: str, timeframe: str, total_return_pct: float, ruined: bool = False) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "timestamp": "2026-03-10T10:00:00",
        "strategy": strategy,
        "symbol": symbol,
        "timeframe": timeframe,
        "status": "ok",
        "mode": "backtest",
        "params": {
            "initial_capital": 10000,
            "fees_bps": 10,
            "leverage": 2,
            "fast_period": 12,
        },
        "metrics": {
            "total_pnl": 1000 * (total_return_pct / 10.0),
            "total_return_pct": total_return_pct,
            "sharpe_ratio": 1.4,
            "sortino_ratio": 1.2,
            "win_rate_pct": 55.0,
            "total_trades": 25,
            "profit_factor": 1.3,
            "max_drawdown_pct": -12.5,
            "account_ruined": ruined,
        },
    }
    (run_dir / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")


def test_extract_all_results_reads_metadata(tmp_path: Path) -> None:
    results_root = tmp_path / "backtest_results"
    _write_run(results_root, "run_a", strategy="ema_cross", symbol="BTCUSDC", timeframe="1h", total_return_pct=12.5)

    results = extract_all_results(results_root)

    assert len(results) == 1
    assert results[0]["run_id"] == "run_a"
    assert results[0]["strategy"] == "ema_cross"
    assert results[0]["params"] == {"fast_period": 12, "leverage": 2}


def test_refresh_analysis_artifacts_generates_html_and_top_csv(tmp_path: Path, monkeypatch) -> None:
    results_root = tmp_path / "backtest_results"
    workspace_analysis_dir = tmp_path / "workspace" / "backtest_results" / "_analysis"
    _write_run(results_root, "run_profitable", strategy="ema_cross", symbol="BTCUSDC", timeframe="1h", total_return_pct=18.0)
    _write_run(results_root, "run_profitable_dup", strategy="ema_cross", symbol="BTCUSDC", timeframe="1h", total_return_pct=18.0)
    _write_run(results_root, "run_negative", strategy="rsi_reversal", symbol="ETHUSDC", timeframe="4h", total_return_pct=-4.0, ruined=True)

    monkeypatch.setenv("BACKTEST_RESULTS_DIR", str(results_root))
    monkeypatch.setenv("BACKTEST_ARTIFACTS_DIR", str(results_root))
    monkeypatch.chdir(tmp_path)
    stats = refresh_analysis_artifacts(
        results_root,
        top_n=100,
        workspace_output_dir=workspace_analysis_dir,
    )
    analysis_dir = results_root / "_analysis"

    assert stats["raw_results"] == 3
    assert stats["total_results"] == 2
    assert stats["filtered_results"] == 1
    assert stats["workspace_output_dir"] == str(workspace_analysis_dir)
    assert (analysis_dir / "analysis_report.html").exists()
    assert (analysis_dir / "analysis_report_filtered.html").exists()
    assert (analysis_dir / "analysis_top_configs.csv").exists()
    assert (workspace_analysis_dir / "analysis_report.html").exists()
    assert (workspace_analysis_dir / "analysis_report_filtered.html").exists()
    assert (workspace_analysis_dir / "analysis_top_configs.csv").exists()
    assert len(stats["mirrored_files"]) == 3

    with open(analysis_dir / "analysis_top_configs.csv", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run_profitable"
    assert rows[0]["duplicate_run_count"] == "2"
    assert "Top 100 Configurations" in (analysis_dir / "analysis_report_filtered.html").read_text(encoding="utf-8")


def test_refresh_analysis_artifacts_handles_nested_params(tmp_path: Path, monkeypatch) -> None:
    results_root = tmp_path / "backtest_results"
    workspace_analysis_dir = results_root / "_analysis"
    run_dir = results_root / "run_nested"
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": "run_nested",
        "timestamp": "2026-03-10T10:00:00",
        "strategy": "ema_cross",
        "symbol": "BTCUSDC",
        "timeframe": "1h",
        "status": "ok",
        "mode": "backtest",
        "params": {
            "fast_period": 12,
            "filters": {"adx_min": 20, "volatility": {"enabled": True}},
        },
        "metrics": {
            "total_pnl": 1200.0,
            "total_return_pct": 12.0,
            "sharpe_ratio": 1.4,
            "sortino_ratio": 1.2,
            "win_rate_pct": 55.0,
            "total_trades": 25,
            "profit_factor": 1.3,
            "max_drawdown_pct": -12.5,
            "account_ruined": False,
        },
    }
    (run_dir / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("BACKTEST_RESULTS_DIR", str(results_root))
    monkeypatch.setenv("BACKTEST_ARTIFACTS_DIR", str(results_root))
    stats = refresh_analysis_artifacts(
        results_root,
        top_n=10,
        workspace_output_dir=workspace_analysis_dir,
    )

    assert stats["total_results"] == 1
    assert stats["filtered_results"] == 1
    assert stats["mirrored_files"] == []


def test_artifact_helpers_default_under_results_dir(tmp_path: Path, monkeypatch) -> None:
    results_root = tmp_path / "backtest_results"
    monkeypatch.setenv("BACKTEST_RESULTS_DIR", str(results_root))
    monkeypatch.delenv("BACKTEST_ARTIFACTS_DIR", raising=False)
    monkeypatch.setattr(result_store_module, "PROJECT_ENV_PATH", tmp_path / ".env")

    assert get_artifacts_root_dir() == results_root
    assert get_results_analysis_dir() == results_root / "_analysis"
    assert get_workspace_results_root_dir() == tmp_path / "backtest_results"
    assert get_workspace_results_analysis_dir() == tmp_path / "backtest_results" / "_analysis"
    assert get_saved_runs_dir() == results_root / "_saved_runs"
    assert get_builder_sessions_dir() == results_root / "_builder_sessions"
    assert get_sweep_diagnostics_dir() == results_root / "_diagnostics" / "sweeps"
    assert get_profiling_results_dir() == results_root / "_profiling"
    assert get_output_root_dir() == results_root / "_output"
    assert get_results_organized_dir() == results_root / "_organized_results"
    assert get_results_archive_dir() == results_root / "_archive_results"


def test_artifact_helpers_respect_explicit_artifacts_root(tmp_path: Path, monkeypatch) -> None:
    results_root = tmp_path / "backtest_results"
    artifacts_root = tmp_path / "artifacts"
    monkeypatch.setenv("BACKTEST_RESULTS_DIR", str(results_root))
    monkeypatch.setenv("BACKTEST_ARTIFACTS_DIR", str(artifacts_root))
    monkeypatch.setattr(result_store_module, "PROJECT_ENV_PATH", tmp_path / ".env")

    assert get_artifacts_root_dir() == artifacts_root
    assert get_results_analysis_dir() == artifacts_root / "_analysis"
    assert get_workspace_results_root_dir() == tmp_path / "backtest_results"
    assert get_workspace_results_analysis_dir() == tmp_path / "backtest_results" / "_analysis"
    assert get_saved_runs_dir() == artifacts_root / "_saved_runs"
    assert get_builder_sessions_dir() == artifacts_root / "_builder_sessions"
    assert get_sweep_diagnostics_dir() == artifacts_root / "_diagnostics" / "sweeps"
    assert get_profiling_results_dir() == artifacts_root / "_profiling"
    assert get_output_root_dir() == artifacts_root / "_output"
    assert get_results_organized_dir() == artifacts_root / "_organized_results"
    assert get_results_archive_dir() == artifacts_root / "_archive_results"


def test_load_project_env_fallback_reads_dotenv_without_python_dotenv(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    results_root = tmp_path / "external_results"
    artifacts_root = tmp_path / "external_artifacts"
    env_path.write_text(
        "\n".join(
            [
                f"BACKTEST_RESULTS_DIR={results_root}",
                f"BACKTEST_ARTIFACTS_DIR={artifacts_root}",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("BACKTEST_RESULTS_DIR", raising=False)
    monkeypatch.delenv("BACKTEST_ARTIFACTS_DIR", raising=False)
    monkeypatch.setattr(result_store_module, "PROJECT_ENV_PATH", env_path)
    monkeypatch.setattr(result_store_module, "_DOTENV_LOADED", False)

    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "dotenv":
            raise ImportError("forced by test")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert result_store_module.load_project_env() is True
    assert result_store_module.get_results_root_dir() == results_root
    assert result_store_module.get_artifacts_root_dir() == artifacts_root
    assert result_store_module.get_results_analysis_dir() == artifacts_root / "_analysis"
