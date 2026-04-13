"""
Module-ID: agents.builder_state

Purpose: Shared Builder session/iteration state types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.builder_feedback import (
    IterationPhaseFeedback,
    coerce_iteration_phase_feedback,
)

@dataclass
class BuilderIteration:
    """Résultat d'une itération du builder."""

    iteration: int
    hypothesis: str = ""
    code: str = ""
    backtest_result: Optional[Any] = None
    error: Optional[str] = None
    analysis: str = ""
    decision: str = ""  # "continue", "accept", "stop"
    change_type: str = ""  # "logic", "params", "both"
    diagnostic_category: str = ""  # computed by compute_diagnostic()
    diagnostic_detail: Dict[str, Any] = field(default_factory=dict)
    phase_feedback: IterationPhaseFeedback = field(
        default_factory=IterationPhaseFeedback
    )
    timestamp: datetime = field(default_factory=datetime.now)
    is_fallback: bool = False  # True if deterministic fallback was used
    used_indicators: List[str] = field(default_factory=list)
    perf_score: float = 0.0  # median generate_signals time in ms (micro-benchmark)
    code_quality_score: float = 1.0  # 0–1 composite quality (speed + repair count)

    def __post_init__(self) -> None:
        self.phase_feedback = coerce_iteration_phase_feedback(
            self.phase_feedback
        )

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "phase_feedback":
            value = coerce_iteration_phase_feedback(value)
        super().__setattr__(name, value)


@dataclass
class BuilderSession:
    """Session complète de construction de stratégie."""

    session_id: str
    objective: str
    session_dir: Path
    available_indicators: List[str] = field(default_factory=list)

    # État
    iterations: List[BuilderIteration] = field(default_factory=list)
    best_iteration: Optional[BuilderIteration] = None
    best_sharpe: float = float("-inf")
    best_score: float = float("-inf")  # Telemetry only, no longer drives loop decisions.
    status: str = "running"  # "running", "success", "failed", "max_iterations"
    auto_reset_count: int = 0
    recovery_events: List[Dict[str, Any]] = field(default_factory=list)

    # Configuration
    max_iterations: int = 10
    target_sharpe: float = 1.0
    start_time: datetime = field(default_factory=datetime.now)

    # Contexte de marché (transmis au LLM)
    symbol: str = "UNKNOWN"
    timeframe: str = "1h"
    n_bars: int = 0
    date_range_start: str = ""
    date_range_end: str = ""
    fees_bps: float = 10.0
    slippage_bps: float = 5.0
    initial_capital: float = 10000.0
    direction_constraint: str = "long_short"
    universe_mode: str = "canonical"
    universe_purpose: str = "builder"
    universe_strategy_type: str = ""
    universe_meta: Dict[str, Any] = field(default_factory=dict)
    builder_execution_mode: str = "mono_single_llm"
    orchestration_mode: str = "single_llm"
    instrumentation_enabled: bool = False
    instrumentation_summary: Dict[str, Any] = field(default_factory=dict)
    ablation_config: Dict[str, bool] = field(default_factory=dict)
    pipeline_traces_path: str = ""
    restriction_events: Dict[str, int] = field(default_factory=dict)
    multi_llm_profile: str = ""
    multi_llm_role_overrides: Dict[str, Any] = field(default_factory=dict)
    multi_llm_assignments: List[Dict[str, Any]] = field(default_factory=list)


def _iteration_is_recovery_anchor(
    iteration: Optional[BuilderIteration],
    *,
    allow_fallback: bool = False,
) -> bool:
    """Retourne True si l'itération peut servir de point de reprise."""
    if iteration is None:
        return False
    if iteration.error is not None:
        return False
    if iteration.backtest_result is None:
        return False
    if iteration.is_fallback and not allow_fallback:
        return False
    return True


def _select_session_recovery_anchor(
    session: BuilderSession,
    last_iteration: Optional[BuilderIteration] = None,
) -> tuple[Optional[BuilderIteration], str]:
    """Choisit le meilleur ancrage disponible pour un auto-reset de session."""
    if _iteration_is_recovery_anchor(session.best_iteration):
        return session.best_iteration, "best_iteration"

    if _iteration_is_recovery_anchor(last_iteration):
        return last_iteration, "last_iteration"

    for candidate in reversed(session.iterations):
        if _iteration_is_recovery_anchor(candidate):
            return candidate, "history_non_fallback"

    if _iteration_is_recovery_anchor(last_iteration, allow_fallback=True):
        return last_iteration, "last_iteration_fallback"

    for candidate in reversed(session.iterations):
        if _iteration_is_recovery_anchor(candidate, allow_fallback=True):
            return candidate, "history_fallback"

    return None, "none"


