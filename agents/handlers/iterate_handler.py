"""Handler for ITERATE state - Prepare next iteration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from utils.observability import get_obs_logger

from ..base_agent import MetricsSnapshot
from ..state_machine import AgentState

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator

logger = get_obs_logger(__name__)


def get_best_tested_config(orch: "Orchestrator") -> Optional[Dict[str, Any]]:
    """Return the best tested configuration from proposals."""
    best = None
    best_sharpe = float("-inf")

    for proposal in orch.context.strategist_proposals:
        if not proposal.get("tested"):
            continue

        metrics_dict = proposal.get("tested_metrics", {})
        sharpe = metrics_dict.get("sharpe_ratio", 0)

        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best = {
                "params": proposal.get("parameters", {}),
                "metrics": MetricsSnapshot.from_dict(metrics_dict),
            }

    return best


def handle_iterate(orch: "Orchestrator") -> None:
    """Handle ITERATE state - Prepare next iteration."""
    orch._log_event("phase_start", phase="ITERATE")
    logger.info("Phase ITERATE: Préparation itération suivante")

    # Select best tested configuration
    best_tested = get_best_tested_config(orch)
    if best_tested:
        orch.context.current_params = best_tested["params"]
        if best_tested.get("metrics"):
            orch.context.current_metrics = best_tested["metrics"]

            # Update best if better
            if (
                orch.context.best_metrics is None
                or best_tested["metrics"].sharpe_ratio > orch.context.best_metrics.sharpe_ratio
            ):
                orch.context.best_metrics = best_tested["metrics"]
                orch.context.best_params = best_tested["params"].copy()

    # Clean proposals
    orch.context.strategist_proposals = []
    orch.context.critic_concerns = []

    # Iteration complete callback
    if orch.config.on_iteration_complete:
        orch.config.on_iteration_complete(
            orch.state_machine.iteration,
            {"metrics": orch.context.current_metrics, "params": orch.context.current_params},
        )

    # Check combination budget
    if (
        not orch._unlimited_iterations
    ) and orch._total_combinations_tested >= orch.config.max_iterations:
        logger.warning(
            "Budget épuisé: %d combos testées (limite: %d, dont %d sweeps)",
            orch._total_combinations_tested,
            orch.config.max_iterations,
            orch._sweeps_performed,
        )
        orch._warnings.append(
            f"Budget épuisé: {orch._total_combinations_tested}/{orch.config.max_iterations} combos"
        )
        # Transition to REJECTED because budget is exhausted
        orch.state_machine.transition_to(AgentState.REJECTED)
        return

    # Transition to ANALYZE
    orch.state_machine.transition_to(AgentState.ANALYZE)
