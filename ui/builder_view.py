"""
Module-ID: ui.builder_view

Purpose: Interface Streamlit pour le Strategy Builder — création de stratégies par IA.

Role in pipeline: UI / interaction utilisateur

Key components: render_builder_view, render_iteration_card, render_session_summary

Inputs: SidebarState (builder_objective, builder_model_single_llm, etc.), DataFrame OHLCV

Outputs: Affichage interactif des itérations et résultats du builder

Dependencies: agents.strategy_builder, ui.helpers, ui.context

Conventions: Streamlit components, pas de logique de trading

Read-if: Modification de l'interface Strategy Builder

Skip-if: Logique backend du builder (voir agents/strategy_builder.py)
"""

from __future__ import annotations

import copy
import csv
import html
import inspect
import io
import json
import logging
import math
import os
import random
import re
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from operator import itemgetter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
import streamlit as st

import agents.ollama_manager as ollama_manager_module
from agents.llm_config import (
    normalize_llm_inference_settings,
    normalize_llm_model_inference_profiles,
)
from agents.ollama_runtime import (
    is_ollama_cloud_model,
    resolve_ollama_request_context,
    strip_ollama_cloud_model_alias,
)
from config.market_selection import (
    evaluate_market_dataset,
    filter_market_universe,
    infer_strategy_type,
    normalize_universe_mode,
)

try:
    import psutil

    _HAS_PSUTIL = True
except Exception:
    psutil = None
    _HAS_PSUTIL = False

# ── Logging de diagnostic (TEMPORAIRE) ──
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # Force INFO level
# Ajouter un handler console si absent
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setLevel(logging.INFO)
    _formatter = logging.Formatter('%(asctime)s | %(levelname)-7s | %(name)s | %(message)s', datefmt='%H:%M:%S')
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)

from agents.builder_state import compute_session_generation_stats
from agents.llm_client import create_llm_client
from agents.llm_router import LLMTopologyConfig
from agents.model_config import is_cloud_only_model
from agents.strategy_builder import (
    MIN_BUILDER_BARS,
    SANDBOX_ROOT,
    StrategyBuilder,
    generate_llm_objective,
    generate_random_objective,
    recommend_market_context,
    sanitize_objective_text,
    validate_builder_dataset_exploitability,
)
from agents.thought_stream import STREAM_FILE, reset_live_stream
from ui.builder_runtime import (
    build_builder_base_llm_config,
    format_ollama_keep_alive,
)
from ui.helpers import _maybe_auto_save_run, safe_load_data, show_status

ensure_ollama_running = ollama_manager_module.ensure_ollama_running
probe_model_runtime_acceptance = ollama_manager_module.probe_model_runtime_acceptance

from ui.state import (
    BUILDER_EXECUTION_MODE_MONO,
    BUILDER_UNIVERSE_MODE_CANONICAL,
    clear_execution_state,
    resolve_builder_flow_analysis_preferences,
    resolve_builder_runtime_preferences,
)

_AUTONOMOUS_SUPERVISOR_STATE_FILE = SANDBOX_ROOT / "_autonomous_supervisor_state.json"
_AUTONOMOUS_RUNTIME_STATE_FILE = SANDBOX_ROOT / "_autonomous_runtime_state.json"
_BUILDER_SESSION_SUMMARY_PATCH_LOCK = threading.Lock()
_AUTONOMOUS_SUPERVISOR_VERSION = "1.0"
_AUTONOMOUS_RUNTIME_VERSION = "1.0"
_AUTONOMOUS_MAX_PERSISTED_HISTORY = 150
# Cles redondantes avec session_summary.json — non persistees au niveau history.
# universe_meta seul pesait ~80% du supervisor_state (36 KB/entry).
_AUTONOMOUS_HISTORY_PURGED_KEYS: frozenset[str] = frozenset(
    {
        "universe_meta",
        "instrumentation_summary",
        "multi_llm_role_outputs",
        "multi_llm_shared_memory",
        "multi_llm_role_override_pools",
    }
)
_AUTONOMOUS_STATE_SAVE_RETRIES = 3
_AUTONOMOUS_STATE_SAVE_RETRY_DELAY_SEC = 0.05
_AUTONOMOUS_SUPERVISOR_STATE_LOCK = threading.Lock()
_AUTONOMOUS_RUNTIME_STATE_LOCK = threading.Lock()
_AUTONOMOUS_SESSION_FAILURE_RESET_THRESHOLD = 4
_AUTONOMOUS_MAX_SOFT_RESETS = 3
_AUTONOMOUS_SOFT_RESET_WINDOW_SECONDS = 2 * 60 * 60
_AUTONOMOUS_HARDENED_COOLDOWN_MULTIPLIER = 8
_AUTONOMOUS_SOURCE_MODES = ("llm", "fallback")

# Champs métriques communs à toute entrée d'historique autonome.
# Utilisé comme base par les 3 chemins (succès, erreur sans session, crash).
_HISTORY_ENTRY_METRIC_DEFAULTS: Dict[str, Any] = {
    "best_sharpe": None, "best_telemetry_score": None, "best_score": None,
    "best_return": None, "best_return_iteration": None, "best_max_dd": None,
    "best_pf": None, "best_trades": None, "best_return_sharpe": None,
    "best_total_pnl": None,
    "final_return": None, "final_iteration": None, "final_max_dd": None,
    "final_pf": None, "final_trades": None, "final_sharpe": None,
    "final_total_pnl": None,
}

_STREAM_CODE_LINE_PREFIXES = (
    "from ",
    "import ",
    "class ",
    "def ",
    "@",
    "if ",
    "elif ",
    "else:",
    "for ",
    "while ",
    "try:",
    "except ",
    "finally:",
    "with ",
    "return ",
    "raise ",
    "pass",
    "break",
    "continue",
    "signals",
    "long_",
    "short_",
    "entry_",
    "exit_",
    "sl_",
    "tp_",
)


BUILDER_VIEW_CSS = """
<style>
.bc-builder-summary-line {
    margin: 0.1rem 0 0.85rem 0;
    padding-bottom: 0.55rem;
    border-bottom: 1px solid rgba(148, 163, 184, 0.18);
    color: #b8cbe2;
    font-size: 0.93rem;
    line-height: 1.45;
}
.bc-builder-badge-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin: 0.15rem 0 0.7rem 0;
}
.bc-builder-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.36rem 0.58rem;
    border-radius: 999px;
    border: 1px solid rgba(148, 163, 184, 0.18);
    background: rgba(15, 23, 42, 0.88);
    color: #dbeafe;
    font-size: 0.8rem;
}
.bc-builder-runtime-note {
    margin: 0.15rem 0 0.8rem 0;
    padding: 0.72rem 0.85rem;
    border-radius: 16px;
    border: 1px solid rgba(148, 163, 184, 0.16);
    background: rgba(10, 20, 35, 0.68);
    color: #c4d4e7;
}
</style>
"""


def _safe_numeric_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _inject_builder_view_styles() -> None:
    st.markdown(BUILDER_VIEW_CSS, unsafe_allow_html=True)


def _extract_live_stream_session_id(text: str) -> str:
    match = re.search(r"(?m)^\s*SESSION\s*:\s*(?P<session_id>\S+)\s*$", str(text or ""))
    if not match:
        return ""
    return str(match.group("session_id") or "").strip()


def _current_builder_live_session_id() -> str:
    try:
        runtime = _load_autonomous_runtime_state()
    except Exception:
        return ""
    if not bool(runtime.get("active")) or bool(runtime.get("manual_stop")):
        return ""
    return str(runtime.get("current_session_id") or "").strip()


def _load_builder_live_thoughts_preview(
    path: Path = STREAM_FILE,
    *,
    tail_lines: int = 220,
    max_chars: int = 30000,
    expected_session_id: str = "",
) -> tuple[str, bool]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeError):
        return "", False

    expected_session_id = str(expected_session_id or "").strip()
    if expected_session_id:
        live_session_id = _extract_live_stream_session_id(raw)
        if live_session_id and live_session_id != expected_session_id:
            return (
                "Flux live masque: le fichier courant appartient a la session "
                f"`{live_session_id}`, alors que la session attendue est "
                f"`{expected_session_id}`. Le prochain evenement Builder "
                "reinitialisera `_live_thoughts.md` avec la bonne session.",
                False,
            )

    lines = raw.splitlines()
    truncated = False
    if tail_lines > 0 and len(lines) > tail_lines:
        lines = lines[-tail_lines:]
        truncated = True
    text = "\n".join(lines).strip()
    if max_chars > 0 and len(text) > max_chars:
        text = text[-max_chars:]
        truncated = True
    if truncated and text:
        text = "…(truncated)…\n" + text
    return text, truncated


def _fill_live_thoughts_slot(slot: Any, tail_lines: int = 220) -> None:
    """Relit STREAM_FILE et met à jour le slot st.empty() dédié au contenu live."""
    preview, truncated = _load_builder_live_thoughts_preview(
        STREAM_FILE,
        tail_lines=tail_lines,
        expected_session_id=_current_builder_live_session_id(),
    )
    with slot.container():
        if preview:
            if truncated:
                st.caption(f"Affichage des {tail_lines} dernières lignes du flux courant.")
            st.code(preview, language="markdown")
        else:
            st.caption("No live thought stream available yet.")


def _refresh_live_thoughts_code_slot(tail_lines: int = 180) -> None:
    """Met à jour le slot live thoughts stocké en session_state, si présent."""
    slot = st.session_state.get("_live_thoughts_code_slot")
    if slot is None:
        return
    try:
        _fill_live_thoughts_slot(slot, tail_lines=tail_lines)
    except Exception:
        pass


def _render_builder_live_thoughts_panel(
    *,
    title: str = "📂 Live Thought Stream",
    expanded: bool = False,
    show_terminal_command: bool = True,
    tail_lines: int = 220,
    placeholder: Any = None,
) -> None:
    target = placeholder if placeholder is not None else st
    with target.container():
        with st.expander(title, expanded=expanded):
            if show_terminal_command:
                st.code(
                    f'Get-Content "{STREAM_FILE}" -Wait -Tail 80',
                    language="powershell",
                )
            try:
                file_exists = STREAM_FILE.exists()
                modified_at = (
                    datetime.fromtimestamp(STREAM_FILE.stat().st_mtime).strftime(
                        "%d/%m/%Y %H:%M:%S"
                    )
                    if file_exists
                    else "n/a"
                )
            except OSError:
                file_exists = False
                modified_at = "n/a"
            st.caption(
                f"📄 File: `{STREAM_FILE}`"
                + (f" | Updated: {modified_at}" if file_exists else "")
            )
            code_slot = st.empty()
            # Stocker le slot pour permettre les mises à jour pendant la boucle autonome
            st.session_state["_live_thoughts_code_slot"] = code_slot
            _fill_live_thoughts_slot(code_slot, tail_lines=tail_lines)


def _render_builder_mode_hero(
    *,
    mode_label: str,
    orchestration_label: str,
    market_label: str,
    target_sharpe: float,
    capital: float,
    auto_market_pick: bool,
    extra_chips: Optional[List[str]] = None,
    subtitle: str = "",
) -> None:
    chips = [
        f"Mode: {mode_label}",
        f"Orchestration: {orchestration_label}",
        f"Marchés: {market_label}",
        f"Sharpe cible: {target_sharpe:.2f}",
        f"Capital: ${capital:,.0f}",
    ]
    if auto_market_pick:
        chips.append("Auto-marché actif")
    if extra_chips:
        chips.extend([chip for chip in extra_chips if chip])
    subtitle_html = html.escape(subtitle) if subtitle else "Vue synthétique du contexte Builder avant les détails techniques."
    summary_line = " • ".join(html.escape(chip) for chip in chips)
    st.markdown(
        """<div class="bc-builder-summary-line"><strong>Strategy Builder</strong><br>"""
        + subtitle_html
        + """<br>"""
        + summary_line
        + """</div>""",
        unsafe_allow_html=True,
    )


def _render_builder_runtime_notes(title: str, lines: List[str], *, expanded: bool = False) -> None:
    filtered = [line.strip() for line in lines if str(line or "").strip()]
    if not filtered:
        return
    with st.expander(title, expanded=expanded):
        for line in filtered:
            st.caption(line)


def _render_builder_badge_row(labels: List[str]) -> None:
    visible = [label for label in labels if str(label or "").strip()]
    if not visible:
        return
    badges = "".join(
        f"<span class='bc-builder-badge'>{html.escape(label)}</span>" for label in visible
    )
    st.markdown(f"<div class='bc-builder-badge-row'>{badges}</div>", unsafe_allow_html=True)


def _format_optional_float(value: Any, pattern: str, default: str = "n/a") -> str:
    try:
        if value is None:
            return default
        return pattern.format(float(value))
    except Exception:
        return default


def _normalize_builder_code_source(source: Any) -> str:
    raw = str(source or "").strip().lower().replace("_", "-")
    return re.sub(r"\s+", "-", raw)


