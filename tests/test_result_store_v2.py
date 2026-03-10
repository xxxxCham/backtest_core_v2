from __future__ import annotations

import importlib.util
import sys
from types import SimpleNamespace
from pathlib import Path

import pandas as pd

_MODULE_PATH = Path(__file__).resolve().parents[1] / "backtest" / "result_store.py"
_SPEC = importlib.util.spec_from_file_location("backtest_result_store_v2", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
ResultStore = _MODULE.ResultStore


def _sample_run_result():
    index = pd.date_range("2025-01-01", periods=5, freq="h")
    equity = pd.Series([10000.0, 10020.0, 10010.0, 10060.0, 10100.0], index=index, name="equity")
    returns = equity.pct_change().fillna(0.0).rename("returns")
    trades = pd.DataFrame(
        [
            {"entry_time": str(index[1]), "exit_time": str(index[2]), "pnl": 20.0},
            {"entry_time": str(index[3]), "exit_time": str(index[4]), "pnl": 40.0},
        ]
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
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "config_snapshot.json").exists()
    assert (run_dir / "versions.json").exists()
    assert (run_dir / "equity.csv").exists()
    assert (run_dir / "trades.csv").exists()

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
                    }
                ]
            }
        }
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
