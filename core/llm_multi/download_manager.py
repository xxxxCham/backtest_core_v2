"""Install planning and execution for missing multi-LLM models."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .model_discovery import ModelInventory
from .registry import resolve_profile_assignments

DEFAULT_DOWNLOAD_LOG_DIR = Path(__file__).resolve().parent / "logs"


@dataclass
class ModelInstallRequest:
    """Single pending model installation."""

    role: str
    backend: str
    model_name: str
    reason: str
    destination_root: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "backend": self.backend,
            "model_name": self.model_name,
            "reason": self.reason,
            "destination_root": self.destination_root,
        }


@dataclass
class ModelInstallResult:
    """Outcome of an attempted model installation."""

    role: str
    backend: str
    model_name: str
    success: bool
    command: List[str] = field(default_factory=list)
    log_path: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "backend": self.backend,
            "model_name": self.model_name,
            "success": self.success,
            "command": list(self.command),
            "log_path": self.log_path,
            "detail": self.detail,
        }


def _default_destination_root(backend: str) -> str:
    if backend == "huggingface":
        return r"D:\models\huggingface"
    return r"D:\models\ollama"


def plan_missing_downloads(
    profile_name: str,
    inventory: ModelInventory,
    *,
    config_path: Optional[str | Path] = None,
    role_overrides: Optional[Dict[str, str]] = None,
    require_live_ollama: bool = False,
) -> List[ModelInstallRequest]:
    resolved = resolve_profile_assignments(
        profile_name,
        inventory,
        config_path=config_path,
        role_overrides=role_overrides,
        require_live_ollama=require_live_ollama,
    )
    requests: List[ModelInstallRequest] = []
    for assignment in resolved["assignments"]:
        if (
            assignment.available
            or not assignment.requested_model
            or not assignment.install_required
        ):
            continue
        requests.append(
            ModelInstallRequest(
                role=assignment.role,
                backend=assignment.backend,
                model_name=assignment.requested_model,
                reason=assignment.reason,
                destination_root=_default_destination_root(assignment.backend),
            )
        )
    return requests


def install_missing_models(
    requests: List[ModelInstallRequest],
    *,
    ollama_host: Optional[str] = None,
    dry_run: bool = False,
    log_dir: Optional[str | Path] = None,
) -> List[ModelInstallResult]:
    """Install only the missing models that have explicit requests."""

    results: List[ModelInstallResult] = []
    if not requests:
        return results

    destination = Path(log_dir or DEFAULT_DOWNLOAD_LOG_DIR)
    destination.mkdir(parents=True, exist_ok=True)
    host = str(
        ollama_host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    ).strip()
    ollama_binary = shutil.which("ollama")

    for request in requests:
        log_path = destination / (
            f"install_{request.role}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
        if request.backend != "ollama":
            detail = "automatic install currently implemented for Ollama models only"
            log_path.write_text(detail, encoding="utf-8")
            results.append(
                ModelInstallResult(
                    role=request.role,
                    backend=request.backend,
                    model_name=request.model_name,
                    success=False,
                    log_path=str(log_path),
                    detail=detail,
                )
            )
            continue

        if not ollama_binary:
            detail = "ollama binary not found on PATH"
            log_path.write_text(detail, encoding="utf-8")
            results.append(
                ModelInstallResult(
                    role=request.role,
                    backend=request.backend,
                    model_name=request.model_name,
                    success=False,
                    log_path=str(log_path),
                    detail=detail,
                )
            )
            continue

        command = [ollama_binary, "pull", request.model_name]
        if dry_run:
            detail = f"dry_run: {' '.join(command)}"
            log_path.write_text(detail, encoding="utf-8")
            results.append(
                ModelInstallResult(
                    role=request.role,
                    backend=request.backend,
                    model_name=request.model_name,
                    success=True,
                    command=command,
                    log_path=str(log_path),
                    detail=detail,
                )
            )
            continue

        env = os.environ.copy()
        env["OLLAMA_HOST"] = host
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        detail_payload = {
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "returncode": completed.returncode,
            "host": host,
            "request": request.to_dict(),
        }
        log_path.write_text(json.dumps(detail_payload, indent=2), encoding="utf-8")
        results.append(
            ModelInstallResult(
                role=request.role,
                backend=request.backend,
                model_name=request.model_name,
                success=completed.returncode == 0,
                command=command,
                log_path=str(log_path),
                detail=(completed.stdout or completed.stderr or "").strip(),
            )
        )

    return results
