from __future__ import annotations

from types import SimpleNamespace

import catalog.strategy_catalog as strategy_catalog_module
from catalog.strategy_catalog import (
    build_entry_id,
    compute_params_hash,
    list_entries,
    move_entries,
    prepare_saved_run_entry,
    read_catalog,
    upsert_entries,
    upsert_entry,
    upsert_from_builder_session,
    upsert_from_saved_run,
    upsert_from_saved_runs,
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

    moved = move_entries([entry_id], "p3_benchmark_consensus", path=path)
    assert moved == 1
    entries = list_entries(path=path, categories=["p3_benchmark_consensus"])
    assert len(entries) == 1


def test_upsert_entry_normalizes_and_deduplicates_tags(tmp_path):
    path = tmp_path / "strategy_catalog.json"
    entry = {
        "strategy_name": "ema_cross",
        "symbol": "BTCUSDC",
        "timeframe": "1h",
        "params_hash": compute_params_hash({"fast": 10}),
        "tags": [" builder_out ", "builder_out", " review "],
    }

    saved = upsert_entry(entry, path=path)

    assert saved["tags"] == ["builder_out", "review"]


def test_upsert_entries_batches_updates_without_duplicates(tmp_path):
    path = tmp_path / "strategy_catalog.json"
    params_hash_a = compute_params_hash({"fast": 10})
    params_hash_b = compute_params_hash({"fast": 20})
    entry_a = {
        "id": build_entry_id("ema_cross", "BTCUSDC", "1h", params_hash_a),
        "strategy_name": "ema_cross",
        "symbol": "BTCUSDC",
        "timeframe": "1h",
        "params_hash": params_hash_a,
        "category": "p1_builder_inbox",
        "status": "active",
        "tags": ["batch"],
    }
    entry_b = {
        "id": build_entry_id("ema_cross", "ETHUSDC", "4h", params_hash_b),
        "strategy_name": "ema_cross",
        "symbol": "ETHUSDC",
        "timeframe": "4h",
        "params_hash": params_hash_b,
        "category": "p2_positive_observed",
        "status": "active",
        "tags": ["batch"],
    }

    saved = upsert_entries([entry_a, entry_b], path=path)

    assert len(saved) == 2
    assert len(read_catalog(path=path)["entries"]) == 2

    updated = upsert_entries(
        [
            {
                **entry_a,
                "category": "p3_benchmark_consensus",
                "tags": ["batch", "updated"],
            },
        ],
        path=path,
    )

    catalog = read_catalog(path=path)
    assert len(updated) == 1
    assert len(catalog["entries"]) == 2
    assert list_entries(path=path, categories=["p3_benchmark_consensus"])[0]["id"] == entry_a["id"]


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
            "universe_mode": "canonical",
            "universe_purpose": "builder_autonomous",
        },
    }

    entry = upsert_from_saved_run(saved_run, path=path)

    assert entry["category"] == "p3_benchmark_consensus"
    assert entry["status"] == "active"
    assert entry["params_hash"] != "none"
    assert "promoted_run" in entry["tags"]
    assert "replay_candidate" in entry["tags"]
    assert entry["meta"]["source_run_id"] == "run_001"
    assert entry["meta"]["builder_session_id"] == "sess-123"
    assert entry["meta"]["builder_iteration"] == 4
    assert entry["meta"]["universe_mode"] == "canonical"
    assert "universe_canonical" in entry["tags"]


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

    entry = upsert_from_saved_run(saved_run, target_category="p3_benchmark_consensus", path=path)
    moved = move_entries([entry["id"]], "p6_paper_candidate", path=path)
    assert moved == 1

    updated = upsert_from_saved_run(saved_run, target_category="p3_benchmark_consensus", path=path)
    assert updated["category"] == "p6_paper_candidate"


def test_prepare_saved_run_entry_merges_existing_catalog_state(tmp_path):
    path = tmp_path / "strategy_catalog.json"
    saved_run = {
        "run_id": "run_merge",
        "strategy": "ema_cross",
        "symbol": "BTCUSDC",
        "timeframe": "1h",
        "status": "ok",
        "params": {"fast_period": 10, "slow_period": 30},
    }

    existing = upsert_from_saved_run(saved_run, target_category="p6_paper_candidate", path=path)
    existing["note"] = "garder cette note"
    existing["tags"] = [*existing.get("tags", []), "manual_review"]

    prepared = prepare_saved_run_entry(
        saved_run,
        target_category="p3_benchmark_consensus",
        existing_entry=existing,
    )

    assert prepared["category"] == "p6_paper_candidate"
    assert prepared["note"] == "garder cette note"
    assert "manual_review" in prepared["tags"]


