"""
Module-ID: agents.builder_session_io

Purpose: Fonctions d'I/O de session Builder — persistance des checkpoints,
         résumés de session, leaderboards et gestion du cycle de vie session.

Role in pipeline: persistence / session lifecycle

Dependencies: agents.builder_diagnostics, agents.builder_state,
              agents.builder_objective_parser, backtest.result_store
"""
from __future__ import annotations

import csv
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backtest.result_store import get_builder_sessions_dir
from utils.observability import get_obs_logger

from agents.builder_diagnostics import (
    _builder_iteration_selection_key,
    compute_builder_telemetry_score,
)
from agents.builder_objective_parser import sanitize_objective_text
from agents.builder_state import (
    BuilderIteration,
    BuilderSession,
    _select_session_recovery_anchor,
)

logger = get_obs_logger(__name__)

SANDBOX_ROOT = get_builder_sessions_dir()

MAX_SESSION_AUTO_RESETS = int(os.getenv("BACKTEST_BUILDER_MAX_SESSION_RESETS", "2"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate_runtime_traceback_tail(
    text: Any,
    *,
    max_lines: int = 25,
    max_chars: int = 4000,
) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    lines = raw.splitlines()
    if len(lines) > max_lines:
        raw = "\n".join(lines[-max_lines:])
    if len(raw) > max_chars:
        raw = raw[-max_chars:]
    return raw.strip()


# ---------------------------------------------------------------------------
# Session identity
# ---------------------------------------------------------------------------

def create_session_id(objective: str) -> str:
    """Génère un identifiant de session unique."""
    normalized = sanitize_objective_text(objective).lower()
    slug = re.sub(r"[^a-z0-9]+", "_", normalized)[:40].strip("_")
    if not slug:
        slug = "builder_session"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{slug}"


def get_session_dir(session_id: str) -> Path:
    """Retourne le chemin du dossier sandbox pour une session."""
    return SANDBOX_ROOT / session_id


# ---------------------------------------------------------------------------
# Persistence — strategy code & runtime checkpoints
# ---------------------------------------------------------------------------

def persist_session_strategy_code(
    session: BuilderSession,
    code: str,
) -> None:
    """Persiste le code effectivement retenu pour la session courante."""
    if not code:
        return
    try:
        (session.session_dir / "strategy.py").write_text(code, encoding="utf-8")
    except (
        ValueError,
        KeyError,
        RuntimeError,
        AttributeError,
        TypeError,
        IndexError,
        OSError,
    ):
        logger.debug(
            "builder_strategy_code_persist_failed session=%s",
            getattr(session, "session_id", "unknown"),
            exc_info=True,
        )


def persist_runtime_checkpoint(
    session: BuilderSession,
    *,
    iteration_num: int,
    stage: str,
    status: str,
    branch_label: str = "main",
    error: str = "",
    traceback_tail: str = "",
    proposal_feedback: Optional[Dict[str, Any]] = None,
    code_feedback: Optional[Dict[str, Any]] = None,
    precheck_feedback: Optional[Dict[str, Any]] = None,
    backtest_feedback: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Persiste un checkpoint léger pour diagnostiquer un crash intra-itération."""
    timestamp = datetime.now().isoformat()
    checkpoint_path = (
        session.session_dir / f"iteration_{int(iteration_num):03d}_runtime_checkpoint.json"
    )
    latest_path = session.session_dir / "runtime_checkpoint.json"

    payload: Dict[str, Any] = {}
    try:
        if checkpoint_path.exists():
            raw_payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if isinstance(raw_payload, dict):
                payload = dict(raw_payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        payload = {}

    events = payload.get("events", [])
    if not isinstance(events, list):
        events = []

    trimmed_error = str(error or "").strip()
    trimmed_traceback = _truncate_runtime_traceback_tail(traceback_tail)
    event_payload: Dict[str, Any] = {
        "timestamp": timestamp,
        "stage": str(stage or "").strip(),
        "status": str(status or "").strip(),
    }
    if trimmed_error:
        event_payload["error"] = trimmed_error
    if trimmed_traceback:
        event_payload["traceback_tail"] = trimmed_traceback
    events = [*events[-19:], event_payload]

    serialized_payload = {
        "session_id": session.session_id,
        "objective": session.objective,
        "iteration": int(iteration_num),
        "branch_label": str(branch_label or "main"),
        "stage": str(stage or "").strip(),
        "status": str(status or "").strip(),
        "updated_at": timestamp,
        "strategy_file": "strategy.py",
        "strategy_version_file": f"strategy_v{int(iteration_num)}.py",
        "error": trimmed_error or None,
        "traceback_tail": trimmed_traceback or None,
        "proposal_feedback": dict(proposal_feedback or {}),
        "code_feedback": dict(code_feedback or {}),
        "precheck_feedback": dict(precheck_feedback or {}),
        "backtest_feedback": dict(backtest_feedback or {}),
        "events": events,
    }
    if isinstance(extra, dict) and extra:
        serialized_payload["extra"] = dict(extra)

    for destination in (checkpoint_path, latest_path):
        try:
            destination.write_text(
                json.dumps(serialized_payload, indent=2, default=str),
                encoding="utf-8",
            )
        except (
            OSError,
            ValueError,
            RuntimeError,
            AttributeError,
            TypeError,
            IndexError,
        ):
            logger.debug(
                "builder_runtime_checkpoint_persist_failed session=%s stage=%s status=%s",
                getattr(session, "session_id", "unknown"),
                stage,
                status,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Session summaries & leaderboard
# ---------------------------------------------------------------------------

def safe_save_session_summary(session: BuilderSession) -> None:
    """Checkpoint best-effort pour survivre aux arrêts anormaux."""
    try:
        save_session_summary(session)
    except (
        ValueError,
        KeyError,
        RuntimeError,
        AttributeError,
        TypeError,
        IndexError,
        NameError,
    ) as exc:
        logger.warning(
            "builder_session_checkpoint_failed session=%s error=%s",
            getattr(session, "session_id", "unknown"),
            exc,
        )


def save_session_summary(session: BuilderSession) -> None:
    """Sauvegarde un résumé JSON de la session."""
    iteration_rows: List[Dict[str, Any]] = []
    last_runtime_feedback: Dict[str, Any] = {
        "last_runtime_error": None,
        "last_runtime_error_iteration": None,
        "last_runtime_traceback_tail": None,
    }
    for it in session.iterations:
        metrics = (
            it.backtest_result.metrics
            if it.backtest_result and isinstance(it.backtest_result.metrics, dict)
            else {}
        )
        phase_feedback = (
            it.phase_feedback.to_dict()
            if hasattr(it.phase_feedback, "to_dict")
            else (it.phase_feedback if isinstance(it.phase_feedback, dict) else {})
        )
        backtest_feedback = (
            phase_feedback.get("backtest", {})
            if isinstance(phase_feedback, dict)
            else {}
        )
        if not isinstance(backtest_feedback, dict):
            backtest_feedback = {}
        score_payload = (
            compute_builder_telemetry_score(
                metrics,
                target_sharpe=session.target_sharpe,
            )
            if metrics
            else {}
        )
        row = {
            "iteration": it.iteration,
            "hypothesis": it.hypothesis,
            "change_type": it.change_type,
            "diagnostic_category": it.diagnostic_category,
            "error": it.error,
            "decision": it.decision,
            "evaluation_mode": backtest_feedback.get("mode"),
            "params_used": backtest_feedback.get("params_used"),
            "sweep_total_tested": backtest_feedback.get("sweep_total_tested"),
            "sweep_success": backtest_feedback.get("sweep_success"),
            "sweep_failed": backtest_feedback.get("sweep_failed"),
            "sharpe": metrics.get("sharpe_ratio") if metrics else None,
            "total_pnl": metrics.get("total_pnl") if metrics else None,
            "return_pct": metrics.get("total_return_pct") if metrics else None,
            "max_drawdown_pct": metrics.get("max_drawdown_pct") if metrics else None,
            "profit_factor": metrics.get("profit_factor") if metrics else None,
            "win_rate_pct": metrics.get("win_rate_pct") if metrics else None,
            "trades": metrics.get("total_trades") if metrics else None,
            "telemetry_score": score_payload.get("score") if score_payload else None,
            "continuous_score": score_payload.get("score") if score_payload else None,
            "telemetry_breakdown": {
                "components": score_payload.get("components", {}) if score_payload else {},
                "penalties": score_payload.get("penalties", {}) if score_payload else {},
                "drawdown_excess_pct": score_payload.get("drawdown_excess_pct", 0.0) if score_payload else 0.0,
            }
            if score_payload
            else None,
            "score_breakdown": {
                "components": score_payload.get("components", {}) if score_payload else {},
                "penalties": score_payload.get("penalties", {}) if score_payload else {},
                "drawdown_excess_pct": score_payload.get("drawdown_excess_pct", 0.0) if score_payload else 0.0,
            }
            if score_payload
            else None,
            "score_card": (
                it.diagnostic_detail.get("score_card")
                if it.diagnostic_detail else None
            ),
            "is_fallback": it.is_fallback,
            "phase_feedback": phase_feedback or None,
        }
        iteration_rows.append(row)

        runtime_error = str(backtest_feedback.get("runtime_error") or "").strip()
        runtime_traceback_tail = str(
            backtest_feedback.get("runtime_traceback_tail") or ""
        ).strip()
        if runtime_error or runtime_traceback_tail:
            last_runtime_feedback = {
                "last_runtime_error": runtime_error or None,
                "last_runtime_error_iteration": it.iteration,
                "last_runtime_traceback_tail": runtime_traceback_tail or None,
            }

    leaderboard = sorted(
        [row for row in iteration_rows if row.get("sharpe") is not None],
        key=lambda row: _builder_iteration_selection_key(
            {
                "sharpe_ratio": row.get("sharpe"),
                "total_return_pct": row.get("return_pct"),
                "max_drawdown_pct": row.get("max_drawdown_pct"),
                "profit_factor": row.get("profit_factor"),
                "total_trades": row.get("trades"),
                "win_rate_pct": row.get("win_rate_pct"),
            },
            is_fallback=bool(row.get("is_fallback", False)),
            target_sharpe=session.target_sharpe,
        ),
        reverse=True,
    )
    for rank, row in enumerate(leaderboard, start=1):
        row["rank"] = rank

    summary = {
        "session_id": session.session_id,
        "objective": session.objective,
        "status": session.status,
        "best_sharpe": session.best_sharpe,
        "best_telemetry_score": session.best_score,
        "best_score": session.best_score,
        "symbol": session.symbol,
        "timeframe": session.timeframe,
        "n_bars": session.n_bars,
        "date_range_start": session.date_range_start,
        "date_range_end": session.date_range_end,
        "initial_capital": session.initial_capital,
        "fees_bps": session.fees_bps,
        "slippage_bps": session.slippage_bps,
        "universe_mode": session.universe_mode,
        "universe_purpose": session.universe_purpose,
        "universe_strategy_type": session.universe_strategy_type,
        "universe_meta": session.universe_meta,
        "start_time": session.start_time.isoformat(),
        "auto_reset_count": session.auto_reset_count,
        "recovery_events": session.recovery_events,
        "total_iterations": len(session.iterations),
        "available_indicators": session.available_indicators,
        "builder_execution_mode": session.builder_execution_mode,
        "orchestration_mode": session.orchestration_mode,
        "instrumentation_enabled": session.instrumentation_enabled,
        "instrumentation_summary": session.instrumentation_summary,
        "ablation_config": session.ablation_config,
        "pipeline_traces_path": session.pipeline_traces_path,
        "restriction_events": session.restriction_events,
        "multi_llm_profile": (
            session.multi_llm_profile
            if session.orchestration_mode == "multi_llm"
            else ""
        ),
        "multi_llm_role_overrides": (
            session.multi_llm_role_overrides
            if session.orchestration_mode == "multi_llm"
            else {}
        ),
        "multi_llm_assignments": (
            session.multi_llm_assignments
            if session.orchestration_mode == "multi_llm"
            else []
        ),
        "last_runtime_error": last_runtime_feedback.get("last_runtime_error"),
        "last_runtime_error_iteration": last_runtime_feedback.get("last_runtime_error_iteration"),
        "last_runtime_traceback_tail": last_runtime_feedback.get("last_runtime_traceback_tail"),
        "iterations": iteration_rows,
        "leaderboard": leaderboard,
    }

    summary_path = session.session_dir / "session_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )

    if leaderboard:
        csv_path = session.session_dir / "leaderboard_builder.csv"
        md_path = session.session_dir / "leaderboard_builder.md"
        csv_fields = [
            "rank",
            "iteration",
            "decision",
            "evaluation_mode",
            "sweep_total_tested",
            "sharpe",
            "return_pct",
            "max_drawdown_pct",
            "profit_factor",
            "win_rate_pct",
            "trades",
            "change_type",
            "diagnostic_category",
            "is_fallback",
            "error",
            "hypothesis",
        ]
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=csv_fields, extrasaction="ignore")
            writer.writeheader()
            for row in leaderboard:
                writer.writerow(row)

        lines = [
            f"# Leaderboard Builder - session {session.session_id}",
            "",
            f"Objective: {session.objective}",
            f"Status: {session.status}",
            f"Best Sharpe: {session.best_sharpe:.3f}",
            "",
            "| Rank | Iter | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for row in leaderboard:
            lines.append(
                "| {rank} | {it} | {sharpe:.3f} | {ret:+.2f}% | {dd:.2f}% | {pf:.2f} | {trades} | {decision} | {cat} |".format(
                    rank=int(row.get("rank", 0) or 0),
                    it=int(row.get("iteration", 0) or 0),
                    sharpe=float(row.get("sharpe", 0.0) or 0.0),
                    ret=float(row.get("return_pct", 0.0) or 0.0),
                    dd=float(row.get("max_drawdown_pct", 0.0) or 0.0),
                    pf=float(row.get("profit_factor", 0.0) or 0.0),
                    trades=int(row.get("trades", 0) or 0),
                    decision=str(row.get("decision", "") or ""),
                    cat=str(row.get("diagnostic_category", "") or ""),
                )
            )
        md_path.write_text("\n".join(lines), encoding="utf-8")

    # Auto-route into strategy catalog (best-effort, non-blocking).
    try:
        from catalog.strategy_catalog import upsert_from_builder_session
        upsert_from_builder_session(session)
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError) as exc:
        logger.warning("builder_catalog_upsert_failed session=%s error=%s", session.session_id, exc)


# ---------------------------------------------------------------------------
# Session auto-reset
# ---------------------------------------------------------------------------

def attempt_session_auto_reset(
    session: BuilderSession,
    *,
    iteration_num: int,
    trigger: str,
    reason: str,
    last_iteration: Optional[BuilderIteration],
    consecutive_failures: int,
    fallback_count: int,
) -> Tuple[bool, Optional[BuilderIteration], int, int, Dict[str, Any]]:
    """Réinitialise proprement la session autour du meilleur ancrage disponible."""
    if session.auto_reset_count >= MAX_SESSION_AUTO_RESETS:
        return False, last_iteration, consecutive_failures, fallback_count, {
            "trigger": trigger,
            "reason": reason,
            "recovered": False,
            "reset_budget_exhausted": True,
            "reset_count": session.auto_reset_count,
        }

    anchor, anchor_source = _select_session_recovery_anchor(session, last_iteration)
    session.auto_reset_count += 1
    event = {
        "iteration": iteration_num,
        "trigger": trigger,
        "reason": reason,
        "recovered": True,
        "reset_count": session.auto_reset_count,
        "anchor_source": anchor_source,
        "anchor_iteration": anchor.iteration if anchor else None,
        "preserved_best_iteration": (
            session.best_iteration.iteration if session.best_iteration else None
        ),
        "consecutive_failures_before_reset": consecutive_failures,
        "fallback_count_before_reset": fallback_count,
        "timestamp": datetime.now().isoformat(),
    }
    session.recovery_events.append(event)
    logger.warning(
        "builder_session_auto_reset session=%s reset=%d trigger=%s anchor=%s anchor_iter=%s",
        session.session_id,
        session.auto_reset_count,
        trigger,
        anchor_source,
        anchor.iteration if anchor else None,
    )
    safe_save_session_summary(session)
    return True, anchor, 0, 0, event
