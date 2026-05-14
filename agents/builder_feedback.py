"""Module-ID: agents.builder_feedback

Purpose: Typed-yet-flexible Builder iteration feedback containers.

The Builder needs two seemingly conflicting properties:
1. A stable, typed structure for core orchestration feedback.
2. Enough flexibility for different models to attach heterogeneous metadata.

These containers keep dict compatibility for the UI/tests/serialization while
coercing known sections into explicit section types and preserving unknown keys
inside each section as regular extras.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, ClassVar


class FeedbackSection(dict[str, Any]):
    """Base section container.

    Subclasses declare `KNOWN_KEYS` for stable fields. Unknown keys remain
    accepted and are preserved to support model-specific richness.
    """

    KNOWN_KEYS: ClassVar[frozenset[str]] = frozenset()

    def __init__(
        self,
        initial: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        if initial:
            self.update(initial)
        if kwargs:
            self.update(kwargs)

    @property
    def extras(self) -> dict[str, Any]:
        return {key: value for key, value in self.items() if key not in self.KNOWN_KEYS}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in self.items():
            if isinstance(value, FeedbackSection):
                payload[key] = value.to_dict()
            else:
                payload[key] = value
        return payload


class ProposalFeedbackSection(FeedbackSection):
    KNOWN_KEYS = frozenset(
        {
            "phase",
            "initial_kind",
            "final_kind",
            "final_valid",
            "realign_attempts",
            "realign_success",
            "issues",
            "issues_after_retry",
            "error_code",
            "source",
            "contract_retry_attempted",
            "contract_retry_used",
            "contract_retry_issues",
            "fallback_deterministic_used",
            "fallback_retry_used",
            "change_type_overridden",
            "branching_enabled",
            "branch_labels",
            "branching",
        },
    )


class CodeFeedbackSection(FeedbackSection):
    KNOWN_KEYS = frozenset(
        {
            "phase",
            "initial_kind",
            "final_kind",
            "final_valid",
            "realign_attempts",
            "realign_success",
            "validation_error",
            "validation_error_retry",
            "logic_retry_used",
            "source",
            "fallback_deterministic_used",
            "fallback_variant",
            "fallback_retry_used",
            "params_contract_fallback",
            "runtime_fix_fallback_deterministic_used",
            "safe_path_mode",
        },
    )


class PrecheckFeedbackSection(FeedbackSection):
    KNOWN_KEYS = frozenset(
        {
            "backtest_skipped",
            "no_trade_signal_profile",
            "pathological_signal_density",
            "skip_reason",
            "signal_count",
            "bar_count",
            "long_signals",
            "short_signals",
            "signal_density",
            "transition_signals",
            "transition_density",
            "repeated_same_ratio",
        },
    )


class PreReflectionFeedbackSection(FeedbackSection):
    KNOWN_KEYS = frozenset({"text", "timeout"})


class BacktestFeedbackSection(FeedbackSection):
    KNOWN_KEYS = frozenset(
        {
            "mode",
            "params_used",
            "runtime_error",
            "runtime_traceback_tail",
            "runtime_fix_applied",
            "runtime_fix_retry_error",
            "runtime_fix_validation_error",
            "runtime_fix_fallback_deterministic_used",
            "sweep_skipped_reason",
            "sweep_total_tested",
            "sweep_success",
            "sweep_failed",
            "sweep_duration_ms",
            "sweep_param_names",
            "sweep_candidate_values",
            "sweep_best_params",
            "sweep_top_results",
        },
    )


class ScoringFeedbackSection(FeedbackSection):
    KNOWN_KEYS = frozenset(
        {
            "telemetry_score",
            "continuous_score",
            "drawdown_excess_pct",
            "components",
            "penalties",
        },
    )


class DecisionFeedbackSection(FeedbackSection):
    KNOWN_KEYS = frozenset(
        {
            "positive_progress_gate",
            "stagnation_circuit_breaker",
            "stop_overridden",
            "accept_overridden",
        },
    )


class StagnationFeedbackSection(FeedbackSection):
    KNOWN_KEYS = frozenset({"identical_metrics"})


class SessionResetFeedbackSection(FeedbackSection):
    KNOWN_KEYS = frozenset(
        {
            "iteration",
            "trigger",
            "reason",
            "recovered",
            "reset_budget_exhausted",
            "reset_count",
            "anchor_source",
            "anchor_iteration",
            "preserved_best_iteration",
            "consecutive_failures_before_reset",
            "fallback_count_before_reset",
            "timestamp",
        },
    )


_SECTION_TYPES: dict[str, type[FeedbackSection]] = {
    "proposal": ProposalFeedbackSection,
    "code": CodeFeedbackSection,
    "precheck": PrecheckFeedbackSection,
    "pre_reflection": PreReflectionFeedbackSection,
    "backtest": BacktestFeedbackSection,
    "scoring": ScoringFeedbackSection,
    "decision": DecisionFeedbackSection,
    "stagnation": StagnationFeedbackSection,
    "session_reset": SessionResetFeedbackSection,
}


def _coerce_feedback_section(
    key: str,
    value: Any,
) -> Any:
    section_type = _SECTION_TYPES.get(key)
    if section_type is None:
        return value
    if value is None:
        return section_type()
    if isinstance(value, section_type):
        return value
    if isinstance(value, FeedbackSection):
        return section_type(value.to_dict())
    if isinstance(value, Mapping):
        return section_type(value)
    return value


class IterationPhaseFeedback(dict[str, Any]):
    """Typed aggregate for per-iteration Builder feedback.

    The container remains a `dict` subclass so legacy code, tests, and UI checks
    based on `isinstance(..., dict)` continue to work.
    """

    def __init__(
        self,
        initial: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        if initial:
            self.update(initial)
        if kwargs:
            self.update(kwargs)

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, _coerce_feedback_section(key, value))

    def update(
        self,
        other: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None,
        **kwargs: Any,
    ) -> None:
        if other:
            if isinstance(other, Mapping):
                iterable = other.items()
            else:
                iterable = other
            for key, value in iterable:
                self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key not in self:
            self[key] = default if default is not None else {}
        return self[key]

    @property
    def proposal(self) -> ProposalFeedbackSection:
        return self.setdefault("proposal", {})

    @property
    def code(self) -> CodeFeedbackSection:
        return self.setdefault("code", {})

    @property
    def precheck(self) -> PrecheckFeedbackSection:
        return self.setdefault("precheck", {})

    @property
    def pre_reflection(self) -> PreReflectionFeedbackSection:
        return self.setdefault("pre_reflection", {})

    @property
    def backtest(self) -> BacktestFeedbackSection:
        return self.setdefault("backtest", {})

    @property
    def scoring(self) -> ScoringFeedbackSection:
        return self.setdefault("scoring", {})

    @property
    def decision(self) -> DecisionFeedbackSection:
        return self.setdefault("decision", {})

    @property
    def stagnation(self) -> StagnationFeedbackSection:
        return self.setdefault("stagnation", {})

    @property
    def session_reset(self) -> SessionResetFeedbackSection:
        return self.setdefault("session_reset", {})

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in self.items():
            if isinstance(value, FeedbackSection):
                payload[key] = value.to_dict()
            else:
                payload[key] = value
        return payload


def coerce_iteration_phase_feedback(value: Any) -> IterationPhaseFeedback:
    if isinstance(value, IterationPhaseFeedback):
        return value
    if value is None:
        return IterationPhaseFeedback()
    if isinstance(value, Mapping):
        return IterationPhaseFeedback(value)
    return IterationPhaseFeedback()
