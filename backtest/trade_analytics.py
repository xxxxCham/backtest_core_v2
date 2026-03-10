"""
Module-ID: backtest.trade_analytics

Purpose: Analyses simples sur les trades (exit reasons, streaks, exposure).

Role in pipeline: analytics / reporting

Key components: analyze_exit_reasons, calculate_streaks, calculate_exposure
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


def analyze_exit_reasons(trades_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Analyse les raisons de sortie (exit_reason) et leurs performances.

    Returns:
        Dict avec:
            - by_reason: {reason: {count, pnl_sum, win_rate}}
            - most_common_reason
            - most_profitable_reason
    """
    if trades_df is None or trades_df.empty:
        return {
            "by_reason": {},
            "most_common_reason": None,
            "most_profitable_reason": None,
        }

    if "exit_reason" not in trades_df.columns or "pnl" not in trades_df.columns:
        return {
            "by_reason": {},
            "most_common_reason": None,
            "most_profitable_reason": None,
        }

    by_reason: Dict[str, Dict[str, Any]] = {}

    grouped = trades_df.groupby("exit_reason", dropna=False)
    for reason, group in grouped:
        pnl_values = group["pnl"]
        count = int(len(group))
        pnl_sum = float(pnl_values.sum())
        wins = int((pnl_values > 0).sum())
        win_rate = (wins / count * 100.0) if count > 0 else 0.0
        by_reason[str(reason)] = {
            "count": count,
            "pnl_sum": pnl_sum,
            "win_rate": win_rate,
        }

    # Déterminer les raisons principales
    most_common_reason: Optional[str] = None
    most_profitable_reason: Optional[str] = None
    if by_reason:
        most_common_reason = max(
            by_reason.items(),
            key=lambda item: (item[1]["count"], item[0]),
        )[0]
        most_profitable_reason = max(
            by_reason.items(),
            key=lambda item: (item[1]["pnl_sum"], item[0]),
        )[0]

    return {
        "by_reason": by_reason,
        "most_common_reason": most_common_reason,
        "most_profitable_reason": most_profitable_reason,
    }


def _append_streak(streaks: List[int], current: int) -> None:
    if current > 0:
        streaks.append(current)


def calculate_streaks(trades_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calcule les streaks de gains/pertes consécutifs.

    Returns:
        Dict avec max_consecutive_wins, max_consecutive_losses,
        avg_win_streak, avg_loss_streak
    """
    if trades_df is None or trades_df.empty or "pnl" not in trades_df.columns:
        return {
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
            "avg_win_streak": 0.0,
            "avg_loss_streak": 0.0,
        }

    wins_streaks: List[int] = []
    loss_streaks: List[int] = []
    current = 0
    current_type: Optional[str] = None

    for pnl in trades_df["pnl"].tolist():
        if pnl > 0:
            if current_type == "win":
                current += 1
            else:
                _append_streak(loss_streaks, current if current_type == "loss" else 0)
                current_type = "win"
                current = 1
        elif pnl < 0:
            if current_type == "loss":
                current += 1
            else:
                _append_streak(wins_streaks, current if current_type == "win" else 0)
                current_type = "loss"
                current = 1
        else:
            # pnl == 0 -> reset
            if current_type == "win":
                _append_streak(wins_streaks, current)
            elif current_type == "loss":
                _append_streak(loss_streaks, current)
            current_type = None
            current = 0

    # Flush last streak
    if current_type == "win":
        _append_streak(wins_streaks, current)
    elif current_type == "loss":
        _append_streak(loss_streaks, current)

    max_wins = max(wins_streaks) if wins_streaks else 0
    max_losses = max(loss_streaks) if loss_streaks else 0
    avg_wins = float(np.mean(wins_streaks)) if wins_streaks else 0.0
    avg_losses = float(np.mean(loss_streaks)) if loss_streaks else 0.0

    return {
        "max_consecutive_wins": max_wins,
        "max_consecutive_losses": max_losses,
        "avg_win_streak": avg_wins,
        "avg_loss_streak": avg_losses,
    }


def calculate_exposure(trades_df: pd.DataFrame, total_bars: int) -> Dict[str, Any]:
    """
    Calcule l'exposition au marché (% du temps en position).

    Args:
        trades_df: DataFrame avec entry_time, exit_time, pnl
        total_bars: Nombre total de barres dans la période

    Returns:
        Dict avec exposure_pct, avg_duration_winners_hours, avg_duration_losers_hours
    """
    if trades_df is None or trades_df.empty:
        return {
            "exposure_pct": 0.0,
            "avg_duration_winners_hours": 0.0,
            "avg_duration_losers_hours": 0.0,
        }

    if "entry_time" not in trades_df.columns or "exit_time" not in trades_df.columns:
        return {
            "exposure_pct": 0.0,
            "avg_duration_winners_hours": 0.0,
            "avg_duration_losers_hours": 0.0,
        }

    df = trades_df.copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"], errors="coerce")
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce")
    df = df.dropna(subset=["entry_time", "exit_time"])

    if df.empty or total_bars <= 0:
        return {
            "exposure_pct": 0.0,
            "avg_duration_winners_hours": 0.0,
            "avg_duration_losers_hours": 0.0,
        }

    durations_hours = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 3600.0
    total_duration = float(durations_hours.sum())

    # Approx: total_bars équivaut au nombre d'heures si timeframe 1h
    exposure_pct = max(0.0, min(100.0, (total_duration / float(total_bars)) * 100.0))

    winners = df[df.get("pnl", 0) > 0]
    losers = df[df.get("pnl", 0) < 0]

    avg_winners = 0.0
    avg_losers = 0.0
    if not winners.empty:
        w_durations = (winners["exit_time"] - winners["entry_time"]).dt.total_seconds() / 3600.0
        avg_winners = float(w_durations.mean())
    if not losers.empty:
        l_durations = (losers["exit_time"] - losers["entry_time"]).dt.total_seconds() / 3600.0
        avg_losers = float(l_durations.mean())

    return {
        "exposure_pct": exposure_pct,
        "avg_duration_winners_hours": avg_winners,
        "avg_duration_losers_hours": avg_losers,
    }


__all__ = [
    "analyze_exit_reasons",
    "calculate_streaks",
    "calculate_exposure",
]
