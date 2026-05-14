from __future__ import annotations

import json
from types import SimpleNamespace

from tools import keep_awake


class FakeKernel32:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def SetThreadExecutionState(self, flags) -> int:  # noqa: N802
        self.calls.append(int(flags.value))
        return 1


def test_build_awake_flags_defaults_keep_system_and_display_awake() -> None:
    flags = keep_awake.build_awake_flags()

    assert flags & keep_awake.ES_CONTINUOUS
    assert flags & keep_awake.ES_SYSTEM_REQUIRED
    assert flags & keep_awake.ES_DISPLAY_REQUIRED
    assert not flags & keep_awake.ES_AWAYMODE_REQUIRED


def test_pulse_awake_calls_set_thread_execution_state() -> None:
    kernel32 = FakeKernel32()

    flags = keep_awake.pulse_awake(away_mode=True, kernel32=kernel32)

    assert kernel32.calls == [flags]
    assert flags & keep_awake.ES_AWAYMODE_REQUIRED


def test_release_awake_clears_requirements() -> None:
    kernel32 = FakeKernel32()

    keep_awake.release_awake(kernel32=kernel32)

    assert kernel32.calls == [keep_awake.ES_CONTINUOUS]


def test_write_status_adds_runtime_metadata(tmp_path) -> None:
    keep_awake.write_status(tmp_path, {"status": "running", "interval_seconds": 600})

    payload = json.loads((tmp_path / keep_awake.STATUS_FILE_NAME).read_text(encoding="utf-8"))

    assert payload["status"] == "running"
    assert payload["interval_seconds"] == 600
    assert payload["pid"] > 0
    assert payload["updated_at"]


def test_start_background_returns_existing_running_status(monkeypatch, tmp_path) -> None:
    expected = {"running": True, "pid": 1234, "state_dir": str(tmp_path)}
    popen_calls: list[object] = []

    monkeypatch.setattr(keep_awake, "get_keep_awake_status", lambda state_dir: expected)
    monkeypatch.setattr(keep_awake.subprocess, "Popen", lambda *args, **kwargs: popen_calls.append((args, kwargs)))

    status = keep_awake.start_background(state_dir=tmp_path)

    assert status == expected
    assert popen_calls == []


def test_start_background_spawns_module_when_inactive(monkeypatch, tmp_path) -> None:
    statuses = [
        {"running": False, "pid": 0, "state_dir": str(tmp_path)},
        {"running": True, "pid": 5678, "state_dir": str(tmp_path)},
    ]
    popen_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    monkeypatch.setattr(keep_awake, "get_keep_awake_status", lambda state_dir: statuses.pop(0))
    monkeypatch.setattr(
        keep_awake.subprocess,
        "Popen",
        lambda *args, **kwargs: popen_calls.append((args, kwargs)) or SimpleNamespace(pid=1111),
    )

    status = keep_awake.start_background(state_dir=tmp_path, interval_seconds=600)

    assert status["running"] is True
    assert popen_calls
    assert "-m" in popen_calls[0][0][0]
    assert "tools.keep_awake" in popen_calls[0][0][0]


def test_stop_background_requests_graceful_stop(monkeypatch, tmp_path) -> None:
    status = {
        "running": True,
        "pid": 2468,
        "interval_seconds": 600,
        "flags": keep_awake.build_awake_flags(),
        "away_mode": False,
    }
    running_states = [True, False, False]
    terminated: list[int] = []

    monkeypatch.setattr(keep_awake, "get_keep_awake_status", lambda state_dir: status)
    monkeypatch.setattr(keep_awake, "is_pid_running", lambda pid: running_states.pop(0))
    monkeypatch.setattr(keep_awake, "_terminate_pid", lambda pid: terminated.append(pid))

    result = keep_awake.stop_background(state_dir=tmp_path)

    assert result["running"] is True
    assert terminated == []
    assert not (tmp_path / keep_awake.STOP_FILE_NAME).exists()
