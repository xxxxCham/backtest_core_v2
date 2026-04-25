"""Module-ID: agents.llm_router

Purpose: Définir la topologie LLM multi-host/multi-GPU et résoudre les routes
         par rôle d'agent ou phase Builder.

Role in pipeline: orchestration / routing

Key components: LLMEndpointConfig, LLMTopologyConfig, ResolvedLLMRoute

Inputs: host primaire/contrôle, role, phase, fallback host

Outputs: route résolue avec host effectif, gpu_target et indicateur de fallback

Dependencies: os, dataclasses

Conventions: phase 1 = routes explicites, fallback vers route par défaut,
             sérialisation JSON-friendly via to_dict()/from_dict().
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_PRIMARY_ROUTE = "builder_primary"
DEFAULT_CONTROL_ROUTE = "control"
DEFAULT_ROUTE_NAME = "default"
TOPOLOGY_PROFILE_SINGLE_HOST = "single_host"
TOPOLOGY_PROFILE_PHASE1_COOPERATIVE = "phase1_cooperative"


def normalize_ollama_host(host: str | None) -> str:
    value = str(host or "").strip()
    if not value:
        value = DEFAULT_OLLAMA_HOST
    if not value.startswith(("http://", "https://")):
        value = f"http://{value}"
    return value.rstrip("/")


@dataclass
class LLMEndpointConfig:
    """Décrit un endpoint Ollama routable."""

    name: str
    ollama_host: str
    gpu_target: str = "auto"
    enabled: bool = True
    description: str = ""

    def __post_init__(self) -> None:
        self.ollama_host = normalize_ollama_host(self.ollama_host)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ollama_host": self.ollama_host,
            "gpu_target": self.gpu_target,
            "enabled": self.enabled,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMEndpointConfig:
        return cls(
            name=str(data.get("name", "") or ""),
            ollama_host=str(
                data.get("ollama_host", DEFAULT_OLLAMA_HOST) or DEFAULT_OLLAMA_HOST,
            ),
            gpu_target=str(data.get("gpu_target", "auto") or "auto"),
            enabled=bool(data.get("enabled", True)),
            description=str(data.get("description", "") or ""),
        )


@dataclass
class ResolvedLLMRoute:
    """Résolution effective d'une route LLM."""

    route_name: str
    endpoint_name: str
    ollama_host: str
    gpu_target: str
    source_kind: str
    source_value: str
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_name": self.route_name,
            "endpoint_name": self.endpoint_name,
            "ollama_host": self.ollama_host,
            "gpu_target": self.gpu_target,
            "source_kind": self.source_kind,
            "source_value": self.source_value,
            "fallback_used": self.fallback_used,
        }


def _default_primary_host() -> str:
    return normalize_ollama_host(os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST))


def _default_control_host(primary_host: str | None = None) -> str:
    return normalize_ollama_host(
        os.environ.get("OLLAMA_CONTROL_HOST", primary_host or _default_primary_host()),
    )


def _default_role_routes() -> dict[str, str]:
    return {
        "analyst": DEFAULT_PRIMARY_ROUTE,
        "strategist": DEFAULT_PRIMARY_ROUTE,
        "critic": DEFAULT_CONTROL_ROUTE,
        "validator": DEFAULT_CONTROL_ROUTE,
    }


def _default_builder_phase_routes() -> dict[str, str]:
    return {
        "default": DEFAULT_PRIMARY_ROUTE,
        "proposal": DEFAULT_PRIMARY_ROUTE,
        "code": DEFAULT_PRIMARY_ROUTE,
        "retry_proposal": DEFAULT_PRIMARY_ROUTE,
        "retry_proposal_nojson": DEFAULT_PRIMARY_ROUTE,
        "retry_code": DEFAULT_PRIMARY_ROUTE,
        "retry_code_runtime": DEFAULT_PRIMARY_ROUTE,
        "objective_gen": DEFAULT_PRIMARY_ROUTE,
        "analysis": DEFAULT_CONTROL_ROUTE,
        "pre_reflection": DEFAULT_CONTROL_ROUTE,
    }


