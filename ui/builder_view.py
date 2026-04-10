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

import csv
import html
import inspect
import io
import json
import logging
import math
import os
import random
import threading
import time
import traceback
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import streamlit as st

import httpx

from agents.llm_config import (
    apply_llm_inference_settings,
    normalize_llm_inference_settings,
    normalize_llm_model_inference_profiles,
)
from config.market_selection import (
    UNIVERSE_MODE_CANONICAL,
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

from agents.llm_client import LLMConfig, LLMProvider, create_llm_client
from agents.model_config import is_cloud_only_model
from agents.ollama_manager import ensure_ollama_running, probe_model_runtime_acceptance
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
from agents.thought_stream import STREAM_FILE
from ui.helpers import _maybe_auto_save_run, safe_load_data, show_status

try:
    from core.llm_multi import (
        DEFAULT_MULTI_LLM_PROFILE,
        MultiLLMSessionManager,
        discover_local_models,
    )
    from core.llm_multi.roles import SIMPLE_MULTI_LLM_ACTIVE_ROLES

    _MULTI_LLM_RUNTIME_AVAILABLE = True
except ImportError:
    DEFAULT_MULTI_LLM_PROFILE = "24GB_balanced"
    _MULTI_LLM_RUNTIME_AVAILABLE = False
    discover_local_models = None
    SIMPLE_MULTI_LLM_ACTIVE_ROLES = (
        "idea_llm",
        "builder_llm",
        "critic_llm",
        "risk_llm",
    )

from ui.state import (
    BUILDER_UNIVERSE_MODE_CANONICAL,
    BUILDER_EXECUTION_MODE_DUAL_LANE,
    BUILDER_EXECUTION_MODE_EXPERT,
    BUILDER_EXECUTION_MODE_MONO,
    normalize_builder_multi_llm_role_pool_overrides,
    resolve_builder_execution_preferences,
    resolve_builder_flow_analysis_preferences,
    resolve_builder_runtime_preferences,
)


_AUTONOMOUS_SUPERVISOR_STATE_FILE = SANDBOX_ROOT / "_autonomous_supervisor_state.json"
_AUTONOMOUS_RUNTIME_STATE_FILE = SANDBOX_ROOT / "_autonomous_runtime_state.json"
_BUILDER_SESSION_SUMMARY_PATCH_LOCK = threading.Lock()
_AUTONOMOUS_SUPERVISOR_VERSION = "1.0"
_AUTONOMOUS_RUNTIME_VERSION = "1.0"
_AUTONOMOUS_MAX_PERSISTED_HISTORY = 1000
_AUTONOMOUS_STATE_SAVE_RETRIES = 3
_AUTONOMOUS_STATE_SAVE_RETRY_DELAY_SEC = 0.05
_AUTONOMOUS_SUPERVISOR_STATE_LOCK = threading.Lock()
_AUTONOMOUS_RUNTIME_STATE_LOCK = threading.Lock()
_AUTONOMOUS_SESSION_FAILURE_RESET_THRESHOLD = 4
_AUTONOMOUS_MAX_SOFT_RESETS = 3
_AUTONOMOUS_SOFT_RESET_WINDOW_SECONDS = 2 * 60 * 60
_AUTONOMOUS_HARDENED_COOLDOWN_MULTIPLIER = 8
_AUTONOMOUS_SOURCE_MODES = ("llm", "fallback")
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
    border-radius: 14px;
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
        f"Auto-marché: {'ON' if auto_market_pick else 'OFF'}",
    ]
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
        "started_at": "",
        "last_heartbeat_at": "",
        "last_resume_at": "",
        "last_event": "",
        "last_error": "",
        "last_stop_reason": "",
        "last_session_num": 0,
        "last_session_id": "",
        "last_session_status": "",
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


def _trim_autonomous_history(
    history: List[Dict[str, Any]],
    *,
    limit: int = _AUTONOMOUS_MAX_PERSISTED_HISTORY,
) -> List[Dict[str, Any]]:
    items = list(history or [])
    if len(items) <= limit:
        return items
    return items[-limit:]


