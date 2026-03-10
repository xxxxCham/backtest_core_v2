"""Profile registry and role resolution for the multi-LLM builder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .model_discovery import ModelInventory
from .roles import RoleAssignment, RolePreference

DEFAULT_MULTI_LLM_CONFIG_PATH = (
    Path(__file__).resolve().parent / "config" / "default_profiles.json"
)
DEFAULT_MULTI_LLM_PROFILE = "24GB_balanced"


def load_multi_llm_config(config_path: Optional[str | Path] = None) -> Dict[str, Any]:
    path = Path(config_path or DEFAULT_MULTI_LLM_CONFIG_PATH)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def list_profile_names(config_path: Optional[str | Path] = None) -> List[str]:
    payload = load_multi_llm_config(config_path)
    return sorted(payload.get("profiles", {}).keys())


def _role_preference_from_payload(role: str, payload: Dict[str, Any]) -> RolePreference:
    return RolePreference(
        role=role,
        backend=str(payload.get("backend", "ollama") or "ollama"),
        preferred_models=list(payload.get("preferred_models", []) or []),
        fallback_models=list(payload.get("fallback_models", []) or []),
        required=bool(payload.get("required", True)),
        description=str(payload.get("description", "") or ""),
    )


def _candidate_order(
    preference: RolePreference,
    override_model: Optional[str],
) -> List[str]:
    ordered: List[str] = []
    if override_model:
        ordered.append(str(override_model).strip())
    ordered.extend(preference.preferred_models)
    ordered.extend(preference.fallback_models)
    seen: set[str] = set()
    unique: List[str] = []
    for candidate in ordered:
        normalized = str(candidate or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _remaining_candidates(
    candidates: List[str],
    selected_candidate: str,
) -> List[str]:
    if selected_candidate in candidates:
        idx = candidates.index(selected_candidate)
        return candidates[idx + 1 :]
    return candidates[1:]


def resolve_profile_assignments(
    profile_name: Optional[str],
    inventory: ModelInventory,
    *,
    config_path: Optional[str | Path] = None,
    role_overrides: Optional[Dict[str, str]] = None,
    require_live_ollama: bool = False,
) -> Dict[str, Any]:
    payload = load_multi_llm_config(config_path)
    profiles = payload.get("profiles", {})
    selected_profile = str(
        profile_name or payload.get("default_profile") or DEFAULT_MULTI_LLM_PROFILE
    )
    if selected_profile not in profiles:
        raise KeyError(f"Unknown multi-LLM profile: {selected_profile}")

    profile_payload = profiles[selected_profile]
    overrides = dict(role_overrides or {})
    assignments: List[RoleAssignment] = []
    missing_roles: List[str] = []

    for role, role_payload in profile_payload.get("roles", {}).items():
        preference = _role_preference_from_payload(role, role_payload)
        requested_candidates = _candidate_order(preference, overrides.get(role))
        resolved_model = None
        resolved_request = requested_candidates[0] if requested_candidates else ""
        deferred_non_live_match = None
        for candidate in requested_candidates:
            candidate_model = inventory.find(candidate)
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
                metadata=deferred_model.metadata,
            )
        elif resolved_model is None:
            assignment = RoleAssignment(
                role=role,
                backend=preference.backend,
                requested_model=resolved_request,
                reason=(
                    "no local match found"
                    if requested_candidates
                    else "no candidate declared for role"
                ),
                install_required=bool(requested_candidates),
                alternatives=_remaining_candidates(
                    requested_candidates,
                    resolved_request,
                )
                if requested_candidates
                else [],
            )
        elif not resolved_model.verified_available:
            assignment = RoleAssignment(
                role=role,
                backend=preference.backend,
                requested_model=resolved_request,
                resolved_model=resolved_model.name,
                source=resolved_model.source,
                reason="catalog reference found but not verified locally",
                discovered_path=resolved_model.path,
                alternatives=_remaining_candidates(
                    requested_candidates,
                    resolved_request,
                ),
                metadata=resolved_model.metadata,
                live=resolved_model.live,
                install_required=True,
            )
        else:
            assignment = RoleAssignment(
                role=role,
                backend=preference.backend,
                requested_model=resolved_request,
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
                metadata=resolved_model.metadata,
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


def assignments_to_rows(assignments: Iterable[RoleAssignment]) -> List[Dict[str, Any]]:
    return [assignment.to_dict() for assignment in assignments]
