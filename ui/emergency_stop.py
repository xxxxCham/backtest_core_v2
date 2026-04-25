"""Module-ID: ui.emergency_stop

Purpose: Arrêt unifié du runtime Builder/LLM et nettoyage déterministe.

Role in pipeline: ui / cleanup

Key components: execute_emergency_stop

Inputs: Session state, hosts Ollama, callbacks de cache optionnels

Outputs: Statistiques de nettoyage structurées

Dependencies: gc, httpx, agents.ollama_manager, ui.cache_manager

Conventions: Une seule autorité d'arrêt; pas de singleton; pas d'hôte codé en dur.

Read-if: Modification du bouton "Arrêter et nettoyer"

Skip-if: Utilisation normale hors stop manuel
"""

from __future__ import annotations

import gc
import logging
from collections.abc import Callable, Iterable

# pylint: disable=broad-except
from typing import Any

import httpx

from agents.ollama_manager import cleanup_all_models, stop_local_ollama_server
from ui.cache_manager import clear_data_cache
from ui.state import mark_ui_stop_requested

logger = logging.getLogger(__name__)

_SESSION_CONTEXT_KEYS = (
    "last_run_result",
    "last_winner_params",
    "last_winner_metrics",
    "last_winner_origin",
    "last_winner_meta",
    "orchestration_logs",
    "llm_optimizer",
    "llm_session",
    "current_optimization",
)


def _session_contains(session_state: Any | None, key: str) -> bool:
    if session_state is None:
        return False
    try:
        return key in session_state
    except Exception:  # noqa: BLE001
        return hasattr(session_state, key)


def _session_set(session_state: Any | None, key: str, value: Any) -> None:
    if session_state is None:
        return
    try:
        session_state[key] = value
        return
    except Exception:  # noqa: BLE001
        pass
    try:
        setattr(session_state, key, value)
    except Exception:  # noqa: BLE001
        logger.debug("session_state_set_failed key=%s", key, exc_info=True)


def _session_pop(session_state: Any | None, key: str) -> bool:
    if session_state is None:
        return False
    try:
        if key in session_state:
            session_state.pop(key, None)
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        if hasattr(session_state, key):
            delattr(session_state, key)
            return True
    except Exception:  # noqa: BLE001
        logger.debug("session_state_pop_failed key=%s", key, exc_info=True)
    return False


def _normalize_ollama_hosts(ollama_hosts: Iterable[str] | None) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw_host in ollama_hosts or ():
        host = str(raw_host or "").strip().rstrip("/")
        if not host or host in seen:
            continue
        seen.add(host)
        ordered.append(host)
    return ordered


def _list_loaded_models_for_host(ollama_host: str) -> list[str]:
    try:
        response = httpx.get(f"{ollama_host}/api/ps", timeout=3.0)
    except Exception:  # noqa: BLE001
        return []
    if response.status_code != 200:
        return []
    try:
        payload = response.json() if response.content else {}
    except Exception:  # noqa: BLE001
        return []
    models = payload.get("models", []) or []
    return [str(model.get("name", "") or "").strip() for model in models if str(model.get("name", "") or "").strip()]


def _record_component(stats: dict[str, Any], component: str) -> None:
    components = stats.setdefault("components_cleaned", [])
    if component not in components:
        components.append(component)


def _record_error(stats: dict[str, Any], error: str) -> None:
    stats.setdefault("errors", []).append(error)


def _mark_stop_requested(session_state: Any | None, stats: dict[str, Any]) -> None:
    mark_ui_stop_requested(session_state)
    _record_component(stats, "session_flags")


def _clear_session_context(session_state: Any | None, stats: dict[str, Any]) -> None:
    cleared = 0
    for key in _SESSION_CONTEXT_KEYS:
        cleared += int(_session_pop(session_state, key))
    if cleared > 0:
        _record_component(stats, f"session_context_{cleared}")


def _cleanup_indicator_cache(stats: dict[str, Any]) -> None:
    try:
        from data.indicator_bank import get_indicator_bank

        bank = get_indicator_bank()
        expired = int(bank.cleanup_expired() or 0)
        if expired > 0:
            _record_component(stats, f"indicator_expired_{expired}")
        memory_cache = getattr(bank, "_memory_cache", None)
        if isinstance(memory_cache, dict):
            memory_cache.clear()
            _record_component(stats, "indicator_memory_cache")
    except Exception as exc:  # noqa: BLE001
        _record_error(stats, f"indicator_cache: {exc}")


def _cleanup_pytorch(stats: dict[str, Any]) -> None:
    try:
        import torch
    except ImportError:
        return
    except Exception as exc:  # noqa: BLE001
        _record_error(stats, f"pytorch_import: {exc}")
        return

    try:
        if not torch.cuda.is_available():
            return
        device_count = int(torch.cuda.device_count() or 0)
        for index in range(device_count):
            with torch.cuda.device(index):
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        _record_component(stats, "pytorch_cuda")
    except Exception as exc:  # noqa: BLE001
        _record_error(stats, f"pytorch: {exc}")


