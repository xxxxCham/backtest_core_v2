"""External supervisor for the Streamlit autonomous Strategy Builder.

This script is intentionally one-shot and idempotent. Windows Task Scheduler
or the Tkinter control panel can run it periodically; each run checks the target
state, arms the autonomous runtime when needed, and starts the Streamlit
launcher if the app is down or stale.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import psutil

    _HAS_PSUTIL = True
except Exception:
    psutil = None
    _HAS_PSUTIL = False


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "autonomous_builder_supervisor.json"
PROJECT_ENV_PATH = REPO_ROOT / ".env"
RUNTIME_VERSION = "1.0"
SUPERVISOR_STATE_VERSION = "1.0"


DEFAULT_CONFIG: dict[str, Any] = {
    "repo_root": str(REPO_ROOT),
    "launcher": "RUN_STREAMLIT.bat",
    "streamlit_port": 8502,
    "streamlit_health_path": "/_stcore/health",
    "artifacts_root": "",
    "results_root": "",
    "check_interval_minutes": 30,
    "stale_heartbeat_minutes": 20,
    "startup_grace_seconds": 180,
    "runtime_disabled": True,
    "auto_arm_when_inactive": False,
    "respect_manual_stop": True,
    "restart_stale_streamlit": False,
    "launch_streamlit_if_down": False,
    "open_browser_on_launch": False,
    "browser_open_min_interval_seconds": 600,
    "start_ollama_if_down": False,
    "ollama_host": "http://127.0.0.1:11434",
    "ollama_model": "qwen3.6:35b",
    "disable_file": "",
    "builder": {
        "execution_mode": "mono_single_llm",
        "autonomous": True,
        "pause_seconds": 10,
        "auto_use_llm": True,
        "auto_market_pick": True,
        "universe_mode": "canonical",
        "preload_model": True,
        "keep_alive_minutes": 20,
        "unload_after_run": True,
        "auto_start_ollama": True,
        "multi_llm_enabled": False,
        "multi_llm_profile": "",
        "flow_analysis_enabled": False,
        "flow_analysis_ablation": {},
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: Any) -> float | None:
    parsed = _parse_iso_datetime(value)
    if parsed is None:
        return None
    return max(0.0, (_utc_now() - parsed).total_seconds())


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp_path.write_text(serialized, encoding="utf-8")
    os.replace(tmp_path, path)


def _load_env_file(path: Path = PROJECT_ENV_PATH) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return env
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            env[key] = value
    return env


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    raw = _load_json(path, {})
    if not isinstance(raw, dict):
        raw = {}
    config = _deep_merge(DEFAULT_CONFIG, raw)
    repo_root = Path(str(config.get("repo_root") or REPO_ROOT)).expanduser()
    config["repo_root"] = str(repo_root)
    return config


def _project_env(config: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    env_file_values = _load_env_file(Path(config["repo_root"]) / ".env")
    for key, value in env_file_values.items():
        env.setdefault(key, value)

    artifacts_root = str(config.get("artifacts_root") or "").strip()
    results_root = str(config.get("results_root") or "").strip()
    if artifacts_root:
        env["BACKTEST_ARTIFACTS_DIR"] = artifacts_root
    if results_root:
        env["BACKTEST_RESULTS_DIR"] = results_root
    env["BACKTEST_STREAMLIT_PORT"] = str(int(config.get("streamlit_port") or 8502))
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def _artifacts_root(config: dict[str, Any]) -> Path:
    env = _project_env(config)
    configured = str(config.get("artifacts_root") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(
        env.get("BACKTEST_ARTIFACTS_DIR")
        or env.get("BACKTEST_RESULTS_DIR")
        or "backtest_results",
    ).expanduser()


def builder_sessions_dir(config: dict[str, Any]) -> Path:
    return _artifacts_root(config) / "_builder_sessions"


def runtime_state_path(config: dict[str, Any]) -> Path:
    return builder_sessions_dir(config) / "_autonomous_runtime_state.json"


def supervisor_state_path(config: dict[str, Any]) -> Path:
    return builder_sessions_dir(config) / "_external_supervisor_state.json"


def supervisor_log_path(config: dict[str, Any]) -> Path:
    return builder_sessions_dir(config) / "supervisor" / "autonomous_builder_supervisor.log"


def _log(config: dict[str, Any], message: str) -> None:
    line = f"{_utc_now_iso()} | {message}"
    print(line, flush=True)
    try:
        path = supervisor_log_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


def _default_runtime_state() -> dict[str, Any]:
    return {
        "version": RUNTIME_VERSION,
        "active": False,
        "manual_stop": False,
        "run_id": "",
        "claim_source": "",
        "claim_reason": "",
        "owner_pid": 0,
        "owner_started_at": "",
        "owner_signature": "",
        "started_at": "",
        "last_heartbeat_at": "",
        "last_resume_at": "",
        "last_event": "",
        "last_error": "",
        "last_stop_reason": "",
        "last_session_num": 0,
        "last_session_id": "",
        "last_session_status": "",
        "current_session_num": 0,
        "current_session_id": "",
        "last_progress_at": "",
        "last_progress_event": "",
        "last_progress_phase": "",
        "last_progress_iteration": 0,
        "pid": 0,
        "process_rss_mb": 0.0,
        "system_available_ram_mb": 0.0,
        "model": "",
        "ollama_host": "",
        "requested_source_mode": "",
        "effective_source_mode": "",
        "auto_market_pick": False,
        "resume_count": 0,
        "resume_ui_state": {},
    }


def load_runtime_state(config: dict[str, Any]) -> dict[str, Any]:
    raw = _load_json(runtime_state_path(config), {})
    if isinstance(raw, dict) and isinstance(raw.get("runtime"), dict):
        raw = raw["runtime"]
    if not isinstance(raw, dict):
        raw = {}
    runtime = _default_runtime_state()
    runtime.update(raw)
    return runtime


def save_runtime_state(config: dict[str, Any], runtime: dict[str, Any]) -> None:
    cleaned = _default_runtime_state()
    cleaned.update({key: value for key, value in runtime.items() if key in cleaned})
    payload = {
        "version": RUNTIME_VERSION,
        "updated_at": _utc_now_iso(),
        "runtime": cleaned,
    }
    _write_json_atomic(runtime_state_path(config), payload)


def _new_runtime_run_id() -> str:
    stamp = _utc_now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_supervisor_{uuid.uuid4().hex[:8]}"


def build_resume_ui_state(config: dict[str, Any]) -> dict[str, Any]:
    builder = dict(config.get("builder") or {})
    return {
        "builder_execution_mode": str(builder.get("execution_mode") or "mono_single_llm"),
        "builder_model_single_llm": str(config.get("ollama_model") or ""),
        "builder_ollama_host": str(config.get("ollama_host") or "http://127.0.0.1:11434"),
        "builder_auto_pause": int(builder.get("pause_seconds") or 10),
        "builder_auto_use_llm": bool(builder.get("auto_use_llm", True)),
        "builder_auto_market_pick": bool(builder.get("auto_market_pick", True)),
        "builder_universe_mode": str(builder.get("universe_mode") or "canonical"),
        "builder_preload_model": bool(builder.get("preload_model", True)),
        "builder_keep_alive_minutes": int(builder.get("keep_alive_minutes") or 20),
        "builder_unload_after_run": bool(builder.get("unload_after_run", True)),
        "builder_auto_start_ollama": bool(builder.get("auto_start_ollama", True)),
        "builder_multi_llm_enabled": bool(builder.get("multi_llm_enabled", False)),
        "builder_multi_llm_profile": str(builder.get("multi_llm_profile") or ""),
        "builder_multi_llm_role_overrides": dict(builder.get("multi_llm_role_overrides") or {}),
        "builder_flow_analysis_enabled": bool(builder.get("flow_analysis_enabled", False)),
        "builder_flow_analysis_ablation": dict(builder.get("flow_analysis_ablation") or {}),
    }


def arm_runtime(config: dict[str, Any], *, reason: str) -> dict[str, Any]:
    now = _utc_now_iso()
    runtime = _default_runtime_state()
    runtime["active"] = True
    runtime["manual_stop"] = False
    runtime["run_id"] = _new_runtime_run_id()
    runtime["claim_source"] = "external_supervisor"
    runtime["claim_reason"] = str(reason or "")
    runtime["owner_pid"] = 0
    runtime["owner_started_at"] = ""
    runtime["owner_signature"] = ""
    runtime["started_at"] = now
    runtime["last_heartbeat_at"] = now
    runtime["last_resume_at"] = ""
    runtime["last_event"] = f"external_supervisor_armed:{reason}"
    runtime["last_error"] = ""
    runtime["last_stop_reason"] = ""
    runtime["last_progress_at"] = now
    runtime["last_progress_event"] = "external_supervisor_armed"
    runtime["last_progress_phase"] = "bootstrap"
    runtime["model"] = str(config.get("ollama_model") or "")
    runtime["ollama_host"] = str(config.get("ollama_host") or "")
    runtime["requested_source_mode"] = "llm"
    runtime["auto_market_pick"] = bool(
        dict(config.get("builder") or {}).get("auto_market_pick", True),
    )
    runtime["resume_ui_state"] = build_resume_ui_state(config)
    save_runtime_state(config, runtime)
    return runtime


def _http_ok(url: str, *, timeout: float = 4.0) -> tuple[bool, int, str]:
    request = Request(url, headers={"User-Agent": "backtest-builder-supervisor/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(512).decode("utf-8", errors="replace")
            return 200 <= int(response.status) < 500, int(response.status), body
    except HTTPError as exc:
        return 200 <= int(exc.code) < 500, int(exc.code), str(exc)
    except (OSError, URLError, TimeoutError) as exc:
        return False, 0, str(exc)


def streamlit_url(config: dict[str, Any]) -> str:
    return f"http://localhost:{int(config.get('streamlit_port') or 8502)}"


def is_streamlit_healthy(config: dict[str, Any]) -> tuple[bool, str]:
    health_path = str(config.get("streamlit_health_path") or "/_stcore/health")
    if not health_path.startswith("/"):
        health_path = "/" + health_path
    ok, status, detail = _http_ok(streamlit_url(config) + health_path)
    if ok:
        return True, f"health_status={status}"
    root_ok, root_status, root_detail = _http_ok(streamlit_url(config) + "/")
    if root_ok:
        return True, f"root_status={root_status}"
    return False, f"health_status={status}; detail={detail or root_detail}"


def _ollama_tags_url(ollama_host: str) -> str:
    host = str(ollama_host or "http://127.0.0.1:11434").rstrip("/")
    return host + "/api/tags"


def _ollama_ps_url(ollama_host: str) -> str:
    host = str(ollama_host or "http://127.0.0.1:11434").rstrip("/")
    return host + "/api/ps"


def _normalize_ollama_name(name: str) -> str:
    value = str(name or "").strip().lower()
    if value.endswith(":latest"):
        return value[: -len(":latest")]
    return value


def _extract_ollama_model_names(body: str) -> set[str]:
    try:
        payload = json.loads(body or "{}")
    except json.JSONDecodeError:
        return set()
    if not isinstance(payload, dict):
        return set()
    names: set[str] = set()
    for item in payload.get("models") or []:
        if not isinstance(item, dict):
            continue
        for key in ("name", "model"):
            raw = item.get(key)
            if raw:
                names.add(str(raw))
    return names


def _ollama_body_has_model(body: str, model_name: str) -> bool:
    wanted = _normalize_ollama_name(model_name)
    if not wanted:
        return True
    for name in _extract_ollama_model_names(body):
        if _normalize_ollama_name(name) == wanted:
            return True
    return wanted in _normalize_ollama_name(body)


def is_ollama_healthy(config: dict[str, Any]) -> tuple[bool, str, bool, bool, bool]:
    ok, status, body = _http_ok(_ollama_tags_url(str(config.get("ollama_host") or "")))
    if not ok:
        return False, f"ollama_status={status}; detail={body}", False, False, False
    model_name = str(config.get("ollama_model") or "").strip()
    if not model_name:
        return True, f"ollama_status={status}", True, True, True

    present_in_tags = _ollama_body_has_model(body, model_name)
    loaded_in_ps = False
    if not present_in_tags:
        ps_ok, ps_status, ps_body = _http_ok(_ollama_ps_url(str(config.get("ollama_host") or "")))
        loaded_in_ps = bool(ps_ok and _ollama_body_has_model(ps_body, model_name))
        if loaded_in_ps:
            return True, f"ollama_status={status}; model_loaded_in_ps", True, present_in_tags, loaded_in_ps
        if not ps_ok:
            return True, f"ollama_status={status}; ps_status={ps_status}", False, present_in_tags, loaded_in_ps
    return True, f"ollama_status={status}", present_in_tags, present_in_tags, loaded_in_ps


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    flags = 0
    flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    return flags


def launch_streamlit(config: dict[str, Any], *, dry_run: bool = False) -> bool:
    repo_root = Path(str(config["repo_root"]))
    launcher = repo_root / str(config.get("launcher") or "RUN_STREAMLIT.bat")
    if not launcher.exists():
        _log(config, f"launch_skipped launcher_missing path={launcher}")
        return False
    if dry_run:
        _log(config, f"dry_run launch_streamlit launcher={launcher}")
        return True

    env = _project_env(config)
    log_path = supervisor_log_path(config).with_name("streamlit_launcher.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["cmd.exe", "/c", str(launcher)] if os.name == "nt" else [str(launcher)]
    with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
        subprocess.Popen(
            cmd,
            cwd=str(repo_root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=_creation_flags(),
        )
    _log(config, f"streamlit_launch_requested port={config.get('streamlit_port')} launcher={launcher}")
    return True


def start_ollama_if_needed(config: dict[str, Any], *, dry_run: bool = False) -> bool:
    healthy, detail, _model_detected, _present_in_tags, _loaded_in_ps = is_ollama_healthy(config)
    if healthy:
        return False
    if not bool(config.get("start_ollama_if_down", True)):
        _log(config, f"ollama_down_no_start detail={detail}")
        return False
    ollama_exe = shutil.which("ollama")
    if not ollama_exe:
        _log(config, f"ollama_down_start_skipped command_missing detail={detail}")
        return False
    if dry_run:
        _log(config, f"dry_run start_ollama command={ollama_exe} serve")
        return True
    log_path = supervisor_log_path(config).with_name("ollama_serve.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
        subprocess.Popen(
            [ollama_exe, "serve"],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=_creation_flags(),
        )
    _log(config, "ollama_start_requested")
    return True


def _process_matches_repo_streamlit(proc: Any, repo_root: Path) -> bool:
    try:
        cmdline = " ".join(str(part or "") for part in proc.cmdline())
    except Exception:
        return False
    lowered = cmdline.replace("\\", "/").lower()
    root = str(repo_root).replace("\\", "/").lower()
    if root not in lowered:
        return False
    markers = (
        "tools/streamlit_watchdog.py",
        "streamlit run ui/app.py",
        "streamlit.exe run ui/app.py",
        "run_streamlit.bat",
    )
    return any(marker in lowered for marker in markers)


def terminate_repo_streamlit(config: dict[str, Any], *, dry_run: bool = False) -> int:
    if not _HAS_PSUTIL:
        _log(config, "restart_skipped psutil_unavailable")
        return 0
    repo_root = Path(str(config["repo_root"]))
    targets: list[Any] = []
    for proc in psutil.process_iter(["pid", "name"]):
        if _process_matches_repo_streamlit(proc, repo_root):
            targets.append(proc)
    if dry_run:
        _log(config, f"dry_run terminate_streamlit count={len(targets)}")
        return len(targets)
    for proc in targets:
        try:
            for child in proc.children(recursive=True):
                try:
                    child.terminate()
                except Exception:
                    pass
            proc.terminate()
        except Exception:
            pass
    gone, alive = psutil.wait_procs(targets, timeout=8)
    for proc in alive:
        try:
            proc.kill()
        except Exception:
            pass
    count = len(targets)
    if count:
        _log(config, f"streamlit_processes_terminated count={count}")
    return count


def _load_supervisor_state(config: dict[str, Any]) -> dict[str, Any]:
    raw = _load_json(supervisor_state_path(config), {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        "version": SUPERVISOR_STATE_VERSION,
        "last_check_at": raw.get("last_check_at", ""),
        "last_launch_at": raw.get("last_launch_at", ""),
        "last_browser_open_at": raw.get("last_browser_open_at", ""),
        "last_action": raw.get("last_action", ""),
    }


def _save_supervisor_state(config: dict[str, Any], state: dict[str, Any]) -> None:
    state = dict(state)
    state["version"] = SUPERVISOR_STATE_VERSION
    _write_json_atomic(supervisor_state_path(config), state)


def open_browser(config: dict[str, Any], *, reason: str, dry_run: bool = False) -> bool:
    if not bool(config.get("open_browser_on_launch", True)):
        return False
    state = _load_supervisor_state(config)
    min_interval = int(config.get("browser_open_min_interval_seconds") or 600)
    last_age = _age_seconds(state.get("last_browser_open_at"))
    if last_age is not None and last_age < min_interval:
        _log(config, f"browser_open_throttled age={last_age:.0f}s reason={reason}")
        return False
    url = streamlit_url(config)
    if dry_run:
        _log(config, f"dry_run open_browser url={url} reason={reason}")
        return True
    if os.name == "nt":
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "", url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_creation_flags(),
        )
    else:
        subprocess.Popen(
            ["xdg-open", url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    state["last_browser_open_at"] = _utc_now_iso()
    state["last_action"] = f"open_browser:{reason}"
    _save_supervisor_state(config, state)
    _log(config, f"browser_open_requested url={url} reason={reason}")
    return True


def _port_accepts_connection(port: int) -> bool:
    for family, address in (
        (socket.AF_INET, ("127.0.0.1", int(port))),
        (socket.AF_INET6, ("::1", int(port), 0, 0)),
    ):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.3)
                if sock.connect_ex(address) == 0:
                    return True
        except OSError:
            pass
    return False


def inspect_status(config: dict[str, Any]) -> dict[str, Any]:
    runtime = load_runtime_state(config)
    streamlit_healthy, streamlit_detail = is_streamlit_healthy(config)
    ollama_healthy, ollama_detail, model_detected, present_in_tags, loaded_in_ps = is_ollama_healthy(config)
    heartbeat_age = _age_seconds(runtime.get("last_heartbeat_at"))
    started_age = _age_seconds(runtime.get("started_at"))
    progress_age = _age_seconds(runtime.get("last_progress_at"))
    return {
        "runtime_path": str(runtime_state_path(config)),
        "streamlit_url": streamlit_url(config),
        "streamlit_healthy": streamlit_healthy,
        "streamlit_detail": streamlit_detail,
        "port_accepts_connection": _port_accepts_connection(int(config.get("streamlit_port") or 8502)),
        "ollama_healthy": ollama_healthy,
        "ollama_detail": ollama_detail,
        "ollama_model": str(config.get("ollama_model") or ""),
        "ollama_model_detected": model_detected,
        "ollama_model_present_in_tags": present_in_tags,
        "ollama_model_loaded_in_ps": loaded_in_ps,
        "runtime_active": bool(runtime.get("active")),
        "runtime_manual_stop": bool(runtime.get("manual_stop")),
        "runtime_run_id": str(runtime.get("run_id") or ""),
        "runtime_claim_source": str(runtime.get("claim_source") or ""),
        "runtime_owner_pid": int(runtime.get("owner_pid") or runtime.get("pid") or 0),
        "runtime_last_event": str(runtime.get("last_event") or ""),
        "runtime_last_stop_reason": str(runtime.get("last_stop_reason") or ""),
        "runtime_heartbeat_age_seconds": heartbeat_age,
        "runtime_started_age_seconds": started_age,
        "runtime_progress_age_seconds": progress_age,
        "runtime_progress_phase": str(runtime.get("last_progress_phase") or ""),
        "runtime_pid": int(runtime.get("pid", 0) or 0),
        "disable_file": str(config.get("disable_file") or ""),
    }


def _runtime_is_stale(status: dict[str, Any], config: dict[str, Any]) -> bool:
    if not bool(status.get("runtime_active")):
        return False
    heartbeat_age = status.get("runtime_heartbeat_age_seconds")
    started_age = status.get("runtime_started_age_seconds")
    if heartbeat_age is None:
        return True
    stale_after = float(config.get("stale_heartbeat_minutes") or 20) * 60.0
    startup_grace = float(config.get("startup_grace_seconds") or 180)
    if started_age is not None and started_age < startup_grace:
        return False
    if float(heartbeat_age) <= stale_after:
        return False
    # Le heartbeat est stale, mais une phase longue (backtest, codegen LLM) peut
    # dépasser le seuil sans être un vrai blocage. On accorde une grâce supplémentaire
    # si last_progress_at est encore récent.
    progress_age = status.get("runtime_progress_age_seconds")
    if progress_age is not None:
        active_phase_grace = float(config.get("active_phase_stale_minutes") or 45) * 60.0
        if progress_age < active_phase_grace:
            return False
    return True


def check_once(config: dict[str, Any], *, dry_run: bool = False) -> int:
    if bool(config.get("runtime_disabled", False)):
        _log(config, "disabled runtime_disabled=true (config flag)")
        return 0
    disable_file = str(config.get("disable_file") or "").strip()
    if disable_file and Path(disable_file).exists():
        _log(config, f"disabled disable_file={disable_file}")
        return 0

    state = _load_supervisor_state(config)
    state["last_check_at"] = _utc_now_iso()
    state["last_action"] = "check"
    _save_supervisor_state(config, state)

    start_ollama_if_needed(config, dry_run=dry_run)

    status = inspect_status(config)
    runtime_active = bool(status["runtime_active"])
    manual_stop = bool(status["runtime_manual_stop"])
    respect_manual_stop = bool(config.get("respect_manual_stop", False))

    should_arm = False
    arm_reason = ""
    if bool(config.get("auto_arm_when_inactive", True)):
        if not runtime_active:
            if manual_stop and respect_manual_stop:
                _log(config, "runtime_manual_stop_respected")
            else:
                should_arm = True
                arm_reason = "inactive"
        elif manual_stop and not respect_manual_stop:
            should_arm = True
            arm_reason = "manual_stop_override"

    if should_arm:
        if dry_run:
            _log(config, f"dry_run arm_runtime reason={arm_reason}")
        else:
            arm_runtime(config, reason=arm_reason)
        status = inspect_status(config)

    streamlit_healthy = bool(status["streamlit_healthy"])
    stale_runtime = _runtime_is_stale(status, config)
    launched = False

    if stale_runtime and bool(config.get("restart_stale_streamlit", False)):
        _log(
            config,
            "stale_runtime_restart "
            f"heartbeat_age={status.get('runtime_heartbeat_age_seconds')} "
            f"progress_age={status.get('runtime_progress_age_seconds')} "
            f"phase={status.get('runtime_progress_phase')}",
        )
        terminate_repo_streamlit(config, dry_run=dry_run)
        launched = launch_streamlit(config, dry_run=dry_run)
    elif not streamlit_healthy and bool(config.get("launch_streamlit_if_down", True)):
        _log(config, f"streamlit_down detail={status['streamlit_detail']}")
        launched = launch_streamlit(config, dry_run=dry_run)

    if launched:
        state = _load_supervisor_state(config)
        state["last_launch_at"] = _utc_now_iso()
        state["last_action"] = "launch_streamlit"
        _save_supervisor_state(config, state)
        if not dry_run:
            time.sleep(3)
        open_browser(config, reason="streamlit_launched", dry_run=dry_run)
    elif should_arm and streamlit_healthy:
        open_browser(config, reason="runtime_armed", dry_run=dry_run)
    else:
        _log(
            config,
            "ok "
            f"streamlit={streamlit_healthy} runtime_active={status['runtime_active']} "
            f"heartbeat_age={status.get('runtime_heartbeat_age_seconds')}",
        )

    return 0


def loop_forever(config: dict[str, Any], *, dry_run: bool = False) -> int:
    if bool(config.get("runtime_disabled", False)):
        _log(config, "loop_skipped runtime_disabled=true (config flag)")
        return 0
    lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock_socket.bind(("127.0.0.1", 38503))
        lock_socket.listen(1)
    except OSError:
        _log(config, "loop_already_running")
        return 0

    interval_sec = max(60, int(float(config.get("check_interval_minutes") or 15) * 60))
    _log(config, f"loop_started interval_sec={interval_sec}")
    while True:
        try:
            check_once(config, dry_run=dry_run)
        except Exception as exc:
            _log(config, f"loop_check_failed error={exc}")
        if dry_run:
            return 0
        time.sleep(interval_sec)


def print_status(config: dict[str, Any]) -> int:
    print(json.dumps(inspect_status(config), indent=2, ensure_ascii=False, default=str))
    return 0


def install_hint(config_path: Path) -> int:
    runner = REPO_ROOT / "tools" / "install_autonomous_builder_supervisor.ps1"
    print(
        "Install with:\n"
        f"  powershell -NoProfile -ExecutionPolicy Bypass -File \"{runner}\" -RunNow\n\n"
        "Remove with:\n"
        f"  powershell -NoProfile -ExecutionPolicy Bypass -File \"{runner}\" -Remove\n\n"
        f"Config: {config_path}",
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Supervise autonomous Backtest Core Strategy Builder")
    parser.add_argument(
        "command",
        choices=("check", "loop", "status", "arm", "install-hint"),
        nargs="?",
        default="check",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.command == "status":
        return print_status(config)
    if args.command == "install-hint":
        return install_hint(args.config)
    if args.command == "arm":
        if args.dry_run:
            _log(config, "dry_run arm_runtime reason=manual")
        else:
            arm_runtime(config, reason="manual")
        return 0
    if args.command == "loop":
        return loop_forever(config, dry_run=bool(args.dry_run))
    return check_once(config, dry_run=bool(args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