@dataclass
class LLMTopologyConfig:
    """Topologie partagée Builder + orchestrateur pour la phase 1."""

    endpoints: dict[str, LLMEndpointConfig] = field(default_factory=dict)
    role_routes: dict[str, str] = field(default_factory=_default_role_routes)
    builder_phase_routes: dict[str, str] = field(
        default_factory=_default_builder_phase_routes,
    )
    default_route: str = DEFAULT_PRIMARY_ROUTE
    fallback_to_default: bool = True
    trace_only: bool = True
    profile: str = TOPOLOGY_PROFILE_PHASE1_COOPERATIVE

    def __post_init__(self) -> None:
        if not self.endpoints:
            primary_host = _default_primary_host()
            control_host = _default_control_host(primary_host)
            self.endpoints = {
                DEFAULT_ROUTE_NAME: LLMEndpointConfig(
                    name=DEFAULT_ROUTE_NAME,
                    ollama_host=primary_host,
                    gpu_target="auto",
                    description="Route de secours partagée",
                ),
                DEFAULT_PRIMARY_ROUTE: LLMEndpointConfig(
                    name=DEFAULT_PRIMARY_ROUTE,
                    ollama_host=primary_host,
                    gpu_target=os.environ.get("OLLAMA_PRIMARY_GPU", "GPU-0"),
                    description=("Endpoint productif pour proposal/code/analyst/strategist"),
                ),
                DEFAULT_CONTROL_ROUTE: LLMEndpointConfig(
                    name=DEFAULT_CONTROL_ROUTE,
                    ollama_host=control_host,
                    gpu_target=os.environ.get("OLLAMA_CONTROL_GPU", "GPU-1"),
                    description=("Endpoint de contrôle pour critic/validator/analysis"),
                ),
            }
        else:
            self.endpoints = {
                name: (endpoint if isinstance(endpoint, LLMEndpointConfig) else LLMEndpointConfig.from_dict(endpoint))
                for name, endpoint in self.endpoints.items()
            }

        if self.default_route not in self.endpoints:
            self.default_route = (
                DEFAULT_PRIMARY_ROUTE if DEFAULT_PRIMARY_ROUTE in self.endpoints else next(iter(self.endpoints))
            )

    @classmethod
    def phase1_default(
        cls,
        *,
        primary_host: str | None = None,
        control_host: str | None = None,
        primary_gpu_target: str = "GPU-0",
        control_gpu_target: str = "GPU-1",
        trace_only: bool = True,
    ) -> LLMTopologyConfig:
        primary = normalize_ollama_host(primary_host or _default_primary_host())
        control = normalize_ollama_host(control_host or _default_control_host(primary))
        return cls(
            endpoints={
                DEFAULT_ROUTE_NAME: LLMEndpointConfig(
                    name=DEFAULT_ROUTE_NAME,
                    ollama_host=primary,
                    gpu_target="auto",
                    description="Route de secours partagée",
                ),
                DEFAULT_PRIMARY_ROUTE: LLMEndpointConfig(
                    name=DEFAULT_PRIMARY_ROUTE,
                    ollama_host=primary,
                    gpu_target=primary_gpu_target,
                    description=("Endpoint productif pour proposal/code/analyst/strategist"),
                ),
                DEFAULT_CONTROL_ROUTE: LLMEndpointConfig(
                    name=DEFAULT_CONTROL_ROUTE,
                    ollama_host=control,
                    gpu_target=control_gpu_target,
                    description=("Endpoint de contrôle pour critic/validator/analysis"),
                ),
            },
            role_routes=_default_role_routes(),
            builder_phase_routes=_default_builder_phase_routes(),
            default_route=DEFAULT_PRIMARY_ROUTE,
            fallback_to_default=True,
            trace_only=trace_only,
            profile=TOPOLOGY_PROFILE_PHASE1_COOPERATIVE,
        )

    @classmethod
    def single_host_default(
        cls,
        *,
        primary_host: str | None = None,
        primary_gpu_target: str = "auto",
        trace_only: bool = True,
    ) -> LLMTopologyConfig:
        primary = normalize_ollama_host(primary_host or _default_primary_host())
        return cls(
            endpoints={
                DEFAULT_ROUTE_NAME: LLMEndpointConfig(
                    name=DEFAULT_ROUTE_NAME,
                    ollama_host=primary,
                    gpu_target=primary_gpu_target,
                    description="Route de secours partagée",
                ),
                DEFAULT_PRIMARY_ROUTE: LLMEndpointConfig(
                    name=DEFAULT_PRIMARY_ROUTE,
                    ollama_host=primary,
                    gpu_target=primary_gpu_target,
                    description="Endpoint unique partagé par toutes les phases",
                ),
                DEFAULT_CONTROL_ROUTE: LLMEndpointConfig(
                    name=DEFAULT_CONTROL_ROUTE,
                    ollama_host=primary,
                    gpu_target=primary_gpu_target,
                    description="Route logique de contrôle pointant sur le même endpoint",
                ),
            },
            role_routes=_default_role_routes(),
            builder_phase_routes=_default_builder_phase_routes(),
            default_route=DEFAULT_PRIMARY_ROUTE,
            fallback_to_default=True,
            trace_only=trace_only,
            profile=TOPOLOGY_PROFILE_SINGLE_HOST,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoints": {name: endpoint.to_dict() for name, endpoint in self.endpoints.items()},
            "role_routes": dict(self.role_routes),
            "builder_phase_routes": dict(self.builder_phase_routes),
            "default_route": self.default_route,
            "fallback_to_default": self.fallback_to_default,
            "trace_only": self.trace_only,
            "profile": self.profile,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LLMTopologyConfig:
        if not data:
            return cls.phase1_default()
        endpoints = {
            name: LLMEndpointConfig.from_dict(endpoint) for name, endpoint in (data.get("endpoints") or {}).items()
        }
        return cls(
            endpoints=endpoints,
            role_routes=dict(data.get("role_routes") or _default_role_routes()),
            builder_phase_routes=dict(
                data.get("builder_phase_routes") or _default_builder_phase_routes(),
            ),
            default_route=str(
                data.get("default_route", DEFAULT_PRIMARY_ROUTE) or DEFAULT_PRIMARY_ROUTE,
            ),
            fallback_to_default=bool(data.get("fallback_to_default", True)),
            trace_only=bool(data.get("trace_only", True)),
            profile=str(
                data.get(
                    "profile",
                    TOPOLOGY_PROFILE_PHASE1_COOPERATIVE,
                )
                or TOPOLOGY_PROFILE_PHASE1_COOPERATIVE,
            ),
        )

    def get_endpoint(self, route_name: str) -> LLMEndpointConfig | None:
        route = str(route_name or "").strip()
        endpoint = self.endpoints.get(route)
        if endpoint and endpoint.enabled:
            return endpoint
        return None

    def _resolve_route(
        self,
        route_name: str | None,
        *,
        source_kind: str,
        source_value: str,
        fallback_host: str | None = None,
    ) -> ResolvedLLMRoute:
        requested = str(route_name or "").strip() or self.default_route
        endpoint = self.get_endpoint(requested)
        fallback_used = False

        if endpoint is None and self.fallback_to_default:
            fallback_used = True
            endpoint = self.get_endpoint(self.default_route)
            requested = self.default_route

        if endpoint is None:
            fallback_used = True
            endpoint = LLMEndpointConfig(
                name=DEFAULT_ROUTE_NAME,
                ollama_host=fallback_host or _default_primary_host(),
                gpu_target="auto",
                description="Fallback implicite",
            )
            requested = endpoint.name

        return ResolvedLLMRoute(
            route_name=requested,
            endpoint_name=endpoint.name,
            ollama_host=endpoint.ollama_host,
            gpu_target=endpoint.gpu_target,
            source_kind=source_kind,
            source_value=source_value,
            fallback_used=fallback_used,
        )

    def resolve_role_route(
        self,
        role: str,
        *,
        fallback_host: str | None = None,
    ) -> ResolvedLLMRoute:
        role_key = str(role or "").strip().lower() or "unknown"
        route_name = self.role_routes.get(role_key, self.default_route)
        return self._resolve_route(
            route_name,
            source_kind="role",
            source_value=role_key,
            fallback_host=fallback_host,
        )

    def resolve_builder_phase_route(
        self,
        phase: str,
        *,
        fallback_host: str | None = None,
    ) -> ResolvedLLMRoute:
        phase_key = str(phase or "").strip() or "default"
        route_name = self.builder_phase_routes.get(phase_key)
        if route_name is None:
            base_phase = phase_key.split("_")[0] if phase_key else "default"
            route_name = self.builder_phase_routes.get(
                base_phase,
                self.builder_phase_routes.get("default", self.default_route),
            )
        return self._resolve_route(
            route_name,
            source_kind="phase",
            source_value=phase_key,
            fallback_host=fallback_host,
        )


def build_phase1_topology(
    *,
    primary_host: str | None = None,
    control_host: str | None = None,
    primary_gpu_target: str = "GPU-0",
    control_gpu_target: str = "GPU-1",
    trace_only: bool = True,
) -> LLMTopologyConfig:
    """Construit la topologie phase 1 standard."""
    return LLMTopologyConfig.phase1_default(
        primary_host=primary_host,
        control_host=control_host,
        primary_gpu_target=primary_gpu_target,
        control_gpu_target=control_gpu_target,
        trace_only=trace_only,
    )


def build_single_host_topology(
    *,
    primary_host: str | None = None,
    primary_gpu_target: str = "auto",
    trace_only: bool = True,
) -> LLMTopologyConfig:
    """Construit une topologie mono-endpoint pour préserver le comportement historique."""
    return LLMTopologyConfig.single_host_default(
        primary_host=primary_host,
        primary_gpu_target=primary_gpu_target,
        trace_only=trace_only,
    )
