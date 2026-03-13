"""
Watchdog léger pour Streamlit.

Relance automatiquement l'application quand le runtime autonome Builder
indique qu'il doit continuer mais que le process est réellement tombé
ou s'est fermé.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

try:
    import psutil

    _HAS_PSUTIL = True
except Exception:
    psutil = None
    _HAS_PSUTIL = False


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


def _load_runtime_state(path: Path) -> Dict[str, Any]:
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


def _save_runtime_state(path: Path, runtime: Dict[str, Any]) -> None:
    payload = {
        "version": "1.0",
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "runtime": dict(runtime),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def _runtime_requests_restart(runtime: Dict[str, Any]) -> bool:
    return bool(runtime.get("active")) and not bool(runtime.get("manual_stop"))


def _runtime_pid(runtime: Dict[str, Any]) -> int:
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
    runtime: Dict[str, Any],
    *,
    reason: str,
    now: datetime,
) -> Dict[str, Any]:
    cleaned = dict(runtime)
    cleaned["active"] = False
    cleaned["manual_stop"] = False
    cleaned["last_heartbeat_at"] = now.replace(microsecond=0).isoformat()
    cleaned["last_event"] = "watchdog_cleared_stale_runtime"
    cleaned["last_stop_reason"] = str(reason or "")
    cleaned["last_error"] = ""
    cleaned["pid"] = 0
    cleaned["process_rss_mb"] = 0.0
    _save_runtime_state(path, cleaned)
    return cleaned


def maybe_clear_orphaned_runtime_claim(
    runtime: Dict[str, Any],
    *,
    now: datetime,
    stale_runtime_claim_timeout_sec: int,
) -> Tuple[bool, str]:
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
    runtime: Dict[str, Any],
    *,
    process_running: bool,
) -> Tuple[bool, str]:
    if not _runtime_requests_restart(runtime):
        return False, ""
    if not process_running:
        return True, "process_missing_while_runtime_active"
    return False, ""


def decide_exit_restart(runtime: Dict[str, Any], exit_code: int | None) -> Tuple[bool, str]:
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
        default=Path("sandbox_strategies") / "_autonomous_runtime_state.json",
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

        proc = _launch_streamlit(root, args.port)
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
            f"[watchdog] restart #{restart_count} in {delay_sec}s "
            f"(reason={restart_reason})",
            flush=True,
        )
        time.sleep(delay_sec)


if __name__ == "__main__":
    raise SystemExit(main())
