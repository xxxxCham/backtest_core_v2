# ruff: noqa: I001
"""
Module-ID: agents.builder_policy_helpers

Purpose: Helpers de politique itérative du Strategy Builder — override de
         change_type, détection de stagnation, branching, sélection de branche.

Role in pipeline: décision / pilotage de la boucle Builder

Dependencies: agents.builder_ast_utils, agents.builder_diagnostics,
              agents.builder_proposal_helpers (pour _normalize_change_type)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from agents.builder_ast_utils import (
    _extract_required_indicators_signature,
)
from agents.builder_diagnostics import (
    _builder_iteration_selection_key,
)
from agents.builder_proposal_helpers import (
    _is_logic_like_change_type,
    _normalize_change_type,
)

if TYPE_CHECKING:
    from agents.builder_state import BuilderIteration, BuilderSession, IterationContext


# ---------------------------------------------------------------------------
# Policy overrides
# ---------------------------------------------------------------------------

def _to_ctx(
    arg: "Union[BuilderIteration, IterationContext, None]",
) -> "IterationContext":
    """Coerce un BuilderIteration ou None en IterationContext (import tardif)."""
    from agents.builder_state import IterationContext
    if isinstance(arg, IterationContext):
        return arg
    return IterationContext(arg)


def _policy_change_type_override(
    *,
    session: "BuilderSession",
    last_iteration: "Union[BuilderIteration, IterationContext, None]" = None,
    ctx: "Optional[IterationContext]" = None,
) -> Optional[str]:
    """Force un type de modification cohérent avec le diagnostic récent."""
    c = ctx if ctx is not None else _to_ctx(last_iteration)
    if not c.exists:
        return None

    cat = c.diagnostic_category
    sev = c.diagnostic_severity

    recent = [
        _to_ctx(it).diagnostic_category
        for it in (session.iterations[-3:] if session.iterations else [])
        if _to_ctx(it).diagnostic_category
    ]
    if len(recent) >= 2 and set(recent[-2:]).issubset({"ruined", "no_trades"}):
        return "logic"

    logic_cats = {
        "ruined", "no_trades", "overtrading",
        "wrong_direction", "high_drawdown", "needs_work",
    }
    param_cats = {"approaching_target", "marginal", "target_reached"}

    if cat in logic_cats:
        return "logic"
    if cat in param_cats and sev in {"info", "success"}:
        return "params"
    return None


# ---------------------------------------------------------------------------
# Indicator exploration helpers
# ---------------------------------------------------------------------------

def _previous_iteration_indicators(
    last_iteration: "Union[BuilderIteration, IterationContext, None]" = None,
    *,
    ctx: "Optional[IterationContext]" = None,
) -> tuple[str, ...]:
    """Retourne les indicateurs de l'itération précédente depuis son code validé."""
    c = ctx if ctx is not None else _to_ctx(last_iteration)
    if not c.code:
        return tuple()
    return _extract_required_indicators_signature(c.code)


def _requires_indicator_exploration(
    last_iteration: "Union[BuilderIteration, IterationContext, None]" = None,
    *,
    ctx: "Optional[IterationContext]" = None,
) -> bool:
    """Indique si la prochaine proposition doit explorer de nouveaux indicateurs."""
    c = ctx if ctx is not None else _to_ctx(last_iteration)
    if not c.exists:
        return False
    if c.has_identical_metrics_stagnation:
        return True
    return c.is_category(
        "ruined", "no_trades", "overtrading",
        "wrong_direction", "high_drawdown", "needs_work",
    )


# ---------------------------------------------------------------------------
# Stagnation branching
# ---------------------------------------------------------------------------

def _should_enable_stagnation_branching(
    last_iteration: "Union[BuilderIteration, IterationContext, None]" = None,
    *,
    ctx: "Optional[IterationContext]" = None,
) -> bool:
    """N'ouvre des branches supplémentaires qu'après vraie stagnation."""
    c = ctx if ctx is not None else _to_ctx(last_iteration)
    if not c.exists:
        return False
    return c.has_identical_metrics_stagnation and _requires_indicator_exploration(ctx=c)


def _build_stagnation_branch_specs(
    previous_indicators: tuple[str, ...],
) -> List[Dict[str, str]]:
    previous_text = ", ".join(previous_indicators) if previous_indicators else "the previous indicator set"
    return [
        {
            "label": "keep",
            "directive": (
                "STAGNATION BRANCH: KEEP_SET. Reuse exactly the previous indicator set "
                f"({previous_text}) but materially change the logic, filters, sequencing, or regime interpretation. "
                "Do not add or remove indicators in this branch."
            ),
        },
        {
            "label": "add_one",
            "directive": (
                "STAGNATION BRANCH: ADD_ONE. Start from the previous indicator set "
                f"({previous_text}) and add exactly one new indicator from the available list. "
                "The added indicator must address the current failure mode."
            ),
        },
        {
            "label": "remove_or_replace",
            "directive": (
                "STAGNATION BRANCH: REMOVE_OR_REPLACE. Starting from the previous indicator set "
                f"({previous_text}), either remove one weak/noisy indicator or replace one previous indicator "
                "with a more relevant one. A smaller set is allowed if it improves clarity."
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Stagnation circuit breaker
# ---------------------------------------------------------------------------

def _should_trip_logic_stagnation_circuit(
    last_iteration: "Union[BuilderIteration, IterationContext, None]",
    iteration: "BuilderIteration",
) -> bool:
    prev = _to_ctx(last_iteration)
    if not prev.exists:
        return False
    cur = _to_ctx(iteration)
    if not cur.has_identical_metrics_stagnation:
        return False
    if not prev.has_identical_metrics_stagnation:
        return False
    if not _is_logic_like_change_type(iteration.change_type):
        return False
    if not _is_logic_like_change_type(prev.change_type):
        return False
    return True


# ---------------------------------------------------------------------------
# Branch selection
# ---------------------------------------------------------------------------

def _select_best_branch_candidate(
    outcomes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    successful = [outcome for outcome in outcomes if not outcome.get("error") and outcome.get("bt_result") is not None]
    if not successful:
        return outcomes[0] if outcomes else {}

    branch_preference = {
        "add_one": 2,
        "remove_or_replace": 1,
        "keep": 0,
    }

    def _outcome_metrics(outcome: Dict[str, Any]) -> Dict[str, Any]:
        metrics = outcome.get("metrics")
        if isinstance(metrics, dict):
            return metrics
        bt_result = outcome.get("bt_result")
        bt_metrics = getattr(bt_result, "metrics", None)
        return bt_metrics if isinstance(bt_metrics, dict) else {}

    successful.sort(
        key=lambda outcome: (
            *_builder_iteration_selection_key(
                _outcome_metrics(outcome),
                is_fallback=bool(outcome.get("is_fallback", False)),
                target_sharpe=float(outcome.get("target_sharpe", 1.0) or 1.0),
            ),
            branch_preference.get(str(outcome.get("branch_label", "")), 0),
        ),
        reverse=True,
    )
    return successful[0]
