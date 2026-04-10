"""Helpers for interacting with StrategyBuilder session objects."""

from __future__ import annotations

from typing import Any, Dict


def extract_builder_metrics(session: Any) -> Dict[str, Any]:
    """Extract the most relevant deterministic metrics from a builder session."""

    if session is None:
        return {}

    best_iteration = getattr(session, "best_iteration", None)
    backtest_result = getattr(best_iteration, "backtest_result", None)
    metrics = dict(getattr(backtest_result, "metrics", {}) or {})
    if not metrics and backtest_result is not None:
        metrics = {
            "sharpe_ratio": getattr(backtest_result, "sharpe_ratio", None),
            "total_return_pct": getattr(backtest_result, "total_return_pct", None),
            "max_drawdown_pct": getattr(backtest_result, "max_drawdown_pct", None),
            "profit_factor": getattr(backtest_result, "profit_factor", None),
            "total_trades": getattr(backtest_result, "total_trades", None),
        }
    return metrics


def summarize_builder_session(session: Any) -> Dict[str, Any]:
    metrics = extract_builder_metrics(session)
    return {
        "session_id": getattr(session, "session_id", ""),
        "status": getattr(session, "status", ""),
        "best_sharpe": getattr(session, "best_sharpe", None),
        "iterations": len(getattr(session, "iterations", []) or []),
        "metrics": metrics,
    }
