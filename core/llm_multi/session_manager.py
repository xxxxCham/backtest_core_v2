"""Multi-LLM session manager that orchestrates the existing deterministic builder."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from agents.llm_config import (
    apply_llm_inference_settings,
    normalize_llm_inference_settings,
    normalize_llm_model_inference_profiles,
)
from agents.llm_client import LLMConfig, LLMMessage, LLMProvider, create_llm_client
from agents.llm_router import (
    LLMTopologyConfig,
    build_single_host_topology,
    normalize_ollama_host,
)
from agents.model_config import is_cloud_only_model
from agents.ollama_manager import ensure_ollama_running, unload_model
from agents.strategy_builder import generate_random_objective, sanitize_objective_text
from utils.model_loader import normalize_model_name

from .adapters.strategy_builder_adapter import summarize_builder_session
from .model_discovery import ModelInventory, discover_local_models
from .prompt_templates import (
    build_critic_system_prompt,
    build_critic_user_prompt,
    build_idea_system_prompt,
    build_idea_user_prompt,
    build_risk_system_prompt,
    build_risk_user_prompt,
)
from .registry import resolve_profile_assignments
from .roles import MULTI_LLM_ROLE_DETAILS, RoleAssignment
from .router import deterministic_router_decision

logger = logging.getLogger(__name__)
_RUNTIME_EVENT_HISTORY_LIMIT = 40


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_json_wrappers(raw_content: str) -> str:
    text = str(raw_content or "").strip()
    if not text:
        return ""
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        while lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    lowered = text.lower()
    if lowered.startswith("json\n"):
        text = text[5:].strip()
    elif lowered.startswith("json\r\n"):
        text = text[6:].strip()
    return text


def _extract_objective_text(raw_content: str) -> str:
    text = _strip_json_wrappers(raw_content)
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
    text = _strip_json_wrappers(raw_content)
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


def _compact_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sharpe_ratio": metrics.get("sharpe_ratio"),
        "total_return_pct": metrics.get("total_return_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "profit_factor": metrics.get("profit_factor"),
        "total_trades": metrics.get("total_trades"),
    }


def _json_clone(payload: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def _dedupe_texts(values: Iterable[Any], *, limit: int = 6) -> List[str]:
    items: List[str] = []
    seen: set[str] = set()
    for raw in values:
        normalized = sanitize_objective_text(raw)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(normalized)
        if len(items) >= limit:
            break
    return items


def _compact_history_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    shared_memory = entry.get("multi_llm_shared_memory", {}) or {}
    critic_context = shared_memory.get("critic_context", {}) or {}
    risk_context = shared_memory.get("risk_context", {}) or {}
    router_context = shared_memory.get("router_context", {}) or {}
    router_decision = entry.get("multi_llm_router_decision", {}) or {}
    return {
        "session_num": int(entry.get("session_num", 0) or 0),
        "objective": sanitize_objective_text(entry.get("objective")),
        "symbol": str(entry.get("symbol", "") or "").strip(),
        "timeframe": str(entry.get("timeframe", "") or "").strip(),
        "status": str(entry.get("status", "") or "").strip(),
        "best_sharpe": entry.get("best_sharpe"),
        "best_return": entry.get("best_return"),
        "best_pf": entry.get("best_pf"),
        "best_trades": entry.get("best_trades"),
        "source_label": str(entry.get("source_label", "") or "").strip(),
        "builder_model": str(entry.get("multi_llm_builder_model", "") or "").strip(),
        "critic_verdict": str(critic_context.get("verdict", "") or "").strip(),
        "next_focus": _normalize_text_list(critic_context.get("next_focus")),
        "risk_level": str(risk_context.get("risk_level", "") or "").strip(),
        "key_risks": _normalize_text_list(risk_context.get("key_risks")),
        "router_action": str(
            router_context.get("action")
            or router_decision.get("action")
            or ""
        ).strip(),
        "router_reason": sanitize_objective_text(
            router_context.get("reason")
            or router_decision.get("reason")
        ),
    }


def _safe_continuity_metric(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_successful_continuity_entry(entry: Dict[str, Any]) -> bool:
    status = str(entry.get("status", "") or "").strip().lower()
    if status in {"crash", "crashed", "error", "failed", "failure"}:
        return False
    return any(
        _safe_continuity_metric(entry.get(metric_name)) is not None
        for metric_name in ("best_sharpe", "best_return", "best_pf", "best_trades")
    )


def _build_continuity_context(history_tail: List[Dict[str, Any]]) -> Dict[str, Any]:
    recent_entries = [
        _compact_history_entry(item)
        for item in list(history_tail or [])[-4:]
        if isinstance(item, dict)
    ]
    eligible_entries = [
        entry for entry in recent_entries if _is_successful_continuity_entry(entry)
    ]
    best_recent = max(
        eligible_entries,
        key=lambda item: (
            _safe_continuity_metric(item.get("best_sharpe"))
            if _safe_continuity_metric(item.get("best_sharpe")) is not None
            else float("-inf"),
            _safe_continuity_metric(item.get("best_return"))
            if _safe_continuity_metric(item.get("best_return")) is not None
            else float("-inf"),
            _safe_continuity_metric(item.get("best_pf"))
            if _safe_continuity_metric(item.get("best_pf")) is not None
            else float("-inf"),
            _safe_continuity_metric(item.get("best_trades"))
            if _safe_continuity_metric(item.get("best_trades")) is not None
            else float("-inf"),
        ),
        default={},
    )
    carry_over_focus = _dedupe_texts(
        focus
        for entry in recent_entries
        for focus in (entry.get("next_focus") or [])
    )
    recurring_risks = _dedupe_texts(
        risk
        for entry in recent_entries
        for risk in (entry.get("key_risks") or [])
    )
    return {
        "recent_sessions": recent_entries,
        "best_recent_session": dict(best_recent) if best_recent else {},
        "carry_over_focus": carry_over_focus,
        "recurring_risks": recurring_risks,
    }


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
    shared_memory: Dict[str, Any]
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
            "shared_memory": dict(self.shared_memory),
        }


class _ManagedRoleLLMClient:
    """Proxy client that coordinates runtime transitions for one logical role."""

    def __init__(self, manager: "MultiLLMSessionManager", role: str, client: Any) -> None:
        self._manager = manager
        self._role = str(role or "").strip()
        self._client = client

    @property
    def config(self) -> Any:
        return getattr(self._client, "config", None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def chat(self, messages: List[LLMMessage], **kwargs: Any) -> Any:
        self._manager.activate_runtime_model_for_role(self._role)
        self._manager.mark_role_signal(
            self._role,
            signal="mission_start",
            phase="chat",
            detail="role call started",
        )
        try:
            response = self._client.chat(messages, **kwargs)
        except Exception as exc:
            self._manager.mark_role_signal(
                self._role,
                signal="mission_failed",
                phase="chat",
                detail="role call failed",
                error=str(exc),
            )
            if self._manager.attempt_role_runtime_recovery(self._role, error=exc):
                self._manager.mark_role_signal(
                    self._role,
                    signal="mission_start",
                    phase="chat_retry",
                    detail="role call restarted after recovery",
                )
                try:
                    response = self._client.chat(messages, **kwargs)
                except Exception as retry_exc:
                    self._manager.mark_role_signal(
                        self._role,
                        signal="mission_failed",
                        phase="chat_retry",
                        detail="role retry failed",
                        error=str(retry_exc),
                    )
                    next_model = self._manager.select_next_role_candidate(
                        self._role,
                        rejected_model=str(getattr(self.config, "model", "") or ""),
                        reason=str(retry_exc),
                    )
                    if not next_model:
                        raise
                    self._client = self._manager._build_client(self._role)
                    self._manager.mark_role_signal(
                        self._role,
                        signal="mission_start",
                        phase="chat_failover",
                        detail=f"role call restarted with fallback {next_model}",
                    )
                    response = self._client.chat(messages, **kwargs)
            else:
                next_model = self._manager.select_next_role_candidate(
                    self._role,
                    rejected_model=str(getattr(self.config, "model", "") or ""),
                    reason=str(exc),
                )
                if not next_model:
                    raise
                self._client = self._manager._build_client(self._role)
                self._manager.mark_role_signal(
                    self._role,
                    signal="mission_start",
                    phase="chat_failover",
                    detail=f"role call restarted with fallback {next_model}",
                )
                response = self._client.chat(messages, **kwargs)
        self._manager.mark_role_signal(
            self._role,
            signal="mission_done",
            phase="chat",
            detail="role call completed",
        )
        return response

    def chat_stream(
        self,
        messages: List[LLMMessage],
        *,
        on_chunk: Callable[[str], None],
        **kwargs: Any,
    ) -> Any:
        self._manager.activate_runtime_model_for_role(self._role)
        self._manager.mark_role_signal(
            self._role,
            signal="mission_start",
            phase="chat_stream",
            detail="streaming role call started",
        )
        try:
            response = self._client.chat_stream(
                messages,
                on_chunk=on_chunk,
                **kwargs,
            )
        except Exception as exc:
            self._manager.mark_role_signal(
                self._role,
                signal="mission_failed",
                phase="chat_stream",
                detail="streaming role call failed",
                error=str(exc),
            )
            if self._manager.attempt_role_runtime_recovery(self._role, error=exc):
                self._manager.mark_role_signal(
                    self._role,
                    signal="mission_start",
                    phase="chat_stream_retry",
                    detail="streaming role call restarted after recovery",
                )
                try:
                    response = self._client.chat_stream(
                        messages,
                        on_chunk=on_chunk,
                        **kwargs,
                    )
                except Exception as retry_exc:
                    self._manager.mark_role_signal(
                        self._role,
                        signal="mission_failed",
                        phase="chat_stream_retry",
                        detail="streaming role retry failed",
                        error=str(retry_exc),
                    )
                    next_model = self._manager.select_next_role_candidate(
                        self._role,
                        rejected_model=str(getattr(self.config, "model", "") or ""),
                        reason=str(retry_exc),
                    )
                    if not next_model:
                        raise
                    self._client = self._manager._build_client(self._role)
                    self._manager.mark_role_signal(
                        self._role,
                        signal="mission_start",
                        phase="chat_stream_failover",
                        detail=f"streaming role call restarted with fallback {next_model}",
                    )
                    response = self._client.chat_stream(
                        messages,
                        on_chunk=on_chunk,
                        **kwargs,
                    )
            else:
                next_model = self._manager.select_next_role_candidate(
                    self._role,
                    rejected_model=str(getattr(self.config, "model", "") or ""),
                    reason=str(exc),
                )
                if not next_model:
                    raise
                self._client = self._manager._build_client(self._role)
                self._manager.mark_role_signal(
                    self._role,
                    signal="mission_start",
                    phase="chat_stream_failover",
                    detail=f"streaming role call restarted with fallback {next_model}",
                )
                response = self._client.chat_stream(
                    messages,
                    on_chunk=on_chunk,
                    **kwargs,
                )
        self._manager.mark_role_signal(
            self._role,
            signal="mission_done",
            phase="chat_stream",
            detail="streaming role call completed",
        )
        return response


class MultiLLMSessionManager:
    """Resolve role models and orchestrate idea/build/critic/risk with local routing."""

    def __init__(
        self,
        *,
        profile_name: str,
        base_llm_config: Optional[LLMConfig] = None,
        inventory: Optional[ModelInventory] = None,
        config_path: Optional[str] = None,
        role_overrides: Optional[Dict[str, str]] = None,
        llm_topology_config: Optional[LLMTopologyConfig | Dict[str, Any]] = None,
        inference_global_settings: Optional[Dict[str, Any]] = None,
        inference_model_profiles: Optional[Dict[str, Dict[str, Any]]] = None,
        require_live_ollama: bool = True,
        client_factory: Callable[[LLMConfig], Any] = create_llm_client,
    ) -> None:
        self.base_llm_config = base_llm_config or LLMConfig()
        self.inference_global_settings = normalize_llm_inference_settings(
            inference_global_settings
        )
        self.inference_model_profiles = normalize_llm_model_inference_profiles(
            inference_model_profiles
        )
        if isinstance(llm_topology_config, dict):
            llm_topology_config = LLMTopologyConfig.from_dict(llm_topology_config)
        self.llm_topology_config = llm_topology_config or build_single_host_topology(
            primary_host=self.base_llm_config.ollama_host
        )
        distinct_hosts = {
            str(getattr(endpoint, "ollama_host", "") or "").strip()
            for endpoint in self.llm_topology_config.endpoints.values()
            if bool(getattr(endpoint, "enabled", True))
        }
        self.require_live_ollama = bool(require_live_ollama and len(distinct_hosts) <= 1)
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
        self._shared_memory = self._new_shared_memory()
        self._active_ollama_models_by_host: Dict[str, str] = {}
        self._runtime_flow_events: List[Dict[str, Any]] = []
        self._role_runtime_state: Dict[str, Dict[str, Any]] = {}

    @property
    def assignments(self) -> List[RoleAssignment]:
        return list(self.resolution["assignments"])

    @property
    def missing_roles(self) -> List[str]:
        return list(self.resolution["missing_roles"])

    def _new_shared_memory(self) -> Dict[str, Any]:
        return {
            "continuity_context": {
                "recent_sessions": [],
                "best_recent_session": {},
                "carry_over_focus": [],
                "recurring_risks": [],
            },
            "objective_context": {
                "objective": "",
                "rationale": "",
                "strategy_family": "",
                "constraints": [],
                "used_fallback": False,
            },
            "market_context": {
                "symbol": "",
                "timeframe": "",
            },
            "latest_session": {
                "status": "",
                "metrics": {},
            },
            "critic_context": {
                "verdict": "",
                "critique": "",
                "next_focus": [],
            },
            "risk_context": {
                "risk_level": "",
                "key_risks": [],
                "mitigations": [],
            },
            "router_context": {
                "action": "",
                "reason": "",
                "confidence": 0.0,
            },
        }

    def reset_shared_memory(self) -> None:
        self._shared_memory = self._new_shared_memory()

    def shared_memory_snapshot(self) -> Dict[str, Any]:
        return _json_clone(self._shared_memory)

    def consume_shared_memory(self) -> Dict[str, Any]:
        snapshot = self.shared_memory_snapshot()
        self.reset_shared_memory()
        return snapshot

    def set_selected_market(self, *, symbol: str, timeframe: str) -> None:
        self._shared_memory["market_context"] = {
            "symbol": str(symbol or "").strip(),
            "timeframe": str(timeframe or "").strip(),
        }

    def _seed_shared_memory_from_history(
        self,
        *,
        history_tail: List[Dict[str, Any]],
    ) -> None:
        self._shared_memory["continuity_context"] = _build_continuity_context(
            history_tail
        )

    def _seed_shared_memory_from_idea(
        self,
        *,
        objective: str,
        handoff: Dict[str, Any],
        used_fallback: bool,
    ) -> None:
        self._shared_memory["objective_context"] = {
            "objective": sanitize_objective_text(objective),
            "rationale": sanitize_objective_text(handoff.get("rationale")),
            "strategy_family": sanitize_objective_text(handoff.get("strategy_family")),
            "constraints": _normalize_text_list(handoff.get("constraints")),
            "used_fallback": bool(used_fallback),
        }

    def _update_shared_memory_from_session_summary(
        self,
        *,
        session_summary: Dict[str, Any],
    ) -> None:
        self._shared_memory["latest_session"] = {
            "status": str(session_summary.get("status", "") or ""),
            "metrics": _compact_metrics(session_summary.get("metrics", {}) or {}),
        }

    def _update_shared_memory_from_reviews(
        self,
        *,
        critic_payload: Dict[str, Any],
        risk_payload: Dict[str, Any],
        router_decision: Dict[str, Any],
    ) -> None:
        self._shared_memory["critic_context"] = {
            "verdict": str(critic_payload.get("verdict", "") or "").strip(),
            "critique": sanitize_objective_text(critic_payload.get("critique")),
            "next_focus": _normalize_text_list(critic_payload.get("next_focus")),
        }
        self._shared_memory["risk_context"] = {
            "risk_level": str(risk_payload.get("risk_level", "") or "").strip(),
            "key_risks": _normalize_text_list(risk_payload.get("key_risks")),
            "mitigations": _normalize_text_list(risk_payload.get("mitigations")),
        }
        self._shared_memory["router_context"] = {
            "action": str(router_decision.get("action", "") or "").strip(),
            "reason": sanitize_objective_text(router_decision.get("reason")),
            "confidence": float(router_decision.get("confidence", 0.0) or 0.0),
        }

    def resolve_role_assignment(self, role: str) -> Optional[RoleAssignment]:
        for assignment in self.assignments:
            if assignment.role == role:
                return assignment
        return None

    def resolve_builder_model(self) -> str:
        assignment = self.resolve_role_assignment("builder_llm")
        if assignment and assignment.available and assignment.resolved_model:
            return assignment.resolved_model
        raise RuntimeError(
            "multi_llm_builder_model_unavailable: `builder_llm` must be resolved "
            "explicitly by the active multi-LLM profile; mono-model fallback disabled"
        )

    def _apply_role_candidate(self, role: str, candidate: str, *, reason: str = "") -> bool:
        assignment = self.resolve_role_assignment(role)
        if assignment is None:
            return False

        normalized_candidate = normalize_model_name(str(candidate or "").strip()) or str(candidate or "").strip()
        if not normalized_candidate:
            return False

        if is_cloud_only_model(normalized_candidate):
            discovered = self.inventory.find(normalized_candidate) if self.inventory is not None else None
            if discovered is not None and (
                not self.require_live_ollama
                or not getattr(self.inventory, "live_ollama_reachable", False)
                or discovered.live
            ):
                metadata = dict(discovered.metadata or {})
                metadata["cloud_only"] = True
                assignment.requested_model = normalized_candidate
                assignment.resolved_model = discovered.name
                assignment.available = True
                assignment.verified = bool(discovered.verified_available)
                assignment.source = str(discovered.source or "ollama_cloud")
                assignment.reason = reason or "fallback candidate selected"
                assignment.discovered_path = str(discovered.path or "")
                assignment.live = bool(discovered.live)
                assignment.install_required = False
                assignment.metadata = metadata
                return True
            if self.require_live_ollama and bool(getattr(self.inventory, "live_ollama_reachable", False)):
                return False
            metadata = dict(assignment.metadata or {})
            metadata["cloud_only"] = True
            assignment.requested_model = normalized_candidate
            assignment.resolved_model = normalized_candidate
            assignment.available = True
            assignment.verified = True
            assignment.source = "ollama_cloud"
            assignment.reason = reason or "fallback candidate selected"
            assignment.discovered_path = ""
            assignment.live = bool(getattr(self.inventory, "live_ollama_reachable", False))
            assignment.install_required = False
            assignment.metadata = metadata
            return True

        discovered = self.inventory.find(normalized_candidate) if self.inventory is not None else None
        if discovered is None or not discovered.verified_available:
            return False

        assignment.requested_model = normalized_candidate
        assignment.resolved_model = discovered.name
        assignment.available = True
        assignment.verified = bool(discovered.verified_available)
        assignment.source = str(discovered.source or "")
        assignment.reason = reason or "fallback candidate selected"
        assignment.discovered_path = str(discovered.path or "")
        assignment.live = bool(discovered.live)
        assignment.install_required = False
        assignment.metadata = dict(discovered.metadata or {})
        return True

    def select_next_role_candidate(
        self,
        role: str,
        *,
        rejected_model: str = "",
        reason: str = "",
    ) -> Optional[str]:
        assignment = self.resolve_role_assignment(role)
        if assignment is None:
            return None

        normalized_rejected = normalize_model_name(
            str(rejected_model or assignment.resolved_model or assignment.requested_model).strip()
        )
        remaining = [
            normalize_model_name(str(candidate or "").strip()) or str(candidate or "").strip()
            for candidate in list(assignment.alternatives or [])
            if (normalize_model_name(str(candidate or "").strip()) or str(candidate or "").strip())
        ]
        remaining = [candidate for candidate in remaining if candidate != normalized_rejected]
        if not remaining:
            return None

        for index, next_candidate in enumerate(remaining):
            if not self._apply_role_candidate(
                role,
                next_candidate,
                reason=f"fallback after runtime rejection: {reason}",
            ):
                continue
            assignment.alternatives = remaining[index + 1 :]
            route = self.resolve_role_route(role)
            self.forget_runtime_model(
                ollama_host=route.ollama_host,
                model_name=normalized_rejected,
            )
            self.mark_role_signal(
                role,
                signal="fallback_candidate",
                phase="runtime_prepare",
                detail=f"fallback to {assignment.resolved_model}",
                error=str(reason or "").strip(),
                model=assignment.resolved_model,
                host=route.ollama_host,
            )
            return assignment.resolved_model

        return None

    def _append_runtime_flow_event(
        self,
        *,
        event: str,
        role: str = "",
        host: str = "",
        model: str = "",
        previous_model: str = "",
        gpu_target: str = "",
        reason: str = "",
        unloaded_previous: bool = False,
        released: Optional[bool] = None,
        phase: str = "",
        status: str = "",
        error: str = "",
    ) -> Dict[str, Any]:
        payload = {
            "ts": _utc_now_iso(),
            "event": str(event or "").strip(),
            "role": str(role or "").strip(),
            "host": normalize_ollama_host(
                host or getattr(self.base_llm_config, "ollama_host", None)
            ),
            "model": str(model or "").strip(),
            "previous_model": str(previous_model or "").strip(),
            "gpu_target": str(gpu_target or "auto"),
            "reason": str(reason or "").strip(),
            "unloaded_previous": bool(unloaded_previous),
        }
        if released is not None:
            payload["released"] = bool(released)
        if phase:
            payload["phase"] = str(phase or "").strip()
        if status:
            payload["status"] = str(status or "").strip()
        if error:
            payload["error"] = str(error or "").strip()
        self._runtime_flow_events.append(payload)
        if len(self._runtime_flow_events) > _RUNTIME_EVENT_HISTORY_LIMIT:
            self._runtime_flow_events = self._runtime_flow_events[
                -_RUNTIME_EVENT_HISTORY_LIMIT:
            ]
        return payload

    def mark_role_signal(
        self,
        role: str,
        *,
        signal: str,
        phase: str = "",
        detail: str = "",
        error: str = "",
        model: str = "",
        host: str = "",
    ) -> Dict[str, Any]:
        assignment = self.resolve_role_assignment(role)
        route = self.resolve_role_route(role)
        normalized_host = normalize_ollama_host(
            host
            or getattr(route, "ollama_host", None)
            or getattr(self.base_llm_config, "ollama_host", None)
        )
        resolved_model = str(
            model
            or (assignment.resolved_model if assignment is not None else "")
            or self._active_ollama_models_by_host.get(normalized_host, "")
        ).strip()
        payload = {
            "ts": _utc_now_iso(),
            "role": str(role or "").strip(),
            "signal": str(signal or "").strip(),
            "phase": str(phase or "").strip(),
            "detail": str(detail or "").strip(),
            "error": str(error or "").strip(),
            "host": normalized_host,
            "model": resolved_model,
        }
        if payload["role"]:
            self._role_runtime_state[payload["role"]] = payload
        self._append_runtime_flow_event(
            event=f"role_{payload['signal']}",
            role=payload["role"],
            host=normalized_host,
            model=resolved_model,
            gpu_target=str(getattr(route, "gpu_target", "") or "auto"),
            reason=payload["detail"] or payload["signal"],
            phase=payload["phase"],
            status=payload["signal"],
            error=payload["error"],
        )
        return payload

    def activate_runtime_model(
        self,
        model_name: str,
        *,
        ollama_host: Optional[str],
        gpu_target: Optional[str] = None,
        role: str = "",
        reason: str = "",
    ) -> Dict[str, Any]:
        normalized_model = str(model_name or "").strip()
        normalized_host = normalize_ollama_host(
            ollama_host or getattr(self.base_llm_config, "ollama_host", None)
        )
        previous_model = self._active_ollama_models_by_host.get(normalized_host, "")
        switched = bool(
            normalized_model
            and previous_model
            and previous_model != normalized_model
        )
        unloaded_previous = False

        if switched:
            unloaded_previous = bool(
                unload_model(previous_model, ollama_host=normalized_host)
            )
            logger.info(
                "multi_llm_runtime_switch host=%s from=%s to=%s gpu=%s unloaded_previous=%s",
                normalized_host,
                previous_model,
                normalized_model,
                gpu_target or "auto",
                unloaded_previous,
            )

        if normalized_model:
            self._active_ollama_models_by_host[normalized_host] = normalized_model
        elif normalized_host in self._active_ollama_models_by_host:
            self._active_ollama_models_by_host.pop(normalized_host, None)

        event_name = "runtime_switch" if switched else "runtime_activate"
        self._append_runtime_flow_event(
            event=event_name,
            role=role,
            host=normalized_host,
            model=normalized_model,
            previous_model=previous_model,
            gpu_target=str(gpu_target or "auto"),
            reason=reason or ("role_dispatch" if role else "runtime_prepare"),
            unloaded_previous=unloaded_previous,
        )
        if role and normalized_model:
            self.mark_role_signal(
                role,
                signal="ready",
                phase="runtime_prepare",
                detail=reason or "runtime prepared",
                model=normalized_model,
                host=normalized_host,
            )

        return {
            "host": normalized_host,
            "model": normalized_model,
            "previous_model": previous_model,
            "switched": switched,
            "unloaded_previous": unloaded_previous,
            "gpu_target": str(gpu_target or "auto"),
            "role": str(role or "").strip(),
            "reason": str(reason or "").strip(),
        }

    def activate_runtime_model_for_role(self, role: str) -> Dict[str, Any]:
        assignment = self.resolve_role_assignment(role)
        if assignment is None or assignment.backend != "ollama" or not assignment.resolved_model:
            return {}
        route = self.resolve_role_route(role)
        return self.activate_runtime_model(
            assignment.resolved_model,
            ollama_host=route.ollama_host,
            gpu_target=route.gpu_target or None,
            role=role,
            reason="role_dispatch",
        )

    def attempt_role_runtime_recovery(self, role: str, *, error: Exception) -> bool:
        assignment = self.resolve_role_assignment(role)
        if assignment is None or assignment.backend != "ollama" or not assignment.resolved_model:
            return False
        route = self.resolve_role_route(role)
        self.mark_role_signal(
            role,
            signal="recovering",
            phase="runtime_recovery",
            detail="automatic ollama restart requested",
            error=str(error),
            model=assignment.resolved_model,
            host=route.ollama_host,
        )
        try:
            ok, _msg = ensure_ollama_running(
                ollama_host=route.ollama_host,
                gpu_target=route.gpu_target or None,
            )
        except TypeError:
            ok, _msg = ensure_ollama_running(ollama_host=route.ollama_host)
        if not ok:
            self.mark_role_signal(
                role,
                signal="recovery_failed",
                phase="runtime_recovery",
                detail="automatic ollama restart failed",
                error=str(error),
                model=assignment.resolved_model,
                host=route.ollama_host,
            )
            return False
        self.forget_runtime_model(ollama_host=route.ollama_host)
        self.activate_runtime_model(
            assignment.resolved_model,
            ollama_host=route.ollama_host,
            gpu_target=route.gpu_target or None,
            role=role,
            reason="runtime_recovery",
        )
        self.mark_role_signal(
            role,
            signal="recovered",
            phase="runtime_recovery",
            detail="automatic ollama restart succeeded",
            model=assignment.resolved_model,
            host=route.ollama_host,
        )
        return True

    def forget_runtime_model(
        self,
        *,
        ollama_host: Optional[str],
        model_name: Optional[str] = None,
    ) -> None:
        normalized_host = normalize_ollama_host(
            ollama_host or getattr(self.base_llm_config, "ollama_host", None)
        )
        tracked_model = self._active_ollama_models_by_host.get(normalized_host, "")
        normalized_model = str(model_name or "").strip()
        if not tracked_model:
            return
        if not normalized_model or tracked_model == normalized_model:
            self._active_ollama_models_by_host.pop(normalized_host, None)

    def release_runtime_models(self) -> List[Dict[str, Any]]:
        releases: List[Dict[str, Any]] = []
        for host, model_name in list(self._active_ollama_models_by_host.items()):
            released = bool(unload_model(model_name, ollama_host=host))
            self._append_runtime_flow_event(
                event="runtime_release",
                host=host,
                model=model_name,
                gpu_target="auto",
                reason="session_cleanup",
                released=released,
            )
            releases.append(
                {
                    "host": host,
                    "model": model_name,
                    "released": released,
                }
            )
        self._active_ollama_models_by_host.clear()
        return releases

    def runtime_flow_snapshot(self) -> Dict[str, Any]:
        host_gpu_targets: Dict[str, set[str]] = {}
        host_role_rows: Dict[str, List[str]] = {}
        role_rows: List[Dict[str, Any]] = []

        for assignment in self.assignments:
            route = self.resolve_role_route(assignment.role)
            normalized_host = normalize_ollama_host(route.ollama_host)
            active_model = self._active_ollama_models_by_host.get(normalized_host, "")
            role_detail = MULTI_LLM_ROLE_DETAILS.get(assignment.role, {})
            host_gpu_targets.setdefault(normalized_host, set()).add(
                str(route.gpu_target or "auto")
            )
            host_role_rows.setdefault(normalized_host, []).append(assignment.role)
            role_rows.append(
                {
                    "role": assignment.role,
                    "etape": str(role_detail.get("stage", "") or "").strip() or "-",
                    "modele": assignment.resolved_model or assignment.requested_model or "-",
                    "host": normalized_host,
                    "gpu": str(route.gpu_target or "auto"),
                    "etat": (
                        "actif"
                        if active_model and active_model == assignment.resolved_model
                        else ("pret" if assignment.available else "indisponible")
                    ),
                    "signal": self._role_runtime_state.get(assignment.role, {}).get("signal", "-"),
                    "signal_phase": self._role_runtime_state.get(assignment.role, {}).get("phase", "-"),
                    "signal_detail": self._role_runtime_state.get(assignment.role, {}).get("detail", "-"),
                    "actif_sur_host": active_model or "-",
                    "source": assignment.source or "-",
                    "fallback": bool(route.fallback_used),
                }
            )

        hosts = sorted(
            set(host_gpu_targets.keys()) | set(self._active_ollama_models_by_host.keys())
        )
        host_rows: List[Dict[str, Any]] = []
        for host in hosts:
            role_names = host_role_rows.get(host, [])
            host_rows.append(
                {
                    "host": host,
                    "gpu": ", ".join(sorted(host_gpu_targets.get(host, {"auto"}))),
                    "roles": ", ".join(role_names) if role_names else "-",
                    "modele_actif": self._active_ollama_models_by_host.get(host, "-"),
                }
            )

        return {
            "profile_name": self.profile_name,
            "missing_roles": list(self.missing_roles),
            "active_models_by_host": dict(self._active_ollama_models_by_host),
            "host_rows": host_rows,
            "role_rows": role_rows,
            "recent_events": list(self._runtime_flow_events[-12:]),
            "shared_memory": self.shared_memory_snapshot(),
        }

    def build_role_client(self, role: str) -> Optional[Any]:
        client = self._build_client(role)
        assignment = self.resolve_role_assignment(role)
        if (
            client is not None
            and assignment is not None
            and assignment.backend == "ollama"
        ):
            return _ManagedRoleLLMClient(self, role, client)
        return client

    def build_builder_phase_clients(self) -> Dict[str, Any]:
        phase_clients: Dict[str, Any] = {}
        builder_client = self.build_role_client("builder_llm")
        critic_client = self.build_role_client("critic_llm")
        risk_client = self.build_role_client("risk_llm")

        if builder_client is not None:
            for phase in (
                "proposal",
                "retry_proposal",
                "code",
                "retry_code",
            ):
                phase_clients[phase] = builder_client
        if critic_client is not None:
            phase_clients["analysis"] = critic_client
        if risk_client is not None:
            phase_clients["pre_reflection"] = risk_client
        return phase_clients

    def resolve_role_route(self, role: str) -> Any:
        base_host = getattr(self.base_llm_config, "ollama_host", None)
        role_key = str(role or "").strip()
        if role_key == "idea_llm":
            return self.llm_topology_config.resolve_builder_phase_route(
                "objective_gen",
                fallback_host=base_host,
            )
        if role_key == "builder_llm":
            return self.llm_topology_config.resolve_builder_phase_route(
                "code",
                fallback_host=base_host,
            )
        if role_key == "critic_llm":
            return self.llm_topology_config.resolve_builder_phase_route(
                "analysis",
                fallback_host=base_host,
            )
        if role_key == "risk_llm":
            return self.llm_topology_config.resolve_builder_phase_route(
                "pre_reflection",
                fallback_host=base_host,
            )
        return self.llm_topology_config.resolve_role_route(
            role_key,
            fallback_host=base_host,
        )

    def _build_client(self, role: str) -> Optional[Any]:
        assignment = self.resolve_role_assignment(role)
        if assignment is None or not assignment.available or not assignment.resolved_model:
            return None
        route = self.resolve_role_route(role)

        provider = (
            LLMProvider.OPENAI
            if assignment.backend == "openai"
            else LLMProvider.OLLAMA
        )
        config = LLMConfig(
            provider=provider,
            model=assignment.resolved_model,
            ollama_host=route.ollama_host,
            keep_alive=self.base_llm_config.keep_alive,
            openai_api_key=self.base_llm_config.openai_api_key,
            openai_base_url=self.base_llm_config.openai_base_url,
            temperature=self.base_llm_config.temperature,
            max_tokens=self.base_llm_config.max_tokens,
            top_p=self.base_llm_config.top_p,
            timeout_seconds=self.base_llm_config.timeout_seconds,
            max_retries=self.base_llm_config.max_retries,
            retry_delay_seconds=self.base_llm_config.retry_delay_seconds,
        )
        config = apply_llm_inference_settings(
            config,
            model_name=assignment.resolved_model,
            global_settings=self.inference_global_settings,
            model_profiles=self.inference_model_profiles,
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
        route = self.resolve_role_route(role)
        client = self.build_role_client(role)
        if client is None:
            return RoleOutput(
                role=role,
                model=model_name,
                available=False,
                error="role unavailable locally",
            )
        lifecycle_managed = bool(
            assignment
            and assignment.backend == "ollama"
            and model_name
        )
        role_output: Optional[RoleOutput] = None
        unload_attempted = False
        unload_ok = False
        try:
            response = client.chat(
                [
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=user_prompt),
                ]
            )
            role_output = RoleOutput(
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
                    "route": route.to_dict(),
                },
            )
        except Exception as exc:  # noqa: BLE001
            role_output = RoleOutput(
                role=role,
                model=model_name,
                available=True,
                error=str(exc),
                metadata={"route": route.to_dict()},
            )
        finally:
            if lifecycle_managed:
                self.mark_role_signal(
                    role,
                    signal="unload_pending",
                    phase="post_call_cleanup",
                    detail="waiting for unload after mission completion",
                    model=model_name,
                    host=route.ollama_host,
                )
                unload_attempted = True
                unload_ok = bool(
                    unload_model(
                        model_name,
                        ollama_host=route.ollama_host,
                    )
                )
                self.forget_runtime_model(
                    ollama_host=route.ollama_host,
                    model_name=model_name,
                )
                self._append_runtime_flow_event(
                    event="role_unload",
                    role=role,
                    host=route.ollama_host,
                    model=model_name,
                    gpu_target=route.gpu_target,
                    reason="post_call_cleanup",
                    released=unload_ok,
                )
                self.mark_role_signal(
                    role,
                    signal="unloaded",
                    phase="post_call_cleanup",
                    detail="model unloaded after mission completion",
                    model=model_name,
                    host=route.ollama_host,
                    error="" if unload_ok else "unload_failed",
                )
        assert role_output is not None
        role_output.metadata["model_lifecycle"] = {
            "managed_by_runtime": lifecycle_managed,
            "policy": "load_on_call_then_unload",
            "unload_attempted": unload_attempted,
            "unloaded_after_call": unload_ok,
        }
        return role_output

    def generate_objective(
        self,
        *,
        symbols: Iterable[str],
        timeframes: Iterable[str],
        available_indicators: Iterable[str],
        history_tail: List[Dict[str, Any]],
        fallback_objective: Optional[str] = None,
    ) -> Dict[str, Any]:
        symbols_list = list(symbols)
        timeframes_list = list(timeframes)
        available_indicators_list = list(available_indicators)
        self.reset_shared_memory()
        self._seed_shared_memory_from_history(history_tail=history_tail)
        continuity_context = self.shared_memory_snapshot().get("continuity_context", {})
        fallback = sanitize_objective_text(
            fallback_objective
            or generate_random_objective(
                symbol=symbols_list or ["BTCUSDT"],
                timeframe=timeframes_list or ["1h"],
                available_indicators=available_indicators_list,
            )
        )
        role_output = self._call_role(
            "idea_llm",
            system_prompt=build_idea_system_prompt(),
            user_prompt=build_idea_user_prompt(
                symbols=symbols_list,
                timeframes=timeframes_list,
                available_indicators=available_indicators_list,
                history_tail=history_tail,
                continuity_context=continuity_context,
            ),
        )
        content = role_output.content.strip()
        handoff = _normalize_idea_handoff(content)
        objective = _render_builder_objective(handoff, fallback) if content else ""
        if not objective:
            objective = fallback
        role_output.metadata["handoff_payload"] = handoff
        self._seed_shared_memory_from_idea(
            objective=objective,
            handoff=handoff,
            used_fallback=(objective == fallback),
        )
        role_output.metadata["shared_memory"] = self.shared_memory_snapshot()
        role_output.metadata["prompt_inputs"] = {
            "symbols": symbols_list,
            "timeframes": timeframes_list,
            "available_indicators": available_indicators_list,
            "history_tail_size": len(history_tail),
        }
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
        self._update_shared_memory_from_session_summary(session_summary=summary)
        shared_memory = self.shared_memory_snapshot()
        critic_output = self._call_role(
            "critic_llm",
            system_prompt=build_critic_system_prompt(),
            user_prompt=build_critic_user_prompt(
                objective=objective,
                session_summary=summary,
                shared_memory=shared_memory,
                continuity_context=shared_memory.get("continuity_context", {}),
            ),
        )
        risk_output = self._call_role(
            "risk_llm",
            system_prompt=build_risk_system_prompt(),
            user_prompt=build_risk_user_prompt(
                objective=objective,
                session_summary=summary,
                shared_memory=shared_memory,
                continuity_context=shared_memory.get("continuity_context", {}),
            ),
        )
        critic_payload = _normalize_review_payload(critic_output)
        risk_payload = _normalize_review_payload(risk_output)
        critic_output.metadata["normalized_review"] = critic_payload
        risk_output.metadata["normalized_review"] = risk_payload
        critic_output.metadata["session_summary_in_prompt"] = summary
        risk_output.metadata["session_summary_in_prompt"] = summary
        critic_output.metadata["shared_memory_in_prompt"] = shared_memory
        risk_output.metadata["shared_memory_in_prompt"] = shared_memory
        decision = deterministic_router_decision(
            session_status=str(summary.get("status", "") or ""),
            metrics=summary.get("metrics", {}),
            target_sharpe=target_sharpe,
            critic_summary=json.dumps(critic_payload, ensure_ascii=False),
            risk_summary=json.dumps(risk_payload, ensure_ascii=False),
        )
        self._update_shared_memory_from_reviews(
            critic_payload=critic_payload,
            risk_payload=risk_payload,
            router_decision=decision,
        )
        router_output = RoleOutput(
            role="execution_router_llm",
            model="deterministic_router",
            content=json.dumps(decision, ensure_ascii=False),
            available=True,
            metadata={
                "router_mode": "deterministic_only",
                "decision_source": "local_rules",
                "critic_summary": critic_payload,
                "risk_summary": risk_payload,
                "shared_memory": self.shared_memory_snapshot(),
            },
        )

        return {
            "session_summary": summary,
            "role_outputs": {
                "critic_llm": critic_output,
                "risk_llm": risk_output,
                "execution_router_llm": router_output,
            },
            "router_decision": decision,
            "shared_memory": self.shared_memory_snapshot(),
        }

    def run_cycle(
        self,
        *,
        symbols: Iterable[str],
        timeframes: Iterable[str],
        available_indicators: Iterable[str],
        history_tail: List[Dict[str, Any]],
        target_sharpe: float,
        builder_runner: Callable[[str, str], Any],
        fallback_objective: Optional[str] = None,
    ) -> MultiLLMCycleResult:
        try:
            idea_bundle = self.generate_objective(
                symbols=symbols,
                timeframes=timeframes,
                available_indicators=available_indicators,
                history_tail=history_tail,
                fallback_objective=fallback_objective,
            )
            builder_model = self.resolve_builder_model()
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
            shared_memory = self.consume_shared_memory()
            return MultiLLMCycleResult(
                objective=idea_bundle["objective"],
                profile_name=self.profile_name,
                builder_model=builder_model,
                role_assignments=self.assignments,
                role_outputs=role_outputs,
                router_decision=review_bundle["router_decision"],
                session_summary=review_bundle["session_summary"],
                shared_memory=shared_memory,
                builder_session=session,
            )
        except Exception:
            self.reset_shared_memory()
            raise