def test_upsert_from_saved_runs_batches_single_catalog_write(tmp_path, monkeypatch):
    path = tmp_path / "strategy_catalog.json"
    write_calls: list[int] = []
    original_write_catalog = strategy_catalog_module.write_catalog

    def _tracked_write(payload, path=None):
        write_calls.append(1)
        return original_write_catalog(payload, path=path)

    monkeypatch.setattr(strategy_catalog_module, "write_catalog", _tracked_write)

    saved_runs = [
        {
            "run_id": "run_batch_a",
            "strategy": "ema_cross",
            "symbol": "BTCUSDC",
            "timeframe": "1h",
            "status": "ok",
            "params": {"fast_period": 10, "slow_period": 30},
        },
        {
            "run_id": "run_batch_b",
            "strategy": "ema_cross",
            "symbol": "ETHUSDC",
            "timeframe": "4h",
            "status": "ok",
            "params": {"fast_period": 12, "slow_period": 50},
        },
    ]

    entries = upsert_from_saved_runs(saved_runs, path=path)

    assert len(entries) == 2
    assert len(write_calls) == 1
    assert len(read_catalog(path=path)["entries"]) == 2


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
    best_iteration = SimpleNamespace(iteration=1, backtest_result=best_result, phase_feedback={})
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
        universe_mode="exploratory",
        universe_purpose="builder_manual",
        universe_strategy_type="momentum",
    )

    entry = upsert_from_builder_session(session, path=path)
    catalog = read_catalog(path=path)

    assert entry["params_hash"] != "none"
    assert entry["meta"]["builder_iteration"] == 1
    assert len(catalog["entries"]) == 1
    assert catalog["entries"][0]["category"] == "p2_positive_observed"
    assert catalog["entries"][0]["meta"]["session_positive_iteration_count"] == 1
    assert entry["meta"]["universe_mode"] == "exploratory"
    assert entry["meta"]["universe_strategy_type"] == "momentum"
    assert "universe_exploratory" in entry["tags"]


def test_upsert_from_builder_session_keeps_all_positive_iterations(tmp_path):
    path = tmp_path / "strategy_catalog.json"
    negative = SimpleNamespace(
        iteration=1,
        backtest_result=SimpleNamespace(
            metrics={"total_return_pct": -3.0, "sharpe_ratio": -0.2, "total_trades": 8},
            meta={"params": {"fast_period": 8}},
        ),
        phase_feedback={},
    )
    positive_a = SimpleNamespace(
        iteration=2,
        backtest_result=SimpleNamespace(
            metrics={
                "total_return_pct": 4.2,
                "sharpe_ratio": 0.6,
                "profit_factor": 1.08,
                "total_trades": 18,
            },
            meta={"params": {"fast_period": 12, "slow_period": 26}},
        ),
        phase_feedback={},
    )
    positive_b = SimpleNamespace(
        iteration=3,
        backtest_result=SimpleNamespace(
            metrics={
                "total_return_pct": 11.5,
                "sharpe_ratio": 1.1,
                "profit_factor": 1.25,
                "total_trades": 26,
            },
            meta={"params": {"fast_period": 15, "slow_period": 50}},
        ),
        phase_feedback={},
    )
    session = SimpleNamespace(
        session_id="session-multi",
        symbol="ETHUSDC",
        timeframe="4h",
        status="success",
        best_iteration=positive_b,
        target_sharpe=1.0,
        objective="Conserver toutes les variantes positives",
        best_sharpe=1.1,
        iterations=[negative, positive_a, positive_b],
        universe_mode="canonical",
        universe_purpose="builder_manual",
        universe_strategy_type="trend",
    )

    primary_entry = upsert_from_builder_session(session, path=path)
    entries = list_entries(path=path, status=None)

    assert primary_entry["meta"]["builder_iteration"] == 3
    assert len(entries) == 2
    by_iteration = {entry["meta"]["builder_iteration"]: entry for entry in entries}
    assert sorted(by_iteration.keys()) == [2, 3]
    assert all(entry["category"] == "p2_positive_observed" for entry in entries)
    assert by_iteration[2]["last_metrics_snapshot"]["total_return_pct"] == 4.2
    assert by_iteration[3]["last_metrics_snapshot"]["total_return_pct"] == 11.5
    assert all("positive_return" in entry["tags"] for entry in entries)


def test_upsert_from_builder_session_batches_single_catalog_write(tmp_path, monkeypatch):
    path = tmp_path / "strategy_catalog.json"
    write_calls: list[int] = []
    original_write_catalog = strategy_catalog_module.write_catalog

    def _tracked_write(payload, path=None):
        write_calls.append(1)
        return original_write_catalog(payload, path=path)

    monkeypatch.setattr(strategy_catalog_module, "write_catalog", _tracked_write)

    positive_a = SimpleNamespace(
        iteration=2,
        backtest_result=SimpleNamespace(
            metrics={
                "total_return_pct": 4.2,
                "sharpe_ratio": 0.6,
                "profit_factor": 1.08,
                "total_trades": 18,
            },
            meta={"params": {"fast_period": 12, "slow_period": 26}},
        ),
        phase_feedback={},
    )
    positive_b = SimpleNamespace(
        iteration=3,
        backtest_result=SimpleNamespace(
            metrics={
                "total_return_pct": 11.5,
                "sharpe_ratio": 1.1,
                "profit_factor": 1.25,
                "total_trades": 26,
            },
            meta={"params": {"fast_period": 15, "slow_period": 50}},
        ),
        phase_feedback={},
    )
    session = SimpleNamespace(
        session_id="session-batch",
        symbol="ETHUSDC",
        timeframe="4h",
        status="success",
        best_iteration=positive_b,
        target_sharpe=1.0,
        objective="Conserver toutes les variantes positives",
        best_sharpe=1.1,
        iterations=[positive_a, positive_b],
        universe_mode="canonical",
        universe_purpose="builder_manual",
        universe_strategy_type="trend",
    )

    upsert_from_builder_session(session, path=path)

    assert len(write_calls) == 1
    assert len(read_catalog(path=path)["entries"]) == 2
