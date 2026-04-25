import json
from pathlib import Path

from ui import model_stats_view


def _history_sample():
    return [
        {
            "session_num": 10,
            "session_id": "20260319_100000_builder_a",
            "status": "success",
            "best_return": 12.5,
            "best_sharpe": 1.42,
            "best_trades": 33,
            "duration": 9.1,
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "source_mode": "llm",
            "orchestration_mode": "single_llm",
            "multi_llm_profile": "",
            "multi_llm_builder_model": "lfm2:24b",
            "objective": "Builder A",
        },
        {
            "session_num": 11,
            "session_id": "20260319_101000_builder_b",
            "status": "failed",
            "best_return": -8.0,
            "best_sharpe": -0.5,
            "best_trades": 21,
            "duration": 12.4,
            "symbol": "ETHUSDT",
            "timeframe": "4h",
            "source_mode": "llm",
            "orchestration_mode": "single_llm",
            "multi_llm_profile": "",
            "multi_llm_builder_model": "lfm2:24b",
            "objective": "Builder B",
        },
        {
            "session_num": 12,
            "session_id": "20260319_102000_builder_c",
            "status": "max_iterations",
            "best_return": 4.0,
            "best_sharpe": 0.6,
            "best_trades": 19,
            "duration": 18.0,
            "symbol": "SOLUSDT",
            "timeframe": "30m",
            "source_mode": "fallback",
            "orchestration_mode": "multi_llm",
            "multi_llm_profile": "24GB_curated_2026",
            "multi_llm_builder_model": "qwen3-coder:30b",
            "objective": "Builder C",
        },
    ]


def test_extract_active_entries_respects_last_reset_session_num():
    history = _history_sample()
    state = model_stats_view._default_model_stats_state()
    state["active_window"]["last_reset_session_num"] = 10

    active_entries = model_stats_view._extract_active_entries(history, state)

    assert [entry["session_num"] for entry in active_entries] == [11, 12]


def test_aggregate_model_records_counts_returns_and_statuses():
    history = _history_sample()
    records = model_stats_view.extract_builder_model_records(history)

    rows = model_stats_view.aggregate_model_records(records)

    lfm_row = next(row for row in rows if row["model"] == "lfm2:24b")
    assert lfm_row["sessions"] == 2
    assert lfm_row["positive_returns"] == 1
    assert lfm_row["negative_returns"] == 1
    assert lfm_row["success_status"] == 1
    assert lfm_row["failed_status"] == 1

    qwen_row = next(row for row in rows if row["model"] == "qwen3-coder:30b")
    assert qwen_row["max_iterations_status"] == 1
    assert qwen_row["positive_returns"] == 1
    assert qwen_row["negative_returns"] == 0
    assert lfm_row["negative_rate_pct"] == 50.0
    assert lfm_row["failed_rate_pct"] == 50.0
    assert lfm_row["error_rate_pct"] == 0.0


def test_aggregate_model_records_adds_productivity_metrics_and_sorts_by_profit_per_hour():
    history = _history_sample()
    records = model_stats_view.extract_builder_model_records(history)

    rows = model_stats_view.aggregate_model_records(records)

    assert rows[0]["model"] == "qwen3-coder:30b"
    assert rows[0]["avg_session_duration_s"] == 18.0
    assert rows[0]["sessions_per_hour"] == 200.0
    assert rows[0]["expected_return_per_hour_pct"] == 800.0

    lfm_row = next(row for row in rows if row["model"] == "lfm2:24b")
    assert lfm_row["avg_session_duration_s"] == 10.8
    assert lfm_row["avg_duration_s"] == 10.8
    assert lfm_row["sessions_per_hour"] == 333.333
    assert lfm_row["expected_return_per_hour_pct"] == 375.0


def test_extract_builder_model_records_recovers_duration_from_timestamps():
    history = [
        {
            "session_num": 1,
            "session_id": "timestamped",
            "status": "success",
            "best_return": 3.0,
            "started_at": "2026-04-25T10:00:00",
            "finished_at": "2026-04-25T10:02:00",
            "multi_llm_builder_model": "fast-local",
        },
    ]

    records = model_stats_view.extract_builder_model_records(history)

    assert records[0]["session_duration_seconds"] == 120.0
    assert records[0]["duration"] == 120.0
    assert records[0]["start_time"] == "2026-04-25T10:00:00"
    assert records[0]["end_time"] == "2026-04-25T10:02:00"


def test_extract_builder_model_records_falls_back_to_model_name_for_older_history():
    history = [
        {
            "session_num": 1,
            "session_id": "older",
            "status": "success",
            "best_return": 2.0,
            "duration": 60.0,
            "model_name": "deepseek-moe-16b-local",
        },
    ]

    records = model_stats_view.extract_builder_model_records(history)

    assert records[0]["model"] == "deepseek-moe-16b-local"


