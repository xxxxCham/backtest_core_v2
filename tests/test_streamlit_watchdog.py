from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tools.autonomous_builder_supervisor as supervisor_module
import tools.streamlit_watchdog as watchdog_module
import tools.supervisor_control_panel as supervisor_panel_module
from tools.streamlit_watchdog import (
    decide_exit_restart,
    decide_stall_restart,
    maybe_clear_orphaned_runtime_claim,
)


def _runtime(**overrides):
    payload = {
        "active": True,
        "manual_stop": False,
        "run_id": "run-1",
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


def test_supervisor_detects_loaded_ollama_model_when_tags_miss(monkeypatch):
    def fake_http_ok(url):
        if url.endswith("/api/tags"):
            return True, 200, json.dumps({"models": []})
        if url.endswith("/api/ps"):
            return True, 200, json.dumps({"models": [{"name": "qwen3.6:35b"}]})
        raise AssertionError(url)

    monkeypatch.setattr(supervisor_module, "_http_ok", fake_http_ok)

    healthy, detail, detected, present_in_tags, loaded_in_ps = supervisor_module.is_ollama_healthy(
        {"ollama_host": "http://127.0.0.1:11434", "ollama_model": "qwen3.6:35b"}
    )

    assert healthy is True
    assert detected is True
    assert present_in_tags is False
    assert loaded_in_ps is True
    assert "model_loaded_in_ps" in detail


def test_supervisor_status_reports_ollama_detection_sources(monkeypatch):
    monkeypatch.setattr(supervisor_module, "load_runtime_state", lambda _config: {})
    monkeypatch.setattr(supervisor_module, "is_streamlit_healthy", lambda _config: (True, "health_status=200"))
    monkeypatch.setattr(
        supervisor_module,
        "is_ollama_healthy",
        lambda _config: (True, "ollama_status=200; model_loaded_in_ps", True, False, True),
    )
    monkeypatch.setattr(supervisor_module, "_port_accepts_connection", lambda _port: True)

    status = supervisor_module.inspect_status(dict(supervisor_module.DEFAULT_CONFIG))

    assert status["ollama_model_detected"] is True
    assert status["ollama_model_present_in_tags"] is False
    assert status["ollama_model_loaded_in_ps"] is True


def test_supervisor_panel_delegates_keep_awake_controls(monkeypatch):
    calls: dict[str, object] = {}

    def fake_start_background(**kwargs):
        calls["start"] = kwargs
        return {"running": True, "pid": 123}

    def fake_stop_background(**kwargs):
        calls["stop"] = kwargs
        return {"running": False, "pid": 0}

    monkeypatch.setattr(supervisor_panel_module.keep_awake, "start_background", fake_start_background)
    monkeypatch.setattr(supervisor_panel_module.keep_awake, "stop_background", fake_stop_background)

    started = supervisor_panel_module.start_panel_keep_awake()
    stopped = supervisor_panel_module.stop_panel_keep_awake()

    assert started == {"running": True, "pid": 123}
    assert stopped == {"running": False, "pid": 0}
    assert calls["start"] == {"interval_seconds": supervisor_panel_module.KEEP_AWAKE_INTERVAL_SECONDS}
    assert calls["stop"] == {}


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


def test_legacy_runtime_claim_is_cleared_when_stale():
    stale = (datetime.now(timezone.utc) - timedelta(seconds=181)).isoformat()

    should_clear, reason = maybe_clear_orphaned_runtime_claim(
        _runtime(last_heartbeat_at=stale, pid=424242, run_id=""),
        now=datetime.now(timezone.utc),
        stale_runtime_claim_timeout_sec=120,
    )

    assert should_clear is True
    assert reason.startswith("legacy_stale_runtime(pid=424242")


def test_external_supervisor_ownerless_runtime_claim_is_cleared_when_stale():
    stale = (datetime.now(timezone.utc) - timedelta(seconds=181)).isoformat()

    should_clear, reason = maybe_clear_orphaned_runtime_claim(
        _runtime(
            last_heartbeat_at=stale,
            pid=0,
            owner_pid=0,
            claim_source="external_supervisor",
        ),
        now=datetime.now(timezone.utc),
        stale_runtime_claim_timeout_sec=120,
    )

    assert should_clear is True
    assert reason.startswith("external_supervisor_stale_runtime(ownerless")


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


def test_resolve_launch_plan_reuses_same_streamlit_app_when_healthy(monkeypatch):
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
    monkeypatch.setattr(
        watchdog_module,
        "_http_probe_streamlit",
        lambda port: (True, "http_200:/_stcore/health"),
    )

    action, port, reason = watchdog_module._resolve_launch_plan(
        Path("D:/backtest_core_v2"),
        8502,
    )

    assert action == "reuse"
    assert port == 8502
    assert reason == "same_app_running(8502,pid=4242,health=http_200:/_stcore/health)"


def test_resolve_launch_plan_does_not_spawn_next_port_when_same_streamlit_app_already_owns_requested_port(
    monkeypatch,
):
    monkeypatch.setattr(
        watchdog_module,
        "_port_is_available",
        lambda port: port == 8503,
    )
    monkeypatch.setattr(
        watchdog_module,
        "_port_owner_info",
        lambda port: {
            "pid": 20664,
            "name": "python.exe",
            "cmdline": [
                "python",
                "-m",
                "streamlit",
                "run",
                "ui/app.py",
                "--server.port",
                "8502",
            ],
        },
    )
    monkeypatch.setattr(
        watchdog_module,
        "_http_probe_streamlit",
        lambda port: (True, "http_200:/_stcore/health"),
    )

    action, port, reason = watchdog_module._resolve_launch_plan(
        Path("D:/backtest_core_v2"),
        8502,
    )

    assert action == "reuse"
    assert port == 8502
    assert reason == "same_app_running(8502,pid=20664,health=http_200:/_stcore/health)"


def test_resolve_launch_plan_replaces_same_streamlit_app_when_unhealthy(monkeypatch):
    monkeypatch.setattr(watchdog_module, "_port_is_available", lambda port: False)
    monkeypatch.setattr(
        watchdog_module,
        "_port_owner_info",
        lambda port: {
            "pid": 20664,
            "name": "python.exe",
            "cmdline": ["python", "-m", "streamlit", "run", "ui/app.py", "--server.port", "8502"],
        },
    )
    monkeypatch.setattr(
        watchdog_module,
        "_http_probe_streamlit",
        lambda port: (False, "TimeoutError:/_stcore/health"),
    )

    action, port, reason = watchdog_module._resolve_launch_plan(
        Path("D:/backtest_core_v2"),
        8502,
    )

    assert action == "replace"
    assert port == 8502
    assert reason == "same_app_unhealthy(pid=20664,health=TimeoutError:/_stcore/health)"


def test_resolve_launch_plan_replaces_same_streamlit_app_when_runtime_claim_is_stale(monkeypatch):
    now = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    stale = (now - timedelta(seconds=181)).isoformat()
    monkeypatch.setattr(watchdog_module, "_port_is_available", lambda port: False)
    monkeypatch.setattr(
        watchdog_module,
        "_port_owner_info",
        lambda port: {
            "pid": 20664,
            "name": "python.exe",
            "cmdline": ["python", "-m", "streamlit", "run", "ui/app.py", "--server.port", "8502"],
        },
    )
    monkeypatch.setattr(
        watchdog_module,
        "_http_probe_streamlit",
        lambda port: (True, "http_200:/_stcore/health"),
    )

    action, port, reason = watchdog_module._resolve_launch_plan(
        Path("D:/backtest_core_v2"),
        8502,
        runtime=_runtime(last_heartbeat_at=stale, pid=20664),
        stale_runtime_claim_timeout_sec=120,
        now=now,
    )

    assert action == "replace"
    assert port == 8502
    assert reason == "runtime_heartbeat_stale(age=181s)"


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


def test_resolve_launch_plan_skips_multiple_busy_ports_until_next_free_port(monkeypatch):
    monkeypatch.setattr(
        watchdog_module,
        "_port_is_available",
        lambda port: port == 8504,
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
    assert port == 8504
    assert reason == "port_in_use(8502,pid=9999)"


def test_port_is_available_returns_false_when_port_accepts_connection(monkeypatch):
    monkeypatch.setattr(watchdog_module, "_port_owner_info", lambda port: {})
    monkeypatch.setattr(watchdog_module, "_port_accepts_connection", lambda port: True)

    assert watchdog_module._port_is_available(8502) is False


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


def test_launch_streamlit_forces_headless_and_disables_browser_stats(monkeypatch, tmp_path):
    calls = []

    class _DummyProcess:
        def poll(self):
            return None

    def _fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        return _DummyProcess()

    monkeypatch.setattr(watchdog_module.subprocess, "Popen", _fake_popen)

    watchdog_module._launch_streamlit(tmp_path, 8502)

    assert calls
    command = list(calls[0][0][0])
    assert "--server.headless" in command
    assert command[command.index("--server.headless") + 1] == "true"
    assert "--browser.gatherUsageStats" in command
    assert command[command.index("--browser.gatherUsageStats") + 1] == "false"


def test_open_browser_once_when_streamlit_is_ready_opens_localhost_url(monkeypatch):
    calls = []

    class _DummyProcess:
        def poll(self):
            return None

    monkeypatch.setattr(
        watchdog_module,
        "_http_probe_streamlit",
        lambda port, timeout_sec=0.5: (True, "http_200:/_stcore/health"),
    )
    monkeypatch.setattr(
        watchdog_module,
        "_open_streamlit_browser",
        lambda port: calls.append(port) or True,
    )

    opened = watchdog_module._open_browser_once_when_streamlit_is_ready(_DummyProcess(), 8502)

    assert opened is True
    assert calls == [8502]


def test_open_streamlit_browser_skips_non_interactive_windows_session(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(watchdog_module.os, "name", "nt")
    monkeypatch.setattr(watchdog_module, "_is_interactive_desktop_session", lambda: False)
    monkeypatch.setattr(watchdog_module, "_current_windows_session_id", lambda: 0)
    monkeypatch.setattr(watchdog_module.os, "startfile", lambda url: calls.append(url), raising=False)

    opened = watchdog_module._open_streamlit_browser(8502)

    assert opened is False
    assert calls == []
    assert "non-interactive Windows session" in capsys.readouterr().out


def test_open_browser_once_when_streamlit_is_ready_skips_when_process_exits(monkeypatch):
    class _ExitedProcess:
        def poll(self):
            return 1

    monkeypatch.setattr(
        watchdog_module,
        "_http_probe_streamlit",
        lambda port, timeout_sec=0.5: (False, "TimeoutError:/_stcore/health"),
    )

    opened = watchdog_module._open_browser_once_when_streamlit_is_ready(
        _ExitedProcess(),
        8502,
        startup_timeout_sec=1.0,
        poll_interval_sec=0.1,
    )

    assert opened is False


def test_main_does_not_launch_supervisor_loop_by_default(monkeypatch, tmp_path, capsys):
    calls = {"supervisor_loop": 0}
    monkeypatch.delenv("BACKTEST_STREAMLIT_LAUNCH_SUPERVISOR_LOOP", raising=False)
    monkeypatch.setattr(
        watchdog_module,
        "_launch_supervisor_loop",
        lambda root: calls.__setitem__("supervisor_loop", 1),
    )
    monkeypatch.setattr(
        watchdog_module,
        "_load_runtime_state",
        lambda path: _runtime(active=False),
    )
    monkeypatch.setattr(
        watchdog_module,
        "_resolve_launch_plan",
        lambda root, requested_port, **kwargs: ("reuse", requested_port, "same_app_running(8502,pid=1,health=test)"),
    )

    result = watchdog_module.main(
        [
            "--port",
            "8502",
            "--runtime-state",
            str(tmp_path / "_autonomous_runtime_state.json"),
        ],
    )

    assert result == 0
    assert calls["supervisor_loop"] == 0
    assert "supervisor loop disabled" in capsys.readouterr().out


def test_main_launches_supervisor_loop_only_when_requested(monkeypatch, tmp_path):
    calls = {"supervisor_loop": 0}

    def _mark_supervisor_loop_launched(root):
        calls["supervisor_loop"] += 1
        return True

    monkeypatch.setattr(
        watchdog_module,
        "_launch_supervisor_loop",
        _mark_supervisor_loop_launched,
    )
    monkeypatch.setattr(
        watchdog_module,
        "_load_runtime_state",
        lambda path: _runtime(active=False),
    )
    monkeypatch.setattr(
        watchdog_module,
        "_resolve_launch_plan",
        lambda root, requested_port, **kwargs: ("reuse", requested_port, "same_app_running(8502,pid=1,health=test)"),
    )

    result = watchdog_module.main(
        [
            "--port",
            "8502",
            "--runtime-state",
            str(tmp_path / "_autonomous_runtime_state.json"),
            "--launch-supervisor-loop",
        ],
    )

    assert result == 0
    assert calls["supervisor_loop"] == 1


def test_external_supervisor_defaults_do_not_auto_open_manual_streamlit_sessions():
    defaults = supervisor_module.DEFAULT_CONFIG

    assert defaults["streamlit_port"] == 8502
    assert defaults["auto_arm_when_inactive"] is False
    assert defaults["respect_manual_stop"] is True
    assert defaults["launch_streamlit_if_down"] is False
    assert defaults["open_browser_on_launch"] is False


def test_launch_supervisor_loop_starts_hidden_runner_on_windows(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    runner = repo_root / "tools" / "run_autonomous_builder_supervisor_loop.ps1"
    runner.parent.mkdir(parents=True)
    runner.write_text("Write-Host test\n", encoding="utf-8")
    popen_calls = []

    monkeypatch.setattr(watchdog_module.os, "name", "nt")
    monkeypatch.setattr(
        watchdog_module.subprocess,
        "Popen",
        lambda *args, **kwargs: popen_calls.append((args, kwargs)),
    )

    assert watchdog_module._launch_supervisor_loop(repo_root) is True
    assert popen_calls
    command = list(popen_calls[0][0][0])
    assert command[:2] == ["powershell.exe", "-NoProfile"]
    assert str(runner) in command


def test_save_runtime_state_retries_transient_permission_error(monkeypatch, tmp_path):
    runtime_state_path = tmp_path / "_autonomous_runtime_state.json"
    original_write_text = Path.write_text
    attempts = {"count": 0}

    def flaky_write_text(self, data, *args, **kwargs):
        if self.parent == runtime_state_path.parent and self.name.endswith(".tmp"):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise PermissionError(13, "Permission denied", str(self))
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", flaky_write_text)

    watchdog_module._save_runtime_state(
        runtime_state_path,
        _runtime(active=False, manual_stop=False, pid=0),
    )

    payload = watchdog_module._load_runtime_state(runtime_state_path)
    assert payload["active"] is False
    assert attempts["count"] == 2