def _get_builder_code_provenance_badge(
    phase_feedback: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    feedback = phase_feedback or {}
    code_feedback = (feedback.get("code", {}) if isinstance(feedback, dict) else {}) or {}
    backtest_feedback = (feedback.get("backtest", {}) if isinstance(feedback, dict) else {}) or {}

    source_raw = str(code_feedback.get("source", "") or "").strip()
    source = _normalize_builder_code_source(source_raw)

    if backtest_feedback.get("runtime_fix_fallback_deterministic_used"):
        return {
            "kind": "runtime_fix_fallback",
            "badge": "🛠️ Runtime-fix + fallback",
            "detail": "Statistiques issues d'un correctif runtime puis d'une bascule vers le fallback déterministe.",
        }

    if backtest_feedback.get("runtime_fix_applied"):
        return {
            "kind": "runtime_fix",
            "badge": "🛠️ Runtime-fix",
            "detail": "Statistiques issues d'un correctif runtime appliqué après un premier échec en exécution.",
        }

    if code_feedback.get("fallback_deterministic_used"):
        return {
            "kind": "deterministic_fallback",
            "badge": "🧱 Fallback déterministe",
            "detail": "Statistiques issues du code déterministe de secours, pas du code LLM original.",
        }

    retry_like_source = (
        "retry" in source
        or code_feedback.get("fallback_retry_used")
        or (
            int(code_feedback.get("realign_attempts", 0) or 0) > 0
            and source not in {"", "llm", "direct-llm", "llm-direct"}
        )
    )
    if retry_like_source:
        return {
            "kind": "retry",
            "badge": "♻️ LLM corrigé",
            "detail": "Statistiques issues d'un code LLM corrigé ou regénéré après un premier essai invalide.",
        }

    if source in {"", "llm", "direct-llm", "llm-direct", "initial", "raw-llm"}:
        return {
            "kind": "llm",
            "badge": "🧠 LLM direct",
            "detail": "Statistiques issues du code LLM validé sans fallback déterministe ni correctif runtime.",
        }

    source_label = source_raw or source or "inconnue"
    return {
        "kind": "other",
        "badge": f"🧩 Source: {source_label}",
        "detail": f"Statistiques issues d'une source Builder spécifique: {source_label}.",
    }


def _history_best_sharpe(history: List[Dict[str, Any]]) -> float:
    return max((_safe_numeric_float(item.get("best_sharpe"), 0.0) for item in history), default=0.0)


def _autonomous_history_strategy_sort_key(entry: Dict[str, Any]) -> tuple[float, ...]:
    final_return = _safe_numeric_float(
        entry.get("final_return", entry.get("best_return")),
        float("-inf"),
    )
    final_sharpe = _safe_numeric_float(
        entry.get("final_sharpe", entry.get("best_sharpe")),
        float("-inf"),
    )
    final_max_dd = abs(
        _safe_numeric_float(
            entry.get("final_max_dd", entry.get("best_max_dd")),
            float("inf"),
        )
    )
    final_trades = _safe_numeric_float(
        entry.get("final_trades", entry.get("best_trades")),
        0.0,
    )
    status = str(entry.get("status", "") or "").strip().lower()
    status_rank = 1.0 if status == "success" else 0.0
    return (
        status_rank,
        1.0 if final_return > 0.0 else 0.0,
        final_return,
        final_sharpe,
        -final_max_dd,
        final_trades,
    )


def _history_latest_session_num(history: List[Dict[str, Any]]) -> int:
    latest = 0
    for item in history or []:
        try:
            latest = max(latest, int(item.get("session_num", 0) or 0))
        except Exception:
            logger.warning("session_num parse failed for item=%s", item)
            continue
    return latest


def _resolve_autonomous_session_counter_seed(
    history: List[Dict[str, Any]],
    runtime_state: Optional[Dict[str, Any]] = None,
) -> int:
    runtime_last_session_num = 0
    if isinstance(runtime_state, dict):
        try:
            runtime_last_session_num = int(runtime_state.get("last_session_num", 0) or 0)
        except Exception:
            runtime_last_session_num = 0
    return max(len(history or []), _history_latest_session_num(history), runtime_last_session_num)


def _next_autonomous_recap_render_seq() -> int:
    seq = int(st.session_state.get("_builder_autonomous_recap_render_seq", 0) or 0) + 1
    st.session_state["_builder_autonomous_recap_render_seq"] = seq
    return seq


def _extract_code_from_stream_text(text: str) -> str:
    normalized = str(text or "").replace("\r\n", "\n")

    fenced_blocks = re.findall(
        r"```(?:python)?\s*(.*?)```",
        normalized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if fenced_blocks:
        return str(fenced_blocks[-1]).strip()

    lines = normalized.splitlines()
    first_code_index: Optional[int] = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(_STREAM_CODE_LINE_PREFIXES):
            first_code_index = idx
            break
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*=", stripped):
            first_code_index = idx
            break
        if stripped.endswith(":") and (
            stripped.startswith(("if ", "elif ", "else", "for ", "while ", "try", "except ", "with "))
        ):
            first_code_index = idx
            break

    if first_code_index is None:
        return ""

    code_lines: List[str] = []
    for line in lines[first_code_index:]:
        stripped = line.strip()
        if (
            stripped.startswith("## ")
            or stripped.startswith("<|")
            or stripped.startswith("Okay,")
            or stripped.startswith("Wait,")
            or stripped.startswith("Let me")
            or stripped.startswith("First,")
            or stripped.startswith("Next,")
        ):
            continue
        code_lines.append(line)
    return "\n".join(code_lines).strip()


def _sanitize_builder_stream_text(phase: str, text: str) -> tuple[str, str]:
    cleaned = str(text or "").replace("\r\n", "\n")
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<think>.*", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = cleaned.replace("<|im_start|>", "").replace("<|im_end|>", "")

    if phase in {"code", "retry_code"}:
        code_view = _extract_code_from_stream_text(cleaned)
        if code_view:
            return code_view, "python"
        return (
            "Generation du code utile en cours...\n"
            "Le prompt brut et les auto-commentaires du modele sont masques.",
            "text",
        )

    lines = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        if stripped.startswith("<|"):
            continue
        if stripped.startswith("## YOUR TURN"):
            continue
        lines.append(line)
    return "\n".join(lines).strip(), "text"


_BUILDER_PROGRESS_PHASE_LABELS = {
    "proposal": "proposition",
    "code": "generation code",
    "save_and_load": "sauvegarde / chargement",
    "precheck": "precheck signaux",
    "analysis": "analyse",
    "backtest": "backtest",
    "runtime_fix": "reparation runtime",
    "runtime_fix_fallback_backtest": "backtest fallback",
    "validation": "validation",
}


def _builder_event_payload(event_payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = event_payload.get("payload")
    if isinstance(payload, dict):
        return dict(payload)
    return {}


def _builder_event_branch_label(event_payload: Dict[str, Any]) -> str:
    payload = _builder_event_payload(event_payload)
    return str(
        event_payload.get("selected_branch_label")
        or event_payload.get("branch_label")
        or payload.get("selected_branch_label")
        or payload.get("branch_label")
        or ""
    ).strip()


def _builder_branch_prefix(branch_label: str, *, include_main: bool = False) -> str:
    cleaned = str(branch_label or "").strip()
    if not cleaned:
        return ""
    if cleaned == "main" and not include_main:
        return ""
    return f"[{cleaned}] "


def _format_builder_live_event_line(event_payload: Dict[str, Any]) -> str:
    event = str(event_payload.get("event", "") or "")
    message = str(event_payload.get("message", "") or "").strip()
    payload = _builder_event_payload(event_payload)
    phase = str(event_payload.get("phase", "") or payload.get("phase", "") or "")
    branch_label = _builder_event_branch_label(event_payload)
    prefix = _builder_branch_prefix(
        branch_label,
        include_main=event in {"proposal_candidate", "proposal_selected"},
    )
    if event == "proposal_candidate":
        proposal = dict(payload.get("proposal") or {})
        hypothesis = str(proposal.get("hypothesis", "") or "hypothese candidate")
        return f"{prefix}Proposition candidate: {hypothesis}"
    if event == "proposal_selected":
        proposal = dict(payload.get("proposal") or {})
        hypothesis = str(proposal.get("hypothesis", "") or "hypothese retenue")
        return f"{prefix}Branche retenue: {hypothesis}"
    if event == "phase_done" and phase == "backtest":
        sharpe = _safe_optional_float(payload.get("sharpe"))
        ret_pct = _safe_optional_float(payload.get("total_return_pct"))
        if sharpe is not None and ret_pct is not None:
            return f"{prefix}Backtest: Sharpe {sharpe:.3f} | Return {ret_pct:+.2f}%"
    if message:
        return prefix + message
    if event == "iteration_done":
        decision = str(payload.get("decision", "") or "").strip()
        return f"Iteration terminee{f' ({decision})' if decision else ''}"
    return prefix + (event or "progress")


def _format_builder_live_detail_lines(event_payload: Dict[str, Any]) -> List[str]:
    event = str(event_payload.get("event", "") or "")
    payload = _builder_event_payload(event_payload)
    details: List[str] = []
    if event == "proposal_selected":
        proposal = dict(payload.get("proposal") or {})
        used = proposal.get("used_indicators", [])
        if proposal.get("hypothesis"):
            details.append(f"Hypothese retenue: {proposal['hypothesis']}")
        if isinstance(used, list) and used:
            details.append("Indicateurs: " + ", ".join(str(item) for item in used))
    elif event == "phase_done" and str(event_payload.get("phase", "") or "") == "backtest":
        sharpe = _safe_optional_float(payload.get("sharpe"))
        ret_pct = _safe_optional_float(payload.get("total_return_pct"))
        if sharpe is not None and ret_pct is not None:
            details.append(
                f"Backtest courant: Sharpe {sharpe:.3f} | Return {ret_pct:+.2f}%"
            )
        else:
            logger.warning("backtest metric format failed sharpe=%s ret_pct=%s", sharpe, ret_pct)
    elif event == "iteration_error":
        error_text = str(payload.get("error", "") or "").strip()
        if error_text:
            details.append(f"Erreur: {error_text[:220]}")
    else:
        detail_text = str(payload.get("detail", "") or "").strip()
        if detail_text:
            details.append(f"Detail: {detail_text[:220]}")
    return details


def _default_autonomous_supervisor_state() -> Dict[str, Any]:
    return {
        "version": _AUTONOMOUS_SUPERVISOR_VERSION,
        "consecutive_errors": 0,
        "consecutive_failed_sessions": 0,
        "soft_reset_count": 0,
        "soft_reset_timestamps": [],
        "last_error_origin": "",
        "last_error": "",
        "last_recovery_reason": "",
        "last_selected_source_mode": "",
        "last_selected_source_reason": "",
        "forced_source_mode": "",
        "disable_auto_market_pick_once": False,
        "last_resume_at": "",
        "next_pause_multiplier": 1,
    }


def _default_autonomous_runtime_state() -> Dict[str, Any]:
    return {
        "version": _AUTONOMOUS_RUNTIME_VERSION,
        "active": False,
        "manual_stop": False,
        "run_id": "",
        "claim_source": "",
        "claim_reason": "",
        "owner_pid": 0,
        "owner_started_at": "",
        "owner_signature": "",
        "started_at": "",
        "last_heartbeat_at": "",
        "last_resume_at": "",
        "last_event": "",
        "last_error": "",
        "last_stop_reason": "",
        "last_session_num": 0,
        "last_session_id": "",
        "last_session_status": "",
        "current_session_num": 0,
        "current_session_id": "",
        "last_progress_at": "",
        "last_progress_event": "",
        "last_progress_phase": "",
        "last_progress_iteration": 0,
        "pid": 0,
        "process_rss_mb": 0.0,
        "system_available_ram_mb": 0.0,
        "model": "",
        "ollama_host": "",
        "requested_source_mode": "",
        "effective_source_mode": "",
        "auto_market_pick": False,
        "resume_count": 0,
        "resume_ui_state": {},
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_runtime_timestamp(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _collect_autonomous_runtime_process_metrics() -> Dict[str, Any]:
    metrics: Dict[str, Any] = {
        "pid": 0,
        "process_rss_mb": 0.0,
        "system_available_ram_mb": 0.0,
    }
    try:
        metrics["pid"] = int(os.getpid())
    except Exception:
        metrics["pid"] = 0

    if not _HAS_PSUTIL:
        return metrics

    try:
        process = psutil.Process()
        metrics["process_rss_mb"] = round(
            float(process.memory_info().rss) / (1024.0 ** 2),
            1,
        )
    except Exception:
        metrics["process_rss_mb"] = 0.0

    try:
        metrics["system_available_ram_mb"] = round(
            float(psutil.virtual_memory().available) / (1024.0 ** 2),
            1,
        )
    except Exception:
        metrics["system_available_ram_mb"] = 0.0

    return metrics


def _current_process_owner_started_at() -> str:
    if not _HAS_PSUTIL:
        return ""
    try:
        started_ts = float(psutil.Process(os.getpid()).create_time())
    except Exception:
        return ""
    return datetime.fromtimestamp(started_ts, tz=timezone.utc).replace(
        microsecond=0
    ).isoformat()


def _current_runtime_owner_fields() -> Dict[str, Any]:
    pid = int(os.getpid())
    started_at = _current_process_owner_started_at()
    signature = f"{pid}:{started_at or 'unknown'}"
    return {
        "owner_pid": pid,
        "owner_started_at": started_at,
        "owner_signature": signature,
    }


def _new_autonomous_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{os.getpid()}_{uuid.uuid4().hex[:8]}"


def _safe_runtime_pid(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _runtime_pid_exists(pid: int) -> Optional[bool]:
    if pid <= 0 or not _HAS_PSUTIL:
        return None
    try:
        return bool(psutil.pid_exists(pid))
    except Exception:
        return None


def _runtime_claim_owned_by_current_process(runtime: Dict[str, Any]) -> bool:
    if not str(runtime.get("run_id") or "").strip():
        return False
    current = _current_runtime_owner_fields()
    owner_signature = str(runtime.get("owner_signature") or "").strip()
    if owner_signature:
        return owner_signature == current["owner_signature"]
    owner_pid = _safe_runtime_pid(runtime.get("owner_pid") or runtime.get("pid"))
    return owner_pid == int(current["owner_pid"])


def _runtime_claim_owner_alive(runtime: Dict[str, Any]) -> bool:
    if not str(runtime.get("run_id") or "").strip():
        return False
    owner_pid = _safe_runtime_pid(runtime.get("owner_pid") or runtime.get("pid"))
    if owner_pid <= 0:
        return False
    exists = _runtime_pid_exists(owner_pid)
    return exists is not False


def _runtime_claim_can_resume_in_current_process(runtime: Dict[str, Any]) -> bool:
    if not bool(runtime.get("active")) or bool(runtime.get("manual_stop")):
        return False
    if not str(runtime.get("run_id") or "").strip():
        return False
    if _runtime_claim_owned_by_current_process(runtime):
        return True
    claim_source = str(runtime.get("claim_source") or "").strip()
    owner_pid = _safe_runtime_pid(runtime.get("owner_pid") or runtime.get("pid"))
    if owner_pid <= 0 or claim_source == "external_supervisor":
        return True
    return _runtime_pid_exists(owner_pid) is False


def _runtime_claim_can_auto_resume_in_current_process(runtime: Dict[str, Any]) -> bool:
    if not bool(runtime.get("active")) or bool(runtime.get("manual_stop")):
        return False
    if not str(runtime.get("run_id") or "").strip():
        return False
    return _runtime_claim_owned_by_current_process(runtime)


def _reset_inactive_builder_live_thoughts(
    *,
    reason: str,
    respect_session_running: bool = True,
) -> None:
    if respect_session_running and bool(st.session_state.get("is_running", False)):
        return
    runtime = _load_autonomous_runtime_state()
    if bool(runtime.get("active")) and not bool(runtime.get("manual_stop")):
        if _runtime_claim_owned_by_current_process(runtime) or _runtime_claim_owner_alive(runtime):
            return
    reset_live_stream(
        path=STREAM_FILE,
        reason=reason,
        last_session_id=str(
            runtime.get("current_session_id") or runtime.get("last_session_id") or ""
        ),
    )
    st.session_state.pop("_live_thoughts_code_slot", None)


def reset_inactive_builder_live_thoughts(
    *,
    reason: str,
    respect_session_running: bool = True,
) -> None:
    _reset_inactive_builder_live_thoughts(
        reason=reason,
        respect_session_running=respect_session_running,
    )


def _recent_soft_reset_timestamps(
    supervisor: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> List[str]:
    current_time = now or datetime.now(timezone.utc)
    raw_items = supervisor.get("soft_reset_timestamps", [])
    if not isinstance(raw_items, list):
        raw_items = []

    cleaned: List[str] = []
    for raw in raw_items:
        parsed = _parse_runtime_timestamp(raw)
        if parsed is None:
            continue
        if (current_time - parsed).total_seconds() <= _AUTONOMOUS_SOFT_RESET_WINDOW_SECONDS:
            cleaned.append(parsed.replace(microsecond=0).isoformat())
    supervisor["soft_reset_timestamps"] = cleaned
    return cleaned


def _compact_history_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Retire les cles redondantes (universe_meta, etc.) d'une entry history.

    Ces donnees sont disponibles dans le session_summary.json sur disque ;
    les conserver dans l'historique en RAM/JSON fait gonfler le supervisor_state
    sans valeur ajoutee pour le superviseur.
    """
    if not isinstance(entry, dict):
        return entry
    return {k: v for k, v in entry.items() if k not in _AUTONOMOUS_HISTORY_PURGED_KEYS}


def _trim_autonomous_history(
    history: List[Dict[str, Any]],
    *,
    limit: int = _AUTONOMOUS_MAX_PERSISTED_HISTORY,
) -> List[Dict[str, Any]]:
    items = list(history or [])
    if len(items) > limit:
        items = items[-limit:]
    # Compaction : applique a chaque entry, y compris celles persistees avant
    # l'ajout du filtre (migration automatique au prochain save).
    return [_compact_history_entry(item) for item in items]


def _sync_autonomous_state(
    history: List[Dict[str, Any]],
    supervisor: Dict[str, Any],
    *,
    trim: bool = True,
    persist: bool = True,
) -> None:
    """Point d'écriture canonique pour l'état autonome (history + supervisor).

    Remplace les écritures dispersées ``st.session_state[...] = ...`` par un
    unique chemin de mutation, ce qui élimine les divergences d'état.
    """
    if trim:
        history[:] = _trim_autonomous_history(history)
    st.session_state["builder_autonomous_history"] = history
    st.session_state["builder_autonomous_supervisor"] = supervisor
    if persist:
        _save_autonomous_supervisor_state(history, supervisor)


def _load_autonomous_supervisor_state() -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "history": [],
        "supervisor": _default_autonomous_supervisor_state(),
    }
    if not _AUTONOMOUS_SUPERVISOR_STATE_FILE.exists():
        return payload

    try:
        raw = json.loads(
            _AUTONOMOUS_SUPERVISOR_STATE_FILE.read_text(encoding="utf-8")
        )
    except Exception as exc:
        logger.warning("builder_autonomous_state_load_failed error=%s", exc)
        return payload

    history = raw.get("history", [])
    if not isinstance(history, list):
        history = []

    supervisor = _default_autonomous_supervisor_state()
    raw_supervisor = raw.get("supervisor", {})
    if isinstance(raw_supervisor, dict):
        for key in supervisor.keys():
            if key in raw_supervisor:
                supervisor[key] = raw_supervisor[key]

    payload["history"] = _trim_autonomous_history(
        [item for item in history if isinstance(item, dict)]
    )
    payload["supervisor"] = supervisor
    return payload


def _load_autonomous_runtime_state() -> Dict[str, Any]:
    runtime = _default_autonomous_runtime_state()
    if not _AUTONOMOUS_RUNTIME_STATE_FILE.exists():
        return runtime

    try:
        raw = json.loads(_AUTONOMOUS_RUNTIME_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("builder_autonomous_runtime_load_failed error=%s", exc)
        return runtime

    if not isinstance(raw, dict):
        return runtime
    if isinstance(raw.get("runtime"), dict):
        raw = raw["runtime"]

    for key in runtime.keys():
        if key in raw:
            runtime[key] = raw[key]
    return runtime


def _normalize_autonomous_objective_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _parse_autonomous_session_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    match = re.match(r"^(?P<stamp>\d{8}_\d{6})", text)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("stamp"), "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def _get_autonomous_session_started_at(entry: Dict[str, Any]) -> Optional[datetime]:
    for key in ("started_at", "start_time", "created_at", "recorded_at"):
        dt = _parse_autonomous_session_datetime(entry.get(key))
        if dt is not None:
            return dt
    return _parse_autonomous_session_datetime(entry.get("session_id"))


def _format_autonomous_session_started_at(
    entry: Dict[str, Any],
    *,
    default: str = "n/a",
) -> str:
    dt = _get_autonomous_session_started_at(entry)
    if dt is None:
        return default
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def _safe_optional_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        numeric = float(value)
    except Exception:
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


# ---------------------------------------------------------------------------
# Micro-helpers de coercion et de snapshot communs
# ---------------------------------------------------------------------------

def _coerce_list(value: Any) -> list:
    """Retourne value si c'est une liste, sinon []."""
    return value if isinstance(value, list) else []


# Schéma pour _build_builder_autonomous_resume_ui_state : (attr, type, default)
_RESUME_UI_SCHEMA: tuple = (
    ("builder_execution_mode", str, "mono_single_llm"),
    ("builder_model_single_llm", str, ""),
    ("builder_ollama_host", str, ""),
    ("builder_auto_pause", int, 10),
    ("builder_auto_use_llm", bool, True),
    ("builder_auto_market_pick", bool, False),
    ("builder_universe_mode", str, BUILDER_UNIVERSE_MODE_CANONICAL),
    ("builder_preload_model", bool, True),
    ("builder_keep_alive_minutes", int, 20),
    ("builder_unload_after_run", bool, True),
    ("builder_auto_start_ollama", bool, True),
    ("builder_flow_analysis_enabled", bool, False),
)


_BUILDER_RUNTIME_CFG_GETTER = itemgetter(
    "model", "ollama_host", "max_iterations", "target_sharpe", "capital",
    "auto_market_pick", "orchestration_label", "preload_model",
    "keep_alive_minutes", "unload_after_run", "auto_start_ollama",
    "builder_execution_mode", "orchestration_mode",
    "builder_flow_analysis_enabled", "builder_flow_analysis_ablation",
    "llm_inference_global_settings", "llm_inference_model_profiles",
)

_BUILDER_MARKET_UNIVERSE_CACHE_KEY = "_builder_market_universe_cache"
_BUILDER_MARKET_UNIVERSE_CACHE_VERSION = 1
_BUILDER_MARKET_UNIVERSE_CACHE_MAX_ENTRIES = 12
_BUILDER_AUTONOMOUS_RUN_ID_STATE_KEY = "_builder_autonomous_run_id"


# 7 suffixes de sortie communs aux snapshots best_ / final_
_SNAPSHOT_SUFFIXES = (
    "return", "return_iteration", "max_dd", "pf",
    "trades", "return_sharpe", "total_pnl",
)
# Clés source alignées — lignes JSON session_summary
_SUMMARY_ROW_KEYS = (
    "return_pct", "iteration", "max_drawdown_pct", "profit_factor",
    "trades", "sharpe", "total_pnl",
)
# Clés source alignées — backtest_result.metrics brut (None = external)
_RAW_METRICS_KEYS = (
    "total_return_pct", None, "max_drawdown_pct", "profit_factor",
    "total_trades", "sharpe_ratio", "total_pnl",
)


def _snapshot_key(prefix: str, suffix: str) -> str:
    if prefix == "final":
        suffix = {"return_iteration": "iteration", "return_sharpe": "sharpe"}.get(
            suffix,
            suffix,
        )
    return f"{prefix}_{suffix}"


def _snapshot_from_summary_row(
    prefix: str, row: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Construit un dict {prefix}_{suffix} depuis une ligne JSON summary."""
    if not row:
        return {_snapshot_key(prefix, s): None for s in _SNAPSHOT_SUFFIXES}
    return {
        _snapshot_key(prefix, s): row.get(k)
        for s, k in zip(_SNAPSHOT_SUFFIXES, _SUMMARY_ROW_KEYS)
    }


def _snapshot_from_metrics(
    prefix: str,
    metrics: Optional[Dict[str, Any]],
    *,
    iteration: Any = None,
) -> Dict[str, Any]:
    """Construit un dict {prefix}_{suffix} depuis un dict metrics brut."""
    if not metrics:
        result = {_snapshot_key(prefix, s): None for s in _SNAPSHOT_SUFFIXES}
        result[_snapshot_key(prefix, "return_iteration")] = iteration
        return result
    result: Dict[str, Any] = {}
    for suffix, key in zip(_SNAPSHOT_SUFFIXES, _RAW_METRICS_KEYS):
        output_key = _snapshot_key(prefix, suffix)
        if key is None:
            result[output_key] = iteration
        else:
            result[output_key] = metrics.get(key)
    return result


_RUNTIME_FEEDBACK_EMPTY: Dict[str, Any] = {
    "last_runtime_error": None,
    "last_runtime_error_iteration": None,
    "last_runtime_traceback_tail": None,
}


def _runtime_feedback_payload(
    *,
    runtime_error: Any,
    runtime_iteration: Any,
    runtime_traceback_tail: Any,
) -> Dict[str, Any]:
    error_text = str(runtime_error or "").strip()
    traceback_text = str(runtime_traceback_tail or "").strip()
    if not error_text and not traceback_text:
        return dict(_RUNTIME_FEEDBACK_EMPTY)
    return {
        "last_runtime_error": error_text or None,
        "last_runtime_error_iteration": runtime_iteration,
        "last_runtime_traceback_tail": traceback_text or None,
    }


def _extract_runtime_feedback_from_backtest_rows(
    rows: Iterable[tuple[Any, Any]],
) -> Dict[str, Any]:
    for runtime_iteration, backtest_feedback in rows:
        if not isinstance(backtest_feedback, dict):
            continue
        payload = _runtime_feedback_payload(
            runtime_error=backtest_feedback.get("runtime_error"),
            runtime_iteration=runtime_iteration,
            runtime_traceback_tail=backtest_feedback.get("runtime_traceback_tail"),
        )
        if payload != _RUNTIME_FEEDBACK_EMPTY:
            return payload
    return dict(_RUNTIME_FEEDBACK_EMPTY)


def _recover_dict_field(
    primary: Dict[str, Any],
    fallback: Dict[str, Any],
    key: str,
) -> dict:
    """Récupère un champ dict depuis primary, fallback sur fallback[key]."""
    val = primary.get(key)
    if isinstance(val, dict):
        return dict(val or {})
    return dict(fallback.get(key, {}) or {})


def _extract_autonomous_bar_count_from_summary(summary: Dict[str, Any]) -> Optional[int]:
    raw_iterations = summary.get("iterations", [])
    iterations = raw_iterations if isinstance(raw_iterations, list) else []
    for row in reversed(iterations):
        if not isinstance(row, dict):
            continue
        phase_feedback = row.get("phase_feedback")
        if not isinstance(phase_feedback, dict):
            continue
        precheck = phase_feedback.get("precheck")
        if not isinstance(precheck, dict):
            continue
        try:
            bar_count = int(precheck.get("bar_count", 0) or 0)
        except Exception:
            continue
        if bar_count > 0:
            return bar_count
    return None


def _timeframe_to_days(timeframe: Any) -> Optional[float]:
    text = str(timeframe or "").strip().lower()
    match = re.fullmatch(r"(\d+)\s*([mhdw])", text)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    unit_days = {
        "m": 1.0 / 1440.0,
        "h": 1.0 / 24.0,
        "d": 1.0,
        "w": 7.0,
    }
    return value * unit_days[unit]


def _compute_autonomous_test_days(
    *,
    timeframe: Any,
    n_bars: Any,
    date_range_start: Any,
    date_range_end: Any,
) -> Optional[float]:
    dt_start = _parse_autonomous_session_datetime(date_range_start)
    dt_end = _parse_autonomous_session_datetime(date_range_end)
    if dt_start is not None and dt_end is not None:
        delta_days = (dt_end - dt_start).total_seconds() / 86400.0
        if delta_days > 0:
            return delta_days

    tf_days = _timeframe_to_days(timeframe)
    if tf_days is None:
        return None

    try:
        bars = int(n_bars or 0)
    except Exception:
        return None
    if bars <= 0:
        return None
    return bars * tf_days


def _resolve_autonomous_gain_metrics(entry: Dict[str, Any]) -> Dict[str, Optional[float]]:
    status = str(entry.get("status", "") or "").strip().lower()
    if status not in {"success", "max_iterations"}:
        return {
            "total_pnl": None,
            "test_days": None,
            "pnl_per_day": None,
        }

    final_return = _safe_optional_float(entry.get("final_return"))
    initial_capital = _safe_optional_float(entry.get("initial_capital"))
    total_pnl = _safe_optional_float(entry.get("final_total_pnl"))

    if total_pnl is None and final_return is not None and initial_capital is not None:
        total_pnl = initial_capital * (final_return / 100.0)
    if total_pnl is None and final_return is not None:
        total_pnl = 10000.0 * (final_return / 100.0)

    test_days = _compute_autonomous_test_days(
        timeframe=entry.get("timeframe"),
        n_bars=entry.get("n_bars"),
        date_range_start=entry.get("date_range_start"),
        date_range_end=entry.get("date_range_end"),
    )

    pnl_per_day: Optional[float] = None
    if total_pnl is not None and test_days is not None and test_days > 0:
        pnl_per_day = total_pnl / test_days

    return {
        "total_pnl": total_pnl,
        "test_days": test_days,
        "pnl_per_day": pnl_per_day,
    }


def _extract_best_return_snapshot_from_session_summary(
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    best_row: Optional[Dict[str, Any]] = None
    best_return: Optional[float] = None

    for row in _coerce_list(summary.get("iterations", [])):
        if not isinstance(row, dict):
            continue
        current_return = _safe_optional_float(row.get("return_pct"))
        if current_return is None:
            continue
        if best_return is None or current_return > best_return:
            best_return = current_return
            best_row = row

    if best_row is not None:
        return _snapshot_from_summary_row("best", best_row)

    for row in _coerce_list(summary.get("leaderboard", [])):
        if isinstance(row, dict):
            return _snapshot_from_summary_row("best", row)

    return _snapshot_from_summary_row("best", None)


def _extract_final_iteration_snapshot_from_session_summary(
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    for row in reversed(_coerce_list(summary.get("iterations", []))):
        if isinstance(row, dict):
            return _snapshot_from_summary_row("final", row)

    for row in _coerce_list(summary.get("leaderboard", [])):
        if isinstance(row, dict):
            return _snapshot_from_summary_row("final", row)

    return _snapshot_from_summary_row("final", None)


def _extract_last_runtime_feedback_from_session_summary(
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    from_summary = _runtime_feedback_payload(
        runtime_error=summary.get("last_runtime_error"),
        runtime_iteration=summary.get("last_runtime_error_iteration"),
        runtime_traceback_tail=summary.get("last_runtime_traceback_tail"),
    )
    if from_summary != _RUNTIME_FEEDBACK_EMPTY:
        return from_summary

    rows: List[tuple[Any, Any]] = []
    for row in reversed(_coerce_list(summary.get("iterations", []))):
        if not isinstance(row, dict):
            continue
        phase_feedback = row.get("phase_feedback")
        backtest_feedback = (
            phase_feedback.get("backtest", {}) if isinstance(phase_feedback, dict) else {}
        )
        rows.append((row.get("iteration"), backtest_feedback))
    return _extract_runtime_feedback_from_backtest_rows(rows)


def _extract_autonomous_session_last_runtime_feedback(session: Any) -> Dict[str, Any]:
    rows: List[tuple[Any, Any]] = []
    iterations = getattr(session, "iterations", []) or []
    for iteration in reversed(iterations):
        phase_feedback = getattr(iteration, "phase_feedback", {}) or {}
        backtest_feedback = (
            phase_feedback.get("backtest", {}) if isinstance(phase_feedback, dict) else {}
        )
        rows.append((getattr(iteration, "iteration", None), backtest_feedback))
    return _extract_runtime_feedback_from_backtest_rows(rows)


def _load_builder_runtime_checkpoint(session_id: str) -> Optional[Dict[str, Any]]:
    checkpoint_path = SANDBOX_ROOT / str(session_id or "").strip() / "runtime_checkpoint.json"
    if not checkpoint_path.exists():
        return None
    try:
        raw = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _extract_last_runtime_feedback_from_checkpoint(
    checkpoint: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(checkpoint, dict):
        return dict(_RUNTIME_FEEDBACK_EMPTY)

    backtest_feedback = checkpoint.get("backtest_feedback", {})
    if not isinstance(backtest_feedback, dict):
        backtest_feedback = {}

    return _runtime_feedback_payload(
        runtime_error=checkpoint.get("error") or backtest_feedback.get("runtime_error"),
        runtime_iteration=checkpoint.get("iteration"),
        runtime_traceback_tail=(
            checkpoint.get("traceback_tail")
            or backtest_feedback.get("runtime_traceback_tail")
        ),
    )


def _build_recovered_autonomous_history_entry_from_checkpoint(
    entry: Dict[str, Any],
    checkpoint: Dict[str, Any],
    *,
    session_id: str,
) -> Dict[str, Any]:
    recovered = dict(entry)
    runtime_feedback = _extract_last_runtime_feedback_from_checkpoint(checkpoint)
    recovered["session_id"] = session_id
    recovered["last_runtime_error"] = runtime_feedback.get("last_runtime_error")
    recovered["last_runtime_error_iteration"] = runtime_feedback.get(
        "last_runtime_error_iteration"
    )
    recovered["last_runtime_traceback_tail"] = runtime_feedback.get(
        "last_runtime_traceback_tail"
    )
    recovered["recovered_from_runtime_checkpoint"] = True
    if checkpoint.get("objective"):
        recovered["objective"] = checkpoint.get("objective")
    return recovered


def _load_autonomous_session_summary(summary_path: Path) -> Optional[Dict[str, Any]]:
    try:
        raw = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def _build_recovered_autonomous_history_entry(
    entry: Dict[str, Any],
    summary: Dict[str, Any],
    *,
    session_id: str,
) -> Dict[str, Any]:
    recovered = dict(entry)
    recovered_snapshot = _extract_best_return_snapshot_from_session_summary(summary)
    final_snapshot = _extract_final_iteration_snapshot_from_session_summary(summary)
    runtime_feedback = _extract_last_runtime_feedback_from_session_summary(summary)
    iterations = _coerce_list(summary.get("iterations", []))

    recovered["session_id"] = session_id
    recovered["n_iterations"] = int(summary.get("total_iterations") or len(iterations) or 0)
    recovered["best_sharpe"] = summary.get("best_sharpe")
    recovered["best_telemetry_score"] = summary.get(
        "best_telemetry_score",
        summary.get("best_score"),
    )
    recovered["best_score"] = recovered["best_telemetry_score"]
    # Spread snapshot dicts au lieu de recopier champ par champ
    recovered.update(recovered_snapshot)
    recovered.update(final_snapshot)
    recovered["n_bars"] = (
        summary.get("n_bars")
        or recovered.get("n_bars")
        or _extract_autonomous_bar_count_from_summary(summary)
    )

    scalar_defaults: Dict[str, Any] = {
        "date_range_start": None,
        "date_range_end": None,
        "initial_capital": None,
        "universe_mode": BUILDER_UNIVERSE_MODE_CANONICAL,
        "universe_purpose": "builder_autonomous",
        "universe_strategy_type": "",
        "builder_execution_mode": BUILDER_EXECUTION_MODE_MONO,
        "orchestration_mode": "single_llm",
        "pipeline_traces_path": "",
    }
    for key, default in scalar_defaults.items():
        recovered[key] = summary.get(key) or recovered.get(key) or default

    # universe_meta & instrumentation_summary : volontairement non recuperees ici
    # (cf. _AUTONOMOUS_HISTORY_PURGED_KEYS — restent disponibles dans session_summary.json).
    recovered["instrumentation_enabled"] = bool(
        summary.get("instrumentation_enabled", recovered.get("instrumentation_enabled", False))
    )
    recovered["pipeline_traces_path"] = str(recovered.get("pipeline_traces_path") or "")
    # Runtime feedback : recovered a priorité, sinon fallback sur extraction
    for fb_key in ("last_runtime_error", "last_runtime_error_iteration",
                   "last_runtime_traceback_tail"):
        recovered[fb_key] = recovered.get(fb_key) or runtime_feedback.get(fb_key)
    recovered["recovered_from_summary"] = True
    recovered["recovered_session_status"] = summary.get("status")
    return recovered


def _recover_autonomous_history_entry_from_disk(
    entry: Dict[str, Any],
    *,
    runtime_state: Optional[Dict[str, Any]] = None,
    max_candidates: int = 250,
) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        return entry

    current_session_id = str(entry.get("session_id", "") or "").strip()
    current_iterations = int(entry.get("n_iterations", 0) or 0)
    current_return = entry.get("best_return")
    has_final_snapshot = any(
        entry.get(key) not in (None, "")
        for key in ("final_return", "final_iteration", "final_max_dd", "final_sharpe", "final_trades")
    )
    if current_session_id and has_final_snapshot and (current_return is not None or current_iterations > 0):
        return entry

    normalized_objective = _normalize_autonomous_objective_text(entry.get("objective"))
    if not normalized_objective:
        return entry

    candidate_session_ids: List[str] = []
    if current_session_id:
        candidate_session_ids.append(current_session_id)

    runtime_payload = runtime_state or _load_autonomous_runtime_state()
    runtime_last_session_id = str(runtime_payload.get("last_session_id", "") or "").strip()
    if runtime_last_session_id and runtime_last_session_id not in candidate_session_ids:
        candidate_session_ids.append(runtime_last_session_id)

    for session_id in candidate_session_ids:
        summary_path = SANDBOX_ROOT / session_id / "session_summary.json"
        if not summary_path.exists():
            checkpoint = _load_builder_runtime_checkpoint(session_id)
            if checkpoint is None:
                continue
            checkpoint_objective = _normalize_autonomous_objective_text(
                checkpoint.get("objective")
            )
            if normalized_objective == checkpoint_objective:
                return _build_recovered_autonomous_history_entry_from_checkpoint(
                    entry,
                    checkpoint,
                    session_id=session_id,
                )
            continue
        summary = _load_autonomous_session_summary(summary_path)
        if summary is None:
            continue
        summary_objective = _normalize_autonomous_objective_text(summary.get("objective"))
        if normalized_objective == summary_objective:
            return _build_recovered_autonomous_history_entry(entry, summary, session_id=session_id)

    recent_summary_paths: List[Path] = []
    try:
        for child in SANDBOX_ROOT.iterdir():
            if not child.is_dir() or child.name.startswith("_"):
                continue
            summary_path = child / "session_summary.json"
            if not summary_path.exists():
                continue
            recent_summary_paths.append(summary_path)
    except Exception:
        return entry

    recent_summary_paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for summary_path in recent_summary_paths[:max_candidates]:
        summary = _load_autonomous_session_summary(summary_path)
        if summary is None:
            continue
        summary_objective = _normalize_autonomous_objective_text(summary.get("objective"))
        if normalized_objective != summary_objective:
            continue
        return _build_recovered_autonomous_history_entry(
            entry,
            summary,
            session_id=summary_path.parent.name,
        )

    recent_checkpoint_paths: List[Path] = []
    try:
        for child in SANDBOX_ROOT.iterdir():
            if not child.is_dir() or child.name.startswith("_"):
                continue
            checkpoint_path = child / "runtime_checkpoint.json"
            if not checkpoint_path.exists():
                continue
            recent_checkpoint_paths.append(checkpoint_path)
    except Exception:
        return entry

    recent_checkpoint_paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for checkpoint_path in recent_checkpoint_paths[:max_candidates]:
        checkpoint = _load_builder_runtime_checkpoint(checkpoint_path.parent.name)
        if checkpoint is None:
            continue
        checkpoint_objective = _normalize_autonomous_objective_text(
            checkpoint.get("objective")
        )
        if normalized_objective != checkpoint_objective:
            continue
        return _build_recovered_autonomous_history_entry_from_checkpoint(
            entry,
            checkpoint,
            session_id=checkpoint_path.parent.name,
        )

    return entry


def _recover_autonomous_history_from_disk(
    history: List[Dict[str, Any]],
    *,
    runtime_state: Optional[Dict[str, Any]] = None,
) -> tuple[List[Dict[str, Any]], bool]:
    recovered_history: List[Dict[str, Any]] = []
    changed = False
    runtime_payload = runtime_state or _load_autonomous_runtime_state()

    for entry in list(history or []):
        if not isinstance(entry, dict):
            recovered_history.append(entry)
            continue
        recovered_entry = _recover_autonomous_history_entry_from_disk(
            entry,
            runtime_state=runtime_payload,
        )
        if recovered_entry != entry:
            changed = True
        recovered_history.append(recovered_entry)

    return recovered_history, changed


def _save_autonomous_supervisor_state(
    history: List[Dict[str, Any]],
    supervisor: Dict[str, Any],
) -> None:
    _AUTONOMOUS_SUPERVISOR_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    cleaned_supervisor = _default_autonomous_supervisor_state()
    for key in cleaned_supervisor.keys():
        if key in supervisor:
            cleaned_supervisor[key] = supervisor[key]

    payload = {
        "version": _AUTONOMOUS_SUPERVISOR_VERSION,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "history": _trim_autonomous_history(history),
        "supervisor": cleaned_supervisor,
    }

    _write_autonomous_state_atomically(
        _AUTONOMOUS_SUPERVISOR_STATE_FILE,
        payload,
        warning_log_key="builder_autonomous_state_save_failed",
        state_lock=_AUTONOMOUS_SUPERVISOR_STATE_LOCK,
    )


def _is_transient_state_save_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, "winerror", None)
    errno = getattr(exc, "errno", None)
    return winerror == 32 or errno in {13, 32}


def _cleanup_autonomous_tmp_file(tmp_path: Path) -> None:
    try:
        if tmp_path.exists():
            tmp_path.unlink()
    except Exception:
        pass


def _build_unique_autonomous_tmp_path(target_path: Path) -> Path:
    suffix = f".{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    return target_path.with_name(f"{target_path.name}{suffix}")


def _write_autonomous_state_atomically(
    target_path: Path,
    payload: Dict[str, Any],
    *,
    warning_log_key: str,
    state_lock: threading.Lock,
) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    last_exc: Optional[BaseException] = None

    with state_lock:
        for attempt in range(_AUTONOMOUS_STATE_SAVE_RETRIES):
            tmp_path = _build_unique_autonomous_tmp_path(target_path)
            try:
                tmp_path.write_text(serialized, encoding="utf-8")
                os.replace(tmp_path, target_path)
                return
            except Exception as exc:
                last_exc = exc
                _cleanup_autonomous_tmp_file(tmp_path)
                should_retry = (
                    attempt < (_AUTONOMOUS_STATE_SAVE_RETRIES - 1)
                    and _is_transient_state_save_error(exc)
                )
                if should_retry:
                    time.sleep(_AUTONOMOUS_STATE_SAVE_RETRY_DELAY_SEC * (attempt + 1))
                    continue
                break

    if last_exc is not None:
        logger.warning("%s error=%s", warning_log_key, last_exc)


def _save_autonomous_runtime_state(runtime: Dict[str, Any]) -> None:
    _AUTONOMOUS_RUNTIME_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    cleaned_runtime = _default_autonomous_runtime_state()
    for key in cleaned_runtime.keys():
        if key in runtime:
            cleaned_runtime[key] = runtime[key]

    payload = {
        "version": _AUTONOMOUS_RUNTIME_VERSION,
        "updated_at": _utc_now_iso(),
        "runtime": cleaned_runtime,
    }

    _write_autonomous_state_atomically(
        _AUTONOMOUS_RUNTIME_STATE_FILE,
        payload,
        warning_log_key="builder_autonomous_runtime_save_failed",
        state_lock=_AUTONOMOUS_RUNTIME_STATE_LOCK,
    )


def should_auto_resume_builder_autonomous(state: Any) -> tuple[bool, Dict[str, Any]]:
    if getattr(state, "optimization_mode", "") != "🏗️ Strategy Builder":
        return False, _default_autonomous_runtime_state()
    if not bool(getattr(state, "builder_autonomous", False)):
        return False, _default_autonomous_runtime_state()

    payload = _load_autonomous_runtime_state()
    should_resume = _runtime_claim_can_auto_resume_in_current_process(payload)
    return should_resume, payload


def _build_builder_autonomous_resume_ui_state(state: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for attr, typ, default in _RESUME_UI_SCHEMA:
        raw = getattr(state, attr, default)
        result[attr] = typ(raw or default) if raw is not None else typ(default)
    ablation = getattr(state, "builder_flow_analysis_ablation", {})
    result["builder_flow_analysis_ablation"] = (
        dict(ablation or {}) if isinstance(ablation, dict) else {}
    )
    return result


def restore_builder_autonomous_ui_state_from_runtime() -> tuple[bool, Dict[str, Any]]:
    """Restaure le mode Builder autonome dans la session Streamlit après redémarrage."""
    payload = _load_autonomous_runtime_state()
    should_resume = _runtime_claim_can_resume_in_current_process(payload)
    if not should_resume:
        return False, payload

    resume_ui_state = payload.get("resume_ui_state", {})
    if not isinstance(resume_ui_state, dict):
        resume_ui_state = {}

    st.session_state["optimization_mode"] = "🏗️ Strategy Builder"
    st.session_state["exec_mode_selector"] = "🏗️ Strategy Builder"
    st.session_state["builder_autonomous"] = True
    st.session_state["_builder_autonomous_toggle_sync"] = True

    builder_execution_mode = str(
        resume_ui_state.get("builder_execution_mode", "") or ""
    ).strip()
    if builder_execution_mode:
        st.session_state["builder_execution_mode"] = builder_execution_mode
        st.session_state["builder_execution_mode_select"] = builder_execution_mode

    builder_model_single_llm = str(
        resume_ui_state.get("builder_model_single_llm", "") or ""
    ).strip()
    if builder_model_single_llm:
        st.session_state["builder_model_single_llm"] = builder_model_single_llm

    builder_ollama_host = str(
        resume_ui_state.get("builder_ollama_host", "") or ""
    ).strip()
    if builder_ollama_host:
        st.session_state["builder_ollama_host"] = builder_ollama_host

    if "builder_auto_pause" in resume_ui_state:
        pause_value = int(resume_ui_state.get("builder_auto_pause", 10) or 10)
        st.session_state["builder_auto_pause"] = pause_value
        st.session_state["builder_auto_pause_slider"] = pause_value

    for name, widget_key in (
        ("builder_auto_use_llm", "builder_auto_use_llm_toggle"),
        ("builder_auto_market_pick", "builder_auto_market_pick_toggle"),
        ("builder_preload_model", "builder_preload_model_toggle"),
        ("builder_unload_after_run", "builder_unload_after_run_toggle"),
        ("builder_auto_start_ollama", "builder_auto_start_ollama_toggle"),
        ("builder_flow_analysis_enabled", "builder_flow_analysis_enabled_toggle"),
    ):
        if name not in resume_ui_state:
            continue
        toggle_value = bool(resume_ui_state.get(name))
        st.session_state[name] = toggle_value
        st.session_state[widget_key] = toggle_value

    if "builder_keep_alive_minutes" in resume_ui_state:
        keep_alive = int(
            resume_ui_state.get("builder_keep_alive_minutes", 20) or 20
        )
        st.session_state["builder_keep_alive_minutes"] = keep_alive
        st.session_state["builder_keep_alive_minutes_input"] = keep_alive

    builder_universe_mode = str(
        resume_ui_state.get("builder_universe_mode", BUILDER_UNIVERSE_MODE_CANONICAL)
        or BUILDER_UNIVERSE_MODE_CANONICAL
    ).strip() or BUILDER_UNIVERSE_MODE_CANONICAL
    st.session_state["builder_universe_mode"] = builder_universe_mode

    ablation_config = resume_ui_state.get("builder_flow_analysis_ablation", {})
    if isinstance(ablation_config, dict):
        st.session_state["builder_flow_analysis_ablation"] = dict(ablation_config)
        st.session_state["builder_flow_analysis_disabled_steps_multiselect"] = [
            step
            for step, enabled in dict(ablation_config).items()
            if not bool(enabled)
        ]

    return True, payload


def _mark_builder_autonomous_runtime_started(
    *,
    model: str,
    ollama_host: str,
    requested_source_mode: str,
    auto_market_pick: bool,
    resume_ui_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    existing_runtime = _load_autonomous_runtime_state()
    current_run_id = str(
        st.session_state.get(_BUILDER_AUTONOMOUS_RUN_ID_STATE_KEY, "") or ""
    ).strip()
    existing_run_id = str(existing_runtime.get("run_id", "") or "").strip()
    same_claim = (
        bool(existing_runtime.get("active"))
        and current_run_id
        and existing_run_id == current_run_id
        and _runtime_claim_owned_by_current_process(existing_runtime)
    )
    now = _utc_now_iso()
    if same_claim:
        runtime = dict(existing_runtime)
        runtime["last_resume_at"] = now
        runtime["resume_count"] = int(runtime.get("resume_count", 0) or 0) + 1
    else:
        runtime = _default_autonomous_runtime_state()
        runtime["run_id"] = _new_autonomous_run_id()
        runtime["claim_source"] = "streamlit"
        runtime["claim_reason"] = "autonomous_start"
        runtime["started_at"] = now
        st.session_state[_BUILDER_AUTONOMOUS_RUN_ID_STATE_KEY] = runtime["run_id"]
        try:
            reset_live_stream(
                path=STREAM_FILE,
                reason=f"autonomous_runtime_started:{runtime['run_id']}",
            )
        except Exception:
            logger.debug("builder_live_stream_reset_on_runtime_start_failed", exc_info=True)
    runtime["active"] = True
    runtime["manual_stop"] = False
    runtime.update(_current_runtime_owner_fields())
    runtime["last_heartbeat_at"] = now
    runtime["last_event"] = "autonomous_started"
    runtime["last_error"] = ""
    runtime["last_stop_reason"] = ""
    runtime["last_progress_at"] = now
    runtime["last_progress_event"] = "session_start"
    runtime["last_progress_phase"] = "initialisation"
    runtime["last_progress_iteration"] = 0
    runtime["model"] = str(model or "")
    runtime["ollama_host"] = str(ollama_host or "")
    runtime["requested_source_mode"] = str(requested_source_mode or "")
    runtime["effective_source_mode"] = ""
    runtime["auto_market_pick"] = bool(auto_market_pick)
    runtime["resume_ui_state"] = (
        dict(resume_ui_state) if isinstance(resume_ui_state, dict) else {}
    )
    runtime.update(_collect_autonomous_runtime_process_metrics())
    _save_autonomous_runtime_state(runtime)
    return runtime


def _heartbeat_builder_autonomous_runtime(**updates: Any) -> Dict[str, Any]:
    runtime = _load_autonomous_runtime_state()
    if bool(runtime.get("active")) and not _runtime_claim_owned_by_current_process(runtime):
        logger.debug(
            "builder_autonomous_heartbeat_skipped_foreign_claim run_id=%s owner_pid=%s",
            runtime.get("run_id", ""),
            runtime.get("owner_pid", runtime.get("pid", 0)),
        )
        return runtime
    runtime["last_heartbeat_at"] = _utc_now_iso()
    runtime.update(_collect_autonomous_runtime_process_metrics())
    runtime.update(_current_runtime_owner_fields())
    for key, value in updates.items():
        if key in runtime:
            runtime[key] = value
    _save_autonomous_runtime_state(runtime)
    return runtime


def mark_builder_autonomous_runtime_stopped(
    *,
    reason: str,
    manual_stop: bool = False,
    error: str = "",
) -> Dict[str, Any]:
    runtime = _load_autonomous_runtime_state()
    if (
        bool(runtime.get("active"))
        and not bool(manual_stop)
        and not _runtime_claim_owned_by_current_process(runtime)
    ):
        logger.debug(
            "builder_autonomous_stop_skipped_foreign_claim reason=%s run_id=%s",
            reason,
            runtime.get("run_id", ""),
        )
        return runtime
    runtime["active"] = False
    runtime["manual_stop"] = bool(manual_stop)
    runtime["last_heartbeat_at"] = _utc_now_iso()
    runtime["last_event"] = "autonomous_stopped"
    runtime["last_stop_reason"] = str(reason or "")
    runtime["last_error"] = str(error or "")
    runtime["current_session_num"] = 0
    runtime["current_session_id"] = ""
    runtime.update(_collect_autonomous_runtime_process_metrics())
    _save_autonomous_runtime_state(runtime)
    if runtime.get("run_id") == st.session_state.get(_BUILDER_AUTONOMOUS_RUN_ID_STATE_KEY):
        st.session_state.pop(_BUILDER_AUTONOMOUS_RUN_ID_STATE_KEY, None)
    return runtime


def _count_tail_history_statuses(
    history: List[Dict[str, Any]],
    statuses: set[str],
    *,
    limit: int = 8,
) -> int:
    count = 0
    for item in reversed(list(history or [])[-limit:]):
        status = str(item.get("status", "") or "").strip().lower()
        if status not in statuses:
            break
        count += 1
    return count


def _get_autonomous_recap_status_badge(entry: Dict[str, Any]) -> Dict[str, str]:
    """Détermine le badge affiché dans le récapitulatif Builder autonome."""
    status = str(entry.get("status", "") or "").strip().lower()
    best_return_pct = _safe_optional_float(
        entry.get("best_return")
        if entry.get("best_return") is not None
        else entry.get("best_return_pct")
    )
    final_return_pct = _safe_optional_float(
        entry.get("final_return")
        if entry.get("final_return") is not None
        else entry.get("final_return_pct")
    )
    known_returns = [
        value for value in (best_return_pct, final_return_pct)
        if value is not None
    ]

    primary_badges = {
        "success": {"icon": "✚", "label": "succes", "tone": "positive"},
        "max_iterations": {"icon": "⏱️", "label": "max_iterations", "tone": "neutral"},
        "running": {"icon": "…", "label": "en cours", "tone": "neutral"},
    }
    if status in primary_badges:
        return primary_badges[status]

    if any(value > 0.0 for value in known_returns):
        return {"icon": "+", "label": "positif", "tone": "positive"}

    if any(value < 0.0 for value in known_returns):
        return {"icon": "−", "label": "negatif", "tone": "negative"}

    fallback_badges = {
        "failed": {"icon": "✖", "label": "echec", "tone": "crash"},
        "error": {"icon": "✖", "label": "erreur", "tone": "crash"},
        "crash": {"icon": "✖", "label": "crash", "tone": "crash"},
    }
    return fallback_badges.get(
        status, {"icon": "?", "label": status or "inconnu", "tone": "neutral"}
    )


def _session_iteration_metrics(iteration: Any) -> tuple[Optional[Dict[str, Any]], Any]:
    backtest_result = getattr(iteration, "backtest_result", None)
    metrics = getattr(backtest_result, "metrics", None)
    return (
        metrics if isinstance(metrics, dict) else None,
        getattr(iteration, "iteration", None),
    )


def _get_autonomous_session_best_return_snapshot(session: Any) -> Dict[str, Any]:
    """Extrait la meilleure itération par return pour le récap autonome."""
    best_return: Optional[float] = None
    best_snapshot: Dict[str, Any] = _snapshot_from_metrics("best", None)

    for iteration in list(getattr(session, "iterations", []) or []):
        metrics, iteration_num = _session_iteration_metrics(iteration)
        if metrics is None:
            continue
        current_return = _safe_optional_float(metrics.get("total_return_pct"))
        if current_return is None:
            continue
        if best_return is None or current_return > best_return:
            best_return = current_return
            best_snapshot = _snapshot_from_metrics(
                "best", metrics, iteration=iteration_num,
            )

    if best_return is not None:
        return best_snapshot

    best_iteration = getattr(session, "best_iteration", None)
    best_metrics, best_iteration_num = _session_iteration_metrics(best_iteration)
    return _snapshot_from_metrics(
        "best", best_metrics, iteration=best_iteration_num,
    )


def _get_autonomous_session_final_snapshot(session: Any) -> Dict[str, Any]:
    """Extrait les métriques de la dernière itération backtestée de la session."""
    for iteration in reversed(list(getattr(session, "iterations", []) or [])):
        metrics, iteration_num = _session_iteration_metrics(iteration)
        if metrics is None:
            continue
        return _snapshot_from_metrics(
            "final", metrics, iteration=iteration_num,
        )

    best_iteration = getattr(session, "best_iteration", None)
    best_metrics, best_iteration_num = _session_iteration_metrics(best_iteration)
    return _snapshot_from_metrics(
        "final", best_metrics, iteration=best_iteration_num,
    )


def _choose_autonomous_objective_mode(
    requested_mode: str,
    history: List[Dict[str, Any]],
    supervisor: Dict[str, Any],
) -> Dict[str, Any]:
    forced_mode = str(supervisor.get("forced_source_mode", "") or "").strip().lower()
    if forced_mode in _AUTONOMOUS_SOURCE_MODES:
        return {"mode": forced_mode, "reason": "forced_recovery_mode"}

    recent = list(history or [])[-8:]
    crash_streak = _count_tail_history_statuses(recent, {"crash", "error"})
    failure_streak = _count_tail_history_statuses(
        recent,
        {"failed", "crash", "error"},
    )
    last_error_origin = str(supervisor.get("last_error_origin", "") or "").strip().lower()

    # Raised thresholds: gemma4:26b and other local-LLM models can timeout
    # transiently. A single bad session shouldn't pin the autonomous market
    # picker into deterministic fallback for the rest of the run.
    if (
        int(supervisor.get("consecutive_errors", 0) or 0) >= 3
        or failure_streak >= 5
        or crash_streak >= 3
    ):
        if requested_mode == "llm" and last_error_origin not in {"llm_runtime", "objective_generation"}:
            return {"mode": "llm", "reason": "llm_preferred_non_llm_incident"}
        return {"mode": "fallback", "reason": "recovery_fallback"}

    if requested_mode not in _AUTONOMOUS_SOURCE_MODES:
        requested_mode = "llm"
    return {"mode": requested_mode, "reason": "requested"}


def _resolve_autonomous_auto_market_pick(
    requested_auto_market_pick: bool,
    supervisor: Dict[str, Any],
) -> Dict[str, Any]:
    if not requested_auto_market_pick:
        return {"enabled": False, "reason": "requested_off"}
    if supervisor.get("disable_auto_market_pick_once"):
        return {"enabled": False, "reason": "recovery_guard_once"}
    return {"enabled": True, "reason": "requested_on"}


def _classify_autonomous_failure_origin(
    error: BaseException,
    traceback_text: str = "",
) -> str:
    text = f"{type(error).__name__}: {error}\n{traceback_text}".lower()
    if (
        "exact_name_rejected_by_host" in text
        or "cloud_model_not_exposed_by_current_host" in text
        or "rejette le nom exact" in text
        or "n'est pas exposé par l'hôte local" in text
        or "aucun nom exact du pool" in text
    ):
        return "llm_runtime_model_name_mismatch"
    if "streamlitapiexception" in text or "script run context" in text:
        return "streamlit_ui"
    if "ollama" in text or "httpx" in text or "timeout" in text or "connection" in text:
        return "llm_runtime"
    if "load_ohlcv" in text or "market selection" in text:
        return "market_selection"
    if "dataframe" in text or "parquet" in text or "csv" in text:
        return "data_loading"
    if "strategy_builder.py" in text or "builder_" in text:
        return "builder_backend"
    return "unexpected"


def _plan_autonomous_recovery(
    origin: str,
    history: List[Dict[str, Any]],
    supervisor: Dict[str, Any],
    *,
    current_source_mode: str,
) -> Dict[str, Any]:
    soft_reset_count = int(supervisor.get("soft_reset_count", 0) or 0)
    recent_soft_reset_count = len(_recent_soft_reset_timestamps(supervisor))
    if recent_soft_reset_count >= _AUTONOMOUS_MAX_SOFT_RESETS:
        return {
            "recover": True,
            "reason": "soft_reset_budget_hardened_recovery",
            "force_source_mode": "fallback",
            "disable_auto_market_pick_once": True,
            "cooldown_multiplier": _AUTONOMOUS_HARDENED_COOLDOWN_MULTIPLIER,
            "hardened_recovery": True,
        }

    plan = {
        "recover": True,
        "reason": origin,
        "force_source_mode": "",
        "disable_auto_market_pick_once": False,
        "cooldown_multiplier": min(5, max(2, soft_reset_count + 2)),
        "hardened_recovery": False,
    }

    if origin in {"llm_runtime", "objective_generation"}:
        plan["reason"] = "llm_recovery_retry_llm"
        # Don't pin the picker into fallback after a single LLM hiccup —
        # the next session retries the LLM picker (with shorter timeout).
        plan["force_source_mode"] = "llm" if soft_reset_count < 2 else "fallback"
    elif origin in {"market_selection", "data_loading"}:
        plan["reason"] = "market_recovery_disable_auto_pick"
        plan["disable_auto_market_pick_once"] = True
        plan["force_source_mode"] = current_source_mode if current_source_mode in _AUTONOMOUS_SOURCE_MODES else "llm"
    elif origin == "session_failed":
        if current_source_mode == "llm":
            plan["reason"] = "session_failed_fallback_simple"
            plan["force_source_mode"] = "fallback"
        else:
            plan["reason"] = "session_failed_retry_llm"
            plan["force_source_mode"] = "llm"
    elif origin in {"builder_backend", "streamlit_ui", "unexpected"}:
        plan["reason"] = f"{origin}_reset_source"
        plan["force_source_mode"] = "fallback" if current_source_mode == "llm" else "llm"

    return plan


def _apply_autonomous_supervisor_recovery(
    supervisor: Dict[str, Any],
    history: List[Dict[str, Any]],
    *,
    origin: str,
    current_source_mode: str,
) -> Dict[str, Any]:
    plan = _plan_autonomous_recovery(
        origin,
        history,
        supervisor,
        current_source_mode=current_source_mode,
    )
    if not plan.get("recover"):
        return plan

    supervisor["soft_reset_count"] = int(supervisor.get("soft_reset_count", 0) or 0) + 1
    recent_timestamps = _recent_soft_reset_timestamps(supervisor)
    recent_timestamps.append(_utc_now_iso())
    supervisor["soft_reset_timestamps"] = recent_timestamps
    supervisor["consecutive_errors"] = 0
    supervisor["consecutive_failed_sessions"] = 0
    supervisor["last_error_origin"] = origin
    supervisor["last_recovery_reason"] = str(plan.get("reason", "") or "")
    supervisor["forced_source_mode"] = str(plan.get("force_source_mode", "") or "")
    supervisor["disable_auto_market_pick_once"] = bool(
        plan.get("disable_auto_market_pick_once")
    )
    supervisor["last_resume_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    supervisor["next_pause_multiplier"] = int(plan.get("cooldown_multiplier", 1) or 1)
    return plan


def _render_iterations_compact_table(session: Any) -> None:
    """Résumé compact des itérations en une seule table dans un expander fermé."""
    iterations = getattr(session, "iterations", []) or []
    if not iterations:
        return

    decision_icons = {"accept": "✅", "stop": "🛑"}
    rows = []
    for it in iterations:
        it_num = getattr(it, "iteration", 0)
        decision = getattr(it, "decision", "")
        error = getattr(it, "error", None)
        bt = getattr(it, "backtest_result", None)
        metrics = getattr(bt, "metrics", None) if bt is not None else None
        icon = "❌" if error else decision_icons.get(decision, "🔄")
        row: Dict[str, Any] = {
            "#": it_num,
            "": icon,
            "Sharpe": float(metrics.get("sharpe_ratio", 0) or 0) if isinstance(metrics, dict) else None,
            "Return %": float(metrics.get("total_return_pct", 0) or 0) if isinstance(metrics, dict) else None,
            "Max DD %": float(metrics.get("max_drawdown_pct", 0) or 0) if isinstance(metrics, dict) else None,
            "Trades": int(metrics.get("total_trades", 0) or 0) if isinstance(metrics, dict) else None,
            "PF": float(metrics.get("profit_factor", 0) or 0) if isinstance(metrics, dict) else None,
            "Type": str(getattr(it, "change_type", "") or ""),
        }
        rows.append(row)

    n = len(rows)
    with st.expander(f"📋 Historique des itérations ({n})", expanded=False):
        st.dataframe(rows, hide_index=True, use_container_width=True)


def render_iteration_card(
    iteration: Any,
    *,
    expanded: bool = False,
) -> None:
    """Affiche un résumé compact d'une itération du builder."""
    it_num = iteration.iteration
    decision = getattr(iteration, "decision", "")
    error = getattr(iteration, "error", None)
    diag = getattr(iteration, "diagnostic_detail", {}) or {}
    phase_feedback = getattr(iteration, "phase_feedback", {}) or {}
    provenance = _get_builder_code_provenance_badge(phase_feedback)

    # Icône selon résultat
    if error:
        icon = "❌"
        label = f"Itération {it_num} — Erreur"
    elif decision == "accept":
        icon = "✅"
        label = f"Itération {it_num} — Acceptée"
    elif decision == "stop":
        icon = "🛑"
        label = f"Itération {it_num} — Arrêt"
    else:
        icon = "🔄"
        label = f"Itération {it_num} — Continue"

    # Diagnostic badge + type de modification
    diag_cat = getattr(iteration, "diagnostic_category", "")
    change_type = getattr(iteration, "change_type", "")
    severity = diag.get("severity", "")

    sev_icons = {
        "critical": "🔴", "warning": "🟡",
        "info": "🔵", "success": "🟢",
    }
    type_labels = {
        "logic": "🔀 Logique",
        "params": "🎛️ Paramètres",
        "both": "🔀🎛️ Logique + Params",
        "accept": "✅ Acceptation",
    }
    sev_icon = sev_icons.get(severity, "⚪")
    type_lbl = type_labels.get(change_type, "")
    cat_lbl = diag_cat.replace("_", " ").title() if diag_cat else ""

    st.markdown(f"**{icon} {label}**")

    badge_labels: List[str] = []
    if cat_lbl:
        badge_labels.append(f"{sev_icon} {cat_lbl}")
    if type_lbl:
        badge_labels.append(type_lbl)
    if decision:
        badge_labels.append(f"Decision: {decision}")
    if provenance.get("badge"):
        badge_labels.append(provenance["badge"])
    _render_builder_badge_row(badge_labels)

    hypothesis = str(getattr(iteration, "hypothesis", "") or "").strip()
    if hypothesis:
        st.caption(f"Hypothèse: {hypothesis}")

    provenance_detail = str(provenance.get("detail", "") or "").strip()
    if provenance_detail:
        st.caption(f"Origine des statistiques: {provenance_detail}")

    if error:
        st.error(f"Erreur: {error}")

    bt = getattr(iteration, "backtest_result", None)
    metrics = getattr(bt, "metrics", None) if bt is not None else None
    backtest_feedback = phase_feedback.get("backtest", {}) or {}
    if isinstance(metrics, dict):
        summary_parts = [
            f"Sharpe `{float(metrics.get('sharpe_ratio', 0.0) or 0.0):.3f}`",
            f"Return `{float(metrics.get('total_return_pct', 0.0) or 0.0):+.2f}%`",
            f"Max DD `{float(metrics.get('max_drawdown_pct', 0.0) or 0.0):.2f}%`",
            f"Trades `{int(metrics.get('total_trades', 0) or 0)}`",
            f"PF `{float(metrics.get('profit_factor', 0.0) or 0.0):.2f}`",
            f"Win Rate `{float(metrics.get('win_rate_pct', 0.0) or 0.0):.1f}%`",
        ]
        st.markdown(" | ".join(summary_parts))
        if isinstance(backtest_feedback, dict) and backtest_feedback.get("mode") == "sweep":
            total_tested = int(backtest_feedback.get("sweep_total_tested", 0) or 0)
            success_count = int(backtest_feedback.get("sweep_success", 0) or 0)
            failed_count = int(backtest_feedback.get("sweep_failed", 0) or 0)
            params_used = backtest_feedback.get("params_used", {}) or {}
            st.caption(
                f"Sweep Builder: {success_count}/{total_tested} combinaisons valides"
                + (f" ({failed_count} échecs)" if failed_count else "")
            )
            if isinstance(params_used, dict) and params_used:
                st.caption(
                    "Paramètres retenus: "
                    + json.dumps(params_used, ensure_ascii=False, sort_keys=True)
                )

    analysis = str(getattr(iteration, "analysis", "") or "").strip()
    if analysis:
        st.caption(f"Analyse: {analysis[:240]}")

    st.markdown("---")


def render_session_summary(session: Any) -> None:
    """Affiche le résumé final de la session builder."""
    status = getattr(session, "status", "unknown")
    best_sharpe_raw = getattr(session, "best_sharpe", None)
    n_iters = len(getattr(session, "iterations", []))

    # Statut global
    status_map = {
        "success": ("🏆", "Stratégie acceptée"),
        "max_iterations": ("⏱️", "Itérations max atteintes"),
        "failed": ("❌", "Échec - aucune stratégie viable"),
        "running": ("🔄", "En cours..."),
    }
    icon, label = status_map.get(status, ("❓", status))

    st.markdown(f"### {icon} {label}")
    sharpe_txt = _format_optional_float(best_sharpe_raw, "{:.3f}")
    model_name_display = str(getattr(session, "model_name", "") or "")
    gen_stats = compute_session_generation_stats(session) if hasattr(session, "iterations") else {}
    canonical_rate = gen_stats.get("canonical_rate")
    canonical_pct_txt = f"{canonical_rate * 100:.0f}%" if canonical_rate is not None else "n/a"
    model_info = f" | **Modèle:** {model_name_display}" if model_name_display else ""
    st.markdown(
        f"**Itérations:** {n_iters} | **Meilleur Sharpe:** {sharpe_txt}"
        f"{model_info} | **LLM canonique:** {canonical_pct_txt}"
    )

    auto_resets = int(getattr(session, "auto_reset_count", 0) or 0)
    if auto_resets:
        st.caption(f"Auto-resets session: {auto_resets}")

    # Synthèse orchestration: réalignements et overrides
    total_realign = 0
    stop_overrides = 0
    accept_overrides = 0
    for it in getattr(session, "iterations", []):
        fb = getattr(it, "phase_feedback", {}) or {}
        total_realign += int((fb.get("proposal", {}) or {}).get("realign_attempts", 0))
        total_realign += int((fb.get("code", {}) or {}).get("realign_attempts", 0))
        dec_fb = fb.get("decision", {}) or {}
        stop_overrides += 1 if dec_fb.get("stop_overridden") else 0
        accept_overrides += 1 if dec_fb.get("accept_overridden") else 0

    if total_realign or stop_overrides or accept_overrides:
        st.caption(
            "Orchestration: "
            f"realignements={total_realign} | "
            f"stop_overrides={stop_overrides} | "
            f"accept_overrides={accept_overrides}"
        )

    # Détails du meilleur résultat
    best = getattr(session, "best_iteration", None)
    if best and hasattr(best, "backtest_result") and best.backtest_result:
        metrics = best.backtest_result.metrics
        best_phase_feedback = getattr(best, "phase_feedback", {}) or {}
        provenance = _get_builder_code_provenance_badge(best_phase_feedback)
        st.markdown("#### 🥇 Meilleur résultat")
        if provenance.get("badge"):
            _render_builder_badge_row([provenance["badge"]])
        provenance_detail = str(provenance.get("detail", "") or "").strip()
        if provenance_detail:
            st.caption(f"Origine du meilleur résultat: {provenance_detail}")

        best_backtest_feedback = best_phase_feedback.get("backtest", {}) or {}
        if (
            isinstance(best_backtest_feedback, dict)
            and best_backtest_feedback.get("mode") == "sweep"
        ):
            total_tested = int(best_backtest_feedback.get("sweep_total_tested", 0) or 0)
            params_used = best_backtest_feedback.get("params_used", {}) or {}
            st.caption(f"Meilleur résultat sélectionné via sweep ({total_tested} combinaisons).")
            if isinstance(params_used, dict) and params_used:
                st.caption(
                    "Paramètres gagnants: "
                    + json.dumps(params_used, ensure_ascii=False, sort_keys=True)
                )

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Sharpe", f"{metrics.get('sharpe_ratio', 0):.3f}")
        with col2:
            st.metric("Return", f"{metrics.get('total_return_pct', 0):+.2f}%")
        with col3:
            st.metric("Max DD", f"{metrics.get('max_drawdown_pct', 0):.2f}%")
        with col4:
            st.metric("Win Rate", f"{metrics.get('win_rate_pct', 0):.1f}%")
        with col5:
            st.metric("PF", f"{metrics.get('profit_factor', 0):.2f}")

        # Hypothèse gagnante
        hyp = getattr(best, "hypothesis", "")
        if hyp:
            st.info(f"Hypothèse gagnante: {hyp}")

        # Code final
        code = getattr(best, "code", "")
        if code:
            with st.expander("📝 Code de la stratégie gagnante", expanded=False):
                st.code(code, language="python")

    # Chemin sandbox
    session_dir = getattr(session, "session_dir", None)
    if session_dir:
        st.caption(f"📁 Fichiers de session: `{session_dir}`")


def _resolve_builder_flow_analysis_payload(session: Any) -> Dict[str, Any]:
    payload = {
        "builder_execution_mode": str(
            getattr(session, "builder_execution_mode", "") or ""
        ),
        "orchestration_mode": str(
            getattr(session, "orchestration_mode", "") or ""
        ),
        "instrumentation_enabled": bool(
            getattr(session, "instrumentation_enabled", False)
        ),
        "instrumentation_summary": (
            dict(getattr(session, "instrumentation_summary", {}) or {})
            if isinstance(getattr(session, "instrumentation_summary", {}), dict)
            else {}
        ),
        "ablation_config": (
            dict(getattr(session, "ablation_config", {}) or {})
            if isinstance(getattr(session, "ablation_config", {}), dict)
            else {}
        ),
        "pipeline_traces_path": str(
            getattr(session, "pipeline_traces_path", "") or ""
        ),
    }
    session_dir = getattr(session, "session_dir", None)
    if not session_dir:
        return payload
    summary_path = Path(session_dir) / "session_summary.json"
    if not summary_path.exists():
        return payload
    try:
        persisted_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return payload
    if not payload["builder_execution_mode"]:
        payload["builder_execution_mode"] = str(
            persisted_summary.get("builder_execution_mode", "") or ""
        )
    if not payload["orchestration_mode"]:
        payload["orchestration_mode"] = str(
            persisted_summary.get("orchestration_mode", "") or ""
        )
    if not payload["instrumentation_enabled"]:
        payload["instrumentation_enabled"] = bool(
            persisted_summary.get("instrumentation_enabled", False)
        )
    if not payload["instrumentation_summary"] and isinstance(
        persisted_summary.get("instrumentation_summary"), dict
    ):
        payload["instrumentation_summary"] = dict(
            persisted_summary.get("instrumentation_summary", {}) or {}
        )
    if not payload["ablation_config"] and isinstance(
        persisted_summary.get("ablation_config"), dict
    ):
        payload["ablation_config"] = dict(
            persisted_summary.get("ablation_config", {}) or {}
        )
    if not payload["pipeline_traces_path"]:
        payload["pipeline_traces_path"] = str(
            persisted_summary.get("pipeline_traces_path", "") or ""
        )
    return payload


def _clone_json_compatible(payload: Any) -> Any:
    try:
        return json.loads(json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:
        return payload


def _read_builder_source_value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _read_builder_source_dict(source: Any, name: str) -> Dict[str, Any]:
    value = _read_builder_source_value(source, name, {})
    return dict(value or {}) if isinstance(value, dict) else {}


def _read_builder_source_list(source: Any, name: str) -> List[Any]:
    value = _read_builder_source_value(source, name, [])
    return list(value or []) if isinstance(value, list) else []


def _load_builder_summary_payload(source: Any) -> Dict[str, Any]:
    session_dir = _read_builder_source_value(source, "session_dir", None)
    if not session_dir:
        return {}
    summary_path = Path(session_dir) / "session_summary.json"
    if not summary_path.exists():
        return {}
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _persist_builder_session_summary_patch(
    session: Any,
    patch: Dict[str, Any],
) -> None:
    session_dir = getattr(session, "session_dir", None)
    if not session_dir or not isinstance(patch, dict) or not patch:
        return

    summary_path = Path(session_dir) / "session_summary.json"
    if not summary_path.exists():
        return

    try:
        current_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("builder_session_summary_patch_load_failed session=%s error=%s", session_dir, exc)
        return
    if not isinstance(current_summary, dict):
        current_summary = {}

    current_summary.update(_clone_json_compatible(patch))
    serialized = json.dumps(current_summary, indent=2, ensure_ascii=False, default=str)

    with _BUILDER_SESSION_SUMMARY_PATCH_LOCK:
        tmp_path = _build_unique_autonomous_tmp_path(summary_path)
        try:
            tmp_path.write_text(serialized, encoding="utf-8")
            os.replace(tmp_path, summary_path)
        except Exception as exc:
            _cleanup_autonomous_tmp_file(tmp_path)
            logger.warning(
                "builder_session_summary_patch_save_failed session=%s error=%s",
                session_dir,
                exc,
            )


def _render_builder_flow_analysis_panel(session: Any) -> None:
    payload = _resolve_builder_flow_analysis_payload(session)
    summary = payload.get("instrumentation_summary") or {}
    execution_mode = str(payload.get("builder_execution_mode") or "")
    instrumentation_enabled = bool(payload.get("instrumentation_enabled"))

    st.markdown("#### Analyse du flux Builder")
    st.caption(
        "Lecture orientée produit du pipeline Builder: ce qui bloque, ce qui aide, "
        "et où comparer deux sessions instrumentées."
    )

    if not instrumentation_enabled or not isinstance(summary, dict) or not summary:
        st.info(
            "Aucune trace disponible pour cette session. Active `Activer l'analyse de flux sur le prochain run` "
            "dans l'onglet `Modèles & runtime`, puis relance un Builder."
        )
        return

    if execution_mode and execution_mode != BUILDER_EXECUTION_MODE_MONO:
        st.caption(
            "La lecture détaillée dans l'interface est optimisée pour le Builder mono-LLM."
        )

    metric_cols = st.columns(6)
    metric_cols[0].metric(
        "Temps / itération",
        f"{_safe_numeric_float(summary.get('avg_iteration_sec'), 0.0):.2f}s",
    )
    metric_cols[1].metric(
        "Fallback",
        f"{_safe_numeric_float(summary.get('fallback_rate'), 0.0) * 100:.1f}%",
    )
    metric_cols[2].metric(
        "Réparation",
        f"{_safe_numeric_float(summary.get('repair_rate'), 0.0) * 100:.1f}%",
    )
    metric_cols[3].metric(
        "Runtime fix",
        int(summary.get("runtime_fix_count", 0) or 0),
    )
    metric_cols[4].metric(
        "Préchecks bloquants",
        int(summary.get("precheck_skip_count", 0) or 0),
    )
    metric_cols[5].metric(
        "Stagnation",
        int(summary.get("stagnation_count", 0) or 0),
    )

    blockers = list(summary.get("blockers", []) or [])
    helpers = list(summary.get("helpers", []) or [])
    blocker_text = ", ".join(
        f"{item.get('kind')} ({int(item.get('count', 0) or 0)})"
        for item in blockers[:5]
        if isinstance(item, dict)
    )
    helper_text = ", ".join(
        f"{item.get('kind')} ({int(item.get('count', 0) or 0)})"
        for item in helpers[:5]
        if isinstance(item, dict)
    )

    st.markdown("**Qu’est-ce qui bloque ?**")
    st.caption(
        blocker_text or "Aucun frein récurrent n'a dominé cette session instrumentée."
    )
    st.markdown("**Qu’est-ce qui aide ?**")
    st.caption(
        helper_text or "Aucune aide récurrente n'a eu besoin de compenser fortement le flux."
    )
    st.markdown("**Où le flux diverge ?**")
    st.caption(
        "Utilise la comparaison de sessions dans l’explorateur des sessions Builder pour isoler la phase racine "
        "entre deux runs instrumentés du même mode."
    )

    with st.expander("Chronologie de session", expanded=False):
        phase_totals = dict(summary.get("phase_totals_sec", {}) or {})
        phase_counts = dict(summary.get("phase_counts", {}) or {})
        phase_errors = dict(summary.get("phase_errors", {}) or {})
        phase_avg = dict(summary.get("phase_avg_sec", {}) or {})
        phase_rows = [
            {
                "phase": phase,
                "temps_total_s": _safe_numeric_float(phase_totals.get(phase), 0.0),
                "temps_moyen_s": _safe_numeric_float(phase_avg.get(phase), 0.0),
                "occurrences": int(phase_counts.get(phase, 0) or 0),
                "erreurs": int(phase_errors.get(phase, 0) or 0),
            }
            for phase in sorted(set(phase_totals) | set(phase_counts) | set(phase_errors))
        ]
        if phase_rows:
            st.dataframe(phase_rows, width="stretch", hide_index=True)
        else:
            st.caption("Aucune chronologie détaillée disponible pour cette session.")

    with st.expander("Vue avancée", expanded=False):
        disabled_steps = [
            step
            for step, enabled in dict(payload.get("ablation_config", {}) or {}).items()
            if not enabled
        ]
        st.caption(
            "Ablation active: "
            + (", ".join(disabled_steps) if disabled_steps else "aucune, pipeline complet")
        )
        traces_path = str(payload.get("pipeline_traces_path", "") or "")
        if traces_path:
            st.caption(f"Trace détaillée: `{traces_path}`")
        st.json(summary)


# ---------------------------------------------------------------------------
# Warmup Ollama — préchargement du modèle en VRAM
# ---------------------------------------------------------------------------

def _is_local_ollama_host(ollama_host: str) -> bool:
    """Retourne True si l'host Ollama est local (localhost/127.0.0.1/0.0.0.0)."""
    try:
        parsed = urlparse(_normalize_ollama_host(ollama_host))
        host = (parsed.hostname or "").lower()
        return host in {"127.0.0.1", "localhost", "0.0.0.0"}
    except Exception:
        return False


def _normalize_ollama_host(ollama_host: str) -> str:
    host = str(ollama_host or "").strip()
    if not host:
        return "http://127.0.0.1:11434"
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host.rstrip("/")


def _resolve_single_llm_runtime_route(
    ollama_host: str,
    llm_topology_config: Any = None,
) -> tuple[str, str]:
    """Résout la route mono-LLM effective depuis la topologie UI."""
    fallback_host = _normalize_ollama_host(ollama_host)
    try:
        if isinstance(llm_topology_config, LLMTopologyConfig):
            topology = llm_topology_config
        elif isinstance(llm_topology_config, dict):
            topology = LLMTopologyConfig.from_dict(llm_topology_config)
        else:
            return fallback_host, ""
        route = topology.resolve_builder_phase_route(
            "default",
            fallback_host=fallback_host,
        )
        resolved_host = _normalize_ollama_host(
            str(getattr(route, "ollama_host", "") or fallback_host)
        )
        resolved_gpu_target = str(getattr(route, "gpu_target", "") or "").strip()
        return resolved_host, resolved_gpu_target
    except Exception:
        return fallback_host, ""


def _model_matches(model_name: str, requested_model: str) -> bool:
    """Matching contrôlé entre nom demandé et liste Ollama.

    Ne doit jamais confondre deux variantes de tailles différentes
    comme `qwen3-coder:480b` et `qwen3-coder:30b`.
    """
    model_name_l = str(model_name or "").strip().lower()
    requested_l = str(requested_model or "").strip().lower()
    model_canonical = strip_ollama_cloud_model_alias(model_name_l)
    requested_canonical = strip_ollama_cloud_model_alias(requested_l)

    if not model_name_l or not requested_l:
        return False

    if model_canonical and requested_canonical and model_canonical == requested_canonical:
        return True

    if model_name_l == requested_l:
        return True

    model_size = _extract_model_size_b(model_name_l)
    requested_size = _extract_model_size_b(requested_l)
    if model_size > 0 and requested_size > 0 and model_size != requested_size:
        return False

    if ":" in model_name_l and ":" in requested_l:
        return False

    if model_name_l.startswith(requested_l):
        return True
    if requested_l.startswith(model_name_l):
        return True

    req_base = requested_l.split(":", 1)[0]
    model_base = model_name_l.split(":", 1)[0]
    if model_base == req_base:
        return True

    req_compact = re.sub(r"[^a-z0-9]", "", req_base)
    model_compact = re.sub(r"[^a-z0-9]", "", model_base)
    return bool(req_compact) and req_compact == model_compact


def _extract_model_size_b(model_name: str) -> float:
    """Extrait la taille d'un modèle en milliards de paramètres (ex: 32b)."""
    m = re.search(r"(\d+(?:\.\d+)?)b", model_name.lower())
    if not m:
        return -1.0
    try:
        return float(m.group(1))
    except Exception:
        return -1.0


def _is_cloud_only_model(model_name: str) -> bool:
    return bool(is_cloud_only_model(model_name) or is_ollama_cloud_model(model_name))


def _store_builder_runtime_acceptance_probe(payload: Dict[str, Any]) -> Dict[str, Any]:
    probe_payload = dict(payload or {})
    st.session_state["builder_runtime_acceptance_probe"] = probe_payload
    return probe_payload


def _resolve_cloud_runtime_model_alias(
    requested_model: str,
    tag_entries: List[Dict[str, Any]],
) -> tuple[str, str, bool]:
    requested = str(requested_model or "").strip()
    if not requested:
        return "", "Nom de modèle vide.", False
    if not _is_cloud_only_model(requested):
        return requested, "", False

    for entry in list(tag_entries or []):
        tag_name = str(entry.get("name", "") or "").strip()
        remote_model = str(entry.get("remote_model", "") or "").strip()
        if not tag_name:
            continue
        if remote_model and (
            _model_matches(remote_model, requested)
            or _model_matches(requested, remote_model)
        ):
            return (
                tag_name,
                f"Alias runtime cloud détecté pour `{requested}` -> `{tag_name}`.",
                True,
            )
        tag_name_l = tag_name.lower()
        requested_l = requested.lower()
        if tag_name_l == requested_l:
            return tag_name, "", True
        if tag_name_l.endswith("-cloud") and tag_name_l.startswith(requested_l):
            return (
                tag_name,
                f"Alias runtime cloud détecté pour `{requested}` -> `{tag_name}`.",
                True,
            )

    return (
        requested,
        (
            f"Modèle cloud-only `{requested}` transmis tel quel au runtime Ollama Cloud. "
            "Aucune substitution locale n'est autorisée."
        ),
        True,
    )


def _resolve_requested_model(
    requested_model: str,
    installed_models: List[str],
    *,
    allow_fallback: bool = False,
    tag_entries: List[Dict[str, Any]] | None = None,
) -> tuple[str, str, bool]:
    """Résout un modèle demandé vers un modèle installé."""
    if _is_cloud_only_model(requested_model):
        return _resolve_cloud_runtime_model_alias(
            requested_model,
            list(tag_entries or []),
        )

    if not installed_models:
        return requested_model, "Aucun modèle installé détecté.", False

    # 1) Match direct/normalisé
    for name in installed_models:
        if _model_matches(name, requested_model):
            return name, "", True

    if not allow_fallback:
        available_preview = ", ".join(installed_models[:5])
        if len(installed_models) > 5:
            available_preview += ", ..."
        return (
            requested_model,
            (
                f"Modèle `{requested_model}` absent sur cet Ollama. "
                f"Disponibles: {available_preview or 'aucun'}."
            ),
            False,
        )

    # 2) Match par taille (ex: 32b) pour garder un profil proche
    requested_size = _extract_model_size_b(requested_model)
    if requested_size > 0:
        same_size = [
            n for n in installed_models
            if _extract_model_size_b(n) == requested_size
        ]
        if same_size:
            return (
                same_size[0],
                (
                    f"Modèle `{requested_model}` absent. "
                    f"Fallback auto vers `{same_size[0]}` (taille {requested_size:.0f}B)."
                ),
                False,
            )

    # 3) Priorité à quelques modèles robustes si présents
    preferred = [
        "deepseek-r1-32b-local:latest",
        "deepseek-r1:32b",
        "qwq-32b-local:latest",
        "qwq:32b",
        "qwen3-48b-savant:latest",
    ]
    installed_lower = {m.lower(): m for m in installed_models}
    for pref in preferred:
        if pref.lower() in installed_lower:
            chosen = installed_lower[pref.lower()]
            return (
                chosen,
                f"Modèle `{requested_model}` absent. Fallback auto vers `{chosen}`.",
                False,
            )

    # 4) Dernier recours: premier installé
    return (
        installed_models[0],
        (
            f"Modèle `{requested_model}` absent. "
            f"Fallback auto vers `{installed_models[0]}`."
        ),
        False,
    )


def _is_model_loaded_in_ollama_ps(
    *,
    model: str,
    ollama_host: str,
    timeout: float = 6.0,
) -> tuple[bool, str]:
    """Vérifie via /api/ps si un modèle est déjà chargé en mémoire."""
    try:
        request_ctx = resolve_ollama_request_context(
            ollama_host,
            model_name=model,
        )
        runtime_host = str(request_ctx["effective_host"] or ollama_host).rstrip("/")
        runtime_model = str(request_ctx["request_model"] or model).strip() or model
        request_kwargs: Dict[str, Any] = {"timeout": timeout}
        headers = dict(request_ctx.get("headers", {}) or {})
        if headers:
            request_kwargs["headers"] = headers
        resp = httpx.get(f"{runtime_host}/api/ps", **request_kwargs)
        if resp.status_code != 200:
            return False, f"/api/ps status={resp.status_code}"
        payload = resp.json() if resp.content else {}
        models = payload.get("models", []) or []
        loaded_names = [
            str(item.get("name", "") or "").strip()
            for item in models
            if str(item.get("name", "") or "").strip()
        ]
        for loaded in loaded_names:
            if _model_matches(loaded, runtime_model):
                return True, f"modèle déjà chargé (`{loaded}`)"
        if loaded_names:
            return False, f"modèles actifs: {', '.join(loaded_names[:3])}"
        return False, "aucun modèle actif"
    except Exception as exc:
        return False, f"/api/ps inaccessible: {exc}"


def _warmup_ollama_model(
    *,
    model: str,
    ollama_host: str,
    keep_alive_minutes: int,
    timeout: float = 300.0,
) -> tuple[bool, str]:
    """Précharge un modèle Ollama en VRAM via un prompt court.

    Envoie un prompt minimal à /api/generate pour forcer le chargement
    du modèle en mémoire GPU avant les vrais appels LLM.

    Returns:
        (succès, détail).
    """
    keep_alive = format_ollama_keep_alive(keep_alive_minutes)
    request_ctx = resolve_ollama_request_context(
        ollama_host,
        model_name=model,
    )
    runtime_host = str(request_ctx["effective_host"] or ollama_host).rstrip("/")
    runtime_model = str(request_ctx["request_model"] or model).strip() or model
    try:
        request_kwargs: Dict[str, Any] = {"timeout": timeout}
        headers = dict(request_ctx.get("headers", {}) or {})
        if headers:
            request_kwargs["headers"] = headers
        resp = httpx.post(
            f"{runtime_host}/api/generate",
            json={
                "model": runtime_model,
                "prompt": "Ready.",
                "keep_alive": keep_alive,
                "stream": False,
            },
            **request_kwargs,
        )
        if resp.status_code == 200:
            done_reason = ""
            try:
                payload = resp.json() if resp.content else {}
                done_reason = str(payload.get("done_reason", "") or "").strip()
            except Exception:
                done_reason = ""
            detail = "warmup /api/generate status=200"
            if done_reason:
                detail += f", done_reason={done_reason}"
            return True, detail

        body = (resp.text or "").strip().replace("\n", " ")
        if len(body) > 300:
            body = body[:300] + "..."
        loaded, loaded_detail = _is_model_loaded_in_ollama_ps(
            model=runtime_model,
            ollama_host=runtime_host,
        )
        if loaded:
            return (
                True,
                f"warmup status={resp.status_code} mais {loaded_detail}",
            )
        return (
            False,
            f"warmup status={resp.status_code}, body={body or '<vide>'}, ps={loaded_detail}",
        )
    except httpx.TimeoutException:
        loaded, loaded_detail = _is_model_loaded_in_ollama_ps(
            model=runtime_model,
            ollama_host=runtime_host,
        )
        if loaded:
            return (
                True,
                f"timeout warmup ({int(timeout)}s) mais {loaded_detail}",
            )
        return (
            False,
            f"timeout warmup ({int(timeout)}s), ps={loaded_detail}",
        )
    except Exception as exc:
        loaded, loaded_detail = _is_model_loaded_in_ollama_ps(
            model=runtime_model,
            ollama_host=runtime_host,
        )
        if loaded:
            return (
                True,
                f"erreur warmup ({exc}) mais {loaded_detail}",
            )
        return (
            False,
            f"erreur warmup ({exc}), ps={loaded_detail}",
        )


def _unload_ollama_model(*, model: str, ollama_host: str, timeout: float = 20.0) -> bool:
    """Décharge un modèle Ollama de la mémoire."""
    try:
        request_ctx = resolve_ollama_request_context(
            ollama_host,
            model_name=model,
        )
        runtime_host = str(request_ctx["effective_host"] or ollama_host).rstrip("/")
        runtime_model = str(request_ctx["request_model"] or model).strip() or model
        request_kwargs: Dict[str, Any] = {"timeout": timeout}
        headers = dict(request_ctx.get("headers", {}) or {})
        if headers:
            request_kwargs["headers"] = headers
        resp = httpx.post(
            f"{runtime_host}/api/generate",
            json={
                "model": runtime_model,
                "prompt": "",
                "keep_alive": 0,
                "stream": False,
            },
            **request_kwargs,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _prepare_builder_llm(
    *,
    model: str,
    ollama_host: str,
    preload_model: bool,
    keep_alive_minutes: int,
    auto_start_ollama: bool,
    gpu_target: str | None = None,
    allow_model_fallback: bool = False,
) -> tuple[bool, str, str]:
    """Prépare Ollama + modèle pour le Strategy Builder (check + warmup)."""
    ollama_host = _normalize_ollama_host(ollama_host)
    request_ctx = resolve_ollama_request_context(
        ollama_host,
        model_name=model,
    )
    runtime_host = str(request_ctx["effective_host"] or ollama_host).rstrip("/")
    route_note = ""
    if runtime_host != ollama_host and bool(request_ctx.get("api_key_present")):
        route_note = (
            f"Routage direct Ollama Cloud activé via OLLAMA_API_KEY "
            f"({runtime_host})."
        )
    probe_payload: Dict[str, Any] = {
        "requested_model": str(model or "").strip(),
        "resolved_model": str(model or "").strip(),
        "ollama_host": runtime_host,
        "requested_ollama_host": ollama_host,
        "cloud_only": _is_cloud_only_model(model),
        "host_reachable": False,
        "present_in_tags": False,
        "accepted": False,
        "status": "pending",
        "message": "Préparation runtime en cours.",
        "tags_status_code": None,
        "runtime_status_code": None,
        "warmup_attempted": False,
        "warmup_ok": None,
        "warmup_detail": "",
    }
    if auto_start_ollama and _is_local_ollama_host(runtime_host):
        try:
            ok, msg = ensure_ollama_running(
                ollama_host=runtime_host,
                gpu_target=gpu_target,
                model_name=model,
            )
        except TypeError:
            ok, msg = ensure_ollama_running(ollama_host=runtime_host)
        if not ok:
            probe_payload.update(
                {
                    "status": "startup_failed",
                    "message": f"{route_note} {msg}".strip(),
                }
            )
            _store_builder_runtime_acceptance_probe(probe_payload)
            return False, f"{route_note} {msg}".strip(), model

    try:
        request_kwargs: Dict[str, Any] = {"timeout": 8.0}
        headers = dict(request_ctx.get("headers", {}) or {})
        if headers:
            request_kwargs["headers"] = headers
        tags = httpx.get(f"{runtime_host}/api/tags", **request_kwargs)
    except Exception as exc:
        probe_payload.update(
            {
                "status": "host_unreachable",
                "message": f"{route_note} Ollama inaccessible ({runtime_host}): {exc}".strip(),
            }
        )
        _store_builder_runtime_acceptance_probe(probe_payload)
        return False, f"{route_note} Ollama inaccessible ({runtime_host}): {exc}".strip(), model

    if tags.status_code != 200:
        probe_payload.update(
            {
                "status": "host_http_error",
                "message": (
                    f"{route_note} Ollama indisponible sur {runtime_host} "
                    f"(status={tags.status_code})"
                ).strip(),
                "tags_status_code": tags.status_code,
            }
        )
        _store_builder_runtime_acceptance_probe(probe_payload)
        return (
            False,
            (
                f"{route_note} Ollama indisponible sur {runtime_host} "
                f"(status={tags.status_code})"
            ).strip(),
            model,
        )

    try:
        tags_payload = tags.json()
    except Exception:
        tags_payload = {}
    tag_entries = list(tags_payload.get("models", []) or [])
    models = [m.get("name", "") for m in tag_entries if m.get("name")]
    probe_payload.update(
        {
            "host_reachable": True,
            "tags_status_code": tags.status_code,
        }
    )
    resolved_model, resolve_note, model_found = _resolve_requested_model(
        model,
        models,
        allow_fallback=allow_model_fallback,
        tag_entries=tag_entries,
    )
    probe_payload["resolved_model"] = resolved_model
    if not model_found:
        probe_payload.update(
            {
                "status": "local_model_missing",
                "message": resolve_note,
            }
        )
        _store_builder_runtime_acceptance_probe(probe_payload)
        return False, resolve_note, model

    if _is_cloud_only_model(resolved_model):
        acceptance_probe = probe_model_runtime_acceptance(
            resolved_model,
            requested_model=model,
            ollama_host=runtime_host,
            tags_payload=tags_payload,
            tags_status_code=tags.status_code,
        )
        acceptance_probe["cloud_only"] = True
        acceptance_probe["warmup_attempted"] = False
        acceptance_probe["warmup_ok"] = None
        acceptance_probe["warmup_detail"] = ""
        _store_builder_runtime_acceptance_probe(acceptance_probe)
        if not acceptance_probe.get("accepted"):
            return False, str(acceptance_probe.get("message") or resolve_note), resolved_model
        resolved_model = str(acceptance_probe.get("resolved_model") or resolved_model).strip() or resolved_model
        if resolved_model != str(model or "").strip():
            resolve_note = f"Alias runtime cloud local validé pour `{model}` -> `{resolved_model}`."
        probe_payload = acceptance_probe
    else:
        probe_payload.update(
            {
                "cloud_only": False,
                "present_in_tags": any(_model_matches(name, resolved_model) for name in models),
                "accepted": True,
                "status": "local_model_visible",
                "message": f"Le modèle `{resolved_model}` est visible sur {runtime_host} via /api/tags.",
            }
        )
        if not preload_model:
            acceptance_probe = probe_model_runtime_acceptance(
                resolved_model,
                requested_model=model,
                ollama_host=runtime_host,
                tags_payload=tags_payload,
                tags_status_code=tags.status_code,
            )
            acceptance_probe["cloud_only"] = False
            acceptance_probe["warmup_attempted"] = False
            acceptance_probe["warmup_ok"] = None
            acceptance_probe["warmup_detail"] = ""
            if resolve_note:
                acceptance_probe["message"] = (
                    f"{resolve_note} {str(acceptance_probe.get('message') or '').strip()}"
                ).strip()
            _store_builder_runtime_acceptance_probe(acceptance_probe)
            if not acceptance_probe.get("accepted"):
                return (
                    False,
                    str(acceptance_probe.get("message") or resolve_note or ""),
                    resolved_model,
                )
            probe_payload = acceptance_probe
        else:
            _store_builder_runtime_acceptance_probe(probe_payload)

    if not preload_model:
        msg = f"Ollama OK ({runtime_host}) — warmup désactivé."
        if resolve_note:
            msg = f"{resolve_note} {msg}"
        if route_note:
            msg = f"{route_note} {msg}".strip()
        probe_payload["message"] = f"{probe_payload.get('message', '').strip()} Warmup désactivé.".strip()
        _store_builder_runtime_acceptance_probe(probe_payload)
        return True, msg, resolved_model

    warmup_ok, warmup_detail = _warmup_ollama_model(
        model=resolved_model,
        ollama_host=runtime_host,
        keep_alive_minutes=keep_alive_minutes,
    )
    probe_payload.update(
        {
            "warmup_attempted": True,
            "warmup_ok": warmup_ok,
            "warmup_detail": warmup_detail,
        }
    )
    if warmup_ok:
        msg = (
            f"Modèle `{resolved_model}` chargé en mémoire "
            f"({keep_alive_minutes} min keep-alive). "
            f"[{warmup_detail}]"
        )
        if resolve_note:
            msg = f"{resolve_note} {msg}"
        if route_note:
            msg = f"{route_note} {msg}".strip()
        probe_payload["message"] = msg
        _store_builder_runtime_acceptance_probe(probe_payload)
        return (
            True,
            msg,
            resolved_model,
        )

    probe_payload.update(
        {
            "status": "warmup_failed",
            "message": (
                f"{route_note} Impossible de précharger `{resolved_model}` sur {runtime_host}. "
                f"Détail: {warmup_detail}"
            ).strip(),
        }
    )
    _store_builder_runtime_acceptance_probe(probe_payload)
    return (
        False,
        (
            f"{route_note} Impossible de précharger `{resolved_model}` sur {runtime_host}. "
            f"Détail: {warmup_detail}"
        ).strip(),
        resolved_model,
    )


def _prepare_builder_llm_resilient(
    *,
    model: str,
    ollama_host: str,
    preload_model: bool,
    keep_alive_minutes: int,
    auto_start_ollama: bool,
    gpu_target: str | None = None,
    allow_lazy_fallback: bool = False,
    allow_model_fallback: bool = False,
) -> tuple[bool, str, str, bool]:
    """Prépare le runtime Builder avec fallback optionnel vers lazy-load.

    Le fallback n'est tenté que quand le seul problème est le préchargement
    du modèle; un Ollama inaccessible ou un modèle absent restent des erreurs
    bloquantes.
    """
    ok, msg, resolved_model = _prepare_builder_llm(
        model=model,
        ollama_host=ollama_host,
        preload_model=preload_model,
        keep_alive_minutes=keep_alive_minutes,
        auto_start_ollama=auto_start_ollama,
        gpu_target=gpu_target,
        allow_model_fallback=allow_model_fallback,
    )
    if ok:
        return True, msg, resolved_model, False

    normalized_msg = str(msg or "")
    should_retry_lazy = (
        allow_lazy_fallback
        and preload_model
        and "Impossible de précharger" in normalized_msg
    )
    if not should_retry_lazy:
        return False, msg, resolved_model, False

    retry_ok, retry_msg, retry_model = _prepare_builder_llm(
        model=resolved_model,
        ollama_host=ollama_host,
        preload_model=False,
        keep_alive_minutes=keep_alive_minutes,
        auto_start_ollama=auto_start_ollama,
        gpu_target=gpu_target,
        allow_model_fallback=allow_model_fallback,
    )
    if not retry_ok:
        return False, msg, resolved_model, False

    return (
        True,
        (
            f"{normalized_msg} "
            "Fallback automatique vers un démarrage lazy-load. "
            f"{retry_msg}"
        ).strip(),
        retry_model,
        True,
    )


def _dedupe_keep_order(values: List[str], *, upper: bool = False) -> List[str]:
    """Supprime les doublons en conservant l'ordre d'apparition."""
    out: List[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        if upper:
            value = value.upper()
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _is_builder_supported_timeframe(raw_tf: str) -> bool:
    """Filtre des TF supportés en mode Builder (rejette les TF mensuels)."""
    tf = str(raw_tf or "").strip()
    if not tf:
        return False
    m = re.fullmatch(r"(\d+)([mhdwM])", tf)
    if not m:
        return False
    amount = int(m.group(1))
    unit = m.group(2)
    if amount <= 0:
        return False
    if unit == "M":
        return False
    return True


def _sanitize_builder_timeframes(
    timeframes: List[str],
    *,
    fallback: str = "1h",
) -> List[str]:
    """Normalise la liste de TF pour le Builder en retirant les entrées non supportées."""
    cleaned = [
        str(tf or "").strip()
        for tf in (timeframes or [])
        if _is_builder_supported_timeframe(str(tf or "").strip())
    ]
    cleaned = _dedupe_keep_order(cleaned, upper=False)
    if cleaned:
        return cleaned
    return [fallback] if _is_builder_supported_timeframe(fallback) else ["1h"]


def _get_builder_compatible_indicators(df: Any) -> List[str]:
    """Retourne les indicateurs calculables avec les colonnes réellement présentes."""
    try:
        from indicators.registry import get_indicator, list_indicators
    except Exception:
        return ["ema", "rsi", "atr"]

    all_indicators = [str(x or "").strip().lower() for x in list_indicators()]
    all_indicators = [x for x in all_indicators if x]
    if not all_indicators:
        return ["ema", "rsi", "atr"]

    # Si df indisponible, partir sur OHLCV standard.
    raw_cols = getattr(df, "columns", None)
    if raw_cols is None:
        raw_cols = []
    df_cols = {
        str(col or "").strip().lower()
        for col in list(raw_cols)
        if str(col or "").strip()
    }
    if not df_cols:
        df_cols = {"open", "high", "low", "close", "volume"}

    # Indicateurs à colonne externe optionnelle/non-OHLCV.
    # fear_greed exige une colonne dédiée "fear_greed" et échoue sinon.
    custom_column_requirements = {
        "fear_greed": "fear_greed",
    }

    compatible: List[str] = []
    for name in all_indicators:
        info = get_indicator(name)
        required = tuple(getattr(info, "required_columns", ()) or ())
        if any(str(col).lower() not in df_cols for col in required):
            continue
        extra_col = custom_column_requirements.get(name)
        if extra_col and extra_col not in df_cols:
            continue
        compatible.append(name)

    if compatible:
        return compatible
    return ["ema", "rsi", "atr"]


def _stable_random_pick(session_key: str, candidates: List[str], fallback: str) -> str:
    """Retourne un choix aléatoire stable sur la session Streamlit."""
    normalized = [str(v or "").strip() for v in candidates if str(v or "").strip()]
    if not normalized:
        return fallback

    cached = str(st.session_state.get(session_key, "") or "").strip()
    if cached in normalized:
        return cached

    picked = random.choice(normalized)
    st.session_state[session_key] = picked
    return picked


def _pick_non_recent_market(
    symbols: List[str],
    timeframes: List[str],
    recent_markets: List[Tuple[str, str]],
) -> Tuple[str, str]:
    """Choisit un couple marché de fallback en évitant d'abord les plus récents."""
    clean_symbols = [str(s or "").strip().upper() for s in symbols if str(s or "").strip()]
    clean_tfs = [str(tf or "").strip() for tf in timeframes if str(tf or "").strip()]
    if not clean_symbols:
        clean_symbols = ["BTCUSDC"]
    if not clean_tfs:
        clean_tfs = ["1h"]

    all_pairs = [(s, tf) for s in clean_symbols for tf in clean_tfs]
    if len(all_pairs) == 1:
        return all_pairs[0]

    recent_set = {
        (str(s or "").strip().upper(), str(tf or "").strip())
        for s, tf in (recent_markets or [])
        if str(s or "").strip() and str(tf or "").strip()
    }
    candidate_pairs = [pair for pair in all_pairs if pair not in recent_set]
    pool = candidate_pairs if candidate_pairs else all_pairs

    # Diversifier explicitement les TF pour éviter les longs blocs mono-timeframe.
    tf_usage = st.session_state.setdefault("_builder_tf_usage", {})
    for tf in clean_tfs:
        tf_usage.setdefault(tf, 0)
    min_tf_usage = min(tf_usage.get(tf, 0) for _, tf in pool)
    tf_pool = [
        tf for tf in clean_tfs
        if tf_usage.get(tf, 0) == min_tf_usage and any(pair_tf == tf for _, pair_tf in pool)
    ]
    chosen_tf = random.choice(tf_pool) if tf_pool else random.choice(clean_tfs)

    tf_pairs = [pair for pair in pool if pair[1] == chosen_tf]
    chosen_pair = random.choice(tf_pairs) if tf_pairs else random.choice(pool)
    tf_usage[chosen_pair[1]] = int(tf_usage.get(chosen_pair[1], 0)) + 1
    return chosen_pair


def _builder_market_candidates(
    state: Any,
    *,
    current_symbol: str,
    current_timeframe: str,
    objective: str = "",
    purpose: str = "builder",
    fallback_df: Any = None,
) -> Tuple[List[str], List[str]]:
    """Construit l'univers symbol/timeframe proposé au LLM."""
    auto_market_pick = bool(getattr(state, "builder_auto_market_pick", False))

    # En mode auto market pick, ignorer les valeurs bootstrap cachées (1 seul token/TF)
    # et ne conserver que les sélections explicitement faites dans les multiselects UI.
    if auto_market_pick:
        selected_symbols = [
            str(s or "").strip().upper()
            for s in (st.session_state.get("symbols_select", []) or [])
            if str(s or "").strip()
        ]
        selected_timeframes = [
            str(tf or "").strip()
            for tf in (st.session_state.get("timeframes_select", []) or [])
            if str(tf or "").strip()
        ]
    else:
        selected_symbols = list(getattr(state, "symbols", []) or [])
        selected_timeframes = list(getattr(state, "timeframes", []) or [])

    available_symbols, available_timeframes = _resolve_builder_available_market_inventory(
        state
    )

    # Priorité: sélection utilisateur -> marché courant -> univers complet.
    symbols = _dedupe_keep_order(
        [*selected_symbols, current_symbol, *available_symbols],
        upper=True,
    )
    if selected_timeframes:
        # Source de vérité: quand l'utilisateur a sélectionné des TF,
        # ne pas réinjecter un current_timeframe externe potentiellement obsolète.
        tf_candidates = [str(tf or "").strip() for tf in selected_timeframes if str(tf or "").strip()]
        if current_timeframe and current_timeframe in tf_candidates:
            tf_candidates = [current_timeframe, *[tf for tf in tf_candidates if tf != current_timeframe]]
    else:
        tf_candidates = [current_timeframe, *available_timeframes]

    timeframes = _dedupe_keep_order(tf_candidates, upper=False)
    timeframes = _sanitize_builder_timeframes(timeframes, fallback=current_timeframe or "1h")

    # Anti-biais: on garde des ancres utiles (marché courant + sélection utilisateur),
    # puis on complète aléatoirement pour éviter l'effet "premiers éléments de liste".
    symbol_anchors = _dedupe_keep_order(
        [current_symbol, *selected_symbols],
        upper=True,
    )
    symbol_anchors = [s for s in symbol_anchors if s in symbols][:6]
    symbol_pool = [s for s in symbols if s not in symbol_anchors]
    random.shuffle(symbol_pool)
    symbols = [*symbol_anchors, *symbol_pool]

    timeframe_anchors = _dedupe_keep_order(
        [current_timeframe, *selected_timeframes],
        upper=False,
    )
    timeframe_anchors = [
        tf for tf in timeframe_anchors
        if tf in timeframes and _is_builder_supported_timeframe(tf)
    ][:4]
    timeframe_pool = [tf for tf in timeframes if tf not in timeframe_anchors]
    random.shuffle(timeframe_pool)
    timeframes = [*timeframe_anchors, *timeframe_pool]

    symbols = symbols[:24]
    timeframes = timeframes[:12]

    normalized_mode = normalize_universe_mode(
        getattr(state, "builder_universe_mode", BUILDER_UNIVERSE_MODE_CANONICAL),
        purpose=purpose,
    )
    static_objective = sanitize_objective_text(
        str(getattr(state, "builder_objective", "") or "")
    )
    filter_objective = static_objective
    if not filter_objective and str(purpose or "").strip() != "builder_autonomous":
        filter_objective = sanitize_objective_text(str(objective or ""))
    normalized_strategy_type = infer_strategy_type(
        strategy_key=str(getattr(state, "strategy_key", "") or ""),
        objective=filter_objective,
    )

    universe_payload = _get_or_build_builder_market_universe(
        state=state,
        symbols=symbols,
        timeframes=timeframes,
        normalized_mode=normalized_mode,
        purpose=purpose,
        normalized_strategy_type=normalized_strategy_type,
        current_symbol=current_symbol,
        current_timeframe=current_timeframe,
        objective=filter_objective,
    )
    st.session_state["_builder_market_last_universe_meta"] = universe_payload

    return list(universe_payload.get("symbols", []) or []), list(
        universe_payload.get("timeframes", []) or []
    )


def _call_builder_market_candidates(
    state: Any,
    *,
    current_symbol: str,
    current_timeframe: str,
    objective: str = "",
    purpose: str = "builder",
    fallback_df: Any = None,
) -> Tuple[List[str], List[str]]:
    """Appelle `_builder_market_candidates` en restant compatible avec les anciens stubs de test."""
    candidate_fn = _builder_market_candidates
    call_kwargs: Dict[str, Any] = {
        "current_symbol": current_symbol,
        "current_timeframe": current_timeframe,
    }
    optional_kwargs = {
        "objective": objective,
        "purpose": purpose,
        "fallback_df": fallback_df,
    }
    try:
        signature = inspect.signature(candidate_fn)
    except (TypeError, ValueError):
        signature = None
    if signature is None:
        return candidate_fn(state, **call_kwargs, **optional_kwargs)

    accepts_var_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    for key, value in optional_kwargs.items():
        if accepts_var_kwargs or key in signature.parameters:
            call_kwargs[key] = value
    return candidate_fn(state, **call_kwargs)


def discover_available_builder_data() -> tuple[list[str], list[str]]:
    """Découvre l'inventaire OHLCV local utilisable par le Builder."""
    try:
        from data.loader import discover_available_data as _discover_available_data
    except Exception:
        logger.warning("builder_market_discovery_import_failed", exc_info=True)
        return [], []

    try:
        tokens, timeframes = _discover_available_data()
    except Exception:
        logger.warning("builder_market_discovery_failed", exc_info=True)
        return [], []

    return list(tokens or []), list(timeframes or [])


def _resolve_builder_available_market_inventory(
    state: Any,
) -> Tuple[List[str], List[str]]:
    """Complète l'inventaire Builder depuis le scan disque si l'état UI est vide."""
    available_symbols = _dedupe_keep_order(
        list(getattr(state, "available_tokens", []) or []),
        upper=True,
    )
    available_timeframes = _dedupe_keep_order(
        [
            str(tf or "").strip()
            for tf in (getattr(state, "available_timeframes", []) or [])
            if _is_builder_supported_timeframe(str(tf or "").strip())
        ],
        upper=False,
    )

    if not available_symbols or not available_timeframes:
        cache_payload = st.session_state.get("_builder_discovered_market_inventory", {})
        if isinstance(cache_payload, dict):
            discovered_symbols = list(cache_payload.get("symbols", []) or [])
            discovered_timeframes = list(cache_payload.get("timeframes", []) or [])
        else:
            discovered_symbols = []
            discovered_timeframes = []

        if not discovered_symbols and not discovered_timeframes:
            discovered_symbols, discovered_timeframes = discover_available_builder_data()
            st.session_state["_builder_discovered_market_inventory"] = {
                "symbols": list(discovered_symbols),
                "timeframes": list(discovered_timeframes),
            }

        if not available_symbols and discovered_symbols:
            available_symbols = _dedupe_keep_order(discovered_symbols, upper=True)
        if not available_timeframes and discovered_timeframes:
            available_timeframes = _dedupe_keep_order(
                [
                    str(tf or "").strip()
                    for tf in discovered_timeframes
                    if _is_builder_supported_timeframe(str(tf or "").strip())
                ],
                upper=False,
            )

    return available_symbols, _sanitize_builder_timeframes(
        available_timeframes,
        fallback="1h",
    )


def _builder_market_date_bounds(state: Any) -> Tuple[str | None, str | None]:
    use_date_filter = bool(getattr(state, "use_date_filter", False))
    if not use_date_filter:
        return None, None
    return (
        _state_date_to_iso(getattr(state, "start_date", None)),
        _state_date_to_iso(getattr(state, "end_date", None)),
    )


def _builder_market_universe_cache() -> Dict[Any, Dict[str, Any]]:
    cache = st.session_state.get(_BUILDER_MARKET_UNIVERSE_CACHE_KEY)
    if not isinstance(cache, dict):
        cache = {}
        st.session_state[_BUILDER_MARKET_UNIVERSE_CACHE_KEY] = cache
    return cache


def _builder_market_loader_criteria() -> Dict[str, Any]:
    try:
        from data.loader import TRIM_LAUNCH_MIN_HOURS, TRIM_LAUNCH_PCT
    except Exception:
        return {
            "loader_trim_launch_pct": None,
            "loader_trim_launch_min_hours": None,
            "loader_gap_max_multiplier": 2.0,
            "loader_non_tradable_rule": "volume<=0",
        }
    return {
        "loader_trim_launch_pct": float(TRIM_LAUNCH_PCT),
        "loader_trim_launch_min_hours": int(TRIM_LAUNCH_MIN_HOURS),
        "loader_gap_max_multiplier": 2.0,
        "loader_non_tradable_rule": "volume<=0",
    }


def _builder_market_universe_cache_key(
    *,
    state: Any,
    symbols: List[str],
    timeframes: List[str],
    normalized_mode: str,
    purpose: str,
    normalized_strategy_type: str,
) -> Tuple[Any, ...]:
    start, end = _builder_market_date_bounds(state)
    return (
        _BUILDER_MARKET_UNIVERSE_CACHE_VERSION,
        str(normalized_mode or "").strip().lower(),
        str(purpose or "").strip(),
        str(normalized_strategy_type or "").strip().lower(),
        start,
        end,
        tuple(str(symbol or "").strip().upper() for symbol in symbols),
        tuple(str(timeframe or "").strip() for timeframe in timeframes),
    )


def _clone_builder_market_universe_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return copy.deepcopy(payload)
    except Exception:
        return dict(payload)


def _get_or_build_builder_market_universe(
    *,
    state: Any,
    symbols: List[str],
    timeframes: List[str],
    normalized_mode: str,
    purpose: str,
    normalized_strategy_type: str,
    current_symbol: str,
    current_timeframe: str,
    objective: str = "",
) -> Dict[str, Any]:
    """Retourne l'univers filtré Builder sans rescanner les OHLCV à chaque run.

    Le filtrage reste délégué à `filter_market_universe`, source canonique des
    exigences de liquidité, ancienneté de listing, tradabilité, volume, gaps et
    compatibilité stratégie/timeframe. Cette fonction mémorise seulement son
    résultat pour un couple critères+inventaire+découpage temporel donné.
    """
    cache_key = _builder_market_universe_cache_key(
        state=state,
        symbols=symbols,
        timeframes=timeframes,
        normalized_mode=normalized_mode,
        purpose=purpose,
        normalized_strategy_type=normalized_strategy_type,
    )
    cache = _builder_market_universe_cache()
    if cache_key in cache:
        cached_payload = _clone_builder_market_universe_payload(cache[cache_key])
        cached_payload["cache_status"] = "hit"
        st.session_state["_builder_market_last_universe_meta"] = cached_payload
        return cached_payload

    def _universe_loader(symbol: str, timeframe: str) -> Any:
        loaded_df, load_error, _data_source = _load_builder_market_data(
            state=state,
            symbol=symbol,
            timeframe=timeframe,
            fallback_df=None,
            allow_current_fallback=False,
        )
        if load_error is not None or not _has_builder_market_df(loaded_df):
            return None
        return loaded_df

    universe_payload = filter_market_universe(
        symbols=symbols,
        timeframes=timeframes,
        universe_mode=normalized_mode,
        purpose=purpose,
        strategy_type=normalized_strategy_type,
        strategy_key=str(getattr(state, "strategy_key", "") or ""),
        objective=objective,
        data_loader=_universe_loader,
    )
    universe_payload["requested_symbols"] = list(symbols)
    universe_payload["requested_timeframes"] = list(timeframes)
    universe_payload["current_symbol"] = str(current_symbol or "").strip().upper()
    universe_payload["current_timeframe"] = str(current_timeframe or "").strip()
    universe_payload["cache_status"] = "miss"
    universe_payload["cache_version"] = _BUILDER_MARKET_UNIVERSE_CACHE_VERSION
    universe_payload["filter_source"] = "config.market_selection.filter_market_universe"
    loader_criteria = _builder_market_loader_criteria()
    universe_payload["data_loader_criteria"] = loader_criteria
    universe_payload["criteria"] = {
        **dict(universe_payload.get("criteria", {}) or {}),
        **loader_criteria,
    }

    cache[cache_key] = _clone_builder_market_universe_payload(universe_payload)
    while len(cache) > _BUILDER_MARKET_UNIVERSE_CACHE_MAX_ENTRIES:
        first_key = next(iter(cache))
        cache.pop(first_key, None)
    st.session_state["_builder_market_last_universe_meta"] = universe_payload
    return universe_payload


def _get_builder_market_universe_meta() -> Dict[str, Any]:
    payload = st.session_state.get("_builder_market_last_universe_meta", {})
    return dict(payload) if isinstance(payload, dict) else {}


def _state_date_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return str(value.isoformat())
        except Exception:
            return None
    text = str(value).strip()
    return text or None


def _load_builder_market_data(
    *,
    state: Any,
    symbol: str,
    timeframe: str,
    fallback_df: Any,
    allow_current_fallback: bool = True,
) -> tuple[Any, str | None, str]:
    """Charge les données pour un marché recommandé avec cache simple en session."""
    fallback_available = _has_builder_market_df(fallback_df)
    if not symbol or not timeframe:
        if fallback_available and allow_current_fallback:
            return fallback_df, "Marché invalide", "fallback_current_df"
        return None, "Marché invalide", "load_error"

    base_symbol = str(getattr(state, "symbol", "") or "").upper()
    base_timeframe = str(getattr(state, "timeframe", "") or "")
    if symbol.upper() == base_symbol and timeframe == base_timeframe and fallback_available:
        return fallback_df, None, "current_df"

    start, end = _builder_market_date_bounds(state)
    cache_key = f"{symbol}|{timeframe}|{start}|{end}"

    cache = st.session_state.setdefault("_builder_market_df_cache", {})
    if cache_key in cache:
        return cache[cache_key], None, "cache"

    market_df, load_msg = safe_load_data(symbol, timeframe, start=start, end=end)
    if not _has_builder_market_df(market_df):
        if fallback_available and allow_current_fallback:
            return fallback_df, load_msg or f"Chargement impossible pour {symbol}/{timeframe}", "fallback_current_df"
        return None, load_msg or f"Chargement impossible pour {symbol}/{timeframe}", "load_error"

    cache[cache_key] = market_df
    if len(cache) > 6:
        first_key = next(iter(cache))
        if first_key != cache_key:
            cache.pop(first_key, None)
    return market_df, None, "loaded"


def _has_builder_market_df(df: Any) -> bool:
    if df is None:
        return False
    try:
        if getattr(df, "empty", False):
            return False
        return len(df) > 0
    except Exception:
        return False


def _has_builder_market_enough_bars(df: Any, *, min_bars: int = MIN_BUILDER_BARS) -> bool:
    if not _has_builder_market_df(df):
        return False
    try:
        return len(df) >= int(min_bars)
    except Exception:
        return False


def _builder_market_min_bars_error(symbol: str, timeframe: str, *, n_bars: int) -> str:
    return (
        f"Dataset insuffisant pour Builder: {int(n_bars)} barres "
        f"(< {int(MIN_BUILDER_BARS)}) sur {symbol}/{timeframe}."
    )


def _validate_builder_market_dataset(
    *,
    df: Any,
    symbol: str,
    timeframe: str,
    universe_mode: str = "canonical",
    strategy_type: str = "",
    purpose: str = "builder",
    objective: str = "",
) -> tuple[bool, str]:
    if not _has_builder_market_df(df):
        return False, "Aucune donnée OHLCV chargée."
    try:
        return validate_builder_dataset_exploitability(
            df,
            symbol=symbol,
            timeframe=timeframe,
            universe_mode=universe_mode,
            strategy_type=strategy_type,
            purpose=purpose,
            objective=objective,
        )
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        return validate_builder_dataset_exploitability(
            df,
            symbol=symbol,
            timeframe=timeframe,
        )
    except Exception as exc:
        logger.warning(
            "builder_market_validation_fallback symbol=%s timeframe=%s error=%s",
            symbol,
            timeframe,
            exc,
        )
        evaluation = evaluate_market_dataset(
            df,
            symbol=symbol,
            timeframe=timeframe,
            universe_mode=universe_mode,
            purpose=purpose,
            strategy_type=strategy_type,
            objective=objective,
        )
        if evaluation.get("accepted"):
            return True, ""
        reasons = list(evaluation.get("exclusion_reasons", []) or [])
        if reasons:
            return False, f"{symbol}/{timeframe}: " + " | ".join(str(reason) for reason in reasons)
        if not _has_builder_market_enough_bars(df):
            return False, _builder_market_min_bars_error(
                symbol,
                timeframe,
                n_bars=len(df),
            )
        return True, ""


def _release_runtime_ollama_model(
    *,
    model: str,
    ollama_host: str,
) -> tuple[bool, str]:
    """Décharge proprement un modèle si encore présent en mémoire."""
    normalized_model = str(model or "").strip()
    if not normalized_model:
        return True, "aucun modele a liberer"
    unloaded = _unload_ollama_model(model=normalized_model, ollama_host=ollama_host)
    if unloaded:
        return True, f"modele `{normalized_model}` decharge"
    loaded, loaded_detail = _is_model_loaded_in_ollama_ps(
        model=normalized_model,
        ollama_host=ollama_host,
    )
    if not loaded:
        return True, f"modele `{normalized_model}` deja libere ({loaded_detail})"
    return False, f"impossible de decharger `{normalized_model}` ({loaded_detail})"


def _build_builder_market_probe_pairs(
    symbols: List[str],
    timeframes: List[str],
    *,
    preferred_pairs: List[Tuple[str, str]] | None = None,
    recent_markets: List[Tuple[str, str]] | None = None,
    max_pairs: int = 24,
) -> List[Tuple[str, str]]:
    clean_symbols = [str(s or "").strip().upper() for s in symbols if str(s or "").strip()]
    clean_tfs = [str(tf or "").strip() for tf in timeframes if str(tf or "").strip()]
    if not clean_symbols:
        clean_symbols = ["BTCUSDC"]
    if not clean_tfs:
        clean_tfs = ["1h"]

    ordered_pairs: List[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()

    def _append_pair(pair_symbol: str, pair_timeframe: str) -> None:
        clean_pair = (str(pair_symbol or "").strip().upper(), str(pair_timeframe or "").strip())
        if not clean_pair[0] or not clean_pair[1] or clean_pair in seen:
            return
        seen.add(clean_pair)
        ordered_pairs.append(clean_pair)

    for pref_symbol, pref_tf in (preferred_pairs or []):
        _append_pair(pref_symbol, pref_tf)

    recent_set = {
        (str(s or "").strip().upper(), str(tf or "").strip())
        for s, tf in (recent_markets or [])
        if str(s or "").strip() and str(tf or "").strip()
    }

    all_pairs = [(s, tf) for s in clean_symbols for tf in clean_tfs]
    non_recent_pairs = [pair for pair in all_pairs if pair not in recent_set]
    recent_pairs = [pair for pair in all_pairs if pair in recent_set]

    for pool in (non_recent_pairs, recent_pairs):
        if len(pool) > 1:
            random.shuffle(pool)
        for pair_symbol, pair_timeframe in pool:
            _append_pair(pair_symbol, pair_timeframe)
            if len(ordered_pairs) >= max_pairs:
                return ordered_pairs

    return ordered_pairs[:max_pairs]


def _find_first_valid_builder_market(
    *,
    state: Any,
    symbols: List[str],
    timeframes: List[str],
    default_symbol: str,
    default_timeframe: str,
    fallback_df: Any,
    preferred_pairs: List[Tuple[str, str]] | None = None,
    recent_markets: List[Tuple[str, str]] | None = None,
    max_pairs: int = 24,
    objective: str = "",
    purpose: str = "builder",
) -> tuple[str, str, Any, Dict[str, Any]]:
    probe_pairs = _build_builder_market_probe_pairs(
        symbols,
        timeframes,
        preferred_pairs=preferred_pairs,
        recent_markets=recent_markets,
        max_pairs=max_pairs,
    )
    failures: List[Dict[str, str]] = []
    strategy_type = infer_strategy_type(
        strategy_key=str(getattr(state, "strategy_key", "") or ""),
        objective=objective,
    )
    universe_mode = normalize_universe_mode(
        getattr(state, "builder_universe_mode", BUILDER_UNIVERSE_MODE_CANONICAL),
        purpose=purpose,
    )
    universe_meta = _get_builder_market_universe_meta()

    for probe_symbol, probe_timeframe in probe_pairs:
        use_fallback = (
            _has_builder_market_df(fallback_df)
            and probe_symbol == str(default_symbol or "").strip().upper()
            and probe_timeframe == str(default_timeframe or "").strip()
        )
        probe_df, load_error, data_source = _load_builder_market_data(
            state=state,
            symbol=probe_symbol,
            timeframe=probe_timeframe,
            fallback_df=fallback_df if use_fallback else None,
            allow_current_fallback=use_fallback,
        )
        if _has_builder_market_df(probe_df) and load_error is None:
            dataset_ok, dataset_error = _validate_builder_market_dataset(
                df=probe_df,
                symbol=probe_symbol,
                timeframe=probe_timeframe,
                universe_mode=universe_mode,
                strategy_type=strategy_type,
                purpose=purpose,
                objective=objective,
            )
            if not dataset_ok:
                failures.append(
                    {
                        "symbol": probe_symbol,
                        "timeframe": probe_timeframe,
                        "error": dataset_error,
                    }
                )
                continue
            return probe_symbol, probe_timeframe, probe_df, {
                "data_source": data_source,
                "failures": failures,
                "probed_pairs": probe_pairs,
                "universe_mode": universe_mode,
                "strategy_type": strategy_type,
                "universe_criteria": dict(universe_meta.get("criteria", {}) or {}),
                "universe_exclusion_summary": dict(
                    universe_meta.get("exclusion_summary", {}) or {}
                ),
                "universe_filter_source": str(
                    universe_meta.get("filter_source", "") or ""
                ),
                "universe_cache_status": str(
                    universe_meta.get("cache_status", "") or ""
                ),
            }
        if load_error:
            failures.append(
                {
                    "symbol": probe_symbol,
                    "timeframe": probe_timeframe,
                    "error": str(load_error),
                }
            )

    fallback_ok, _fallback_error = _validate_builder_market_dataset(
        df=fallback_df,
        symbol=default_symbol,
        timeframe=default_timeframe,
        universe_mode=universe_mode,
        strategy_type=strategy_type,
        purpose=purpose,
        objective=objective,
    )
    if fallback_ok:
        return default_symbol, default_timeframe, fallback_df, {
            "data_source": "fallback_current_df",
            "failures": failures,
            "probed_pairs": probe_pairs,
            "universe_mode": universe_mode,
            "strategy_type": strategy_type,
            "universe_criteria": dict(universe_meta.get("criteria", {}) or {}),
            "universe_exclusion_summary": dict(
                universe_meta.get("exclusion_summary", {}) or {}
            ),
            "universe_filter_source": str(
                universe_meta.get("filter_source", "") or ""
            ),
            "universe_cache_status": str(
                universe_meta.get("cache_status", "") or ""
            ),
        }

    return "", "", None, {
        "data_source": "load_error",
        "failures": failures,
        "probed_pairs": probe_pairs,
        "universe_mode": universe_mode,
        "strategy_type": strategy_type,
        "universe_criteria": dict(universe_meta.get("criteria", {}) or {}),
        "universe_exclusion_summary": dict(
            universe_meta.get("exclusion_summary", {}) or {}
        ),
        "universe_filter_source": str(
            universe_meta.get("filter_source", "") or ""
        ),
        "universe_cache_status": str(
            universe_meta.get("cache_status", "") or ""
        ),
    }


def _pick_market_for_objective(
    *,
    state: Any,
    objective: str,
    llm_client: Any,
    default_symbol: str,
    default_timeframe: str,
    fallback_df: Any,
    recent_markets: list[tuple[str, str]] | None = None,
    purpose: str = "builder_auto_market",
) -> tuple[str, str, Any, Dict[str, Any]]:
    """Demande au LLM le meilleur marché pour l'objectif puis charge les données."""
    symbols, timeframes = _call_builder_market_candidates(
        state,
        current_symbol=default_symbol,
        current_timeframe=default_timeframe,
        objective=objective,
        purpose=purpose,
        fallback_df=fallback_df,
    )
    universe_meta = _get_builder_market_universe_meta()
    strategy_type = str(universe_meta.get("strategy_type") or infer_strategy_type(
        strategy_key=str(getattr(state, "strategy_key", "") or ""),
        objective=objective,
    ))
    universe_mode = str(
        universe_meta.get("universe_mode")
        or normalize_universe_mode(
            getattr(state, "builder_universe_mode", BUILDER_UNIVERSE_MODE_CANONICAL),
            purpose=purpose,
        )
    )
    if not symbols or not timeframes:
        return "", "", None, {
            "symbol": "",
            "timeframe": "",
            "confidence": 0.0,
            "reason": "Aucun marché éligible dans l'univers courant.",
            "source": "universe_empty",
            "data_source": "load_error",
            "load_error": "Aucun marché éligible après filtres locaux/canoniques.",
            "candidate_symbols": symbols,
            "candidate_timeframes": timeframes,
            "universe_mode": universe_mode,
            "universe_strategy_type": strategy_type,
            "universe_criteria": dict(universe_meta.get("criteria", {}) or {}),
            "universe_exclusions": list(universe_meta.get("excluded_pairs", []) or []),
            "universe_exclusion_summary": dict(
                universe_meta.get("exclusion_summary", {}) or {}
            ),
            "universe_filter_source": str(
                universe_meta.get("filter_source", "") or ""
            ),
            "universe_cache_status": str(
                universe_meta.get("cache_status", "") or ""
            ),
        }
    pick = recommend_market_context(
        llm_client,
        objective=objective,
        candidate_symbols=symbols,
        candidate_timeframes=timeframes,
        default_symbol=default_symbol,
        default_timeframe=default_timeframe,
        recent_markets=recent_markets,
    )

    run_symbol = str(pick.get("symbol", default_symbol) or default_symbol).upper()
    run_timeframe = str(pick.get("timeframe", default_timeframe) or default_timeframe)
    run_df, load_error, data_source = _load_builder_market_data(
        state=state,
        symbol=run_symbol,
        timeframe=run_timeframe,
        fallback_df=fallback_df,
    )
    if _has_builder_market_df(run_df) and load_error is None:
        dataset_ok, dataset_error = _validate_builder_market_dataset(
            df=run_df,
            symbol=run_symbol,
            timeframe=run_timeframe,
            universe_mode=universe_mode,
            strategy_type=strategy_type,
            purpose=purpose,
            objective=objective,
        )
        if not dataset_ok:
            load_error = dataset_error
            data_source = "invalid_dataset"

    if load_error:
        fallback_symbol, fallback_timeframe, fallback_candidate_df, fallback_meta = _find_first_valid_builder_market(
            state=state,
            symbols=symbols,
            timeframes=timeframes,
            default_symbol=default_symbol,
            default_timeframe=default_timeframe,
            fallback_df=fallback_df,
            preferred_pairs=[(default_symbol, default_timeframe)],
            recent_markets=recent_markets,
            objective=objective,
            purpose=purpose,
        )
        fallback_ok, _fallback_error = _validate_builder_market_dataset(
            df=fallback_candidate_df,
            symbol=fallback_symbol,
            timeframe=fallback_timeframe,
            universe_mode=universe_mode,
            strategy_type=strategy_type,
            purpose=purpose,
            objective=objective,
        )
        if fallback_ok and fallback_symbol and fallback_timeframe:
            run_symbol = fallback_symbol
            run_timeframe = fallback_timeframe
            run_df = fallback_candidate_df
            data_source = str(fallback_meta.get("data_source", data_source) or data_source)
            pick["fallback_symbol"] = fallback_symbol
            pick["fallback_timeframe"] = fallback_timeframe
            pick["fallback_data_source"] = data_source
            pick["probe_failures"] = fallback_meta.get("failures", [])
        else:
            run_symbol = default_symbol
            run_timeframe = default_timeframe

    pick["data_source"] = data_source
    pick["load_error"] = load_error
    pick["candidate_symbols"] = symbols
    pick["candidate_timeframes"] = timeframes
    pick["universe_mode"] = universe_mode
    pick["universe_strategy_type"] = strategy_type
    pick["universe_criteria"] = dict(universe_meta.get("criteria", {}) or {})
    pick["universe_exclusions"] = list(universe_meta.get("excluded_pairs", []) or [])
    pick["universe_exclusion_summary"] = dict(
        universe_meta.get("exclusion_summary", {}) or {}
    )
    pick["universe_filter_source"] = str(
        universe_meta.get("filter_source", "") or ""
    )
    pick["universe_cache_status"] = str(
        universe_meta.get("cache_status", "") or ""
    )
    return run_symbol, run_timeframe, run_df, pick


def _select_autonomous_market_for_session(
    *,
    state: Any,
    objective: str,
    objective_mode: str,
    use_auto_market_pick: bool,
    llm_client: Any,
    default_symbol: str,
    default_timeframe: str,
    fallback_df: Any,
    recent_markets: list[tuple[str, str]] | None = None,
) -> tuple[str, str, Any, Dict[str, Any]]:
    universe_mode = normalize_universe_mode(
        getattr(state, "builder_universe_mode", BUILDER_UNIVERSE_MODE_CANONICAL),
        purpose="builder_autonomous",
    )
    strategy_type = infer_strategy_type(
        strategy_key=str(getattr(state, "strategy_key", "") or ""),
        objective=objective,
    )
    if not use_auto_market_pick:
        dataset_ok, dataset_msg = _validate_builder_market_dataset(
            df=fallback_df,
            symbol=default_symbol,
            timeframe=default_timeframe,
            universe_mode=universe_mode,
            strategy_type=strategy_type,
            purpose="builder_autonomous",
            objective=objective,
        )
        return default_symbol, default_timeframe, fallback_df, {
            "source": "auto_market_disabled",
            "reason": (
                "Auto-market pick désactivé."
                if dataset_ok
                else f"Marché courant rejeté par l'univers {universe_mode}: {dataset_msg}"
            ),
            "data_source": "fallback_current_df" if _has_builder_market_df(fallback_df) else "none",
            "load_error": None if dataset_ok else dataset_msg,
            "universe_mode": universe_mode,
            "universe_strategy_type": strategy_type,
        }

    normalized_mode = str(objective_mode or "").strip().lower()
    if normalized_mode == "llm" and llm_client is not None:
        return _pick_market_for_objective(
            state=state,
            objective=objective,
            llm_client=llm_client,
            default_symbol=default_symbol,
            default_timeframe=default_timeframe,
            fallback_df=fallback_df,
            recent_markets=recent_markets,
            purpose="builder_autonomous",
        )

    fallback_symbols, fallback_timeframes = _call_builder_market_candidates(
        state=state,
        current_symbol=default_symbol,
        current_timeframe=default_timeframe,
        objective=objective,
        purpose="builder_autonomous",
        fallback_df=fallback_df,
    )
    fallback_symbol, fallback_timeframe, fallback_candidate_df, fallback_meta = _find_first_valid_builder_market(
        state=state,
        symbols=fallback_symbols,
        timeframes=fallback_timeframes,
        default_symbol=default_symbol,
        default_timeframe=default_timeframe,
        fallback_df=fallback_df,
        preferred_pairs=[(default_symbol, default_timeframe)],
        recent_markets=recent_markets,
        objective=objective,
        purpose="builder_autonomous",
    )
    if fallback_symbol and fallback_timeframe and _has_builder_market_df(fallback_candidate_df):
        source = "deterministic_recovery" if normalized_mode != "llm" else "deterministic_no_llm_client"
        reason = (
            "Mode recovery/fallback: sélection déterministe d'un marché valide sans appel LLM."
            if normalized_mode != "llm"
            else "Client de sélection marché indisponible: fallback déterministe appliqué."
        )
        return fallback_symbol, fallback_timeframe, fallback_candidate_df, {
            "source": source,
            "reason": reason,
            "confidence": 0.0,
            "data_source": str(fallback_meta.get("data_source", "loaded") or "loaded"),
            "load_error": None,
            "candidate_symbols": fallback_symbols,
            "candidate_timeframes": fallback_timeframes,
            "probe_failures": fallback_meta.get("failures", []),
            "universe_mode": str(fallback_meta.get("universe_mode") or universe_mode),
            "universe_strategy_type": str(fallback_meta.get("strategy_type") or strategy_type),
            "universe_criteria": dict(fallback_meta.get("universe_criteria", {}) or {}),
            "universe_exclusion_summary": dict(
                fallback_meta.get("universe_exclusion_summary", {}) or {}
            ),
            "universe_filter_source": str(
                fallback_meta.get("universe_filter_source", "") or ""
            ),
            "universe_cache_status": str(
                fallback_meta.get("universe_cache_status", "") or ""
            ),
        }

    return default_symbol, default_timeframe, fallback_df, {
        "source": "deterministic_recovery_failed",
        "reason": "Aucun marché valide trouvé pendant le fallback déterministe.",
        "confidence": 0.0,
        "data_source": "load_error",
        "load_error": "Aucun marché Builder exploitable trouvé.",
        "universe_mode": universe_mode,
        "universe_strategy_type": strategy_type,
    }


# ---------------------------------------------------------------------------
# Run unique d'une session builder (factorisé pour réutilisation)
# ---------------------------------------------------------------------------

def _run_single_builder_session(
    *,
    objective: str,
    model: str,
    ollama_host: str,
    gpu_target: str | None = None,
    llm_inference_global_settings: Optional[Dict[str, Any]] = None,
    llm_inference_model_profiles: Optional[Dict[str, Dict[str, Any]]] = None,
    llm_topology_config: Any = None,
    preload_model: bool,
    keep_alive_minutes: int,
    unload_after_run: bool,
    auto_start_ollama: bool,
    max_iterations: int,
    target_sharpe: float,
    capital: float,
    symbol: str,
    timeframe: str,
    fees_bps: float,
    slippage_bps: float,
    df: Any,
    universe_mode: str = "canonical",
    universe_purpose: str = "builder",
    universe_strategy_type: str = "",
    universe_meta: Optional[Dict[str, Any]] = None,
    session_label: str = "",
    skip_llm_prepare: bool = False,
    show_config_caption: bool = True,
    autonomous_runtime_watchdog: bool = False,
    phase_llm_clients: Optional[Dict[str, Any]] = None,
    builder_execution_mode: str = BUILDER_EXECUTION_MODE_MONO,
    orchestration_mode: str = "single_llm",
    builder_flow_analysis_enabled: bool = False,
    builder_flow_analysis_ablation: Optional[Dict[str, bool]] = None,
    live_thoughts_panel_placeholder: Any = None,
    live_thoughts_panel_kwargs: Optional[Dict[str, Any]] = None,
) -> Any:
    """Exécute une session builder unique et affiche les résultats.

    Args:
        skip_llm_prepare: Si True, ne pas refaire les checks/warmup (déjà fait en amont).
        autonomous_runtime_watchdog: Si True, émet un heartbeat périodique
            et des métriques process pour permettre une relance externe.

    Returns:
        BuilderSession ou None en cas d'erreur/interruption.
    """
    _ = live_thoughts_panel_placeholder, live_thoughts_panel_kwargs
    if session_label:
        st.markdown(f"### {session_label}")
    st.markdown(f"**Objectif:** {objective}")
    if show_config_caption:
        st.caption(
            f"Modèle: `{model}` | Max itérations: {max_iterations} | "
            f"Sharpe cible: {target_sharpe} | Capital: ${capital:,.0f} | "
            f"Marché: {symbol} {timeframe} | "
            f"Univers: `{universe_mode}` | "
            f"Données: {len(df):,} barres | "
            f"Frais: {fees_bps}bps + {slippage_bps}bps slip"
        )

    # Préchargement du modèle Ollama en VRAM
    runtime_model = model
    runtime_model_released = False

    def _release_runtime_model() -> None:
        nonlocal runtime_model_released
        if runtime_model_released or not unload_after_run:
            return
        runtime_model_released = True
        with st.spinner(f"💾 Déchargement du modèle `{runtime_model}`…"):
            released, detail = _release_runtime_ollama_model(
                model=runtime_model,
                ollama_host=ollama_host,
            )
            if released:
                st.caption(f"✅ {detail}")
                if st.session_state.get("builder_model_effective") == runtime_model:
                    st.session_state["builder_model_effective"] = ""
            else:
                st.warning(f"⚠️ {detail}")

    if not skip_llm_prepare:
        with st.spinner(f"⏳ Préparation LLM `{model}` ({ollama_host})…"):
            ok, msg, resolved_model = _prepare_builder_llm(
                model=model,
                ollama_host=ollama_host,
                gpu_target=gpu_target,
                preload_model=preload_model,
                keep_alive_minutes=keep_alive_minutes,
                auto_start_ollama=auto_start_ollama,
            )
            if ok:
                st.caption(f"✅ {msg}")
                runtime_model = resolved_model
                if runtime_model != model:
                    st.info(
                        f"ℹ️ Modèle effectif Builder: `{runtime_model}` "
                        f"(fallback depuis `{model}`)"
                    )
            else:
                st.error(f"❌ {msg}")
                if unload_after_run and resolved_model:
                    _release_runtime_ollama_model(
                        model=resolved_model,
                        ollama_host=ollama_host,
                    )
                return None

    st.session_state["builder_model_effective"] = runtime_model

    progress_bar = st.progress(0.0, text="Initialisation...")
    progress_detail_placeholder = st.empty()
    live_events_placeholder = st.empty()

    # Zone de streaming LLM
    stream_placeholder = st.empty()
    _stream_state: dict = {"text": "", "phase": "", "active": False}
    _progress_state: dict[str, Any] = {
        "iteration": 0,
        "max_iterations": max_iterations,
        "phase": "initialisation",
        "event": "session_start",
        "recent_events": [],
    }

    _PHASE_LABELS = {
        "proposal": ("💡", "Proposition", "json"),
        "code": ("🔧", "Génération de code", "python"),
        "analysis": ("🤔", "Analyse", "json"),
        "backtest": ("📈", "Backtest", "text"),
        "retry_proposal": ("🔁", "Retry proposition", "json"),
        "retry_code": ("🔁", "Retry code", "python"),
        "objective_gen": ("🎯", "Génération d'objectif", "text"),
    }

    def _on_builder_progress(payload: Dict[str, Any]) -> None:
        event_payload = dict(payload or {})
        raw_payload = _builder_event_payload(event_payload)
        event = str(payload.get("event", "") or "")
        iteration = int(
            event_payload.get("iteration", _progress_state["iteration"]) or 0
        )
        max_iters = int(
            raw_payload.get("max_iterations", _progress_state["max_iterations"])
            or max_iterations
        )
        phase = str(
            event_payload.get("phase", _progress_state["phase"])
            or raw_payload.get("phase", "")
            or ""
        )
        _progress_state.update(
            {
                "iteration": iteration,
                "max_iterations": max_iters,
                "phase": phase,
                "event": event,
            }
        )

        if autonomous_runtime_watchdog:
            try:
                heartbeat_payload: Dict[str, Any] = {
                    "last_event": f"builder_{event or 'progress'}",
                    "last_progress_at": _utc_now_iso(),
                    "last_progress_event": event,
                    "last_progress_phase": phase,
                    "last_progress_iteration": iteration,
                }
                session_id = str(event_payload.get("session_id") or "").strip()
                if event == "session_start" and session_id:
                    heartbeat_payload["current_session_id"] = session_id
                    heartbeat_payload["current_session_num"] = int(iteration or 0)
                    heartbeat_payload["last_session_status"] = "running"
                elif event == "session_done":
                    heartbeat_payload["current_session_id"] = ""
                    heartbeat_payload["current_session_num"] = 0
                _heartbeat_builder_autonomous_runtime(**heartbeat_payload)
            except Exception as exc:
                logger.warning(
                    "builder_autonomous_progress_heartbeat_failed event=%s error=%s",
                    event,
                    exc,
                )

        phase_fraction = {
            "proposal": 0.18,
            "code": 0.46,
            "save_and_load": 0.56,
            "validation": 0.60,
            "precheck": 0.66,
            "runtime_fix": 0.72,
            "runtime_fix_fallback_backtest": 0.76,
            "backtest": 0.82,
            "analysis": 0.92,
        }
        completed_iterations = max(iteration - 1, 0)
        if event == "iteration_done":
            completed_iterations = max(iteration, 0)
            fraction = 0.0
        elif event == "session_done":
            completed_iterations = max_iters
            fraction = 0.0
        else:
            fraction = phase_fraction.get(phase, 0.05)

        progress_value = 0.0
        if max_iters > 0:
            progress_value = min((completed_iterations + fraction) / max_iters, 1.0)

        progress_text = str(event_payload.get("message", "") or "").strip()
        branch_label = _builder_event_branch_label(event_payload)
        if not progress_text:
            if event == "session_start":
                progress_text = "Initialisation de la session Builder..."
            elif event == "iteration_start":
                progress_text = f"Itération {iteration}/{max_iters} — démarrage"
            elif event in {"phase_start", "phase_done"}:
                progress_text = (
                    f"Itération {iteration}/{max_iters} — "
                    f"{_BUILDER_PROGRESS_PHASE_LABELS.get(phase, phase or 'phase en cours')}"
                )
            elif event == "iteration_error":
                progress_text = (
                    f"Itération {iteration}/{max_iters} — erreur "
                    f"({_BUILDER_PROGRESS_PHASE_LABELS.get(phase, phase or 'runtime')})"
                )
            elif event == "iteration_done":
                decision = str(raw_payload.get("decision", "") or "continue")
                progress_text = f"Itération {iteration}/{max_iters} — décision {decision}"
            elif event == "session_done":
                progress_text = (
                    f"Session terminée — {event_payload.get('status', 'n/a')} "
                    f"({raw_payload.get('total_iterations', 0)} itérations)"
                )
            else:
                progress_text = f"Itération {iteration}/{max_iters} — activité en cours"
        timeline_line = _format_builder_live_event_line(event_payload)
        if timeline_line:
            recent_events = list(_progress_state.get("recent_events", []) or [])
            recent_events.append(timeline_line)
            _progress_state["recent_events"] = recent_events[-8:]

        try:
            progress_bar.progress(progress_value, text=progress_text)
            with progress_detail_placeholder.container():
                if branch_label and branch_label != "main":
                    st.caption(f"Contexte branche: {branch_label}")
                for detail_line in _format_builder_live_detail_lines(event_payload):
                    st.caption(detail_line)
            with live_events_placeholder.container():
                recent_events = list(_progress_state.get("recent_events", []) or [])
                if recent_events:
                    st.caption("Timeline live")
                    for entry in reversed(recent_events[-6:]):
                        st.caption(entry)
            # Rafraîchir le flux de pensée live sur les événements significatifs
            if event in {"iteration_start", "iteration_done", "backtest_done", "session_done"}:
                _refresh_live_thoughts_code_slot(tail_lines=180)
        except Exception:
            pass

    def _on_llm_stream(phase: str, chunk: str) -> None:
        if phase != _stream_state["phase"]:
            _stream_state["text"] = ""
            _stream_state["phase"] = phase
        _stream_state["text"] += chunk
        _stream_state["active"] = True

        icon, label, default_lang = _PHASE_LABELS.get(phase, ("🧠", phase, "text"))
        text, lang = _sanitize_builder_stream_text(phase, _stream_state["text"])

        try:
            with stream_placeholder.container():
                st.caption(f"{icon} **{label}** — streaming en cours…")
                display = text[-4000:] if len(text) > 4000 else text
                if len(text) > 4000:
                    display = "…(tronqué)…\n" + display
                st.code(display, language=lang)
        except Exception:
            pass

    llm_config = build_builder_base_llm_config(
        model=runtime_model,
        ollama_host=ollama_host,
        keep_alive_minutes=keep_alive_minutes,
        llm_inference_global_settings=llm_inference_global_settings,
        llm_inference_model_profiles=llm_inference_model_profiles,
    )

    watchdog_stop_event = threading.Event()
    watchdog_thread: Optional[threading.Thread] = None

    def _autonomous_watchdog_loop() -> None:
        while not watchdog_stop_event.wait(10.0):
            try:
                runtime_state = _load_autonomous_runtime_state()
                if not bool(runtime_state.get("active")) or bool(runtime_state.get("manual_stop")):
                    break
                _heartbeat_builder_autonomous_runtime(
                    last_event="session_heartbeat",
                    last_progress_event=str(_progress_state.get("event", "") or ""),
                    last_progress_phase=str(_progress_state.get("phase", "") or ""),
                    last_progress_iteration=int(_progress_state.get("iteration", 0) or 0),
                )
            except Exception as exc:
                logger.warning(
                    "builder_autonomous_watchdog_heartbeat_failed error=%s",
                    exc,
                )

    if autonomous_runtime_watchdog:
        _heartbeat_builder_autonomous_runtime(
            last_event="builder_session_bootstrap",
            last_progress_at=_utc_now_iso(),
            last_progress_event="session_start",
            last_progress_phase="initialisation",
            last_progress_iteration=0,
            current_session_id="",
            current_session_num=0,
        )
        watchdog_thread = threading.Thread(
            target=_autonomous_watchdog_loop,
            name="builder-autonomous-heartbeat",
            daemon=True,
        )
        watchdog_thread.start()

    builder = StrategyBuilder(
        llm_config=llm_config,
        llm_topology_config=llm_topology_config,
        phase_llm_clients=phase_llm_clients,
        stream_callback=_on_llm_stream,
        backtest_completed_callback=_maybe_auto_save_run,
        progress_callback=_on_builder_progress,
    )
    builder.builder_execution_mode = str(
        builder_execution_mode or BUILDER_EXECUTION_MODE_MONO
    )
    builder.orchestration_mode = str(orchestration_mode or "single_llm")
    builder.instrumentation.enabled = bool(builder_flow_analysis_enabled)
    builder.ablation.enable_all()
    for step, enabled in dict(builder_flow_analysis_ablation or {}).items():
        if not enabled:
            try:
                builder.ablation.disable(step)
            except ValueError:
                continue
    compatible_indicators = _get_builder_compatible_indicators(df)
    if compatible_indicators:
        builder.available_indicators = compatible_indicators

    iterations_container = st.container()
    summary_placeholder = st.empty()

    try:
        session = builder.run(
            objective=objective,
            data=df,
            max_iterations=max_iterations,
            target_sharpe=target_sharpe,
            initial_capital=capital,
            symbol=symbol,
            timeframe=timeframe,
            fees_bps=fees_bps,
            slippage_bps=slippage_bps,
            universe_mode=universe_mode,
            universe_purpose=universe_purpose,
            universe_strategy_type=universe_strategy_type,
            universe_meta=universe_meta,
        )
    except KeyboardInterrupt:
        st.warning("Construction interrompue par l'utilisateur.")
        _release_runtime_model()
        return None
    except Exception as exc:
        show_status("error", f"Erreur Strategy Builder: {exc}")
        st.code(traceback.format_exc())
        _release_runtime_model()
        return None
    finally:
        if autonomous_runtime_watchdog:
            watchdog_stop_event.set()
            if watchdog_thread is not None:
                watchdog_thread.join(timeout=2.0)

    # Nettoyage
    try:
        stream_placeholder.empty()
    except Exception:
        pass

    progress_bar.progress(1.0, text="Terminé")

    with iterations_container:
        _render_iterations_compact_table(session)

    with summary_placeholder.container():
        st.markdown("---")
        render_session_summary(session)
        with st.expander("🔬 Diagnostics avancés de session", expanded=False):
            _render_builder_flow_analysis_panel(session)

    _release_runtime_model()

    return session


# ---------------------------------------------------------------------------
# Helpers pour entrées d'historique autonome
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tableau récapitulatif des sessions autonomes
# ---------------------------------------------------------------------------

def _render_autonomous_recap(
    history: List[Dict[str, Any]],
    supervisor: Optional[Dict[str, Any]] = None,
) -> None:
    """Affiche un tableau récapitulatif de toutes les sessions autonomes."""

    def _fmt_float(value: Any, pattern: str, default: str = "n/a") -> str:
        return _format_optional_float(value, pattern, default=default)

    def _fmt_int(value: Any, default: str = "n/a") -> str:
        try:
            if value is None:
                return default
            return str(int(value))
        except Exception:
            return default

    def _fmt_days(value: Any, default: str = "n/a") -> str:
        numeric = _safe_optional_float(value)
        if numeric is None:
            return default
        return f"{numeric:.1f}"

    def _fmt_currency(value: Any, default: str = "n/a") -> str:
        numeric = _safe_optional_float(value)
        if numeric is None:
            return default
        return f"{numeric:+,.2f}".replace(",", " ")

    def _escape_autonomous_recap_cell(value: Any) -> str:
        if value is None:
            return ""
        return html.escape(str(value))

    st.markdown("---")
    _recap_title_col, _recap_reset_col = st.columns([7, 1])
    with _recap_title_col:
        st.markdown("## 📊 Récapitulatif des sessions autonomes")
    with _recap_reset_col:
        _render_seq_reset = _next_autonomous_recap_render_seq()
        if st.button(
            "🗑️ Réinitialiser",
            key=f"builder_recap_reset_btn_{_render_seq_reset}",
            help="Effacer tout l'historique des sessions autonomes et repartir à zéro.",
            type="secondary",
        ):
            _sync_autonomous_state([], _default_autonomous_supervisor_state(), trim=False)
            st.rerun()

    runtime_state = _load_autonomous_runtime_state()
    recovered_history, recovered_changed = _recover_autonomous_history_from_disk(
        history,
        runtime_state=runtime_state,
    )
    if recovered_changed:
        history[:] = recovered_history
        _sync_autonomous_state(
            history,
            supervisor if isinstance(supervisor, dict) else _default_autonomous_supervisor_state(),
        )

    latest_session_num = _history_latest_session_num(history)

    if supervisor:
        st.caption(
            "Superviseur: "
            f"errors={int(supervisor.get('consecutive_errors', 0) or 0)} | "
            f"failed_sessions={int(supervisor.get('consecutive_failed_sessions', 0) or 0)} | "
            f"soft_resets={int(supervisor.get('soft_reset_count', 0) or 0)} | "
            f"source={str(supervisor.get('last_selected_source_mode', '-') or '-')} | "
            f"policy={str(supervisor.get('last_selected_source_reason', '-') or '-')}"
        )
    if latest_session_num > len(history):
        st.caption(
            f"Fenêtre glissante: {len(history)} sessions affichées sur {latest_session_num} exécutées "
            f"(limite persistée: {_AUTONOMOUS_MAX_PERSISTED_HISTORY})."
        )

    table_rows: List[str] = []
    export_rows: List[Dict[str, Any]] = []
    full_objective_rows: List[str] = []

    for i, h in enumerate(history, 1):
        objective_raw = str(h.get("objective", "") or "")
        objective_one_line = " ".join(objective_raw.split())
        obj_short = objective_one_line[:100]
        if len(objective_one_line) > 100:
            obj_short += "…"
        display_session_num = _fmt_int(h.get("session_num"), default=str(i))
        started_at = _format_autonomous_session_started_at(h)

        source = str(h.get("source_label", "") or "-")
        h_model = str(h.get("model_name", "") or "-")
        h_gen_stats = h.get("generation_stats") or {}
        h_canonical_rate = h_gen_stats.get("canonical_rate")
        h_llm_pct = f"{h_canonical_rate * 100:.0f}%" if h_canonical_rate is not None else "n/a"
        status = h.get("status", "?")
        # Toujours afficher le BEST run (achievement de la session) plutôt
        # que la dernière itération (qui peut être une régression du LLM).
        sharpe = h.get("best_sharpe")
        if sharpe is None:
            sharpe = h.get("final_sharpe")
        ret = h.get("best_return")
        if ret is None:
            ret = h.get("final_return")
        max_dd = h.get("best_max_dd")
        if max_dd is None:
            max_dd = h.get("final_max_dd")
        trades = h.get("best_trades")
        if trades is None:
            trades = h.get("final_trades")
        duration = h.get("duration", 0)
        gain_metrics = _resolve_autonomous_gain_metrics(h)

        # Régression detection: si l'itération finale a clairement régressé par
        # rapport au best, on annote la cellule pour l'expliquer.
        _final_sharpe = _safe_optional_float(h.get("final_sharpe"))
        _best_sharpe_num = _safe_optional_float(h.get("best_sharpe"))
        _final_return = _safe_optional_float(h.get("final_return"))
        _best_return_num = _safe_optional_float(h.get("best_return"))
        regression_sharpe = (
            _best_sharpe_num is not None
            and _final_sharpe is not None
            and _best_sharpe_num > 0.0
            and _final_sharpe < _best_sharpe_num - 0.20
        )
        regression_return = (
            _best_return_num is not None
            and _final_return is not None
            and _best_return_num > 0.0
            and _final_return < max(0.0, _best_return_num * 0.5)
        )
        sharpe_regression_html = ""
        if regression_sharpe:
            sharpe_regression_html = (
                f"<span class='builder-autonomous-recap-regress' "
                f"title='Régression LLM en fin de session: "
                f"dernière itération sharpe={_final_sharpe:.3f}'>"
                f"↓ {_final_sharpe:.2f}</span>"
            )
        return_regression_html = ""
        if regression_return:
            return_regression_html = (
                f"<span class='builder-autonomous-recap-regress' "
                f"title='Régression LLM en fin de session: "
                f"dernière itération return={_final_return:+.2f}%'>"
                f"↓ {_final_return:+.0f}%</span>"
            )

        badge = _get_autonomous_recap_status_badge(h)
        status_html = (
            f"<span class='builder-autonomous-recap-status "
            f"builder-autonomous-recap-status--{badge['tone']}'>"
            f"{_escape_autonomous_recap_cell(badge['icon'])} "
            f"{_escape_autonomous_recap_cell(badge['label'])}</span>"
        )
        objective_html = (
            "<div class='builder-autonomous-recap-objective-cell' "
            f"title='{_escape_autonomous_recap_cell(objective_one_line)}'>"
            f"<div class='builder-autonomous-recap-objective-preview'>{_escape_autonomous_recap_cell(obj_short)}</div>"
            "<div class='builder-autonomous-recap-objective-trigger' aria-hidden='true'>↗</div>"
            f"<div class='builder-autonomous-recap-objective-full'>{_escape_autonomous_recap_cell(objective_one_line)}</div>"
            "</div>"
        )
        table_rows.append(
            "<tr>"
            f"<td class='builder-autonomous-recap-num'>{_escape_autonomous_recap_cell(display_session_num)}</td>"
            f"<td>{_escape_autonomous_recap_cell(started_at)}</td>"
            f"<td>{_escape_autonomous_recap_cell(source)}</td>"
            f"<td>{_escape_autonomous_recap_cell(h_model)}</td>"
            f"<td class='builder-autonomous-recap-num'>{_escape_autonomous_recap_cell(h_llm_pct)}</td>"
            f"<td>{objective_html}</td>"
            f"<td>{status_html}</td>"
            f"<td class='builder-autonomous-recap-num'>"
            f"<span class='builder-autonomous-recap-best'>{_escape_autonomous_recap_cell(_fmt_float(sharpe, '{:.3f}'))}</span>"
            f"{sharpe_regression_html}"
            f"</td>"
            f"<td class='builder-autonomous-recap-num'>"
            f"<span class='builder-autonomous-recap-best'>{_escape_autonomous_recap_cell(_fmt_float(ret, '{:+.2f}%'))}</span>"
            f"{return_regression_html}"
            f"</td>"
            f"<td class='builder-autonomous-recap-num'>{_escape_autonomous_recap_cell(_fmt_currency(gain_metrics.get('total_pnl')))}</td>"
            f"<td class='builder-autonomous-recap-num'>{_escape_autonomous_recap_cell(_fmt_days(gain_metrics.get('test_days')))}</td>"
            f"<td class='builder-autonomous-recap-num'>{_escape_autonomous_recap_cell(_fmt_currency(gain_metrics.get('pnl_per_day')))}</td>"
            f"<td class='builder-autonomous-recap-num'>{_escape_autonomous_recap_cell(_fmt_float(max_dd, '{:.2f}%'))}</td>"
            f"<td class='builder-autonomous-recap-num'>{_escape_autonomous_recap_cell(_fmt_int(trades))}</td>"
            f"<td class='builder-autonomous-recap-num'>{_escape_autonomous_recap_cell(f'{duration:.0f}s')}</td>"
            "</tr>"
        )
        full_objective_rows.append(
            "<tr>"
            f"<td class='builder-autonomous-recap-num'>{_escape_autonomous_recap_cell(display_session_num)}</td>"
            f"<td>{_escape_autonomous_recap_cell(started_at)}</td>"
            f"<td>{_escape_autonomous_recap_cell(source)}</td>"
            f"<td>{_escape_autonomous_recap_cell(objective_one_line)}</td>"
            "</tr>"
        )
        export_rows.append(
            {
                "session_num": h.get("session_num"),
                "started_at": h.get("started_at"),
                "started_at_display": started_at,
                "model_name": h_model,
                "llm_canonical_pct": h_llm_pct,
                "status": status,
                "status_display": f"{badge['icon']} {badge['label']}",
                "best_sharpe": h.get("best_sharpe"),
                "final_sharpe": sharpe,
                "final_return_pct": ret,
                "final_iteration": h.get("final_iteration"),
                "final_max_drawdown_pct": max_dd,
                "final_trades": trades,
                "gain_total_eur": gain_metrics.get("total_pnl"),
                "test_days": gain_metrics.get("test_days"),
                "gain_per_day_eur": gain_metrics.get("pnl_per_day"),
                "best_return_pct": h.get("best_return"),
                "best_return_iteration": h.get("best_return_iteration"),
                "best_max_drawdown_pct": h.get("best_max_dd"),
                "best_trades": h.get("best_trades"),
                "duration_s": duration,
                "symbol": h.get("symbol"),
                "timeframe": h.get("timeframe"),
                "objective": objective_one_line,
                "source": source,
                "source_mode": h.get("source_mode"),
                "orchestration_mode": h.get("orchestration_mode"),
                "session_id": h.get("session_id"),
            }
        )

    if not table_rows:
        empty_cell = _escape_autonomous_recap_cell(
            "Aucune session enregistrée pour le moment."
        )
        table_rows.append(
            "<tr>"
            f"<td class='builder-autonomous-recap-empty' colspan='15'>{empty_cell}</td>"
            "</tr>"
        )
        full_objective_rows.append(
            "<tr>"
            f"<td class='builder-autonomous-recap-empty' colspan='4'>{empty_cell}</td>"
            "</tr>"
        )

    recap_table_html = """
<style>
.builder-autonomous-recap-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.92rem;
    table-layout: auto;
}
.builder-autonomous-recap-table thead th {
    position: sticky;
    top: 0;
    z-index: 25;
    background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
    color: #f1f5f9;
    font-weight: 700;
    letter-spacing: 0.02em;
    text-transform: uppercase;
    font-size: 0.78rem;
    padding: 0.55rem 0.6rem;
    border-bottom: 2px solid rgba(96, 165, 250, 0.45);
    box-shadow: 0 6px 14px -8px rgba(2, 8, 23, 0.55);
    text-align: left;
    vertical-align: middle;
    white-space: nowrap;
}
.builder-autonomous-recap-table thead th.builder-autonomous-recap-num {
    text-align: right;
}
.builder-autonomous-recap-table tbody tr:nth-child(even) {
    background: rgba(30, 41, 59, 0.18);
}
.builder-autonomous-recap-table tbody tr:hover {
    background: rgba(96, 165, 250, 0.10);
    transition: background 120ms ease-out;
}
.builder-autonomous-recap-table td {
    padding: 0.42rem 0.6rem;
    border-bottom: 1px solid rgba(148, 163, 184, 0.18);
    text-align: left;
    vertical-align: top;
}
.builder-autonomous-recap-objective-cell {
    position: relative;
    max-width: 44rem;
    white-space: normal;
    line-height: 1.35;
    padding-right: 1.8rem;
}
.builder-autonomous-recap-objective-preview {
    color: #e6eefc;
}
.builder-autonomous-recap-objective-trigger {
    position: absolute;
    top: 0.05rem;
    right: 0.05rem;
    width: 1.4rem;
    height: 1.4rem;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 999px;
    background: linear-gradient(135deg, rgba(37, 99, 235, 0.98), rgba(96, 165, 250, 0.96));
    color: #ffffff;
    font-size: 0.8rem;
    font-weight: 700;
    box-shadow: 0 8px 18px rgba(30, 64, 175, 0.28);
    opacity: 0;
    transform: translateY(-2px);
    transition: opacity 140ms ease, transform 140ms ease;
    pointer-events: none;
}
.builder-autonomous-recap-objective-full {
    display: none;
    position: absolute;
    top: calc(100% - 0.15rem);
    right: 0;
    z-index: 30;
    width: min(56rem, 78vw);
    max-height: 15rem;
    overflow: auto;
    padding: 0.85rem 0.95rem;
    border-radius: 14px;
    border: 1px solid rgba(96, 165, 250, 0.35);
    background:
        radial-gradient(circle at top left, rgba(59, 130, 246, 0.14), transparent 38%),
        linear-gradient(180deg, rgba(9, 17, 31, 0.99), rgba(14, 26, 45, 0.98));
    color: #f8fbff;
    box-shadow: 0 18px 38px rgba(2, 8, 23, 0.34);
}
.builder-autonomous-recap-objective-cell:hover .builder-autonomous-recap-objective-trigger,
.builder-autonomous-recap-objective-cell:focus-within .builder-autonomous-recap-objective-trigger {
    opacity: 1;
    transform: translateY(0);
}
.builder-autonomous-recap-objective-cell:hover .builder-autonomous-recap-objective-full,
.builder-autonomous-recap-objective-cell:focus-within .builder-autonomous-recap-objective-full {
    display: block;
}
.builder-autonomous-recap-num {
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
}
.builder-autonomous-recap-status {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.18rem 0.55rem;
    border-radius: 999px;
    font-weight: 700;
    white-space: nowrap;
    font-size: 0.82rem;
    letter-spacing: 0.02em;
}
.builder-autonomous-recap-status--positive {
    color: #052e16;
    background: rgba(34, 197, 94, 0.22);
    border: 1px solid rgba(34, 197, 94, 0.55);
}
.builder-autonomous-recap-status--negative {
    color: #fef2f2;
    background: rgba(248, 113, 113, 0.20);
    border: 1px solid rgba(239, 68, 68, 0.55);
}
.builder-autonomous-recap-status--crash {
    color: #fef2f2;
    background: rgba(220, 38, 38, 0.32);
    border: 1px solid rgba(220, 38, 38, 0.65);
}
.builder-autonomous-recap-status--neutral {
    color: #fef3c7;
    background: rgba(217, 119, 6, 0.20);
    border: 1px solid rgba(217, 119, 6, 0.55);
}
.builder-autonomous-recap-best {
    font-weight: 700;
}
.builder-autonomous-recap-regress {
    display: block;
    margin-top: 0.15rem;
    font-size: 0.72rem;
    font-weight: 600;
    color: #fca5a5;
    opacity: 0.85;
    cursor: help;
    letter-spacing: 0.01em;
}
.builder-autonomous-recap-empty {
    text-align: center !important;
    padding: 0.95rem 0.75rem !important;
    color: rgba(226, 232, 240, 0.72);
    font-style: italic;
}
.builder-autonomous-recap-details {
        margin-top: 0.85rem;
        border: 1px solid rgba(148, 163, 184, 0.2);
        border-radius: 0.75rem;
        padding: 0.35rem 0.75rem 0.6rem;
        background: rgba(15, 23, 42, 0.18);
}
.builder-autonomous-recap-details summary {
        cursor: pointer;
        font-weight: 700;
        margin: 0.25rem 0;
}
.builder-autonomous-recap-legend {
        margin-top: 0.75rem;
        font-size: 0.88rem;
        color: rgba(226, 232, 240, 0.92);
}
</style>
<table class="builder-autonomous-recap-table">
  <thead>
    <tr>
      <th class="builder-autonomous-recap-num">Session</th>
      <th>Date/heure</th>
      <th>Generation</th>
      <th>Modele</th>
      <th class="builder-autonomous-recap-num">LLM %</th>
      <th>Objectif</th>
      <th>Statut</th>
      <th class="builder-autonomous-recap-num" title="Meilleur Sharpe atteint pendant la session (best run)">Sharpe</th>
      <th class="builder-autonomous-recap-num" title="Meilleur return atteint pendant la session (best run)">Return</th>
      <th class="builder-autonomous-recap-num">Gain total $</th>
      <th class="builder-autonomous-recap-num">Jours testes</th>
      <th class="builder-autonomous-recap-num">$ / jour</th>
      <th class="builder-autonomous-recap-num" title="Max drawdown du best run">Max DD</th>
      <th class="builder-autonomous-recap-num" title="Nombre de trades du best run">Trades</th>
      <th class="builder-autonomous-recap-num">Duree</th>
    </tr>
  </thead>
  <tbody>
""" + "\n".join(table_rows) + """
  </tbody>
</table>
<details class="builder-autonomous-recap-details">
    <summary>📜 Voir les objectifs complets</summary>
    <table class="builder-autonomous-recap-table">
        <thead>
            <tr>
                <th>Session</th>
                <th>Date/heure</th>
                <th>Generation</th>
                <th>Objectif complet</th>
            </tr>
        </thead>
        <tbody>
""" + "\n".join(full_objective_rows) + """
        </tbody>
    </table>
</details>
<div class="builder-autonomous-recap-legend">
    <strong>Generation :</strong> <strong>LLM</strong> = objectif formule par le modele ;
    <strong>Fallback simple</strong> = objectif de secours produit par le runtime quand il doit repartir sans dependre du flux LLM principal.<br>
    <strong>Modele :</strong> nom du modele LLM utilise pour la session.
    <strong>LLM % :</strong> pourcentage d'iterations generees par le LLM (canoniques) vs fallback deterministe.<br>
    <strong>Lecture des metriques :</strong> <strong>Sharpe/Return/Max DD/Trades</strong> = metriques du <em>best run</em> (meilleure itération de la session).
    Si l'itération finale a régressé par rapport au best, une annotation <span style="color:#fca5a5;font-weight:700">↓</span> en dessous indique la valeur de la dernière itération.<br>
    <strong>Gain total $ / $ par jour</strong> = derive du PnL final si disponible, sinon du return final applique au capital initial ;
    <strong>Jours testes</strong> = plage de donnees reelle si disponible, sinon estimation via le nombre de barres et le timeframe.
</div>
"""
    overview_tab, history_tab, live_tab = st.tabs(
        [
            "Vue d'ensemble",
            f"Historique ({len(history)})",
            "Pensées en direct",
        ]
    )

    with overview_tab:
        if history:
            best = max(history, key=_autonomous_history_strategy_sort_key)
            st.success(
                f"**Meilleure session :** Return {_fmt_float(best.get('final_return', best.get('best_return')), '{:+.2f}%')} "
                f"(Sharpe {_fmt_float(best.get('final_sharpe', best.get('best_sharpe')), '{:.3f}')}) — "
                f"{best.get('objective', '')[:80]}"
            )
        else:
            st.info("Aucune session autonome enregistrée pour le moment.")

        if export_rows:
            csv_buf = io.StringIO()
            writer = csv.DictWriter(csv_buf, fieldnames=list(export_rows[0].keys()))
            writer.writeheader()
            writer.writerows(export_rows)
            render_seq = _next_autonomous_recap_render_seq()
            st.download_button(
                "⬇️ Export leaderboard CSV",
                data=csv_buf.getvalue(),
                file_name="builder_autonomous_leaderboard.csv",
                mime="text/csv",
                key=(
                    "builder_autonomous_leaderboard_export_"
                    f"{max(latest_session_num, len(export_rows))}_{render_seq}"
                ),
            )

    with history_tab:
        st.markdown(recap_table_html, unsafe_allow_html=True)

    with live_tab:
        _render_builder_live_thoughts_panel(
            title="Flux de pensée live",
            expanded=True,
            show_terminal_command=True,
            tail_lines=260,
        )


# ---------------------------------------------------------------------------
#  Sous-fonctions extraites de _execute_builder_autonomous_loop
# ---------------------------------------------------------------------------


def _record_autonomous_session_result(
    *,
    session: Any,
    session_ctx: Dict[str, Any],
    cfg: Dict[str, Any],
    history: List[Dict[str, Any]],
    supervisor: Dict[str, Any],
    recap_placeholder: Any,
) -> Optional[str]:
    """Enregistre le résultat d'une session autonome et met à jour le superviseur.

    Retourne ``terminal_reason`` si la boucle doit s'arrêter, sinon ``None``.
    """
    session_num = session_ctx["session_num"]
    objective = session_ctx["objective"]
    source_label = session_ctx["source_label"]
    duration = session_ctx["duration"]
    session_started_at = session_ctx["started_at"]
    session_finished_at = datetime.now()
    session_symbol = session_ctx["symbol"]
    session_timeframe = session_ctx["timeframe"]
    session_df = session_ctx["df"]
    session_error_message = session_ctx.get("error_message")
    effective_objective_mode = session_ctx["effective_objective_mode"]
    objective_mode_policy = session_ctx["objective_mode_policy"]
    effective_auto_market_pick = session_ctx["effective_auto_market_pick"]
    autonomous_universe_mode = session_ctx["autonomous_universe_mode"]
    autonomous_strategy_type = session_ctx["autonomous_strategy_type"]
    autonomous_universe_meta = session_ctx["autonomous_universe_meta"]
    session_model = session_ctx.get("session_model", "")

    capital = cfg["capital"]
    builder_execution_mode = cfg["builder_execution_mode"]
    orchestration_mode = cfg["orchestration_mode"]
    builder_flow_analysis_enabled = cfg["builder_flow_analysis_enabled"]
    # NB: universe_meta volontairement absent — disponible dans session_summary.json
    # sur disque (cf. _AUTONOMOUS_HISTORY_PURGED_KEYS). Sa presence dans l'historique
    # faisait grossir le supervisor_state de ~36 KB par entry.
    history_entry_base = {
        **_HISTORY_ENTRY_METRIC_DEFAULTS,
        "session_num": session_num,
        "objective": objective,
        "source_label": source_label,
        "duration": duration,
        "session_duration_seconds": duration,
        "start_time": session_started_at.isoformat(),
        "started_at": session_started_at.isoformat(),
        "end_time": session_finished_at.isoformat(),
        "finished_at": session_finished_at.isoformat(),
        "symbol": session_symbol,
        "timeframe": session_timeframe,
        "universe_mode": autonomous_universe_mode,
        "universe_purpose": "builder_autonomous",
        "universe_strategy_type": autonomous_strategy_type,
        "source_mode": effective_objective_mode,
        "source_reason": objective_mode_policy.get("reason", ""),
        "auto_market_pick_used": effective_auto_market_pick,
        "builder_execution_mode": builder_execution_mode,
        "orchestration_mode": orchestration_mode,
    }

    if session is not None:
        best_return_snapshot = _get_autonomous_session_best_return_snapshot(session)
        final_snapshot = _get_autonomous_session_final_snapshot(session)
        last_runtime_feedback = _extract_autonomous_session_last_runtime_feedback(
            session
        )
        best_score = getattr(session, "best_score", float("-inf"))
        if best_score == float("-inf"):
            best_score = None

        gen_stats = compute_session_generation_stats(session)

        history_entry = {
            **history_entry_base,
            "model_name": getattr(session, "model_name", "") or session_model,
            "generation_stats": gen_stats,
            "status": session.status,
            "best_sharpe": session.best_sharpe,
            "best_telemetry_score": best_score,
            "best_score": best_score,
            **best_return_snapshot,
            **final_snapshot,
            **last_runtime_feedback,
            "n_iterations": len(session.iterations),
            "session_id": session.session_id,
            "start_time": getattr(session, "start_time", session_started_at).isoformat(),
            "started_at": getattr(session, "start_time", session_started_at).isoformat(),
            "n_bars": getattr(session, "n_bars", 0),
            "date_range_start": getattr(session, "date_range_start", ""),
            "date_range_end": getattr(session, "date_range_end", ""),
            "initial_capital": getattr(session, "initial_capital", capital),
            "universe_mode": str(getattr(session, "universe_mode", "") or autonomous_universe_mode),
            "universe_purpose": str(getattr(session, "universe_purpose", "") or "builder_autonomous"),
            "universe_strategy_type": str(
                getattr(session, "universe_strategy_type", "") or autonomous_strategy_type
            ),
            # universe_meta volontairement omis (cf. _AUTONOMOUS_HISTORY_PURGED_KEYS)
            "builder_execution_mode": str(
                getattr(session, "builder_execution_mode", builder_execution_mode)
                or builder_execution_mode
            ),
            "orchestration_mode": str(
                getattr(session, "orchestration_mode", orchestration_mode)
                or orchestration_mode
            ),
            "instrumentation_enabled": bool(
                getattr(session, "instrumentation_enabled", False)
            ),
            "instrumentation_summary": (
                dict(getattr(session, "instrumentation_summary", {}) or {})
                if isinstance(getattr(session, "instrumentation_summary", {}), dict)
                else {}
            ),
            "pipeline_traces_path": str(
                getattr(session, "pipeline_traces_path", "") or ""
            ),
        }
        history.append(history_entry)
        _sync_autonomous_state(history, supervisor, persist=False)
        st.session_state["builder_session"] = session
        _heartbeat_builder_autonomous_runtime(
            last_event="session_done",
            last_session_num=session_num,
            last_session_id=str(session.session_id or ""),
            last_session_status=str(session.status or ""),
            current_session_num=0,
            current_session_id="",
            effective_source_mode=effective_objective_mode,
        )

        if session.status == "failed":
            supervisor["consecutive_failed_sessions"] = int(
                supervisor.get("consecutive_failed_sessions", 0) or 0
            ) + 1
        else:
            supervisor["consecutive_failed_sessions"] = 0
            supervisor["forced_source_mode"] = ""
            supervisor["disable_auto_market_pick_once"] = False
    else:
        history_entry = {
            **history_entry_base,
            "model_name": session_model,
            "generation_stats": {"total": 0, "canonical": 0, "deterministic": 0, "canonical_rate": 0.0},
            "status": "error",
            "n_iterations": 0,
            "session_id": "",
            "n_bars": len(session_df) if session_df is not None else 0,
            "date_range_start": "",
            "date_range_end": "",
            "initial_capital": capital,
            "error": session_error_message,
            "instrumentation_enabled": builder_flow_analysis_enabled,
            "instrumentation_summary": {},
            "pipeline_traces_path": "",
        }
        history_entry = _recover_autonomous_history_entry_from_disk(history_entry)
        history.append(history_entry)
        _sync_autonomous_state(history, supervisor, persist=False)
        supervisor["consecutive_failed_sessions"] = int(
            supervisor.get("consecutive_failed_sessions", 0) or 0
        ) + 1
        _heartbeat_builder_autonomous_runtime(
            last_event="session_error",
            last_session_num=session_num,
            last_session_status="error",
            current_session_num=0,
            current_session_id="",
            effective_source_mode=effective_objective_mode,
        )

    _sync_autonomous_state(history, supervisor)

    if int(supervisor.get("consecutive_failed_sessions", 0) or 0) >= _AUTONOMOUS_SESSION_FAILURE_RESET_THRESHOLD:
        recovery_plan = _apply_autonomous_supervisor_recovery(
            supervisor,
            history,
            origin="session_failed",
            current_source_mode=effective_objective_mode,
        )
        _sync_autonomous_state(history, supervisor)
        if recovery_plan.get("recover"):
            st.session_state["builder_session"] = None
            st.warning(
                "Superviseur: trop de sessions en échec consécutives, "
                f"reset appliqué ({recovery_plan.get('reason', 'n/a')})."
            )
            _heartbeat_builder_autonomous_runtime(
                last_event="supervisor_recovery",
                effective_source_mode=str(
                    recovery_plan.get("force_source_mode", "") or effective_objective_mode
                ),
            )
        else:
            st.error(
                "Superviseur autonome: budget de reset épuisé après trop "
                "de sessions en échec."
            )
            return "supervisor_stop"

    with recap_placeholder.container():
        _render_autonomous_recap(history, supervisor)

    return None


def _handle_autonomous_loop_crash(
    *,
    exc: Exception,
    exc_tb: str,
    session_num: int,
    session_started_at: "datetime",
    loop_body_start: float,
    effective_objective_mode: str,
    cfg: Dict[str, Any],
    session_model: str,
    consecutive_errors: int,
    max_consecutive_errors: int,
    history: List[Dict[str, Any]],
    supervisor: Dict[str, Any],
    recap_placeholder: Any,
    state: Any,
) -> Tuple[int, Optional[str]]:
    """Gère un crash dans la boucle autonome.

    Retourne ``(consecutive_errors_mis_à_jour, terminal_reason ou None)``.
    """
    builder_execution_mode = cfg["builder_execution_mode"]
    orchestration_mode = cfg["orchestration_mode"]
    builder_flow_analysis_enabled = cfg["builder_flow_analysis_enabled"]
    capital = cfg["capital"]

    consecutive_errors += 1
    failure_origin = _classify_autonomous_failure_origin(exc, exc_tb)
    supervisor["consecutive_errors"] = consecutive_errors
    supervisor["consecutive_failed_sessions"] = int(
        supervisor.get("consecutive_failed_sessions", 0) or 0
    ) + 1
    supervisor["last_error_origin"] = failure_origin
    supervisor["last_error"] = f"{type(exc).__name__}: {exc}"
    logger.error(
        "Session autonome #%d CRASH (%d/%d erreurs consecutives): %s\n%s",
        session_num, consecutive_errors, max_consecutive_errors,
        exc, exc_tb,
    )

    history.append({
        **_HISTORY_ENTRY_METRIC_DEFAULTS,
        "session_num": session_num,
        "objective": "(crash avant execution)",
        "source_label": "Crash avant generation",
        "status": "crash",
        "n_iterations": 0,
        "duration": time.perf_counter() - loop_body_start,
        "session_id": "",
        "started_at": session_started_at.isoformat(),
        "finished_at": datetime.now().isoformat(),
        "n_bars": 0,
        "date_range_start": "",
        "date_range_end": "",
        "initial_capital": capital,
        "symbol": "",
        "timeframe": "",
        "universe_mode": normalize_universe_mode(
            getattr(state, "builder_universe_mode", BUILDER_UNIVERSE_MODE_CANONICAL),
            purpose="builder_autonomous",
        ),
        "universe_purpose": "builder_autonomous",
        "universe_strategy_type": "",
        "universe_meta": {},
        "error": f"{type(exc).__name__}: {exc}",
        "source_mode": effective_objective_mode,
        "source_reason": supervisor.get("last_selected_source_reason", ""),
        "builder_execution_mode": builder_execution_mode,
        "orchestration_mode": orchestration_mode,
        "instrumentation_enabled": builder_flow_analysis_enabled,
        "instrumentation_summary": {},
        "pipeline_traces_path": "",
    })
    _sync_autonomous_state(history, supervisor)
    terminal_error = f"{type(exc).__name__}: {exc}"
    _heartbeat_builder_autonomous_runtime(
        last_event="session_crash",
        last_session_num=session_num,
        last_session_status="crash",
        last_error=terminal_error,
        effective_source_mode=effective_objective_mode,
    )
    try:
        with recap_placeholder.container():
            _render_autonomous_recap(history, supervisor)
    except Exception:
        pass

    st.error(
        f"Session #{session_num} crash: {type(exc).__name__}: {exc} "
        f"-- reprise automatique ({consecutive_errors}/{max_consecutive_errors})"
    )

    if consecutive_errors >= max_consecutive_errors:
        recovery_plan = _apply_autonomous_supervisor_recovery(
            supervisor,
            history,
            origin=failure_origin,
            current_source_mode=effective_objective_mode,
        )
        _sync_autonomous_state(history, supervisor)
        if recovery_plan.get("recover"):
            consecutive_errors = 0
            st.session_state["builder_session"] = None
            st.warning(
                "Superviseur: seuil d'erreurs atteint, reset appliqué "
                f"({recovery_plan.get('reason', 'n/a')})."
            )
            _heartbeat_builder_autonomous_runtime(
                last_event="supervisor_recovery",
                effective_source_mode=str(
                    recovery_plan.get("force_source_mode", "") or effective_objective_mode
                ),
            )
        else:
            logger.error(
                "Arret du mode autonome: %d erreurs consecutives",
                max_consecutive_errors,
            )
            st.error(
                f"Arret de securite: {max_consecutive_errors} erreurs consecutives. "
                f"Verifiez les logs et relancez."
            )
            return consecutive_errors, "consecutive_errors_stop"

    return consecutive_errors, None


# ---------------------------------------------------------------------------
#  Sous-fonction: initialisation runtime de la boucle autonome
# ---------------------------------------------------------------------------

def _init_autonomous_loop_runtime(
    state,
    df,
    status_container,
    *,
    cfg: Dict[str, Any],
    symbol: str,
    timeframe: str,
    all_symbols: List[str],
    all_timeframes: List[str],
    autonomous_resume_ui_state: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Prepare autonomous loop runtime. Returns context dict or None on abort."""
    (
        model, ollama_host, max_iterations, target_sharpe, capital,
        auto_market_pick, orchestration_label, preload_model,
        keep_alive_minutes, unload_after_run, auto_start_ollama,
        builder_execution_mode, orchestration_mode,
        builder_flow_analysis_enabled, builder_flow_analysis_ablation,
        llm_inference_global_settings, llm_inference_model_profiles,
    ) = _BUILDER_RUNTIME_CFG_GETTER(cfg)

    autonomous_runtime_started = True

    def _abort_autonomous_start(reason: str, error: str = "") -> None:
        nonlocal autonomous_runtime_started
        if autonomous_runtime_started:
            mark_builder_autonomous_runtime_stopped(
                reason=reason,
                manual_stop=False,
                error=error,
            )
            autonomous_runtime_started = False
        clear_execution_state(st.session_state)

    # Mode AUTONOME 24/24
    # ══════════════════════════════════════════════════════════════════════
    auto_pause = getattr(state, "builder_auto_pause", 10)
    requested_objective_mode = "llm"

    persisted_supervisor_state = _load_autonomous_supervisor_state()
    persisted_runtime_state = _load_autonomous_runtime_state()

    _market_display = (
        f"{', '.join(all_symbols)} × {', '.join(all_timeframes)}"
        if len(all_symbols) > 1 or len(all_timeframes) > 1
        else f"{symbol} {timeframe}"
    )
    _render_builder_mode_hero(
        mode_label="Autonome 24/24",
        orchestration_label=orchestration_label,
        market_label=_market_display,
        target_sharpe=target_sharpe,
        capital=capital,
        auto_market_pick=auto_market_pick,
        extra_chips=[
            f"Pause: {auto_pause}s",
            "Objectifs: llm-first",
            f"Max itérations/session: {max_iterations}",
        ],
        subtitle="Boucle continue pensée pour garder le contexte, le rythme et le meilleur résultat visibles sans noyer l'écran sous le runtime.",
    )
    autonomous_runtime_lines: List[str] = [
        "Architecture: mono-LLM",
        f"Modèle: `{model}`",
    ]
    _render_builder_runtime_notes("🧩 Détails runtime autonome", autonomous_runtime_lines, expanded=False)

    live_thoughts_panel_placeholder = st.empty()
    live_thoughts_panel_kwargs = {
        "title": "📂 Flux de pensée live (optionnel)",
        "expanded": False,
        "show_terminal_command": True,
        "tail_lines": 180,
    }
    _render_builder_live_thoughts_panel(
        placeholder=live_thoughts_panel_placeholder,
        **live_thoughts_panel_kwargs,
    )

    st.markdown("---")

    single_llm_runtime_prepared = False
    single_llm_prepared_model = ""
    single_llm_prepared_host = ""
    builder_runtime_host, builder_runtime_gpu_target = _resolve_single_llm_runtime_route(
        ollama_host,
        getattr(state, "llm_topology_config", None),
    )

    # Préparer LLM une seule fois pour toute la boucle autonome
    _heartbeat_builder_autonomous_runtime(
        last_event="runtime_prepare",
        last_progress_event="runtime_prepare",
        last_progress_phase="initialisation",
    )
    with st.spinner(f"⏳ Préparation LLM `{model}` ({ollama_host})…"):
        ok, msg, resolved_model, lazy_fallback_used = _prepare_builder_llm_resilient(
            model=model,
            ollama_host=builder_runtime_host,
            gpu_target=builder_runtime_gpu_target or None,
            preload_model=preload_model,
            keep_alive_minutes=keep_alive_minutes,
            auto_start_ollama=auto_start_ollama,
            allow_lazy_fallback=True,
        )
        if ok:
            st.caption(f"✅ {msg}")
            if lazy_fallback_used:
                st.warning(
                    "Préchargement Builder dégradé: lancement maintenu en lazy-load "
                    "pour éviter un blocage de warmup Ollama."
                )
            model = resolved_model
            single_llm_runtime_prepared = True
            single_llm_prepared_model = str(model or "").strip()
            single_llm_prepared_host = _normalize_ollama_host(builder_runtime_host)
        else:
            show_status("error", msg)
            _abort_autonomous_start(
                "single_llm_runtime_prepare_failed",
                msg,
            )
            return None
    objective_indicators = _get_builder_compatible_indicators(df)
    autonomous_resume_ui_state["builder_model_single_llm"] = str(model or "")
    autonomous_resume_ui_state["builder_ollama_host"] = str(builder_runtime_host or "")
    _heartbeat_builder_autonomous_runtime(
        last_event="runtime_ready",
        last_progress_event="runtime_ready",
        last_progress_phase="initialisation",
        model=str(model or ""),
        ollama_host=str(builder_runtime_host or ""),
        requested_source_mode=str(requested_objective_mode or ""),
        auto_market_pick=bool(auto_market_pick),
        resume_ui_state=autonomous_resume_ui_state,
    )

    # Historique des sessions autonomes — initialisation unique
    if "builder_autonomous_history" not in st.session_state:
        _sync_autonomous_state(
            list(persisted_supervisor_state.get("history", [])),
            dict(persisted_supervisor_state.get("supervisor", _default_autonomous_supervisor_state())),
            trim=False,
            persist=False,
        )
    history: List[Dict[str, Any]] = st.session_state["builder_autonomous_history"]
    supervisor: Dict[str, Any] = st.session_state["builder_autonomous_supervisor"]

    if history:
        total_sessions_seen = _resolve_autonomous_session_counter_seed(
            history,
            persisted_runtime_state,
        )
        if total_sessions_seen > len(history):
            st.caption(
                f"Reprise superviseur autonome: {len(history)} runs persistés sur "
                f"{total_sessions_seen} sessions exécutées "
                f"({int(supervisor.get('soft_reset_count', 0) or 0)} soft-resets cumulés)"
            )
        else:
            st.caption(
                f"Reprise superviseur autonome: {len(history)} runs persistés "
                f"({int(supervisor.get('soft_reset_count', 0) or 0)} soft-resets cumulés)"
            )

    # Compteur de session
    session_num = _resolve_autonomous_session_counter_seed(
        history,
        persisted_runtime_state,
    )
    recap_placeholder = st.empty()
    session_placeholder = st.empty()
    with recap_placeholder.container():
        _render_autonomous_recap(history, supervisor)
    _consecutive_errors = int(supervisor.get("consecutive_errors", 0) or 0)
    _MAX_CONSECUTIVE_ERRORS = 5  # Arrêt de sécurité après N erreurs consécutives
    terminal_reason = "completed"
    terminal_error = ""

    return {
        "model": model,
        "ollama_host": ollama_host,
        "single_llm_runtime_prepared": single_llm_runtime_prepared,
        "single_llm_prepared_model": single_llm_prepared_model,
        "single_llm_prepared_host": single_llm_prepared_host,
        "builder_runtime_host": builder_runtime_host,
        "builder_runtime_gpu_target": builder_runtime_gpu_target,
        "objective_indicators": objective_indicators,
        "history": history,
        "supervisor": supervisor,
        "session_num": session_num,
        "recap_placeholder": recap_placeholder,
        "session_placeholder": session_placeholder,
        "_consecutive_errors": _consecutive_errors,
        "_MAX_CONSECUTIVE_ERRORS": _MAX_CONSECUTIVE_ERRORS,
        "terminal_reason": terminal_reason,
        "terminal_error": terminal_error,
        "requested_objective_mode": requested_objective_mode,
        "auto_pause": auto_pause,
        "auto_market_pick": auto_market_pick,
        "max_iterations": max_iterations,
        "target_sharpe": target_sharpe,
        "capital": capital,
        "builder_execution_mode": builder_execution_mode,
        "orchestration_mode": orchestration_mode,
        "builder_flow_analysis_enabled": builder_flow_analysis_enabled,
        "builder_flow_analysis_ablation": builder_flow_analysis_ablation,
        "llm_inference_global_settings": llm_inference_global_settings,
        "llm_inference_model_profiles": llm_inference_model_profiles,
        "preload_model": preload_model,
        "keep_alive_minutes": keep_alive_minutes,
        "unload_after_run": unload_after_run,
        "auto_start_ollama": auto_start_ollama,
        "status_container": status_container,
    }

# ---------------------------------------------------------------------------
#  Sous-fonction: finalisation de la boucle autonome
# ---------------------------------------------------------------------------


def _finalize_autonomous_loop(*, ctx: Dict[str, Any]) -> None:
    """Render recap, unload model, sync state after autonomous loop ends."""
    history = ctx["history"]
    supervisor = ctx["supervisor"]
    recap_placeholder = ctx["recap_placeholder"]
    status_container = ctx["status_container"]
    model = ctx["model"]
    ollama_host = ctx["ollama_host"]
    unload_after_run = ctx["unload_after_run"]
    terminal_reason = ctx["terminal_reason"]
    terminal_error = ctx["terminal_error"]

    # ── Fin de la boucle autonome ──
    with recap_placeholder.container():
        _render_autonomous_recap(history, supervisor)

    with status_container:
        n = len(history)
        best_ever = _history_best_sharpe(history)
        show_status(
            "success" if best_ever > 0 else "info",
            f"Mode autonome terminé : {n} sessions | Meilleur Sharpe: {best_ever:.3f}",
        )

    if unload_after_run and terminal_reason != "manual_stop":
        with st.spinner(f"💾 Déchargement du modèle `{model}`…"):
            if _unload_ollama_model(model=model, ollama_host=ollama_host):
                st.caption(f"✅ Modèle `{model}` déchargé")
            else:
                st.warning(f"⚠️ Impossible de décharger `{model}`")

    _sync_autonomous_state(history, supervisor)
    clear_execution_state(st.session_state)
    mark_builder_autonomous_runtime_stopped(
        reason=terminal_reason,
        manual_stop=(terminal_reason == "manual_stop"),
        error=terminal_error,
    )


def _execute_builder_autonomous_loop(
    state: Any,
    df: Any,
    status_container: Any,
    *,
    cfg: Dict[str, Any],
    symbol: str,
    timeframe: str,
    all_symbols: List[str],
    all_timeframes: List[str],
    fees_bps: float,
    slippage_bps: float,
    autonomous_resume_ui_state: Dict[str, Any],
) -> None:
    """Exécute la boucle autonome 24/24 du Builder."""
    ctx = _init_autonomous_loop_runtime(
        state, df, status_container,
        cfg=cfg, symbol=symbol, timeframe=timeframe,
        all_symbols=all_symbols, all_timeframes=all_timeframes,
        autonomous_resume_ui_state=autonomous_resume_ui_state,
    )
    if ctx is None:
        return

    # Unpack runtime context
    model = ctx["model"]
    ollama_host = ctx["ollama_host"]
    single_llm_runtime_prepared = ctx["single_llm_runtime_prepared"]
    single_llm_prepared_model = ctx["single_llm_prepared_model"]
    single_llm_prepared_host = ctx["single_llm_prepared_host"]
    builder_runtime_host = ctx["builder_runtime_host"]
    builder_runtime_gpu_target = ctx["builder_runtime_gpu_target"]
    objective_indicators = ctx["objective_indicators"]
    history = ctx["history"]
    supervisor = ctx["supervisor"]
    session_num = ctx["session_num"]
    recap_placeholder = ctx["recap_placeholder"]
    session_placeholder = ctx["session_placeholder"]
    _consecutive_errors = ctx["_consecutive_errors"]
    _MAX_CONSECUTIVE_ERRORS = ctx["_MAX_CONSECUTIVE_ERRORS"]
    terminal_reason = ctx["terminal_reason"]
    terminal_error = ctx["terminal_error"]
    requested_objective_mode = ctx["requested_objective_mode"]
    auto_pause = ctx["auto_pause"]
    auto_market_pick = ctx["auto_market_pick"]
    max_iterations = ctx["max_iterations"]
    target_sharpe = ctx["target_sharpe"]
    capital = ctx["capital"]
    builder_execution_mode = ctx["builder_execution_mode"]
    orchestration_mode = ctx["orchestration_mode"]
    builder_flow_analysis_enabled = ctx["builder_flow_analysis_enabled"]
    builder_flow_analysis_ablation = ctx["builder_flow_analysis_ablation"]
    llm_inference_global_settings = ctx["llm_inference_global_settings"]
    llm_inference_model_profiles = ctx["llm_inference_model_profiles"]
    preload_model = ctx["preload_model"]
    keep_alive_minutes = ctx["keep_alive_minutes"]
    unload_after_run = ctx["unload_after_run"]
    auto_start_ollama = ctx["auto_start_ollama"]
    status_container = ctx["status_container"]

    while st.session_state.get("is_running", False):
        if st.session_state.get("stop_requested", False):
            terminal_reason = "manual_stop"
            break
        session_num += 1
        # Rafraîchir le flux de pensée live dès le début de chaque nouvelle session
        # (ThoughtStream vient de réinitialiser _live_thoughts.md)
        _refresh_live_thoughts_code_slot(tail_lines=180)
        _loop_body_start = time.perf_counter()
        session_started_at = datetime.now()
        effective_objective_mode = requested_objective_mode
        effective_auto_market_pick = auto_market_pick
        session_model = model
        session_llm_host = builder_runtime_host
        session_llm_gpu_target = builder_runtime_gpu_target
        session_phase_llm_clients: Dict[str, Any] = {}
        llm_client_for_obj = None
        llm_client_for_market = None

        # ── Protection globale : toute exception est rattrapee pour continuer ──
        try:

            # ── Extraire les marchés récents pour forcer la diversité ──
            _recent_markets: list[tuple[str, str]] = [
                (str(h.get("symbol", "")), str(h.get("timeframe", "")))
                for h in history[-6:]
                if h.get("symbol") and h.get("timeframe")
            ]

            # ── DIAG: Historique de diversité ──
            logger.info(
                "🔍 [DIAG] Session #%d | Historique total: %d runs | Marchés récents (6 derniers): %s",
                session_num,
                len(history),
                _recent_markets if _recent_markets else "❌ VIDE (premier run ou historique perdu)",
            )

            objective_mode_policy = _choose_autonomous_objective_mode(
                requested_objective_mode,
                history,
                supervisor,
            )
            effective_objective_mode = str(
                objective_mode_policy.get("mode", requested_objective_mode) or requested_objective_mode
            )
            supervisor["last_selected_source_mode"] = effective_objective_mode
            supervisor["last_selected_source_reason"] = str(
                objective_mode_policy.get("reason", "") or ""
            )

            auto_market_policy = _resolve_autonomous_auto_market_pick(
                auto_market_pick,
                supervisor,
            )
            effective_auto_market_pick = bool(auto_market_policy.get("enabled"))
            if (
                not effective_auto_market_pick
                and auto_market_policy.get("reason") == "recovery_guard_once"
            ):
                supervisor["disable_auto_market_pick_once"] = False

            st.caption(
                f"Session #{session_num} | source={effective_objective_mode} "
                f"({objective_mode_policy.get('reason', 'n/a')}) | "
                f"auto_marché={'ON' if effective_auto_market_pick else 'OFF'} "
                f"({auto_market_policy.get('reason', 'n/a')})"
            )
            logger.info(
                "builder_autonomous_policy session=%d source_mode=%s source_reason=%s auto_market=%s auto_market_reason=%s",
                session_num,
                effective_objective_mode,
                objective_mode_policy.get("reason", ""),
                effective_auto_market_pick,
                auto_market_policy.get("reason", ""),
            )
            _heartbeat_builder_autonomous_runtime(
                last_event="session_start",
                last_session_num=session_num,
                current_session_num=session_num,
                current_session_id="",
                last_session_status="starting",
                effective_source_mode=effective_objective_mode,
                auto_market_pick=effective_auto_market_pick,
            )

            if st.session_state.get("stop_requested", False):
                terminal_reason = "manual_stop"
                break

            reuse_prepared_runtime = (
                session_num == 1
                and single_llm_runtime_prepared
                and str(model or "").strip() == single_llm_prepared_model
                and _normalize_ollama_host(session_llm_host) == single_llm_prepared_host
            )
            if reuse_prepared_runtime:
                st.caption(
                    f"♻️ Runtime LLM déjà préparé — réutilisation pour la session #{session_num}."
                )
                session_model = model
            else:
                with st.spinner(f"⏳ Vérification LLM session #{session_num}…"):
                    ok, msg, resolved_model = _prepare_builder_llm(
                        model=model,
                        ollama_host=session_llm_host,
                        gpu_target=session_llm_gpu_target or None,
                        preload_model=False if single_llm_runtime_prepared else preload_model,
                        keep_alive_minutes=keep_alive_minutes,
                        auto_start_ollama=auto_start_ollama,
                    )
                    if not ok:
                        raise RuntimeError(msg)
                    if resolved_model != model:
                        st.caption(
                            f"ℹ️ Modèle effectif session #{session_num}: `{resolved_model}`"
                        )
                        model = resolved_model
                    session_model = model
                    single_llm_runtime_prepared = True
                    single_llm_prepared_model = str(model or "").strip()
                    single_llm_prepared_host = _normalize_ollama_host(session_llm_host)

            llm_config_shared = build_builder_base_llm_config(
                model=model,
                ollama_host=session_llm_host,
                keep_alive_minutes=keep_alive_minutes,
                llm_inference_global_settings=llm_inference_global_settings,
                llm_inference_model_profiles=llm_inference_model_profiles,
            )
            if effective_objective_mode == "llm":
                llm_client_for_obj = create_llm_client(llm_config_shared)
            if effective_auto_market_pick:
                llm_client_for_market = create_llm_client(llm_config_shared)
            # ── Générer l'objectif ──
            source_label = "LLM"
            if effective_objective_mode == "llm" and llm_client_for_obj is not None:
                with st.spinner("🧠 Génération de l'objectif par LLM..."):
                    objective = generate_llm_objective(
                        llm_client_for_obj,
                        symbol=None if effective_auto_market_pick else all_symbols,
                        timeframe=None if effective_auto_market_pick else all_timeframes,
                        available_indicators=objective_indicators,
                        recent_markets=_recent_markets or None,
                    )
            else:
                source_label = "Fallback simple"
                objective = generate_random_objective(
                    symbol=("{symbol}" if effective_auto_market_pick else all_symbols),
                    timeframe=("{timeframe}" if effective_auto_market_pick else all_timeframes),
                    available_indicators=objective_indicators,
                )
            objective = sanitize_objective_text(objective)
            st.caption(f"Generation objectif: {source_label}")

            session_symbol = symbol
            session_timeframe = timeframe
            if effective_auto_market_pick:
                session_symbol, session_timeframe = _pick_non_recent_market(
                    all_symbols,
                    all_timeframes,
                    _recent_markets,
                )
            default_session_symbol = session_symbol
            default_session_timeframe = session_timeframe
            session_df = df
            if effective_auto_market_pick:
                session_df, pre_load_error, pre_data_source = _load_builder_market_data(
                    state=state,
                    symbol=default_session_symbol,
                    timeframe=default_session_timeframe,
                    fallback_df=df,
                )
                if pre_load_error:
                    logger.warning(
                        "🔍 [DIAG] Default session market preload failed for %s %s: %s (source=%s)",
                        default_session_symbol,
                        default_session_timeframe,
                        pre_load_error,
                        pre_data_source,
                    )
            market_pick: Dict[str, Any] = {}
            autonomous_universe_mode = normalize_universe_mode(
                getattr(state, "builder_universe_mode", BUILDER_UNIVERSE_MODE_CANONICAL),
                purpose="builder_autonomous",
            )
            autonomous_strategy_type = infer_strategy_type(
                strategy_key=str(getattr(state, "strategy_key", "") or ""),
                objective=objective,
            )
            if effective_auto_market_pick:
                spinner_label = (
                    "🧭 Sélection automatique du marché (token/TF)…"
                    if effective_objective_mode == "llm" and llm_client_for_market is not None
                    else "🧭 Sélection automatique du marché (fallback déterministe)…"
                )
                with st.spinner(spinner_label):
                    session_symbol, session_timeframe, session_df, market_pick = _select_autonomous_market_for_session(
                        state=state,
                        objective=objective,
                        objective_mode=effective_objective_mode,
                        use_auto_market_pick=effective_auto_market_pick,
                        llm_client=llm_client_for_market,
                        default_symbol=default_session_symbol,
                        default_timeframe=default_session_timeframe,
                        fallback_df=session_df,
                        recent_markets=_recent_markets or None,
                    )
                confidence = float(market_pick.get("confidence", 0.0) or 0.0)
                source = str(market_pick.get("source", "") or "")
                data_source = str(market_pick.get("data_source", "") or "")
                reason = str(market_pick.get("reason", "") or "")

                # Détection override UI
                is_override = (
                    default_session_symbol and default_session_timeframe and
                    (
                        session_symbol != default_session_symbol
                        or session_timeframe != default_session_timeframe
                    )
                )

                if is_override:
                    # UI warning pour override explicite
                    st.warning(
                        f"🔄 **Override LLM** : {default_session_symbol} {default_session_timeframe} → {session_symbol} {session_timeframe}\n\n"
                        f"**Raison:** {reason}\n\n"
                        f"*Source: {source} | Confidence: {confidence:.2f}*"
                    )
                    # Log structuré override
                    logger.info(
                        "Market selection: source=llm_override, original=%s %s, final=%s %s, reason=%s, confidence=%.2f",
                        default_session_symbol,
                        default_session_timeframe,
                        session_symbol,
                        session_timeframe,
                        reason,
                        confidence,
                    )
                else:
                    st.caption(
                        f"🧭 Session #{session_num}: {session_symbol} {session_timeframe} "
                        f"(source={source}, data={data_source}, conf={confidence:.2f})"
                    )

                # ── DIAG: Sélection finale ──
                logger.info(
                    "🔍 [DIAG] Session #%d → Marché sélectionné: %s %s | "
                    "Source: %s | Confidence: %.2f | Data: %s | "
                    "Candidats: %d symbols × %d timeframes",
                    session_num,
                    session_symbol,
                    session_timeframe,
                    source,
                    confidence,
                    data_source,
                    len(market_pick.get("candidate_symbols", [])),
                    len(market_pick.get("candidate_timeframes", [])),
                )
            else:
                # ── DIAG: Mode auto-pick désactivé ──
                logger.info(
                    "🔍 [DIAG] Session #%d → Marché PAR DÉFAUT (auto_market_pick=OFF): %s %s",
                    session_num,
                    session_symbol,
                    session_timeframe,
                )

            autonomous_universe_mode = str(
                market_pick.get("universe_mode") or autonomous_universe_mode
            ).strip() or autonomous_universe_mode
            autonomous_strategy_type = str(
                market_pick.get("universe_strategy_type") or autonomous_strategy_type
            ).strip() or autonomous_strategy_type
            autonomous_universe_meta: Dict[str, Any] = {
                "mode": autonomous_universe_mode,
                "strategy_type": autonomous_strategy_type,
                "criteria": dict(market_pick.get("universe_criteria", {}) or {}),
                "excluded_pairs": list(market_pick.get("universe_exclusions", []) or []),
                "exclusion_summary": dict(
                    market_pick.get("universe_exclusion_summary", {}) or {}
                ),
                "filter_source": str(market_pick.get("universe_filter_source", "") or ""),
                "cache_status": str(market_pick.get("universe_cache_status", "") or ""),
                "market_pick": dict(market_pick),
            }

            # ── Remplacer les placeholders {symbol}/{timeframe} après sélection marché ──
            if "{symbol}" in objective or "{timeframe}" in objective:
                objective = objective.replace("{symbol}", session_symbol)
                objective = objective.replace("{timeframe}", session_timeframe)
                objective = sanitize_objective_text(objective)
                logger.info(
                    "🔍 [DIAG] Placeholders remplacés dans objectif → %s %s",
                    session_symbol,
                    session_timeframe,
                )
            # ── Exécuter la session ──
            if st.session_state.get("stop_requested", False):
                terminal_reason = "manual_stop"
                break
            session_dataset_ok, session_dataset_msg = _validate_builder_market_dataset(
                df=session_df,
                symbol=session_symbol,
                timeframe=session_timeframe,
                universe_mode=autonomous_universe_mode,
                strategy_type=autonomous_strategy_type,
                purpose="builder_autonomous",
                objective=objective,
            )
            session: Any = None
            duration = 0.0
            session_error_message = (
                str(market_pick.get("load_error") or "").strip() or None
            )
            if not session_dataset_ok:
                session_error_message = session_dataset_msg
                st.warning(
                    f"Session #{session_num}: marché rejeté par l'univers `{autonomous_universe_mode}` "
                    f"({session_symbol} {session_timeframe}) - {session_dataset_msg}"
                )
            with session_placeholder.container():
                if session_dataset_ok:
                    t0 = time.perf_counter()
                    session = _run_single_builder_session(
                        objective=objective,
                        model=session_model,
                        ollama_host=session_llm_host,
                        gpu_target=session_llm_gpu_target or None,
                        llm_inference_global_settings=llm_inference_global_settings,
                        llm_inference_model_profiles=llm_inference_model_profiles,
                        llm_topology_config=getattr(state, "llm_topology_config", None),
                        preload_model=preload_model,
                        keep_alive_minutes=keep_alive_minutes,
                        unload_after_run=unload_after_run,
                        auto_start_ollama=auto_start_ollama,
                        max_iterations=max_iterations,
                        target_sharpe=target_sharpe,
                        capital=capital,
                        symbol=session_symbol,
                        timeframe=session_timeframe,
                        fees_bps=fees_bps,
                        slippage_bps=slippage_bps,
                        df=session_df,
                        universe_mode=autonomous_universe_mode,
                        universe_purpose="builder_autonomous",
                        universe_strategy_type=autonomous_strategy_type,
                        universe_meta=autonomous_universe_meta,
                        session_label=f"🔄 Session autonome #{session_num}",
                        skip_llm_prepare=True,
                        show_config_caption=False,
                        autonomous_runtime_watchdog=True,
                        phase_llm_clients=session_phase_llm_clients or None,
                        builder_execution_mode=builder_execution_mode,
                        orchestration_mode=orchestration_mode,
                        builder_flow_analysis_enabled=builder_flow_analysis_enabled,
                        builder_flow_analysis_ablation=builder_flow_analysis_ablation,
                    )
                    duration = time.perf_counter() - t0

            if unload_after_run:
                single_llm_runtime_prepared = False
                single_llm_prepared_model = ""
                single_llm_prepared_host = ""

            # ── Enregistrer le résultat ──
            _session_ctx: Dict[str, Any] = {
                "session_num": session_num,
                "objective": objective,
                "source_label": source_label,
                "duration": duration,
                "started_at": session_started_at,
                "symbol": session_symbol,
                "timeframe": session_timeframe,
                "df": session_df,
                "error_message": session_error_message,
                "effective_objective_mode": effective_objective_mode,
                "objective_mode_policy": objective_mode_policy,
                "effective_auto_market_pick": effective_auto_market_pick,
                "autonomous_universe_mode": autonomous_universe_mode,
                "autonomous_strategy_type": autonomous_strategy_type,
                "autonomous_universe_meta": autonomous_universe_meta,
                "session_model": session_model,
            }
            _record_terminal = _record_autonomous_session_result(
                session=session,
                session_ctx=_session_ctx,
                cfg=cfg,
                history=history,
                supervisor=supervisor,
                recap_placeholder=recap_placeholder,
            )
            if _record_terminal is not None:
                terminal_reason = _record_terminal
                break

        except KeyboardInterrupt:
            logger.info("Mode autonome interrompu par l'utilisateur (KeyboardInterrupt)")
            terminal_reason = "keyboard_interrupt"
            break
        except Exception as _loop_exc:
            _exc_tb = traceback.format_exc()
            _consecutive_errors, _crash_terminal = _handle_autonomous_loop_crash(
                exc=_loop_exc,
                exc_tb=_exc_tb,
                session_num=session_num,
                session_started_at=session_started_at,
                loop_body_start=_loop_body_start,
                effective_objective_mode=effective_objective_mode,
                cfg=cfg,
                session_model=session_model,
                consecutive_errors=_consecutive_errors,
                max_consecutive_errors=_MAX_CONSECUTIVE_ERRORS,
                history=history,
                supervisor=supervisor,
                recap_placeholder=recap_placeholder,
                state=state,
            )
            terminal_error = f"{type(_loop_exc).__name__}: {_loop_exc}"
            if _crash_terminal is not None:
                terminal_reason = _crash_terminal
                break
        else:
            # Session OK -> reset erreurs consecutives
            _consecutive_errors = 0
            supervisor["consecutive_errors"] = 0
            supervisor["next_pause_multiplier"] = 1
            _sync_autonomous_state(history, supervisor)

        # ── Vérifier si on doit continuer ──
        if not st.session_state.get("is_running", False):
            terminal_reason = "manual_stop"
            break

        # ── Pause configurable avec countdown (allongée après crash) ──
        pause_multiplier = int(supervisor.get("next_pause_multiplier", 1) or 1)
        if _consecutive_errors > 0:
            pause_multiplier = max(pause_multiplier, 3)
        effective_pause = auto_pause * max(1, pause_multiplier)
        if effective_pause > 0:
            countdown_placeholder = st.empty()
            for remaining in range(effective_pause, 0, -1):
                if not st.session_state.get("is_running", False):
                    break
                _heartbeat_builder_autonomous_runtime(
                    last_event="countdown",
                    last_progress_event="countdown",
                    last_progress_phase="pause",
                    last_progress_iteration=0,
                )
                countdown_placeholder.info(
                    f"⏱️ Prochaine session dans **{remaining}s**..."
                )
                time.sleep(1)
            try:
                countdown_placeholder.empty()
            except Exception:
                pass
        if int(supervisor.get("next_pause_multiplier", 1) or 1) != 1:
            supervisor["next_pause_multiplier"] = 1
            _sync_autonomous_state(history, supervisor)

    # Finalize: recap, unload, sync
    ctx["terminal_reason"] = terminal_reason
    ctx["terminal_error"] = terminal_error
    ctx["history"] = history
    ctx["supervisor"] = supervisor
    _finalize_autonomous_loop(ctx=ctx)


def _execute_builder_manual_session(
    state: Any,
    df: Any,
    status_container: Any,
    *,
    cfg: Dict[str, Any],
    symbol: str,
    timeframe: str,
    all_symbols: List[str],
    all_timeframes: List[str],
    fees_bps: float,
    slippage_bps: float,
) -> None:
    """Exécute une session Builder manuelle (objectif unique)."""
    (
        model, ollama_host, max_iterations, target_sharpe, capital,
        auto_market_pick, orchestration_label, preload_model,
        keep_alive_minutes, unload_after_run, auto_start_ollama,
        builder_execution_mode, orchestration_mode,
        builder_flow_analysis_enabled, builder_flow_analysis_ablation,
        llm_inference_global_settings, llm_inference_model_profiles,
    ) = _BUILDER_RUNTIME_CFG_GETTER(cfg)

    raw_objective = str(getattr(state, "builder_objective", "") or "")
    objective = sanitize_objective_text(raw_objective)
    if raw_objective.strip() != objective:
        st.warning(
            "Objectif nettoyé automatiquement (des lignes de logs ont été retirées)."
        )
        st.session_state["builder_objective"] = objective
        st.session_state["_builder_objective_input_sync"] = objective
    if not objective.strip():
        with status_container:
            show_status("error", "Objectif vide — décrivez la stratégie souhaitée")
        clear_execution_state(st.session_state)
        return

    _render_builder_mode_hero(
        mode_label="Manuel",
        orchestration_label=orchestration_label,
        market_label=f"{symbol} {timeframe}",
        target_sharpe=target_sharpe,
        capital=capital,
        auto_market_pick=auto_market_pick,
        extra_chips=[f"Max itérations: {max_iterations}"],
        subtitle="Session unique orientée création et lecture rapide des itérations.",
    )
    live_thoughts_panel_placeholder = st.empty()
    live_thoughts_panel_kwargs = {
        "title": "📂 Flux de pensée live (optionnel)",
        "expanded": False,
        "show_terminal_command": True,
        "tail_lines": 180,
    }
    _render_builder_live_thoughts_panel(
        placeholder=live_thoughts_panel_placeholder,
        **live_thoughts_panel_kwargs,
    )

    st.markdown("---")

    run_model = model
    run_ollama_host, run_ollama_gpu_target = _resolve_single_llm_runtime_route(
        ollama_host,
        getattr(state, "llm_topology_config", None),
    )
    run_symbol = symbol
    run_timeframe = timeframe
    run_df = df
    manual_universe_mode = normalize_universe_mode(
        getattr(state, "builder_universe_mode", BUILDER_UNIVERSE_MODE_CANONICAL),
        purpose="builder_manual",
    )
    manual_strategy_type = infer_strategy_type(
        strategy_key=str(getattr(state, "strategy_key", "") or ""),
        objective=objective,
    )
    manual_universe_meta: Dict[str, Any] = {
        "mode": manual_universe_mode,
        "strategy_type": manual_strategy_type,
    }

    if auto_market_pick:
        llm_client_for_market = create_llm_client(
            build_builder_base_llm_config(
                model=run_model,
                ollama_host=run_ollama_host,
                keep_alive_minutes=keep_alive_minutes,
                llm_inference_global_settings=llm_inference_global_settings,
                llm_inference_model_profiles=llm_inference_model_profiles,
            ),
        )
        with st.spinner("🧭 Sélection automatique du marché (token/TF)…"):
            run_symbol, run_timeframe, run_df, market_pick = _pick_market_for_objective(
                state=state,
                objective=objective,
                llm_client=llm_client_for_market,
                default_symbol=symbol,
                default_timeframe=timeframe,
                fallback_df=df,
                purpose="builder_manual",
            )
        manual_universe_meta = {
            "mode": str(market_pick.get("universe_mode") or manual_universe_mode),
            "strategy_type": str(
                market_pick.get("universe_strategy_type") or manual_strategy_type
            ),
            "criteria": dict(market_pick.get("universe_criteria", {}) or {}),
            "excluded_pairs": list(market_pick.get("universe_exclusions", []) or []),
            "exclusion_summary": dict(
                market_pick.get("universe_exclusion_summary", {}) or {}
            ),
            "filter_source": str(market_pick.get("universe_filter_source", "") or ""),
            "cache_status": str(market_pick.get("universe_cache_status", "") or ""),
            "market_pick": dict(market_pick),
        }
        confidence = float(market_pick.get("confidence", 0.0) or 0.0)
        source = str(market_pick.get("source", "") or "")
        data_source = str(market_pick.get("data_source", "") or "")
        st.info(
            f"🧭 Marché sélectionné: `{run_symbol} {run_timeframe}` "
            f"(source: `{source}`, données: `{data_source}`, confiance: {confidence:.2f})."
        )

    manual_dataset_ok, manual_dataset_msg = _validate_builder_market_dataset(
        df=run_df,
        symbol=run_symbol,
        timeframe=run_timeframe,
        universe_mode=manual_universe_mode,
        strategy_type=manual_strategy_type,
        purpose="builder_manual",
        objective=objective,
    )
    if not manual_dataset_ok:
        st.error(
            f"Univers `{manual_universe_mode}`: marché rejeté pour ce run manuel "
            f"({run_symbol} {run_timeframe}). {manual_dataset_msg}"
        )
        clear_execution_state(st.session_state)
        return

    session = _run_single_builder_session(
        objective=objective,
        model=run_model,
        ollama_host=run_ollama_host,
        gpu_target=run_ollama_gpu_target or None,
        llm_inference_global_settings=llm_inference_global_settings,
        llm_inference_model_profiles=llm_inference_model_profiles,
        llm_topology_config=getattr(state, "llm_topology_config", None),
        preload_model=preload_model,
        keep_alive_minutes=keep_alive_minutes,
        unload_after_run=unload_after_run,
        auto_start_ollama=auto_start_ollama,
        max_iterations=max_iterations,
        target_sharpe=target_sharpe,
        capital=capital,
        symbol=run_symbol,
        timeframe=run_timeframe,
        fees_bps=fees_bps,
        slippage_bps=slippage_bps,
        df=run_df,
        universe_mode=manual_universe_mode,
        universe_purpose="builder_manual",
        universe_strategy_type=manual_strategy_type,
        universe_meta=manual_universe_meta,
        builder_execution_mode=builder_execution_mode,
        orchestration_mode=orchestration_mode,
        builder_flow_analysis_enabled=builder_flow_analysis_enabled,
        builder_flow_analysis_ablation=builder_flow_analysis_ablation,
        live_thoughts_panel_placeholder=live_thoughts_panel_placeholder,
        live_thoughts_panel_kwargs=live_thoughts_panel_kwargs,
    )

    if session is not None:
        st.session_state["builder_session"] = session
        st.session_state["builder_last_objective"] = objective
        with status_container:
            show_status(
                "success" if session.status == "success" else "info",
                "Builder terminé: "
                f"{session.status} (Sharpe {_format_optional_float(getattr(session, 'best_sharpe', None), '{:.3f}')})",
            )
    clear_execution_state(st.session_state)
    return

# ---------------------------------------------------------------------------
# Point d'entrée principal
# ---------------------------------------------------------------------------

def render_builder_view(
    state: Any,
    df: Any,
    status_container: Any,
) -> None:
    """
    Rendu principal du mode Strategy Builder.

    Supporte deux modes :
    - **Manuel** : exécute une session unique avec l'objectif saisi
    - **Autonome 24/24** : génère des objectifs automatiquement et boucle
    """
    _inject_builder_view_styles()

    model = state.builder_model_single_llm
    max_iterations = state.builder_max_iterations
    target_sharpe = state.builder_target_sharpe
    ollama_host = str(
        getattr(state, "builder_ollama_host", None)
        or "http://127.0.0.1:11434"
    ).strip()
    ollama_host = _normalize_ollama_host(ollama_host)
    runtime_preferences = resolve_builder_runtime_preferences(state)
    preload_model = bool(runtime_preferences["builder_preload_model"])
    keep_alive_minutes = int(runtime_preferences["builder_keep_alive_minutes"])
    unload_after_run = bool(runtime_preferences["builder_unload_after_run"])
    auto_start_ollama = bool(runtime_preferences["builder_auto_start_ollama"])
    auto_market_pick = bool(getattr(state, "builder_auto_market_pick", False))
    builder_execution_mode = BUILDER_EXECUTION_MODE_MONO
    orchestration_mode = "single_llm"
    flow_analysis_preferences = resolve_builder_flow_analysis_preferences(state)
    builder_flow_analysis_enabled = bool(
        flow_analysis_preferences["builder_flow_analysis_enabled"]
    )
    builder_flow_analysis_ablation = dict(
        flow_analysis_preferences["builder_flow_analysis_ablation"]
    )
    llm_inference_global_settings = normalize_llm_inference_settings(
        getattr(state, "llm_inference_global_settings", None)
    )
    llm_inference_model_profiles = normalize_llm_model_inference_profiles(
        getattr(state, "llm_inference_model_profiles", None)
    )
    st.session_state.pop("builder_runtime_diagnostic", None)
    orchestration_label = "Mono"
    capital_raw = getattr(state, "builder_capital", 10000.0)
    try:
        capital = float(capital_raw)
    except (TypeError, ValueError):
        capital = 10000.0

    # Contexte de marché — si rien n'est sélectionné, on pioche parmi les tokens disponibles
    available_tokens, available_tfs = _resolve_builder_available_market_inventory(
        state
    )

    _raw_symbol = (
        getattr(state, "symbol", None)
        or st.session_state.get("selected_symbol")
        or ""
    )
    _raw_timeframe = (
        getattr(state, "timeframe", None)
        or st.session_state.get("selected_timeframe")
        or ""
    )

    # Fallback intelligent quand rien n'est sélectionné.
    # Évite le biais "premier élément de liste" en utilisant un bootstrap aléatoire stable de session.
    symbol = (
        str(_raw_symbol).strip().upper()
        if _raw_symbol
        else _stable_random_pick("_builder_startup_symbol", available_tokens, "BTCUSDC").upper()
    )
    timeframe = (
        str(_raw_timeframe).strip()
        if _raw_timeframe
        else _stable_random_pick(
            "_builder_startup_timeframe",
            available_tfs,
            "1h",
        )
    )
    if not _is_builder_supported_timeframe(timeframe):
        timeframe = _stable_random_pick(
            "_builder_startup_timeframe",
            available_tfs,
            "1h",
        )

    autonomous = bool(
        getattr(state, "builder_autonomous", False)
        or st.session_state.get("builder_autonomous", False)
        or st.session_state.get("builder_autonomous_toggle", False)
    )
    if autonomous:
        st.session_state["builder_autonomous"] = True
        if not bool(st.session_state.get("builder_autonomous_toggle", False)):
            # Ne jamais écrire directement la clé du widget après instanciation :
            # exec_tabs la resynchronise proprement au prochain rerun.
            st.session_state["_builder_autonomous_toggle_sync"] = True
        try:
            state.builder_autonomous = True
        except Exception:
            logger.debug("builder_autonomous_state_sync_failed", exc_info=True)
    autonomous_running = autonomous and bool(st.session_state.get("is_running", False))

    if auto_market_pick:
        try:
            _call_builder_market_candidates(
                state,
                current_symbol=symbol,
                current_timeframe=timeframe,
                objective=sanitize_objective_text(
                    str(getattr(state, "builder_objective", "") or "")
                ),
                purpose="builder_autonomous" if autonomous else "builder_auto_market",
                fallback_df=None,
            )
        except Exception:
            logger.warning("builder_market_universe_warmup_failed", exc_info=True)

    if autonomous and not autonomous_running:
        auto_pause = int(getattr(state, "builder_auto_pause", 10) or 10)
        persisted_supervisor_state = _load_autonomous_supervisor_state()
        history = st.session_state.get("builder_autonomous_history")
        if not isinstance(history, list):
            history = list(persisted_supervisor_state.get("history", []))
        supervisor = st.session_state.get("builder_autonomous_supervisor")
        if not isinstance(supervisor, dict):
            supervisor = dict(
                persisted_supervisor_state.get(
                    "supervisor",
                    _default_autonomous_supervisor_state(),
                )
            )

        if auto_market_pick:
            if available_tokens and available_tfs:
                market_label = (
                    f"{len(available_tokens)} symboles × "
                    f"{len(available_tfs)} timeframes"
                )
            else:
                market_label = "Univers marché indisponible"
        else:
            market_label = (
                f"{symbol} {timeframe}"
                if symbol and timeframe and symbol != "UNKNOWN"
                else "Aucune présélection"
            )

        _render_builder_mode_hero(
            mode_label="Autonome 24/24",
            orchestration_label=orchestration_label,
            market_label=market_label,
            target_sharpe=target_sharpe,
            capital=capital,
            auto_market_pick=auto_market_pick,
            extra_chips=[
                f"Pause: {auto_pause}s",
                "Objectifs: llm-first",
                f"Max itérations/session: {max_iterations}",
            ],
            subtitle="Mode armé mais inactif: le bootstrap marché et le runtime ne démarrent qu'au lancement.",
        )

        idle_runtime_lines: List[str] = [
            "Architecture: mono-LLM",
            f"Modèle: `{model}`",
        ]
        _render_builder_runtime_notes(
            "🧩 Détails runtime autonome",
            idle_runtime_lines,
            expanded=False,
        )
        st.info(
            "Mode autonome prêt. L'univers marché filtré est préparé; Cliquez sur "
            "Lancer pour préparer le runtime LLM et enchaîner les sessions."
        )
        st.markdown("---")
        _render_autonomous_recap(history, supervisor)
        return

    # ── DIAG: Mode auto-sélection marché ──
    logger.info(
        "🔍 [DIAG] auto_market_pick = %s | Symbole/TF par défaut: %s/%s",
        "✅ ACTIVÉ" if auto_market_pick else "❌ DÉSACTIVÉ",
        symbol,
        timeframe,
    )

    # Listes complètes pour le mode autonome (diversification multi-market).
    # En auto market pick, on ne traite comme "user_*" que les sélections explicites UI.
    if auto_market_pick:
        user_symbols = [
            str(s or "").strip().upper()
            for s in (st.session_state.get("symbols_select", []) or [])
            if str(s or "").strip()
        ]
        user_symbols = [s for s in user_symbols if s in available_tokens]
        user_timeframes = [
            str(tf or "").strip()
            for tf in (st.session_state.get("timeframes_select", []) or [])
            if str(tf or "").strip()
        ]
        user_timeframes = [tf for tf in user_timeframes if tf in available_tfs]
    else:
        user_symbols = list(getattr(state, "symbols", []) or [])
        user_timeframes = list(getattr(state, "timeframes", []) or [])

    # ── ROTATION DIVERSIFIÉE : éviter de toujours tester les mêmes tokens ──
    if not user_symbols and available_tokens:
        # Shuffle pour diversifier (évite biais alphabétique)
        shuffled_tokens = available_tokens.copy()
        random.shuffle(shuffled_tokens)

        # Tracker des marchés récemment testés (pour éviter répétitions)
        if "builder_tested_markets" not in st.session_state:
            st.session_state["builder_tested_markets"] = []

        raw_tested_markets = st.session_state.get("builder_tested_markets", [])
        if isinstance(raw_tested_markets, list):
            tested_markets = [item for item in raw_tested_markets if isinstance(item, dict)]
        else:
            tested_markets = []
        if tested_markets != raw_tested_markets:
            st.session_state["builder_tested_markets"] = tested_markets
        recently_tested_tokens = {
            str(item.get("symbol", "") or "").strip().upper()
            for item in tested_markets[-20:]
            if str(item.get("symbol", "") or "").strip()
        }  # 20 derniers

        # Priorité aux tokens NON récemment testés
        untested_tokens = [t for t in shuffled_tokens if t not in recently_tested_tokens]
        if untested_tokens:
            all_symbols = untested_tokens[:20]  # Top 20 non testés
        else:
            # Tous testés récemment → re-shuffle complet
            all_symbols = shuffled_tokens[:20]

        logger.info(
            "🔄 Rotation tokens: %d disponibles, %d récemment testés, %d sélectionnés pour ce run",
            len(available_tokens),
            len(recently_tested_tokens),
            len(all_symbols),
        )
    else:
        all_symbols = user_symbols if user_symbols else [symbol]

    all_timeframes_raw = user_timeframes if user_timeframes else (available_tfs or [timeframe])
    all_timeframes = _sanitize_builder_timeframes(all_timeframes_raw, fallback=timeframe or "1h")

    # ── DIAG: Univers de sélection ──
    logger.info(
        "🔍 [DIAG] Univers disponible: %d symboles × %d timeframes = %d combinaisons | "
        "Symboles: %s | Timeframes: %s",
        len(all_symbols), len(all_timeframes), len(all_symbols) * len(all_timeframes),
        ", ".join(all_symbols[:10]) + ("..." if len(all_symbols) > 10 else ""),
        ", ".join(all_timeframes),
    )

    fees_bps_raw = getattr(state, "fees_bps", None)
    if fees_bps_raw is None:
        fees_bps_raw = st.session_state.get("fees_bps", 10.0)
    try:
        fees_bps = float(fees_bps_raw)
    except (TypeError, ValueError):
        fees_bps = 10.0

    slippage_bps_raw = getattr(state, "slippage_bps", None)
    if slippage_bps_raw is None:
        slippage_bps_raw = st.session_state.get("slippage_bps", 5.0)
    try:
        slippage_bps = float(slippage_bps_raw)
    except (TypeError, ValueError):
        slippage_bps = 5.0

    autonomous_runtime_started = False
    autonomous_resume_ui_state: Dict[str, Any] = {}

    def _abort_autonomous_start(reason: str, error: str = "") -> None:
        nonlocal autonomous_runtime_started
        if autonomous_runtime_started:
            mark_builder_autonomous_runtime_stopped(
                reason=reason,
                manual_stop=False,
                error=error,
            )
            autonomous_runtime_started = False
        clear_execution_state(st.session_state)

    if autonomous:
        autonomous_resume_ui_state = _build_builder_autonomous_resume_ui_state(state)
        autonomous_resume_ui_state["builder_model_single_llm"] = str(model or "")
        autonomous_resume_ui_state["builder_ollama_host"] = str(ollama_host or "")
        _mark_builder_autonomous_runtime_started(
            model=model,
            ollama_host=ollama_host,
            requested_source_mode="llm",
            auto_market_pick=auto_market_pick,
            resume_ui_state=autonomous_resume_ui_state,
        )
        autonomous_runtime_started = True
        _heartbeat_builder_autonomous_runtime(
            last_event="bootstrap_start",
            last_progress_event="bootstrap_start",
            last_progress_phase="initialisation",
        )

    if (df is None or len(df) == 0) and not autonomous:
        # Mode manuel : on a besoin des données pré-chargées
        # Tenter un chargement automatique si symbol/timeframe sont définis
        if symbol and timeframe and symbol != "UNKNOWN":
            try:
                from data.loader import load_ohlcv
                df = load_ohlcv(symbol, timeframe)
                st.caption(f"📥 Données chargées automatiquement: {symbol} {timeframe}")
            except Exception:
                logger.warning("auto load_ohlcv failed for %s %s", symbol, timeframe, exc_info=True)
        if df is None or len(df) == 0:
            with status_container:
                show_status("error", "Aucune donnée OHLCV chargée — sélectionnez un token et timeframe, ou activez le mode autonome.")
            clear_execution_state(st.session_state)
            return
    elif (df is None or len(df) == 0) and autonomous:
        # Mode autonome: ne jamais bloquer sur une présélection UI vide ou invalide.
        requested_pair_explicit = bool(
            str(_raw_symbol or "").strip() and str(_raw_timeframe or "").strip()
        )
        requested_symbol = symbol
        requested_timeframe = timeframe
        bootstrap_objective = sanitize_objective_text(
            str(getattr(state, "builder_objective", "") or "")
        )
        probe_symbols = list(all_symbols)
        probe_timeframes = list(all_timeframes)
        if auto_market_pick:
            candidate_symbols, candidate_timeframes = _call_builder_market_candidates(
                state,
                current_symbol=requested_symbol,
                current_timeframe=requested_timeframe,
                objective=bootstrap_objective,
                purpose="builder_autonomous",
                fallback_df=df,
            )
            if candidate_symbols:
                probe_symbols = list(candidate_symbols)
            if candidate_timeframes:
                probe_timeframes = list(candidate_timeframes)
            if (
                not requested_pair_explicit
                and probe_symbols
                and probe_timeframes
            ):
                requested_symbol = str(probe_symbols[0] or "").strip().upper()
                requested_timeframe = str(probe_timeframes[0] or "").strip()

        preferred_pairs: List[Tuple[str, str]] = []
        if requested_symbol and requested_timeframe and requested_symbol != "UNKNOWN":
            preferred_pairs.append((requested_symbol, requested_timeframe))

        logger.info(
            "🔍 [DIAG] Startup data probe: trying up to %d pairs",
            min(len(probe_symbols) * len(probe_timeframes), 24),
        )
        _heartbeat_builder_autonomous_runtime(
            last_event="startup_probe",
            last_progress_event="startup_probe",
            last_progress_phase="initialisation",
        )

        symbol, timeframe, df, bootstrap_meta = _find_first_valid_builder_market(
            state=state,
            symbols=probe_symbols,
            timeframes=probe_timeframes,
            default_symbol=requested_symbol,
            default_timeframe=requested_timeframe,
            fallback_df=df,
            preferred_pairs=preferred_pairs,
            max_pairs=24,
            purpose="builder_autonomous",
        )
        if not _has_builder_market_df(df):
            with status_container:
                show_status("error", "Aucune donnée OHLCV disponible pour démarrer le mode autonome.")
                for failure in (bootstrap_meta.get("failures", []) or [])[:2]:
                    st.caption(
                        f"Rejeté: {failure['symbol']} {failure['timeframe']} -> {failure['error']}"
                    )
            _abort_autonomous_start(
                "startup_market_probe_failed",
                "Aucune donnée OHLCV disponible pour démarrer le mode autonome.",
            )
            return
        if (
            preferred_pairs
            and (symbol, timeframe) != preferred_pairs[0]
        ):
            st.warning(
                "⚠️ Présélection marché ignorée en mode autonome. "
                f"{requested_symbol} {requested_timeframe} est indisponible ou rejeté; "
                f"fallback sur {symbol} {timeframe}."
            )
        st.caption(f"📥 Données initiales: {symbol} {timeframe} ({len(df)} barres)")
        _heartbeat_builder_autonomous_runtime(
            last_event="startup_probe_ready",
            last_progress_event="startup_probe_ready",
            last_progress_phase="initialisation",
        )

    # ══════════════════════════════════════════════════════════════════════
    _builder_cfg = dict(
        model=model,
        max_iterations=max_iterations,
        target_sharpe=target_sharpe,
        ollama_host=ollama_host,
        preload_model=preload_model,
        keep_alive_minutes=keep_alive_minutes,
        unload_after_run=unload_after_run,
        auto_start_ollama=auto_start_ollama,
        auto_market_pick=auto_market_pick,
        builder_execution_mode=builder_execution_mode,
        orchestration_mode=orchestration_mode,
        builder_flow_analysis_enabled=builder_flow_analysis_enabled,
        builder_flow_analysis_ablation=builder_flow_analysis_ablation,
        llm_inference_global_settings=llm_inference_global_settings,
        llm_inference_model_profiles=llm_inference_model_profiles,
        orchestration_label=orchestration_label,
        capital=capital,
    )

    # ══════════════════════════════════════════════════════════════════════
    # Mode MANUEL → délégué à _execute_builder_manual_session
    # ══════════════════════════════════════════════════════════════════════
    if not autonomous:
        _execute_builder_manual_session(
            state, df, status_container,
            cfg=_builder_cfg,
            symbol=symbol,
            timeframe=timeframe,
            all_symbols=all_symbols,
            all_timeframes=all_timeframes,
            fees_bps=fees_bps,
            slippage_bps=slippage_bps,
        )
        return

    # ══════════════════════════════════════════════════════════════════════
    # Mode AUTONOME → délégué à _execute_builder_autonomous_loop
    # ══════════════════════════════════════════════════════════════════════
    _execute_builder_autonomous_loop(
        state, df, status_container,
        cfg=_builder_cfg,
        symbol=symbol,
        timeframe=timeframe,
        all_symbols=all_symbols,
        all_timeframes=all_timeframes,
        fees_bps=fees_bps,
        slippage_bps=slippage_bps,
        autonomous_resume_ui_state=autonomous_resume_ui_state,
    )
