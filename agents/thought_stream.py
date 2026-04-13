"""
Module-ID: agents.thought_stream

Purpose: Flux live canonique du Strategy Builder.
         Rend un fichier Markdown de session courante pour le terminal dedie.

Role in pipeline: observabilite

Usage (terminal PowerShell) :
    Get-Content "$env:BACKTEST_ARTIFACTS_DIR\\_builder_sessions\\_live_thoughts.md" -Wait -Tail 50

Skip-if: Vous n'utilisez pas le Strategy Builder.
"""

from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from backtest.result_store import get_builder_sessions_dir

STREAM_FILE = get_builder_sessions_dir() / "_live_thoughts.md"
STREAM_ARCHIVE_DIR = get_builder_sessions_dir() / "_live_thoughts_archives"

# Nombre de caractères accumulés avant d'écrire une ligne dans le flux terminal.
# Réduit le bruit (1 ligne/80 chars au lieu de 1 ligne/token) tout en restant live.
_STREAM_BATCH_CHARS: int = 80

_LIVE_STREAM_LABELS = {
    "proposal": ("IDEA", "Proposition"),
    "retry_proposal": ("RETRY", "Retry proposition"),
    "code": ("CODE", "Generation de code"),
    "retry_code": ("RETRY", "Retry code"),
    "analysis": ("ANALYSE", "Analyse"),
    "objective_gen": ("OBJECTIF", "Generation d'objectif"),
    "save_and_load": ("LOAD", "Sauvegarde / chargement"),
    "precheck": ("CHECK", "Precheck signaux"),
    "backtest": ("BACKTEST", "Backtest"),
    "runtime_fix": ("FIX", "Reparation runtime"),
    "runtime_fix_fallback_backtest": ("FALLBACK", "Backtest fallback"),
}
_LIVE_STREAM_STATUS_ICONS = {
    "start": "[...]",
    "ok": "[OK]",
    "done": "[OK]",
    "selected": "[OK]",
    "blocked": "[BLOCKED]",
    "warning": "[WARN]",
    "error": "[ERROR]",
    "success": "[OK]",
    "failed": "[ERROR]",
    "running": "[RUN]",
}


@dataclass(frozen=True)
class BuilderLiveEvent:
    event: str
    timestamp: str
    session_id: str = ""
    iteration: int = 0
    branch_label: str = ""
    selected_branch_label: str = ""
    phase: str = ""
    status: str = ""
    message: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": str(self.event or ""),
            "timestamp": str(self.timestamp or ""),
            "session_id": str(self.session_id or ""),
            "iteration": int(self.iteration or 0),
            "branch_label": str(self.branch_label or ""),
            "selected_branch_label": str(self.selected_branch_label or ""),
            "phase": str(self.phase or ""),
            "status": str(self.status or ""),
            "message": str(self.message or ""),
            "payload": dict(self.payload or {}),
        }


