"""Handler for report generation, result building, and iteration recording."""

from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from utils.observability import get_obs_logger

from ..base_agent import BaseAgent
from ..state_machine import AgentState

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator, OrchestratorResult

logger = get_obs_logger(__name__)


def record_iteration(orch: "Orchestrator", decision: Optional[str] = None) -> None:
    """Record current iteration in history."""
    entry: Dict[str, Any] = {
        "iteration": orch.state_machine.iteration,
        "timestamp": datetime.now().isoformat(),
        "params": orch.context.current_params.copy(),
    }

    if orch.context.current_metrics:
        entry.update(
            {
                "sharpe_ratio": orch.context.current_metrics.sharpe_ratio,
                "total_return": orch.context.current_metrics.total_return,
                "max_drawdown": orch.context.current_metrics.max_drawdown,
            }
        )

    entry["proposals_count"] = len(orch.context.strategist_proposals)
    entry["concerns_count"] = len(orch.context.critic_concerns)
    if decision:
        entry["decision"] = decision

    orch.context.iteration_history.append(entry)

    orch._log_event(
        "iteration_recorded",
        iteration=entry["iteration"],
        sharpe=entry.get("sharpe_ratio"),
        total_return=entry.get("total_return"),
        max_drawdown=entry.get("max_drawdown"),
        proposals_count=entry.get("proposals_count", 0),
        concerns_count=entry.get("concerns_count", 0),
        decision=decision,
    )
    orch._append_memory_iteration(entry)


