from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tools.streamlit_watchdog as watchdog_module
from tools.streamlit_watchdog import (
    decide_exit_restart,
    decide_stall_restart,
    maybe_clear_orphaned_runtime_claim,
)


def _runtime(**overrides):
    payload = {
        "active": True,
        "manual_stop": False,
        "last_heartbeat_at": datetime.now(timezone.utc).isoformat(),
        "last_stop_reason": "",
    }
    payload.update(overrides)
    return payload


def test_stall_restart_when_process_missing_and_runtime_active():
    should_restart, reason = decide_stall_restart(
        _runtime(),
        process_running=False,
    )

    assert should_restart is True
    assert reason == "process_missing_while_runtime_active"


def test_no_stall_restart_when_heartbeat_is_stale():
    stale = (datetime.now(timezone.utc) - timedelta(seconds=181)).isoformat()
    should_restart, reason = decide_stall_restart(
        _runtime(last_heartbeat_at=stale),
        process_running=True,
    )

    assert should_restart is False
    assert reason == ""


def test_no_restart_when_runtime_is_manual_stop():
    should_restart, reason = decide_stall_restart(
        _runtime(active=False, manual_stop=True),
        process_running=False,
    )

    assert should_restart is False
    assert reason == ""


def test_no_stall_restart_for_orphaned_runtime_pid_mismatch():
    stale = (datetime.now(timezone.utc) - timedelta(seconds=181)).isoformat()
    should_restart, reason = decide_stall_restart(
        _runtime(last_heartbeat_at=stale, pid=999),
        process_running=True,
    )

    assert should_restart is False
    assert reason == ""


def test_orphaned_runtime_claim_is_cleared_when_pid_is_missing(monkeypatch):
    stale = (datetime.now(timezone.utc) - timedelta(seconds=181)).isoformat()
    monkeypatch.setattr(watchdog_module, "_pid_exists", lambda pid: False)

    should_clear, reason = maybe_clear_orphaned_runtime_claim(
        _runtime(last_heartbeat_at=stale, pid=424242),
        now=datetime.now(timezone.utc),
        stale_runtime_claim_timeout_sec=120,
    )

    assert should_clear is True
    assert reason.startswith("orphaned_stale_runtime(pid=424242,missing")


def test_exit_restart_when_runtime_still_active():
    should_restart, reason = decide_exit_restart(_runtime(), exit_code=1)

    assert should_restart is True
    assert reason == "runtime_active_after_exit(code=1)"


def test_exit_no_restart_on_manual_stop():
    should_restart, reason = decide_exit_restart(
        _runtime(active=False, manual_stop=True, last_stop_reason="manual_stop"),
        exit_code=0,
    )

    assert should_restart is False
    assert reason == "manual_stop"


def test_resolve_launch_plan_reuses_existing_streamlit_app(monkeypatch):
    monkeypatch.setattr(watchdog_module, "_port_is_available", lambda port: False)
    monkeypatch.setattr(
        watchdog_module,
        "_port_owner_info",
        lambda port: {
            "pid": 4242,
            "name": "python.exe",
            "cmdline": ["python", "-m", "streamlit", "run", "ui/app.py", "--server.port", "8502"],
        },
    )

    action, port, reason = watchdog_module._resolve_launch_plan(
        Path("D:/backtest_core_v2"),
        8502,
    )

    assert action == "reuse"
    assert port == 8502
    assert reason == "already_running(pid=4242)"


def test_resolve_launch_plan_switches_to_next_free_port(monkeypatch):
    monkeypatch.setattr(
        watchdog_module,
        "_port_is_available",
        lambda port: port == 8503,
    )
    monkeypatch.setattr(
        watchdog_module,
        "_port_owner_info",
        lambda port: {
            "pid": 9999,
            "name": "other.exe",
            "cmdline": ["other.exe"],
        },
    )

    action, port, reason = watchdog_module._resolve_launch_plan(
        Path("D:/backtest_core_v2"),
        8502,
    )

    assert action == "launch"
    assert port == 8503
    assert reason == "port_in_use(8502,pid=9999)"


def test_watchdog_script_runs_directly_from_tools_path():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "tools" / "streamlit_watchdog.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Watchdog Streamlit autonome" in result.stdout
