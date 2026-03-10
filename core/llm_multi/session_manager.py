"""Multi-LLM session manager that orchestrates the existing deterministic builder."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from agents.llm_client import LLMConfig, LLMMessage, LLMProvider, create_llm_client
from agents.strategy_builder import generate_random_objective, sanitize_objective_text

from .adapters.strategy_builder_adapter import summarize_builder_session
from .model_discovery import ModelInventory, discover_local_models
from .prompt_templates import (
    build_critic_system_prompt,
    build_critic_user_prompt,
    build_idea_system_prompt,
    build_idea_user_prompt,
    build_risk_system_prompt,
    build_risk_user_prompt,
    build_router_system_prompt,
    build_router_user_prompt,
)
from .registry import resolve_profile_assignments
from .roles import RoleAssignment
from .router import deterministic_router_decision, parse_router_decision


def _extract_objective_text(raw_content: str) -> str:
    text = str(raw_content or "").strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except Exception:
        return sanitize_objective_text(text)

    if isinstance(payload, dict):
        for key in ("objective", "goal", "prompt", "strategy_objective"):
            value = payload.get(key)
            normalized = sanitize_objective_text(value)
            if normalized:
                return normalized
    return sanitize_objective_text(text)


def _parse_role_payload(raw_content: str) -> Dict[str, Any]:
    text = str(raw_content or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_text_list(value: Any) -> List[str]:
    if isinstance(value, str):
        normalized = sanitize_objective_text(value)
        return [normalized] if normalized else []
    if isinstance(value, (list, tuple, set)):
        items: List[str] = []
        for raw in value:
            normalized = sanitize_objective_text(raw)
            if normalized:
                items.append(normalized)
        return items
    return []


def _normalize_idea_handoff(raw_content: str) -> Dict[str, Any]:
    payload = _parse_role_payload(raw_content)
    objective = _extract_objective_text(raw_content) if raw_content else ""
    rationale = sanitize_objective_text(
        payload.get("rationale")
        or payload.get("hypothesis")
        or payload.get("thesis")
    )
    strategy_family = sanitize_objective_text(payload.get("strategy_family"))
    constraints = _normalize_text_list(payload.get("constraints"))
    return {
        "objective": objective,
        "rationale": rationale,
        "strategy_family": strategy_family,
        "constraints": constraints,
        "raw_payload": payload,
    }


def _render_builder_objective(handoff: Dict[str, Any], fallback_objective: str) -> str:
    objective = sanitize_objective_text(handoff.get("objective") or fallback_objective)
    rationale = sanitize_objective_text(handoff.get("rationale"))
    strategy_family = sanitize_objective_text(handoff.get("strategy_family"))
    constraints = _normalize_text_list(handoff.get("constraints"))

    parts: List[str] = [objective] if objective else []
    if strategy_family:
        parts.append(f"Strategy family: {strategy_family}.")
    if rationale:
        parts.append(f"Hypothesis: {rationale}")
    if constraints:
        parts.append("Constraints: " + "; ".join(constraints[:4]))
    return sanitize_objective_text("\n".join(parts))


def _normalize_review_payload(role_output: "RoleOutput") -> Dict[str, Any]:
    payload = _parse_role_payload(role_output.content)
    if payload:
        return payload
    text = sanitize_objective_text(role_output.content or role_output.error)
    return {"raw_text": text} if text else {}


@dataclass
class RoleOutput:
    """Captured output for a role invocation."""

    role: str
    model: str
    content: str = ""
    available: bool = False
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "model": self.model,
            "content": self.content,
            "available": self.available,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


@dataclass
class MultiLLMCycleResult:
    """Outcome of one multi-LLM autonomous builder cycle."""

    objective: str
    profile_name: str
    builder_model: str
    role_assignments: List[RoleAssignment]
    role_outputs: Dict[str, RoleOutput]
    router_decision: Dict[str, Any]
    session_summary: Dict[str, Any]
    builder_session: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "profile_name": self.profile_name,
            "builder_model": self.builder_model,
            "role_assignments": [
                assignment.to_dict() for assignment in self.role_assignments
            ],
            "role_outputs": {
                role: output.to_dict() for role, output in self.role_outputs.items()
            },
            "router_decision": dict(self.router_decision),
            "session_summary": dict(self.session_summary),
        }


class MultiLLMSessionManager:
    """Resolve role models and orchestrate idea/build/critic/risk/router steps."""

    def __init__(
        self,
        *,
        profile_name: str,
        base_llm_config: Optional[LLMConfig] = None,
        inventory: Optional[ModelInventory] = None,
        config_path: Optional[str] = None,
        role_overrides: Optional[Dict[str, str]] = None,
        require_live_ollama: bool = True,
        client_factory: Callable[[LLMConfig], Any] = create_llm_client,
    ) -> None:
        self.base_llm_config = base_llm_config or LLMConfig()
        self.require_live_ollama = bool(require_live_ollama)
        self.inventory = inventory or discover_local_models(
            ollama_host=self.base_llm_config.ollama_host,
            include_live_ollama=True,
        )
        self.resolution = resolve_profile_assignments(
            profile_name,
            self.inventory,
            config_path=config_path,
            role_overrides=role_overrides,
            require_live_ollama=self.require_live_ollama,
        )
        self.profile_name = str(self.resolution["profile_name"])
        self.client_factory = client_factory

    @property
    def assignments(self) -> List[RoleAssignment]:
        return list(self.resolution["assignments"])

    @property
    def missing_roles(self) -> List[str]:
        return list(self.resolution["missing_roles"])

    def resolve_role_assignment(self, role: str) -> Optional[RoleAssignment]:
        for assignment in self.assignments:
            if assignment.role == role:
                return assignment
        return None

    def resolve_builder_model(self, fallback_model: str) -> str:
        assignment = self.resolve_role_assignment("builder_llm")
        if assignment and assignment.available and assignment.resolved_model:
            return assignment.resolved_model
        return fallback_model

    def _build_client(self, role: str) -> Optional[Any]:
        assignment = self.resolve_role_assignment(role)
        if assignment is None or not assignment.available or not assignment.resolved_model:
            return None

        provider = (
            LLMProvider.OPENAI
            if assignment.backend == "openai"
            else LLMProvider.OLLAMA
        )
        config = LLMConfig(
            provider=provider,
            model=assignment.resolved_model,
            ollama_host=self.base_llm_config.ollama_host,
            openai_api_key=self.base_llm_config.openai_api_key,
            openai_base_url=self.base_llm_config.openai_base_url,
            temperature=self.base_llm_config.temperature,
            max_tokens=self.base_llm_config.max_tokens,
            top_p=self.base_llm_config.top_p,
            timeout_seconds=self.base_llm_config.timeout_seconds,
            max_retries=self.base_llm_config.max_retries,
            retry_delay_seconds=self.base_llm_config.retry_delay_seconds,
        )
        return self.client_factory(config)

    def _call_role(
        self,
        role: str,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> RoleOutput:
        assignment = self.resolve_role_assignment(role)
        model_name = assignment.resolved_model if assignment else ""
        client = self._build_client(role)
        if client is None:
            return RoleOutput(
                role=role,
                model=model_name,
                available=False,
                error="role unavailable locally",
            )
        try:
            response = client.chat(
                [
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=user_prompt),
                ]
            )
            return RoleOutput(
                role=role,
                model=model_name,
                content=response.content,
                available=True,
                metadata={
                    "parsed_payload": _parse_role_payload(response.content),
                    "provider": response.provider.value,
                    "latency_ms": response.latency_ms,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return RoleOutput(
                role=role,
                model=model_name,
                available=True,
                error=str(exc),
            )

    def generate_objective(
        self,
        *,
        symbols: Iterable[str],
        timeframes: Iterable[str],
        available_indicators: Iterable[str],
        history_tail: List[Dict[str, Any]],
        fallback_objective: Optional[str] = None,
    ) -> Dict[str, Any]:
        fallback = sanitize_objective_text(
            fallback_objective
            or generate_random_objective(
                symbol=list(symbols) or ["BTCUSDT"],
                timeframe=list(timeframes) or ["1h"],
                available_indicators=list(available_indicators),
            )
        )
        role_output = self._call_role(
            "idea_llm",
            system_prompt=build_idea_system_prompt(),
            user_prompt=build_idea_user_prompt(
                symbols=symbols,
                timeframes=timeframes,
                available_indicators=available_indicators,
                history_tail=history_tail,
            ),
        )
        content = role_output.content.strip()
        handoff = _normalize_idea_handoff(content)
        objective = _render_builder_objective(handoff, fallback) if content else ""
        if not objective:
            objective = fallback
        role_output.metadata["handoff_payload"] = handoff
        return {
            "objective": objective,
            "handoff": handoff,
            "role_output": role_output,
            "used_fallback": objective == fallback,
        }

    def review_builder_session(
        self,
        *,
        objective: str,
        builder_session: Any,
        target_sharpe: float,
    ) -> Dict[str, Any]:
        summary = summarize_builder_session(builder_session)
        critic_output = self._call_role(
            "critic_llm",
            system_prompt=build_critic_system_prompt(),
            user_prompt=build_critic_user_prompt(
                objective=objective,
                session_summary=summary,
            ),
        )
        risk_output = self._call_role(
            "risk_llm",
            system_prompt=build_risk_system_prompt(),
            user_prompt=build_risk_user_prompt(
                objective=objective,
                session_summary=summary,
            ),
        )
        critic_payload = _normalize_review_payload(critic_output)
        risk_payload = _normalize_review_payload(risk_output)
        critic_output.metadata["normalized_review"] = critic_payload
        risk_output.metadata["normalized_review"] = risk_payload
        router_output = self._call_role(
            "execution_router_llm",
            system_prompt=build_router_system_prompt(),
            user_prompt=build_router_user_prompt(
                objective=objective,
                session_summary=summary,
                critic_summary=json.dumps(critic_payload, ensure_ascii=False),
                risk_summary=json.dumps(risk_payload, ensure_ascii=False),
                target_sharpe=target_sharpe,
            ),
        )

        if router_output.content:
            decision = parse_router_decision(router_output.content)
        else:
            decision = deterministic_router_decision(
                session_status=str(summary.get("status", "") or ""),
                metrics=summary.get("metrics", {}),
                target_sharpe=target_sharpe,
                critic_summary=json.dumps(critic_payload, ensure_ascii=False),
                risk_summary=json.dumps(risk_payload, ensure_ascii=False),
            )

        return {
            "session_summary": summary,
            "role_outputs": {
                "critic_llm": critic_output,
                "risk_llm": risk_output,
                "execution_router_llm": router_output,
            },
            "router_decision": decision,
        }

    def run_cycle(
        self,
        *,
        symbols: Iterable[str],
        timeframes: Iterable[str],
        available_indicators: Iterable[str],
        history_tail: List[Dict[str, Any]],
        target_sharpe: float,
        fallback_builder_model: str,
        builder_runner: Callable[[str, str], Any],
        fallback_objective: Optional[str] = None,
    ) -> MultiLLMCycleResult:
        idea_bundle = self.generate_objective(
            symbols=symbols,
            timeframes=timeframes,
            available_indicators=available_indicators,
            history_tail=history_tail,
            fallback_objective=fallback_objective,
        )
        builder_model = self.resolve_builder_model(fallback_builder_model)
        session = builder_runner(idea_bundle["objective"], builder_model)
        review_bundle = self.review_builder_session(
            objective=idea_bundle["objective"],
            builder_session=session,
            target_sharpe=target_sharpe,
        )
        role_outputs = {
            "idea_llm": idea_bundle["role_output"],
            **review_bundle["role_outputs"],
        }
        return MultiLLMCycleResult(
            objective=idea_bundle["objective"],
            profile_name=self.profile_name,
            builder_model=builder_model,
            role_assignments=self.assignments,
            role_outputs=role_outputs,
            router_decision=review_bundle["router_decision"],
            session_summary=review_bundle["session_summary"],
            builder_session=session,
        )
