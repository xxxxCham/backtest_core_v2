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

from typing import TYPE_CHECKING, Any, Dict, List, Optional

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
    from agents.builder_state import BuilderIteration, BuilderSession


# ---------------------------------------------------------------------------
# Policy overrides
# ---------------------------------------------------------------------------

def _policy_change_type_override(
    *,
    session: "BuilderSession",
    last_iteration: Optional["BuilderIteration"],
) -> Optional[str]:
    """Force un type de modification cohérent avec le diagnostic récent.

    Objectif: éviter les oscillations `both` quand le problème est clairement
    structurel (ruined/no_trades/etc.).
    """
    if last_iteration is None:
        return None

    cat = str(getattr(last_iteration, "diagnostic_category", "") or "").strip().lower()
    sev = str(
        (getattr(last_iteration, "diagnostic_detail", {}) or {}).get("severity", "")
    ).strip().lower()

    # Pattern oscillant fréquent: ruined <-> no_trades
    recent = [
        str(getattr(it, "diagnostic_category", "") or "").strip().lower()
        for it in (session.iterations[-3:] if session.iterations else [])
        if str(getattr(it, "diagnostic_category", "") or "").strip()
    ]
    if len(recent) >= 2 and set(recent[-2:]).issubset({"ruined", "no_trades"}):
        return "logic"

    logic_cats = {
        "ruined",
        "no_trades",
        "overtrading",
        "wrong_direction",
        "high_drawdown",
        "needs_work",
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
    last_iteration: Optional["BuilderIteration"],
) -> tuple[str, ...]:
    """Retourne les indicateurs de l'itération précédente depuis son code validé."""
    if last_iteration is None or not getattr(last_iteration, "code", ""):
        return tuple()
    return _extract_required_indicators_signature(last_iteration.code)


def _requires_indicator_exploration(
    last_iteration: Optional["BuilderIteration"],
) -> bool:
    """Indique si la prochaine proposition doit explorer de nouveaux indicateurs."""
    if last_iteration is None:
        return False

    stag = (getattr(last_iteration, "phase_feedback", {}) or {}).get("stagnation", {})
    if bool(stag.get("identical_metrics")):
        return True

    cat = str(getattr(last_iteration, "diagnostic_category", "") or "").strip().lower()
    return cat in {
        "ruined",
        "no_trades",
        "overtrading",
        "wrong_direction",
        "high_drawdown",
        "needs_work",
    }


# ---------------------------------------------------------------------------
# Stagnation branching
# ---------------------------------------------------------------------------

def _should_enable_stagnation_branching(
    last_iteration: Optional["BuilderIteration"],
) -> bool:
    """N'ouvre des branches supplémentaires qu'après vraie stagnation."""
    if last_iteration is None:
        return False
    stagnation = (getattr(last_iteration, "phase_feedback", {}) or {}).get("stagnation", {})
    return bool(stagnation.get("identical_metrics")) and _requires_indicator_exploration(last_iteration)


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
    last_iteration: Optional["BuilderIteration"],
    iteration: "BuilderIteration",
) -> bool:
    if last_iteration is None:
        return False
    current_stagnation = (getattr(iteration, "phase_feedback", {}) or {}).get("stagnation", {})
    previous_stagnation = (getattr(last_iteration, "phase_feedback", {}) or {}).get("stagnation", {})
    if not bool(current_stagnation.get("identical_metrics")):
        return False
    if not bool(previous_stagnation.get("identical_metrics")):
        return False
    if not _is_logic_like_change_type(iteration.change_type):
        return False
    if not _is_logic_like_change_type(getattr(last_iteration, "change_type", "")):
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
