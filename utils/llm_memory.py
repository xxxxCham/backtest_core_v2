"""
Module-ID: utils.llm_memory

Purpose: Lightweight memory pour runs LLM - session ephemeral + history JSONL append-only.

Role in pipeline: orchestration / data

Key components: SessionMemory, HistoryStorage, LLMMemoryTracker, approved-only persistence

Inputs: Session id, strategy/symbol/timeframe, propositions + évaluations

Outputs: Fichiers JSON session (mutable), JSONL history (append-only)

Dependencies: json, pathlib, datetime, collections

Conventions: Session mutable par run; history immuable (approved results); dirs runs/llm_memory/session et history.

Read-if: Modification format fichiers, logique session/history.

Skip-if: Vous utilisez juste LLMMemoryTracker.save().
"""

from __future__ import annotations

import json
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_BASE_DIR = Path("runs") / "llm_memory"
SESSION_DIRNAME = "session"
HISTORY_DIRNAME = "history"
DEFAULT_MAX_ENTRIES = 3
MAX_INSIGHTS = 5


def _utc_now_iso() -> str:
    ts = datetime.now(timezone.utc).replace(microsecond=0)
    return ts.isoformat().replace("+00:00", "Z")


def _safe_segment(value: Optional[str], fallback: str) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    text = text.replace(" ", "_")
    text = re.sub(r"[^A-Za-z0-9_.-]", "_", text)
    return text or fallback


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def get_session_path(session_id: str, base_dir: Path = DEFAULT_BASE_DIR) -> Path:
    safe_id = _safe_segment(session_id, "session")
    return base_dir / SESSION_DIRNAME / f"{safe_id}.json"


def get_history_path(
    strategy: str,
    symbol: str,
    timeframe: str,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> Path:
    safe_strategy = _safe_segment(strategy, "unknown_strategy")
    safe_symbol = _safe_segment(symbol, "unknown_symbol")
    safe_timeframe = _safe_segment(timeframe, "unknown_timeframe")
    return (
        base_dir
        / HISTORY_DIRNAME
        / safe_strategy
        / safe_symbol
        / f"{safe_timeframe}.jsonl"
    )


def extract_date_range(data: Any) -> Tuple[str, str]:
    if data is None:
        return "", ""
    try:
        import pandas as pd
    except Exception:
        return "", ""

    try:
        if hasattr(data, "index") and isinstance(data.index, pd.DatetimeIndex):
            start = data.index[0]
            end = data.index[-1]
            return str(start), str(end)

        if isinstance(data, pd.DataFrame):
            if "timestamp" in data.columns or "date" in data.columns:
                col = "timestamp" if "timestamp" in data.columns else "date"
                dates = pd.to_datetime(data[col])
                return str(dates.iloc[0]), str(dates.iloc[-1])
    except Exception:
        return "", ""

    return "", ""


def split_date_range(value: Optional[str]) -> Tuple[str, str]:
    if not value:
        return "", ""
    text = str(value)
    if "->" in text:
        start, end = text.split("->", 1)
        return start.strip(), end.strip()
    if "\u2192" in text:
        start, end = text.split("\u2192", 1)
        return start.strip(), end.strip()
    return text.strip(), ""


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    _ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)