def _cleanup_memory_manager(stats: dict[str, Any]) -> None:
    try:
        from utils.memory import MemoryManager

        manager = MemoryManager()
        freed = int(manager.cleanup(aggressive=True) or 0)
        if freed > 0:
            stats["ram_freed_mb"] = stats.get("ram_freed_mb", 0.0) + (freed / (1024**2))
            _record_component(stats, "memory_manager")
    except Exception as exc:  # noqa: BLE001
        _record_error(stats, f"memory_manager: {exc}")


def _run_cache_callbacks(
    callbacks: Iterable[Callable[[], Any]],
    stats: dict[str, Any],
) -> None:
    for callback in callbacks:
        try:
            callback()
        except Exception as exc:  # noqa: BLE001
            callback_name = getattr(callback, "__name__", repr(callback))
            _record_error(stats, f"cache_callback[{callback_name}]: {exc}")
            continue
        callback_name = getattr(callback, "__name__", "callback")
        _record_component(stats, f"cache_callback_{callback_name}")


def _cleanup_ollama_hosts(
    ollama_hosts: Iterable[str],
    stats: dict[str, Any],
    *,
    stop_local_servers: bool,
) -> None:
    unloaded_by_host = stats.setdefault("ollama_unloaded", {})
    remaining_by_host = stats.setdefault("ollama_remaining", {})
    stopped_by_host = stats.setdefault("ollama_stopped", {})

    for host in _normalize_ollama_hosts(ollama_hosts):
        try:
            unloaded = int(cleanup_all_models(ollama_host=host) or 0)
        except Exception as exc:  # noqa: BLE001
            unloaded_by_host[host] = 0
            _record_error(stats, f"cleanup_all_models[{host}]: {exc}")
            unloaded = 0
        else:
            unloaded_by_host[host] = unloaded

        remaining_models = _list_loaded_models_for_host(host)
        if remaining_models:
            remaining_by_host[host] = remaining_models

        if not stop_local_servers:
            continue

        owned_only = not bool(remaining_models)
        stopped = 0
        try:
            stopped = int(
                stop_local_ollama_server(
                    ollama_host=host,
                    owned_only=owned_only,
                )
                or 0,
            )
        except Exception as exc:  # noqa: BLE001
            _record_error(stats, f"stop_local_ollama_server[{host}]: {exc}")
            continue

        post_stop_remaining = _list_loaded_models_for_host(host)
        if post_stop_remaining and owned_only:
            try:
                stopped += int(
                    stop_local_ollama_server(
                        ollama_host=host,
                        owned_only=False,
                    )
                    or 0,
                )
            except Exception as exc:  # noqa: BLE001
                _record_error(stats, f"stop_local_ollama_server_hard[{host}]: {exc}")
            post_stop_remaining = _list_loaded_models_for_host(host)

        if stopped > 0:
            stopped_by_host[host] = stopped
        if post_stop_remaining:
            remaining_by_host[host] = post_stop_remaining
        else:
            remaining_by_host.pop(host, None)


def _collect_process_memory(stats: dict[str, Any]) -> None:
    try:
        import psutil

        stats["current_ram_mb"] = psutil.Process().memory_info().rss / (1024**2)
    except Exception:  # noqa: BLE001
        return


def execute_emergency_stop(
    session_state: Any | None = None,
    *,
    ollama_hosts: Iterable[str] | None = None,
    cache_callbacks: Iterable[Callable[[], Any]] | None = None,
    stop_local_servers: bool = True,
) -> dict[str, Any]:
    """Exécute un arrêt unique et déterministe du runtime Builder/LLM.

    `ollama_hosts` permet de nettoyer tous les endpoints réellement utilisés
    par la session. Les callbacks servent uniquement aux caches externes
    (Streamlit, copies temporaires, etc.).
    """
    stats: dict[str, Any] = {
        "components_cleaned": [],
        "errors": [],
        "ram_freed_mb": 0.0,
        "ollama_unloaded": {},
        "ollama_remaining": {},
        "ollama_stopped": {},
    }

    _mark_stop_requested(session_state, stats)
    _clear_session_context(session_state, stats)
    _cleanup_ollama_hosts(
        ollama_hosts or (),
        stats,
        stop_local_servers=stop_local_servers,
    )
    _cleanup_indicator_cache(stats)
    _cleanup_memory_manager(stats)
    _cleanup_pytorch(stats)
    _run_cache_callbacks(
        [clear_data_cache, *(list(cache_callbacks or []))],
        stats,
    )

    stats["gc_collected_objects"] = gc.collect()
    _record_component(stats, "garbage_collector")
    _collect_process_memory(stats)
    return stats
