from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from backtest.storage import ResultStorage


def _sample_native_result():
    index = pd.date_range("2025-01-01", periods=5, freq="h", tz="UTC")
    equity = pd.Series([10000.0, 10010.0, 10025.0, 10020.0, 10040.0], index=index, name="equity")
    returns = equity.pct_change().fillna(0.0).rename("returns")
    trades = pd.DataFrame(
        [
            {"entry_time": str(index[1]), "exit_time": str(index[2]), "pnl": 10.0},
            {"entry_time": str(index[3]), "exit_time": str(index[4]), "pnl": 15.0},
        ],
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
        (tmp_path / "backtest_results" / "runs" / "native_run_001" / "metadata.json").read_text(
            encoding="utf-8",
        ),
    )
    assert metadata["period_start"] == "2026-03-07T17:35:19+00:00"


def test_load_result_falls_back_to_legacy_root_layout(tmp_path):
    storage_root = tmp_path / "backtest_results"
    legacy_run_dir = storage_root / "legacy_run_001"
    legacy_run_dir.mkdir(parents=True)

    sample = _sample_native_result()
    metadata = {
        "run_id": "legacy_run_001",
        "timestamp": "2026-03-07T17:35:19+00:00",
        "strategy": sample.meta["strategy"],
        "symbol": sample.meta["symbol"],
        "timeframe": sample.meta["timeframe"],
        "params": sample.meta["params"],
        "metrics": sample.metrics,
        "n_bars": len(sample.equity),
        "n_trades": len(sample.trades),
        "period_start": sample.meta["period_start"],
        "period_end": sample.meta["period_end"],
        "duration_sec": 0.5,
        "mode": "builder",
        "status": "ok",
        "extra_metadata": {"builder_session_id": "legacy-sess"},
    }
    (legacy_run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    sample.equity.to_frame(name="equity").to_parquet(legacy_run_dir / "equity.parquet")
    sample.trades.to_parquet(legacy_run_dir / "trades.parquet", index=False)
    sample.returns.to_frame(name="returns").to_parquet(legacy_run_dir / "returns.parquet")

    storage = ResultStorage(storage_root)

    loaded = storage.load_result("legacy_run_001")

    assert loaded.meta["builder_session_id"] == "legacy-sess"
    assert loaded.meta["strategy"] == sample.meta["strategy"]


def test_migrate_legacy_layout_to_runs_dir_moves_native_runs(tmp_path):
    storage_root = tmp_path / "backtest_results"
    sample = _sample_native_result()
    legacy_run_id = "legacy_migrate_001"
    migrated_source = storage_root / legacy_run_id
    migrated_source.mkdir(parents=True)
    metadata = {
        "run_id": legacy_run_id,
        "timestamp": "2026-03-07T17:35:19+00:00",
        "strategy": sample.meta["strategy"],
        "symbol": sample.meta["symbol"],
        "timeframe": sample.meta["timeframe"],
        "params": sample.meta["params"],
        "metrics": sample.metrics,
        "n_bars": len(sample.equity),
        "n_trades": len(sample.trades),
        "period_start": sample.meta["period_start"],
        "period_end": sample.meta["period_end"],
        "duration_sec": 0.5,
        "mode": "builder",
        "status": "ok",
        "extra_metadata": {"builder_session_id": "legacy-migrate"},
    }
    (migrated_source / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    sample.equity.to_frame(name="equity").to_parquet(migrated_source / "equity.parquet")
    sample.trades.to_parquet(migrated_source / "trades.parquet", index=False)
    sample.returns.to_frame(name="returns").to_parquet(migrated_source / "returns.parquet")

    storage = ResultStorage(storage_root)
    migrated = storage.migrate_legacy_layout_to_runs_dir()

    assert migrated == 1
    assert not migrated_source.exists()
    assert (storage_root / "runs" / legacy_run_id / "metadata.json").exists()
    assert storage.load_result(legacy_run_id).meta["strategy"] == sample.meta["strategy"]


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


def test_build_catalogs_clamps_invalid_legacy_max_drawdown_pct(tmp_path):
    storage_root = tmp_path / "backtest_results"
    runs_root = storage_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)

    broken_run_dir = runs_root / "broken_legacy_dd"
    broken_run_dir.mkdir(parents=True, exist_ok=True)
    (broken_run_dir / "metadata.json").write_text(
        json.dumps(
            {
                "run_id": "broken_legacy_dd",
                "timestamp": "2026-04-17T12:00:00+00:00",
                "strategy": "ema_cross",
                "symbol": "BTCUSDC",
                "timeframe": "1h",
                "params": {"fast_period": 12, "slow_period": 26},
                "metrics": {
                    "total_return_pct": 14.2,
                    "sharpe_ratio": 1.3,
                    "max_drawdown_pct": -1052.7795852445672,
                    "total_trades": 17,
                },
                "n_bars": 800,
                "n_trades": 17,
                "period_start": "2026-01-01T00:00:00+00:00",
                "period_end": "2026-02-01T00:00:00+00:00",
                "duration_sec": 0.7,
                "mode": "backtest",
                "status": "ok",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    storage = ResultStorage(storage_root)

    catalog_path = storage.build_catalogs(force=True)
    overview_df = pd.read_csv(catalog_path)

    row = overview_df.loc[overview_df["run_id"] == "broken_legacy_dd"].iloc[0]
    assert row["metrics_max_drawdown_pct"] == -100.0


def test_metadata_from_v3_row_ignores_nan_max_drawdown_without_clamp_warning(tmp_path, caplog: pytest.LogCaptureFixture):
    storage = ResultStorage(tmp_path / "backtest_results")
    row = {
        "run_id": "nan_dd_v3_row",
        "created_at": "2026-04-17T12:00:00+00:00",
        "strategy": "ema_cross",
        "symbol": "BTCUSDC",
        "timeframe": "1h",
        "params": {"fast_period": 12, "slow_period": 26},
        "total_return_pct": 14.2,
        "sharpe_ratio": 1.3,
        "max_drawdown_pct": float("nan"),
        "n_trades": 17,
        "period_start": "2026-01-01T00:00:00+00:00",
        "period_end": "2026-02-01T00:00:00+00:00",
        "duration_sec": 0.7,
        "mode": "backtest",
        "status": "ok",
        "extra": {"n_bars": 800},
    }

    with caplog.at_level("WARNING"):
        metadata = storage._metadata_from_v3_row(row)

    assert "max_drawdown_pct" not in metadata.metrics
    assert "storage_metric_clamped" not in caplog.text


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
