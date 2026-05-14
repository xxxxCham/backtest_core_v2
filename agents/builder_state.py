"""Module-ID: agents.builder_state

Purpose: Shared Builder session/iteration state types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

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
    backtest_result: Any | None = None
    error: str | None = None
    analysis: str = ""
    decision: str = ""  # "continue", "accept", "stop"
    change_type: str = ""  # "logic", "params", "both"
    diagnostic_category: str = ""  # computed by compute_diagnostic()
    diagnostic_detail: dict[str, Any] = field(default_factory=dict)
    phase_feedback: IterationPhaseFeedback = field(
        default_factory=IterationPhaseFeedback,
    )
    timestamp: datetime = field(default_factory=datetime.now)
    is_fallback: bool = False  # True if deterministic fallback was used
    used_indicators: list[str] = field(default_factory=list)
    perf_score: float = 0.0  # median generate_signals time in ms (micro-benchmark)
    code_quality_score: float = 1.0  # 0–1 composite quality (speed + repair count)

    def __post_init__(self) -> None:
        self.phase_feedback = coerce_iteration_phase_feedback(
            self.phase_feedback,
        )

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "phase_feedback":
            value = coerce_iteration_phase_feedback(value)
        super().__setattr__(name, value)


class IterationContext:
    """Wrapper null-safe autour de BuilderIteration.

    Élimine les 30+ guards ``if last_iteration is None`` dispersés dans le
    codebase.  Toutes les propriétés retournent une valeur sûre (jamais None)
    pour que les appelants n'aient plus besoin de vérifier.
    """

    __slots__ = ("_it",)

    def __init__(self, iteration: BuilderIteration | None = None) -> None:
        self._it = iteration

    # --- Existence -----------------------------------------------------------
    @property
    def exists(self) -> bool:
        """True si une itération réelle est encapsulée."""
        return self._it is not None

    @property
    def raw(self) -> BuilderIteration | None:
        """Accès direct (pour les rares cas où l'objet brut est nécessaire)."""
        return self._it

    # --- Propriétés null-safe ------------------------------------------------
    @property
    def code(self) -> str:
        return self._it.code if self._it and self._it.code else ""

    @property
    def analysis(self) -> str:
        return self._it.analysis if self._it else ""

    @property
    def hypothesis(self) -> str:
        return self._it.hypothesis if self._it else ""

    @property
    def change_type(self) -> str:
        return self._it.change_type if self._it else ""

    @property
    def diagnostic_category(self) -> str:
        return (self._it.diagnostic_category or "").strip().lower() if self._it else ""

    @property
    def diagnostic_detail(self) -> dict[str, Any]:
        if self._it and self._it.diagnostic_detail:
            return dict(self._it.diagnostic_detail)
        return {}

    @property
    def diagnostic_severity(self) -> str:
        return str(self.diagnostic_detail.get("severity", "")).strip().lower()

    @property
    def diagnostic_actions(self) -> list[str]:
        return self.diagnostic_detail.get("actions", [])

    @property
    def diagnostic_donts(self) -> list[str]:
        return self.diagnostic_detail.get("donts", [])

    @property
    def used_indicators(self) -> list[str]:
        if self._it and self._it.used_indicators:
            return list(self._it.used_indicators)
        return []

    @property
    def is_fallback(self) -> bool:
        return bool(self._it.is_fallback) if self._it else False

    # --- Backtest ------------------------------------------------------------
    @property
    def has_backtest(self) -> bool:
        return self._it is not None and self._it.backtest_result is not None

    @property
    def metrics(self) -> dict[str, Any]:
        if self.has_backtest:
            m = self._it.backtest_result.metrics  # type: ignore[union-attr]
            return m if isinstance(m, dict) else {}
        return {}

    # --- Phase feedback ------------------------------------------------------
    @property
    def phase_feedback_dict(self) -> dict[str, Any]:
        if self._it is None:
            return {}
        raw = self._it.phase_feedback
        d = raw.to_dict() if hasattr(raw, "to_dict") else (raw or {})
        return d if isinstance(d, dict) else {}

    @property
    def backtest_feedback(self) -> dict[str, Any]:
        bf = self.phase_feedback_dict.get("backtest", {})
        return bf if isinstance(bf, dict) else {}

    @property
    def stagnation(self) -> dict[str, Any]:
        s = self.phase_feedback_dict.get("stagnation", {})
        return s if isinstance(s, dict) else {}

    @property
    def has_identical_metrics_stagnation(self) -> bool:
        return bool(self.stagnation.get("identical_metrics"))

    # --- Raccourcis combinés -------------------------------------------------
    def metric(self, key: str, default: float = 0.0) -> float:
        return float(self.metrics.get(key, default) or default)

    def is_category(self, *cats: str) -> bool:
        return self.diagnostic_category in cats


@dataclass
class BuilderSession:
    """Session complète de construction de stratégie."""

    session_id: str
    objective: str
    session_dir: Path
    available_indicators: list[str] = field(default_factory=list)

    # État
    iterations: list[BuilderIteration] = field(default_factory=list)
    best_iteration: BuilderIteration | None = None
    best_sharpe: float = float("-inf")
    best_score: float = float("-inf")  # Telemetry only, no longer drives loop decisions.
    status: str = "running"  # "running", "success", "failed", "max_iterations"
    auto_reset_count: int = 0
    recovery_events: list[dict[str, Any]] = field(default_factory=list)

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
    objective_indicators: list[str] = field(default_factory=list)
    indicator_lock_mode: str = ""
    universe_mode: str = "canonical"
    universe_purpose: str = "builder"
    universe_strategy_type: str = ""
    universe_meta: dict[str, Any] = field(default_factory=dict)
    builder_execution_mode: str = "mono_single_llm"
    orchestration_mode: str = "single_llm"
    instrumentation_enabled: bool = False
    instrumentation_summary: dict[str, Any] = field(default_factory=dict)
    ablation_config: dict[str, bool] = field(default_factory=dict)
    pipeline_traces_path: str = ""
    restriction_events: dict[str, int] = field(default_factory=dict)
    model_name: str = ""
    cross_session_memory: list[dict[str, Any]] = field(default_factory=list)

    # Reprise de session Builder max_iterations
    resume_parent_session_id: str = ""
    resume_mode: str = ""
    resume_from_iteration: int = 0
    resume_extra_iterations: int = 0
    resume_original_status: str = ""
    resume_source_summary_path: str = ""
    resume_original_model_name: str = ""
    resume_requested_model_name: str = ""


def _iteration_is_recovery_anchor(
    iteration: BuilderIteration | None,
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


def compute_session_generation_stats(session: BuilderSession) -> dict[str, Any]:
    """Calcule les statistiques canonique vs déterministe d'une session.

    Retourne un dict avec ``total``, ``canonical`` (LLM),
    ``deterministic`` (fallback), ``canonical_rate`` (0.0–1.0).
    """
    iterations = session.iterations or []
    total = len(iterations)
    if total == 0:
        return {"total": 0, "canonical": 0, "deterministic": 0, "canonical_rate": 0.0}
    deterministic = sum(1 for it in iterations if it.is_fallback)
    canonical = total - deterministic
    return {
        "total": total,
        "canonical": canonical,
        "deterministic": deterministic,
        "canonical_rate": canonical / total,
    }


def _select_session_recovery_anchor(
    session: BuilderSession,
    last_iteration: BuilderIteration | None = None,
) -> tuple[BuilderIteration | None, str]:
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
