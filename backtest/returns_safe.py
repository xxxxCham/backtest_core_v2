"""
Module-ID: backtest.returns_safe

Purpose: Calcul de rendements robustes même si l'equity passe sous zéro.

Role in pipeline: performance / robustness

Key components: compute_returns_safe, detect_ruin_index

Inputs: Série d'equity

Outputs: Série de rendements sécurisés
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def detect_ruin_index(equity: pd.Series) -> Optional[int]:
    """
    Retourne l'index (positionnel) du premier point où equity <= 0.

    Args:
        equity: Série d'equity

    Returns:
        Index (int) ou None si aucune ruine
    """
    if equity is None or len(equity) == 0:
        return None

    for i, value in enumerate(equity):
        try:
            if float(value) <= 0:
                return i
        except (TypeError, ValueError):
            continue
    return None


def compute_returns_safe(
    equity: pd.Series,
    *,
    initial_capital: float = 10000.0,
    method: str = "log_returns",
) -> pd.Series:
    """
    Calcule des rendements en évitant inf/NaN même si equity <= 0.

    Methods:
        - "log_returns": log(safe_equity / safe_equity.shift(1))
        - "pnl_based": diff(equity) / initial_capital
        - "filter_until_ruin": pct_change puis NaN après ruine
    """
    if equity is None:
        return pd.Series([], dtype=np.float64)

    eq = pd.Series(equity, dtype=np.float64).copy()

    if method == "log_returns":
        eps = max(1e-12, abs(initial_capital) * 1e-12)
        safe_eq = eq.copy()
        safe_eq[safe_eq <= 0] = eps
        returns = np.log(safe_eq / safe_eq.shift(1))
        if len(returns) > 0:
            returns.iloc[0] = 0.0
        returns = returns.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        returns.name = "returns"
        return returns

    if method == "pnl_based":
        denom = initial_capital if initial_capital != 0 else 1.0
        returns = eq.diff() / float(denom)
        if len(returns) > 0:
            returns.iloc[0] = 0.0
        returns = returns.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        returns.name = "returns"
        return returns

    if method == "filter_until_ruin":
        returns = eq.pct_change()
        if len(returns) > 0:
            returns.iloc[0] = 0.0
        returns = returns.replace([np.inf, -np.inf], np.nan)
        ruin_idx = detect_ruin_index(eq)
        if ruin_idx is not None:
            # Pré-ruine: remplacer NaN par 0.0, Post-ruine: NaN
            returns.iloc[: ruin_idx + 1] = returns.iloc[: ruin_idx + 1].fillna(0.0)
            returns.iloc[ruin_idx + 1 :] = np.nan
        else:
            returns = returns.fillna(0.0)
        returns.name = "returns"
        return returns

    raise ValueError(f"Unknown method: {method}")


__all__ = ["compute_returns_safe", "detect_ruin_index"]
