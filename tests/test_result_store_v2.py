from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd

from backtest.result_store import ResultStore
from backtest.store_v3 import BacktestStoreV3


def _sample_run_result():
    index = pd.date_range("2025-01-01", periods=5, freq="h")
    equity = pd.Series([10000.0, 10020.0, 10010.0, 10060.0, 10100.0], index=index, name="equity")
    returns = equity.pct_change().fillna(0.0).rename("returns")
    trades = pd.DataFrame(
        [
            {"entry_time": str(index[1]), "exit_time": str(index[2]), "pnl": 20.0},
            {"entry_time": str(index[3]), "exit_time": str(index[4]), "pnl": 40.0},
        ],
    )
    metrics = {
        "total_return_pct": 1.0,
        "max_drawdown_pct": -0.3,
        "sharpe_ratio": 1.2,
        "sortino_ratio": 1.4,
        "profit_factor": 1.1,
        "win_rate_pct": 50.0,
        "total_trades": 2,
    }
    meta = {
        "run_id": "legacy_run_id",
        "strategy": "ema_cross",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "params": {"fast_period": 10, "slow_period": 30},
        "period_start": str(index[0]),
        "period_end": str(index[-1]),
        "seed": 42,
    }
    return SimpleNamespace(equity=equity, returns=returns, trades=trades, metrics=metrics, meta=meta)


def test_result_store_writes_backtest_artifacts_and_index(tmp_path):
    store = ResultStore(tmp_path / "backtest_results")
    result = _sample_run_result()

    record = store.save_backtest_result(result, mode="backtest")
    run_dir = tmp_path / "backtest_results" / "runs" / record.run_id

    assert (run_dir / "metadata.json").exists()
    assert (run_dir / "equity.parquet").exists()
    assert (run_dir / "trades.parquet").exists()
    assert (run_dir / "returns.parquet").exists()

    index_df = store.load_index()
    assert not index_df.empty
    row = index_df.iloc[0]
    assert row["run_id"] == record.run_id
    assert row["mode"] == "backtest"
    assert row["strategy"] == "ema_cross"
    assert row["symbol"] == "BTCUSDT"
    assert row["timeframe"] == "1h"


def test_result_store_run_id_collision_gets_incremental_suffix(tmp_path):
    store = ResultStore(tmp_path / "backtest_results")
    result = _sample_run_result()
    fixed_time = "2026-02-18T00:00:00+00:00"

    first = store.save_backtest_result(result, metadata_extra={"created_at": fixed_time})
    second = store.save_backtest_result(result, metadata_extra={"created_at": fixed_time})

    assert second.run_id != first.run_id
    assert second.run_id.startswith(first.run_id.rsplit("_r", 1)[0])
    assert "_r" in second.run_id


def test_result_store_walk_forward_and_golden_set(tmp_path):
    store = ResultStore(tmp_path / "backtest_results")
    parent = store.save_summary_run(
        mode="cycle",
        strategy="ema_cross",
        symbol="BTCUSDT",
        timeframe="1h",
        params={"fast_period": 10, "slow_period": 30},
        metrics={"total_return_pct": 2.0, "sharpe_ratio": 1.0, "total_trades": 4},
        requested_run_id="cycle_parent",
    )

    walk_payload = {
        "results": {
            "rolling": {
                "folds": [
                    {
                        "fold_id": 0,
                        "train_range": [0, 99],
                        "test_range": [100, 149],
                        "train_sharpe": 1.1,
                        "test_sharpe": 0.8,
                        "overfitting_ratio": 1.3,
                    },
                ],
            },
        },
    }

    fold_records = store.save_walk_forward_folds(
        parent_run_id=parent.run_id,
        strategy="ema_cross",
        symbol="BTCUSDT",
        timeframe="1h",
        params={"fast_period": 10, "slow_period": 30},
        walk_forward_payload=walk_payload,
    )
    assert len(fold_records) == 1

    manifest_path = store.tag_run_as_golden(parent.run_id, reason="stable_oos", priority=1, notes="retest engine clean")
    manifest_df = pd.read_csv(manifest_path)
    assert parent.run_id in set(manifest_df["run_id"].astype(str))


