"""Handler for VALIDATE state - Run Validator agent."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from utils.observability import get_obs_logger

from ..state_machine import AgentState
from ..validator import ValidationDecision
from .report_handler import record_iteration

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator

logger = get_obs_logger(__name__)


def handle_validate(orch: "Orchestrator") -> None:
    """Handle VALIDATE state - Execute Validator agent."""
    orch._log_event("phase_start", phase="VALIDATE")
    logger.info("Phase VALIDATE: Exécution Agent Validator")

    # Execute Validator
    orch._apply_role_model("validator")
    orch._log_event(
        "agent_execute_start", role="validator", model=orch.llm_client.config.model
    )
    t0 = time.time()
    result = orch.validator.execute(orch.context)
    dt = int((time.time() - t0) * 1000)
    orch._log_event(
        "agent_execute_end",
        role="validator",
        model=orch.llm_client.config.model,
        success=result.success,
        latency_ms=dt,
    )

    if orch._handle_llm_failure(result, "validator"):
        return

    if not result.success:
        logger.error("Validator échoué: %s", result.errors)
        orch._log_event("error", scope="validator", message=str(result.errors))
        orch._errors.extend(result.errors)
        # Default to ITERATE if validator fails
        decision = ValidationDecision.ITERATE
        orch._last_validation_data = None
        orch._last_validator_summary = ""
    else:
        decision_str = result.data.get("decision", "ITERATE")
        try:
            decision = ValidationDecision(decision_str)
        except ValueError:
            decision = ValidationDecision.ITERATE
        orch._last_validation_data = result.data
        orch._last_validator_summary = result.content or ""

    logger.info("Validator décision: %s", decision.value)
    orch._log_event("validator_decision", decision=decision.value)

    # Record iteration history
    record_iteration(orch, decision.value)

    # Transition based on decision
    if decision == ValidationDecision.APPROVE:
        orch.state_machine.transition_to(AgentState.APPROVED)
    elif decision == ValidationDecision.REJECT:
        orch.state_machine.transition_to(AgentState.REJECTED)
    elif decision == ValidationDecision.ABORT:
        orch.state_machine.fail("Validator a décidé ABORT")
    else:  # ITERATE
        if orch.state_machine.can_transition_to(AgentState.ITERATE):
            orch.state_machine.transition_to(AgentState.ITERATE)
        else:
            logger.info("Max iterations atteint, passage en REJECTED")
            orch.state_machine.transition_to(AgentState.REJECTED)
