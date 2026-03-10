"""
agents.handlers - Extracted handler functions for Orchestrator states.

Each handler receives the Orchestrator instance and manages one state transition.
"""

from __future__ import annotations

from .analyze_handler import handle_analyze
from .critique_handler import handle_critique, test_proposals
from .init_handler import (
    compute_walk_forward_metrics,
    ensure_indicator_context,
    handle_init,
    validate_config,
)
from .iterate_handler import get_best_tested_config, handle_iterate
from .propose_handler import handle_propose, handle_sweep_proposal
from .report_handler import build_result, generate_final_report, record_iteration
from .validate_handler import handle_validate

__all__ = [
    "handle_init",
    "validate_config",
    "compute_walk_forward_metrics",
    "ensure_indicator_context",
    "handle_analyze",
    "handle_propose",
    "handle_sweep_proposal",
    "handle_critique",
    "test_proposals",
    "handle_validate",
    "handle_iterate",
    "get_best_tested_config",
    "generate_final_report",
    "build_result",
    "record_iteration",
]
