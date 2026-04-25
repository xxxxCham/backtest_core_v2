"""Prompt builders for the two-role multi-LLM autonomous builder."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


def _json_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2, default=str)


def build_supervisor_objective_system_prompt() -> str:
    return (
        "You are supervisor_llm for an autonomous trading strategy builder. "
        "Produce one concise, testable strategy objective. "
        "Do not run backtests yourself. Use only the provided market universe, "
        "timeframes, indicators, and continuity context. The objective must be "
        "specific enough for builder_llm to code directly. Return JSON only "
        "with keys: objective, rationale, constraints, strategy_family."
    )


def build_supervisor_objective_user_prompt(
    *,
    symbols: Iterable[str],
    timeframes: Iterable[str],
    available_indicators: Iterable[str],
    history_tail: list[dict[str, Any]],
    continuity_context: dict[str, Any] | None = None,
) -> str:
    payload = {
        "symbols": list(symbols),
        "timeframes": list(timeframes),
        "available_indicators": list(available_indicators),
        "recent_history": history_tail[-5:],
        "continuity_context": continuity_context or {},
        "instructions": [
            "Target realistic strategies that can be implemented from the listed indicators only.",
            "State a clear edge, not just a list of indicators.",
            "Favor robust entry, exit, and risk-management intent.",
            "Avoid repeating the same exact market or timeframe unless justified by recent history.",
            "Use continuity_context as the common reference for recent progress, recurring risks and carry-over focus.",
        ],
        "required_checks": [
            "name the market and timeframe in the objective",
            "mention the intended edge or market behavior",
            "include at least one operational constraint",
        ],
        "required_output": {
            "objective": "one concise objective string",
            "rationale": "short explanation of the edge",
            "constraints": ["constraint1", "constraint2"],
            "strategy_family": "momentum | breakout | mean_reversion | hybrid",
        },
    }
    return _json_payload(payload)


def build_supervisor_review_system_prompt() -> str:
    return (
        "You are supervisor_llm. Review the deterministic builder result as a "
        "single control model: critique robustness, assess trading risk, and "
        "recommend the next loop action. Use deterministic metrics only for "
        "performance claims and preserve continuity with the original intent. "
        "Return JSON only. Prefer short, actionable output."
    )


def build_supervisor_review_user_prompt(
    *,
    objective: str,
    session_summary: dict[str, Any],
    shared_memory: dict[str, Any] | None = None,
    continuity_context: dict[str, Any] | None = None,
    target_sharpe: float,
) -> str:
    return _json_payload(
        {
            "objective": objective,
            "target_sharpe": target_sharpe,
            "shared_memory": shared_memory or {},
            "continuity_context": continuity_context or {},
            "session_summary": session_summary,
            "required_checks": [
                "consistency between objective and actual session outcome",
                "trade count sufficiency",
                "overfitting or fragility signs",
                "drawdown severity",
                "expectancy/profit-factor fragility",
                "next concrete improvement priorities",
            ],
            "allowed_actions": ["accept", "iterate", "recover"],
            "required_output": {
                "verdict": "keep_iterating | promising | weak",
                "critique": "short paragraph",
                "next_focus": ["item1", "item2"],
                "risk_level": "low | medium | high",
                "key_risks": ["risk1", "risk2"],
                "mitigations": ["mitigation1", "mitigation2"],
                "action": "accept | iterate | recover",
                "confidence": 0.0,
                "reason": "short reason for the recommended action",
            },
        },
    )
