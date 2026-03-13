"""Prompt builders for the multi-LLM autonomous builder roles."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List


def _json_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2, default=str)


def build_idea_system_prompt() -> str:
    return (
        "You are the idea_llm for an autonomous trading strategy builder. "
        "Produce one concise, testable strategy objective. "
        "Do not run backtests yourself. Use only the provided market universe, "
        "timeframes, and indicators. The objective must be specific enough for "
        "another model to code directly. Return JSON only with keys: objective, "
        "rationale, constraints, strategy_family."
    )


def build_idea_user_prompt(
    *,
    symbols: Iterable[str],
    timeframes: Iterable[str],
    available_indicators: Iterable[str],
    history_tail: List[Dict[str, Any]],
) -> str:
    payload = {
        "symbols": list(symbols),
        "timeframes": list(timeframes),
        "available_indicators": list(available_indicators),
        "recent_history": history_tail[-5:],
        "instructions": [
            "Target realistic strategies that can be implemented from the listed indicators only.",
            "State a clear edge, not just a list of indicators.",
            "Favor robust entry, exit, and risk-management intent.",
            "Avoid repeating the same exact market or timeframe unless justified by recent history.",
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


def build_critic_system_prompt() -> str:
    return (
        "You are critic_llm. Critique the deterministic builder result. "
        "Focus on robustness, overfitting risk, signal quality, and missing tests. "
        "Use the shared memory to keep continuity with the original intent. "
        "Return JSON only. Prefer short, actionable output."
    )


def build_critic_user_prompt(
    *,
    objective: str,
    session_summary: Dict[str, Any],
    shared_memory: Dict[str, Any] | None = None,
) -> str:
    return _json_payload(
        {
            "objective": objective,
            "shared_memory": shared_memory or {},
            "session_summary": session_summary,
            "required_checks": [
                "consistency between objective and actual session outcome",
                "trade count sufficiency",
                "overfitting or fragility signs",
                "next concrete improvement priorities",
            ],
            "required_output": {
                "verdict": "keep_iterating | promising | weak",
                "critique": "short paragraph",
                "next_focus": ["item1", "item2"],
            },
        }
    )


def build_risk_system_prompt() -> str:
    return (
        "You are risk_llm. Assess trading risk from deterministic metrics only. "
        "Flag fragility, excessive drawdown, low trade count, or unstable expectancy. "
        "Use the shared memory to keep continuity with the original intent. "
        "Return JSON only."
    )


def build_risk_user_prompt(
    *,
    objective: str,
    session_summary: Dict[str, Any],
    shared_memory: Dict[str, Any] | None = None,
) -> str:
    return _json_payload(
        {
            "objective": objective,
            "shared_memory": shared_memory or {},
            "session_summary": session_summary,
            "required_checks": [
                "drawdown severity",
                "trade count sufficiency",
                "expectancy/profit-factor fragility",
                "concrete mitigations that could be applied next iteration",
            ],
            "required_output": {
                "risk_level": "low | medium | high",
                "key_risks": ["risk1", "risk2"],
                "mitigations": ["mitigation1", "mitigation2"],
            },
        }
    )


def build_router_system_prompt() -> str:
    return (
        "You are execution_router_llm. Decide the next action for the autonomous "
        "builder loop from the deterministic metrics, critic review, and risk review. "
        "Return JSON with keys action, confidence, reason."
    )


def build_router_user_prompt(
    *,
    objective: str,
    session_summary: Dict[str, Any],
    critic_summary: str,
    risk_summary: str,
    target_sharpe: float,
) -> str:
    return _json_payload(
        {
            "objective": objective,
            "target_sharpe": target_sharpe,
            "session_summary": session_summary,
            "critic_summary": critic_summary,
            "risk_summary": risk_summary,
            "allowed_actions": ["accept", "iterate", "recover"],
        }
    )