class ThoughtStream:
    """Rend le stream Builder courant a partir d'un contrat d'evenements canonique."""

    def __init__(
        self,
        session_id: str,
        objective: str,
        model: str,
        *,
        path: Optional[Path] = None,
        archive_dir: Optional[Path] = None,
    ):
        self.session_id = str(session_id or "")
        self.objective = str(objective or "")
        self.model = str(model or "")
        self.path = path or STREAM_FILE
        self.archive_dir = archive_dir or STREAM_ARCHIVE_DIR
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._session_started = False
        self._archived = False
        self._stream_closed = False
        self._stream_phase = ""
        self._stream_buffer = ""  # Buffer pour regrouper les tokens avant écriture

    def consume(self, event: BuilderLiveEvent | Mapping[str, Any]) -> None:
        payload = event.to_dict() if isinstance(event, BuilderLiveEvent) else dict(event or {})
        event_name = str(payload.get("event", "") or "")
        if not event_name:
            return

        # Flush le buffer stream avant tout événement structurel pour garantir
        # que les tokens LLM apparaissent dans le bon ordre chronologique.
        with self._lock:
            self._flush_stream_buffer_no_lock()

        if event_name == "session_start":
            self._start_session(payload)

        rendered = self._render_event(payload)
        if rendered:
            self._append(rendered)

        if event_name == "session_done":
            with self._lock:
                self._stream_closed = True
                self._stream_phase = ""
                self._stream_buffer = ""
            self._archive_current_session()

    # ------------------------------------------------------------------ #
    # Backward-compatible helpers
    # ------------------------------------------------------------------ #

    def append(self, text: str) -> None:
        self._append(str(text or ""))

    def warning(self, message: str) -> None:
        self.consume(
            BuilderLiveEvent(
                event="warning",
                timestamp=_now_iso(),
                session_id=self.session_id,
                message=str(message or ""),
            )
        )

    def stage_update(
        self,
        phase: str,
        *,
        status: str = "start",
        detail: str = "",
        branch_label: str = "",
    ) -> None:
        event_name = "phase_start" if str(status or "start") == "start" else "phase_done"
        self.consume(
            BuilderLiveEvent(
                event=event_name,
                timestamp=_now_iso(),
                session_id=self.session_id,
                branch_label=str(branch_label or ""),
                phase=str(phase or ""),
                status=str(status or ""),
                message=str(detail or ""),
                payload={"detail": str(detail or "")},
            )
        )

    def session_end(
        self,
        status: str,
        best_sharpe: float,
        total_iters: int,
    ) -> None:
        self.consume(
            BuilderLiveEvent(
                event="session_done",
                timestamp=_now_iso(),
                session_id=self.session_id,
                status=str(status or ""),
                message=f"Session terminee ({status})",
                payload={
                    "best_sharpe": float(best_sharpe or 0.0),
                    "total_iterations": int(total_iters or 0),
                },
            )
        )

    def stream_chunk(self, phase: str, chunk: str) -> None:
        """Accumule les tokens LLM et écrit une ligne tous les _STREAM_BATCH_CHARS chars.

        Préférer un flux groupé (80 chars/ligne) plutôt qu'une écriture fichier
        par token pour réduire le bruit et rendre le terminal lisible en live.
        """
        text = str(chunk or "")
        if not text:
            return

        phase_name = str(phase or "").strip().lower()

        with self._lock:
            if not self._session_started or self._archived or self._stream_closed:
                return
            # Changement de phase : flush le buffer précédent + en-tête nouvelle phase
            if phase_name and phase_name != self._stream_phase:
                self._flush_stream_buffer_no_lock()
                self._stream_phase = phase_name
                phase_icon, phase_label = _stream_phase_label(phase_name)
                self._append(f"[STREAM] {phase_icon} {phase_label} — démarrage du flux\n")
            elif not self._stream_phase:
                self._stream_phase = phase_name

            # Accumulation dans le buffer
            self._stream_buffer += text

            # Écriture quand le buffer atteint le seuil
            if len(self._stream_buffer) >= _STREAM_BATCH_CHARS:
                self._flush_stream_buffer_no_lock()

    def flush_stream(self) -> None:
        """Flush public : appelé après la fin d'un appel LLM pour écrire le buffer résiduel."""
        with self._lock:
            self._flush_stream_buffer_no_lock()

    def accepts_streaming(self) -> bool:
        with self._lock:
            return bool(self._session_started and not self._archived and not self._stream_closed)

    # ------------------------------------------------------------------ #
    # Session lifecycle
    # ------------------------------------------------------------------ #

    def _start_session(self, event: Mapping[str, Any]) -> None:
        with self._lock:
            self._session_started = True
            self._archived = False
            self._stream_closed = False
            self._stream_phase = ""
            self._stream_buffer = ""
            self._overwrite(self._render_header(event))

    def _flush_stream_buffer_no_lock(self) -> None:
        """Flush le buffer stream vers le fichier. A appeler avec self._lock déjà tenu."""
        buf = self._stream_buffer.strip()
        self._stream_buffer = ""
        if not buf:
            return
        phase_icon, phase_label = _stream_phase_label(self._stream_phase)
        preview = _trunc(buf, max_len=200)
        self._append(f"[STREAM] {phase_icon} {phase_label} - {preview}\n")

    def _archive_current_session(self) -> None:
        with self._lock:
            if self._archived or not self.path.exists():
                return
            archive_target = self.archive_dir / f"{self.session_id or 'builder_session'}.md"
            shutil.copyfile(self.path, archive_target)
            self._archived = True

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

    def _render_header(self, event: Mapping[str, Any]) -> str:
        payload = dict(event.get("payload") or {})
        started_at = _format_datetime(event.get("timestamp"))
        symbol = str(payload.get("symbol", "") or "")
        timeframe = str(payload.get("timeframe", "") or "")
        market = f"{symbol} {timeframe}".strip()
        market_line = f"  MARCHE   : {market}\n" if market else ""
        return (
            f"{'=' * 68}\n"
            f"  STRATEGY BUILDER - Flux live canonique\n"
            f"{'-' * 68}\n"
            f"  OBJECTIF : {self.objective}\n"
            f"  MODELE   : {self.model}\n"
            f"  SESSION  : {self.session_id}\n"
            f"{market_line}"
            f"  DEBUT    : {started_at}\n"
            f"{'=' * 68}\n\n"
        )

    def _render_event(self, event: Mapping[str, Any]) -> str:
        event_name = str(event.get("event", "") or "")
        payload = dict(event.get("payload") or {})
        branch_label = str(
            event.get("selected_branch_label")
            or event.get("branch_label")
            or payload.get("selected_branch_label")
            or payload.get("branch_label")
            or ""
        )
        message = str(event.get("message", "") or "").strip()
        phase = str(event.get("phase", "") or "")
        iteration = int(event.get("iteration", 0) or 0)
        status = str(event.get("status", "") or "")

        if event_name == "session_start":
            return ""
        if event_name == "iteration_start":
            total = int(payload.get("max_iterations", 0) or 0)
            return (
                f"\n{'-' * 68}\n"
                f"  ITERATION {iteration}/{total or '?'}\n"
                f"{'-' * 68}\n"
            )
        if event_name == "proposal_candidate":
            proposal = dict(payload.get("proposal") or {})
            return self._render_proposal_block(
                title=f"CANDIDATE {branch_label or 'main'}",
                proposal=proposal,
                branch_label=branch_label,
                footer=message,
            )
        if event_name == "proposal_selected":
            proposal = dict(payload.get("proposal") or {})
            return self._render_proposal_block(
                title=f"BRANCHE RETENUE {branch_label or 'main'}",
                proposal=proposal,
                branch_label=branch_label,
                footer=message,
            )
        if event_name in {"phase_start", "phase_done"}:
            icon = _LIVE_STREAM_STATUS_ICONS.get(status or ("start" if event_name == "phase_start" else "done"), "[INFO]")
            phase_icon, phase_label = _stream_phase_label(phase)
            detail = str(payload.get("detail", "") or "").strip()
            suffix = _branch_suffix(branch_label)
            line = f"{icon} {phase_icon} {phase_label}{suffix}"
            if detail:
                line += f" - {_trunc(detail, max_len=220)}"
            elif message:
                line += f" - {_trunc(message, max_len=220)}"
            line += "\n"
            if event_name == "phase_done" and phase == "backtest":
                sharpe = payload.get("sharpe")
                ret_pct = payload.get("total_return_pct")
                try:
                    line += (
                        f"    RESULTATS : Sharpe {float(sharpe):.3f} | "
                        f"Return {float(ret_pct):+.2f}%\n"
                    )
                except Exception:
                    pass
            return line
        if event_name == "diagnostic":
            diagnostic = dict(payload.get("diagnostic") or {})
            category = str(diagnostic.get("category", "") or "")
            severity = str(diagnostic.get("severity", "") or "")
            change_type = str(diagnostic.get("change_type", "") or "")
            summary = str(diagnostic.get("summary", message) or message).strip()
            line = f"[DIAG] {category or 'diagnostic'}"
            if severity:
                line += f" | {severity}"
            if change_type:
                line += f" | {change_type}"
            if summary:
                line += f" - {_trunc(summary, max_len=240)}"
            return line + "\n"
        if event_name == "analysis":
            decision = str(payload.get("decision", "") or "")
            change_type = str(payload.get("change_type", "") or "")
            line = "[ANALYSE]"
            if decision:
                line += f" decision={decision}"
            if change_type:
                line += f" | change_type={change_type}"
            if message:
                line += f" - {_trunc(message, max_len=260)}"
            return line + "\n"
        if event_name == "warning":
            return f"[WARN] {_trunc(message or str(payload.get('detail', '') or ''), max_len=260)}\n"
        if event_name == "iteration_done":
            decision = str(payload.get("decision", "") or "")
            best = payload.get("best_sharpe")
            prefix = "[ITER]"
            if payload.get("new_best"):
                prefix = "[ITER][BEST]"
            line = f"{prefix} Iteration {iteration} terminee"
            if decision:
                line += f" | decision={decision}"
            try:
                line += f" | best_sharpe={float(best):.3f}"
            except Exception:
                pass
            return line + "\n"
        if event_name == "iteration_error":
            error_text = message or str(payload.get("error", "") or "")
            return f"[ERROR] Iteration {iteration} - {_trunc(error_text, max_len=260)}\n"
        if event_name == "session_done":
            total_iterations = int(payload.get("total_iterations", 0) or 0)
            best_sharpe = payload.get("best_sharpe")
            ended_at = _format_datetime(event.get("timestamp"))
            line = (
                f"\n{'=' * 68}\n"
                f"  SESSION TERMINEE - {status or 'n/a'}\n"
                f"  ITERATIONS : {total_iterations}\n"
            )
            try:
                line += f"  BEST SHARPE: {float(best_sharpe):.3f}\n"
            except Exception:
                pass
            line += f"  FIN       : {ended_at}\n{'=' * 68}\n"
            return line
        if message:
            return f"[INFO] {_trunc(message, max_len=260)}\n"
        return ""

    def _render_proposal_block(
        self,
        *,
        title: str,
        proposal: Mapping[str, Any],
        branch_label: str,
        footer: str = "",
    ) -> str:
        hypothesis = str(proposal.get("hypothesis", "") or "Hypothese non renseignee")
        indicators = proposal.get("used_indicators", [])
        used_indicators = ", ".join(str(item) for item in indicators if str(item).strip()) or "-"
        change_type = str(proposal.get("change_type", "") or "")
        entry_long = _trunc(proposal.get("entry_long_logic", ""), max_len=160)
        entry_short = _trunc(proposal.get("entry_short_logic", ""), max_len=160)
        risk = _trunc(proposal.get("risk_management", ""), max_len=160)
        params = proposal.get("default_params")
        params_text = ""
        if isinstance(params, dict) and params:
            params_text = ", ".join(f"{key}={value}" for key, value in params.items())
        block = [
            f"[PROPOSAL] {title}{_branch_suffix(branch_label, include_main=True)}",
            f"    Hypothese   : {hypothesis}",
            f"    Indicateurs : {used_indicators}",
        ]
        if change_type:
            block.append(f"    Change type : {change_type}")
        if entry_long and entry_long != "-":
            block.append(f"    Long        : {entry_long}")
        if entry_short and entry_short != "-":
            block.append(f"    Short       : {entry_short}")
        if risk and risk != "-":
            block.append(f"    Risque      : {risk}")
        if params_text:
            block.append(f"    Params      : {params_text}")
        if footer:
            block.append(f"    Note        : {_trunc(footer, max_len=220)}")
        return "\n".join(block) + "\n"

    # ------------------------------------------------------------------ #
    # I/O helpers
    # ------------------------------------------------------------------ #

    def _overwrite(self, text: str) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()

    def _append(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()


def _trunc(text: Any, max_len: int = 140) -> str:
    cleaned = str(text or "").replace("\n", " ").strip()
    if not cleaned:
        return "-"
    return cleaned[:max_len] + "..." if len(cleaned) > max_len else cleaned


def _stream_phase_label(phase: str) -> tuple[str, str]:
    normalized = str(phase or "").strip().lower()
    return _LIVE_STREAM_LABELS.get(normalized, ("LIVE", normalized or "Activite Builder"))


def _branch_suffix(branch_label: str, *, include_main: bool = False) -> str:
    cleaned = str(branch_label or "").strip()
    if not cleaned:
        return ""
    if cleaned == "main" and not include_main:
        return ""
    return f" | branche `{cleaned}`"


def _format_datetime(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return text


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"