def test_reorder_builder_model_frame_prioritizes_requested_percentages():
    frame = model_stats_view.pd.DataFrame(
        [
            {
                "model": "lfm2:24b",
                "sessions": 10,
                "negative_returns": 3,
                "failed_status": 2,
                "success_rate_pct": 40.0,
                "negative_rate_pct": 30.0,
                "failed_rate_pct": 20.0,
                "error_rate_pct": 10.0,
            },
        ],
    )

    reordered = model_stats_view._reorder_builder_model_frame(frame)

    assert list(reordered.columns[:4]) == [
        "model",
        "success_rate_pct",
        "negative_rate_pct",
        "failed_rate_pct",
    ]


def test_reorder_builder_model_frame_prioritizes_productivity_columns():
    frame = model_stats_view.pd.DataFrame(
        [
            {
                "model": "fast-local",
                "sessions": 5,
                "expected_return_per_hour_pct": 420.0,
                "sessions_per_hour": 120.0,
                "avg_session_duration_s": 30.0,
            },
        ],
    )

    reordered = model_stats_view._reorder_builder_model_frame(frame)

    assert "expected_return_per_hour_pct" in list(reordered.columns[:15])
    assert "sessions_per_hour" in list(reordered.columns[:15])
    assert "avg_session_duration_s" in list(reordered.columns[:20])


def test_compact_session_rows_recovers_runtime_error_from_session_summary(tmp_path: Path, monkeypatch):
    sandbox_root = tmp_path / "sandbox_strategies"
    session_dir = sandbox_root / "sess_runtime_error"
    session_dir.mkdir(parents=True)
    (session_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "session_id": session_dir.name,
                "objective": "Builder runtime error",
                "last_runtime_error": "ValueError: persisted runtime",
                "last_runtime_error_iteration": 3,
                "last_runtime_traceback_tail": "Traceback tail persisted",
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(model_stats_view, "SANDBOX_ROOT", sandbox_root)

    rows = model_stats_view._compact_session_rows(
        [
            {
                "session_num": 99,
                "session_id": session_dir.name,
                "status": "failed",
                "objective": "Builder runtime error",
                "multi_llm_builder_model": "lfm2:24b",
            },
        ],
    )

    assert rows[0]["last_runtime_error_iteration"] == 3
    assert rows[0]["last_runtime_error"] == "ValueError: persisted runtime"
    assert rows[0]["last_runtime_traceback_tail"] == "Traceback tail persisted"


def test_compact_session_rows_exposes_best_telemetry_score_alias():
    rows = model_stats_view._compact_session_rows(
        [
            {
                "session_num": 42,
                "session_id": "session_alias",
                "status": "success",
                "best_score": 18.75,
                "multi_llm_builder_model": "qwen3-coder:30b",
            },
        ],
    )

    assert rows[0]["best_telemetry_score"] == 18.75
    assert "best_score" not in rows[0]


def test_archive_active_window_writes_archive_and_updates_baseline(tmp_path: Path):
    history = _history_sample()
    state = model_stats_view._default_model_stats_state()
    state["active_window"]["last_reset_session_num"] = 10
    state_path = tmp_path / "_model_stats_state.json"
    archive_dir = tmp_path / "_model_stats_archives"

    saved_state, archive_meta = model_stats_view.archive_active_window(
        history,
        state=state,
        note="refonte builder",
        state_path=state_path,
        archive_dir=archive_dir,
    )

    assert archive_meta is not None
    assert archive_meta["sessions"] == 2
    assert saved_state["active_window"]["last_reset_session_num"] == 12
    assert saved_state["archives"][0]["id"] == archive_meta["id"]
    assert state_path.exists()

    archive_path = Path(archive_meta["path"])
    if not archive_path.is_absolute():
        archive_path = model_stats_view.ROOT_DIR / archive_path
    assert archive_path.exists()

    archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
    assert archive_payload["note"] == "refonte builder"
    assert len(archive_payload["builder_model_rows"]) == 2


def test_consume_pending_archive_notice_clears_note_before_widget_instantiation(monkeypatch):
    fake_session_state = {
        "builder_model_stats_archive_note": "ancienne note",
        "builder_model_stats_clear_archive_note": True,
        "builder_model_stats_pending_archive_notice": {
            "id": "archive_001",
            "sessions": 3,
        },
    }
    monkeypatch.setattr(model_stats_view.st, "session_state", fake_session_state)

    notice = model_stats_view._consume_pending_archive_notice()

    assert notice == {"id": "archive_001", "sessions": 3}
    assert fake_session_state["builder_model_stats_archive_note"] == ""
    assert "builder_model_stats_clear_archive_note" not in fake_session_state
    assert "builder_model_stats_pending_archive_notice" not in fake_session_state
