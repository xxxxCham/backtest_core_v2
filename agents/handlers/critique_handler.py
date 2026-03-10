"""Handler for CRITIQUE state - Run Critic agent and test proposals."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Dict, Iterable, Optional

from utils.observability import get_obs_logger

from ..base_agent import MetricsSnapshot
from ..state_machine import AgentState

# Optional tqdm import for progress bars
try:
    from tqdm import tqdm

    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

    def tqdm(iterable: Iterable[Any], **kwargs: Any) -> Iterable[Any]:  # type: ignore[misc]
        return iterable


if TYPE_CHECKING:
    from ..orchestrator import Orchestrator

logger = get_obs_logger(__name__)


def handle_critique(orch: "Orchestrator") -> None:
    """Handle CRITIQUE state - Execute Critic agent."""
    orch._log_event("phase_start", phase="CRITIQUE")
    logger.info("Phase CRITIQUE: Exécution Agent Critic")

    if not orch.context.strategist_proposals:
        logger.warning("Aucune proposition à critiquer")
        orch._log_event("warning", message="Aucune proposition à critiquer")
        orch.state_machine.transition_to(AgentState.VALIDATE)
        return

    # Execute Critic
    orch._apply_role_model("critic")
    orch._log_event("agent_execute_start", role="critic", model=orch.llm_client.config.model)
    t0 = time.time()
    result = orch.critic.execute(orch.context)
    dt = int((time.time() - t0) * 1000)
    orch._log_event(
        "agent_execute_end",
        role="critic",
        model=orch.llm_client.config.model,
        success=result.success,
        latency_ms=dt,
    )

    if orch._handle_llm_failure(result, "critic"):
        return

    if not result.success:
        logger.error("Critic échoué: %s", result.errors)
        orch._log_event("error", scope="critic", message=str(result.errors))
        orch._errors.extend(result.errors)
        # Continue with unfiltered proposals
        orch.context.critic_concerns = []
    else:
        # Update with filtered proposals
        approved = result.data.get("approved_proposals", [])
        if approved:
            orch.context.strategist_proposals = approved

        orch.context.critic_assessment = result.content
        orch.context.critic_concerns = result.data.get("concerns", [])
        orch._log_event(
            "critic_result",
            approved_count=len(approved),
            concerns_count=len(orch.context.critic_concerns),
        )
        logger.info(
            "Critic: %d propositions approuvées, %d concerns",
            len(approved),
            len(orch.context.critic_concerns),
        )

    # Test approved proposals
    test_proposals(orch)

    # Transition to VALIDATE
    orch.state_machine.transition_to(AgentState.VALIDATE)


def test_proposals(orch: "Orchestrator") -> None:
    """Test approved proposals via backtest."""
    proposals = list(orch.context.strategist_proposals or [])
    if not proposals:
        return

    def _eval_one(
        proposal: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Optional[MetricsSnapshot]]:
        params = proposal.get("parameters", {})
        if not params:
            return proposal, None
        return proposal, orch._run_backtest(params)

    n_workers = int(getattr(orch.config, "n_workers", 1) or 1)

    # Sequential by default
    if n_workers <= 1 or len(proposals) <= 1:
        proposal_iterator: Any = (
            tqdm(
                proposals,
                desc="Testing proposals",
                unit="proposal",
                disable=not TQDM_AVAILABLE,
                leave=False,
            )
            if len(proposals) > 1
            else proposals
        )

        for proposal in proposal_iterator:
            params = proposal.get("parameters", {})
            if not params:
                continue

            orch._log_event(
                "proposal_test_started",
                proposal_id=proposal.get("id"),
                proposal_name=proposal.get("name"),
            )
            logger.info("Test proposition %s: %s", proposal.get("id"), proposal.get("name"))

            metrics = orch._run_backtest(params)
            if metrics:
                proposal["tested_metrics"] = metrics.to_dict()
                proposal["tested"] = True

                orch.param_tracker.register(
                    params=params,
                    sharpe_ratio=metrics.sharpe_ratio,
                    total_return=metrics.total_return,
                )

                orch._log_event(
                    "proposal_test_ended",
                    proposal_id=proposal.get("id"),
                    tested=True,
                    sharpe=metrics.sharpe_ratio,
                    total_return=metrics.total_return,
                )
            else:
                proposal["tested"] = False
                orch._log_event(
                    "proposal_test_ended",
                    proposal_id=proposal.get("id"),
                    tested=False,
                )
        return

    # Parallel: workers slider now has real effect
    from concurrent.futures import ThreadPoolExecutor, as_completed

    for proposal in proposals:
        if proposal.get("parameters", {}):
            orch._log_event(
                "proposal_test_started",
                proposal_id=proposal.get("id"),
                proposal_name=proposal.get("name"),
            )

    futures = {}
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        for proposal in proposals:
            if not proposal.get("parameters", {}):
                continue
            futures[pool.submit(_eval_one, proposal)] = proposal

        for fut in as_completed(futures):
            proposal = futures[fut]
            try:
                _, metrics = fut.result()
            except Exception as e:
                metrics = None
                orch._warnings.append(f"Backtest proposition échoué: {e}")
                orch._log_event(
                    "proposal_test_ended",
                    proposal_id=proposal.get("id"),
                    tested=False,
                    error=str(e),
                )
                continue

            if metrics:
                proposal["tested_metrics"] = metrics.to_dict()
                proposal["tested"] = True

                orch.param_tracker.register(
                    params=proposal.get("parameters", {}),
                    sharpe_ratio=metrics.sharpe_ratio,
                    total_return=metrics.total_return,
                )

                orch._log_event(
                    "proposal_test_ended",
                    proposal_id=proposal.get("id"),
                    tested=True,
                    sharpe=metrics.sharpe_ratio,
                    total_return=metrics.total_return,
                )
            else:
                proposal["tested"] = False
                orch._log_event(
                    "proposal_test_ended",
                    proposal_id=proposal.get("id"),
                    tested=False,
                )
