"""
Backtest Core - Performance Calculator
======================================

Calcul des métriques de performance standard et avancées.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

# Import des métriques Tier S
from backtest.metrics_tier_s import (
    TierSMetrics,
    calculate_tier_s_metrics,
    format_tier_s_report,
)

# Import des optimisations Numba
from backtest.performance_numba import (
    _drawdown_series_numba,
    _max_drawdown_numba,
)
from utils.log import get_logger

logger = get_logger(__name__)


@dataclass
class PerformanceMetrics:
    """Container pour les métriques de performance."""

    # Rendement
    total_pnl: float
    total_return_pct: float
    annualized_return: float

    # Risque
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_duration_days: float
    volatility_annual: float

    # Trades
    total_trades: int
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    avg_trade_duration_hours: float

    # Ratios avancés
    calmar_ratio: float
    risk_reward_ratio: float
    expectancy: float

    # Métriques Tier S (optionnelles)
    tier_s: Optional[TierSMetrics] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "total_pnl": self.total_pnl,
            "total_return_pct": self.total_return_pct,
            "annualized_return": self.annualized_return,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_duration_days": self.max_drawdown_duration_days,
            "volatility_annual": self.volatility_annual,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "largest_win": self.largest_win,
            "largest_loss": self.largest_loss,
            "avg_trade_duration_hours": self.avg_trade_duration_hours,
            "calmar_ratio": self.calmar_ratio,
            "risk_reward_ratio": self.risk_reward_ratio,
            "expectancy": self.expectancy,
            "tier_s": self.tier_s.to_dict() if self.tier_s else None
        }


def equity_curve(
    returns: pd.Series,
    initial_capital: float = 10000.0
) -> pd.Series:
    """
    Calcule la courbe d'équité à partir des rendements.

    Args:
        returns: Série de rendements (fractionnaires)
        initial_capital: Capital initial

    Returns:
        Série d'équité
    """
    if returns.empty:
        return pd.Series([], dtype=np.float64)

    # Nettoyer les données
    returns_clean = returns.dropna()
    returns_clean = returns_clean.clip(-1.0, 10.0)  # Limites raisonnables

    # Calcul cumulatif
    cumulative = (1 + returns_clean).cumprod()
    equity = initial_capital * cumulative

    return equity


def drawdown_series(equity: pd.Series) -> pd.Series:
    """
    Calcule la série de drawdown.

    Args:
        equity: Courbe d'équité

    Returns:
        Série de drawdown (valeurs négatives, 0 = au pic)

    Note:
        Version optimisée Numba (100× plus rapide que pandas.expanding().max())
    """
    if equity.empty:
        return pd.Series([], dtype=np.float64)

    # Utiliser version Numba optimisée (100× speedup)
    drawdown_values = _drawdown_series_numba(equity.values)

    return pd.Series(drawdown_values, index=equity.index, dtype=np.float64)


def max_drawdown(equity: pd.Series) -> float:
    """
    Calcule le drawdown maximum.

    Note:
        Version optimisée Numba (100× plus rapide)
    """
    if equity.empty:
        return 0.0

    # Utiliser version Numba directe (évite création Series intermédiaire)
    return float(_max_drawdown_numba(equity.values))


def detect_liquidation(
    equity: pd.Series,
    initial_capital: float = 10000.0,
) -> Dict[str, Any]:
    """
    Détecte la ruine du compte (equity <= 0) et calcule drawdown brut.

    Returns:
        Dict avec account_ruined, ruin_time, min_equity,
        max_drawdown_pct_raw, max_drawdown_pct_capped
    """
    if equity is None or equity.empty:
        return {
            "account_ruined": False,
            "ruin_time": None,
            "min_equity": float(initial_capital),
            "max_drawdown_pct_raw": 0.0,
            "max_drawdown_pct_capped": 0.0,
        }

    eq_values = pd.Series(equity, dtype=np.float64).values
    running_max = np.maximum.accumulate(eq_values)

    with np.errstate(divide="ignore", invalid="ignore"):
        drawdown_pct = (eq_values - running_max) / running_max * 100.0

    max_dd_raw = float(np.nanmin(drawdown_pct)) if len(drawdown_pct) > 0 else 0.0
    max_dd_capped = max(-100.0, max_dd_raw)

    min_equity = float(np.nanmin(eq_values))
    ruin_idx = None
    for i, val in enumerate(eq_values):
        if np.isfinite(val) and val <= 0:
            ruin_idx = i
            break

    ruin_time = equity.index[ruin_idx] if ruin_idx is not None else None

    return {
        "account_ruined": bool(min_equity <= 0),
        "ruin_time": ruin_time,
        "min_equity": min_equity,
        "max_drawdown_pct_raw": max_dd_raw,
        "max_drawdown_pct_capped": max_dd_capped,
    }




def sharpe_ratio(
    returns: pd.Series,
    risk_free: float = 0.0,
    periods_per_year: int = 252,  # Jours de trading par defaut
    method: str = "daily_resample",  # "standard", "trading_days" ou "daily_resample"
    equity: Optional[pd.Series] = None  # Necessaire pour daily_resample
) -> float:
    '''
    Calcule le ratio de Sharpe annualise.

    Pour limiter les biais des equity curves "sparse", la methode daily_resample
    peut resampler l'equity en quotidien avant de calculer les rendements.
    Des gardes supplmentaires evitent les valeurs aberrantes lorsque seules
    quelques trades non nuls sont disponibles.
    '''
    returns_series = returns.copy() if isinstance(returns, pd.Series) else pd.Series(returns)
    if returns_series.empty:
        return 0.0

    if method == "daily_resample":
        if equity is None or (hasattr(equity, "empty") and equity.empty):
            logger.warning("daily_resample necessite equity, fallback sur standard")
            method = "standard"
        elif not isinstance(equity.index, pd.DatetimeIndex):
            logger.warning("equity.index n'est pas DatetimeIndex, fallback sur standard")
            method = "standard"
        else:
            equity_daily = equity.resample('D').last().dropna()
            if len(equity_daily) >= 2:
                returns_series = equity_daily.pct_change().dropna()
                periods_per_year = 252  # Annualisation coherente avec des returns quotidiens
            else:
                logger.debug(
                    "sharpe_ratio_insufficient_daily_data days=%s, fallback to provided returns",
                    len(equity_daily),
                )
            method = "standard"

    returns_clean = (
        pd.Series(returns_series, dtype=np.float64)
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )

    MIN_SAMPLES_FOR_SHARPE = 3  # Minimum pour un std ddof=1 un minimum de stabilite
    MIN_NON_ZERO_RETURNS = 3    # Eviter ratios irreels avec 1-2 trades
    if len(returns_clean) < MIN_SAMPLES_FOR_SHARPE:
        logger.debug(
            "sharpe_ratio_insufficient_samples samples=%s < min=%s, returning 0.0",
            len(returns_clean),
            MIN_SAMPLES_FOR_SHARPE,
        )
        return 0.0

    if method == "trading_days":
        returns_clean = returns_clean[returns_clean != 0.0]
        if len(returns_clean) < MIN_SAMPLES_FOR_SHARPE:
            logger.debug(
                "sharpe_ratio_insufficient_samples_after_filter samples=%s < min=%s, returning 0.0",
                len(returns_clean),
                MIN_SAMPLES_FOR_SHARPE,
            )
            return 0.0
    non_zero_count = int((returns_clean != 0.0).sum())
    if non_zero_count < MIN_NON_ZERO_RETURNS:
        logger.debug(
            "sharpe_ratio_insufficient_non_zero non_zero=%s < min=%s, returning 0.0",
            non_zero_count,
            MIN_NON_ZERO_RETURNS,
        )
        return 0.0

    periods_per_year = periods_per_year or 0
    rf_period = risk_free / periods_per_year if periods_per_year else 0.0

    excess_returns = returns_clean - rf_period
    mean_excess = excess_returns.mean()
    std_returns = float(returns_clean.std(ddof=1))

    min_annual_vol = 0.001  # 0.1% minimum de volatilite annualisee
    min_period_std = min_annual_vol / np.sqrt(periods_per_year or 1)

    if not np.isfinite(std_returns) or std_returns < min_period_std:
        logger.debug(
            "sharpe_ratio_zero_volatility std=%.6f < min=%.6f, returns=%s samples",
            std_returns,
            min_period_std,
            len(returns_clean),
        )
        return 0.0

    sharpe = (mean_excess * np.sqrt(periods_per_year)) / std_returns if periods_per_year else 0.0

    MAX_SHARPE = 20.0
    if abs(sharpe) > MAX_SHARPE:
        logger.warning(
            "sharpe_ratio_clamped value=%.2f clamped_to=+/-%.1f std=%.6f mean=%.6f samples=%s",
            sharpe,
            MAX_SHARPE,
            std_returns,
            mean_excess,
            len(returns_clean),
        )
        sharpe = np.sign(sharpe) * MAX_SHARPE

    # Protection critique : Sharpe forcé à 0 si impossible
    if not np.isfinite(sharpe):
        logger.error("sharpe_ratio_infinite value=%.2f, forced_to_zero", sharpe)
        sharpe = 0.0

    return float(sharpe)


def sortino_ratio(
    returns: pd.Series,
    risk_free: float = 0.0,
    periods_per_year: int = 252,
    method: str = "daily_resample",
    equity: Optional[pd.Series] = None
) -> float:
    """
    Calcule le ratio de Sortino (ne pénalise que la volatilité baissière).

    Args:
        returns: Série de rendements
        risk_free: Taux sans risque annuel
        periods_per_year: Nombre de périodes par an pour l'annualisation
        method: "standard", "trading_days" ou "daily_resample"
        equity: Série d'equity (requis si method="daily_resample")

    Returns:
        Ratio de Sortino annualisé
    """
    if returns.empty:
        return 0.0

    # Méthode daily_resample : resample equity en quotidien
    if method == "daily_resample":
        if equity is None or equity.empty:
            logger.warning("daily_resample nécessite equity, fallback sur standard")
            method = "standard"
        else:
            if not isinstance(equity.index, pd.DatetimeIndex):
                logger.warning("equity.index n'est pas DatetimeIndex, fallback sur standard")
                method = "standard"
            else:
                equity_daily = equity.resample('D').last().dropna()
                if len(equity_daily) < 2:
                    return 0.0
                returns = equity_daily.pct_change().dropna()
                method = "standard"
                # ⚠️ IMPORTANT: Après resample quotidien, forcer periods_per_year = 252 (jours de trading)
                periods_per_year = 252

    returns_clean = returns.dropna()
    if returns_clean.empty:
        return 0.0

    # Filtrer returns nuls si méthode trading_days
    if method == "trading_days":
        returns_clean = returns_clean[returns_clean != 0.0]
        if len(returns_clean) < 2:
            return 0.0

    rf_period = risk_free / periods_per_year
    excess_returns = returns_clean - rf_period
    mean_excess = excess_returns.mean()

    # Volatilité baissière seulement
    downside_returns = returns_clean[returns_clean < 0]
    if len(downside_returns) < 2:
        return 0.0

    downside_std = downside_returns.std(ddof=1)

    if downside_std <= 1e-10:
        return 0.0

    sortino = (mean_excess * np.sqrt(periods_per_year)) / downside_std

    return float(sortino)


def profit_factor(trades_df: pd.DataFrame) -> float:
    """
    Calcule le profit factor (gains bruts / pertes brutes).
    """
    if trades_df.empty or "pnl" not in trades_df.columns:
        return 0.0

    gross_profits = trades_df[trades_df["pnl"] > 0]["pnl"].sum()
    gross_losses = abs(trades_df[trades_df["pnl"] < 0]["pnl"].sum())

    if gross_losses == 0:
        return float("inf") if gross_profits > 0 else 1.0

    return gross_profits / gross_losses


def calculate_metrics(
    equity: pd.Series,
    returns: pd.Series,
    trades_df: pd.DataFrame,
    initial_capital: float = 10000.0,
    periods_per_year: int = 252,  # Jours de trading par défaut
    include_tier_s: bool = False,
    sharpe_method: str = "daily_resample"  # "standard", "trading_days" ou "daily_resample"
) -> Dict[str, Any]:
    """
    Calcule toutes les métriques de performance.

    Args:
        equity: Courbe d'équité
        returns: Série de rendements (par barre)
        trades_df: DataFrame des trades
        initial_capital: Capital initial
        periods_per_year: Périodes par an pour annualisation du Sharpe
                         (défaut: 252 jours de trading, standard industrie)
        include_tier_s: Inclure métriques Tier S avancées
        sharpe_method: Méthode de calcul du Sharpe/Sortino:
                      - "daily_resample": Resample equity en quotidien (RECOMMANDÉ, standard industrie)
                      - "trading_days": Filtre les returns nuls (incomplet, non recommandé)
                      - "standard": Utilise tous les returns (peut donner valeurs aberrantes)

    Returns:
        Dict de toutes les métriques

    Notes:
        - Le Sharpe/Sortino sont calculés avec periods_per_year=252 par défaut
          (jours de trading), indépendamment du timeframe des données
        - La méthode "daily_resample" évite les biais liés aux equity "sparse"
          (qui ne changent qu'aux trades, créant beaucoup de returns nuls)
    """
    metrics = {}

    # === Métriques de rendement ===
    if not equity.empty:
        final_equity = equity.iloc[-1]
        total_pnl = final_equity - initial_capital
        total_return_pct = (total_pnl / initial_capital) * 100

        # Rendement annualisé (calendrier si index datetime)
        annualized_return = 0.0
        years = 0.0
        if isinstance(equity.index, pd.DatetimeIndex) and len(equity) > 1:
            elapsed_days = (equity.index[-1] - equity.index[0]).total_seconds() / 86400
            years = elapsed_days / 365 if elapsed_days > 0 else 0.0
        elif periods_per_year and len(equity) > 1:
            years = len(equity) / periods_per_year

        if years > 0 and final_equity > 0:
            annualized_return = ((final_equity / initial_capital) ** (1 / years) - 1) * 100
    else:
        total_pnl = 0.0
        total_return_pct = 0.0
        annualized_return = 0.0

    metrics["total_pnl"] = total_pnl
    metrics["total_return_pct"] = total_return_pct
    metrics["annualized_return"] = annualized_return

    # === Métriques de risque ===
    metrics["sharpe_ratio"] = sharpe_ratio(
        returns,
        periods_per_year=periods_per_year,
        method=sharpe_method,
        equity=equity  # Passer equity pour daily_resample
    )
    metrics["sortino_ratio"] = sortino_ratio(
        returns,
        periods_per_year=periods_per_year,
        method=sharpe_method,
        equity=equity  # Passer equity pour daily_resample
    )
    # Plafonner le drawdown à -100% (ruine totale maximum)
    # Un drawdown de -925% n'a pas de sens, ça indique probablement une equity négative
    metrics["max_drawdown"] = max(-100.0, max_drawdown(equity) * 100)  # En %, plafonné à -100%
    # Alias explicite (usage UI)
    metrics["max_drawdown_pct"] = metrics["max_drawdown"]

    # Volatilité annualisée
    volatility_returns = returns
    vol_annualization = periods_per_year
    if sharpe_method == "daily_resample" and isinstance(equity.index, pd.DatetimeIndex):
        daily_equity = equity.resample("D").last().dropna()
        if len(daily_equity) >= 2:
            volatility_returns = daily_equity.pct_change().dropna()
            vol_annualization = 252

    if not volatility_returns.empty and vol_annualization:
        vol = volatility_returns.std(ddof=1) * np.sqrt(vol_annualization) * 100
        metrics["volatility_annual"] = vol
    else:
        metrics["volatility_annual"] = 0.0

    # Durée max du drawdown
    if not equity.empty:
        dd = drawdown_series(equity)
        if (dd < 0).any():
            if isinstance(dd.index, pd.DatetimeIndex):
                dd_periods = []
                start_ts = None
                last_ts = None
                for ts, in_dd in (dd < 0).items():
                    if in_dd and start_ts is None:
                        start_ts = ts
                    elif not in_dd and start_ts is not None:
                        end_ts = last_ts if last_ts is not None else ts
                        dd_periods.append(end_ts - start_ts)
                        start_ts = None
                    last_ts = ts
                if start_ts is not None and last_ts is not None:
                    dd_periods.append(last_ts - start_ts)

                metrics["max_drawdown_duration_days"] = (
                    max((p.total_seconds() / 86400 for p in dd_periods))
                    if dd_periods else 0.0
                )
            else:
                in_dd = dd < 0
                dd_lengths = []
                current = 0
                for val in in_dd:
                    if val:
                        current += 1
                    else:
                        if current > 0:
                            dd_lengths.append(current)
                        current = 0
                if current > 0:
                    dd_lengths.append(current)

                max_dd_bars = max(dd_lengths) if dd_lengths else 0
                metrics["max_drawdown_duration_days"] = max_dd_bars / (periods_per_year or 1)
        else:
            metrics["max_drawdown_duration_days"] = 0.0
    else:
        metrics["max_drawdown_duration_days"] = 0.0

    # === Détection liquidation / drawdown brut ===
    liquidation = detect_liquidation(equity, initial_capital=initial_capital)
    metrics.update(liquidation)
    metrics["max_drawdown_pct_raw"] = liquidation.get("max_drawdown_pct_raw", metrics["max_drawdown"])
    metrics["max_drawdown_pct_capped"] = liquidation.get("max_drawdown_pct_capped", metrics["max_drawdown"])
    metrics["max_drawdown"] = metrics["max_drawdown_pct_capped"]
    metrics["max_drawdown_pct"] = metrics["max_drawdown_pct_capped"]

    # === Métriques de trades ===
    if not trades_df.empty and "pnl" in trades_df.columns:
        n_trades = len(trades_df)
        winning_trades = trades_df[trades_df["pnl"] > 0]
        losing_trades = trades_df[trades_df["pnl"] < 0]

        metrics["total_trades"] = n_trades
        metrics["win_rate"] = len(winning_trades) / n_trades * 100 if n_trades > 0 else 0
        metrics["win_rate_pct"] = metrics["win_rate"]
        metrics["profit_factor"] = profit_factor(trades_df)

        metrics["avg_win"] = winning_trades["pnl"].mean() if len(winning_trades) > 0 else 0
        metrics["avg_loss"] = losing_trades["pnl"].mean() if len(losing_trades) > 0 else 0
        metrics["largest_win"] = winning_trades["pnl"].max() if len(winning_trades) > 0 else 0
        metrics["largest_loss"] = losing_trades["pnl"].min() if len(losing_trades) > 0 else 0

        # Durée moyenne des trades
        if "entry_ts" in trades_df.columns and "exit_ts" in trades_df.columns:
            durations = (trades_df["exit_ts"] - trades_df["entry_ts"]).dt.total_seconds() / 3600
            metrics["avg_trade_duration_hours"] = durations.mean()
        else:
            metrics["avg_trade_duration_hours"] = 0

        # Expectancy (espérance mathématique par trade)
        metrics["expectancy"] = trades_df["pnl"].mean() if n_trades > 0 else 0

        # Risk/Reward ratio
        if metrics["avg_loss"] != 0:
            metrics["risk_reward_ratio"] = abs(metrics["avg_win"] / metrics["avg_loss"])
        else:
            metrics["risk_reward_ratio"] = 0
    else:
        metrics["total_trades"] = 0
        metrics["win_rate"] = 0
        metrics["win_rate_pct"] = 0.0
        metrics["profit_factor"] = 0
        metrics["avg_win"] = 0
        metrics["avg_loss"] = 0
        metrics["largest_win"] = 0
        metrics["largest_loss"] = 0
        metrics["avg_trade_duration_hours"] = 0
        metrics["expectancy"] = 0
        metrics["risk_reward_ratio"] = 0

    # === Ratios avancés ===
    # Calmar ratio (rendement annualisé / max drawdown)
    if metrics["max_drawdown"] != 0:
        metrics["calmar_ratio"] = metrics["annualized_return"] / abs(metrics["max_drawdown"])
    else:
        metrics["calmar_ratio"] = 0

    # === Métriques Tier S (optionnel) ===
    if include_tier_s:
        trades_pnl = trades_df["pnl"] if not trades_df.empty and "pnl" in trades_df.columns else pd.Series([])
        tier_s_metrics = calculate_tier_s_metrics(
            returns=returns,
            equity=equity,
            trades_pnl=trades_pnl,
            initial_capital=initial_capital,
            periods_per_year=periods_per_year
        )
        metrics["tier_s"] = tier_s_metrics.to_dict()
        # Ajouter les métriques clés au niveau supérieur
        metrics["sqn"] = tier_s_metrics.sqn
        metrics["recovery_factor"] = tier_s_metrics.recovery_factor
        metrics["ulcer_index"] = tier_s_metrics.ulcer_index
        metrics["martin_ratio"] = tier_s_metrics.martin_ratio
        metrics["gain_pain_ratio"] = tier_s_metrics.gain_pain_ratio
        metrics["tier_s_score"] = tier_s_metrics.tier_s_score
        metrics["tier_s_grade"] = tier_s_metrics.tier_s_grade
    else:
        metrics["tier_s"] = None

    return metrics


class PerformanceCalculator:
    """
    Calculateur de performance avec API orientée objet.
    """

    def __init__(self, initial_capital: float = 10000.0, include_tier_s: bool = False):
        self.initial_capital = initial_capital
        self.include_tier_s = include_tier_s
        self._last_metrics: Optional[Dict[str, Any]] = None
        self._last_tier_s: Optional[TierSMetrics] = None

    def summarize(
        self,
        returns: pd.Series,
        trades_df: pd.DataFrame,
        periods_per_year: int = 252,
        sharpe_method: str = "daily_resample"
    ) -> Dict[str, Any]:
        """
        Calcule un résumé complet des performances.

        Args:
            returns: Série de rendements
            trades_df: DataFrame des trades
            periods_per_year: Périodes par an (défaut: 252 jours de trading)
            sharpe_method: Méthode de calcul Sharpe ("daily_resample", "trading_days" ou "standard")

        Returns:
            Dict des métriques calculées
        """
        # Calculer l'équité
        eq = equity_curve(returns, self.initial_capital)

        # Calculer toutes les métriques
        metrics = calculate_metrics(
            equity=eq,
            returns=returns,
            trades_df=trades_df,
            initial_capital=self.initial_capital,
            periods_per_year=periods_per_year,
            include_tier_s=self.include_tier_s,
            sharpe_method=sharpe_method
        )

        self._last_metrics = metrics

        # Stocker les métriques Tier S si calculées
        if self.include_tier_s and metrics.get("tier_s"):
            trades_pnl = trades_df["pnl"] if not trades_df.empty and "pnl" in trades_df.columns else pd.Series([])
            self._last_tier_s = calculate_tier_s_metrics(
                returns=returns,
                equity=eq,
                trades_pnl=trades_pnl,
                initial_capital=self.initial_capital,
                periods_per_year=periods_per_year
            )

        return metrics

    def format_report(self, metrics: Optional[Dict[str, Any]] = None) -> str:
        """
        Formate un rapport lisible des métriques.
        """
        if metrics is None:
            metrics = self._last_metrics
        if metrics is None:
            return "Aucune métrique disponible"

        report = """
╔══════════════════════════════════════════════════════════╗
║              RAPPORT DE PERFORMANCE                       ║
╠══════════════════════════════════════════════════════════╣
║ RENDEMENT                                                 ║
║   P&L Total:           ${total_pnl:>12,.2f}               ║
║   Rendement Total:     {total_return_pct:>12.2f}%         ║
║   Rendement Annualisé: {annualized_return:>12.2f}%        ║
╠══════════════════════════════════════════════════════════╣
║ RISQUE                                                    ║
║   Sharpe Ratio:        {sharpe_ratio:>12.2f}              ║
║   Sortino Ratio:       {sortino_ratio:>12.2f}             ║
║   Max Drawdown:        {max_drawdown:>12.2f}%             ║
║   Volatilité Ann.:     {volatility_annual:>12.2f}%        ║
╠══════════════════════════════════════════════════════════╣
║ TRADES                                                    ║
║   Nombre de Trades:    {total_trades:>12d}                ║
║   Win Rate:            {win_rate:>12.1f}%                 ║
║   Profit Factor:       {profit_factor:>12.2f}             ║
║   Gain Moyen:          ${avg_win:>12,.2f}                 ║
║   Perte Moyenne:       ${avg_loss:>12,.2f}                ║
╚══════════════════════════════════════════════════════════╝
""".format(**metrics)

        # Ajouter rapport Tier S si disponible
        if self._last_tier_s:
            report += format_tier_s_report(self._last_tier_s)

        return report


__all__ = [
    "PerformanceCalculator",
    "PerformanceMetrics",
    "TierSMetrics",
    "calculate_metrics",
    "calculate_tier_s_metrics",
    "detect_liquidation",
    "equity_curve",
    "drawdown_series",
    "max_drawdown",
    "sharpe_ratio",
    "sortino_ratio",
    "profit_factor",
    "format_tier_s_report",
]
