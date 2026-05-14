"""Keep a Windows workstation awake while this process is running."""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_AWAYMODE_REQUIRED = 0x00000040
ES_CONTINUOUS = 0x80000000

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_DIR = PROJECT_ROOT / "runs" / "keep_awake"
PID_FILE_NAME = "keep_awake.pid"
STATUS_FILE_NAME = "keep_awake.json"
LOG_FILE_NAME = "keep_awake.log"
STOP_FILE_NAME = "keep_awake.stop"
DEFAULT_STARTUP_TIMEOUT_SECONDS = 5.0


def build_awake_flags(*, display: bool = True, system: bool = True, away_mode: bool = False) -> int:
    flags = ES_CONTINUOUS
    if system:
        flags |= ES_SYSTEM_REQUIRED
    if display:
        flags |= ES_DISPLAY_REQUIRED
    if away_mode:
        flags |= ES_AWAYMODE_REQUIRED
    return flags


def _load_kernel32() -> Any:
    if os.name != "nt":
        raise RuntimeError("keep_awake only supports Windows SetThreadExecutionState.")
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _set_thread_execution_state(flags: int, *, kernel32: Any | None = None) -> int:
    kernel32 = kernel32 or _load_kernel32()
    set_state = kernel32.SetThreadExecutionState
    try:
        set_state.argtypes = [ctypes.c_uint]
        set_state.restype = ctypes.c_uint
    except AttributeError:
        pass

    previous = int(set_state(ctypes.c_uint(flags)))
    if previous == 0:
        if os.name == "nt":
            raise ctypes.WinError(ctypes.get_last_error())
        raise OSError("SetThreadExecutionState failed.")
    return previous


def pulse_awake(*, display: bool = True, system: bool = True, away_mode: bool = False, kernel32: Any | None = None) -> int:
    flags = build_awake_flags(display=display, system=system, away_mode=away_mode)
    _set_thread_execution_state(flags, kernel32=kernel32)
    return flags


def release_awake(*, kernel32: Any | None = None) -> None:
    _set_thread_execution_state(ES_CONTINUOUS, kernel32=kernel32)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def write_status(state_dir: Path, payload: dict[str, Any]) -> None:
    status_path = state_dir / STATUS_FILE_NAME
    enriched = {
        "version": "1.0",
        "updated_at": _utc_now(),
        "pid": os.getpid(),
        "host": socket.gethostname(),
        **payload,
    }
    _write_text_atomic(status_path, json.dumps(enriched, indent=2, sort_keys=True))


def _write_pid(state_dir: Path) -> None:
    _write_text_atomic(state_dir / PID_FILE_NAME, f"{os.getpid()}\n")


def _remove_stop_request(state_dir: Path) -> None:
    try:
        (state_dir / STOP_FILE_NAME).unlink()
    except FileNotFoundError:
        pass


def _remove_pid(state_dir: Path) -> None:
    try:
        (state_dir / PID_FILE_NAME).unlink()
    except FileNotFoundError:
        pass


