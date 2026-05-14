"""Side-effect-light runtime helpers for the Streamlit Strategy Builder."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.llm_client import LLMConfig, LLMProvider
from agents.llm_config import apply_llm_inference_settings


def parse_runtime_timestamp(value: Any) -> datetime | None:
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


def is_transient_atomic_write_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, "winerror", None)
    errno = getattr(exc, "errno", None)
    return winerror == 32 or errno in {13, 32}


def cleanup_atomic_tmp_file(tmp_path: Path) -> None:
    try:
        if tmp_path.exists():
            tmp_path.unlink()
    except Exception:
        pass


def build_unique_atomic_tmp_path(target_path: Path) -> Path:
    suffix = f".{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    return target_path.with_name(f"{target_path.name}{suffix}")


def format_ollama_keep_alive(keep_alive_minutes: int) -> str:
    resolved = max(0, int(keep_alive_minutes))
    return "0m" if resolved <= 0 else f"{resolved}m"


def build_builder_base_llm_config(
    *,
    model: str,
    ollama_host: str,
    keep_alive_minutes: int,
    llm_inference_global_settings: dict[str, Any],
    llm_inference_model_profiles: dict[str, Any],
) -> LLMConfig:
    config = apply_llm_inference_settings(
        LLMConfig(
            provider=LLMProvider.OLLAMA,
            model=model,
            ollama_host=ollama_host,
        ),
        model_name=model,
        global_settings=llm_inference_global_settings,
        model_profiles=llm_inference_model_profiles,
    )
    if getattr(config, "provider", None) == LLMProvider.OLLAMA:
        config.keep_alive = format_ollama_keep_alive(keep_alive_minutes)
    return config


def apply_builder_runtime_to_client(
    llm_client: Any,
    *,
    model: str,
    ollama_host: str,
    llm_inference_global_settings: dict[str, Any],
    llm_inference_model_profiles: dict[str, Any],
) -> Any:
    config = getattr(llm_client, "config", None)
    if config is None:
        return llm_client
    config.model = model
    config.ollama_host = ollama_host
    apply_llm_inference_settings(
        config,
        model_name=model,
        global_settings=llm_inference_global_settings,
        model_profiles=llm_inference_model_profiles,
    )
    return llm_client