def generate_final_report(orch: "Orchestrator") -> str:
    """Generate a detailed final report including tracker statistics."""
    lines = [
        "=" * 80,
        "\U0001f4ca RAPPORT FINAL D'OPTIMISATION MULTI-AGENTS",
        "=" * 80,
        "",
        f"\U0001f516 Session ID: {orch.session_id}",
        f"\U0001f4c8 Stratégie: {orch.config.strategy_name}",
        f"\U0001f504 Itérations totales: {orch.state_machine.iteration}",
        f"\U0001f9ea Backtests exécutés: {orch._backtests_count}",
        f"\U0001f916 Combinaisons testées: {orch._total_combinations_tested}",
        f"\U0001f50d Sweeps effectués: {orch._sweeps_performed}/{orch._max_sweeps_per_session}",
        "",
    ]

    # Final state
    final_state = orch.state_machine.current_state
    if final_state == AgentState.APPROVED:
        decision_label = "\u2705 APPROUV\u00c9"
    elif final_state == AgentState.REJECTED:
        decision_label = "\u274c REJET\u00c9"
    else:
        decision_label = "\u26a0\ufe0f AVORT\u00c9"
    lines.extend(
        [
            "\U0001f4cc D\u00c9CISION FINALE:",
            f"  \u00c9tat: {final_state.name}",
            f"  D\u00e9cision: {decision_label}",
            "",
        ]
    )

    # Walk-forward status
    if orch.config.walk_forward_disabled_reason:
        lines.extend(
            [
                "\u26a0\ufe0f WALK-FORWARD VALIDATION:",
                "  Status: D\u00c9SACTIV\u00c9 AUTOMATIQUEMENT",
                f"  Raison: {orch.config.walk_forward_disabled_reason}",
                "",
            ]
        )
    elif orch.config.use_walk_forward:
        lines.extend(
            [
                "\u2705 WALK-FORWARD VALIDATION:",
                "  Status: ACTIV\u00c9",
                f"  Windows: {orch.config.walk_forward_windows}",
                f"  Train ratio: {orch.config.train_ratio:.0%}",
                "",
            ]
        )

    # Best results
    if orch.context.best_metrics:
        lines.extend(
            [
                "\U0001f3c6 MEILLEURS R\u00c9SULTATS OBTENUS:",
                f"  \U0001f4ca Sharpe Ratio: {orch.context.best_metrics.sharpe_ratio:.3f}",
                f"  \U0001f4b0 Total Return: {orch.context.best_metrics.total_return:.2%}",
                f"  \U0001f4c9 Max Drawdown: {orch.context.best_metrics.max_drawdown:.2%}",
            ]
        )
        if hasattr(orch.context.best_metrics, "win_rate"):
            lines.append(
                f"  \U0001f3af Win Rate: {orch.context.best_metrics.win_rate:.1%}"
            )
        lines.extend(
            [
                f"  \U0001f522 Total Trades: {orch.context.best_metrics.total_trades}",
                "",
                "\u2699\ufe0f  Param\u00e8tres optimaux:",
            ]
        )
        for k, v in (orch.context.best_params or {}).items():
            if isinstance(v, float):
                lines.append(f"    \u2022 {k}: {v:.4f}")
            else:
                lines.append(f"    \u2022 {k}: {v}")
        lines.append("")

    # Agent activity
    lines.extend(
        [
            "=" * 80,
            "\U0001f916 ACTIVIT\u00c9 DES AGENTS",
            "=" * 80,
            "",
        ]
    )

    def _agent_stats(agent: BaseAgent, name: str) -> List[str]:
        stats = getattr(agent, "stats", {})
        tokens = stats.get("total_tokens", 0)
        calls = stats.get("execution_count", 0)
        return [
            f"\U0001f539 {name}:",
            f"    Appels LLM: {calls}",
            f"    Tokens utilis\u00e9s: {tokens:,}",
        ]

    lines.extend(_agent_stats(orch.analyst, "Agent Analyst"))
    lines.extend(_agent_stats(orch.strategist, "Agent Strategist"))
    lines.extend(_agent_stats(orch.critic, "Agent Critic"))
    lines.extend(_agent_stats(orch.validator, "Agent Validator"))
    lines.append("")

    # Iteration history
    if orch.context.iteration_history:
        lines.extend(
            [
                "=" * 80,
                "\U0001f4dc HISTORIQUE DES IT\u00c9RATIONS",
                "=" * 80,
                "",
            ]
        )
        for i, hist in enumerate(orch.context.iteration_history[-10:], 1):
            iter_num = hist.get("iteration", i)
            sharpe = hist.get("sharpe_ratio", 0)
            ret = hist.get("total_return", 0)
            params = hist.get("params", {})
            hist_decision = hist.get("decision", "N/A")

            lines.extend(
                [
                    f"It\u00e9ration #{iter_num}:",
                    f"  Sharpe: {sharpe:.3f} | Return: {ret:.2%}",
                    f"  D\u00e9cision: {hist_decision}",
                ]
            )
            if params and len(params) <= 5:
                param_str = ", ".join(f"{k}={v}" for k, v in params.items())
                lines.append(f"  Params: {param_str}")
            lines.append("")

    # Sweep statistics
    if orch._sweeps_performed > 0:
        lines.extend(
            [
                "=" * 80,
                "\U0001f50d STATISTIQUES GRID SEARCH (SWEEPS)",
                "=" * 80,
                "",
                f"  Nombre de sweeps: {orch._sweeps_performed}",
                f"  Limite par session: {orch._max_sweeps_per_session}",
                f"  Combinaisons test\u00e9es via sweeps: "
                f"{orch._total_combinations_tested - orch._backtests_count}",
                "",
            ]
        )

        if hasattr(orch, "_ranges_tracker"):
            ranges_summary = orch._ranges_tracker.get_summary(max_ranges=5)
            if ranges_summary != "Aucune range test\u00e9e dans cette session.":
                lines.extend(
                    [
                        "Ranges explor\u00e9es:",
                        ranges_summary,
                        "",
                    ]
                )

    # Session tracker stats
    if hasattr(orch, "param_tracker"):
        lines.extend(
            [
                "=" * 80,
                "\U0001f4ca STATISTIQUES DE SESSION",
                "=" * 80,
                "",
                f"  \u2705 Tests uniques: {orch.param_tracker.get_tested_count()}",
                f"  \U0001f504 Duplications \u00e9vit\u00e9es: {orch.param_tracker.get_duplicates_prevented()}",
                "",
            ]
        )

        best_sharpe = orch.param_tracker.get_best_params("sharpe_ratio")
        if best_sharpe:
            lines.extend(
                [
                    "\U0001f3c5 Meilleur Sharpe Ratio test\u00e9:",
                    f"    Valeur: {best_sharpe.sharpe_ratio:.3f}",
                ]
            )
            if hasattr(best_sharpe, "total_return") and best_sharpe.total_return:
                lines.append(f"    Return: {best_sharpe.total_return:.2%}")
            lines.append("    Param\u00e8tres:")
            for k, v in best_sharpe.params.items():
                if isinstance(v, float):
                    lines.append(f"      \u2022 {k}: {v:.4f}")
                else:
                    lines.append(f"      \u2022 {k}: {v}")
            lines.append("")

    # Warnings and errors
    if orch._warnings or orch._errors:
        lines.extend(
            [
                "=" * 80,
                "\u26a0\ufe0f  AVERTISSEMENTS ET ERREURS",
                "=" * 80,
                "",
            ]
        )
        if orch._warnings:
            lines.extend(
                [
                    "Avertissements:",
                    *[f"  \u26a0\ufe0f  {w}" for w in orch._warnings],
                    "",
                ]
            )
        if orch._errors:
            lines.extend(
                [
                    "Erreurs:",
                    *[f"  \u274c {e}" for e in orch._errors],
                    "",
                ]
            )

    lines.append("=" * 80)
    return "\n".join(lines)


