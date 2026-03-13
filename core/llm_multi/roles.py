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

SIMPLE_MULTI_LLM_ACTIVE_ROLES = (
    "idea_llm",
    "builder_llm",
    "critic_llm",
    "risk_llm",
)

MULTI_LLM_ROLE_DETAILS = {
    "idea_llm": {
        "label": "Ideation",
        "stage": "Amont",
        "purpose": "Recoit univers marches/TF/indicateurs et historique recent, puis propose un objectif de strategie testable.",
        "summary": "Propose une idee de strategie a partir de l'univers disponible.",
        "active_in_simple_mode": "true",
    },
    "builder_llm": {
        "label": "Builder",
        "stage": "Execution principale",
        "purpose": "Recoit objectif, contexte marche, code precedent, metriques et diagnostic, puis produit ou ajuste la strategie.",
        "summary": "Construit ou ajuste la strategie avec le contrat complet du Builder.",
        "active_in_simple_mode": "true",
    },
    "critic_llm": {
        "label": "Critique",
        "stage": "Post-run",
        "purpose": "Recoit le resume deterministe de session et audite robustesse, overfitting, qualite des signaux et tests manquants.",
        "summary": "Audit methodologique du resultat et de sa robustesse.",
        "active_in_simple_mode": "true",
    },
    "risk_llm": {
        "label": "Risk",
        "stage": "Post-run",
        "purpose": "Recoit le resume deterministe de session et evalue drawdown, fragilite, nombre de trades et risque de comportement de trading.",
        "summary": "Evalue le risque de trading a partir des resultats du run.",
        "active_in_simple_mode": "true",
    },
    "execution_router_llm": {
        "label": "Routeur deterministe",
        "stage": "Controle de boucle local",
        "purpose": "N'est plus un LLM actif en mode simple; la suite de boucle est decidee localement de maniere deterministe.",
        "summary": "Decision locale accept/iterate/recover.",
        "active_in_simple_mode": "false",
    },
}


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
    required: bool = True
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


def get_multi_llm_role_details(role: str) -> Dict[str, str]:
    return dict(MULTI_LLM_ROLE_DETAILS.get(str(role or "").strip(), {}))