def start_session(
    session_id: str,
    *,
    strategy: str,
    symbol: str,
    timeframe: str,
    period_start: str,
    period_end: str,
    model: str,
    data_rows: int,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> Path:
    session_path = get_session_path(session_id, base_dir=base_dir)
    payload = {
        "session_id": session_id,
        "status": "running",
        "started_at": _utc_now_iso(),
        "updated_at": _utc_now_iso(),
        "strategy": strategy,
        "symbol": symbol,
        "timeframe": timeframe,
        "period_start": period_start,
        "period_end": period_end,
        "model": model,
        "data_rows": data_rows,
        "iterations": [],
    }
    _write_json(session_path, payload)
    return session_path


def append_session_iteration(
    session_path: Path,
    entry: Dict[str, Any],
) -> None:
    payload = _read_json(session_path)
    iterations = payload.get("iterations", [])
    if not isinstance(iterations, list):
        iterations = []
    iterations.append(entry)
    payload["iterations"] = iterations
    payload["updated_at"] = _utc_now_iso()
    _write_json(session_path, payload)


def set_session_status(session_path: Path, status: str) -> None:
    payload = _read_json(session_path)
    payload["status"] = status
    payload["updated_at"] = _utc_now_iso()
    _write_json(session_path, payload)


def delete_session(session_path: Path) -> bool:
    try:
        if session_path.exists():
            session_path.unlink()
            return True
    except Exception:
        return False
    return False


def append_history_entry(
    history_path: Path,
    entry: Dict[str, Any],
) -> None:
    _ensure_dir(history_path.parent)
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=True) + "\n")


def load_recent_history_entries(
    history_path: Path,
    limit: int = DEFAULT_MAX_ENTRIES,
) -> List[Dict[str, Any]]:
    if limit <= 0 or not history_path.exists():
        return []
    buffer: deque[Dict[str, Any]] = deque(maxlen=limit)
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if isinstance(entry, dict):
                    buffer.append(entry)
    except Exception:
        return []
    return list(buffer)


def build_memory_summary(
    strategy: str,
    symbol: str,
    timeframe: str,
    limit: int = DEFAULT_MAX_ENTRIES,
    base_dir: Path = DEFAULT_BASE_DIR,
) -> str:
    history_path = get_history_path(
        strategy=strategy,
        symbol=symbol,
        timeframe=timeframe,
        base_dir=base_dir,
    )
    entries = load_recent_history_entries(history_path, limit=limit)
    if not entries:
        return ""
    lines = []
    for entry in entries:
        line = _format_history_line(entry)
        if line:
            lines.append(f"- {line}")
    return "\n".join(lines)


def _format_history_line(entry: Dict[str, Any]) -> str:
    timestamp = entry.get("timestamp") or entry.get("approved_at") or ""
    date = _format_date(timestamp)

    metrics = entry.get("metrics", {}) if isinstance(entry.get("metrics"), dict) else {}
    sharpe = _format_float(metrics.get("sharpe_ratio"))
    ret_pct = _format_pct(metrics.get("total_return_pct"))
    dd_pct = _format_pct(metrics.get("max_drawdown_pct"))
    win_pct = _format_pct(metrics.get("win_rate_pct"))
    trades = metrics.get("total_trades")

    parts = [date, f"sharpe={sharpe}"]
    if ret_pct != "n/a":
        parts.append(f"ret={ret_pct}")
    if dd_pct != "n/a":
        parts.append(f"dd={dd_pct}")
    if win_pct != "n/a":
        parts.append(f"win={win_pct}")
    if trades is not None:
        parts.append(f"trades={trades}")

    line = " ".join(parts)

    params = entry.get("params", {}) if isinstance(entry.get("params"), dict) else {}
    params_summary = _summarize_params(params, limit=3)
    if params_summary:
        line += f" | params: {params_summary}"

    insights = entry.get("insights", [])
    if isinstance(insights, list) and insights:
        note = str(insights[0])
        if note:
            line += f" | note: {note}"

    return line


def _format_date(value: str) -> str:
    if not value:
        return "n/a"
    text = str(value)
    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return text


def _format_float(value: Any) -> str:
    try:
        return f"{float(value):.3f}"
    except Exception:
        return "n/a"


def _format_pct(value: Any) -> str:
    try:
        val = float(value)
    except Exception:
        return "n/a"
    if abs(val) <= 1.0 and abs(val) > 0.0001:
        val *= 100.0
    return f"{val:.1f}%"


def _summarize_params(params: Dict[str, Any], limit: int = 3) -> str:
    if not params:
        return ""
    items = sorted(params.items(), key=lambda kv: str(kv[0]))
    parts = []
    for key, value in items[:limit]:
        parts.append(f"{key}={_format_param(value)}")
    return " ".join(parts)


def _format_param(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)
