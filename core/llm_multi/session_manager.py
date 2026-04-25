"""Multi-LLM session manager that orchestrates the existing deterministic builder."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from agents.llm_client import LLMConfig, LLMMessage, LLMProvider, create_llm_client
from agents.llm_config import (
    apply_llm_inference_settings,
    normalize_llm_inference_settings,
    normalize_llm_model_inference_profiles,
)
from agents.llm_router import (
    LLMTopologyConfig,
    build_single_host_topology,
    normalize_ollama_host,
)
from agents.model_config import is_cloud_only_model
from agents.ollama_manager import ensure_ollama_running, resolve_ollama_request_context, unload_model
from agents.strategy_builder import generate_random_objective, sanitize_objective_text
from utils.model_loader import normalize_model_name

from .adapters.strategy_builder_adapter import summarize_builder_session
from .model_discovery import ModelInventory, discover_local_models
from .prompt_templates import (
    build_supervisor_objective_system_prompt,
    build_supervisor_objective_user_prompt,
    build_supervisor_review_system_prompt,
    build_supervisor_review_user_prompt,
)
from .registry import resolve_profile_assignments
from .roles import (
    MULTI_LLM_ROLE_DETAILS,
    RoleAssignment,
    build_role_rotation_metadata,
    normalize_role_candidate,
    resolve_assignment_rotation_index,
    resolve_assignment_rotation_queue,
    role_rotation_remainder,
)
from .router import deterministic_router_decision, normalize_router_action

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


def _parse_role_payload(raw_content: str) -> dict[str, Any]:
    text = _strip_json_wrappers(raw_content)
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = sanitize_objective_text(value)
        return [normalized] if normalized else []
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for raw in value:
            normalized = sanitize_objective_text(raw)
            if normalized:
                items.append(normalized)
        return items
    return []


def _normalize_objective_handoff(raw_content: str) -> dict[str, Any]:
    payload = _parse_role_payload(raw_content)
    objective = _extract_objective_text(raw_content) if raw_content else ""
    rationale = sanitize_objective_text(
        payload.get("rationale") or payload.get("hypothesis") or payload.get("thesis"),
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


def _render_builder_objective(handoff: dict[str, Any], fallback_objective: str) -> str:
    objective = sanitize_objective_text(handoff.get("objective") or fallback_objective)
    rationale = sanitize_objective_text(handoff.get("rationale"))
    strategy_family = sanitize_objective_text(handoff.get("strategy_family"))
    constraints = _normalize_text_list(handoff.get("constraints"))

    parts: list[str] = [objective] if objective else []
    if strategy_family:
        parts.append(f"Strategy family: {strategy_family}.")
    if rationale:
        parts.append(f"Hypothesis: {rationale}")
    if constraints:
        parts.append("Constraints: " + "; ".join(constraints[:4]))
    return sanitize_objective_text("\n".join(parts))


def _normalize_review_payload(role_output: RoleOutput) -> dict[str, Any]:
    payload = _parse_role_payload(role_output.content)
    if payload:
        return payload
    text = sanitize_objective_text(role_output.content or role_output.error)
    return {"raw_text": text} if text else {}


def _compact_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "sharpe_ratio": metrics.get("sharpe_ratio"),
        "total_return_pct": metrics.get("total_return_pct"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "profit_factor": metrics.get("profit_factor"),
        "total_trades": metrics.get("total_trades"),
    }


def _json_clone(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


def _dedupe_texts(values: Iterable[Any], *, limit: int = 6) -> list[str]:
    items: list[str] = []
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


def _compact_history_entry(entry: dict[str, Any]) -> dict[str, Any]:
    shared_memory = entry.get("multi_llm_shared_memory", {}) or {}
    supervisor_context = shared_memory.get("supervisor_context", {}) or {}
    decision_context = shared_memory.get("decision_context", {}) or {}
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
        "supervisor_verdict": str(supervisor_context.get("verdict", "") or "").strip(),
        "next_focus": _normalize_text_list(supervisor_context.get("next_focus")),
        "risk_level": str(supervisor_context.get("risk_level", "") or "").strip(),
        "key_risks": _normalize_text_list(supervisor_context.get("key_risks")),
        "router_action": str(
            decision_context.get("action") or router_decision.get("action") or "",
        ).strip(),
        "router_reason": sanitize_objective_text(
            decision_context.get("reason") or router_decision.get("reason"),
        ),
    }


def _safe_continuity_metric(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_successful_continuity_entry(entry: dict[str, Any]) -> bool:
    status = str(entry.get("status", "") or "").strip().lower()
    if status in {"crash", "crashed", "error", "failed", "failure"}:
        return False
    return any(
        _safe_continuity_metric(entry.get(metric_name)) is not None
        for metric_name in ("best_sharpe", "best_return", "best_pf", "best_trades")
    )


def _build_continuity_context(history_tail: list[dict[str, Any]]) -> dict[str, Any]:
    recent_entries = [_compact_history_entry(item) for item in list(history_tail or [])[-4:] if isinstance(item, dict)]
    eligible_entries = [entry for entry in recent_entries if _is_successful_continuity_entry(entry)]
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
    carry_over_focus = _dedupe_texts(focus for entry in recent_entries for focus in (entry.get("next_focus") or []))
    recurring_risks = _dedupe_texts(risk for entry in recent_entries for risk in (entry.get("key_risks") or []))
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
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
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
    role_assignments: list[RoleAssignment]
    role_outputs: dict[str, RoleOutput]
    router_decision: dict[str, Any]
    session_summary: dict[str, Any]
    shared_memory: dict[str, Any]
    builder_session: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "profile_name": self.profile_name,
            "builder_model": self.builder_model,
            "role_assignments": [assignment.to_dict() for assignment in self.role_assignments],
            "role_outputs": {role: output.to_dict() for role, output in self.role_outputs.items()},
            "router_decision": dict(self.router_decision),
            "session_summary": dict(self.session_summary),
            "shared_memory": dict(self.shared_memory),
        }


class _ManagedRoleLLMClient:
    """Proxy client that coordinates runtime transitions for one logical role."""

    def __init__(self, manager: MultiLLMSessionManager, role: str, client: Any) -> None:
        self._manager = manager
        self._role = str(role or "").strip()
        self._client = client

    @property
    def config(self) -> Any:
        return getattr(self._client, "config", None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def _prepare_client_for_mission(self) -> None:
        current_model = normalize_role_candidate(
            getattr(self.config, "model", "") if self.config is not None else "",
        )
        prepared = self._manager.prepare_role_for_mission(self._role)
        prepared_model = normalize_role_candidate(prepared.get("model"))
        if prepared_model and prepared_model != current_model:
            refreshed_client = self._manager._build_client(self._role)
            if refreshed_client is not None:
                self._client = refreshed_client

    def chat(self, messages: list[LLMMessage], **kwargs: Any) -> Any:
        self._prepare_client_for_mission()
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
        messages: list[LLMMessage],
        *,
        on_chunk: Callable[[str], None],
        **kwargs: Any,
    ) -> Any:
        self._prepare_client_for_mission()
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
    """Resolve role models and orchestrate supervisor/build with local routing."""

    def __init__(
        self,
        *,
        profile_name: str,
        base_llm_config: LLMConfig | None = None,
        inventory: ModelInventory | None = None,
        config_path: str | None = None,
        role_overrides: dict[str, Any] | None = None,
        llm_topology_config: LLMTopologyConfig | dict[str, Any] | None = None,
        inference_global_settings: dict[str, Any] | None = None,
        inference_model_profiles: dict[str, dict[str, Any]] | None = None,
        require_live_ollama: bool = True,
        client_factory: Callable[[LLMConfig], Any] = create_llm_client,
    ) -> None:
        self.base_llm_config = base_llm_config or LLMConfig()
        self.inference_global_settings = normalize_llm_inference_settings(
            inference_global_settings,
        )
        self.inference_model_profiles = normalize_llm_model_inference_profiles(
            inference_model_profiles,
        )
        if isinstance(llm_topology_config, dict):
            llm_topology_config = LLMTopologyConfig.from_dict(llm_topology_config)
        self.llm_topology_config = llm_topology_config or build_single_host_topology(
            primary_host=self.base_llm_config.ollama_host,
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
        self._active_ollama_models_by_host: dict[str, str] = {}
        self._runtime_flow_events: list[dict[str, Any]] = []
        self._role_runtime_state: dict[str, dict[str, Any]] = {}
        self._iteration_pinned: bool = False

    @property
    def assignments(self) -> list[RoleAssignment]:
        return list(self.resolution["assignments"])

    @property
    def missing_roles(self) -> list[str]:
        return list(self.resolution["missing_roles"])

    def _new_shared_memory(self) -> dict[str, Any]:
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
            "supervisor_context": {
                "verdict": "",
                "critique": "",
                "next_focus": [],
                "risk_level": "",
                "key_risks": [],
                "mitigations": [],
            },
            "decision_context": {
                "action": "",
                "reason": "",
                "confidence": 0.0,
            },
        }

    def reset_shared_memory(self) -> None:
        self._shared_memory = self._new_shared_memory()

    def shared_memory_snapshot(self) -> dict[str, Any]:
        return _json_clone(self._shared_memory)

    def consume_shared_memory(self) -> dict[str, Any]:
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
        history_tail: list[dict[str, Any]],
    ) -> None:
        self._shared_memory["continuity_context"] = _build_continuity_context(
            history_tail,
        )

    def _seed_shared_memory_from_objective(
        self,
        *,
        objective: str,
        handoff: dict[str, Any],
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
        session_summary: dict[str, Any],
    ) -> None:
        self._shared_memory["latest_session"] = {
            "status": str(session_summary.get("status", "") or ""),
            "metrics": _compact_metrics(session_summary.get("metrics", {}) or {}),
        }

    def _update_shared_memory_from_supervisor_review(
        self,
        *,
        supervisor_payload: dict[str, Any],
        router_decision: dict[str, Any],
    ) -> None:
        self._shared_memory["supervisor_context"] = {
            "verdict": str(supervisor_payload.get("verdict", "") or "").strip(),
            "critique": sanitize_objective_text(supervisor_payload.get("critique")),
            "next_focus": _normalize_text_list(supervisor_payload.get("next_focus")),
            "risk_level": str(supervisor_payload.get("risk_level", "") or "").strip(),
            "key_risks": _normalize_text_list(supervisor_payload.get("key_risks")),
            "mitigations": _normalize_text_list(supervisor_payload.get("mitigations")),
        }
        self._shared_memory["decision_context"] = {
            "action": str(router_decision.get("action", "") or "").strip(),
            "reason": sanitize_objective_text(router_decision.get("reason")),
            "confidence": float(router_decision.get("confidence", 0.0) or 0.0),
        }

    def resolve_role_assignment(self, role: str) -> RoleAssignment | None:
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
            "explicitly by the active multi-LLM profile; mono-model fallback disabled",
        )

    def _sync_assignment_rotation_state(
        self,
        assignment: RoleAssignment,
        *,
        selected_candidate: str = "",
        mission_count: int | None = None,
    ) -> None:
        queue = resolve_assignment_rotation_queue(assignment)
        selected = normalize_role_candidate(
            selected_candidate or assignment.requested_model or assignment.resolved_model,
        )
        if not queue and selected:
            queue = [selected]
        assignment.metadata = build_role_rotation_metadata(
            dict(assignment.metadata or {}),
            queue=queue,
            selected_candidate=selected,
            mission_count=mission_count,
        )
        assignment.alternatives = role_rotation_remainder(
            queue,
            selected,
        )

    # ── Iteration-level pinning ──────────────────────────────────────────
    # When pinned, roles keep their current model for all calls within
    # one Builder iteration.  ``advance_iteration`` rotates every role
    # once then re-pins.

    def pin_iteration_roles(self) -> None:
        """Lock current model selection for every role until the next ``advance_iteration``."""
        self._iteration_pinned = True

    def advance_iteration(self) -> dict[str, dict[str, Any]]:
        """Rotate every role once, then pin for the new iteration.

        Returns a dict ``{role: prepare_role_for_mission result}`` for logging.
        """
        self._iteration_pinned = False
        results: dict[str, dict[str, Any]] = {}
        for assignment in self.assignments:
            if not assignment.available or not assignment.resolved_model:
                continue
            queue = resolve_assignment_rotation_queue(assignment)
            if len(queue) <= 1:
                continue
            results[assignment.role] = self.prepare_role_for_mission(assignment.role)
        self._iteration_pinned = True
        return results

    def prepare_role_for_mission(self, role: str) -> dict[str, Any]:
        assignment = self.resolve_role_assignment(role)
        if assignment is None or not assignment.available or not assignment.resolved_model:
            return {"role": str(role or "").strip(), "rotated": False, "model": ""}

        queue = resolve_assignment_rotation_queue(assignment)
        raw_mission_count = dict(assignment.metadata or {}).get("rotation_mission_count", 0)
        try:
            mission_count = max(0, int(raw_mission_count))
        except (TypeError, ValueError):
            mission_count = 0

        if len(queue) <= 1:
            self._sync_assignment_rotation_state(
                assignment,
                mission_count=mission_count + 1,
            )
            return {
                "role": assignment.role,
                "rotated": False,
                "model": assignment.resolved_model,
                "requested_model": assignment.requested_model,
                "queue": queue,
            }

        if mission_count == 0:
            self._sync_assignment_rotation_state(
                assignment,
                mission_count=1,
            )
            return {
                "role": assignment.role,
                "rotated": False,
                "model": assignment.resolved_model,
                "requested_model": assignment.requested_model,
                "queue": queue,
            }

        # ── Iteration pin: keep current model, skip rotation ─────────────
        if self._iteration_pinned:
            self._sync_assignment_rotation_state(
                assignment,
                mission_count=mission_count + 1,
            )
            return {
                "role": assignment.role,
                "rotated": False,
                "model": assignment.resolved_model,
                "requested_model": assignment.requested_model,
                "queue": queue,
                "iteration_pinned": True,
            }

        current_index = resolve_assignment_rotation_index(assignment, queue=queue)
        for offset in range(1, len(queue) + 1):
            next_index = (current_index + offset) % len(queue)
            next_candidate = queue[next_index]
            if not self._apply_role_candidate(
                role,
                next_candidate,
                reason="scheduled role rotation",
            ):
                continue
            refreshed_assignment = self.resolve_role_assignment(role)
            if refreshed_assignment is None:
                break
            self._sync_assignment_rotation_state(
                refreshed_assignment,
                selected_candidate=next_candidate,
                mission_count=mission_count + 1,
            )
            route = self.resolve_role_route(role)
            self.mark_role_signal(
                role,
                signal="rotation_candidate",
                phase="runtime_prepare",
                detail=f"rotation to {refreshed_assignment.resolved_model}",
                model=refreshed_assignment.resolved_model,
                host=route.ollama_host,
            )
            return {
                "role": refreshed_assignment.role,
                "rotated": True,
                "model": refreshed_assignment.resolved_model,
                "requested_model": refreshed_assignment.requested_model,
                "queue": queue,
            }

        self._sync_assignment_rotation_state(
            assignment,
            mission_count=mission_count + 1,
        )
        return {
            "role": assignment.role,
            "rotated": False,
            "model": assignment.resolved_model,
            "requested_model": assignment.requested_model,
            "queue": queue,
            "rotation_blocked": True,
        }

    def _apply_role_candidate(self, role: str, candidate: str, *, reason: str = "") -> bool:
        assignment = self.resolve_role_assignment(role)
        if assignment is None:
            return False

        normalized_candidate = normalize_model_name(str(candidate or "").strip()) or str(candidate or "").strip()
        if not normalized_candidate:
            return False
        rotation_queue = resolve_assignment_rotation_queue(assignment)
        if not rotation_queue and normalized_candidate:
            rotation_queue = [normalized_candidate]
        raw_mission_count = dict(assignment.metadata or {}).get("rotation_mission_count", 0)
        try:
            mission_count = max(0, int(raw_mission_count))
        except (TypeError, ValueError):
            mission_count = 0

        if is_cloud_only_model(normalized_candidate):
            discovered = self.inventory.find(normalized_candidate) if self.inventory is not None else None
            request_ctx = resolve_ollama_request_context(
                getattr(self.inventory, "live_ollama_host", None),
                model_name=normalized_candidate,
            )
            direct_cloud_available = bool(
                request_ctx.get("direct_cloud") and request_ctx.get("api_key_present"),
            )
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
                assignment.metadata = build_role_rotation_metadata(
                    metadata,
                    queue=rotation_queue,
                    selected_candidate=normalized_candidate,
                    mission_count=mission_count,
                )
                assignment.alternatives = role_rotation_remainder(
                    rotation_queue,
                    normalized_candidate,
                )
                return True
            if direct_cloud_available:
                metadata = dict(assignment.metadata or {})
                metadata["cloud_only"] = True
                metadata["direct_cloud"] = True
                metadata["effective_host"] = str(request_ctx.get("effective_host") or "")
                assignment.requested_model = normalized_candidate
                assignment.resolved_model = normalized_candidate
                assignment.available = True
                assignment.verified = True
                assignment.source = "ollama_cloud_direct"
                assignment.reason = reason or "fallback candidate selected"
                assignment.discovered_path = ""
                assignment.live = True
                assignment.install_required = False
                assignment.metadata = build_role_rotation_metadata(
                    metadata,
                    queue=rotation_queue,
                    selected_candidate=normalized_candidate,
                    mission_count=mission_count,
                )
                assignment.alternatives = role_rotation_remainder(
                    rotation_queue,
                    normalized_candidate,
                )
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
            assignment.metadata = build_role_rotation_metadata(
                metadata,
                queue=rotation_queue,
                selected_candidate=normalized_candidate,
                mission_count=mission_count,
            )
            assignment.alternatives = role_rotation_remainder(
                rotation_queue,
                normalized_candidate,
            )
            return True

        discovered = self.inventory.find(normalized_candidate) if self.inventory is not None else None
        if discovered is None or not discovered.verified_available:
            return False
        if (
            assignment.backend == "ollama"
            and self.require_live_ollama
            and bool(getattr(self.inventory, "live_ollama_reachable", False))
            and not bool(getattr(discovered, "live", False))
        ):
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
        assignment.metadata = build_role_rotation_metadata(
            dict(discovered.metadata or {}),
            queue=rotation_queue,
            selected_candidate=normalized_candidate,
            mission_count=mission_count,
        )
        assignment.alternatives = role_rotation_remainder(
            rotation_queue,
            normalized_candidate,
        )
        return True

    def select_next_role_candidate(
        self,
        role: str,
        *,
        rejected_model: str = "",
        reason: str = "",
    ) -> str | None:
        assignment = self.resolve_role_assignment(role)
        if assignment is None:
            return None

        normalized_rejected = normalize_model_name(
            str(rejected_model or assignment.resolved_model or assignment.requested_model).strip(),
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
        released: bool | None = None,
        phase: str = "",
        status: str = "",
        error: str = "",
    ) -> dict[str, Any]:
        payload = {
            "ts": _utc_now_iso(),
            "event": str(event or "").strip(),
            "role": str(role or "").strip(),
            "host": normalize_ollama_host(
                host or getattr(self.base_llm_config, "ollama_host", None),
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
            self._runtime_flow_events = self._runtime_flow_events[-_RUNTIME_EVENT_HISTORY_LIMIT:]
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
    ) -> dict[str, Any]:
        assignment = self.resolve_role_assignment(role)
        route = self.resolve_role_route(role)
        runtime_ctx = self.resolve_role_runtime_request_context(
            role,
            assignment=assignment,
            route=route,
            model_name=model,
        )
        normalized_host = normalize_ollama_host(
            host
            or runtime_ctx["host_effective"]
            or getattr(route, "ollama_host", None)
            or getattr(self.base_llm_config, "ollama_host", None),
        )
        resolved_model = str(
            model
            or (assignment.resolved_model if assignment is not None else "")
            or self._active_ollama_models_by_host.get(normalized_host, ""),
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
        ollama_host: str | None,
        gpu_target: str | None = None,
        role: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        normalized_model = str(model_name or "").strip()
        normalized_host = normalize_ollama_host(
            ollama_host or getattr(self.base_llm_config, "ollama_host", None),
        )
        previous_model = self._active_ollama_models_by_host.get(normalized_host, "")
        switched = bool(
            normalized_model and previous_model and previous_model != normalized_model,
        )
        unloaded_previous = False

        if switched:
            unloaded_previous = bool(
                unload_model(previous_model, ollama_host=normalized_host),
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

    def activate_runtime_model_for_role(self, role: str) -> dict[str, Any]:
        assignment = self.resolve_role_assignment(role)
        if assignment is None or assignment.backend != "ollama" or not assignment.resolved_model:
            return {}
        route = self.resolve_role_route(role)
        runtime_ctx = self.resolve_role_runtime_request_context(
            role,
            assignment=assignment,
            route=route,
        )
        return self.activate_runtime_model(
            runtime_ctx["tracking_model"] or assignment.resolved_model,
            ollama_host=runtime_ctx["host_effective"] or route.ollama_host,
            gpu_target=route.gpu_target or None,
            role=role,
            reason="role_dispatch",
        )

    def attempt_role_runtime_recovery(self, role: str, *, error: Exception) -> bool:
        assignment = self.resolve_role_assignment(role)
        if assignment is None or assignment.backend != "ollama" or not assignment.resolved_model:
            return False
        route = self.resolve_role_route(role)
        runtime_ctx = self.resolve_role_runtime_request_context(
            role,
            assignment=assignment,
            route=route,
        )
        runtime_host = runtime_ctx["host_effective"] or route.ollama_host
        self.mark_role_signal(
            role,
            signal="recovering",
            phase="runtime_recovery",
            detail="automatic ollama restart requested",
            error=str(error),
            model=assignment.resolved_model,
            host=runtime_host,
        )
        try:
            ok, _msg = ensure_ollama_running(
                ollama_host=runtime_host,
                gpu_target=route.gpu_target or None,
                model_name=assignment.resolved_model,
            )
        except TypeError:
            ok, _msg = ensure_ollama_running(
                ollama_host=runtime_host,
                gpu_target=route.gpu_target or None,
            )
        if not ok:
            self.mark_role_signal(
                role,
                signal="recovery_failed",
                phase="runtime_recovery",
                detail="automatic ollama restart failed",
                error=str(error),
                model=assignment.resolved_model,
                host=runtime_host,
            )
            return False
        self.forget_runtime_model(ollama_host=runtime_host)
        self.activate_runtime_model(
            runtime_ctx["tracking_model"] or assignment.resolved_model,
            ollama_host=runtime_host,
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
            host=runtime_host,
        )
        return True

    def forget_runtime_model(
        self,
        *,
        ollama_host: str | None,
        model_name: str | None = None,
    ) -> None:
        normalized_host = normalize_ollama_host(
            ollama_host or getattr(self.base_llm_config, "ollama_host", None),
        )
        tracked_model = self._active_ollama_models_by_host.get(normalized_host, "")
        normalized_model = str(model_name or "").strip()
        if not tracked_model:
            return
        if not normalized_model or tracked_model == normalized_model:
            self._active_ollama_models_by_host.pop(normalized_host, None)

    def release_runtime_models(self) -> list[dict[str, Any]]:
        releases: list[dict[str, Any]] = []
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
                },
            )
        self._active_ollama_models_by_host.clear()
        return releases

    def runtime_flow_snapshot(self) -> dict[str, Any]:
        host_gpu_targets: dict[str, set[str]] = {}
        host_logical_routes: dict[str, set[str]] = {}
        host_role_rows: dict[str, list[str]] = {}
        role_rows: list[dict[str, Any]] = []

        for assignment in self.assignments:
            route = self.resolve_role_route(assignment.role)
            runtime_ctx = self.resolve_role_runtime_request_context(
                assignment.role,
                assignment=assignment,
                route=route,
            )
            rotation_queue = resolve_assignment_rotation_queue(assignment)
            effective_host = runtime_ctx["host_effective"]
            logical_host = runtime_ctx["host_route"]
            active_model = self._active_ollama_models_by_host.get(effective_host, "")
            role_detail = MULTI_LLM_ROLE_DETAILS.get(assignment.role, {})
            tracking_model = str(
                runtime_ctx["tracking_model"] or assignment.resolved_model or assignment.requested_model or "",
            ).strip()
            host_gpu_targets.setdefault(effective_host, set()).add(
                str(route.gpu_target or "auto"),
            )
            if logical_host:
                host_logical_routes.setdefault(effective_host, set()).add(logical_host)
            host_role_rows.setdefault(effective_host, []).append(assignment.role)
            role_rows.append(
                {
                    "role": assignment.role,
                    "etape": str(role_detail.get("stage", "") or "").strip() or "-",
                    "modele": assignment.resolved_model or assignment.requested_model or "-",
                    "requested_model": assignment.requested_model or "-",
                    "resolved_model": assignment.resolved_model or "-",
                    "request_model": runtime_ctx["request_model"] or "-",
                    "host": effective_host,
                    "host_effective": effective_host,
                    "host_logique": logical_host or "-",
                    "transport": runtime_ctx["transport"],
                    "direct_cloud": bool(runtime_ctx["direct_cloud"]),
                    "gpu": str(route.gpu_target or "auto"),
                    "available": bool(assignment.available),
                    "etat": (
                        "actif"
                        if active_model and active_model == tracking_model
                        else ("pret" if assignment.available else "indisponible")
                    ),
                    "signal": self._role_runtime_state.get(assignment.role, {}).get("signal", "-"),
                    "signal_phase": self._role_runtime_state.get(assignment.role, {}).get("phase", "-"),
                    "signal_detail": self._role_runtime_state.get(assignment.role, {}).get("detail", "-"),
                    "actif_sur_host": active_model or "-",
                    "source": assignment.source or "-",
                    "fallback": bool(route.fallback_used),
                    "rotation_queue": " -> ".join(rotation_queue) if rotation_queue else "-",
                    "rotation_enabled": len(rotation_queue) > 1,
                    "rotation_index": resolve_assignment_rotation_index(
                        assignment,
                        queue=rotation_queue,
                    ),
                    "rotation_calls": int(
                        dict(assignment.metadata or {}).get("rotation_mission_count", 0) or 0,
                    ),
                },
            )

        hosts = sorted(
            set(host_gpu_targets.keys()) | set(self._active_ollama_models_by_host.keys()),
        )
        host_rows: list[dict[str, Any]] = []
        for host in hosts:
            role_names = host_role_rows.get(host, [])
            host_rows.append(
                {
                    "host": host,
                    "transport": (
                        "cloud_direct"
                        if str(host or "").strip().startswith("https://ollama.com")
                        else "local"
                    ),
                    "host_logique": ", ".join(sorted(host_logical_routes.get(host, set()))) or "-",
                    "gpu": ", ".join(sorted(host_gpu_targets.get(host, {"auto"}))),
                    "roles": ", ".join(role_names) if role_names else "-",
                    "modele_actif": self._active_ollama_models_by_host.get(host, "-"),
                },
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

    def build_role_client(self, role: str) -> Any | None:
        client = self._build_client(role)
        assignment = self.resolve_role_assignment(role)
        if client is not None and assignment is not None and assignment.backend == "ollama":
            return _ManagedRoleLLMClient(self, role, client)
        return client

    def build_builder_phase_clients(self) -> dict[str, Any]:
        phase_clients: dict[str, Any] = {}
        builder_client = self.build_role_client("builder_llm")
        supervisor_client = self.build_role_client("supervisor_llm")

        if builder_client is not None:
            for phase in (
                "proposal",
                "retry_proposal",
                "code",
                "retry_code",
            ):
                phase_clients[phase] = builder_client
        if supervisor_client is not None:
            phase_clients["analysis"] = supervisor_client
            phase_clients["pre_reflection"] = supervisor_client
        return phase_clients

    def resolve_role_route(self, role: str) -> Any:
        base_host = getattr(self.base_llm_config, "ollama_host", None)
        role_key = str(role or "").strip()
        if role_key == "supervisor_llm":
            return self.llm_topology_config.resolve_builder_phase_route(
                "analysis",
                fallback_host=base_host,
            )
        if role_key == "builder_llm":
            return self.llm_topology_config.resolve_builder_phase_route(
                "code",
                fallback_host=base_host,
            )
        return self.llm_topology_config.resolve_role_route(
            role_key,
            fallback_host=base_host,
        )

    def resolve_role_runtime_request_context(
        self,
        role: str,
        *,
        assignment: RoleAssignment | None = None,
        route: Any | None = None,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        assignment = assignment or self.resolve_role_assignment(role)
        route = route or self.resolve_role_route(role)
        host_route = normalize_ollama_host(
            getattr(route, "ollama_host", None) or getattr(self.base_llm_config, "ollama_host", None),
        )
        candidate_model = str(
            model_name
            or (assignment.resolved_model if assignment is not None else "")
            or (assignment.requested_model if assignment is not None else ""),
        ).strip()
        request_ctx = resolve_ollama_request_context(
            getattr(route, "ollama_host", None),
            model_name=candidate_model,
        )
        host_effective = normalize_ollama_host(
            request_ctx.get("effective_host") or host_route,
        )
        request_model = str(
            request_ctx.get("request_model") or candidate_model,
        ).strip()
        tracking_model = str(
            request_model
            or candidate_model
            or (assignment.resolved_model if assignment is not None else "")
            or (assignment.requested_model if assignment is not None else ""),
        ).strip()
        direct_cloud = bool(request_ctx.get("direct_cloud"))
        return {
            "host_route": host_route,
            "host_effective": host_effective,
            "request_model": request_model,
            "tracking_model": tracking_model,
            "direct_cloud": direct_cloud,
            "transport": "cloud_direct" if direct_cloud else "local",
        }

    def _build_client(self, role: str) -> Any | None:
        assignment = self.resolve_role_assignment(role)
        if assignment is None or not assignment.available or not assignment.resolved_model:
            return None
        route = self.resolve_role_route(role)
        runtime_ctx = self.resolve_role_runtime_request_context(
            role,
            assignment=assignment,
            route=route,
        )

        provider = LLMProvider.OPENAI if assignment.backend == "openai" else LLMProvider.OLLAMA
        config = LLMConfig(
            provider=provider,
            model=assignment.resolved_model,
            ollama_host=runtime_ctx["host_effective"] or route.ollama_host,
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
        route = self.resolve_role_route(role)
        client = self.build_role_client(role)
        if client is None:
            return RoleOutput(
                role=role,
                model=assignment.resolved_model if assignment else "",
                available=False,
                error="role unavailable locally",
            )
        lifecycle_managed = bool(assignment and assignment.backend == "ollama")
        role_output: RoleOutput | None = None
        unload_attempted = False
        unload_ok = False
        used_model_name = assignment.resolved_model if assignment else ""
        try:
            response = client.chat(
                [
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=user_prompt),
                ],
            )
            refreshed_assignment = self.resolve_role_assignment(role)
            used_model_name = refreshed_assignment.resolved_model if refreshed_assignment else used_model_name
            role_output = RoleOutput(
                role=role,
                model=used_model_name,
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
            refreshed_assignment = self.resolve_role_assignment(role)
            used_model_name = refreshed_assignment.resolved_model if refreshed_assignment else used_model_name
            role_output = RoleOutput(
                role=role,
                model=used_model_name,
                available=True,
                error=str(exc),
                metadata={"route": route.to_dict()},
            )
        finally:
            if lifecycle_managed and used_model_name:
                self.mark_role_signal(
                    role,
                    signal="unload_pending",
                    phase="post_call_cleanup",
                    detail="waiting for unload after mission completion",
                    model=used_model_name,
                    host=route.ollama_host,
                )
                unload_attempted = True
                unload_ok = bool(
                    unload_model(
                        used_model_name,
                        ollama_host=route.ollama_host,
                    ),
                )
                self.forget_runtime_model(
                    ollama_host=route.ollama_host,
                    model_name=used_model_name,
                )
                self._append_runtime_flow_event(
                    event="role_unload",
                    role=role,
                    host=route.ollama_host,
                    model=used_model_name,
                    gpu_target=route.gpu_target,
                    reason="post_call_cleanup",
                    released=unload_ok,
                )
                self.mark_role_signal(
                    role,
                    signal="unloaded",
                    phase="post_call_cleanup",
                    detail="model unloaded after mission completion",
                    model=used_model_name,
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
        history_tail: list[dict[str, Any]],
        fallback_objective: str | None = None,
    ) -> dict[str, Any]:
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
            ),
        )
        role_output = self._call_role(
            "supervisor_llm",
            system_prompt=build_supervisor_objective_system_prompt(),
            user_prompt=build_supervisor_objective_user_prompt(
                symbols=symbols_list,
                timeframes=timeframes_list,
                available_indicators=available_indicators_list,
                history_tail=history_tail,
                continuity_context=continuity_context,
            ),
        )
        content = role_output.content.strip()
        handoff = _normalize_objective_handoff(content)
        objective = _render_builder_objective(handoff, fallback) if content else ""
        if not objective:
            objective = fallback
        role_output.metadata["handoff_payload"] = handoff
        self._seed_shared_memory_from_objective(
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
    ) -> dict[str, Any]:
        summary = summarize_builder_session(builder_session)
        self._update_shared_memory_from_session_summary(session_summary=summary)
        shared_memory = self.shared_memory_snapshot()
        supervisor_output = self._call_role(
            "supervisor_llm",
            system_prompt=build_supervisor_review_system_prompt(),
            user_prompt=build_supervisor_review_user_prompt(
                objective=objective,
                session_summary=summary,
                shared_memory=shared_memory,
                continuity_context=shared_memory.get("continuity_context", {}),
                target_sharpe=target_sharpe,
            ),
        )
        supervisor_payload = _normalize_review_payload(supervisor_output)
        supervisor_output.metadata["normalized_review"] = supervisor_payload
        supervisor_output.metadata["session_summary_in_prompt"] = summary
        supervisor_output.metadata["shared_memory_in_prompt"] = shared_memory
        decision = deterministic_router_decision(
            session_status=str(summary.get("status", "") or ""),
            metrics=summary.get("metrics", {}),
            target_sharpe=target_sharpe,
            critic_summary=json.dumps(supervisor_payload, ensure_ascii=False),
            risk_summary=json.dumps(supervisor_payload, ensure_ascii=False),
        )
        supervisor_action = str(supervisor_payload.get("action", "") or "").strip()
        if supervisor_action:
            decision["action"] = normalize_router_action(supervisor_action)
            decision["confidence"] = float(
                supervisor_payload.get("confidence", decision.get("confidence", 0.0)) or 0.0,
            )
            supervisor_reason = sanitize_objective_text(supervisor_payload.get("reason"))
            if supervisor_reason:
                decision["reason"] = supervisor_reason
            decision["decision_source"] = "supervisor_llm"
        else:
            decision["decision_source"] = "local_rules"
        self._update_shared_memory_from_supervisor_review(
            supervisor_payload=supervisor_payload,
            router_decision=decision,
        )
        supervisor_output.metadata["router_decision"] = dict(decision)
        supervisor_output.metadata["shared_memory"] = self.shared_memory_snapshot()

        return {
            "session_summary": summary,
            "role_outputs": {
                "supervisor_llm": supervisor_output,
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
        history_tail: list[dict[str, Any]],
        target_sharpe: float,
        builder_runner: Callable[[str, str], Any],
        fallback_objective: str | None = None,
    ) -> MultiLLMCycleResult:
        try:
            objective_bundle = self.generate_objective(
                symbols=symbols,
                timeframes=timeframes,
                available_indicators=available_indicators,
                history_tail=history_tail,
                fallback_objective=fallback_objective,
            )
            builder_model = self.resolve_builder_model()
            session = builder_runner(objective_bundle["objective"], builder_model)
            review_bundle = self.review_builder_session(
                objective=objective_bundle["objective"],
                builder_session=session,
                target_sharpe=target_sharpe,
            )
            role_outputs = dict(review_bundle["role_outputs"])
            supervisor_review_output = role_outputs.get("supervisor_llm")
            if supervisor_review_output is not None:
                supervisor_review_output.metadata["objective_output"] = objective_bundle[
                    "role_output"
                ].to_dict()
            else:
                role_outputs["supervisor_llm"] = objective_bundle["role_output"]
            shared_memory = self.consume_shared_memory()
            return MultiLLMCycleResult(
                objective=objective_bundle["objective"],
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
