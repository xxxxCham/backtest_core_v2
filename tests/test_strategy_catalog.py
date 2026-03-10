from __future__ import annotations

from types import SimpleNamespace

from catalog.strategy_catalog import (
    build_entry_id,
    compute_params_hash,
    list_entries,
    move_entries,
    read_catalog,
    upsert_entry,
    upsert_from_builder_session,
    upsert_from_saved_run,
    write_catalog,
)


def test_catalog_roundtrip(tmp_path):
    path = tmp_path / "strategy_catalog.json"
    payload = {"schema_version": 1, "entries": []}
    write_catalog(payload, path=path)
    loaded = read_catalog(path=path)
    assert loaded["schema_version"] == 1
    assert loaded["entries"] == []


def test_upsert_and_filters(tmp_path):
    path = tmp_path / "strategy_catalog.json"
    params_hash = compute_params_hash({"fast": 10})
    entry_id = build_entry_id("ema_cross", "BTCUSDC", "1h", params_hash)
    entry = {
        "id": entry_id,
        "strategy_name": "ema_cross",
        "symbol": "BTCUSDC",
        "timeframe": "1h",
        "params_hash": params_hash,
        "category": "p1_builder_inbox",
        "status": "active",
        "tags": ["builder_out"],
    }
    upsert_entry(entry, path=path)

    entries = list_entries(path=path, categories=["p1_builder_inbox"])
    assert len(entries) == 1
    assert entries[0]["id"] == entry_id

    moved = move_entries([entry_id], "p3_watchlist", path=path)
    assert moved == 1
    entries = list_entries(path=path, categories=["p3_watchlist"])
    assert len(entries) == 1


def test_upsert_from_saved_run_promotes_to_catalog(tmp_path):
    path = tmp_path / "strategy_catalog.json"
    saved_run = {
        "artifact_type": "saved_run",
        "schema": "native_saved_run",
        "run_id": "run_001",
        "path": "run_001",
        "mode": "backtest",
        "status": "ok",
        "strategy": "ema_cross",
        "symbol": "BTCUSDC",
        "timeframe": "1h",
        "loadable": True,
        "params": {"fast_period": 10, "slow_period": 30},
        "metrics": {
            "total_return_pct": 12.5,
            "sharpe_ratio": 1.7,
            "profit_factor": 1.2,
            "total_trades": 42,
        },
        "extra_metadata": {
            "origin": "builder",
            "builder_session_id": "sess-123",
            "builder_iteration": 4,
        },
    }

    entry = upsert_from_saved_run(saved_run, path=path)

    assert entry["category"] == "p3_watchlist"
    assert entry["status"] == "active"
    assert entry["params_hash"] != "none"
    assert "promoted_run" in entry["tags"]
    assert "replay_candidate" in entry["tags"]
    assert entry["meta"]["source_run_id"] == "run_001"
    assert entry["meta"]["builder_session_id"] == "sess-123"
    assert entry["meta"]["builder_iteration"] == 4


def test_upsert_from_saved_run_rejects_partial_status(tmp_path):
    path = tmp_path / "strategy_catalog.json"
    saved_run = {
        "run_id": "run_partial",
        "strategy": "ema_cross",
        "symbol": "BTCUSDC",
        "timeframe": "1h",
        "status": "partial",
        "params": {"fast_period": 10},
    }

    try:
        upsert_from_saved_run(saved_run, path=path)
    except ValueError as exc:
        assert "Incomplete run cannot be promoted" in str(exc)
    else:
        raise AssertionError("partial run should not be promoted")


def test_upsert_from_saved_run_preserves_higher_existing_category(tmp_path):
    path = tmp_path / "strategy_catalog.json"
    saved_run = {
        "run_id": "run_002",
        "strategy": "ema_cross",
        "symbol": "BTCUSDC",
        "timeframe": "1h",
        "status": "ok",
        "params": {"fast_period": 10, "slow_period": 30},
    }

    entry = upsert_from_saved_run(saved_run, target_category="p3_watchlist", path=path)
    moved = move_entries([entry["id"]], "p4_paper_candidate", path=path)
    assert moved == 1

    updated = upsert_from_saved_run(saved_run, target_category="p3_watchlist", path=path)
    assert updated["category"] == "p4_paper_candidate"


def test_upsert_from_builder_session_falls_back_to_session_hash(tmp_path):
    path = tmp_path / "strategy_catalog.json"
    metrics = {
        "sharpe_ratio": 1.5,
        "total_return_pct": 9.0,
        "total_trades": 36,
        "profit_factor": 1.15,
        "max_drawdown_pct": -12.0,
    }
    best_result = SimpleNamespace(metrics=metrics, meta={})
    best_iteration = SimpleNamespace(backtest_result=best_result)
    session = SimpleNamespace(
        session_id="session-abc",
        symbol="BTCUSDC",
        timeframe="1h",
        status="max_iterations",
        best_iteration=best_iteration,
        target_sharpe=1.0,
        objective="Replay candidate",
        best_sharpe=1.5,
        iterations=[best_iteration],
    )

    entry = upsert_from_builder_session(session, path=path)

    assert entry["params_hash"] != "none"
    assert entry["id"].endswith(entry["params_hash"])
