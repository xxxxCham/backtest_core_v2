"""Profile registry and role resolution for the multi-LLM builder."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agents.model_config import is_cloud_only_model
from agents.ollama_manager import resolve_ollama_request_context
from utils.log import get_logger
from utils.model_loader import normalize_model_name

from .model_discovery import DiscoveredModel, ModelInventory
from .roles import (
    RoleAssignment,
    RolePreference,
    build_role_rotation_metadata,
    normalize_role_candidate_queue,
    role_rotation_remainder,
)

DEFAULT_MULTI_LLM_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "default_profiles.json"
DEFAULT_MULTI_LLM_PROFILE = "24GB_balanced"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
USER_MULTI_LLM_PROFILES_DIR = PROJECT_ROOT / "data" / "multi_llm_profiles"
USER_MULTI_LLM_PROFILES_ENV = "BACKTEST_MULTI_LLM_PROFILES_DIR"

logger = get_logger(__name__)


def _is_local_runtime_host(host: str | None) -> bool:
    parsed = urlparse(str(host or "").strip())
    hostname = (parsed.hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost", "::1"}


def _clone_json_like(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload))


def get_user_multi_llm_profiles_dir(
    user_profiles_dir: str | Path | None = None,
) -> Path:
    raw_path = user_profiles_dir or os.getenv(USER_MULTI_LLM_PROFILES_ENV) or USER_MULTI_LLM_PROFILES_DIR
    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _builtin_profile_names(
    config_path: str | Path | None = None,
) -> set[str]:
    path = Path(config_path or DEFAULT_MULTI_LLM_CONFIG_PATH)
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return set(payload.get("profiles", {}).keys())


def _sanitize_user_profile_filename(name: str) -> str:
    filename = re.sub(r'[<>:"/\\|?*]+', "_", str(name or "").strip())
    filename = filename.strip().strip(".")
    return filename or "profil_multi_llm"


def _normalize_saved_role_overrides(raw_value: dict[str, Any]) -> dict[str, list[str]]:
    normalized: dict[str, list[str]] = {}
    for role, raw_models in dict(raw_value or {}).items():
        models: list[str] = []
        seen: set[str] = set()
        if isinstance(raw_models, str):
            raw_iterable = [raw_models]
        else:
            raw_iterable = list(raw_models or [])
        for raw_model in raw_iterable:
            model_name = normalize_model_name(str(raw_model or "").strip())
            if not model_name or model_name in seen:
                continue
            seen.add(model_name)
            models.append(model_name)
        if models:
            normalized[str(role or "").strip()] = models
    return normalized


def _iter_user_profile_files(
    user_profiles_dir: str | Path | None = None,
) -> Iterable[Path]:
    directory = get_user_multi_llm_profiles_dir(user_profiles_dir)
    return sorted(directory.glob("*.json"))


def _load_user_profiles(
    user_profiles_dir: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for filepath in _iter_user_profile_files(user_profiles_dir):
        try:
            with open(filepath, encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Impossible de charger le profil multi-LLM %s: %s", filepath, exc)
            continue

        if not isinstance(payload, dict):
            continue
        profile_name = str(
            payload.get("name") or payload.get("profile_name") or filepath.stem,
        ).strip()
        roles_payload = payload.get("roles")
        if not profile_name or not isinstance(roles_payload, dict):
            continue
        profiles[profile_name] = {
            "description": str(payload.get("description", "") or ""),
            "roles": dict(roles_payload),
            "builtin": False,
            "derived_from": str(payload.get("derived_from", "") or ""),
            "created_at": str(payload.get("created_at", "") or ""),
            "updated_at": str(payload.get("updated_at", "") or ""),
        }
    return profiles


def load_multi_llm_config(
    config_path: str | Path | None = None,
    *,
    user_profiles_dir: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(config_path or DEFAULT_MULTI_LLM_CONFIG_PATH)
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)

    profiles = dict(payload.get("profiles", {}) or {})
    profiles.update(_load_user_profiles(user_profiles_dir))
    payload["profiles"] = profiles
    return payload


def list_profile_names(
    config_path: str | Path | None = None,
    *,
    user_profiles_dir: str | Path | None = None,
) -> list[str]:
    payload = load_multi_llm_config(
        config_path,
        user_profiles_dir=user_profiles_dir,
    )
    return sorted(payload.get("profiles", {}).keys())


def get_profile_definition(
    profile_name: str,
    config_path: str | Path | None = None,
    *,
    user_profiles_dir: str | Path | None = None,
) -> dict[str, Any]:
    payload = load_multi_llm_config(
        config_path,
        user_profiles_dir=user_profiles_dir,
    )
    profiles = payload.get("profiles", {})
    selected_profile = str(
        profile_name or payload.get("default_profile") or DEFAULT_MULTI_LLM_PROFILE,
    )
    if selected_profile not in profiles:
        raise KeyError(f"Unknown multi-LLM profile: {selected_profile}")
    return _clone_json_like(dict(profiles[selected_profile]))


def get_profile_role_pools(
    profile_name: str,
    config_path: str | Path | None = None,
    *,
    user_profiles_dir: str | Path | None = None,
) -> dict[str, list[str]]:
    profile_payload = get_profile_definition(
        profile_name,
        config_path,
        user_profiles_dir=user_profiles_dir,
    )
    role_pools: dict[str, list[str]] = {}
    for role, role_payload in dict(profile_payload.get("roles", {}) or {}).items():
        normalized_pool = _normalize_saved_role_overrides(
            {role: role_payload.get("random_pool_models", [])},
        ).get(role, [])
        if not normalized_pool:
            normalized_pool = _normalize_saved_role_overrides(
                {role: role_payload.get("preferred_models", [])},
            ).get(role, [])
        if normalized_pool:
            role_pools[str(role or "").strip()] = list(normalized_pool)
    return role_pools


def save_multi_llm_profile(
    profile_name: str,
    *,
    base_profile_name: str,
    role_overrides: dict[str, Any],
    description: str = "",
    config_path: str | Path | None = None,
    user_profiles_dir: str | Path | None = None,
) -> Path:
    normalized_name = str(profile_name or "").strip()
    if not normalized_name:
        raise ValueError("Nom de présélection requis")

    builtin_names = _builtin_profile_names(config_path)
    if normalized_name in builtin_names:
        raise ValueError(
            f"Le nom '{normalized_name}' est reserve a un profil integre",
        )

    normalized_overrides = _normalize_saved_role_overrides(role_overrides)
    if not normalized_overrides:
        raise ValueError(
            "Selectionnez au moins un role avec un ou plusieurs modeles avant de sauvegarder",
        )

    base_profile = get_profile_definition(
        base_profile_name,
        config_path,
        user_profiles_dir=user_profiles_dir,
    )
    roles_payload = dict(base_profile.get("roles", {}) or {})
    for role, selected_models in normalized_overrides.items():
        role_payload = dict(roles_payload.get(role, {}) or {})
        role_payload["backend"] = str(role_payload.get("backend", "ollama") or "ollama")
        role_payload["preferred_models"] = list(selected_models)
        role_payload["random_pool_models"] = list(selected_models)
        role_payload["fallback_models"] = list(role_payload.get("fallback_models", []) or [])
        role_payload["required"] = bool(role_payload.get("required", True))
        roles_payload[role] = role_payload

    directory = get_user_multi_llm_profiles_dir(user_profiles_dir)
    filepath = directory / f"{_sanitize_user_profile_filename(normalized_name)}.json"
    timestamp = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    payload = {
        "name": normalized_name,
        "description": str(description or "").strip() or f"Preset utilisateur derive de {base_profile_name}.",
        "derived_from": str(base_profile_name or "").strip(),
        "roles": roles_payload,
        "updated_at": timestamp,
    }
    if filepath.exists():
        try:
            with open(filepath, encoding="utf-8") as handle:
                existing_payload = json.load(handle)
        except Exception:
            existing_payload = {}
        payload["created_at"] = str(existing_payload.get("created_at", "") or timestamp)
    else:
        payload["created_at"] = timestamp

    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    return filepath


def delete_multi_llm_profile(
    profile_name: str,
    *,
    config_path: str | Path | None = None,
    user_profiles_dir: str | Path | None = None,
) -> bool:
    normalized_name = str(profile_name or "").strip()
    if not normalized_name:
        raise ValueError("Nom de présélection requis")

    config_file = Path(config_path or DEFAULT_MULTI_LLM_CONFIG_PATH)
    builtin_names = _builtin_profile_names(config_file)
    if normalized_name in builtin_names:
        with open(config_file, encoding="utf-8") as handle:
            payload = json.load(handle)

        profiles = dict(payload.get("profiles", {}) or {})
        if normalized_name not in profiles:
            return False

        profiles.pop(normalized_name, None)
        payload["profiles"] = profiles

        current_default = str(
            payload.get("default_profile") or DEFAULT_MULTI_LLM_PROFILE,
        ).strip()
        if current_default == normalized_name:
            replacement_default = ""
            if DEFAULT_MULTI_LLM_PROFILE in profiles:
                replacement_default = DEFAULT_MULTI_LLM_PROFILE
            elif profiles:
                replacement_default = sorted(profiles.keys())[0]
            payload["default_profile"] = replacement_default

        with open(config_file, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        return True

    directory = get_user_multi_llm_profiles_dir(user_profiles_dir)
    filepath = directory / f"{_sanitize_user_profile_filename(normalized_name)}.json"
    if not filepath.exists():
        return False
    filepath.unlink()
    return True


def _role_preference_from_payload(role: str, payload: dict[str, Any]) -> RolePreference:
    return RolePreference(
        role=role,
        backend=str(payload.get("backend", "ollama") or "ollama"),
        preferred_models=list(payload.get("preferred_models", []) or []),
        fallback_models=list(payload.get("fallback_models", []) or []),
        required=bool(payload.get("required", True)),
        description=str(payload.get("description", "") or ""),
    )


def _normalize_override_candidates(override_model: Any) -> list[str]:
    if isinstance(override_model, str):
        normalized = normalize_model_name(str(override_model or "").strip()) or str(override_model or "").strip()
        return [normalized] if normalized else []
    if isinstance(override_model, (list, tuple, set)):
        ordered: list[str] = []
        seen: set[str] = set()
        for raw_candidate in override_model:
            normalized = normalize_model_name(str(raw_candidate or "").strip()) or str(raw_candidate or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered
    return []


def _candidate_order(
    preference: RolePreference,
    override_model: Any,
) -> list[str]:
    ordered: list[str] = []
    override_candidates = _normalize_override_candidates(override_model)
    if override_candidates:
        ordered.extend(override_candidates)
    else:
        ordered.extend(preference.preferred_models)
        ordered.extend(preference.fallback_models)
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in ordered:
        normalized = normalize_model_name(str(candidate or "").strip()) or str(candidate or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _remaining_candidates(
    candidates: list[str],
    selected_candidate: str,
) -> list[str]:
    normalized_queue = normalize_role_candidate_queue(candidates)
    return role_rotation_remainder(normalized_queue, selected_candidate)


def resolve_profile_assignments(
    profile_name: str | None,
    inventory: ModelInventory,
    *,
    config_path: str | Path | None = None,
    user_profiles_dir: str | Path | None = None,
    role_overrides: dict[str, Any] | None = None,
    require_live_ollama: bool = False,
) -> dict[str, Any]:
    payload = load_multi_llm_config(
        config_path,
        user_profiles_dir=user_profiles_dir,
    )
    profiles = payload.get("profiles", {})
    selected_profile = str(
        profile_name or payload.get("default_profile") or DEFAULT_MULTI_LLM_PROFILE,
    )
    if selected_profile not in profiles:
        raise KeyError(f"Unknown multi-LLM profile: {selected_profile}")

    profile_payload = profiles[selected_profile]
    overrides = dict(role_overrides or {})
    assignments: list[RoleAssignment] = []
    missing_roles: list[str] = []

    for role, role_payload in profile_payload.get("roles", {}).items():
        preference = _role_preference_from_payload(role, role_payload)
        requested_candidates = _candidate_order(preference, overrides.get(role))
        resolved_model = None
        resolved_request = requested_candidates[0] if requested_candidates else ""
        deferred_non_live_match = None
        deferred_cloud_candidate = ""
        for candidate in requested_candidates:
            normalized_candidate = normalize_model_name(str(candidate or "").strip()) or str(candidate or "").strip()
            candidate_model = inventory.find(candidate)
            if is_cloud_only_model(normalized_candidate):
                request_ctx = resolve_ollama_request_context(
                    getattr(inventory, "live_ollama_host", None),
                    model_name=normalized_candidate,
                )
                direct_cloud_available = bool(
                    request_ctx.get("direct_cloud") and request_ctx.get("api_key_present"),
                )
                if candidate_model is not None and (
                    not require_live_ollama or not inventory.live_ollama_reachable or candidate_model.live
                ):
                    resolved_model = candidate_model
                    resolved_request = normalized_candidate
                    break
                if direct_cloud_available:
                    resolved_model = DiscoveredModel(
                        name=normalized_candidate,
                        backend=preference.backend,
                        source="ollama_cloud_direct",
                        verified_available=True,
                        path="",
                        exists_on_disk=False,
                        live=True,
                        aliases=[normalized_candidate],
                        role_hints=[],
                        metadata={
                            "cloud_only": True,
                            "direct_cloud": True,
                            "effective_host": str(request_ctx.get("effective_host") or ""),
                        },
                    )
                    resolved_request = normalized_candidate
                    break
                if require_live_ollama and inventory.live_ollama_reachable and _is_local_runtime_host(
                    request_ctx.get("requested_host") or getattr(inventory, "live_ollama_host", None),
                ):
                    resolved_model = DiscoveredModel(
                        name=normalized_candidate,
                        backend=preference.backend,
                        source="ollama_cloud_local_runtime",
                        verified_available=True,
                        path="",
                        exists_on_disk=False,
                        live=True,
                        aliases=[normalized_candidate],
                        role_hints=[],
                        metadata={
                            "cloud_only": True,
                            "local_runtime_auth": True,
                            "requested_host": str(request_ctx.get("requested_host") or ""),
                        },
                    )
                    resolved_request = normalized_candidate
                    break
                if require_live_ollama and inventory.live_ollama_reachable:
                    if not deferred_cloud_candidate:
                        deferred_cloud_candidate = normalized_candidate
                    resolved_request = normalized_candidate
                    continue
                resolved_model = DiscoveredModel(
                    name=normalized_candidate,
                    backend=preference.backend,
                    source="ollama_cloud",
                    verified_available=True,
                    path="",
                    exists_on_disk=False,
                    live=bool(inventory.live_ollama_reachable),
                    aliases=[normalized_candidate],
                    role_hints=[],
                    metadata={"cloud_only": True},
                )
                resolved_request = normalized_candidate
                break
            if candidate_model is None:
                continue
            if (
                preference.backend == "ollama"
                and require_live_ollama
                and inventory.live_ollama_reachable
                and not candidate_model.live
            ):
                if deferred_non_live_match is None:
                    deferred_non_live_match = (candidate, candidate_model)
                continue
            resolved_model = candidate_model
            resolved_request = candidate
            break

        if resolved_model is None and deferred_non_live_match is not None:
            resolved_request, deferred_model = deferred_non_live_match
            assignment = RoleAssignment(
                role=role,
                backend=preference.backend,
                requested_model=resolved_request,
                required=preference.required,
                resolved_model=deferred_model.name,
                verified=deferred_model.verified_available,
                source=deferred_model.source,
                reason="found locally but not exposed by current Ollama host",
                discovered_path=deferred_model.path,
                live=deferred_model.live,
                install_required=False,
                alternatives=_remaining_candidates(
                    requested_candidates,
                    resolved_request,
                ),
                metadata=build_role_rotation_metadata(
                    dict(deferred_model.metadata or {}),
                    queue=requested_candidates,
                    selected_candidate=resolved_request,
                ),
            )
        elif resolved_model is None:
            unresolved_cloud_request = deferred_cloud_candidate or resolved_request
            assignment = RoleAssignment(
                role=role,
                backend=preference.backend,
                requested_model=unresolved_cloud_request,
                required=preference.required,
                reason=(
                    "cloud candidate not exposed by current Ollama host"
                    if deferred_cloud_candidate
                    else ("no local match found" if requested_candidates else "no candidate declared for role")
                ),
                install_required=bool(requested_candidates),
                alternatives=_remaining_candidates(
                    requested_candidates,
                    unresolved_cloud_request,
                )
                if requested_candidates
                else [],
                metadata=build_role_rotation_metadata(
                    {},
                    queue=requested_candidates,
                    selected_candidate=unresolved_cloud_request,
                ),
            )
        elif not resolved_model.verified_available:
            assignment = RoleAssignment(
                role=role,
                backend=preference.backend,
                requested_model=resolved_request,
                required=preference.required,
                resolved_model=resolved_model.name,
                source=resolved_model.source,
                reason="catalog reference found but not verified locally",
                discovered_path=resolved_model.path,
                alternatives=_remaining_candidates(
                    requested_candidates,
                    resolved_request,
                ),
                metadata=build_role_rotation_metadata(
                    dict(resolved_model.metadata or {}),
                    queue=requested_candidates,
                    selected_candidate=resolved_request,
                ),
                live=resolved_model.live,
                install_required=True,
            )
        else:
            assignment = RoleAssignment(
                role=role,
                backend=preference.backend,
                requested_model=resolved_request,
                required=preference.required,
                resolved_model=resolved_model.name,
                available=True,
                verified=True,
                source=resolved_model.source,
                reason="resolved locally",
                discovered_path=resolved_model.path,
                alternatives=_remaining_candidates(
                    requested_candidates,
                    resolved_request,
                ),
                metadata=build_role_rotation_metadata(
                    dict(resolved_model.metadata or {}),
                    queue=requested_candidates,
                    selected_candidate=resolved_request,
                ),
                live=resolved_model.live,
                install_required=False,
            )

        if preference.required and not assignment.available:
            missing_roles.append(role)
        assignments.append(assignment)

    return {
        "profile_name": selected_profile,
        "description": str(profile_payload.get("description", "") or ""),
        "config_path": str(Path(config_path or DEFAULT_MULTI_LLM_CONFIG_PATH)),
        "assignments": assignments,
        "missing_roles": missing_roles,
        "inventory_summary": inventory.summary(),
    }


def assignments_to_rows(assignments: Iterable[RoleAssignment]) -> list[dict[str, Any]]:
    return [assignment.to_dict() for assignment in assignments]
