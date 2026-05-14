"""Module-ID: agents.ollama_runtime

Purpose: Contrat canonique des helpers runtime Ollama partagés entre client, manager et UI.

Role in pipeline: orchestration

Key components: resolve_ollama_request_context, get_ollama_cloud_runtime_model_candidates

Inputs: hôte Ollama, nom de modèle

Outputs: contexte de requête HTTP, aliases runtime cloud, normalisation host/modèle

Dependencies: os, urllib.parse, agents.model_config

Conventions: un seul endroit de décision pour éviter la dérive corrective entre couches.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from agents.model_config import is_cloud_only_model

_OLLAMA_DIRECT_CLOUD_HOST = "https://ollama.com"
_OLLAMA_CLOUD_LOCAL_RUNTIME_ALIAS_OVERRIDES: dict[str, list[str]] = {
    "cogito-2.1:671b": ["cogito-2.1:671b-cloud"],
    "deepseek-v3.1": ["deepseek-v3.1:671b-cloud"],
    "deepseek-v3.2": ["deepseek-v3.2:cloud"],
    "deepseek-v4-pro": ["deepseek-v4-pro:cloud"],
    "deepseek-v4-flash": ["deepseek-v4-flash:cloud"],
    "devstral-2:123b": ["devstral-2:123b-cloud"],
    "glm-4.6": ["glm-4.6:cloud"],
    "glm-4.7": ["glm-4.7:cloud"],
    "glm-5": ["glm-5:cloud"],
    "glm-5.1": ["glm-5.1:cloud"],
    "gpt-oss:120b": ["gpt-oss:120b-cloud"],
    "kimi-k2": ["kimi-k2:1t-cloud", "kimi-k2:cloud"],
    "kimi-k2-thinking": ["kimi-k2-thinking:cloud"],
    "kimi-k2.5": ["kimi-k2.5:cloud"],
    "kimi-k2.6": ["kimi-k2.6:cloud"],
    "minimax-m2.1": ["minimax-m2.1:cloud"],
    "minimax-m2.5": ["minimax-m2.5:cloud"],
    "minimax-m2.7": ["minimax-m2.7:cloud"],
    "mistral-large-3": ["mistral-large-3:675b-cloud"],
    "nemotron-3-super:120b": ["nemotron-3-super:120b-cloud"],
    "qwen3-coder:480b": ["qwen3-coder:480b-cloud"],
    "qwen3-coder-next": ["qwen3-coder-next:cloud"],
    "qwen3-next:80b": ["qwen3-next:80b-cloud"],
    "qwen3-vl:235b": ["qwen3-vl:235b-cloud"],
    "qwen3.5:122b": ["qwen3.5:122b-cloud"],
}


def _get_ollama_host(override: str | None = None) -> str:
    """Retourne l'hôte Ollama effectif (override > env > défaut)."""
    host = str(
        override or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434",
    ).strip()
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    parsed = urlparse(host)
    normalized_path = str(parsed.path or "").rstrip("/")
    if normalized_path.lower() == "/api":
        host = parsed._replace(path="", params="", query="", fragment="").geturl()
    return host.rstrip("/")


def _ollama_url(path: str, ollama_host: str | None = None) -> str:
    normalized = path if path.startswith("/") else f"/{path}"
    return f"{_get_ollama_host(ollama_host)}{normalized}"


def _is_local_ollama_host(ollama_host: str | None = None) -> bool:
    host = _get_ollama_host(ollama_host)
    parsed = urlparse(host)
    hostname = (parsed.hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost", "::1"}


def _is_ollama_cloud_host(ollama_host: str | None = None) -> bool:
    host = _get_ollama_host(ollama_host)
    parsed = urlparse(host)
    hostname = (parsed.hostname or "").lower()
    return hostname == "ollama.com" or hostname.endswith(".ollama.com")


def strip_ollama_cloud_model_alias(model_name: str | None) -> str:
    normalized = str(model_name or "").strip()
    lowered = normalized.lower()
    for suffix in ("-cloud", ":cloud"):
        if lowered.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def is_ollama_cloud_model(model_name: str | None) -> bool:
    normalized = str(model_name or "").strip()
    if not normalized:
        return False
    if is_cloud_only_model(normalized):
        return True
    stripped = strip_ollama_cloud_model_alias(normalized)
    return stripped != normalized and bool(is_cloud_only_model(stripped))


def get_ollama_cloud_runtime_model_candidates(
    model_name: str | None,
    *,
    direct_cloud: bool = False,
) -> list[str]:
    normalized = str(model_name or "").strip()
    if not normalized:
        return []

    canonical = strip_ollama_cloud_model_alias(normalized) or normalized
    candidates: list[str] = []

    def _push(value: str | None) -> None:
        item = str(value or "").strip()
        if item and item not in candidates:
            candidates.append(item)

    if direct_cloud:
        _push(canonical)
        return candidates

    _push(normalized)
    if not is_ollama_cloud_model(normalized):
        return candidates

    for alias in _OLLAMA_CLOUD_LOCAL_RUNTIME_ALIAS_OVERRIDES.get(canonical, []):
        _push(alias)

    if ":" in canonical:
        _push(f"{canonical}-cloud")
    else:
        _push(f"{canonical}:cloud")

    return candidates


def is_ollama_model_not_found_response(status_code: int | None, body: str | None) -> bool:
    if status_code != 404:
        return False
    lowered = str(body or "").strip().lower()
    return "model '" in lowered or " not found" in lowered or lowered.startswith("{\"error\":\"model ")


def resolve_ollama_request_context(
    ollama_host: str | None = None,
    *,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Résout l'hôte HTTP Ollama effectif et les headers d'auth requis."""
    requested_host = _get_ollama_host(ollama_host)
    requested_model = str(model_name or "").strip()
    api_key = str(os.environ.get("OLLAMA_API_KEY", "") or "").strip()

    direct_cloud = False
    effective_host = requested_host
    if _is_ollama_cloud_host(requested_host):
        effective_host = _OLLAMA_DIRECT_CLOUD_HOST
        direct_cloud = True
    elif (
        requested_model
        and api_key
        and is_ollama_cloud_model(requested_model)
        and _is_local_ollama_host(requested_host)
    ):
        effective_host = _OLLAMA_DIRECT_CLOUD_HOST
        direct_cloud = True

    request_model = (
        get_ollama_cloud_runtime_model_candidates(
            requested_model,
            direct_cloud=True,
        )[0]
        if direct_cloud
        else requested_model
    )
    headers: dict[str, str] = {}
    if direct_cloud and api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    return {
        "requested_host": requested_host,
        "effective_host": effective_host,
        "requested_model": requested_model,
        "request_model": request_model,
        "direct_cloud": direct_cloud,
        "api_key_present": bool(api_key),
        "ssh_key_present": bool(str(os.environ.get("OLLAMA_SSH", "") or "").strip()),
        "headers": headers,
    }
