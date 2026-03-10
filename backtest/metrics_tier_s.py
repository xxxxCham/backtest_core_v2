"""
Module-ID: backtest.metrics_tier_s

Purpose: Calcul des métriques avancées (Sortino, Calmar, SQN, Recovery Factor, Ulcer Index, etc.) pour analyse institutionnelle.

Role in pipeline: metrics

Key components: TierSMetrics, calculate_tier_s_metrics, format_tier_s_report, grade_tier_s

Inputs: Returns array, trades list, max_drawdown, PnL

Outputs: TierSMetrics (dataclass), tier_s_score (0-100), tier_s_grade (A/B/C/D/F)

Dependencies: numpy, pandas, optionnel: tabulate (formatage)

Conventions: Toutes les métriques normalisées (fractions 0-1 pour retours); scores 0-100; grades A=excellent, F=faible.

Read-if: Analyse métriques avancées, scores institutionnels, ou grading stratégies.

Skip-if: Vous n'utilisez que les métriques standards (Sharpe, Sortino basique).
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

# Import optionnel de tabulate pour tableaux formatés
try:
    from tabulate import tabulate
    TABULATE_AVAILABLE = True
except ImportError:
    TABULATE_AVAILABLE = False

# Import des optimisations Numba
from backtest.performance_numba import (
    _expanding_max_numba,
    _recovery_factor_numba,
    _sortino_downside_deviation_numba,
    _ulcer_index_numba,
)


@dataclass
class TierSMetrics:
    """Container pour les métriques Tier S."""

    # Ratios de risque ajusté
    sortino_ratio: float
    calmar_ratio: float
    sqn: float
    martin_ratio: float

    # Facteurs de récupération
    recovery_factor: float
    gain_pain_ratio: float

    # Indices de stress
    ulcer_index: float

    # Métriques R-Multiple
    avg_r_multiple: float
    expectancy_r: float

    # Sharpe ajusté
    outlier_adjusted_sharpe: float

    # Qualité
    tier_s_score: float  # Score composite 0-100
    tier_s_grade: str    # A, B, C, D, F

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "sortino_ratio": self.sortino_ratio,
            "calmar_ratio": self.calmar_ratio,
            "sqn": self.sqn,
            "martin_ratio": self.martin_ratio,
            "recovery_factor": self.recovery_factor,
            "gain_pain_ratio": self.gain_pain_ratio,
            "ulcer_index": self.ulcer_index,
            "avg_r_multiple": self.avg_r_multiple,
            "expectancy_r": self.expectancy_r,
            "outlier_adjusted_sharpe": self.outlier_adjusted_sharpe,
            "tier_s_score": self.tier_s_score,
            "tier_s_grade": self.tier_s_grade,
        }


def sortino_ratio(
    returns: pd.Series,
    risk_free: float = 0.0,
    periods_per_year: int = 365 * 24,
    target_return: float = 0.0
) -> float:
    """
    Ratio de Sortino amélioré.

    Ne pénalise que la volatilité baissière (downside deviation).

    Formula: (R - Rf) / σ_downside

    Args:
        returns: Série de rendements
        risk_free: Taux sans risque annuel
        periods_per_year: Périodes par an
        target_return: Rendement cible (défaut: 0)

    Returns:
        Ratio de Sortino annualisé
    """
    if returns.empty or len(returns) < 2:
        return 0.0

    returns_clean = returns.dropna()
    if returns_clean.empty:
        return 0.0

    # Rendement excédentaire moyen
    rf_period = risk_free / periods_per_year
    target_period = target_return / periods_per_year
    excess_returns = returns_clean - rf_period
    mean_excess = excess_returns.mean()

    # Downside deviation - version Numba optimisée (10× speedup)
    downside_deviation = _sortino_downside_deviation_numba(
        returns_clean.values,
        target_period
    )

    if downside_deviation <= 1e-10:
        # Pas de volatilité baissière significative
        return float('inf') if mean_excess > 0 else 0.0

    # Annualisation
    sortino = (mean_excess * np.sqrt(periods_per_year)) / downside_deviation

    return float(np.clip(sortino, -100, 100))


def calmar_ratio(
    returns: pd.Series,
    equity: pd.Series,
    periods_per_year: int = 365 * 24
) -> float:
    """
    Ratio de Calmar: CAGR / Max Drawdown absolu.

    Mesure le rendement par unité de drawdown maximum.
    Bon indicateur de la relation risque/rendement sur le long terme.

    Args:
        returns: Série de rendements
        equity: Courbe d'équité
        periods_per_year: Périodes par an

    Returns:
        Ratio de Calmar

    Note:
        Version optimisée Numba pour calcul running_max (100× speedup)
    """
    if returns.empty or equity.empty:
        return 0.0

    # CAGR (Compound Annual Growth Rate)
    initial_value = equity.iloc[0]
    final_value = equity.iloc[-1]

    if initial_value <= 0 or final_value <= 0:
        return 0.0

    n_periods = len(equity)
    years = n_periods / periods_per_year

    if years <= 0:
        return 0.0

    cagr = (final_value / initial_value) ** (1 / years) - 1

    # Max Drawdown - version Numba optimisée
    running_max = _expanding_max_numba(equity.values)
    drawdown = (equity.values / running_max) - 1.0
    max_dd = abs(np.min(drawdown))

    if max_dd <= 1e-10:
        return float('inf') if cagr > 0 else 0.0

    calmar = cagr / max_dd

    return float(np.clip(calmar, -100, 100))


def sqn(trades_pnl: pd.Series, min_trades: int = 30) -> float:
    """
    System Quality Number (SQN) de Van Tharp.

    Mesure la qualité d'un système de trading.
    Formula: √N × (Mean R / StdDev R)

    Interprétation:
    - SQN < 1.6: Pauvre
    - 1.6 ≤ SQN < 2.0: En dessous de la moyenne
    - 2.0 ≤ SQN < 2.5: Moyenne
    - 2.5 ≤ SQN < 3.0: Bon
    - 3.0 ≤ SQN < 5.0: Excellent
    - 5.0 ≤ SQN < 7.0: Superbe
    - SQN ≥ 7.0: Saint Graal

    Args:
        trades_pnl: Série des P&L par trade
        min_trades: Minimum de trades pour calcul valide

    Returns:
        SQN (plafonné à 10 pour éviter les outliers)
    """
    if trades_pnl.empty or len(trades_pnl) < min_trades:
        return 0.0

    n = len(trades_pnl)
    mean_r = trades_pnl.mean()
    std_r = trades_pnl.std(ddof=1)

    if std_r <= 1e-10:
        return 0.0

    # SQN = √N × (Mean / Std)
    sqn_value = np.sqrt(n) * (mean_r / std_r)

    # Plafonnement selon Van Tharp
    return float(np.clip(sqn_value, -10, 10))


def recovery_factor(
    equity: pd.Series,
    initial_capital: float
) -> float:
    """
    Recovery Factor: Net Profit / Max Drawdown absolu.

    Mesure combien de fois le système a récupéré son pire drawdown.

    Args:
        equity: Courbe d'équité
        initial_capital: Capital initial

    Returns:
        Recovery Factor

    Note:
        Version optimisée Numba (100× plus rapide)
    """
    if equity.empty:
        return 0.0

    # Utiliser version Numba optimisée (100× speedup)
    return float(_recovery_factor_numba(equity.values, initial_capital))


def ulcer_index(equity: pd.Series) -> float:
    """
    Ulcer Index: Mesure du stress lié aux drawdowns.

    Plus sensible aux drawdowns prolongés que le max drawdown simple.
    Formula: √(Σ D² / N) où D = drawdown en %

    Args:
        equity: Courbe d'équité

    Returns:
        Ulcer Index (plus bas = mieux)

    Note:
        Version optimisée Numba (100× plus rapide)
    """
    if equity.empty or len(equity) < 2:
        return 0.0

    # Utiliser version Numba optimisée (100× speedup)
    return float(_ulcer_index_numba(equity.values))


def martin_ratio(
    returns: pd.Series,
    equity: pd.Series,
    risk_free: float = 0.0,
    periods_per_year: int = 365 * 24
) -> float:
    """
    Martin Ratio (UPI - Ulcer Performance Index).

    Ratio rendement/ulcer index. Alternative au Sharpe utilisant
    l'Ulcer Index comme mesure de risque.

    Formula: (Return - Rf) / Ulcer Index

    Args:
        returns: Série de rendements
        equity: Courbe d'équité
        risk_free: Taux sans risque annuel
        periods_per_year: Périodes par an

    Returns:
        Martin Ratio (plus haut = mieux)
    """
    if returns.empty or equity.empty:
        return 0.0

    # Rendement annualisé
    total_return = (equity.iloc[-1] / equity.iloc[0]) - 1
    n_periods = len(equity)
    years = n_periods / periods_per_year

    if years <= 0:
        return 0.0

    annualized_return = ((1 + total_return) ** (1 / years) - 1) * 100
    excess_return = annualized_return - risk_free * 100

    # Ulcer Index
    ui = ulcer_index(equity)

    if ui <= 1e-10:
        return float('inf') if excess_return > 0 else 0.0

    return float(np.clip(excess_return / ui, -100, 100))


def gain_pain_ratio(trades_pnl: pd.Series) -> float:
    """
    Gain/Pain Ratio: Somme des gains / Somme des pertes.

    Simple mais efficace pour évaluer l'asymétrie gains/pertes.

    Args:
        trades_pnl: Série des P&L par trade

    Returns:
        Gain/Pain ratio (> 1 = profitable)
    """
    if trades_pnl.empty:
        return 0.0

    gains = trades_pnl[trades_pnl > 0].sum()
    losses = abs(trades_pnl[trades_pnl < 0].sum())

    if losses <= 1e-10:
        return float('inf') if gains > 0 else 1.0

    return float(gains / losses)


def r_multiple_stats(
    trades_pnl: pd.Series,
    initial_risk_per_trade: float
) -> Tuple[float, float]:
    """
    Statistiques R-Multiple.

    R = Profit / Risque Initial
    Permet de normaliser les trades par rapport au risque.

    Args:
        trades_pnl: Série des P&L par trade
        initial_risk_per_trade: Risque initial par trade (ex: stop loss)

    Returns:
        Tuple (avg_r_multiple, expectancy_r)
    """
    if trades_pnl.empty or initial_risk_per_trade <= 0:
        return 0.0, 0.0

    # Convertir en R-multiples
    r_multiples = trades_pnl / initial_risk_per_trade

    avg_r = float(r_multiples.mean())

    # Expectancy en R
    wins = r_multiples[r_multiples > 0]
    losses = r_multiples[r_multiples < 0]

    win_rate = len(wins) / len(r_multiples) if len(r_multiples) > 0 else 0
    avg_win_r = wins.mean() if len(wins) > 0 else 0
    avg_loss_r = abs(losses.mean()) if len(losses) > 0 else 0

    expectancy_r = (win_rate * avg_win_r) - ((1 - win_rate) * avg_loss_r)

    return avg_r, float(expectancy_r)


def outlier_adjusted_sharpe(
    returns: pd.Series,
    risk_free: float = 0.0,
    periods_per_year: int = 365 * 24,
    percentile_cutoff: float = 2.5
) -> float:
    """
    Sharpe Ratio ajusté pour les outliers.

    Exclut les rendements extrêmes qui peuvent fausser le ratio.

    Args:
        returns: Série de rendements
        risk_free: Taux sans risque annuel
        periods_per_year: Périodes par an
        percentile_cutoff: Percentile à exclure des deux côtés

    Returns:
        Sharpe ratio ajusté
    """
    if returns.empty or len(returns) < 10:
        return 0.0

    returns_clean = returns.dropna()

    # Exclure les outliers
    lower = np.percentile(returns_clean, percentile_cutoff)
    upper = np.percentile(returns_clean, 100 - percentile_cutoff)

    trimmed_returns = returns_clean[(returns_clean >= lower) & (returns_clean <= upper)]

    if len(trimmed_returns) < 2:
        return 0.0

    # Calcul du Sharpe
    rf_period = risk_free / periods_per_year
    excess_returns = trimmed_returns - rf_period
    mean_excess = excess_returns.mean()
    std_returns = trimmed_returns.std(ddof=1)

    if std_returns <= 1e-10:
        return 0.0

    sharpe = (mean_excess * np.sqrt(periods_per_year)) / std_returns

    return float(np.clip(sharpe, -100, 100))


def calculate_tier_s_score(metrics: Dict[str, float]) -> Tuple[float, str]:
    """
    Calcule un score composite Tier S (0-100) et une note (A-F).

    Pondération:
    - Sortino: 20%
    - Calmar: 15%
    - SQN: 25%
    - Recovery Factor: 15%
    - Gain/Pain: 10%
    - Martin Ratio: 15%

    Args:
        metrics: Dict des métriques Tier S

    Returns:
        Tuple (score 0-100, grade A-F)
    """
    # Normalisation des métriques (0-100 chacune)
    def normalize(value: float, bad: float, good: float) -> float:
        if good == bad:
            return 50.0
        normalized = (value - bad) / (good - bad) * 100
        return float(np.clip(normalized, 0, 100))

    # Seuils (bad, good) pour chaque métrique
    thresholds = {
        "sortino_ratio": (0, 3),
        "calmar_ratio": (0, 2),
        "sqn": (0, 5),
        "recovery_factor": (0, 5),
        "gain_pain_ratio": (0.5, 3),
        "martin_ratio": (0, 5),
    }

    weights = {
        "sortino_ratio": 0.20,
        "calmar_ratio": 0.15,
        "sqn": 0.25,
        "recovery_factor": 0.15,
        "gain_pain_ratio": 0.10,
        "martin_ratio": 0.15,
    }

    score = 0.0
    for metric, (bad, good) in thresholds.items():
        value = metrics.get(metric, 0)
        if np.isinf(value):
            value = good * 2  # Traiter inf comme excellent
        normalized = normalize(value, bad, good)
        score += normalized * weights[metric]

    # Grade
    if score >= 90:
        grade = "A"
    elif score >= 75:
        grade = "B"
    elif score >= 60:
        grade = "C"
    elif score >= 40:
        grade = "D"
    else:
        grade = "F"

    return score, grade


def calculate_tier_s_metrics(
    returns: pd.Series,
    equity: pd.Series,
    trades_pnl: pd.Series,
    initial_capital: float = 10000.0,
    initial_risk_per_trade: Optional[float] = None,
    periods_per_year: int = 365 * 24,
    risk_free: float = 0.0
) -> TierSMetrics:
    """
    Calcule toutes les métriques Tier S.

    Args:
        returns: Série de rendements
        equity: Courbe d'équité
        trades_pnl: P&L par trade
        initial_capital: Capital initial
        initial_risk_per_trade: Risque initial par trade (pour R-multiple)
        periods_per_year: Périodes par an
        risk_free: Taux sans risque annuel

    Returns:
        TierSMetrics avec toutes les métriques
    """
    # Calcul individuel de chaque métrique
    sortino = sortino_ratio(returns, risk_free, periods_per_year)
    calmar = calmar_ratio(returns, equity, periods_per_year)
    sqn_val = sqn(trades_pnl)
    recovery = recovery_factor(equity, initial_capital)
    ulcer = ulcer_index(equity)
    martin = martin_ratio(returns, equity, risk_free, periods_per_year)
    gain_pain = gain_pain_ratio(trades_pnl)

    # R-Multiple stats
    if initial_risk_per_trade is None:
        # Estimer le risque comme 2% du capital
        initial_risk_per_trade = initial_capital * 0.02
    avg_r, exp_r = r_multiple_stats(trades_pnl, initial_risk_per_trade)

    # Sharpe ajusté
    adj_sharpe = outlier_adjusted_sharpe(returns, risk_free, periods_per_year)

    # Score composite
    metrics_dict = {
        "sortino_ratio": sortino,
        "calmar_ratio": calmar,
        "sqn": sqn_val,
        "recovery_factor": recovery,
        "gain_pain_ratio": gain_pain,
        "martin_ratio": martin,
    }
    tier_score, tier_grade = calculate_tier_s_score(metrics_dict)

    return TierSMetrics(
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        sqn=sqn_val,
        martin_ratio=martin,
        recovery_factor=recovery,
        gain_pain_ratio=gain_pain,
        ulcer_index=ulcer,
        avg_r_multiple=avg_r,
        expectancy_r=exp_r,
        outlier_adjusted_sharpe=adj_sharpe,
        tier_s_score=tier_score,
        tier_s_grade=tier_grade,
    )


def format_tier_s_report(metrics: TierSMetrics, use_table: bool = True) -> str:
    """
    Formate un rapport des métriques Tier S.

    Args:
        metrics: Métriques Tier S à formater
        use_table: Utiliser tabulate pour un format tableau (défaut: True)

    Returns:
        Rapport formaté en texte
    """
    grade_colors = {"A": "🟢", "B": "🔵", "C": "🟡", "D": "🟠", "F": "🔴"}
    grade_emoji = grade_colors.get(metrics.tier_s_grade, "⚪")

    if TABULATE_AVAILABLE and use_table:
        # Version avec tabulate (format tableau élégant)
        header = f"\n{'='*70}\n  MÉTRIQUES TIER S (INSTITUTIONNEL)\n{'='*70}"
        grade_line = f"\n  GRADE: {grade_emoji} {metrics.tier_s_grade}  |  SCORE: {metrics.tier_s_score:.1f}/100\n"

        # Tableau des ratios de risque
        risk_ratios = [
            ["Sortino Ratio", f"{metrics.sortino_ratio:.3f}"],
            ["Calmar Ratio", f"{metrics.calmar_ratio:.3f}"],
            ["SQN (Van Tharp)", f"{metrics.sqn:.3f}"],
            ["Martin Ratio (UPI)", f"{metrics.martin_ratio:.3f}"],
        ]

        # Tableau récupération & stress
        recovery = [
            ["Recovery Factor", f"{metrics.recovery_factor:.3f}"],
            ["Gain/Pain Ratio", f"{metrics.gain_pain_ratio:.3f}"],
            ["Ulcer Index", f"{metrics.ulcer_index:.3f}%"],
        ]

        # Tableau R-Multiple
        r_multiple = [
            ["Avg R-Multiple", f"{metrics.avg_r_multiple:.3f}R"],
            ["Expectancy (R)", f"{metrics.expectancy_r:.3f}R"],
        ]

        # Tableau ajustements
        adjustments = [
            ["Outlier-Adj Sharpe", f"{metrics.outlier_adjusted_sharpe:.3f}"],
        ]

        report = header + grade_line
        report += f"\n{'─'*70}\n  RATIOS DE RISQUE AJUSTÉ\n{'─'*70}\n"
        report += tabulate(risk_ratios, tablefmt="simple", colalign=("left", "right"))
        report += f"\n\n{'─'*70}\n  RÉCUPÉRATION & STRESS\n{'─'*70}\n"
        report += tabulate(recovery, tablefmt="simple", colalign=("left", "right"))
        report += f"\n\n{'─'*70}\n  R-MULTIPLE\n{'─'*70}\n"
        report += tabulate(r_multiple, tablefmt="simple", colalign=("left", "right"))
        report += f"\n\n{'─'*70}\n  AJUSTEMENTS\n{'─'*70}\n"
        report += tabulate(adjustments, tablefmt="simple", colalign=("left", "right"))
        report += f"\n{'='*70}\n"

        return report
    else:
        # Fallback: version ASCII originale
        report = f"""
