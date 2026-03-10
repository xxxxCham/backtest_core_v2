from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd

from backtest.storage import ResultStorage


def _sample_native_result():
    index = pd.date_range("2025-01-01", periods=5, freq="h", tz="UTC")
    equity = pd.Series([10000.0, 10010.0, 10025.0, 10020.0, 10040.0], index=index, name="equity")
    returns = equity.pct_change().fillna(0.0).rename("returns")
    trades = pd.DataFrame(
        [
            {"entry_time": str(index[1]), "exit_time": str(index[2]), "pnl": 10.0},
            {"entry_time": str(index[3]), "exit_time": str(index[4]), "pnl": 15.0},
        ]
    )
    metrics = {
        "total_pnl": 40.0,
        "total_return_pct": 0.4,
        "max_drawdown_pct": -0.2,
        "sharpe_ratio": 1.1,
        "sortino_ratio": 1.2,
        "profit_factor": 1.05,
        "win_rate_pct": 50.0,
        "total_trades": 2,
    }
    meta = {
        "run_id": "native_run_001",
        "strategy": "ema_cross",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "params": {"fast_period": 10, "slow_period": 30},
        "period_start": str(index[0]),
        "period_end": str(index[-1]),
        "origin": "builder",
        "builder_session_id": "sess-1",
        "builder_iteration": 2,
    }
    return SimpleNamespace(equity=equity, returns=returns, trades=trades, metrics=metrics, meta=meta)


def test_save_and_load_result_persists_extra_metadata(tmp_path):
    storage = ResultStorage(tmp_path / "backtest_results")
    result = _sample_native_result()

    storage.save_result(result)
    saved = storage.list_results()[0]

    assert saved.mode == "builder"
    assert saved.status == "ok"
    assert saved.extra_metadata["builder_session_id"] == "sess-1"
    assert saved.extra_metadata["builder_iteration"] == 2

    loaded = storage.load_result("native_run_001")
    assert loaded.meta["origin"] == "builder"
    assert loaded.meta["builder_session_id"] == "sess-1"
    assert loaded.meta["builder_iteration"] == 2


def test_save_result_serializes_timestamp_extra_metadata(tmp_path):
    storage = ResultStorage(tmp_path / "backtest_results")
    result = _sample_native_result()
    result.meta["period_start"] = pd.Timestamp("2026-03-07T17:35:19Z")

    storage.save_result(result)

    metadata = json.loads(
        (tmp_path / "backtest_results" / "native_run_001" / "metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert metadata["period_start"] == "2026-03-07T17:35:19+00:00"


def test_audit_storage_indexes_nested_runner_manifests(tmp_path):
    storage_root = tmp_path / "backtest_results"
    storage = ResultStorage(storage_root)
    storage.save_result(_sample_native_result())

    nested_dir = storage_root / "runs" / "legacy_cycle"
    nested_dir.mkdir(parents=True)
    (nested_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": "legacy_cycle",
                "mode": "cycle",
                "status": "ok",
                "created_at": "2026-02-23T16:25:29+00:00",
                "strategy": "ema_cross",
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "params": {},
                "period_start": "2025-01-01",
                "period_end": "2025-01-31",
                "extra": {"config_snapshot_extra": {"command": "cycle"}},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (nested_dir / "metrics.json").write_text(
        json.dumps({"total_return_pct": 2.0, "sharpe_ratio": 1.3, "total_trades": 4}, indent=2),
        encoding="utf-8",
    )

    report = storage.audit_storage(write_report=True)
    catalog_path = storage.build_catalogs(force=True)
    unified_path = storage_root / "_catalog" / "unified_overview.csv"
    overview_df = pd.read_csv(catalog_path)

    assert report["summary"]["entries"] == 2
    assert report["summary"]["native_entries"] == 1
    assert report["summary"]["external_entries"] == 1
    assert report["summary"]["containers"] == 1
    assert "runs" in report["containers"]
    assert catalog_path.exists()
    assert unified_path.exists()
    assert "path" in overview_df.columns
    assert overview_df.loc[0, "path"] == "native_run_001"


def test_validate_integrity_ignores_metadata_containers(tmp_path):
    storage_root = tmp_path / "backtest_results"
    storage = ResultStorage(storage_root)
    storage.save_result(_sample_native_result())

    nested_dir = storage_root / "runs" / "legacy_cycle"
    nested_dir.mkdir(parents=True)
    (nested_dir / "metadata.json").write_text(
        json.dumps({"run_id": "legacy_cycle", "mode": "cycle", "status": "ok"}, indent=2),
        encoding="utf-8",
    )
    (nested_dir / "metrics.json").write_text(json.dumps({"sharpe_ratio": 1.0}, indent=2), encoding="utf-8")

    report = storage.validate_integrity(auto_fix=False)

    assert not any("runs: Fichier manquant" in warning for warning in report["warnings"])
