"""Shared role dataclasses for the multi-LLM builder mode."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from utils.model_loader import normalize_model_name

MULTI_LLM_ROLES = (
    "builder_llm",
    "supervisor_llm",
)

SIMPLE_MULTI_LLM_ACTIVE_ROLES = (
    "builder_llm",
    "supervisor_llm",
)

MULTI_LLM_ROLE_DETAILS = {
    "builder_llm": {
        "label": "Builder",
        "stage": "Execution principale",
        "purpose": "Recoit objectif, contexte marche, code precedent, metriques et diagnostic, puis produit ou ajuste la strategie.",
        "summary": "Construit ou ajuste la strategie avec le contrat complet du Builder.",
        "active_in_simple_mode": "true",
    },
    "supervisor_llm": {
        "label": "Superviseur",
        "stage": "Objectif et controle",
        "purpose": "Recoit univers marches/TF/indicateurs, historique recent et resultats de session; propose l'objectif, audite robustesse/risque et recommande accept/iterate/recover.",
        "summary": "Fusionne ideation, critique, risque et decision de boucle.",
        "active_in_simple_mode": "true",
    },
}


@dataclass(frozen=True)
class RolePreference:
    """Desired backend and model candidates for a specialized role."""

    role: str
    backend: str = "ollama"
    preferred_models: list[str] = field(default_factory=list)
    fallback_models: list[str] = field(default_factory=list)
    required: bool = True
    description: str = ""


@dataclass
class RoleAssignment:
    """Resolved runtime model for a role."""

    role: str
    backend: str
    requested_model: str
    required: bool = True
    resolved_model: str = ""
    available: bool = False
    verified: bool = False
    source: str = ""
    reason: str = ""
    discovered_path: str = ""
    live: bool = False
    install_required: bool = False
    alternatives: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "backend": self.backend,
            "requested_model": self.requested_model,
            "required": self.required,
            "resolved_model": self.resolved_model,
            "available": self.available,
            "verified": self.verified,
            "source": self.source,
            "reason": self.reason,
            "discovered_path": self.discovered_path,
            "live": self.live,
            "install_required": self.install_required,
            "alternatives": list(self.alternatives),
            "metadata": dict(self.metadata),
        }


def get_multi_llm_role_details(role: str) -> dict[str, str]:
    return dict(MULTI_LLM_ROLE_DETAILS.get(str(role or "").strip(), {}))


def normalize_role_candidate(candidate: Any) -> str:
    raw_candidate = str(candidate or "").strip()
    return normalize_model_name(raw_candidate) or raw_candidate


def normalize_role_candidate_queue(candidates: Iterable[Any]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw_candidate in list(candidates or []):
        normalized = normalize_role_candidate(raw_candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def role_rotation_remainder(
    candidates: Iterable[Any],
    selected_candidate: Any = "",
    *,
    selected_index: int | None = None,
) -> list[str]:
    queue = normalize_role_candidate_queue(candidates)
    if not queue:
        return []
    if selected_index is None:
        normalized_selected = normalize_role_candidate(selected_candidate)
        selected_index = queue.index(normalized_selected) if normalized_selected in queue else 0
    if not (0 <= int(selected_index) < len(queue)):
        selected_index = 0
    return [
        queue[(int(selected_index) + offset) % len(queue)]
        for offset in range(1, len(queue))
    ]


def resolve_assignment_rotation_queue(assignment: RoleAssignment) -> list[str]:
    metadata = dict(getattr(assignment, "metadata", {}) or {})
    queue = normalize_role_candidate_queue(metadata.get("rotation_queue") or [])
    if queue:
        return queue
    inferred_queue = normalize_role_candidate_queue(
        [
            getattr(assignment, "requested_model", ""),
            *list(getattr(assignment, "alternatives", []) or []),
        ],
    )
    if inferred_queue:
        return inferred_queue
    current_candidate = normalize_role_candidate(
        getattr(assignment, "requested_model", "") or getattr(assignment, "resolved_model", ""),
    )
    return [current_candidate] if current_candidate else []


def resolve_assignment_rotation_index(
    assignment: RoleAssignment,
    *,
    queue: Iterable[Any] | None = None,
) -> int:
    normalized_queue = normalize_role_candidate_queue(
        queue if queue is not None else resolve_assignment_rotation_queue(assignment),
    )
    if not normalized_queue:
        return 0
    metadata = dict(getattr(assignment, "metadata", {}) or {})
    current_candidate = normalize_role_candidate(
        getattr(assignment, "requested_model", "") or getattr(assignment, "resolved_model", ""),
    )
    raw_index = metadata.get("rotation_index")
    try:
        index = int(raw_index)
    except (TypeError, ValueError):
        index = -1
    if current_candidate in normalized_queue:
        return normalized_queue.index(current_candidate)
    if 0 <= index < len(normalized_queue):
        return index
    return 0


def build_role_rotation_metadata(
    metadata: dict[str, Any] | None,
    *,
    queue: Iterable[Any],
    selected_candidate: Any,
    mission_count: int | None = None,
) -> dict[str, Any]:
    merged = dict(metadata or {})
    normalized_queue = normalize_role_candidate_queue(queue)
    normalized_selected = normalize_role_candidate(selected_candidate)
    if normalized_queue:
        if normalized_selected in normalized_queue:
            selected_index = normalized_queue.index(normalized_selected)
        else:
            selected_index = 0
        merged["rotation_queue"] = list(normalized_queue)
        merged["rotation_enabled"] = len(normalized_queue) > 1
        merged["rotation_index"] = selected_index
        if mission_count is None:
            raw_mission_count = merged.get("rotation_mission_count", 0)
            try:
                mission_count = int(raw_mission_count)
            except (TypeError, ValueError):
                mission_count = 0
        merged["rotation_mission_count"] = max(0, int(mission_count or 0))
    return merged
