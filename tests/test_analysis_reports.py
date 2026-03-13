from __future__ import annotations

import csv
import json
from pathlib import Path

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
    _write_run(results_root, "run_profitable", strategy="ema_cross", symbol="BTCUSDC", timeframe="1h", total_return_pct=18.0)
    _write_run(results_root, "run_profitable_dup", strategy="ema_cross", symbol="BTCUSDC", timeframe="1h", total_return_pct=18.0)
    _write_run(results_root, "run_negative", strategy="rsi_reversal", symbol="ETHUSDC", timeframe="4h", total_return_pct=-4.0, ruined=True)

    monkeypatch.chdir(tmp_path)
    stats = refresh_analysis_artifacts(results_root, top_n=100)

    assert stats["raw_results"] == 3
    assert stats["total_results"] == 2
    assert stats["filtered_results"] == 1
    assert (tmp_path / "analysis_report.html").exists()
    assert (tmp_path / "analysis_report_filtered.html").exists()
    assert (tmp_path / "analysis_top_configs.csv").exists()

    with open(tmp_path / "analysis_top_configs.csv", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run_profitable"
    assert rows[0]["duplicate_run_count"] == "2"
    assert "Top 100 Configurations" in (tmp_path / "analysis_report_filtered.html").read_text(encoding="utf-8")