def _load_autonomous_supervisor_state() -> Dict[str, Any]:
    payload = {
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

    raw_iterations = summary.get("iterations", [])
    iterations = raw_iterations if isinstance(raw_iterations, list) else []
    for row in iterations:
        if not isinstance(row, dict):
            continue
        current_return_raw = row.get("return_pct")
        try:
            current_return = float(current_return_raw)
        except Exception:
            continue
        if best_return is None or current_return > best_return:
            best_return = current_return
            best_row = row

    if best_row is not None:
        return {
            "best_return": best_return,
            "best_return_iteration": best_row.get("iteration"),
            "best_max_dd": best_row.get("max_drawdown_pct"),
            "best_pf": best_row.get("profit_factor"),
            "best_trades": best_row.get("trades"),
            "best_return_sharpe": best_row.get("sharpe"),
            "best_total_pnl": best_row.get("total_pnl"),
        }

    leaderboard = summary.get("leaderboard", [])
    if isinstance(leaderboard, list):
        for row in leaderboard:
            if not isinstance(row, dict):
                continue
            return {
                "best_return": row.get("return_pct"),
                "best_return_iteration": row.get("iteration"),
                "best_max_dd": row.get("max_drawdown_pct"),
                "best_pf": row.get("profit_factor"),
                "best_trades": row.get("trades"),
                "best_return_sharpe": row.get("sharpe"),
                "best_total_pnl": row.get("total_pnl"),
            }

    return {
        "best_return": None,
        "best_return_iteration": None,
        "best_max_dd": None,
        "best_pf": None,
        "best_trades": None,
        "best_return_sharpe": None,
        "best_total_pnl": None,
    }


def _extract_final_iteration_snapshot_from_session_summary(
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    raw_iterations = summary.get("iterations", [])
    iterations = raw_iterations if isinstance(raw_iterations, list) else []
    for row in reversed(iterations):
        if not isinstance(row, dict):
            continue
        return {
            "final_return": row.get("return_pct"),
            "final_iteration": row.get("iteration"),
            "final_max_dd": row.get("max_drawdown_pct"),
            "final_pf": row.get("profit_factor"),
            "final_trades": row.get("trades"),
            "final_sharpe": row.get("sharpe"),
            "final_total_pnl": row.get("total_pnl"),
        }

    leaderboard = summary.get("leaderboard", [])
    if isinstance(leaderboard, list):
        for row in leaderboard:
            if not isinstance(row, dict):
                continue
            return {
                "final_return": row.get("return_pct"),
                "final_iteration": row.get("iteration"),
                "final_max_dd": row.get("max_drawdown_pct"),
                "final_pf": row.get("profit_factor"),
                "final_trades": row.get("trades"),
                "final_sharpe": row.get("sharpe"),
                "final_total_pnl": row.get("total_pnl"),
            }

    return {
        "final_return": None,
        "final_iteration": None,
        "final_max_dd": None,
        "final_pf": None,
        "final_trades": None,
        "final_sharpe": None,
        "final_total_pnl": None,
    }


def _extract_last_runtime_feedback_from_session_summary(
    summary: Dict[str, Any],
) -> Dict[str, Any]:
    runtime_error = str(summary.get("last_runtime_error") or "").strip()
    runtime_traceback_tail = str(
        summary.get("last_runtime_traceback_tail") or ""
    ).strip()
    runtime_iteration = summary.get("last_runtime_error_iteration")
    if runtime_error or runtime_traceback_tail:
        return {
            "last_runtime_error": runtime_error or None,
            "last_runtime_error_iteration": runtime_iteration,
            "last_runtime_traceback_tail": runtime_traceback_tail or None,
        }

    raw_iterations = summary.get("iterations", [])
    iterations = raw_iterations if isinstance(raw_iterations, list) else []
    for row in reversed(iterations):
        if not isinstance(row, dict):
            continue
        phase_feedback = row.get("phase_feedback")
        if not isinstance(phase_feedback, dict):
            continue
        backtest_feedback = phase_feedback.get("backtest")
        if not isinstance(backtest_feedback, dict):
            continue
        runtime_error = str(backtest_feedback.get("runtime_error") or "").strip()
        runtime_traceback_tail = str(
            backtest_feedback.get("runtime_traceback_tail") or ""
        ).strip()
        if runtime_error or runtime_traceback_tail:
            return {
                "last_runtime_error": runtime_error or None,
                "last_runtime_error_iteration": row.get("iteration"),
                "last_runtime_traceback_tail": runtime_traceback_tail or None,
            }

    return {
        "last_runtime_error": None,
        "last_runtime_error_iteration": None,
        "last_runtime_traceback_tail": None,
    }


def _extract_autonomous_session_last_runtime_feedback(session: Any) -> Dict[str, Any]:
    iterations = getattr(session, "iterations", []) or []
    for iteration in reversed(iterations):
        phase_feedback = getattr(iteration, "phase_feedback", {}) or {}
        if not isinstance(phase_feedback, dict):
            continue
        backtest_feedback = phase_feedback.get("backtest") or {}
        if not isinstance(backtest_feedback, dict):
            continue
        runtime_error = str(backtest_feedback.get("runtime_error") or "").strip()
        runtime_traceback_tail = str(
            backtest_feedback.get("runtime_traceback_tail") or ""
        ).strip()
        if runtime_error or runtime_traceback_tail:
            return {
                "last_runtime_error": runtime_error or None,
                "last_runtime_error_iteration": getattr(iteration, "iteration", None),
                "last_runtime_traceback_tail": runtime_traceback_tail or None,
            }

    return {
        "last_runtime_error": None,
        "last_runtime_error_iteration": None,
        "last_runtime_traceback_tail": None,
    }


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
    raw_iterations = summary.get("iterations", [])
    iterations = raw_iterations if isinstance(raw_iterations, list) else []

    recovered["session_id"] = session_id
    recovered["n_iterations"] = int(summary.get("total_iterations") or len(iterations) or 0)
    recovered["best_sharpe"] = summary.get("best_sharpe")
    recovered["best_telemetry_score"] = summary.get(
        "best_telemetry_score",
        summary.get("best_score"),
    )
    recovered["best_score"] = recovered["best_telemetry_score"]
    recovered["best_return"] = recovered_snapshot.get("best_return")
    recovered["best_return_iteration"] = recovered_snapshot.get("best_return_iteration")
    recovered["best_max_dd"] = recovered_snapshot.get("best_max_dd")
    recovered["best_pf"] = recovered_snapshot.get("best_pf")
    recovered["best_trades"] = recovered_snapshot.get("best_trades")
    recovered["best_return_sharpe"] = recovered_snapshot.get("best_return_sharpe")
    recovered["best_total_pnl"] = recovered_snapshot.get("best_total_pnl")
    recovered["final_return"] = final_snapshot.get("final_return")
    recovered["final_iteration"] = final_snapshot.get("final_iteration")
    recovered["final_max_dd"] = final_snapshot.get("final_max_dd")
    recovered["final_pf"] = final_snapshot.get("final_pf")
    recovered["final_trades"] = final_snapshot.get("final_trades")
    recovered["final_sharpe"] = final_snapshot.get("final_sharpe")
    recovered["final_total_pnl"] = final_snapshot.get("final_total_pnl")
    recovered["n_bars"] = summary.get("n_bars") or recovered.get("n_bars") or _extract_autonomous_bar_count_from_summary(summary)
    recovered["date_range_start"] = summary.get("date_range_start") or recovered.get("date_range_start")
    recovered["date_range_end"] = summary.get("date_range_end") or recovered.get("date_range_end")
    recovered["initial_capital"] = summary.get("initial_capital") or recovered.get("initial_capital")
    recovered["universe_mode"] = (
        summary.get("universe_mode")
        or recovered.get("universe_mode")
        or BUILDER_UNIVERSE_MODE_CANONICAL
    )
    recovered["universe_purpose"] = (
        summary.get("universe_purpose")
        or recovered.get("universe_purpose")
        or "builder_autonomous"
    )
    recovered["universe_strategy_type"] = (
        summary.get("universe_strategy_type")
        or recovered.get("universe_strategy_type")
        or ""
    )
    recovered["universe_meta"] = (
        dict(summary.get("universe_meta", {}) or {})
        if isinstance(summary.get("universe_meta"), dict)
        else dict(recovered.get("universe_meta", {}) or {})
    )
    recovered["builder_execution_mode"] = (
        summary.get("builder_execution_mode")
        or recovered.get("builder_execution_mode")
        or BUILDER_EXECUTION_MODE_MONO
    )
    recovered["orchestration_mode"] = (
        summary.get("orchestration_mode")
        or recovered.get("orchestration_mode")
        or "single_llm"
    )
    recovered["instrumentation_enabled"] = bool(
        summary.get("instrumentation_enabled", recovered.get("instrumentation_enabled", False))
    )
    recovered["instrumentation_summary"] = (
        dict(summary.get("instrumentation_summary", {}) or {})
        if isinstance(summary.get("instrumentation_summary"), dict)
        else dict(recovered.get("instrumentation_summary", {}) or {})
    )
    recovered["pipeline_traces_path"] = str(
        summary.get("pipeline_traces_path")
        or recovered.get("pipeline_traces_path")
        or ""
    )
    recovered["multi_llm_router_decision"] = (
        dict(summary.get("multi_llm_router_decision", {}) or {})
        if isinstance(summary.get("multi_llm_router_decision"), dict)
        else dict(recovered.get("multi_llm_router_decision", {}) or {})
    )
    recovered["multi_llm_role_outputs"] = (
        dict(summary.get("multi_llm_role_outputs", {}) or {})
        if isinstance(summary.get("multi_llm_role_outputs"), dict)
        else dict(recovered.get("multi_llm_role_outputs", {}) or {})
    )
    recovered["multi_llm_shared_memory"] = (
        dict(summary.get("multi_llm_shared_memory", {}) or {})
        if isinstance(summary.get("multi_llm_shared_memory"), dict)
        else dict(recovered.get("multi_llm_shared_memory", {}) or {})
    )
    recovered["continuity_context"] = (
        dict(summary.get("continuity_context", {}) or {})
        if isinstance(summary.get("continuity_context"), dict)
        else dict(recovered.get("continuity_context", {}) or {})
    )
    recovered["last_runtime_error"] = (
        recovered.get("last_runtime_error")
        or runtime_feedback.get("last_runtime_error")
    )
    recovered["last_runtime_error_iteration"] = (
        recovered.get("last_runtime_error_iteration")
        or runtime_feedback.get("last_runtime_error_iteration")
    )
    recovered["last_runtime_traceback_tail"] = (
        recovered.get("last_runtime_traceback_tail")
        or runtime_feedback.get("last_runtime_traceback_tail")
    )
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
    should_resume = bool(payload.get("active")) and not bool(payload.get("manual_stop"))
    return should_resume, payload


def _build_builder_autonomous_resume_ui_state(state: Any) -> Dict[str, Any]:
    role_overrides = normalize_builder_multi_llm_role_pool_overrides(
        getattr(state, "builder_multi_llm_role_overrides", {}) or {}
    )
    return {
        "builder_execution_mode": str(
            getattr(state, "builder_execution_mode", "mono_single_llm")
            or "mono_single_llm"
        ),
        "builder_model_single_llm": str(
            getattr(state, "builder_model_single_llm", "") or ""
        ),
        "builder_ollama_host": str(
            getattr(state, "builder_ollama_host", "") or ""
        ),
        "builder_auto_pause": int(getattr(state, "builder_auto_pause", 10) or 10),
        "builder_auto_use_llm": bool(getattr(state, "builder_auto_use_llm", True)),
        "builder_auto_market_pick": bool(
            getattr(state, "builder_auto_market_pick", False)
        ),
        "builder_universe_mode": str(
            getattr(state, "builder_universe_mode", BUILDER_UNIVERSE_MODE_CANONICAL)
            or BUILDER_UNIVERSE_MODE_CANONICAL
        ),
        "builder_preload_model": bool(
            getattr(state, "builder_preload_model", True)
        ),
        "builder_keep_alive_minutes": int(
            getattr(state, "builder_keep_alive_minutes", 20) or 20
        ),
        "builder_unload_after_run": bool(
            getattr(state, "builder_unload_after_run", True)
        ),
        "builder_auto_start_ollama": bool(
            getattr(state, "builder_auto_start_ollama", True)
        ),
        "builder_multi_llm_enabled": bool(
            getattr(state, "builder_multi_llm_enabled", False)
        ),
        "builder_multi_llm_profile": str(
            getattr(state, "builder_multi_llm_profile", "") or ""
        ),
        "builder_multi_llm_role_overrides": {
            str(role): list(models)
            for role, models in role_overrides.items()
            if str(role).strip() and list(models)
        },
        "builder_flow_analysis_enabled": bool(
            getattr(state, "builder_flow_analysis_enabled", False)
        ),
        "builder_flow_analysis_ablation": (
            dict(getattr(state, "builder_flow_analysis_ablation", {}) or {})
            if isinstance(getattr(state, "builder_flow_analysis_ablation", {}), dict)
            else {}
        ),
        "builder_dual_lane_primary_model": str(
            getattr(state, "builder_dual_lane_primary_model", "") or ""
        ),
        "builder_dual_lane_critic_model": str(
            getattr(state, "builder_dual_lane_critic_model", "") or ""
        ),
    }


def restore_builder_autonomous_ui_state_from_runtime() -> tuple[bool, Dict[str, Any]]:
    """Restaure le mode Builder autonome dans la session Streamlit après redémarrage."""
    payload = _load_autonomous_runtime_state()
    should_resume = bool(payload.get("active")) and not bool(payload.get("manual_stop"))
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
        ("builder_multi_llm_enabled", "builder_multi_llm_enabled_toggle"),
    ):
        if name not in resume_ui_state:
            continue
        value = bool(resume_ui_state.get(name))
        st.session_state[name] = value
        st.session_state[widget_key] = value

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

    builder_multi_llm_profile = str(
        resume_ui_state.get("builder_multi_llm_profile", "") or ""
    ).strip()
    if builder_multi_llm_profile:
        st.session_state["builder_multi_llm_profile"] = builder_multi_llm_profile
        st.session_state["builder_multi_llm_profile_select"] = (
            builder_multi_llm_profile
        )

    role_overrides = resume_ui_state.get("builder_multi_llm_role_overrides", {})
    if isinstance(role_overrides, dict):
        cleaned_role_overrides = normalize_builder_multi_llm_role_pool_overrides(
            role_overrides
        )
        st.session_state["builder_multi_llm_role_overrides"] = cleaned_role_overrides

    ablation_config = resume_ui_state.get("builder_flow_analysis_ablation", {})
    if isinstance(ablation_config, dict):
        st.session_state["builder_flow_analysis_ablation"] = dict(ablation_config)
        st.session_state["builder_flow_analysis_disabled_steps_multiselect"] = [
            step
            for step, enabled in dict(ablation_config).items()
            if not bool(enabled)
        ]

    for name, widget_key in (
        ("builder_dual_lane_primary_model", "builder_dual_lane_primary_model_select"),
        ("builder_dual_lane_critic_model", "builder_dual_lane_critic_model_select"),
    ):
        value = str(resume_ui_state.get(name, "") or "").strip()
        if not value:
            continue
        st.session_state[name] = value
        st.session_state[widget_key] = value

    return True, payload


def _mark_builder_autonomous_runtime_started(
    *,
    model: str,
    ollama_host: str,
    requested_source_mode: str,
    auto_market_pick: bool,
    resume_ui_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    runtime = _load_autonomous_runtime_state()
    was_active = bool(runtime.get("active"))
    runtime["active"] = True
    runtime["manual_stop"] = False
    runtime["started_at"] = runtime.get("started_at") or _utc_now_iso()
    runtime["last_heartbeat_at"] = _utc_now_iso()
    runtime["last_resume_at"] = _utc_now_iso() if was_active else ""
    runtime["last_event"] = "autonomous_started"
    runtime["last_error"] = ""
    runtime["last_stop_reason"] = ""
    runtime["last_progress_at"] = _utc_now_iso()
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
    if was_active:
        runtime["resume_count"] = int(runtime.get("resume_count", 0) or 0) + 1
    _save_autonomous_runtime_state(runtime)
    return runtime


def _heartbeat_builder_autonomous_runtime(**updates: Any) -> Dict[str, Any]:
    runtime = _load_autonomous_runtime_state()
    runtime["last_heartbeat_at"] = _utc_now_iso()
    runtime.update(_collect_autonomous_runtime_process_metrics())
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
    runtime["active"] = False
    runtime["manual_stop"] = bool(manual_stop)
    runtime["last_heartbeat_at"] = _utc_now_iso()
    runtime["last_event"] = "autonomous_stopped"
    runtime["last_stop_reason"] = str(reason or "")
    runtime["last_error"] = str(error or "")
    runtime.update(_collect_autonomous_runtime_process_metrics())
    _save_autonomous_runtime_state(runtime)
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
    raw_return = entry.get("final_return")
    if raw_return in (None, ""):
        raw_return = entry.get("best_return")
    return_pct: Optional[float] = None

    try:
        if raw_return not in (None, ""):
            return_pct = float(raw_return)
            if not math.isfinite(return_pct):
                return_pct = None
    except Exception:
        return_pct = None

    if return_pct is not None and return_pct < 0.0:
        if status in {"failed", "max_iterations", "running", ""}:
            return {"icon": "−", "label": "negatif", "tone": "negative"}

    fallback_badges = {
        "success": {"icon": "✚", "label": "succes", "tone": "positive"},
        "max_iterations": {"icon": "⏱️", "label": "max_iterations", "tone": "neutral"},
        "failed": {"icon": "✖", "label": "echec", "tone": "crash"},
        "error": {"icon": "✖", "label": "erreur", "tone": "crash"},
        "crash": {"icon": "✖", "label": "crash", "tone": "crash"},
        "running": {"icon": "…", "label": "en cours", "tone": "neutral"},
    }
    return fallback_badges.get(
        status, {"icon": "?", "label": status or "inconnu", "tone": "neutral"}
    )


def _get_autonomous_session_best_return_snapshot(session: Any) -> Dict[str, Any]:
    """Extrait la meilleure itération par return pour le récap autonome.

    Le tableau autonome doit garder visible le meilleur return observé dans la
    session, même si cette itération n'est pas celle promue comme meilleur run
    et même si la session finit en échec.
    """
    best_return: Optional[float] = None
    best_snapshot: Dict[str, Any] = {
        "best_return": None,
        "best_return_iteration": None,
        "best_max_dd": None,
        "best_pf": None,
        "best_trades": None,
        "best_return_sharpe": None,
    }

    for iteration in list(getattr(session, "iterations", []) or []):
        backtest_result = getattr(iteration, "backtest_result", None)
        metrics = getattr(backtest_result, "metrics", None)
        if not isinstance(metrics, dict):
            continue

        raw_return = metrics.get("total_return_pct")
        try:
            current_return = float(raw_return)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(current_return):
            continue

        if best_return is None or current_return > best_return:
            best_return = current_return
            best_snapshot = {
                "best_return": current_return,
                "best_return_iteration": getattr(iteration, "iteration", None),
                "best_max_dd": metrics.get("max_drawdown_pct"),
                "best_pf": metrics.get("profit_factor"),
                "best_trades": metrics.get("total_trades"),
                "best_return_sharpe": metrics.get("sharpe_ratio"),
                "best_total_pnl": metrics.get("total_pnl"),
            }

    if best_return is not None:
        return best_snapshot

    best_metrics = {}
    best_iteration = getattr(session, "best_iteration", None)
    best_backtest_result = getattr(best_iteration, "backtest_result", None)
    if best_backtest_result is not None and isinstance(best_backtest_result.metrics, dict):
        best_metrics = best_backtest_result.metrics

    return {
        "best_return": best_metrics.get("total_return_pct"),
        "best_return_iteration": getattr(best_iteration, "iteration", None),
        "best_max_dd": best_metrics.get("max_drawdown_pct"),
        "best_pf": best_metrics.get("profit_factor"),
        "best_trades": best_metrics.get("total_trades"),
        "best_return_sharpe": best_metrics.get("sharpe_ratio"),
        "best_total_pnl": best_metrics.get("total_pnl"),
    }


def _get_autonomous_session_final_snapshot(session: Any) -> Dict[str, Any]:
    """Extrait les métriques de la dernière itération backtestée de la session."""
    for iteration in reversed(list(getattr(session, "iterations", []) or [])):
        backtest_result = getattr(iteration, "backtest_result", None)
        metrics = getattr(backtest_result, "metrics", None)
        if not isinstance(metrics, dict):
            continue
        return {
            "final_return": metrics.get("total_return_pct"),
            "final_iteration": getattr(iteration, "iteration", None),
            "final_max_dd": metrics.get("max_drawdown_pct"),
            "final_pf": metrics.get("profit_factor"),
            "final_trades": metrics.get("total_trades"),
            "final_sharpe": metrics.get("sharpe_ratio"),
            "final_total_pnl": metrics.get("total_pnl"),
        }

    best_metrics = {}
    best_iteration = getattr(session, "best_iteration", None)
    best_backtest_result = getattr(best_iteration, "backtest_result", None)
    if best_backtest_result is not None and isinstance(best_backtest_result.metrics, dict):
        best_metrics = best_backtest_result.metrics

    return {
        "final_return": best_metrics.get("total_return_pct"),
        "final_iteration": getattr(best_iteration, "iteration", None),
        "final_max_dd": best_metrics.get("max_drawdown_pct"),
        "final_pf": best_metrics.get("profit_factor"),
        "final_trades": best_metrics.get("total_trades"),
        "final_sharpe": best_metrics.get("sharpe_ratio"),
        "final_total_pnl": best_metrics.get("total_pnl"),
    }


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

    if (
        int(supervisor.get("consecutive_errors", 0) or 0) >= 2
        or failure_streak >= 4
        or crash_streak >= 2
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
        or "rejette le nom exact" in text
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
        plan["reason"] = "llm_recovery_fallback_simple"
        plan["force_source_mode"] = "fallback"
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
    st.markdown(
        f"**Itérations:** {n_iters} | **Meilleur Sharpe:** {sharpe_txt}"
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


def _compact_multi_llm_role_outputs(
    role_outputs: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    compact: Dict[str, Dict[str, Any]] = {}
    for role, raw_payload in dict(role_outputs or {}).items():
        if not isinstance(raw_payload, dict):
            continue
        content = str(raw_payload.get("content", "") or "").strip()
        compact[str(role or "").strip()] = {
            "model": str(raw_payload.get("model", "") or "").strip(),
            "available": bool(raw_payload.get("available", False)),
            "error": str(raw_payload.get("error", "") or "").strip(),
            "content_excerpt": (
                content[:280] + "…" if len(content) > 280 else content
            ),
            "metadata": (
                _clone_json_compatible(raw_payload.get("metadata", {}) or {})
                if isinstance(raw_payload.get("metadata"), dict)
                else {}
            ),
        }
    return compact


def _finalize_multi_llm_session_review(
    *,
    objective: str,
    session: Any,
    target_sharpe: float,
    multi_llm_manager: Optional["MultiLLMSessionManager"],
    persist_summary: bool = True,
) -> Dict[str, Any]:
    if multi_llm_manager is None or session is None:
        return {
            "router_decision": {},
            "role_outputs": {},
            "role_outputs_compact": {},
            "shared_memory": {},
            "continuity_context": {},
        }

    review_bundle = multi_llm_manager.review_builder_session(
        objective=objective,
        builder_session=session,
        target_sharpe=target_sharpe,
    )
    router_decision = dict(review_bundle.get("router_decision", {}) or {})
    role_outputs = {
        role_name: role_output.to_dict()
        for role_name, role_output in (
            review_bundle.get("role_outputs", {}) or {}
        ).items()
    }
    role_outputs_compact = _compact_multi_llm_role_outputs(role_outputs)
    shared_memory = _clone_json_compatible(
        multi_llm_manager.consume_shared_memory() or {}
    )
    if not isinstance(shared_memory, dict):
        shared_memory = {}
    continuity_context = dict(shared_memory.get("continuity_context", {}) or {})

    setattr(session, "multi_llm_router_decision", router_decision)
    setattr(session, "multi_llm_role_outputs", role_outputs_compact)
    setattr(session, "multi_llm_shared_memory", shared_memory)
    setattr(session, "continuity_context", continuity_context)

    if persist_summary:
        _persist_builder_session_summary_patch(
            session,
            {
                "multi_llm_router_decision": router_decision,
                "multi_llm_role_outputs": role_outputs_compact,
                "multi_llm_shared_memory": shared_memory,
                "continuity_context": continuity_context,
            },
        )

    return {
        "router_decision": router_decision,
        "role_outputs": role_outputs,
        "role_outputs_compact": role_outputs_compact,
        "shared_memory": shared_memory,
        "continuity_context": continuity_context,
    }


def _resolve_builder_multi_llm_payload(source: Any) -> Dict[str, Any]:
    payload = {
        "builder_execution_mode": str(
            _read_builder_source_value(source, "builder_execution_mode", "") or ""
        ),
        "orchestration_mode": str(
            _read_builder_source_value(source, "orchestration_mode", "") or ""
        ),
        "multi_llm_profile": str(
            _read_builder_source_value(source, "multi_llm_profile", "") or ""
        ),
        "multi_llm_assignments": (
            list(_read_builder_source_value(source, "multi_llm_assignments", []) or [])
            if isinstance(_read_builder_source_value(source, "multi_llm_assignments", []), list)
            else []
        ),
        "multi_llm_router_decision": (
            dict(_read_builder_source_value(source, "multi_llm_router_decision", {}) or {})
            if isinstance(_read_builder_source_value(source, "multi_llm_router_decision", {}), dict)
            else {}
        ),
        "multi_llm_role_outputs": (
            dict(_read_builder_source_value(source, "multi_llm_role_outputs", {}) or {})
            if isinstance(_read_builder_source_value(source, "multi_llm_role_outputs", {}), dict)
            else {}
        ),
        "multi_llm_shared_memory": (
            dict(_read_builder_source_value(source, "multi_llm_shared_memory", {}) or {})
            if isinstance(_read_builder_source_value(source, "multi_llm_shared_memory", {}), dict)
            else {}
        ),
        "continuity_context": (
            dict(_read_builder_source_value(source, "continuity_context", {}) or {})
            if isinstance(_read_builder_source_value(source, "continuity_context", {}), dict)
            else {}
        ),
    }
    persisted_summary = _load_builder_summary_payload(source)
    if not payload["builder_execution_mode"]:
        payload["builder_execution_mode"] = str(
            persisted_summary.get("builder_execution_mode", "") or ""
        )
    if not payload["orchestration_mode"]:
        payload["orchestration_mode"] = str(
            persisted_summary.get("orchestration_mode", "") or ""
        )
    for field_name in (
        "multi_llm_profile",
        "multi_llm_assignments",
        "multi_llm_router_decision",
        "multi_llm_role_outputs",
        "multi_llm_shared_memory",
        "continuity_context",
    ):
        if payload.get(field_name):
            continue
        persisted_value = persisted_summary.get(field_name)
        if isinstance(persisted_value, dict):
            payload[field_name] = dict(persisted_value or {})
        elif isinstance(persisted_value, list):
            payload[field_name] = list(persisted_value or [])
        elif persisted_value not in (None, ""):
            payload[field_name] = persisted_value

    if (
        not payload["continuity_context"]
        and isinstance(payload["multi_llm_shared_memory"], dict)
    ):
        payload["continuity_context"] = dict(
            payload["multi_llm_shared_memory"].get("continuity_context", {}) or {}
        )

    return payload


def _render_builder_campaign_memory_card(
    source: Any,
    *,
    title: str = "Mémoire de campagne",
) -> None:
    payload = _resolve_builder_multi_llm_payload(source)
    if str(payload.get("orchestration_mode") or "") != "multi_llm":
        return

    continuity = dict(payload.get("continuity_context", {}) or {})
    shared_memory = dict(payload.get("multi_llm_shared_memory", {}) or {})
    if not continuity and not shared_memory:
        return

    recent_sessions = list(continuity.get("recent_sessions", []) or [])
    best_recent = dict(continuity.get("best_recent_session", {}) or {})
    carry_over_focus = [
        str(item or "").strip()
        for item in list(continuity.get("carry_over_focus", []) or [])
        if str(item or "").strip()
    ]
    recurring_risks = [
        str(item or "").strip()
        for item in list(continuity.get("recurring_risks", []) or [])
        if str(item or "").strip()
    ]
    router_context = dict(shared_memory.get("router_context", {}) or {})

    st.markdown(f"#### {title}")
    st.caption(
        "Référence commune partagée entre les rôles multi-LLM pour garder visibles le meilleur run récent, "
        "les axes à poursuivre et les risques récurrents."
    )

    metric_cols = st.columns(4)
    metric_cols[0].metric("Sessions récentes", len(recent_sessions))
    metric_cols[1].metric("Focus à reprendre", len(carry_over_focus))
    metric_cols[2].metric("Risques récurrents", len(recurring_risks))
    metric_cols[3].metric(
        "Dernière décision routeur",
        str(router_context.get("action") or "n/a"),
    )

    if best_recent:
        st.caption(
            "Dernier meilleur run récent: "
            f"session #{best_recent.get('session_num', '?')} | "
            f"{best_recent.get('symbol', '?')} {best_recent.get('timeframe', '?')} | "
            f"Sharpe {_format_optional_float(best_recent.get('best_sharpe'), '{:.3f}', default='n/a')}"
        )

    st.markdown("**Focus à reprendre**")
    if carry_over_focus:
        for item in carry_over_focus:
            st.markdown(f"- {item}")
    else:
        st.caption("Aucun focus récurrent transmis par les derniers cycles.")

    st.markdown("**Risques récurrents**")
    if recurring_risks:
        for item in recurring_risks:
            st.markdown(f"- {item}")
    else:
        st.caption("Aucun risque récurrent dominant dans la mémoire partagée.")

    if recent_sessions:
        with st.expander("Sessions compactes transmises aux rôles", expanded=False):
            st.dataframe(recent_sessions, width="stretch", hide_index=True)


def _render_multi_llm_session_analysis_panel(
    source: Any,
    *,
    title: str = "Analyse avancée multi-LLM",
) -> None:
    payload = _resolve_builder_multi_llm_payload(source)
    if str(payload.get("orchestration_mode") or "") != "multi_llm":
        return

    router_decision = dict(payload.get("multi_llm_router_decision", {}) or {})
    role_outputs = dict(payload.get("multi_llm_role_outputs", {}) or {})
    shared_memory = dict(payload.get("multi_llm_shared_memory", {}) or {})
    assignments = list(payload.get("multi_llm_assignments", []) or [])

    if not router_decision and not role_outputs and not shared_memory and not assignments:
        return

    st.markdown(f"#### {title}")
    st.caption(
        "Lecture dédiée au flux multi-LLM: rôles réellement résolus, décision du routeur, "
        "mémoire partagée et sorties compactes. Cette vue reste séparée du diagnostic mono."
    )

    resolved_roles = [
        item for item in assignments
        if isinstance(item, dict) and bool(item.get("available"))
    ]
    confidence = _safe_numeric_float(router_decision.get("confidence"), 0.0)
    metric_cols = st.columns(4)
    metric_cols[0].metric("Routeur", str(router_decision.get("action") or "n/a"))
    metric_cols[1].metric("Confiance", f"{confidence:.2f}")
    metric_cols[2].metric("Rôles résolus", len(resolved_roles))
    metric_cols[3].metric(
        "Profil actif",
        str(payload.get("multi_llm_profile") or "n/a"),
    )

    router_reason = str(router_decision.get("reason", "") or "").strip()
    if router_reason:
        st.caption(f"Raison routeur: {router_reason}")

    if assignments:
        assignment_rows = [
            {
                "role": str(item.get("role", "") or ""),
                "demande": str(item.get("requested_model", "") or ""),
                "résolu": str(item.get("resolved_model", "") or ""),
                "backend": str(item.get("backend", "") or ""),
                "host": str(item.get("host", "") or ""),
                "disponible": bool(item.get("available", False)),
                "source": str(item.get("source", "") or ""),
            }
            for item in assignments
            if isinstance(item, dict)
        ]
        with st.expander("Rôles et résolutions effectives", expanded=False):
            st.dataframe(assignment_rows, width="stretch", hide_index=True)

    if role_outputs:
        role_rows = [
            {
                "role": role,
                "modèle": str((payload or {}).get("model", "") or ""),
                "disponible": bool((payload or {}).get("available", False)),
                "erreur": str((payload or {}).get("error", "") or ""),
                "aperçu": str((payload or {}).get("content_excerpt", "") or ""),
            }
            for role, payload in role_outputs.items()
            if isinstance(payload, dict)
        ]
        with st.expander("Sorties compactes des rôles", expanded=False):
            st.dataframe(role_rows, width="stretch", hide_index=True)

    if shared_memory:
        with st.expander("Mémoire partagée multi-LLM", expanded=False):
            st.json(shared_memory)


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
            "La lecture détaillée dans l'interface est prioritairement optimisée pour le mode Mono "
            "dans cette première vague. Les mêmes champs de persistance restent disponibles en multi-LLM "
            "et un panneau dédié `Analyse avancée multi-LLM` est affiché plus bas."
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


def _model_matches(model_name: str, requested_model: str) -> bool:
    """Matching contrôlé entre nom demandé et liste Ollama.

    Ne doit jamais confondre deux variantes de tailles différentes
    comme `qwen3-coder:480b` et `qwen3-coder:30b`.
    """
    model_name_l = str(model_name or "").strip().lower()
    requested_l = str(requested_model or "").strip().lower()

    if not model_name_l or not requested_l:
        return False

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
    return bool(is_cloud_only_model(model_name))


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
        resp = httpx.get(f"{ollama_host}/api/ps", timeout=timeout)
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
            if _model_matches(loaded, model):
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
    keep_alive = f"{max(1, int(keep_alive_minutes))}m"
    try:
        resp = httpx.post(
            f"{ollama_host}/api/generate",
            json={
                "model": model,
                "prompt": "Ready.",
                "keep_alive": keep_alive,
                "stream": False,
            },
            timeout=timeout,
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
            model=model,
            ollama_host=ollama_host,
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
            model=model,
            ollama_host=ollama_host,
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
            model=model,
            ollama_host=ollama_host,
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
        resp = httpx.post(
            f"{ollama_host}/api/generate",
            json={
                "model": model,
                "prompt": "",
                "keep_alive": 0,
                "stream": False,
            },
            timeout=timeout,
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
    probe_payload: Dict[str, Any] = {
        "requested_model": str(model or "").strip(),
        "resolved_model": str(model or "").strip(),
        "ollama_host": ollama_host,
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
    if auto_start_ollama and _is_local_ollama_host(ollama_host):
        try:
            ok, msg = ensure_ollama_running(
                ollama_host=ollama_host,
                gpu_target=gpu_target,
            )
        except TypeError:
            ok, msg = ensure_ollama_running(ollama_host=ollama_host)
        if not ok:
            probe_payload.update(
                {
                    "status": "startup_failed",
                    "message": msg,
                }
            )
            _store_builder_runtime_acceptance_probe(probe_payload)
            return False, msg, model

    try:
        tags = httpx.get(f"{ollama_host}/api/tags", timeout=8.0)
    except Exception as exc:
        probe_payload.update(
            {
                "status": "host_unreachable",
                "message": f"Ollama inaccessible ({ollama_host}): {exc}",
            }
        )
        _store_builder_runtime_acceptance_probe(probe_payload)
        return False, f"Ollama inaccessible ({ollama_host}): {exc}", model

    if tags.status_code != 200:
        probe_payload.update(
            {
                "status": "host_http_error",
                "message": f"Ollama indisponible sur {ollama_host} (status={tags.status_code})",
                "tags_status_code": tags.status_code,
            }
        )
        _store_builder_runtime_acceptance_probe(probe_payload)
        return (
            False,
            f"Ollama indisponible sur {ollama_host} (status={tags.status_code})",
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
            ollama_host=ollama_host,
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
        probe_payload = acceptance_probe
    else:
        probe_payload.update(
            {
                "cloud_only": False,
                "present_in_tags": any(_model_matches(name, resolved_model) for name in models),
                "accepted": True,
                "status": "local_model_visible",
                "message": f"Le modèle `{resolved_model}` est visible sur {ollama_host} via /api/tags.",
            }
        )
        _store_builder_runtime_acceptance_probe(probe_payload)

    if not preload_model:
        msg = f"Ollama OK ({ollama_host}) — warmup désactivé."
        if resolve_note:
            msg = f"{resolve_note} {msg}"
        probe_payload["message"] = f"{probe_payload.get('message', '').strip()} Warmup désactivé.".strip()
        _store_builder_runtime_acceptance_probe(probe_payload)
        return True, msg, resolved_model

    warmup_ok, warmup_detail = _warmup_ollama_model(
        model=resolved_model,
        ollama_host=ollama_host,
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
                f"Impossible de précharger `{resolved_model}` sur {ollama_host}. "
                f"Détail: {warmup_detail}"
            ),
        }
    )
    _store_builder_runtime_acceptance_probe(probe_payload)
    return (
        False,
        (
            f"Impossible de précharger `{resolved_model}` sur {ollama_host}. "
            f"Détail: {warmup_detail}"
        ),
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
        and normalized_msg.startswith("Impossible de précharger")
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


def _pick_builder_session_role_overrides(
    role_pools: Dict[str, List[str]],
    *,
    inventory: Any | None = None,
) -> Dict[str, str]:
    """Tire un seul modele par role pour la session courante.

    Le resultat est ensuite passe au SessionManager et reste fige pour
    toutes les iterations de cette session Builder. Un nouveau tirage n'a
    lieu qu'au lancement de la session suivante.
    """
    selected: Dict[str, str] = {}
    for role in SIMPLE_MULTI_LLM_ACTIVE_ROLES:
        pool = [
            str(candidate or "").strip()
            for candidate in list(role_pools.get(role, []) or [])
            if str(candidate or "").strip()
        ]
        if not pool:
            continue
        if inventory is not None:
            runtime_pickable_pool: List[str] = []
            inventory_find = getattr(inventory, "find", None)
            live_reachable = bool(getattr(inventory, "live_ollama_reachable", False))
            for candidate in pool:
                if not _is_cloud_only_model(candidate):
                    runtime_pickable_pool.append(candidate)
                    continue
                discovered = inventory_find(candidate) if callable(inventory_find) else None
                if discovered is not None and (not live_reachable or bool(getattr(discovered, "live", False))):
                    runtime_pickable_pool.append(candidate)
            if runtime_pickable_pool:
                pool = runtime_pickable_pool
        selected[role] = random.choice(pool)
    return selected


def _prepare_multi_llm_role_runtime_with_failover(
    manager: "MultiLLMSessionManager",
    *,
    role: str,
    preload_model: bool,
    keep_alive_minutes: int,
    auto_start_ollama: bool,
) -> tuple[bool, str, str]:
    assignment = manager.resolve_role_assignment(role)
    route = manager.resolve_role_route(role)
    attempted_messages: List[str] = []
    last_model = ""

    while assignment is not None and assignment.available:
        candidate = str(assignment.resolved_model or assignment.requested_model or "").strip()
        if not candidate:
            break
        last_model = candidate
        ok, msg, resolved_model = _prepare_builder_llm(
            model=candidate,
            ollama_host=route.ollama_host,
            gpu_target=str(route.gpu_target or "") or None,
            preload_model=preload_model,
            keep_alive_minutes=keep_alive_minutes,
            auto_start_ollama=auto_start_ollama,
        )
        if ok:
            if resolved_model and resolved_model != candidate:
                assignment.resolved_model = resolved_model
            if attempted_messages:
                return (
                    True,
                    " | ".join(attempted_messages + [f"fallback actif: {resolved_model}", msg]),
                    resolved_model,
                )
            return True, msg, resolved_model

        attempted_messages.append(f"{candidate}: {msg}")
        next_candidate = manager.select_next_role_candidate(
            role,
            rejected_model=candidate,
            reason=msg,
        )
        if not next_candidate:
            return False, " | ".join(attempted_messages), last_model or resolved_model
        assignment = manager.resolve_role_assignment(role)

    return False, " | ".join(attempted_messages) or "Aucun candidat runtime disponible.", last_model


def _format_builder_role_pool_summary(role_pools: Dict[str, List[str]]) -> str:
    parts: List[str] = []
    for role in SIMPLE_MULTI_LLM_ACTIVE_ROLES:
        pool = list(role_pools.get(role, []) or [])
        if not pool:
            continue
        parts.append(f"{role}=[{' | '.join(pool)}]")
    return ", ".join(parts)


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

    available_symbols = list(getattr(state, "available_tokens", []) or [])
    available_timeframes = list(getattr(state, "available_timeframes", []) or [])

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
    normalized_strategy_type = infer_strategy_type(
        strategy_key=str(getattr(state, "strategy_key", "") or ""),
        objective=objective,
    )

    def _universe_loader(symbol: str, timeframe: str) -> Any:
        use_fallback = (
            _has_builder_market_df(fallback_df)
            and str(symbol or "").strip().upper() == str(current_symbol or "").strip().upper()
            and str(timeframe or "").strip() == str(current_timeframe or "").strip()
        )
        loaded_df, load_error, _data_source = _load_builder_market_data(
            state=state,
            symbol=symbol,
            timeframe=timeframe,
            fallback_df=fallback_df if use_fallback else None,
            allow_current_fallback=use_fallback,
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

    use_date_filter = bool(getattr(state, "use_date_filter", False))
    start = _state_date_to_iso(getattr(state, "start_date", None)) if use_date_filter else None
    end = _state_date_to_iso(getattr(state, "end_date", None)) if use_date_filter else None
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


def _ensure_multi_llm_runtime_hosts(
    manager: Optional["MultiLLMSessionManager"],
    *,
    active_roles: Optional[List[str]] = None,
) -> tuple[bool, List[str]]:
    if manager is None:
        return True, []

    ensured_messages: List[str] = []
    seen_hosts: set[tuple[str, str]] = set()
    roles = active_roles or list(SIMPLE_MULTI_LLM_ACTIVE_ROLES)
    for role in roles:
        assignment = manager.resolve_role_assignment(role)
        if (
            assignment is None
            or not assignment.available
            or assignment.backend != "ollama"
            or not assignment.resolved_model
        ):
            continue
        route = manager.resolve_role_route(role)
        host_key = (
            str(route.ollama_host or "").strip(),
            str(route.gpu_target or "").strip(),
        )
        if host_key in seen_hosts:
            continue
        seen_hosts.add(host_key)
        ok, msg = ensure_ollama_running(
            ollama_host=route.ollama_host,
            gpu_target=route.gpu_target or None,
        )
        if not ok:
            return False, [msg]
        ensured_messages.append(msg)
    return True, ensured_messages


def _release_multi_llm_runtime(
    manager: Optional["MultiLLMSessionManager"],
) -> List[Dict[str, Any]]:
    if manager is None:
        return []
    try:
        return manager.release_runtime_models()
    except Exception as exc:
        logger.warning("builder_multi_llm_runtime_release_failed error=%s", exc)
        return []


def _build_builder_runtime_diagnostic_payload(
    manager: Optional["MultiLLMSessionManager"],
    *,
    mode: str,
    event: str,
    phase: str,
    iteration: int,
    max_iterations: int,
    status: str = "",
    session_label: str = "",
    objective: str = "",
) -> Dict[str, Any]:
    snapshot = manager.runtime_flow_snapshot() if manager is not None else {}
    objective_preview = " ".join(str(objective or "").split())
    if len(objective_preview) > 220:
        objective_preview = objective_preview[:220] + "..."
    return {
        "updated_at": _utc_now_iso(),
        "mode": str(mode or "").strip() or "multi_llm",
        "profile_name": str(
            snapshot.get("profile_name", getattr(manager, "profile_name", "")) or ""
        ),
        "event": str(event or "").strip() or "-",
        "phase": str(phase or "").strip() or "-",
        "iteration": int(iteration or 0),
        "max_iterations": int(max_iterations or 0),
        "status": str(status or "").strip(),
        "session_label": str(session_label or "").strip(),
        "objective_preview": objective_preview,
        "host_rows": list(snapshot.get("host_rows", []) or []),
        "role_rows": list(snapshot.get("role_rows", []) or []),
        "recent_events": list(snapshot.get("recent_events", []) or []),
        "active_models_by_host": dict(snapshot.get("active_models_by_host", {}) or {}),
        "missing_roles": list(snapshot.get("missing_roles", []) or []),
    }


def _render_builder_runtime_diagnostic_panel(
    diagnostic: Dict[str, Any],
    *,
    placeholder: Any,
    expanded: bool = False,
) -> None:
    with placeholder.container():
        with st.expander("🛰️ Diagnostic runtime inter-modeles", expanded=expanded):
            summary_parts = [
                f"profil=`{diagnostic.get('profile_name', '-') or '-'}`",
                f"event=`{diagnostic.get('event', '-') or '-'}`",
                f"phase=`{diagnostic.get('phase', '-') or '-'}`",
                f"iteration={int(diagnostic.get('iteration', 0) or 0)}/{int(diagnostic.get('max_iterations', 0) or 0)}",
            ]
            status = str(diagnostic.get("status", "") or "").strip()
            if status:
                summary_parts.append(f"status=`{status}`")
            session_label = str(diagnostic.get("session_label", "") or "").strip()
            if session_label:
                summary_parts.append(session_label)
            _render_builder_badge_row(summary_parts)

            objective_preview = str(diagnostic.get("objective_preview", "") or "").strip()
            if objective_preview:
                st.markdown(
                    f"<div class='bc-builder-runtime-note'><strong>Objectif actif:</strong> {html.escape(objective_preview)}</div>",
                    unsafe_allow_html=True,
                )

            host_rows = list(diagnostic.get("host_rows", []) or [])
            if host_rows:
                st.markdown("**Hosts runtime**")
                st.dataframe(host_rows, width="stretch", hide_index=True)

            role_rows = list(diagnostic.get("role_rows", []) or [])
            if role_rows:
                st.markdown("**Roles actifs / resolus**")
                st.dataframe(role_rows, width="stretch", hide_index=True)

            recent_events = list(diagnostic.get("recent_events", []) or [])
            if recent_events:
                st.markdown("**Derniers switches observes**")
                st.dataframe(recent_events, width="stretch", hide_index=True)
            else:
                st.caption("Aucun switch runtime enregistre pour cette session.")


def _sync_builder_runtime_diagnostic(
    manager: Optional["MultiLLMSessionManager"],
    *,
    mode: str,
    event: str,
    phase: str,
    iteration: int,
    max_iterations: int,
    status: str = "",
    session_label: str = "",
    objective: str = "",
    placeholder: Any = None,
    expanded: bool = False,
) -> Dict[str, Any]:
    diagnostic = _build_builder_runtime_diagnostic_payload(
        manager,
        mode=mode,
        event=event,
        phase=phase,
        iteration=iteration,
        max_iterations=max_iterations,
        status=status,
        session_label=session_label,
        objective=objective,
    )
    st.session_state["builder_runtime_diagnostic"] = diagnostic
    if placeholder is not None:
        _render_builder_runtime_diagnostic_panel(
            diagnostic,
            placeholder=placeholder,
            expanded=expanded,
        )
    return diagnostic


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
        }

    return "", "", None, {
        "data_source": "load_error",
        "failures": failures,
        "probed_pairs": probe_pairs,
        "universe_mode": universe_mode,
        "strategy_type": strategy_type,
        "universe_criteria": dict(universe_meta.get("criteria", {}) or {}),
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
    multi_llm_manager: Optional["MultiLLMSessionManager"] = None,
    builder_execution_mode: str = BUILDER_EXECUTION_MODE_MONO,
    orchestration_mode: str = "single_llm",
    builder_flow_analysis_enabled: bool = False,
    builder_flow_analysis_ablation: Optional[Dict[str, bool]] = None,
    multi_llm_profile: str = "",
    multi_llm_role_overrides: Optional[Dict[str, Any]] = None,
    multi_llm_assignments: Optional[List[Dict[str, Any]]] = None,
    run_multi_llm_review: bool = False,
) -> Any:
    """Exécute une session builder unique et affiche les résultats.

    Args:
        skip_llm_prepare: Si True, ne pas refaire les checks/warmup (déjà fait en amont).
        autonomous_runtime_watchdog: Si True, émet un heartbeat périodique
            et des métriques process pour permettre une relance externe.

    Returns:
        BuilderSession ou None en cas d'erreur/interruption.
    """
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
    runtime_diag_placeholder = st.empty() if multi_llm_manager is not None else None
    if multi_llm_manager is not None and runtime_diag_placeholder is not None:
        _sync_builder_runtime_diagnostic(
            multi_llm_manager,
            mode="multi_llm",
            event="session_bootstrap",
            phase="initialisation",
            iteration=0,
            max_iterations=max_iterations,
            session_label=session_label,
            objective=objective,
            placeholder=runtime_diag_placeholder,
            expanded=True,
        )

    # Zone de streaming LLM
    stream_placeholder = st.empty()
    _stream_state: dict = {"text": "", "phase": "", "active": False}
    _progress_state: dict[str, Any] = {
        "iteration": 0,
        "max_iterations": max_iterations,
        "phase": "initialisation",
        "event": "session_start",
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

    _PROGRESS_PHASE_LABELS = {
        "proposal": "proposition",
        "code": "génération code",
        "analysis": "analyse",
        "backtest": "backtest",
        "validation": "validation",
    }

    def _on_builder_progress(payload: Dict[str, Any]) -> None:
        event = str(payload.get("event", "") or "")
        iteration = int(payload.get("iteration", _progress_state["iteration"]) or 0)
        max_iters = int(payload.get("max_iterations", _progress_state["max_iterations"]) or max_iterations)
        phase = str(payload.get("phase", _progress_state["phase"]) or "")
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
                _heartbeat_builder_autonomous_runtime(
                    last_event=f"builder_{event or 'progress'}",
                    last_progress_at=_utc_now_iso(),
                    last_progress_event=event,
                    last_progress_phase=phase,
                    last_progress_iteration=iteration,
                )
            except Exception as exc:
                logger.warning(
                    "builder_autonomous_progress_heartbeat_failed event=%s error=%s",
                    event,
                    exc,
                )

        phase_fraction = {
            "proposal": 0.18,
            "code": 0.46,
            "validation": 0.58,
            "backtest": 0.78,
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

        if event == "session_start":
            progress_text = "Initialisation de la session Builder..."
        elif event == "iteration_start":
            progress_text = f"Itération {iteration}/{max_iters} — démarrage"
        elif event == "phase_start":
            progress_text = (
                f"Itération {iteration}/{max_iters} — "
                f"{_PROGRESS_PHASE_LABELS.get(phase, phase or 'phase en cours')}"
            )
        elif event == "iteration_error":
            progress_text = (
                f"Itération {iteration}/{max_iters} — erreur "
                f"({_PROGRESS_PHASE_LABELS.get(phase, phase or 'runtime')})"
            )
        elif event == "iteration_done":
            decision = str(payload.get("decision", "") or "continue")
            progress_text = f"Itération {iteration}/{max_iters} — décision {decision}"
        elif event == "session_done":
            progress_text = (
                f"Session terminée — {payload.get('status', 'n/a')} "
                f"({payload.get('total_iterations', 0)} itérations)"
            )
        else:
            progress_text = f"Itération {iteration}/{max_iters} — activité en cours"

        try:
            progress_bar.progress(progress_value, text=progress_text)
            with progress_detail_placeholder.container():
                st.caption(progress_text)
                if event == "iteration_error":
                    error_text = str(payload.get("error", "") or "").strip()
                    if error_text:
                        st.caption(f"Détail: {error_text[:220]}")
                elif event == "phase_done" and phase == "backtest":
                    sharpe = payload.get("sharpe")
                    ret_pct = payload.get("total_return_pct")
                    try:
                        st.caption(
                            f"Backtest courant: Sharpe {float(sharpe):.3f} | "
                            f"Return {float(ret_pct):+.2f}%"
                        )
                    except Exception:
                        pass
            if multi_llm_manager is not None and runtime_diag_placeholder is not None:
                _sync_builder_runtime_diagnostic(
                    multi_llm_manager,
                    mode="multi_llm",
                    event=event or "progress",
                    phase=phase,
                    iteration=iteration,
                    max_iterations=max_iters,
                    session_label=session_label,
                    objective=objective,
                    placeholder=runtime_diag_placeholder,
                    expanded=True,
                )
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

    llm_config = apply_llm_inference_settings(
        LLMConfig(
            provider=LLMProvider.OLLAMA,
            model=runtime_model,
            ollama_host=ollama_host,
        ),
        model_name=runtime_model,
        global_settings=llm_inference_global_settings,
        model_profiles=llm_inference_model_profiles,
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
    builder.multi_llm_profile = (
        str(multi_llm_profile or "")
        if builder.orchestration_mode == "multi_llm"
        else ""
    )
    builder.multi_llm_role_overrides = (
        dict(multi_llm_role_overrides or {})
        if builder.orchestration_mode == "multi_llm"
        else {}
    )
    builder.multi_llm_assignments = (
        list(multi_llm_assignments or [])
        if builder.orchestration_mode == "multi_llm"
        else []
    )
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

    start_time = time.perf_counter()

    with st.status("🏗️ Construction en cours...", expanded=True) as live_status:
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
            live_status.update(label="⚠️ Interrompu", state="error")
            st.warning("Construction interrompue par l'utilisateur.")
            if multi_llm_manager is not None and runtime_diag_placeholder is not None:
                _sync_builder_runtime_diagnostic(
                    multi_llm_manager,
                    mode="multi_llm",
                    event="session_interrupted",
                    phase=str(_progress_state.get("phase", "") or "runtime"),
                    iteration=int(_progress_state.get("iteration", 0) or 0),
                    max_iterations=max_iterations,
                    status="interrupted",
                    session_label=session_label,
                    objective=objective,
                    placeholder=runtime_diag_placeholder,
                    expanded=True,
                )
            _release_runtime_model()
            return None
        except Exception as exc:
            live_status.update(label=f"❌ Erreur: {exc}", state="error")
            show_status("error", f"Erreur Strategy Builder: {exc}")
            st.code(traceback.format_exc())
            if multi_llm_manager is not None and runtime_diag_placeholder is not None:
                _sync_builder_runtime_diagnostic(
                    multi_llm_manager,
                    mode="multi_llm",
                    event="session_error",
                    phase=str(_progress_state.get("phase", "") or "runtime"),
                    iteration=int(_progress_state.get("iteration", 0) or 0),
                    max_iterations=max_iterations,
                    status="error",
                    session_label=session_label,
                    objective=objective,
                    placeholder=runtime_diag_placeholder,
                    expanded=True,
                )
            _release_runtime_model()
            return None
        finally:
            if autonomous_runtime_watchdog:
                watchdog_stop_event.set()
                if watchdog_thread is not None:
                    watchdog_thread.join(timeout=2.0)

        elapsed = time.perf_counter() - start_time
        live_status.update(
            label=f"✅ Terminé en {elapsed:.1f}s — {len(session.iterations)} itérations",
            state="complete",
        )

    # Nettoyage
    try:
        stream_placeholder.empty()
    except Exception:
        pass

    progress_bar.progress(1.0, text="Terminé")

    if run_multi_llm_review and multi_llm_manager is not None:
        try:
            review_payload = _finalize_multi_llm_session_review(
                objective=objective,
                session=session,
                target_sharpe=target_sharpe,
                multi_llm_manager=multi_llm_manager,
                persist_summary=True,
            )
            router_decision = dict(review_payload.get("router_decision", {}) or {})
            router_action = str(router_decision.get("action", "iterate") or "iterate")
            router_reason = str(router_decision.get("reason", "") or "").strip()
            st.caption(
                f"Multi-LLM router: {router_action}"
                + (f" | {router_reason}" if router_reason else "")
            )
            if runtime_diag_placeholder is not None:
                _sync_builder_runtime_diagnostic(
                    multi_llm_manager,
                    mode="multi_llm",
                    event="session_review_done",
                    phase="analysis",
                    iteration=len(getattr(session, "iterations", []) or []),
                    max_iterations=max_iterations,
                    status=str(getattr(session, "status", "") or ""),
                    session_label=session_label,
                    objective=objective,
                    placeholder=runtime_diag_placeholder,
                    expanded=True,
                )
        except Exception as exc:
            logger.warning("builder_manual_multi_llm_review_failed error=%s", exc)
            st.warning(
                "Relecture multi-LLM post-session indisponible pour ce run. "
                f"Détail: {exc}"
            )

    with iterations_container:
        st.markdown("### 📋 Historique des itérations")
        for it in session.iterations:
            is_last = (it == session.iterations[-1])
            render_iteration_card(it, expanded=is_last)

    with summary_placeholder.container():
        st.markdown("---")
        render_session_summary(session)
        _render_builder_flow_analysis_panel(session)
        _render_builder_campaign_memory_card(session)
        _render_multi_llm_session_analysis_panel(session)

    if multi_llm_manager is not None and runtime_diag_placeholder is not None:
        _sync_builder_runtime_diagnostic(
            multi_llm_manager,
            mode="multi_llm",
            event="session_done",
            phase=str(_progress_state.get("phase", "") or "analysis"),
            iteration=len(getattr(session, "iterations", []) or []),
            max_iterations=max_iterations,
            status=str(getattr(session, "status", "") or ""),
            session_label=session_label,
            objective=objective,
            placeholder=runtime_diag_placeholder,
            expanded=True,
        )

    _release_runtime_model()

    return session


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
            _save_autonomous_supervisor_state([], _default_autonomous_supervisor_state())
            st.session_state["builder_autonomous_history"] = []
            st.session_state["builder_autonomous_supervisor"] = _default_autonomous_supervisor_state()
            st.rerun()

    if not history:
        st.caption("Aucune session enregistrée pour le moment.")
        return

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

    runtime_state = _load_autonomous_runtime_state()
    recovered_history, recovered_changed = _recover_autonomous_history_from_disk(
        history,
        runtime_state=runtime_state,
    )
    if recovered_changed:
        history[:] = recovered_history
        st.session_state["builder_autonomous_history"] = history
        _save_autonomous_supervisor_state(
            history,
            supervisor if isinstance(supervisor, dict) else _default_autonomous_supervisor_state(),
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
        status = h.get("status", "?")
        sharpe = h.get("best_sharpe", h.get("final_sharpe"))
        ret = h.get("best_return", h.get("final_return"))
        max_dd = h.get("best_max_dd", h.get("final_max_dd"))
        trades = h.get("best_trades", h.get("final_trades"))
        duration = h.get("duration", 0)
        gain_metrics = _resolve_autonomous_gain_metrics(h)

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
            f"<td>{objective_html}</td>"
            f"<td>{status_html}</td>"
            f"<td class='builder-autonomous-recap-num'>{_escape_autonomous_recap_cell(_fmt_float(sharpe, '{:.3f}'))}</td>"
            f"<td class='builder-autonomous-recap-num'>{_escape_autonomous_recap_cell(_fmt_float(ret, '{:+.2f}%'))}</td>"
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
                "multi_llm_profile": h.get("multi_llm_profile"),
                "multi_llm_router_action": (
                    (h.get("multi_llm_router_decision", {}) or {}).get("action")
                ),
                "session_id": h.get("session_id"),
            }
        )

    recap_table_html = """
<style>
.builder-autonomous-recap-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.92rem;
}
.builder-autonomous-recap-table th,
.builder-autonomous-recap-table td {
    padding: 0.35rem 0.5rem;
    border-bottom: 1px solid rgba(148, 163, 184, 0.25);
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
.builder-autonomous-recap-table th {
    font-weight: 700;
}
.builder-autonomous-recap-num {
    text-align: right;
    white-space: nowrap;
}
.builder-autonomous-recap-status {
    font-weight: 700;
    white-space: nowrap;
}
.builder-autonomous-recap-status--positive {
    color: #16a34a;
}
.builder-autonomous-recap-status--negative,
.builder-autonomous-recap-status--crash {
    color: #dc2626;
}
.builder-autonomous-recap-status--neutral {
    color: #b45309;
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
      <th>Session</th>
        <th>Date/heure</th>
            <th>Generation</th>
            <th>Objectif</th>
      <th>Statut</th>
      <th>Sharpe fin.</th>
      <th>Return fin.</th>
      <th>Gain total EUR</th>
      <th>Jours testes</th>
      <th>EUR/j</th>
      <th>Max DD fin.</th>
      <th>Trades fin.</th>
      <th>Duree</th>
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
    <strong>Lecture des metriques :</strong> <strong>Sharpe/Return/Max DD/Trades</strong> = metriques de la derniere iteration backtestee de la session.<br>
    <strong>Gain total EUR / EUR-j</strong> = derive du PnL final si disponible, sinon du return final applique au capital initial ;
    <strong>Jours testes</strong> = plage de donnees reelle si disponible, sinon estimation via le nombre de barres et le timeframe.
</div>
"""
    st.markdown(recap_table_html, unsafe_allow_html=True)

    # Meilleur global
    if history:
        best = max(history, key=_autonomous_history_strategy_sort_key)
        st.success(
            f"**Meilleure session :** Return {_fmt_float(best.get('final_return', best.get('best_return')), '{:+.2f}%')} "
            f"(Sharpe {_fmt_float(best.get('final_sharpe', best.get('best_sharpe')), '{:.3f}')}) — "
            f"{best.get('objective', '')[:80]}"
        )

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

    latest_multi_entry = next(
        (
            item
            for item in reversed(history)
            if str(item.get("orchestration_mode", "") or "") == "multi_llm"
        ),
        None,
    )
    if isinstance(latest_multi_entry, dict):
        _render_builder_campaign_memory_card(
            latest_multi_entry,
            title="Mémoire de campagne actuelle",
        )
        _render_multi_llm_session_analysis_panel(
            latest_multi_entry,
            title="Analyse avancée multi-LLM actuelle",
        )


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
    execution_preferences = resolve_builder_execution_preferences(state)
    builder_execution_mode = str(
        execution_preferences["builder_execution_mode"] or BUILDER_EXECUTION_MODE_MONO
    )
    orchestration_mode = (
        "multi_llm"
        if builder_execution_mode != BUILDER_EXECUTION_MODE_MONO
        else "single_llm"
    )
    builder_multi_llm_enabled = bool(
        execution_preferences["builder_multi_llm_enabled"]
    )
    flow_analysis_preferences = resolve_builder_flow_analysis_preferences(state)
    builder_flow_analysis_enabled = bool(
        flow_analysis_preferences["builder_flow_analysis_enabled"]
    )
    builder_flow_analysis_ablation = dict(
        flow_analysis_preferences["builder_flow_analysis_ablation"]
    )
    builder_multi_llm_profile = str(
        getattr(state, "builder_multi_llm_profile", DEFAULT_MULTI_LLM_PROFILE)
        or DEFAULT_MULTI_LLM_PROFILE
    )
    llm_inference_global_settings = normalize_llm_inference_settings(
        getattr(state, "llm_inference_global_settings", None)
    )
    llm_inference_model_profiles = normalize_llm_model_inference_profiles(
        getattr(state, "llm_inference_model_profiles", None)
    )
    builder_multi_llm_role_overrides = normalize_builder_multi_llm_role_pool_overrides(
        getattr(state, "builder_multi_llm_role_overrides", {}) or {}
    )
    if not builder_multi_llm_enabled:
        st.session_state.pop("builder_runtime_diagnostic", None)
    orchestration_label = "Mono"
    if builder_execution_mode == BUILDER_EXECUTION_MODE_EXPERT:
        orchestration_label = "Multi-LLM Expert"
    elif builder_execution_mode == BUILDER_EXECUTION_MODE_DUAL_LANE:
        orchestration_label = "Multi-LLM Dual Lane"
    capital_raw = getattr(state, "builder_capital", 10000.0)
    try:
        capital = float(capital_raw)
    except (TypeError, ValueError):
        capital = 10000.0

    # Contexte de marché — si rien n'est sélectionné, on pioche parmi les tokens disponibles
    available_tokens = list(getattr(state, "available_tokens", []) or [])
    available_tfs = _sanitize_builder_timeframes(
        list(getattr(state, "available_timeframes", []) or []),
        fallback="1h",
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

    autonomous = bool(getattr(state, "builder_autonomous", False))
    autonomous_running = autonomous and bool(st.session_state.get("is_running", False))

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

        idle_runtime_lines: List[str] = []
        if builder_multi_llm_enabled:
            idle_runtime_lines.append(f"Profil multi-LLM: {builder_multi_llm_profile}")
            if builder_multi_llm_role_overrides:
                idle_runtime_lines.append(
                    "Pools par rôle: "
                    + _format_builder_role_pool_summary(
                        builder_multi_llm_role_overrides
                    )
                )
        _render_builder_runtime_notes(
            "🧩 Détails runtime autonome",
            idle_runtime_lines,
            expanded=False,
        )
        st.info(
            "Mode autonome prêt. Cliquez sur Lancer pour démarrer la sonde marché, "
            "préparer le runtime LLM et enchaîner les sessions."
        )
        if history:
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
        st.session_state.is_running = False

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
                pass
        if df is None or len(df) == 0:
            with status_container:
                show_status("error", "Aucune donnée OHLCV chargée — sélectionnez un token et timeframe, ou activez le mode autonome.")
            st.session_state.is_running = False
            return
    elif (df is None or len(df) == 0) and autonomous:
        # Mode autonome: ne jamais bloquer sur une présélection UI vide ou invalide.
        requested_symbol = symbol
        requested_timeframe = timeframe
        probe_symbols = list(all_symbols)
        probe_timeframes = list(all_timeframes)
        if auto_market_pick:
            probe_symbols = _dedupe_keep_order(
                [*probe_symbols, *available_tokens],
                upper=True,
            )
            if not user_timeframes:
                probe_timeframes = _sanitize_builder_timeframes(
                    _dedupe_keep_order(
                        [*probe_timeframes, *available_tfs],
                        upper=False,
                    ),
                    fallback=timeframe or "1h",
                )

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
    # Mode MANUEL (comportement original)
    # ══════════════════════════════════════════════════════════════════════
    if not autonomous:
        raw_objective = str(getattr(state, "builder_objective", "") or "")
        objective = sanitize_objective_text(raw_objective)
        if raw_objective.strip() != objective:
            st.warning(
                "Objectif nettoyé automatiquement (des lignes de logs ont été retirées)."
            )
            st.session_state["builder_objective"] = objective
            # Ne pas modifier la clé widget après instanciation (StreamlitAPIException).
            # La sidebar appliquera cette synchro au prochain rerun, avant de créer le widget.
            st.session_state["_builder_objective_input_sync"] = objective
        if not objective or not objective.strip():
            with status_container:
                show_status("error", "Objectif vide — décrivez la stratégie souhaitée")
            st.session_state.is_running = False
            return

        _render_builder_mode_hero(
            mode_label="Manuel",
            orchestration_label=orchestration_label,
            market_label=f"{symbol} {timeframe}",
            target_sharpe=target_sharpe,
            capital=capital,
            auto_market_pick=auto_market_pick,
            extra_chips=[f"Max itérations: {max_iterations}"],
            subtitle="Session unique orientée création et lecture rapide des itérations, avec les détails runtime repoussés au second niveau.",
        )
        # Flux de pensée
        with st.expander("📂 Flux de pensée en terminal (optionnel)", expanded=False):
            st.code(
                f'Get-Content "{STREAM_FILE}" -Wait -Tail 80',
                language="powershell",
            )
            st.caption(
                f"📄 Fichier : `{STREAM_FILE}`  \n"
                "Alternative : surveiller ce fichier dans un terminal séparé."
            )

        st.markdown("---")

        run_model = model
        run_ollama_host = ollama_host
        run_ollama_gpu_target = ""
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
        skip_llm_prepare = False
        run_phase_llm_clients: Dict[str, Any] = {}
        manual_multi_llm_manager: Optional[MultiLLMSessionManager] = None
        manual_session_role_overrides: Dict[str, str] = {}

        if builder_multi_llm_enabled:
            if not _MULTI_LLM_RUNTIME_AVAILABLE:
                st.error("Mode multi-LLM indisponible dans ce workspace.")
                st.session_state.is_running = False
                return
            manual_multi_llm_inventory = discover_local_models(
                ollama_host=ollama_host,
                include_live_ollama=True,
            )
            manual_session_role_overrides = _pick_builder_session_role_overrides(
                builder_multi_llm_role_overrides,
                inventory=manual_multi_llm_inventory,
            )
            manual_multi_llm_manager = MultiLLMSessionManager(
                profile_name=builder_multi_llm_profile,
                base_llm_config=apply_llm_inference_settings(
                    LLMConfig(
                        provider=LLMProvider.OLLAMA,
                        model=model,
                        ollama_host=ollama_host,
                    ),
                    model_name=model,
                    global_settings=llm_inference_global_settings,
                    model_profiles=llm_inference_model_profiles,
                ),
                inventory=manual_multi_llm_inventory,
                llm_topology_config=getattr(state, "llm_topology_config", None),
                inference_global_settings=llm_inference_global_settings,
                inference_model_profiles=llm_inference_model_profiles,
                role_overrides=manual_session_role_overrides or None,
            )
            if auto_start_ollama:
                ok, startup_messages = _ensure_multi_llm_runtime_hosts(
                    manual_multi_llm_manager
                )
                if not ok:
                    st.error("\n".join(startup_messages))
                    st.session_state.is_running = False
                    return
            builder_assignment = manual_multi_llm_manager.resolve_role_assignment(
                "builder_llm"
            )
            builder_route = manual_multi_llm_manager.resolve_role_route("builder_llm")
            if builder_assignment is None or not builder_assignment.available:
                st.error(
                    "Le role `builder_llm` du profil multi-LLM n'est pas utilisable "
                    f"sur `{builder_route.ollama_host}`."
                )
                _release_multi_llm_runtime(manual_multi_llm_manager)
                st.session_state.is_running = False
                return
            run_model = manual_multi_llm_manager.resolve_builder_model()
            run_ollama_host = builder_route.ollama_host
            run_ollama_gpu_target = str(builder_route.gpu_target or "")
            _sync_builder_runtime_diagnostic(
                manual_multi_llm_manager,
                mode="multi_llm",
                event="manual_runtime_ready",
                phase="initialisation",
                iteration=0,
                max_iterations=max_iterations,
                session_label="Builder manuel",
                objective=objective,
            )
            runtime_lines: List[str] = []
            if manual_multi_llm_manager.missing_roles:
                st.warning(
                    "Multi-LLM partiel: roles manquants = "
                    + ", ".join(manual_multi_llm_manager.missing_roles)
                )
            else:
                runtime_lines.append(
                    f"Builder actif: `{run_model}` @ `{run_ollama_host}`"
                )
            if builder_multi_llm_role_overrides:
                runtime_lines.append(
                    "Pools par rôle: "
                    + _format_builder_role_pool_summary(builder_multi_llm_role_overrides)
                )
            if manual_session_role_overrides:
                runtime_lines.append(
                    "Tirage session verrouillé: "
                    + ", ".join(
                        f"{role}=`{selected_model}`"
                        for role, selected_model in manual_session_role_overrides.items()
                    )
                )
            _render_builder_runtime_notes("🧩 Runtime Builder", runtime_lines, expanded=False)

        llm_client_for_market = None
        if auto_market_pick:
            market_model = run_model
            market_host = run_ollama_host
            market_gpu_target = run_ollama_gpu_target
            market_role = "builder_llm"
            if (
                builder_multi_llm_enabled
                and manual_multi_llm_manager is not None
            ):
                idea_assignment = manual_multi_llm_manager.resolve_role_assignment(
                    "idea_llm"
                )
                if (
                    idea_assignment is not None
                    and idea_assignment.available
                    and idea_assignment.resolved_model
                ):
                    market_role = "idea_llm"
                    market_model = idea_assignment.resolved_model
                    idea_route = manual_multi_llm_manager.resolve_role_route(
                        "idea_llm"
                    )
                    market_host = idea_route.ollama_host
                    market_gpu_target = str(idea_route.gpu_target or "")
            with st.spinner(
                f"⏳ Préparation LLM `{market_model}` ({market_host})…"
            ):
                if manual_multi_llm_manager is not None and market_role in SIMPLE_MULTI_LLM_ACTIVE_ROLES:
                    ok, msg, resolved_model = _prepare_multi_llm_role_runtime_with_failover(
                        manual_multi_llm_manager,
                        role=market_role,
                        preload_model=preload_model,
                        keep_alive_minutes=keep_alive_minutes,
                        auto_start_ollama=auto_start_ollama,
                    )
                else:
                    ok, msg, resolved_model = _prepare_builder_llm(
                        model=market_model,
                        ollama_host=market_host,
                        gpu_target=market_gpu_target or None,
                        preload_model=preload_model,
                        keep_alive_minutes=keep_alive_minutes,
                        auto_start_ollama=auto_start_ollama,
                    )
                if ok:
                    st.caption(f"✅ {msg}")
                    market_model = resolved_model
                    if manual_multi_llm_manager is not None:
                        manual_multi_llm_manager.activate_runtime_model(
                            market_model,
                            ollama_host=market_host,
                            gpu_target=market_gpu_target or None,
                            role=market_role,
                            reason="market_selection_prepare",
                        )
                        _sync_builder_runtime_diagnostic(
                            manual_multi_llm_manager,
                            mode="multi_llm",
                            event="market_runtime_ready",
                            phase="objective_gen",
                            iteration=0,
                            max_iterations=max_iterations,
                            session_label="Builder manuel",
                            objective=objective,
                        )
                else:
                    st.error(f"❌ {msg}")
                    _release_multi_llm_runtime(manual_multi_llm_manager)
                    st.session_state.is_running = False
                    return

            if (
                builder_multi_llm_enabled
                and manual_multi_llm_manager is not None
            ):
                llm_client_for_market = manual_multi_llm_manager.build_role_client(
                    market_role
                )
                if llm_client_for_market is None:
                    llm_client_for_market = create_llm_client(
                        apply_llm_inference_settings(
                            LLMConfig(
                                provider=LLMProvider.OLLAMA,
                                model=market_model,
                                ollama_host=market_host,
                            ),
                            model_name=market_model,
                            global_settings=llm_inference_global_settings,
                            model_profiles=llm_inference_model_profiles,
                        ),
                    )
                else:
                    llm_client_for_market.config.model = market_model
                    llm_client_for_market.config.ollama_host = market_host
                    apply_llm_inference_settings(
                        llm_client_for_market.config,
                        model_name=market_model,
                        global_settings=llm_inference_global_settings,
                        model_profiles=llm_inference_model_profiles,
                    )
            else:
                llm_client_for_market = create_llm_client(
                    apply_llm_inference_settings(
                        LLMConfig(
                            provider=LLMProvider.OLLAMA,
                            model=market_model,
                            ollama_host=market_host,
                        ),
                        model_name=market_model,
                        global_settings=llm_inference_global_settings,
                        model_profiles=llm_inference_model_profiles,
                    ),
                )
                run_model = market_model
                run_ollama_host = market_host
                skip_llm_prepare = True
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
                "market_pick": dict(market_pick),
            }

            confidence = float(market_pick.get("confidence", 0.0) or 0.0)
            reason = str(market_pick.get("reason", "") or "").strip()
            source = str(market_pick.get("source", "") or "")
            data_source = str(market_pick.get("data_source", "") or "")
            if market_pick.get("load_error"):
                st.warning(
                    "⚠️ Choix marché LLM ignoré (chargement données impossible). "
                    f"Fallback sur {symbol} {timeframe}. "
                    f"Détail: {market_pick.get('load_error')}"
                )
            st.info(
                f"🧭 Marché sélectionné: `{run_symbol} {run_timeframe}` "
                f"(source: `{source}`, données: `{data_source}`, confiance: {confidence:.2f})."
            )
            if reason:
                st.caption(f"Raison LLM: {reason}")

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
            if manual_universe_mode != UNIVERSE_MODE_CANONICAL:
                st.caption("Le mode exploratoire reste disponible, mais il doit être activé explicitement.")
            _release_multi_llm_runtime(manual_multi_llm_manager)
            st.session_state.is_running = False
            return

        if (
            builder_multi_llm_enabled
            and manual_multi_llm_manager is not None
        ):
            with st.spinner(
                f"⏳ Préparation builder_llm `{run_model}` ({run_ollama_host})…"
            ):
                ok, msg, resolved_model = _prepare_multi_llm_role_runtime_with_failover(
                    manual_multi_llm_manager,
                    role="builder_llm",
                    preload_model=preload_model,
                    keep_alive_minutes=keep_alive_minutes,
                    auto_start_ollama=auto_start_ollama,
                )
                if ok:
                    st.caption(f"✅ {msg}")
                    run_model = resolved_model
                    run_phase_llm_clients = manual_multi_llm_manager.build_builder_phase_clients()
                    manual_multi_llm_manager.activate_runtime_model(
                        run_model,
                        ollama_host=run_ollama_host,
                        gpu_target=run_ollama_gpu_target or None,
                        role="builder_llm",
                        reason="builder_session_prepare",
                    )
                    _sync_builder_runtime_diagnostic(
                        manual_multi_llm_manager,
                        mode="multi_llm",
                        event="builder_runtime_ready",
                        phase="code",
                        iteration=0,
                        max_iterations=max_iterations,
                        session_label="Builder manuel",
                        objective=objective,
                    )
                    skip_llm_prepare = True
                else:
                    st.error(f"❌ {msg}")
                    _release_multi_llm_runtime(manual_multi_llm_manager)
                    st.session_state.is_running = False
                    return

        session = _run_single_builder_session(
            objective=objective,
            model=run_model,
            ollama_host=run_ollama_host,
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
            skip_llm_prepare=skip_llm_prepare,
            phase_llm_clients=run_phase_llm_clients or None,
            multi_llm_manager=manual_multi_llm_manager,
            builder_execution_mode=builder_execution_mode,
            orchestration_mode=orchestration_mode,
            builder_flow_analysis_enabled=builder_flow_analysis_enabled,
            builder_flow_analysis_ablation=builder_flow_analysis_ablation,
            multi_llm_profile=builder_multi_llm_profile,
            multi_llm_role_overrides=manual_session_role_overrides,
            multi_llm_assignments=(
                [
                    assignment.to_dict()
                    for assignment in manual_multi_llm_manager.assignments
                ]
                if manual_multi_llm_manager is not None
                else []
            ),
            run_multi_llm_review=(
                builder_multi_llm_enabled and manual_multi_llm_manager is not None
            ),
        )
        _release_multi_llm_runtime(manual_multi_llm_manager)
        if manual_multi_llm_manager is not None:
            _sync_builder_runtime_diagnostic(
                manual_multi_llm_manager,
                mode="multi_llm",
                event="manual_cleanup",
                phase="cleanup",
                iteration=len(getattr(session, "iterations", []) or []) if session is not None else 0,
                max_iterations=max_iterations,
                status=str(getattr(session, "status", "") or ("error" if session is None else "")),
                session_label="Builder manuel",
                objective=objective,
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
        else:
            st.session_state.is_running = False

        return

    # ══════════════════════════════════════════════════════════════════════
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
    autonomous_runtime_lines: List[str] = []
    if builder_multi_llm_enabled:
        autonomous_runtime_lines.append(f"Profil multi-LLM: {builder_multi_llm_profile}")
        autonomous_runtime_lines.append(
            "Décision de boucle: routeur déterministe local après `critic_llm` et `risk_llm`."
        )
        if builder_multi_llm_role_overrides:
            autonomous_runtime_lines.append(
                "Pools par rôle: " + _format_builder_role_pool_summary(builder_multi_llm_role_overrides)
            )
    _render_builder_runtime_notes("🧩 Détails runtime autonome", autonomous_runtime_lines, expanded=False)

    # Flux de pensée
    with st.expander("📂 Flux de pensée en terminal (optionnel)", expanded=False):
        st.code(
            f'Get-Content "{STREAM_FILE}" -Wait -Tail 80',
            language="powershell",
        )
        st.caption(
            f"📄 Fichier : `{STREAM_FILE}`  \n"
            "Alternative : surveiller ce fichier dans un terminal séparé."
        )

    st.markdown("---")

    multi_llm_manager: Optional[MultiLLMSessionManager] = None
    multi_llm_inventory: Any = None
    builder_runtime_host = ollama_host
    builder_runtime_gpu_target = ""
    if builder_multi_llm_enabled:
        if not _MULTI_LLM_RUNTIME_AVAILABLE:
            show_status("error", "Mode multi-LLM indisponible dans ce workspace.")
            _abort_autonomous_start(
                "multi_llm_runtime_unavailable",
                "Mode multi-LLM indisponible dans ce workspace.",
            )
            return
        multi_llm_inventory = discover_local_models(
            ollama_host=ollama_host,
            include_live_ollama=True,
        )
        multi_llm_manager = MultiLLMSessionManager(
            profile_name=builder_multi_llm_profile,
            base_llm_config=apply_llm_inference_settings(
                LLMConfig(
                    provider=LLMProvider.OLLAMA,
                    model=model,
                    ollama_host=ollama_host,
                ),
                model_name=model,
                global_settings=llm_inference_global_settings,
                model_profiles=llm_inference_model_profiles,
            ),
            inventory=multi_llm_inventory,
            llm_topology_config=getattr(state, "llm_topology_config", None),
            inference_global_settings=llm_inference_global_settings,
            inference_model_profiles=llm_inference_model_profiles,
            role_overrides=None,
        )
        if auto_start_ollama:
            ok, messages = _ensure_multi_llm_runtime_hosts(multi_llm_manager)
            if not ok:
                show_status("error", "\n".join(messages))
                _abort_autonomous_start(
                    "multi_llm_runtime_host_boot_failed",
                    "\n".join(messages),
                )
                return
            for msg in messages:
                st.caption(f"✅ {msg}")
        role_runtime_summary = " | ".join(
            (
                f"{assignment.role}=`{assignment.resolved_model or assignment.requested_model or '-'}"
                f"`@{multi_llm_manager.resolve_role_route(assignment.role).ollama_host}"
                f"{'' if assignment.available else ' [indisponible]'}"
            )
            for assignment in multi_llm_manager.assignments
            if assignment.role in SIMPLE_MULTI_LLM_ACTIVE_ROLES
        )
        if role_runtime_summary:
            st.caption(f"Roles runtime: {role_runtime_summary}")
        builder_assignment = multi_llm_manager.resolve_role_assignment("builder_llm")
        builder_route = multi_llm_manager.resolve_role_route("builder_llm")
        builder_runtime_host = builder_route.ollama_host
        builder_runtime_gpu_target = str(builder_route.gpu_target or "")
        _sync_builder_runtime_diagnostic(
            multi_llm_manager,
            mode="multi_llm",
            event="autonomous_runtime_ready",
            phase="initialisation",
            iteration=0,
            max_iterations=max_iterations,
            session_label="Builder autonome",
            objective="",
        )
        if builder_assignment is None or not builder_assignment.available:
            show_status(
                "error",
                "Le role `builder_llm` par defaut du profil multi-LLM n'est pas utilisable "
                f"sur `{builder_runtime_host}`. Corrige le profil ou l'hôte avant de lancer.",
            )
            _abort_autonomous_start(
                "multi_llm_builder_role_unavailable",
                (
                    "Le role `builder_llm` par defaut du profil multi-LLM n'est pas utilisable "
                    f"sur `{builder_runtime_host}`."
                ),
            )
            return
        if multi_llm_manager.missing_roles:
            st.warning(
                "Multi-LLM partiel: roles manquants = "
                + ", ".join(multi_llm_manager.missing_roles)
            )
        else:
            st.caption("✅ Tous les roles LLM actifs sont resolus pour le runtime actif.")
        if builder_multi_llm_role_overrides:
            st.caption(
                "Pools par role: "
                + _format_builder_role_pool_summary(builder_multi_llm_role_overrides)
            )
    else:
        # Préparer LLM une seule fois pour toute la boucle autonome
        _heartbeat_builder_autonomous_runtime(
            last_event="runtime_prepare",
            last_progress_event="runtime_prepare",
            last_progress_phase="initialisation",
        )
        with st.spinner(f"⏳ Préparation LLM `{model}` ({ollama_host})…"):
            ok, msg, resolved_model, lazy_fallback_used = _prepare_builder_llm_resilient(
                model=model,
                ollama_host=ollama_host,
                gpu_target=None,
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
                single_llm_prepared_host = _normalize_ollama_host(ollama_host)
            else:
                show_status("error", msg)
                _abort_autonomous_start(
                    "single_llm_runtime_prepare_failed",
                    msg,
                )
                return

    objective_indicators = _get_builder_compatible_indicators(df)
    autonomous_resume_ui_state["builder_model_single_llm"] = str(model or "")
    autonomous_resume_ui_state["builder_ollama_host"] = str(ollama_host or "")
    _heartbeat_builder_autonomous_runtime(
        last_event="runtime_ready",
        last_progress_event="runtime_ready",
        last_progress_phase="initialisation",
        model=str(model or ""),
        ollama_host=str(ollama_host or ""),
        requested_source_mode=str(requested_objective_mode or ""),
        auto_market_pick=bool(auto_market_pick),
        resume_ui_state=autonomous_resume_ui_state,
    )

    # Historique des sessions autonomes
    if "builder_autonomous_history" not in st.session_state:
        st.session_state["builder_autonomous_history"] = list(
            persisted_supervisor_state.get("history", [])
        )
    if "builder_autonomous_supervisor" not in st.session_state:
        st.session_state["builder_autonomous_supervisor"] = dict(
            persisted_supervisor_state.get(
                "supervisor", _default_autonomous_supervisor_state()
            )
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
    _consecutive_errors = int(supervisor.get("consecutive_errors", 0) or 0)
    _MAX_CONSECUTIVE_ERRORS = 5  # Arrêt de sécurité après N erreurs consécutives
    terminal_reason = "completed"
    terminal_error = ""
    single_llm_runtime_prepared = False
    single_llm_prepared_model = ""
    single_llm_prepared_host = ""

    while st.session_state.get("is_running", False):
        if st.session_state.get("stop_requested", False):
            terminal_reason = "manual_stop"
            break
        session_num += 1
        _loop_body_start = time.perf_counter()
        session_started_at = datetime.now()
        effective_objective_mode = requested_objective_mode
        effective_auto_market_pick = auto_market_pick
        session_model = model
        session_llm_host = builder_runtime_host
        session_llm_gpu_target = builder_runtime_gpu_target
        session_phase_llm_clients: Dict[str, Any] = {}
        session_role_overrides: Dict[str, str] = {}
        llm_client_for_obj = None
        llm_client_for_market = None
        multi_llm_role_outputs: Dict[str, Any] = {}
        multi_llm_router_decision: Dict[str, Any] = {}
        multi_llm_shared_memory: Dict[str, Any] = {}

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
                effective_source_mode=effective_objective_mode,
                auto_market_pick=effective_auto_market_pick,
            )

            if st.session_state.get("stop_requested", False):
                terminal_reason = "manual_stop"
                break

            if builder_multi_llm_enabled:
                session_role_overrides = _pick_builder_session_role_overrides(
                    builder_multi_llm_role_overrides,
                    inventory=multi_llm_inventory,
                )
                multi_llm_manager = MultiLLMSessionManager(
                    profile_name=builder_multi_llm_profile,
                    base_llm_config=apply_llm_inference_settings(
                        LLMConfig(
                            provider=LLMProvider.OLLAMA,
                            model=model,
                            ollama_host=ollama_host,
                        ),
                        model_name=model,
                        global_settings=llm_inference_global_settings,
                        model_profiles=llm_inference_model_profiles,
                    ),
                    inventory=multi_llm_inventory,
                    llm_topology_config=getattr(state, "llm_topology_config", None),
                    inference_global_settings=llm_inference_global_settings,
                    inference_model_profiles=llm_inference_model_profiles,
                    role_overrides=session_role_overrides or None,
                )
                if auto_start_ollama and _is_local_ollama_host(builder_runtime_host):
                    ok, msg = ensure_ollama_running(
                        ollama_host=builder_runtime_host,
                        gpu_target=builder_runtime_gpu_target or None,
                    )
                    if not ok:
                        raise RuntimeError(msg)
                session_model = multi_llm_manager.resolve_builder_model()
                builder_route = multi_llm_manager.resolve_role_route("builder_llm")
                session_llm_host = builder_route.ollama_host
                session_llm_gpu_target = str(builder_route.gpu_target or "")
                session_phase_llm_clients = (
                    multi_llm_manager.build_builder_phase_clients()
                )
                if session_role_overrides:
                    st.caption(
                        "Tirage session verrouille jusqu'a la fin du run: "
                        + ", ".join(
                            f"{role}=`{selected_model}`"
                            for role, selected_model in session_role_overrides.items()
                        )
                    )
                if effective_auto_market_pick:
                    market_role = "builder_llm"
                    idea_assignment = multi_llm_manager.resolve_role_assignment(
                        "idea_llm"
                    )
                    if (
                        idea_assignment is not None
                        and idea_assignment.available
                        and idea_assignment.resolved_model
                    ):
                        market_role = "idea_llm"
                    llm_client_for_market = multi_llm_manager.build_role_client(
                        market_role
                    )
                    if llm_client_for_market is None:
                        llm_client_for_market = create_llm_client(
                            apply_llm_inference_settings(
                                LLMConfig(
                                    provider=LLMProvider.OLLAMA,
                                    model=session_model,
                                    ollama_host=session_llm_host,
                                ),
                                model_name=session_model,
                                global_settings=llm_inference_global_settings,
                                model_profiles=llm_inference_model_profiles,
                            )
                        )
            else:
                reuse_prepared_runtime = (
                    session_num == 1
                    and single_llm_runtime_prepared
                    and str(model or "").strip() == single_llm_prepared_model
                    and _normalize_ollama_host(ollama_host) == single_llm_prepared_host
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
                            ollama_host=ollama_host,
                            gpu_target=None,
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
                        single_llm_prepared_host = _normalize_ollama_host(ollama_host)

                llm_config_shared = apply_llm_inference_settings(
                    LLMConfig(
                        provider=LLMProvider.OLLAMA,
                        model=model,
                        ollama_host=ollama_host,
                    ),
                    model_name=model,
                    global_settings=llm_inference_global_settings,
                    model_profiles=llm_inference_model_profiles,
                )
                if effective_objective_mode == "llm":
                    llm_client_for_obj = create_llm_client(llm_config_shared)
                if effective_auto_market_pick:
                    llm_client_for_market = create_llm_client(llm_config_shared)

            # ── Générer l'objectif (multi-market : listes symbols/timeframes) ──
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
            if builder_multi_llm_enabled and multi_llm_manager is not None:
                multi_objective_bundle = multi_llm_manager.generate_objective(
                    symbols=all_symbols,
                    timeframes=all_timeframes,
                    available_indicators=objective_indicators,
                    history_tail=history,
                    fallback_objective=objective,
                )
                objective = str(multi_objective_bundle.get("objective", "") or objective)
                idea_output = multi_objective_bundle.get("role_output")
                if idea_output is not None:
                    source_label = "LLM multi-role"
                    multi_llm_role_outputs["idea_llm"] = idea_output.to_dict()
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
            if builder_multi_llm_enabled and multi_llm_manager is not None:
                multi_llm_manager.set_selected_market(
                    symbol=session_symbol,
                    timeframe=session_timeframe,
                )

            # ── Exécuter la session (remplace l'affichage précédent) ──
            if builder_multi_llm_enabled and multi_llm_manager is not None:
                with st.spinner(f"⏳ Préparation builder_llm session #{session_num}…"):
                    ok, msg, resolved_model = _prepare_multi_llm_role_runtime_with_failover(
                        multi_llm_manager,
                        role="builder_llm",
                        preload_model=preload_model,
                        keep_alive_minutes=keep_alive_minutes,
                        auto_start_ollama=auto_start_ollama,
                    )
                    if not ok:
                        raise RuntimeError(msg)
                    session_model = resolved_model
                    session_phase_llm_clients = multi_llm_manager.build_builder_phase_clients()
                    multi_llm_manager.activate_runtime_model(
                        session_model,
                        ollama_host=session_llm_host,
                        gpu_target=session_llm_gpu_target or None,
                        role="builder_llm",
                        reason="builder_session_prepare",
                    )
                    _sync_builder_runtime_diagnostic(
                        multi_llm_manager,
                        mode="multi_llm",
                        event="builder_runtime_ready",
                        phase="code",
                        iteration=session_num,
                        max_iterations=max_iterations,
                        session_label=f"Session autonome #{session_num}",
                        objective=objective,
                    )
                st.caption(
                    f"Session #{session_num} | builder_llm=`{session_model}` | "
                    f"host=`{session_llm_host}` | profil=`{builder_multi_llm_profile}`"
                )
            if st.session_state.get("stop_requested", False):
                terminal_reason = "manual_stop"
                if builder_multi_llm_enabled and multi_llm_manager is not None:
                    _release_multi_llm_runtime(multi_llm_manager)
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
                        llm_inference_global_settings=llm_inference_global_settings,
                        llm_inference_model_profiles=llm_inference_model_profiles,
                        llm_topology_config=getattr(state, "llm_topology_config", None),
                        preload_model=preload_model,
                        keep_alive_minutes=keep_alive_minutes,
                        unload_after_run=True,
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
                        multi_llm_manager=multi_llm_manager,
                        builder_execution_mode=builder_execution_mode,
                        orchestration_mode=orchestration_mode,
                        builder_flow_analysis_enabled=builder_flow_analysis_enabled,
                        builder_flow_analysis_ablation=builder_flow_analysis_ablation,
                        multi_llm_profile=builder_multi_llm_profile,
                        multi_llm_role_overrides=session_role_overrides,
                        multi_llm_assignments=(
                            [
                                assignment.to_dict()
                                for assignment in multi_llm_manager.assignments
                            ]
                            if multi_llm_manager is not None
                            else []
                        ),
                    )
                    duration = time.perf_counter() - t0

            if (
                builder_multi_llm_enabled
                and multi_llm_manager is not None
                and session is not None
            ):
                multi_review_payload = _finalize_multi_llm_session_review(
                    objective=objective,
                    session=session,
                    target_sharpe=target_sharpe,
                    multi_llm_manager=multi_llm_manager,
                    persist_summary=True,
                )
                multi_llm_router_decision = dict(
                    multi_review_payload.get("router_decision", {}) or {}
                )
                multi_llm_role_outputs = dict(
                    multi_review_payload.get("role_outputs", {}) or {}
                )
                router_action = str(
                    multi_llm_router_decision.get("action", "iterate") or "iterate"
                )
                router_reason = str(
                    multi_llm_router_decision.get("reason", "") or ""
                ).strip()
                st.caption(
                    f"Multi-LLM router: {router_action}"
                    + (f" | {router_reason}" if router_reason else "")
                )
                multi_llm_shared_memory = dict(
                    multi_review_payload.get("shared_memory", {}) or {}
                )

            if (
                builder_multi_llm_enabled
                and multi_llm_manager is not None
                and not multi_llm_shared_memory
            ):
                multi_llm_shared_memory = multi_llm_manager.consume_shared_memory()
            if builder_multi_llm_enabled and multi_llm_manager is not None:
                _release_multi_llm_runtime(multi_llm_manager)
                _sync_builder_runtime_diagnostic(
                    multi_llm_manager,
                    mode="multi_llm",
                    event="autonomous_cleanup",
                    phase="cleanup",
                    iteration=session_num,
                    max_iterations=max_iterations,
                    status=str(getattr(session, "status", "") or ("error" if session is None else "")),
                    session_label=f"Session autonome #{session_num}",
                    objective=objective,
                )

            # ── Enregistrer le résultat ──
            if session is not None:
                best_return_snapshot = _get_autonomous_session_best_return_snapshot(session)
                final_snapshot = _get_autonomous_session_final_snapshot(session)
                last_runtime_feedback = _extract_autonomous_session_last_runtime_feedback(
                    session
                )
                best_score = getattr(session, "best_score", float("-inf"))
                if best_score == float("-inf"):
                    best_score = None

                history_entry = {
                    "session_num": session_num,
                    "objective": objective,
                    "source_label": source_label,
                    "status": session.status,
                    "best_sharpe": session.best_sharpe,
                    "best_telemetry_score": best_score,
                    "best_score": best_score,
                    "best_return": best_return_snapshot.get("best_return"),
                    "best_return_iteration": best_return_snapshot.get("best_return_iteration"),
                    "best_max_dd": best_return_snapshot.get("best_max_dd"),
                    "best_pf": best_return_snapshot.get("best_pf"),
                    "best_trades": best_return_snapshot.get("best_trades"),
                    "best_return_sharpe": best_return_snapshot.get("best_return_sharpe"),
                    "best_total_pnl": best_return_snapshot.get("best_total_pnl"),
                    "final_return": final_snapshot.get("final_return"),
                    "final_iteration": final_snapshot.get("final_iteration"),
                    "final_max_dd": final_snapshot.get("final_max_dd"),
                    "final_pf": final_snapshot.get("final_pf"),
                    "final_trades": final_snapshot.get("final_trades"),
                    "final_sharpe": final_snapshot.get("final_sharpe"),
                    "final_total_pnl": final_snapshot.get("final_total_pnl"),
                    "n_iterations": len(session.iterations),
                    "duration": duration,
                    "session_id": session.session_id,
                    "started_at": getattr(session, "start_time", session_started_at).isoformat(),
                    "finished_at": datetime.now().isoformat(),
                    "n_bars": getattr(session, "n_bars", 0),
                    "date_range_start": getattr(session, "date_range_start", ""),
                    "date_range_end": getattr(session, "date_range_end", ""),
                    "initial_capital": getattr(session, "initial_capital", capital),
                    "last_runtime_error": last_runtime_feedback.get("last_runtime_error"),
                    "last_runtime_error_iteration": last_runtime_feedback.get("last_runtime_error_iteration"),
                    "last_runtime_traceback_tail": last_runtime_feedback.get("last_runtime_traceback_tail"),
                    "symbol": session_symbol,
                    "timeframe": session_timeframe,
                    "universe_mode": str(getattr(session, "universe_mode", "") or autonomous_universe_mode),
                    "universe_purpose": str(getattr(session, "universe_purpose", "") or "builder_autonomous"),
                    "universe_strategy_type": str(
                        getattr(session, "universe_strategy_type", "") or autonomous_strategy_type
                    ),
                    "universe_meta": (
                        dict(getattr(session, "universe_meta", {}) or {})
                        if isinstance(getattr(session, "universe_meta", {}), dict)
                        else dict(autonomous_universe_meta)
                    ),
                    "source_mode": effective_objective_mode,
                    "source_reason": objective_mode_policy.get("reason", ""),
                    "auto_market_pick_used": effective_auto_market_pick,
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
                    "multi_llm_profile": (
                        builder_multi_llm_profile if builder_multi_llm_enabled else ""
                    ),
                    "multi_llm_role_override_pools": (
                        dict(builder_multi_llm_role_overrides)
                        if builder_multi_llm_enabled
                        else {}
                    ),
                    "multi_llm_role_overrides": (
                        dict(session_role_overrides)
                        if builder_multi_llm_enabled
                        else {}
                    ),
                    "multi_llm_assignments": (
                        [
                            assignment.to_dict()
                            for assignment in multi_llm_manager.assignments
                        ]
                        if builder_multi_llm_enabled and multi_llm_manager is not None
                        else []
                    ),
                    "multi_llm_builder_model": session_model,
                    "multi_llm_router_decision": multi_llm_router_decision,
                    "multi_llm_role_outputs": multi_llm_role_outputs,
                    "multi_llm_shared_memory": multi_llm_shared_memory,
                    "continuity_context": (
                        dict(multi_llm_shared_memory.get("continuity_context", {}) or {})
                        if isinstance(multi_llm_shared_memory, dict)
                        else {}
                    ),
                }
                history.append(history_entry)
                history[:] = _trim_autonomous_history(history)
                st.session_state["builder_autonomous_history"] = history
                st.session_state["builder_session"] = session
                _heartbeat_builder_autonomous_runtime(
                    last_event="session_done",
                    last_session_num=session_num,
                    last_session_id=str(session.session_id or ""),
                    last_session_status=str(session.status or ""),
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
                    "session_num": session_num,
                    "objective": objective,
                    "source_label": source_label,
                    "status": "error",
                    "best_sharpe": None,
                    "best_telemetry_score": None,
                    "best_score": None,
                    "best_return": None,
                    "best_max_dd": None,
                    "best_pf": None,
                    "best_trades": None,
                    "best_total_pnl": None,
                    "final_return": None,
                    "final_iteration": None,
                    "final_max_dd": None,
                    "final_pf": None,
                    "final_trades": None,
                    "final_sharpe": None,
                    "final_total_pnl": None,
                    "n_iterations": 0,
                    "duration": duration,
                    "session_id": "",
                    "started_at": session_started_at.isoformat(),
                    "finished_at": datetime.now().isoformat(),
                    "n_bars": len(session_df) if session_df is not None else 0,
                    "date_range_start": "",
                    "date_range_end": "",
                    "initial_capital": capital,
                    "symbol": session_symbol,
                    "timeframe": session_timeframe,
                    "universe_mode": autonomous_universe_mode,
                    "universe_purpose": "builder_autonomous",
                    "universe_strategy_type": autonomous_strategy_type,
                    "universe_meta": autonomous_universe_meta,
                    "error": session_error_message,
                    "source_mode": effective_objective_mode,
                    "source_reason": objective_mode_policy.get("reason", ""),
                    "auto_market_pick_used": effective_auto_market_pick,
                    "builder_execution_mode": builder_execution_mode,
                    "orchestration_mode": orchestration_mode,
                    "instrumentation_enabled": builder_flow_analysis_enabled,
                    "instrumentation_summary": {},
                    "pipeline_traces_path": "",
                    "multi_llm_profile": (
                        builder_multi_llm_profile if builder_multi_llm_enabled else ""
                    ),
                    "multi_llm_role_override_pools": (
                        dict(builder_multi_llm_role_overrides)
                        if builder_multi_llm_enabled
                        else {}
                    ),
                    "multi_llm_role_overrides": (
                        dict(session_role_overrides)
                        if builder_multi_llm_enabled
                        else {}
                    ),
                    "multi_llm_assignments": (
                        [
                            assignment.to_dict()
                            for assignment in multi_llm_manager.assignments
                        ]
                        if builder_multi_llm_enabled and multi_llm_manager is not None
                        else []
                    ),
                    "multi_llm_builder_model": session_model,
                    "multi_llm_router_decision": multi_llm_router_decision,
                    "multi_llm_role_outputs": multi_llm_role_outputs,
                    "multi_llm_shared_memory": multi_llm_shared_memory,
                    "continuity_context": (
                        dict(multi_llm_shared_memory.get("continuity_context", {}) or {})
                        if isinstance(multi_llm_shared_memory, dict)
                        else {}
                    ),
                }
                history_entry = _recover_autonomous_history_entry_from_disk(history_entry)
                history.append(history_entry)
                history[:] = _trim_autonomous_history(history)
                st.session_state["builder_autonomous_history"] = history
                supervisor["consecutive_failed_sessions"] = int(
                    supervisor.get("consecutive_failed_sessions", 0) or 0
                ) + 1
                _heartbeat_builder_autonomous_runtime(
                    last_event="session_error",
                    last_session_num=session_num,
                    last_session_status="error",
                    effective_source_mode=effective_objective_mode,
                )

            st.session_state["builder_autonomous_supervisor"] = supervisor
            _save_autonomous_supervisor_state(history, supervisor)

            if int(supervisor.get("consecutive_failed_sessions", 0) or 0) >= _AUTONOMOUS_SESSION_FAILURE_RESET_THRESHOLD:
                recovery_plan = _apply_autonomous_supervisor_recovery(
                    supervisor,
                    history,
                    origin="session_failed",
                    current_source_mode=effective_objective_mode,
                )
                st.session_state["builder_autonomous_supervisor"] = supervisor
                _save_autonomous_supervisor_state(history, supervisor)
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
                    terminal_reason = "supervisor_stop"
                    break

            # ── Afficher le récap mis à jour ──
            with recap_placeholder.container():
                _render_autonomous_recap(history, supervisor)


        except KeyboardInterrupt:
            if builder_multi_llm_enabled and multi_llm_manager is not None:
                multi_llm_manager.reset_shared_memory()
                _release_multi_llm_runtime(multi_llm_manager)
            logger.info("Mode autonome interrompu par l'utilisateur (KeyboardInterrupt)")
            terminal_reason = "keyboard_interrupt"
            break
        except Exception as _loop_exc:
            if builder_multi_llm_enabled and multi_llm_manager is not None:
                multi_llm_shared_memory = multi_llm_manager.consume_shared_memory()
                _release_multi_llm_runtime(multi_llm_manager)
            _consecutive_errors += 1
            _exc_tb = traceback.format_exc()
            failure_origin = _classify_autonomous_failure_origin(_loop_exc, _exc_tb)
            supervisor["consecutive_errors"] = _consecutive_errors
            supervisor["consecutive_failed_sessions"] = int(
                supervisor.get("consecutive_failed_sessions", 0) or 0
            ) + 1
            supervisor["last_error_origin"] = failure_origin
            supervisor["last_error"] = f"{type(_loop_exc).__name__}: {_loop_exc}"
            logger.error(
                "Session autonome #%d CRASH (%d/%d erreurs consecutives): %s\n%s",
                session_num, _consecutive_errors, _MAX_CONSECUTIVE_ERRORS,
                _loop_exc, _exc_tb,
            )
            # Enregistrer le crash dans l'historique
            history.append({
                "session_num": session_num,
                "objective": "(crash avant execution)",
                "source_label": "Crash avant generation",
                "status": "crash",
                "best_sharpe": None,
                "best_telemetry_score": None,
                "best_score": None,
                "best_return": None,
                "best_max_dd": None,
                "best_pf": None,
                "best_trades": None,
                "best_total_pnl": None,
                "final_return": None,
                "final_iteration": None,
                "final_max_dd": None,
                "final_pf": None,
                "final_trades": None,
                "final_sharpe": None,
                "final_total_pnl": None,
                "n_iterations": 0,
                "duration": time.perf_counter() - _loop_body_start,
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
                "error": f"{type(_loop_exc).__name__}: {_loop_exc}",
                "source_mode": effective_objective_mode,
                "source_reason": supervisor.get("last_selected_source_reason", ""),
                "builder_execution_mode": builder_execution_mode,
                "orchestration_mode": orchestration_mode,
                "instrumentation_enabled": builder_flow_analysis_enabled,
                "instrumentation_summary": {},
                "pipeline_traces_path": "",
                "multi_llm_profile": (
                    builder_multi_llm_profile if builder_multi_llm_enabled else ""
                ),
                "multi_llm_role_override_pools": (
                    dict(builder_multi_llm_role_overrides)
                    if builder_multi_llm_enabled
                    else {}
                ),
                "multi_llm_role_overrides": (
                    dict(session_role_overrides)
                    if builder_multi_llm_enabled
                    else {}
                ),
                "multi_llm_shared_memory": multi_llm_shared_memory,
                "continuity_context": (
                    dict(multi_llm_shared_memory.get("continuity_context", {}) or {})
                    if isinstance(multi_llm_shared_memory, dict)
                    else {}
                ),
            })
            history[:] = _trim_autonomous_history(history)
            st.session_state["builder_autonomous_history"] = history
            st.session_state["builder_autonomous_supervisor"] = supervisor
            _save_autonomous_supervisor_state(history, supervisor)
            terminal_error = f"{type(_loop_exc).__name__}: {_loop_exc}"
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
            if failure_origin == "llm_runtime_model_name_mismatch":
                st.error(
                    f"Session #{session_num} arrêtée: {type(_loop_exc).__name__}: {_loop_exc}"
                )
                st.error(
                    "Le preset multi-LLM actif ne contient aucun nom exact accepté par l'hôte Ollama courant. "
                    "Corrige les noms du preset ou change d'hôte avant de relancer."
                )
                terminal_reason = "llm_runtime_model_name_mismatch"
                break
            st.error(
                f"Session #{session_num} crash: {type(_loop_exc).__name__}: {_loop_exc} "
                f"-- reprise automatique ({_consecutive_errors}/{_MAX_CONSECUTIVE_ERRORS})"
            )
            if _consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                recovery_plan = _apply_autonomous_supervisor_recovery(
                    supervisor,
                    history,
                    origin=failure_origin,
                    current_source_mode=effective_objective_mode,
                )
                st.session_state["builder_autonomous_supervisor"] = supervisor
                _save_autonomous_supervisor_state(history, supervisor)
                if recovery_plan.get("recover"):
                    _consecutive_errors = 0
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
                        _MAX_CONSECUTIVE_ERRORS,
                    )
                    st.error(
                        f"Arret de securite: {_MAX_CONSECUTIVE_ERRORS} erreurs consecutives. "
                        f"Verifiez les logs et relancez."
                    )
                    terminal_reason = "consecutive_errors_stop"
                    break
        else:
            # Session OK -> reset erreurs consecutives
            _consecutive_errors = 0
            supervisor["consecutive_errors"] = 0
            supervisor["next_pause_multiplier"] = 1
            st.session_state["builder_autonomous_supervisor"] = supervisor
            _save_autonomous_supervisor_state(history, supervisor)

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
            st.session_state["builder_autonomous_supervisor"] = supervisor
            _save_autonomous_supervisor_state(history, supervisor)

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

    st.session_state["builder_autonomous_supervisor"] = supervisor
    _save_autonomous_supervisor_state(history, supervisor)
    st.session_state.is_running = False
    mark_builder_autonomous_runtime_stopped(
        reason=terminal_reason,
        manual_stop=(terminal_reason == "manual_stop"),
        error=terminal_error,
    )
