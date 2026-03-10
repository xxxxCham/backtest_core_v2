"""Handler for PROPOSE state - Run Strategist agent and handle sweep requests."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Dict

from utils.observability import get_obs_logger

from ..state_machine import AgentState

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator

logger = get_obs_logger(__name__)


def handle_propose(orch: "Orchestrator") -> None:
    """Handle PROPOSE state - Execute Strategist agent."""
    orch._log_event("phase_start", phase="PROPOSE")
    logger.info("Phase PROPOSE: Exécution Agent Strategist")

    # Add session tracker summary
    if hasattr(orch, "param_tracker"):
        setattr(orch.context, "session_params_summary", orch.param_tracker.get_summary())

    # Execute Strategist
    orch._apply_role_model("strategist")
    orch._log_event(
        "agent_execute_start", role="strategist", model=orch.llm_client.config.model
    )
    t0 = time.time()
    result = orch.strategist.execute(orch.context)
    dt = int((time.time() - t0) * 1000)
    orch._log_event(
        "agent_execute_end",
        role="strategist",
        model=orch.llm_client.config.model,
        success=result.success,
        latency_ms=dt,
    )

    if orch._handle_llm_failure(result, "strategist"):
        return

    if not result.success:
        logger.error("Strategist échoué: %s", result.errors)
        orch._log_event("error", scope="strategist", message=str(result.errors))
        orch._errors.extend(result.errors)
        # Without proposals, go directly to validation
        orch.context.strategist_proposals = []
        orch.state_machine.transition_to(AgentState.VALIDATE)
        return

    # Detect sweep request
    sweep_request = result.data.get("sweep", None)
    if sweep_request:
        logger.info("Strategist demande un grid search (sweep)")
        handle_sweep_proposal(orch, sweep_request)
        return

    # Store proposals
    proposals = result.data.get("proposals", [])
    proposals = proposals[: orch.config.max_proposals_per_iteration]

    # Filter already-tested proposals
    filtered_proposals = []
    duplicates_count = 0
    for proposal in proposals:
        params = proposal.get("parameters", {})
        if not params:
            continue

        if orch.param_tracker.was_tested(params):
            duplicates_count += 1
            logger.info(
                "  Proposition ignorée (déjà testée): %s", proposal.get("name", "N/A")
            )
            continue

        filtered_proposals.append(proposal)

    orch.context.strategist_proposals = filtered_proposals
    orch._log_event(
        "proposals_generated",
        count=len(orch.context.strategist_proposals),
        duplicates_filtered=duplicates_count,
    )
    logger.info(
        "Strategist: %d propositions générées, %d duplications filtrées, %d nouvelles",
        len(proposals),
        duplicates_count,
        len(filtered_proposals),
    )

    # All proposals were duplicates
    if proposals and not filtered_proposals:
        logger.warning("Toutes les propositions sont des duplications - passage à VALIDATE")
        orch.state_machine.transition_to(AgentState.VALIDATE)
        return

    # Transition to CRITIQUE
    orch.state_machine.transition_to(AgentState.CRITIQUE)


def handle_sweep_proposal(orch: "Orchestrator", sweep_request: Dict[str, Any]) -> None:
    """Handle a sweep request from the Strategist (grid search)."""
    orch._log_event("sweep_request", details=sweep_request)
    logger.info("  Sweep rationale: %s", sweep_request.get("rationale", "N/A"))

    # Check sweep limit
    if orch._sweeps_performed >= orch._max_sweeps_per_session:
        logger.warning(
            "Limite de sweeps atteinte (%d). Sweep request ignoré.",
            orch._max_sweeps_per_session,
        )
        orch._warnings.append(
            f"Sweep limit reached ({orch._sweeps_performed}/{orch._max_sweeps_per_session})"
        )
        orch.context.strategist_proposals = []
        orch.state_machine.transition_to(AgentState.VALIDATE)
        return

    # Check if ranges were already tested
    ranges = sweep_request.get("ranges", {})
    if orch._ranges_tracker.was_tested(ranges):
        logger.warning(
            "Ranges déjà testées dans cette session! Params=%s. Forcing diversification...",
            list(ranges.keys()),
        )
        orch._warnings.append(f"Ranges already tested: {list(ranges.keys())}")
        orch.context.strategist_proposals = []
        orch.state_machine.transition_to(AgentState.VALIDATE)
        return

    try:
        from utils.parameters import RangeProposal

        from ..integration import run_llm_sweep

        # Create RangeProposal
        range_proposal = RangeProposal(
            ranges=sweep_request.get("ranges", {}),
            rationale=sweep_request.get("rationale", ""),
            optimize_for=sweep_request.get("optimize_for", "sharpe_ratio"),
            max_combinations=sweep_request.get("max_combinations", 100),
        )

        # Extract param_specs from context
        param_specs = []
        if hasattr(orch.context, "param_specs"):
            param_specs = orch.context.param_specs
        elif hasattr(orch.context, "parameter_configs"):
            from utils.parameters import ParameterSpec

            for pc in orch.context.parameter_configs:
                param_specs.append(
                    ParameterSpec(
                        name=pc.name,
                        min_val=pc.bounds[0],
                        max_val=pc.bounds[1],
                        default=pc.current_value,
                        step=pc.step,
                        param_type="int" if pc.value_type == "int" else "float",
                    )
                )

        if not param_specs:
            raise RuntimeError("Impossible d'extraire param_specs du contexte")

        # Get data
        if orch._loaded_data is None:
            logger.error("sweep_impossible reason=no_data")
            raise RuntimeError("Données non disponibles pour sweep")

        # Execute sweep
        logger.info(
            "  Lancement sweep: %d paramètres, max %d combinaisons",
            len(range_proposal.ranges),
            range_proposal.max_combinations,
        )
        orch._log_event("sweep_start", n_params=len(range_proposal.ranges))

        sweep_results = run_llm_sweep(
            range_proposal=range_proposal,
            param_specs=param_specs,
            data=orch._loaded_data,
            strategy_name=orch.context.strategy_name,
            initial_capital=10000.0,
            n_workers=None,
        )

        # Update budget counters
        n_combinations = sweep_results["n_combinations"]
        orch._sweeps_performed += 1
        orch._total_combinations_tested += n_combinations

        # Register tested ranges
        best_sharpe = sweep_results["best_metrics"].get("sharpe_ratio", 0)
        orch._ranges_tracker.register(
            ranges=range_proposal.ranges,
            n_combinations=n_combinations,
            best_sharpe=best_sharpe,
            rationale=range_proposal.rationale,
        )

        logger.info(
            "Sweep #%d terminé: %d combinaisons testées | Best %s=%.3f | Budget: %d/%s combos",
            orch._sweeps_performed,
            n_combinations,
            range_proposal.optimize_for,
            sweep_results["best_metrics"].get(range_proposal.optimize_for, 0),
            orch._total_combinations_tested,
            orch._max_iter_label,
        )
        orch._log_event(
            "sweep_complete",
            n_combinations=n_combinations,
            sweeps_performed=orch._sweeps_performed,
            total_combinations_tested=orch._total_combinations_tested,
            best_metrics=sweep_results["best_metrics"],
        )

        # Store results in context
        orch.context.sweep_results = sweep_results
        orch.context.sweep_summary = sweep_results["summary"]

        # Create artificial proposal from best config
        best_proposal = {
            "id": 1,
            "name": (
                f"Sweep Best Config ({range_proposal.optimize_for}="
                f"{sweep_results['best_metrics'].get(range_proposal.optimize_for, 0):.3f})"
            ),
            "priority": "HIGH",
            "risk_level": "LOW",
            "parameters": sweep_results["best_params"],
            "rationale": f"Best config from grid search: {range_proposal.rationale}",
            "expected_impact": sweep_results["best_metrics"],
            "risks": ["Config from grid search, may not generalize"],
        }

        orch.context.strategist_proposals = [best_proposal]
        logger.info("  Meilleurs paramètres: %s", sweep_results["best_params"])

        # Transition to CRITIQUE
        orch.state_machine.transition_to(AgentState.CRITIQUE)

    except Exception as e:
        logger.error("Erreur durant le sweep: %s", e)
        orch._log_event("sweep_failed", error=str(e))
        orch._errors.append(f"Sweep failed: {e!s}")
        orch.context.strategist_proposals = []
        orch.state_machine.transition_to(AgentState.VALIDATE)
