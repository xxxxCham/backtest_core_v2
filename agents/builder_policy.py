"""Module-ID: agents.builder_policy

Purpose: Explicit Builder decision-policy engine.

This module centralizes the constraint policies that used to be embedded
directly inside the Builder loop. The loop remains responsible for orchestration
and side effects; this module computes typed policy outcomes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agents.builder_constants import (
    MAX_POSITIVE_FALLBACK_COUNT,
    MIN_SUCCESSFUL_ITERATIONS_BEFORE_STOP,
)
from agents.builder_diagnostics import (
    _count_positive_iterations,
    _is_accept_candidate,
    _is_positive_progress_iteration,
    _required_positive_count_for_iteration,
)
from agents.builder_policy_helpers import (
    _should_trip_logic_stagnation_circuit,
)
from agents.builder_state import BuilderIteration, BuilderSession


@dataclass
class PolicyRestriction:
    name: str
    effect: str
    phase: str = "decision"


@dataclass
class PositiveProgressGateFeedback:
    iteration: int
    required_positive: int
    observed_positive: int
    llm_positive: int
    fallback_positive: int


@dataclass
class StagnationCircuitBreakerFeedback:
    triggered: bool
    reason: str


@dataclass
class DecisionPolicyFeedback:
    positive_progress_gate: PositiveProgressGateFeedback | None = None
    stagnation_circuit_breaker: StagnationCircuitBreakerFeedback | None = None
    stop_overridden: bool = False
    accept_overridden: bool = False

    def merge(self, other: DecisionPolicyFeedback) -> None:
        if other.positive_progress_gate is not None:
            self.positive_progress_gate = other.positive_progress_gate
        if other.stagnation_circuit_breaker is not None:
            self.stagnation_circuit_breaker = other.stagnation_circuit_breaker
        self.stop_overridden = self.stop_overridden or other.stop_overridden
        self.accept_overridden = self.accept_overridden or other.accept_overridden

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.positive_progress_gate is not None:
            payload["positive_progress_gate"] = asdict(
                self.positive_progress_gate,
            )
        if self.stagnation_circuit_breaker is not None:
            payload["stagnation_circuit_breaker"] = asdict(
                self.stagnation_circuit_breaker,
            )
        if self.stop_overridden:
            payload["stop_overridden"] = True
        if self.accept_overridden:
            payload["accept_overridden"] = True
        return payload


@dataclass
class PositiveProgressGateEvaluation:
    feedback: PositiveProgressGateFeedback | None = None
    triggered: bool = False
    warning_message: str = ""
    analysis: str = ""
    decision: str = "continue"
    session_status: str = "running"
    restrictions: list[PolicyRestriction] = field(default_factory=list)


@dataclass
class DecisionPolicyEvaluation:
    decision: str
    analysis: str
    feedback: DecisionPolicyFeedback = field(default_factory=DecisionPolicyFeedback)
    restrictions: list[PolicyRestriction] = field(default_factory=list)
    forced_stop_by_stagnation_policy: bool = False
    successful_iterations: int = 0
    trades: int = 0
    max_drawdown_pct: float = 0.0
    accept_allowed: bool = False
    accept_reason: str = ""
    stagnation_warning_message: str = ""
    stop_override_warning_message: str = ""
    accept_override_warning_message: str = ""


def evaluate_positive_progress_gate(
    *,
    session: BuilderSession,
    iteration_num: int,
    metrics_cur: dict[str, Any],
    enabled: bool,
) -> PositiveProgressGateEvaluation:
    required_positive = _required_positive_count_for_iteration(iteration_num)
    if required_positive <= 0 or not enabled:
        return PositiveProgressGateEvaluation()

    positive_count = _count_positive_iterations(session.iterations)
    if _is_positive_progress_iteration(metrics_cur):
        positive_count += 1

    fallback_positive_count = sum(
        1
        for it in session.iterations
        if it.backtest_result and it.is_fallback and _is_positive_progress_iteration(it.backtest_result.metrics or {})
    )
    capped_fallback_positive = min(
        fallback_positive_count,
        MAX_POSITIVE_FALLBACK_COUNT,
    )
    llm_positive_count = positive_count - capped_fallback_positive
    feedback = PositiveProgressGateFeedback(
        iteration=iteration_num,
        required_positive=required_positive,
        observed_positive=positive_count,
        llm_positive=llm_positive_count,
        fallback_positive=capped_fallback_positive,
    )

    if positive_count >= required_positive:
        return PositiveProgressGateEvaluation(feedback=feedback)

    return PositiveProgressGateEvaluation(
        feedback=feedback,
        triggered=True,
        warning_message=(
            "Arrêt anticipé: progression positive insuffisante "
            f"au checkpoint {iteration_num} "
            f"({positive_count}/{required_positive} positifs, "
            f"dont {llm_positive_count} LLM et {capped_fallback_positive} fallback)."
        ),
        analysis=(
            "[Policy] early stop triggered by positive progression gate "
            f"at iteration {iteration_num}: "
            f"{positive_count}/{required_positive}."
        ),
        decision="stop",
        session_status="failed",
        restrictions=[PolicyRestriction("positive_progress_gate", "blocker")],
    )


def evaluate_decision_policies(
    *,
    session: BuilderSession,
    iteration_num: int,
    max_iterations: int,
    metrics_cur: dict[str, Any],
    last_iteration: BuilderIteration | None,
    iteration: BuilderIteration,
    decision: str,
    analysis: str,
    stop_override_enabled: bool,
    accept_override_enabled: bool,
) -> DecisionPolicyEvaluation:
    result = DecisionPolicyEvaluation(
        decision=decision,
        analysis=analysis,
        successful_iterations=(sum(1 for it in session.iterations if it.backtest_result is not None) + 1),
        trades=int(metrics_cur.get("total_trades", 0) or 0),
        max_drawdown_pct=abs(float(metrics_cur.get("max_drawdown_pct", 0) or 0)),
    )

    if _should_trip_logic_stagnation_circuit(last_iteration, iteration):
        result.forced_stop_by_stagnation_policy = True
        result.decision = "stop"
        result.analysis = f"{result.analysis}\n[Policy] stop forced by logic stagnation circuit breaker."
        result.feedback.stagnation_circuit_breaker = StagnationCircuitBreakerFeedback(
            triggered=True,
            reason="two_consecutive_identical_metric_logic_iterations",
        )
        result.stagnation_warning_message = (
            "Arrêt anticipé: deux itérations logiques consécutives ont produit les mêmes métriques."
        )
        result.restrictions.append(
            PolicyRestriction("stagnation_circuit_breaker", "blocker"),
        )

    if (
        result.decision == "stop"
        and iteration_num < max_iterations
        and not result.forced_stop_by_stagnation_policy
        and stop_override_enabled
    ):
        if (
            result.successful_iterations < MIN_SUCCESSFUL_ITERATIONS_BEFORE_STOP
            or session.best_sharpe < session.target_sharpe
        ):
            result.decision = "continue"
            result.analysis = f"{result.analysis}\n[Policy] stop overridden to continue optimization."
            result.feedback.stop_overridden = True
            result.stop_override_warning_message = (
                "Décision 'stop' ignorée: poursuite obligatoire de la phase test/ajustement."
            )
            result.restrictions.append(
                PolicyRestriction("stop_override", "helper"),
            )

    result.accept_allowed, result.accept_reason = _is_accept_candidate(
        metrics_cur,
        target_sharpe=session.target_sharpe,
    )
    if (
        result.decision == "accept"
        and iteration_num < max_iterations
        and accept_override_enabled
        and not result.accept_allowed
    ):
        result.decision = "continue"
        result.analysis = f"{result.analysis}\n[Policy] accept overridden to continue optimization."
        result.feedback.accept_overridden = True
        result.accept_override_warning_message = (
            "Décision 'accept' ignorée: qualité statistique insuffisante, poursuite optimisation."
        )
        result.restrictions.append(
            PolicyRestriction("accept_override", "helper"),
        )

    # ── Code-quality gate ──────────────────────────────────────────────
    # Block accept if the generated code is too slow or repair-heavy.
    MIN_CODE_QUALITY_FOR_ACCEPT = 0.3
    cqs = float(getattr(iteration, "code_quality_score", 1.0) or 1.0)
    if result.decision == "accept" and cqs < MIN_CODE_QUALITY_FOR_ACCEPT and iteration_num < max_iterations:
        result.decision = "continue"
        result.analysis = (
            f"{result.analysis}\n"
            f"[Policy] accept blocked by code-quality gate "
            f"(score={cqs:.2f} < {MIN_CODE_QUALITY_FOR_ACCEPT})."
        )
        result.restrictions.append(
            PolicyRestriction("code_quality_gate", "helper", phase="decision"),
        )

    return result