╔══════════════════════════════════════════════════════════╗
║          MÉTRIQUES TIER S (INSTITUTIONNEL)               ║
╠══════════════════════════════════════════════════════════╣
║ GRADE: {grade_emoji} {metrics.tier_s_grade}  |  SCORE: {metrics.tier_s_score:>5.1f}/100                    ║
╠══════════════════════════════════════════════════════════╣
║ RATIOS DE RISQUE AJUSTÉ                                  ║
║   Sortino Ratio:       {metrics.sortino_ratio:>10.3f}                     ║
║   Calmar Ratio:        {metrics.calmar_ratio:>10.3f}                     ║
║   SQN (Van Tharp):     {metrics.sqn:>10.3f}                     ║
║   Martin Ratio (UPI):  {metrics.martin_ratio:>10.3f}                     ║
╠══════════════════════════════════════════════════════════╣
║ RÉCUPÉRATION & STRESS                                    ║
║   Recovery Factor:     {metrics.recovery_factor:>10.3f}                     ║
║   Gain/Pain Ratio:     {metrics.gain_pain_ratio:>10.3f}                     ║
║   Ulcer Index:         {metrics.ulcer_index:>10.3f}%                    ║
╠══════════════════════════════════════════════════════════╣
║ R-MULTIPLE                                               ║
║   Avg R-Multiple:      {metrics.avg_r_multiple:>10.3f}R                    ║
║   Expectancy (R):      {metrics.expectancy_r:>10.3f}R                    ║
╠══════════════════════════════════════════════════════════╣
║ AJUSTEMENTS                                              ║
║   Outlier-Adj Sharpe:  {metrics.outlier_adjusted_sharpe:>10.3f}                     ║
╚══════════════════════════════════════════════════════════╝
"""
        return report


__all__ = [
    "TierSMetrics",
    "calculate_tier_s_metrics",
    "format_tier_s_report",
    "sortino_ratio",
    "calmar_ratio",
    "sqn",
    "recovery_factor",
    "ulcer_index",
    "martin_ratio",
    "gain_pain_ratio",
    "r_multiple_stats",
    "outlier_adjusted_sharpe",
]