def _configure_logging(log_path: Path, level: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run_keep_awake(
    *,
    interval_seconds: int = 600,
    state_dir: Path = DEFAULT_STATE_DIR,
    away_mode: bool = False,
    once: bool = False,
    log_level: str = "INFO",
) -> int:
    interval_seconds = max(int(interval_seconds), 30)
    state_dir = Path(state_dir)
    _configure_logging(state_dir / LOG_FILE_NAME, log_level)
    _remove_stop_request(state_dir)
    _write_pid(state_dir)

    stop_event = threading.Event()

    def _stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except ValueError:
            pass
    if hasattr(signal, "SIGBREAK"):
        try:
            signal.signal(signal.SIGBREAK, _stop)
        except ValueError:
            pass

    logging.info("keep_awake starting interval_seconds=%s away_mode=%s", interval_seconds, away_mode)
    started_at = _utc_now()
    flags = 0
    try:
        flags = pulse_awake(away_mode=away_mode)
        write_status(
            state_dir,
            {
                "status": "running",
                "started_at": started_at,
                "last_pulse_at": _utc_now(),
                "interval_seconds": interval_seconds,
                "flags": flags,
                "away_mode": away_mode,
            },
        )
        if once:
            logging.info("keep_awake one-shot pulse complete")
            return 0

        next_pulse = time.monotonic() + interval_seconds
        while not stop_event.is_set():
            if (state_dir / STOP_FILE_NAME).exists():
                stop_event.set()
                break
            remaining = max(0.0, next_pulse - time.monotonic())
            if remaining <= 0.0:
                pulse_awake(away_mode=away_mode)
                write_status(
                    state_dir,
                    {
                        "status": "running",
                        "started_at": started_at,
                        "last_pulse_at": _utc_now(),
                        "interval_seconds": interval_seconds,
                        "flags": flags,
                        "away_mode": away_mode,
                    },
                )
                logging.info("keep_awake pulse flags=0x%08x", flags)
                next_pulse = time.monotonic() + interval_seconds
                continue
            stop_event.wait(min(remaining, 1.0))
        return 0
    except Exception as exc:
        logging.exception("keep_awake failed")
        write_status(
            state_dir,
            {
                "status": "error",
                "started_at": started_at,
                "stopped_at": _utc_now(),
                "interval_seconds": interval_seconds,
                "flags": flags,
                "away_mode": away_mode,
                "error": str(exc),
            },
        )
        return 1
    finally:
        try:
            release_awake()
        except Exception:
            logging.exception("keep_awake release failed")
        write_status(
            state_dir,
            {
                "status": "stopped" if not stop_event.is_set() else "stopped_by_signal",
                "started_at": started_at,
                "stopped_at": _utc_now(),
                "interval_seconds": interval_seconds,
                "flags": flags,
                "away_mode": away_mode,
            },
        )
        _remove_pid(state_dir)
        _remove_stop_request(state_dir)
        logging.info("keep_awake stopped")


def read_pid(state_dir: Path = DEFAULT_STATE_DIR) -> int:
    pid_path = Path(state_dir) / PID_FILE_NAME
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def read_status(state_dir: Path = DEFAULT_STATE_DIR) -> dict[str, Any]:
    status_path = Path(state_dir) / STATUS_FILE_NAME
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _hidden_creationflags() -> int:
    if os.name != "nt":
        return 0
    return int(
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


def _creationflags_kwargs() -> dict[str, int]:
    flags = _hidden_creationflags()
    return {"creationflags": flags} if flags else {}


def is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                check=False,
                timeout=3,
                **_creationflags_kwargs(),
            )
        except Exception:
            return False
        output = (result.stdout or b"").decode(errors="ignore").strip()
        return str(pid) in output and "No tasks" not in output and "INFO:" not in output
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def get_keep_awake_status(state_dir: Path = DEFAULT_STATE_DIR) -> dict[str, Any]:
    status = read_status(state_dir)
    pid = read_pid(state_dir) or int(status.get("pid", 0) or 0)
    running = is_pid_running(pid)
    return {
        **status,
        "pid": pid if running else 0,
        "running": running,
        "status": "running" if running else str(status.get("status") or "stopped"),
        "state_dir": str(Path(state_dir)),
    }


def _wait_for_running_status(state_dir: Path, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + max(float(timeout_seconds), 0.1)
    while time.monotonic() < deadline:
        status = get_keep_awake_status(state_dir)
        if status.get("running"):
            return status
        time.sleep(0.1)
    return get_keep_awake_status(state_dir)


def start_background(
    *,
    interval_seconds: int = 600,
    state_dir: Path = DEFAULT_STATE_DIR,
    away_mode: bool = False,
    timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    _remove_stop_request(state_dir)

    current = get_keep_awake_status(state_dir)
    if current.get("running"):
        return current

    args = [
        sys.executable,
        "-m",
        "tools.keep_awake",
        "--interval-seconds",
        str(max(int(interval_seconds), 30)),
        "--state-dir",
        str(state_dir),
    ]
    if away_mode:
        args.append("--away-mode")

    subprocess.Popen(
        args,
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **_creationflags_kwargs(),
    )
    return _wait_for_running_status(state_dir, timeout_seconds)


def _terminate_pid(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=5,
            **_creationflags_kwargs(),
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def stop_background(
    *,
    state_dir: Path = DEFAULT_STATE_DIR,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    state_dir = Path(state_dir)
    status = get_keep_awake_status(state_dir)
    pid = int(status.get("pid", 0) or 0)
    if not status.get("running"):
        _remove_pid(state_dir)
        _remove_stop_request(state_dir)
        return get_keep_awake_status(state_dir)

    state_dir.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(state_dir / STOP_FILE_NAME, _utc_now())
    deadline = time.monotonic() + max(float(timeout_seconds), 0.1)
    while time.monotonic() < deadline:
        if not is_pid_running(pid):
            break
        time.sleep(0.1)
    if is_pid_running(pid):
        _terminate_pid(pid)
    _remove_pid(state_dir)
    _remove_stop_request(state_dir)
    write_status(
        state_dir,
        {
            "status": "stopped_by_ui",
            "stopped_at": _utc_now(),
            "interval_seconds": status.get("interval_seconds", 600),
            "flags": status.get("flags", 0),
            "away_mode": bool(status.get("away_mode", False)),
        },
    )
    return get_keep_awake_status(state_dir)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Keep Windows display and system awake.")
    parser.add_argument("--interval-seconds", type=int, default=600)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--away-mode", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return run_keep_awake(
        interval_seconds=args.interval_seconds,
        state_dir=args.state_dir,
        away_mode=args.away_mode,
        once=args.once,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    raise SystemExit(main())