def test_result_store_migrate_legacy_store_imports_runs_and_is_idempotent(tmp_path):
    root = tmp_path / "backtest_results"
    runs_dir = root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    canonical_run = runs_dir / "runner_run"
    canonical_run.mkdir()
    (canonical_run / "metadata.json").write_text(
        """
{
  "run_id": "runner_run",
  "created_at": "2026-03-01T00:00:00+00:00",
  "mode": "backtest",
  "status": "ok",
  "strategy": "ema_cross",
  "symbol": "BTCUSDT",
  "timeframe": "1h"
}
""".strip(),
        encoding="utf-8",
    )
    (canonical_run / "metrics.json").write_text(
        '{"total_return_pct": 12.5, "sharpe_ratio": 1.8, "max_drawdown_pct": -4.2, "total_trades": 5}',
        encoding="utf-8",
    )
    (canonical_run / "config_snapshot.json").write_text('{"params": {"fast": 10, "slow": 30}}', encoding="utf-8")
    pd.DataFrame({"equity": [10000.0, 10100.0]}).to_csv(canonical_run / "equity.csv", index=False)
    pd.DataFrame({"pnl": [10.0]}).to_csv(canonical_run / "trades.csv", index=False)
    pd.DataFrame({"returns": [0.0, 0.01]}).to_csv(canonical_run / "returns.csv", index=False)

    legacy_run = root / "legacy_native"
    legacy_run.mkdir()
    (legacy_run / "metadata.json").write_text(
        """
{
  "run_id": "legacy_native",
  "timestamp": "2026-03-02T00:00:00+00:00",
  "strategy": "rsi_reversal",
  "symbol": "ETHUSDT",
  "timeframe": "4h",
  "params": {"period": 14},
  "metrics": {
    "total_return_pct": 3.2,
    "sharpe_ratio": 0.9,
    "max_drawdown_pct": -6.0,
    "total_trades": 2
  },
  "n_bars": 250,
  "n_trades": 2,
  "period_start": "2026-01-01T00:00:00+00:00",
  "period_end": "2026-02-01T00:00:00+00:00",
  "duration_sec": 1.5,
  "mode": "backtest",
  "status": "ok",
  "extra_metadata": {"source": "legacy"}
}
""".strip(),
        encoding="utf-8",
    )
    pd.DataFrame({"equity": [10000.0, 10050.0]}).to_csv(legacy_run / "equity.csv", index=False)
    pd.DataFrame({"pnl": [5.0]}).to_csv(legacy_run / "trades.csv", index=False)

    pd.DataFrame(
        [
            {
                "run_id": "runner_run",
                "mode": "backtest",
                "status": "ok",
                "created_at": "2026-03-01T00:00:00+00:00",
                "strategy": "ema_cross",
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "n_trades": 5,
                "total_return_pct": 12.5,
                "sharpe_ratio": 1.8,
                "parent_run_id": "",
            },
        ],
    ).to_csv(root / "index.csv", index=False)

    (root / "index.json").write_text(
        json.dumps(
            {
                "legacy_native": {
                    "run_id": "legacy_native",
                    "timestamp": "2026-03-02T00:00:00+00:00",
                    "strategy": "rsi_reversal",
                    "symbol": "ETHUSDT",
                    "timeframe": "4h",
                    "params": {"period": 14},
                    "metrics": {
                        "total_return_pct": 3.2,
                        "sharpe_ratio": 0.9,
                        "max_drawdown_pct": -6.0,
                        "total_trades": 2,
                    },
                    "n_bars": 250,
                    "n_trades": 2,
                    "period_start": "2026-01-01T00:00:00+00:00",
                    "period_end": "2026-02-01T00:00:00+00:00",
                    "duration_sec": 1.5,
                    "mode": "backtest",
                    "status": "ok",
                    "extra_metadata": {"source": "legacy"},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    store = ResultStore(root)
    summary = store.migrate_legacy_store()
    assert summary["migrated_runs"] == 2
    assert summary["success_runs"] == 1
    assert summary["partial_runs"] == 1

    df = store.load_index()
    statuses = dict(zip(df["run_id"], df["status"]))
    assert statuses["runner_run"] == "ok"
    assert statuses["legacy_native"] == "partial"

    v3 = BacktestStoreV3(root_dir=root)
    imported = v3.query_runs(limit=0, status=None).set_index("run_id")
    assert imported.loc["runner_run", "params"]["fast"] == 10
    assert imported.loc["legacy_native", "extra"]["missing_artifacts"] == ["returns"]

    second_summary = store.migrate_legacy_store()
    assert second_summary["skipped_existing"] == 2
