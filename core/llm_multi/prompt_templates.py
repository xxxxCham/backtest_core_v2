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
        "Do not run backtests yourself. Use the available market universe only. "
        "Return JSON only with keys: objective, rationale, constraints, strategy_family."
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
            "Target complex but realistic strategies.",
            "Favor robust entry and risk management rules.",
            "Avoid repeating the same exact market or timeframe unless justified.",
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
        "Return JSON only. Prefer short, actionable output."
    )


def build_critic_user_prompt(
    *,
    objective: str,
    session_summary: Dict[str, Any],
) -> str:
    return _json_payload(
        {
            "objective": objective,
            "session_summary": session_summary,
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
        "Return JSON only."
    )


def build_risk_user_prompt(
    *,
    objective: str,
    session_summary: Dict[str, Any],
) -> str:
    return _json_payload(
        {
            "objective": objective,
            "session_summary": session_summary,
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