def build_result(orch: "Orchestrator") -> "OrchestratorResult":
    """Build the final orchestration result."""
    from ..orchestrator import OrchestratorResult

    elapsed = time.time() - orch._start_time if orch._start_time else 0

    # Determine final decision
    final_state = orch.state_machine.current_state
    if final_state == AgentState.APPROVED:
        decision = "APPROVE"
        success = True
    elif final_state == AgentState.REJECTED:
        decision = "REJECT"
        success = False
    else:
        decision = "ABORT"
        success = False

    # LLM statistics
    def _get_agent_stats(agent: BaseAgent) -> Dict[str, int]:
        stats = getattr(agent, "stats", {})
        return {
            "total_tokens": stats.get("total_tokens", 0),
            "execution_count": stats.get("execution_count", 0),
        }

    agents = [orch.analyst, orch.strategist, orch.critic, orch.validator]
    total_tokens = sum(_get_agent_stats(a)["total_tokens"] for a in agents)
    total_calls = sum(_get_agent_stats(a)["execution_count"] for a in agents)

    # Generate final report
    final_report = generate_final_report(orch)

    # Recommendations
    recommendations: List[str] = []
    if hasattr(orch, "param_tracker"):
        duplicates = orch.param_tracker.get_duplicates_prevented()
        if duplicates > 0:
            recommendations.append(
                f"\u2705 {duplicates} duplications de param\u00e8tres \u00e9vit\u00e9es durant la session"
            )
        if orch.param_tracker.get_tested_count() > 0:
            recommendations.append(
                f"\U0001f4ca {orch.param_tracker.get_tested_count()} combinaisons uniques test\u00e9es"
            )

    return OrchestratorResult(
        success=success,
        final_state=final_state,
        decision=decision,
        final_params=orch.context.best_params or orch.context.current_params,
        final_metrics=orch.context.best_metrics,
        total_iterations=orch.state_machine.iteration,
        total_backtests=orch._backtests_count,
        total_time_s=elapsed,
        total_llm_tokens=total_tokens,
        total_llm_calls=total_calls,
        iteration_history=orch.context.iteration_history,
        state_history=orch.state_machine.get_summary()["history"],
        final_report=final_report,
        recommendations=recommendations,
        errors=orch._errors,
        warnings=orch._warnings,
    )
