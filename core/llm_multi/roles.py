"""Shared role dataclasses for the multi-LLM builder mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

MULTI_LLM_ROLES = (
    "idea_llm",
    "builder_llm",
    "critic_llm",
    "risk_llm",
    "execution_router_llm",
)


@dataclass(frozen=True)
class RolePreference:
    """Desired backend and model candidates for a specialized role."""

    role: str
    backend: str = "ollama"
    preferred_models: List[str] = field(default_factory=list)
    fallback_models: List[str] = field(default_factory=list)
    required: bool = True
    description: str = ""


@dataclass
class RoleAssignment:
    """Resolved runtime model for a role."""

    role: str
    backend: str
    requested_model: str
    resolved_model: str = ""
    available: bool = False
    verified: bool = False
    source: str = ""
    reason: str = ""
    discovered_path: str = ""
    live: bool = False
    install_required: bool = False
    alternatives: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "backend": self.backend,
            "requested_model": self.requested_model,
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
