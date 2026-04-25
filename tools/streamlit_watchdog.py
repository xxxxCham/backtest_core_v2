"""Watchdog léger pour Streamlit.

Relance automatiquement l'application quand le runtime autonome Builder
indique qu'il doit continuer mais que le process est réellement tombé
ou s'est fermé.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.result_store import get_builder_sessions_dir

try:
    import psutil

    _HAS_PSUTIL = True
except Exception:
    psutil = None
    _HAS_PSUTIL = False


_RUNTIME_STATE_LOCK = threading.Lock()
_RUNTIME_STATE_SAVE_RETRIES = 3
_RUNTIME_STATE_SAVE_RETRY_DELAY_SEC = 0.2


def _parse_runtime_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_runtime_state(path: Path) -> dict[str, Any]:
    default = {
        "active": False,
        "manual_stop": False,
        "last_heartbeat_at": "",
        "last_stop_reason": "",
        "last_error": "",
        "last_session_num": 0,
        "last_session_status": "",
    }
    if not path.exists():
        return default
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    if isinstance(raw, dict) and isinstance(raw.get("runtime"), dict):
        raw = raw["runtime"]
    if not isinstance(raw, dict):
        return default
    merged = dict(default)
    merged.update(raw)
    return merged


def _save_runtime_state(path: Path, runtime: dict[str, Any]) -> None:
    payload = {
        "version": "1.0",
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "runtime": dict(runtime),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    last_exc: BaseException | None = None

    with _RUNTIME_STATE_LOCK:
        for attempt in range(_RUNTIME_STATE_SAVE_RETRIES):
            tmp_path = _build_unique_runtime_tmp_path(path)
            try:
                tmp_path.write_text(serialized, encoding="utf-8")
                os.replace(tmp_path, path)
                return
            except Exception as exc:
                last_exc = exc
                _cleanup_runtime_tmp_file(tmp_path)
                should_retry = attempt < (_RUNTIME_STATE_SAVE_RETRIES - 1) and _is_transient_runtime_save_error(exc)
                if should_retry:
                    time.sleep(_RUNTIME_STATE_SAVE_RETRY_DELAY_SEC * (attempt + 1))
                    continue
                break

    if last_exc is not None:
        raise last_exc


def _is_transient_runtime_save_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, "winerror", None)
    errno = getattr(exc, "errno", None)
    return winerror == 32 or errno in {13, 32}


def _cleanup_runtime_tmp_file(tmp_path: Path) -> None:
    try:
        if tmp_path.exists():
            tmp_path.unlink()
    except Exception:
        pass


def _build_unique_runtime_tmp_path(target_path: Path) -> Path:
    suffix = f".{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    return target_path.with_name(f"{target_path.name}{suffix}")


def _runtime_requests_restart(runtime: dict[str, Any]) -> bool:
    return bool(runtime.get("active")) and not bool(runtime.get("manual_stop"))


def _runtime_pid(runtime: dict[str, Any]) -> int:
    try:
        return int(runtime.get("pid", 0) or 0)
    except Exception:
        return 0


def _pid_exists(pid: int) -> bool | None:
    if pid <= 0:
        return None
    if not _HAS_PSUTIL:
        return None
    try:
        return bool(psutil.pid_exists(pid))
    except Exception:
        return None


def _clear_stale_runtime_claim(
    path: Path,
    runtime: dict[str, Any],
    *,
    reason: str,
    now: datetime,
) -> dict[str, Any]:
    cleaned = dict(runtime)
    cleaned["active"] = False
    cleaned["manual_stop"] = False
    cleaned["last_heartbeat_at"] = now.replace(microsecond=0).isoformat()
    cleaned["last_event"] = "watchdog_cleared_stale_runtime"
    cleaned["last_stop_reason"] = str(reason or "")
    cleaned["last_error"] = ""
    cleaned["pid"] = 0
    cleaned["process_rss_mb"] = 0.0
    try:
        _save_runtime_state(path, cleaned)
    except Exception as exc:
        print(
            f"[watchdog] warning: unable to persist cleared runtime claim ({exc})",
            flush=True,
        )
    return cleaned


def maybe_clear_orphaned_runtime_claim(
    runtime: dict[str, Any],
    *,
    now: datetime,
    stale_runtime_claim_timeout_sec: int,
) -> tuple[bool, str]:
    if not _runtime_requests_restart(runtime):
        return False, ""

    heartbeat_at = _parse_runtime_timestamp(runtime.get("last_heartbeat_at"))
    if heartbeat_at is None:
        return False, ""

    heartbeat_age = (now - heartbeat_at).total_seconds()
    if heartbeat_age <= float(stale_runtime_claim_timeout_sec):
        return False, ""

    runtime_pid = _runtime_pid(runtime)
    if runtime_pid <= 0:
        return False, ""

    pid_exists = _pid_exists(runtime_pid)
    if pid_exists is False:
        return True, f"orphaned_stale_runtime(pid={runtime_pid},missing,age={heartbeat_age:.0f}s)"
    return False, ""


def decide_stall_restart(
    runtime: dict[str, Any],
    *,
    process_running: bool,
) -> tuple[bool, str]:
    if not _runtime_requests_restart(runtime):
        return False, ""
    if not process_running:
        return True, "process_missing_while_runtime_active"
    return False, ""


def decide_exit_restart(runtime: dict[str, Any], exit_code: int | None) -> tuple[bool, str]:
    if _runtime_requests_restart(runtime):
        return True, f"runtime_active_after_exit(code={exit_code})"
    if bool(runtime.get("manual_stop")):
        return False, "manual_stop"
    if str(runtime.get("last_stop_reason", "") or "").strip().lower() == "manual_stop":
        return False, "manual_stop"
    return False, f"streamlit_exit(code={exit_code})"


def _terminate_process(proc: subprocess.Popen[Any], *, timeout_sec: float = 15.0) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=timeout_sec)
        return
    except Exception:
        pass
    try:
        proc.kill()
        proc.wait(timeout=5.0)
    except Exception:
        pass


def _port_is_available(port: int, *, host: str = "127.0.0.1") -> bool:
    owner = _port_owner_info(port)
    if owner:
        return False
    if _port_accepts_connection(port):
        return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, int(port)))
            return True
    except OSError:
        return False


def _port_accepts_connection(port: int) -> bool:
    loopback_targets = (
        (socket.AF_INET, ("127.0.0.1", int(port))),
        (socket.AF_INET6, ("::1", int(port), 0, 0)),
    )
    for family, address in loopback_targets:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.2)
                if sock.connect_ex(address) == 0:
                    return True
        except OSError:
            continue
    return False


def _port_owner_info(port: int) -> dict[str, Any]:
    if not _HAS_PSUTIL:
        return {}
    try:
        for conn in psutil.net_connections(kind="inet"):
            laddr = getattr(conn, "laddr", None)
            if not laddr or getattr(laddr, "port", None) != int(port):
                continue
            pid = int(getattr(conn, "pid", 0) or 0)
            if pid <= 0:
                return {}
            proc = psutil.Process(pid)
            return {
                "pid": pid,
                "name": str(proc.name() or ""),
                "cmdline": list(proc.cmdline() or []),
            }
    except Exception:
        return {}
    return {}


def _is_same_streamlit_app_owner(owner: dict[str, Any], root: Path) -> bool:
    if not owner:
        return False
    cmdline = " ".join(str(part or "") for part in owner.get("cmdline", []))
    lowered = cmdline.lower()
    if "streamlit" not in lowered:
        return False
    if "ui/app.py" in lowered or "ui\\app.py" in lowered:
        return True
    root_text = str(root).replace("\\", "/").lower()
    return root_text in lowered


def _resolve_launch_plan(
    root: Path,
    requested_port: int,
    *,
    max_port_tries: int = 20,
) -> tuple[str, int, str]:
    owner = _port_owner_info(requested_port)
    if _port_is_available(requested_port):
        return "launch", requested_port, ""

    for candidate in range(int(requested_port) + 1, int(requested_port) + max_port_tries + 1):
        if _port_is_available(candidate):
            owner_pid = int(owner.get("pid", 0) or 0)
            same_app = _is_same_streamlit_app_owner(owner, root)
            reason_kind = "port_in_use_by_same_app" if same_app else "port_in_use"
            reason = f"{reason_kind}({requested_port},pid={owner_pid or 'unknown'})"
            return "launch", candidate, reason

    return "error", requested_port, f"no_free_port_from_{requested_port}_to_{requested_port + max_port_tries}"


def _launch_streamlit(root: Path, port: int) -> subprocess.Popen[Any]:
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "ui/app.py",
        "--server.port",
        str(port),
        "--server.maxUploadSize",
        "500",
    ]
    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    print(
        f"[watchdog] launch streamlit port={port} cwd={root}",
        flush=True,
    )
    return subprocess.Popen(
        cmd,
        cwd=str(root),
        env=env,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watchdog Streamlit autonome")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--stale-runtime-claim-timeout-sec", type=int, default=120)
    parser.add_argument("--restart-delay-sec", type=int, default=5)
    parser.add_argument("--poll-sec", type=float, default=5.0)
    parser.add_argument(
        "--runtime-state",
        type=Path,
        default=get_builder_sessions_dir() / "_autonomous_runtime_state.json",
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    runtime_state_path = (root / args.runtime_state).resolve()
    restart_count = 0

    while True:
        runtime = _load_runtime_state(runtime_state_path)
        cleared, clear_reason = maybe_clear_orphaned_runtime_claim(
            runtime,
            now=datetime.now(timezone.utc),
            stale_runtime_claim_timeout_sec=int(args.stale_runtime_claim_timeout_sec),
        )
        if cleared:
            print(
                f"[watchdog] clear stale runtime claim: {clear_reason}",
                flush=True,
            )
            _clear_stale_runtime_claim(
                runtime_state_path,
                runtime,
                reason=clear_reason,
                now=datetime.now(timezone.utc),
            )

        launch_action, effective_port, launch_reason = _resolve_launch_plan(
            root,
            int(args.port),
        )
        if launch_action == "reuse":
            print(
                f"[watchdog] app already running on http://localhost:{effective_port} ({launch_reason})",
                flush=True,
            )
            return 0
        if launch_action == "error":
            print(f"[watchdog] stop: {launch_reason}", flush=True)
            return 1
        if launch_reason:
            print(
                f"[watchdog] requested port {args.port} busy, switching to {effective_port} ({launch_reason})",
                flush=True,
            )

        proc = _launch_streamlit(root, effective_port)
        restart_reason = ""

        while True:
            time.sleep(max(float(args.poll_sec), 1.0))
            exit_code = proc.poll()
            runtime = _load_runtime_state(runtime_state_path)

            if exit_code is not None:
                should_restart, restart_reason = decide_exit_restart(runtime, exit_code)
                break

            should_restart, restart_reason = decide_stall_restart(
                runtime,
                process_running=True,
            )
            if should_restart:
                print(
                    f"[watchdog] restart requested: {restart_reason}",
                    flush=True,
                )
                _terminate_process(proc)
                break

        if not restart_reason:
            restart_reason = "unknown_exit"

        if not should_restart:
            print(f"[watchdog] stop: {restart_reason}", flush=True)
            return int(exit_code or 0)

        restart_count += 1
        delay_sec = min(int(args.restart_delay_sec) * max(restart_count, 1), 60)
        print(
            f"[watchdog] restart #{restart_count} in {delay_sec}s (reason={restart_reason})",
            flush=True,
        )
        time.sleep(delay_sec)


if __name__ == "__main__":
    raise SystemExit(main())
