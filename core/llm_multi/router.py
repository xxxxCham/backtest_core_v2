"""Decision helpers for the multi-LLM builder pipeline."""

from __future__ import annotations

import json
import re
from typing import Any, Dict


def _extract_json_object(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def normalize_router_action(value: str) -> str:
    lowered = str(value or "").strip().lower()
    if lowered in {"accept", "approve", "ship"}:
        return "accept"
    if lowered in {"recover", "reset", "retry"}:
        return "recover"
    return "iterate"


def parse_router_decision(text: str) -> Dict[str, Any]:
    payload = _extract_json_object(text)
    if payload:
        action = normalize_router_action(payload.get("action", "iterate"))
        return {
            "action": action,
            "confidence": float(payload.get("confidence", 0.0) or 0.0),
            "reason": str(payload.get("reason", "") or "").strip(),
            "raw": text,
        }
    return {
        "action": normalize_router_action(text),
        "confidence": 0.0,
        "reason": str(text or "").strip(),
        "raw": text,
    }


def deterministic_router_decision(
    *,
    session_status: str,
    metrics: Dict[str, Any],
    target_sharpe: float,
    critic_summary: str = "",
    risk_summary: str = "",
) -> Dict[str, Any]:
    sharpe = float(metrics.get("sharpe_ratio", 0.0) or 0.0)
    trades = int(metrics.get("total_trades", 0) or 0)
    drawdown = float(metrics.get("max_drawdown_pct", 0.0) or 0.0)

    if session_status not in {"success", "completed", "max_iterations"}:
        return {
            "action": "recover",
            "confidence": 0.9,
            "reason": "builder session failed",
            "critic_summary": critic_summary,
            "risk_summary": risk_summary,
        }

    if sharpe >= target_sharpe and trades >= 20 and drawdown > -30.0:
        return {
            "action": "accept",
            "confidence": 0.75,
            "reason": "target metrics reached with enough trades",
            "critic_summary": critic_summary,
            "risk_summary": risk_summary,
        }

    if trades < 10 or drawdown <= -35.0:
        return {
            "action": "recover",
            "confidence": 0.7,
            "reason": "fragile run: too few trades or too much drawdown",
            "critic_summary": critic_summary,
            "risk_summary": risk_summary,
        }

    return {
        "action": "iterate",
        "confidence": 0.6,
        "reason": "continue searching for a stronger configuration",
        "critic_summary": critic_summary,
        "risk_summary": risk_summary,
    }
