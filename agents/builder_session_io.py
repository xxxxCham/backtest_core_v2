"""Module-ID: agents.builder_session_io

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
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.builder_ast_utils import _extract_required_indicators_signature
from agents.builder_diagnostics import (
    _builder_iteration_selection_key,
    compute_builder_telemetry_score,
)
from agents.builder_objective_parser import sanitize_objective_text
from agents.builder_state import (
    BuilderIteration,
    BuilderSession,
    _select_session_recovery_anchor,
    compute_session_generation_stats,
)
from backtest.result_store import get_builder_sessions_dir
from utils.observability import get_obs_logger

logger = get_obs_logger(__name__)

SANDBOX_ROOT = get_builder_sessions_dir()
_CODE_PROVENANCE_CACHE: dict[str, Any] | None = None

MAX_SESSION_AUTO_RESETS = int(os.getenv("BACKTEST_BUILDER_MAX_SESSION_RESETS", "2"))
BUILDER_MEMORY_MAX_SCAN = int(os.getenv("BACKTEST_BUILDER_MEMORY_MAX_SCAN", "250"))
BUILDER_MEMORY_MAX_ENTRIES = int(os.getenv("BACKTEST_BUILDER_MEMORY_MAX_ENTRIES", "12"))
BUILDER_MEMORY_PROPOSAL_MAX_CHARS = int(os.getenv("BACKTEST_BUILDER_MEMORY_PROPOSAL_MAX_CHARS", "18000"))
BUILDER_MEMORY_CODE_MAX_CHARS = int(os.getenv("BACKTEST_BUILDER_MEMORY_CODE_MAX_CHARS", "7000"))
BUILDER_MEMORY_MAX_OBJECTIVE_CHARS = int(os.getenv("BACKTEST_BUILDER_MEMORY_MAX_OBJECTIVE_CHARS", "180"))
BUILDER_MEMORY_MAX_HYPOTHESIS_CHARS = int(os.getenv("BACKTEST_BUILDER_MEMORY_MAX_HYPOTHESIS_CHARS", "180"))
BUILDER_MEMORY_MAX_LESSON_CHARS = int(os.getenv("BACKTEST_BUILDER_MEMORY_MAX_LESSON_CHARS", "160"))
BUILDER_MEMORY_MAX_PARAMS = int(os.getenv("BACKTEST_BUILDER_MEMORY_MAX_PARAMS", "5"))

_BUILDER_MEMORY_FAILURE_CATEGORIES = {
    "ruined",
    "no_trades",
    "overtrading",
    "wrong_direction",
    "high_drawdown",
}
_BUILDER_MEMORY_STOPWORDS = {
    "about",
    "after",
    "against",
    "avec",
    "builder",
    "cette",
    "dans",
    "des",
    "from",
    "pour",
    "strategy",
    "strategie",
    "sur",
    "that",
    "this",
    "using",
    "with",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value:
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
    return None


def _datetime_isoformat(value: Any) -> str:
    dt = _coerce_datetime(value)
    return dt.isoformat() if dt else ""


def _elapsed_seconds(start: Any, end: Any) -> float | None:
    start_dt = _coerce_datetime(start)
    end_dt = _coerce_datetime(end)
    if start_dt is None or end_dt is None:
        return None
    try:
        return max((end_dt - start_dt).total_seconds(), 0.0)
    except TypeError:
        # Handles naive/aware mixes from older restored sessions.
        start_naive = start_dt.replace(tzinfo=None)
        end_naive = end_dt.replace(tzinfo=None)
        return max((end_naive - start_naive).total_seconds(), 0.0)


def _git_output(*args: str) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _write_text_atomic(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Écrit un fichier texte via un fichier temporaire puis remplace la cible atomiquement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        temp_path.replace(path)
    except Exception:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _collect_code_provenance(*, refresh: bool = False) -> dict[str, Any]:
    global _CODE_PROVENANCE_CACHE
    if _CODE_PROVENANCE_CACHE is not None and not refresh:
        return dict(_CODE_PROVENANCE_CACHE)

    commit = _git_output("rev-parse", "HEAD")
    branch = _git_output("rev-parse", "--abbrev-ref", "HEAD")
    dirty_status = _git_output("status", "--porcelain", "--untracked-files=no")
    commit_time = _git_output("show", "-s", "--format=%cI", "HEAD") if commit else ""
    _CODE_PROVENANCE_CACHE = {
        "schema": "builder_code_provenance_v1",
        "available": bool(commit),
        "git_commit": commit,
        "git_branch": branch,
        "git_commit_time": commit_time,
        "git_dirty": bool(dirty_status),
        "captured_at": datetime.now().isoformat(),
    }
    return dict(_CODE_PROVENANCE_CACHE)


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


def _memory_safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _memory_safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clip_builder_memory_text(value: Any, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return f"{text[: max(0, max_chars - 1)].rstrip()}…"


def _tokenize_builder_memory_text(*texts: Any) -> set[str]:
    tokens: set[str] = set()
    for text in texts:
        raw = str(text or "").lower().replace("_", " ")
        for token in re.findall(r"[a-z0-9]+", raw):
            if len(token) < 3 or token in _BUILDER_MEMORY_STOPWORDS:
                continue
            tokens.add(token)
    return tokens


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / float(len(union))


def _parse_builder_memory_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _load_builder_memory_summary(summary_path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


def _builder_memory_best_row(summary: dict[str, Any]) -> dict[str, Any]:
    leaderboard = summary.get("leaderboard", [])
    if isinstance(leaderboard, list):
        for row in leaderboard:
            if isinstance(row, dict):
                return dict(row)
    iterations = summary.get("iterations", [])
    rows = [dict(row) for row in iterations if isinstance(row, dict)]
    if not rows:
        return {}
    rows.sort(
        key=lambda row: (
            _memory_safe_float(row.get("telemetry_score"), float("-inf")),
            _memory_safe_float(row.get("return_pct"), float("-inf")),
            _memory_safe_float(row.get("sharpe"), float("-inf")),
            _memory_safe_int(row.get("iteration"), 0),
        ),
        reverse=True,
    )
    return rows[0]


def _builder_memory_final_row(summary: dict[str, Any]) -> dict[str, Any]:
    iterations = summary.get("iterations", [])
    rows = [dict(row) for row in iterations if isinstance(row, dict)]
    if not rows:
        return {}
    rows.sort(key=lambda row: _memory_safe_int(row.get("iteration"), 0))
    return rows[-1]


def _builder_memory_strategy_path(session_dir: Path, iteration_num: int) -> Path | None:
    versioned = session_dir / f"strategy_v{int(iteration_num):03d}.py"
    if versioned.exists():
        return versioned
    legacy = session_dir / f"strategy_v{int(iteration_num)}.py"
    if legacy.exists():
        return legacy
    current = session_dir / "strategy.py"
    if current.exists():
        return current
    return None


def _builder_memory_indicators(summary: dict[str, Any], session_dir: Path, reference_row: dict[str, Any]) -> list[str]:
    row_indicators = reference_row.get("used_indicators")
    if isinstance(row_indicators, list):
        cleaned = [str(ind).strip().lower() for ind in row_indicators if str(ind).strip()]
        if cleaned:
            return cleaned
    iteration_num = _memory_safe_int(reference_row.get("iteration"), 0)
    strategy_path = _builder_memory_strategy_path(session_dir, iteration_num)
    if strategy_path is None:
        return []
    try:
        code = strategy_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return list(_extract_required_indicators_signature(code))


def _builder_memory_params(reference_row: dict[str, Any]) -> dict[str, Any]:
    params = reference_row.get("params_used")
    return dict(params) if isinstance(params, dict) else {}


def _format_builder_memory_params(params: dict[str, Any], *, limit: int = BUILDER_MEMORY_MAX_PARAMS) -> str:
    if not params:
        return ""
    parts: list[str] = []
    for key in sorted(params.keys())[: max(1, limit)]:
        value = params.get(key)
        if isinstance(value, float):
            rendered = f"{value:.4g}"
        else:
            rendered = str(value)
        parts.append(f"{key}={rendered}")
    return ", ".join(parts)


def _builder_memory_outcome(summary: dict[str, Any], best_row: dict[str, Any], final_row: dict[str, Any]) -> str:
    best_sharpe = _memory_safe_float(summary.get("best_sharpe"), _memory_safe_float(best_row.get("sharpe"), 0.0))
    best_return = _memory_safe_float(best_row.get("return_pct"), 0.0)
    best_profit_factor = _memory_safe_float(best_row.get("profit_factor"), 0.0)
    best_trades = _memory_safe_float(best_row.get("trades"), 0.0)
    best_dd = abs(_memory_safe_float(best_row.get("max_drawdown_pct"), 0.0))
    final_diag = str(final_row.get("diagnostic_category") or "").strip().lower()
    status = str(summary.get("status") or "").strip().lower()

    if (
        best_sharpe >= 1.0
        or (
            best_return > 0.0
            and best_profit_factor >= 1.05
            and best_trades >= 20.0
            and best_dd <= 35.0
        )
    ):
        return "success"
    if (
        status in {"failed", "max_iterations"}
        or final_diag in _BUILDER_MEMORY_FAILURE_CATEGORIES
        or best_return <= 0.0 and best_sharpe < 0.35
    ):
        return "failure"
    return "mixed"


def _builder_memory_relevance_score(
    *,
    current_objective: str,
    current_symbol: str,
    current_timeframe: str,
    current_universe_mode: str,
    current_strategy_type: str,
    summary: dict[str, Any],
    summary_path: Path,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    objective_tokens = _tokenize_builder_memory_text(sanitize_objective_text(current_objective))
    candidate_tokens = _tokenize_builder_memory_text(summary.get("objective"))
    objective_overlap = _jaccard_similarity(objective_tokens, candidate_tokens)
    if objective_overlap > 0.0:
        score += objective_overlap * 6.0
        reasons.append("objective_overlap")

    symbol = str(summary.get("symbol") or "").strip()
    if current_symbol and symbol and current_symbol == symbol:
        score += 2.0
        reasons.append("same_symbol")

    timeframe = str(summary.get("timeframe") or "").strip()
    if current_timeframe and timeframe and current_timeframe == timeframe:
        score += 1.5
        reasons.append("same_timeframe")

    universe_mode = str(summary.get("universe_mode") or "").strip()
    if current_universe_mode and universe_mode and current_universe_mode == universe_mode:
        score += 0.35
        reasons.append("same_universe")

    strategy_type = str(summary.get("universe_strategy_type") or "").strip()
    if current_strategy_type and strategy_type and current_strategy_type == strategy_type:
        score += 0.75
        reasons.append("same_strategy_type")

    start_time = _parse_builder_memory_datetime(summary.get("start_time"))
    if start_time is None:
        try:
            start_time = datetime.fromtimestamp(summary_path.stat().st_mtime)
        except OSError:
            start_time = None
    if start_time is not None:
        age_days = max((datetime.now(start_time.tzinfo) - start_time).total_seconds() / 86400.0, 0.0)
        score += max(0.0, 1.0 - min(age_days, 180.0) / 180.0) * 0.4

    return score, reasons


def _build_builder_memory_lesson(
    *,
    outcome: str,
    hypothesis: str,
    final_diag: str,
    runtime_error: str,
    best_sharpe: float,
    best_return_pct: float,
    indicators: list[str],
) -> str:
    if outcome == "success":
        prefix = "Positive reference"
        metric_hint = f"best sharpe {best_sharpe:.2f}, return {best_return_pct:.1f}%"
        indicator_hint = f"indicators {', '.join(indicators[:4])}" if indicators else "indicator mix unavailable"
        core = hypothesis or metric_hint
        return _clip_builder_memory_text(f"{prefix}: {core}. {indicator_hint}. {metric_hint}.", BUILDER_MEMORY_MAX_LESSON_CHARS)
    if outcome == "failure":
        reason = final_diag or runtime_error or "weak edge"
        indicator_hint = f"with {', '.join(indicators[:4])}" if indicators else "with unknown indicator mix"
        return _clip_builder_memory_text(
            f"Failure reference: avoid repeating this pattern {indicator_hint} without structural change ({reason}).",
            BUILDER_MEMORY_MAX_LESSON_CHARS,
        )
    metric_hint = f"best sharpe {best_sharpe:.2f}, return {best_return_pct:.1f}%"
    return _clip_builder_memory_text(
        f"Mixed reference: some signal existed, but the edge stayed inconclusive ({metric_hint}).",
        BUILDER_MEMORY_MAX_LESSON_CHARS,
    )


def _build_builder_memory_entry(
    *,
    summary_path: Path,
    summary: dict[str, Any],
    current_objective: str,
    current_symbol: str,
    current_timeframe: str,
    current_universe_mode: str,
    current_strategy_type: str,
) -> dict[str, Any] | None:
    score, reasons = _builder_memory_relevance_score(
        current_objective=current_objective,
        current_symbol=current_symbol,
        current_timeframe=current_timeframe,
        current_universe_mode=current_universe_mode,
        current_strategy_type=current_strategy_type,
        summary=summary,
        summary_path=summary_path,
    )
    if score <= 0.0 and not reasons:
        return None

    best_row = _builder_memory_best_row(summary)
    final_row = _builder_memory_final_row(summary)
    reference_row = best_row or final_row
    if not reference_row:
        return None

    session_dir = summary_path.parent
    indicators = _builder_memory_indicators(summary, session_dir, reference_row)
    params = _builder_memory_params(reference_row)
    outcome = _builder_memory_outcome(summary, best_row, final_row)
    hypothesis = _clip_builder_memory_text(
        reference_row.get("hypothesis") or summary.get("objective") or "",
        BUILDER_MEMORY_MAX_HYPOTHESIS_CHARS,
    )
    objective = _clip_builder_memory_text(summary.get("objective"), BUILDER_MEMORY_MAX_OBJECTIVE_CHARS)
    best_sharpe = _memory_safe_float(best_row.get("sharpe"), _memory_safe_float(summary.get("best_sharpe"), 0.0))
    best_return_pct = _memory_safe_float(best_row.get("return_pct"), 0.0)
    best_drawdown_pct = _memory_safe_float(best_row.get("max_drawdown_pct"), 0.0)
    trades = _memory_safe_int(best_row.get("trades"), 0)
    profit_factor = _memory_safe_float(best_row.get("profit_factor"), 0.0)
    final_diag = str(final_row.get("diagnostic_category") or "").strip().lower()
    runtime_error = str(summary.get("last_runtime_error") or final_row.get("error") or "").strip()
    params_brief = _format_builder_memory_params(params)
    lesson = _build_builder_memory_lesson(
        outcome=outcome,
        hypothesis=hypothesis,
        final_diag=final_diag,
        runtime_error=runtime_error,
        best_sharpe=best_sharpe,
        best_return_pct=best_return_pct,
        indicators=indicators,
    )

    relation = ",".join(reasons) if reasons else "broad_match"
    indicator_brief = ", ".join(indicators[:6]) if indicators else "unknown"
    line = (
        f"- [{outcome.upper()} | {relation} | score={score:.2f}] "
        f"{str(summary.get('symbol') or '?')} {str(summary.get('timeframe') or '?')} "
        f"| best_iter={_memory_safe_int(reference_row.get('iteration'), 0)} "
        f"| sharpe={best_sharpe:.3f} ret={best_return_pct:.2f}% dd={best_drawdown_pct:.2f}% "
        f"pf={profit_factor:.2f} trades={trades} "
        f"| indicators=[{indicator_brief}] "
        f"| objective={objective} "
        f"| hypothesis={hypothesis} "
        f"| lesson={lesson}"
    )
    if params_brief:
        line += f" | params={params_brief}"

    return {
        "session_id": str(summary.get("session_id") or session_dir.name),
        "objective": objective,
        "symbol": str(summary.get("symbol") or ""),
        "timeframe": str(summary.get("timeframe") or ""),
        "status": str(summary.get("status") or ""),
        "outcome": outcome,
        "relation": reasons,
        "relevance_score": round(score, 4),
        "reference_iteration": _memory_safe_int(reference_row.get("iteration"), 0),
        "hypothesis": hypothesis,
        "indicators": indicators,
        "best_sharpe": best_sharpe,
        "best_return_pct": best_return_pct,
        "max_drawdown_pct": best_drawdown_pct,
        "profit_factor": profit_factor,
        "trades": trades,
        "diagnostic_category": final_diag,
        "params": params,
        "lesson": lesson,
        "summary_line": _clip_builder_memory_text(line, BUILDER_MEMORY_PROPOSAL_MAX_CHARS),
    }


def load_builder_cross_session_memory(
    *,
    objective: str,
    symbol: str,
    timeframe: str,
    session_id: str = "",
    universe_mode: str = "",
    universe_strategy_type: str = "",
    base_dir: Path | None = None,
    max_scan: int = BUILDER_MEMORY_MAX_SCAN,
    max_entries: int = BUILDER_MEMORY_MAX_ENTRIES,
) -> list[dict[str, Any]]:
    root = Path(base_dir or SANDBOX_ROOT)
    if not root.exists():
        return []

    summary_paths = sorted(
        root.glob("*/session_summary.json"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0.0,
        reverse=True,
    )[: max(1, max_scan)]

    candidates: list[dict[str, Any]] = []
    current_session_id = str(session_id or "").strip()
    for summary_path in summary_paths:
        summary = _load_builder_memory_summary(summary_path)
        candidate_session_id = str(summary.get("session_id") or summary_path.parent.name or "").strip()
        if current_session_id and candidate_session_id == current_session_id:
            continue
        entry = _build_builder_memory_entry(
            summary_path=summary_path,
            summary=summary,
            current_objective=objective,
            current_symbol=symbol,
            current_timeframe=timeframe,
            current_universe_mode=universe_mode,
            current_strategy_type=universe_strategy_type,
        )
        if entry is not None:
            candidates.append(entry)

    candidates.sort(
        key=lambda entry: (
            float(entry.get("relevance_score", 0.0) or 0.0),
            1.0 if str(entry.get("outcome") or "") == "success" else 0.0,
            float(entry.get("best_return_pct", 0.0) or 0.0),
            float(entry.get("best_sharpe", 0.0) or 0.0),
        ),
        reverse=True,
    )

    if not candidates:
        return []

    success_limit = max(1, min(max_entries, max_entries // 2 + max_entries % 2))
    failure_limit = max(1, max_entries // 3)
    mixed_limit = max(0, max_entries - success_limit - failure_limit)

    selected: list[dict[str, Any]] = []
    seen_session_ids: set[str] = set()

    def _take(bucket: str, limit: int) -> None:
        if limit <= 0:
            return
        for entry in candidates:
            if str(entry.get("outcome") or "") != bucket:
                continue
            session_marker = str(entry.get("session_id") or "")
            if session_marker in seen_session_ids:
                continue
            selected.append(entry)
            seen_session_ids.add(session_marker)
            if len([item for item in selected if str(item.get("outcome") or "") == bucket]) >= limit:
                return

    _take("success", success_limit)
    _take("failure", failure_limit)
    _take("mixed", mixed_limit)

    for entry in candidates:
        if len(selected) >= max_entries:
            break
        session_marker = str(entry.get("session_id") or "")
        if session_marker in seen_session_ids:
            continue
        selected.append(entry)
        seen_session_ids.add(session_marker)

    selected.sort(
        key=lambda entry: (
            float(entry.get("relevance_score", 0.0) or 0.0),
            float(entry.get("best_return_pct", 0.0) or 0.0),
            float(entry.get("best_sharpe", 0.0) or 0.0),
        ),
        reverse=True,
    )
    return selected[: max(1, max_entries)]


def format_builder_cross_session_memory(
    entries: list[dict[str, Any]] | None,
    *,
    max_chars: int,
) -> str:
    if not entries or max_chars <= 0:
        return ""
    lines: list[str] = []
    remaining = max_chars
    for entry in entries:
        line = str(entry.get("summary_line") or "").strip()
        if not line:
            continue
        if len(line) + 1 > remaining:
            if not lines:
                line = _clip_builder_memory_text(line, remaining)
            else:
                break
        if not line:
            break
        lines.append(line)
        remaining -= len(line) + 1
        if remaining <= 0:
            break
    return "\n".join(lines)


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
    proposal_feedback: dict[str, Any] | None = None,
    code_feedback: dict[str, Any] | None = None,
    precheck_feedback: dict[str, Any] | None = None,
    backtest_feedback: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Persiste un checkpoint léger pour diagnostiquer un crash intra-itération."""
    timestamp = datetime.now().isoformat()
    checkpoint_path = session.session_dir / f"iteration_{int(iteration_num):03d}_runtime_checkpoint.json"
    latest_path = session.session_dir / "runtime_checkpoint.json"

    payload: dict[str, Any] = {}
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
    event_payload: dict[str, Any] = {
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
    iteration_rows: list[dict[str, Any]] = []
    last_runtime_feedback: dict[str, Any] = {
        "last_runtime_error": None,
        "last_runtime_error_iteration": None,
        "last_runtime_traceback_tail": None,
    }
    for it in session.iterations:
        metrics = (
            it.backtest_result.metrics if it.backtest_result and isinstance(it.backtest_result.metrics, dict) else {}
        )
        phase_feedback = (
            it.phase_feedback.to_dict()
            if hasattr(it.phase_feedback, "to_dict")
            else (it.phase_feedback if isinstance(it.phase_feedback, dict) else {})
        )
        backtest_feedback = phase_feedback.get("backtest", {}) if isinstance(phase_feedback, dict) else {}
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
            "timestamp": _datetime_isoformat(it.timestamp),
            "session_elapsed_seconds": _elapsed_seconds(session.start_time, it.timestamp),
            "hypothesis": it.hypothesis,
            "change_type": it.change_type,
            "diagnostic_category": it.diagnostic_category,
            "used_indicators": list(it.used_indicators or []),
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
            "score_card": (it.diagnostic_detail.get("score_card") if it.diagnostic_detail else None),
            "is_fallback": it.is_fallback,
            "phase_feedback": phase_feedback or None,
        }
        iteration_rows.append(row)

        runtime_error = str(backtest_feedback.get("runtime_error") or "").strip()
        runtime_traceback_tail = str(
            backtest_feedback.get("runtime_traceback_tail") or "",
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

    generation_stats = compute_session_generation_stats(session)
    end_time = datetime.now(session.start_time.tzinfo) if getattr(session.start_time, "tzinfo", None) else datetime.now()
    session_duration_seconds = max((end_time - session.start_time).total_seconds(), 0.0)
    code_provenance = _collect_code_provenance()

    summary = {
        "summary_schema_version": 2,
        "session_id": session.session_id,
        "objective": session.objective,
        "model_name": session.model_name,
        "resume_parent_session_id": session.resume_parent_session_id,
        "resume_mode": session.resume_mode,
        "resume_from_iteration": session.resume_from_iteration,
        "resume_extra_iterations": session.resume_extra_iterations,
        "resume_original_status": session.resume_original_status,
        "resume_source_summary_path": session.resume_source_summary_path,
        "resume_original_model_name": session.resume_original_model_name,
        "resume_requested_model_name": session.resume_requested_model_name,
        "code_provenance": code_provenance,
        "git_commit": code_provenance.get("git_commit", ""),
        "git_branch": code_provenance.get("git_branch", ""),
        "git_dirty": code_provenance.get("git_dirty", False),
        "status": session.status,
        "generation_stats": generation_stats,
        "best_sharpe": session.best_sharpe,
        "best_telemetry_score": session.best_score,
        "best_score": session.best_score,
        "target_sharpe": session.target_sharpe,
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
        "end_time": end_time.isoformat(),
        "session_duration_seconds": session_duration_seconds,
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
        "last_runtime_error": last_runtime_feedback.get("last_runtime_error"),
        "last_runtime_error_iteration": last_runtime_feedback.get("last_runtime_error_iteration"),
        "last_runtime_traceback_tail": last_runtime_feedback.get("last_runtime_traceback_tail"),
        "cross_session_memory": list(session.cross_session_memory or []),
        "iterations": iteration_rows,
        "leaderboard": leaderboard,
    }

    summary_path = session.session_dir / "session_summary.json"
    _write_text_atomic(
        summary_path,
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
                ),
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
    last_iteration: BuilderIteration | None,
    consecutive_failures: int,
    fallback_count: int,
    save_callback: Any | None = None,
) -> tuple[bool, BuilderIteration | None, int, int, dict[str, Any]]:
    """Réinitialise proprement la session autour du meilleur ancrage disponible."""
    if session.auto_reset_count >= MAX_SESSION_AUTO_RESETS:
        return (
            False,
            last_iteration,
            consecutive_failures,
            fallback_count,
            {
                "trigger": trigger,
                "reason": reason,
                "recovered": False,
                "reset_budget_exhausted": True,
                "reset_count": session.auto_reset_count,
            },
        )

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
        "preserved_best_iteration": (session.best_iteration.iteration if session.best_iteration else None),
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
    if callable(save_callback):
        save_callback(session)
    else:
        safe_save_session_summary(session)
    return True, anchor, 0, 0, event
