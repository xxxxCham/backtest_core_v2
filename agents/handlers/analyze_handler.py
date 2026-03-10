"""Handler for ANALYZE state - Run Analyst agent."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from utils.observability import get_obs_logger

from ..state_machine import AgentState
from .init_handler import ensure_indicator_context

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator

logger = get_obs_logger(__name__)


def handle_analyze(orch: "Orchestrator") -> None:
    """Handle ANALYZE state - Execute Analyst agent."""
    orch._log_event("phase_start", phase="ANALYZE")
    logger.info("Phase ANALYZE: Exécution Agent Analyst")

    # Update iteration in context
    orch.context.iteration = orch.state_machine.iteration

    # Add session tracker summary
    if hasattr(orch, "param_tracker"):
        setattr(orch.context, "session_params_summary", orch.param_tracker.get_summary())

    # Indicator context (once per run, deduplicated with init)
    ensure_indicator_context(orch)

    # Execute Analyst
    orch._apply_role_model("analyst")
    orch._log_event("agent_execute_start", role="analyst", model=orch.llm_client.config.model)
    t0 = time.time()
    result = orch.analyst.execute(orch.context)
    dt = int((time.time() - t0) * 1000)
    orch._log_event(
        "agent_execute_end",
        role="analyst",
        model=orch.llm_client.config.model,
        success=result.success,
        latency_ms=dt,
    )

    if orch._handle_llm_failure(result, "analyst"):
        return

    if not result.success:
        logger.error("Analyst échoué: %s", result.errors)
        orch._log_event("error", scope="analyst", message=str(result.errors))
        orch._errors.extend(result.errors)
        # Continue anyway - analysis is not blocking
        orch.context.analyst_report = "Analyse non disponible"
    else:
        # Store the report
        orch.context.analyst_report = result.content

        # Check if we should continue optimization
        proceed = result.data.get("proceed_to_optimization", True)
        orch._log_event("analyst_result", proceed=bool(proceed))
        if not proceed:
            logger.info("Analyst recommande de ne pas optimiser")
            transition = orch.state_machine.transition_to(AgentState.VALIDATE)
            if not transition.is_valid:
                logger.warning(
                    "Transition ANALYZE -> VALIDATE refusee: %s",
                    transition.message,
                )
                orch.state_machine.transition_to(AgentState.VALIDATE, force=True)
            return

    # Transition to PROPOSE
    orch.state_machine.transition_to(AgentState.PROPOSE)
