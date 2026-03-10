"""
Module-ID: agents.backtest_executor

Purpose: Fournir une interface stable pour exécuter des backtests depuis les agents (batch, historique, contexte).

Role in pipeline: execution

Key components: BacktestExecutor, BacktestRequest, BacktestResult, ExperimentHistory, suggest_next_experiments

Inputs: backtest_fn callable, DataFrame OHLCV, strategy_name, parameters, options walk-forward (validation_fn)

Outputs: BacktestResult(s), agrégats/historique d’expériences, contexte résumable pour LLM

Dependencies: numpy, pandas, agents (dataclasses), validation_fn (walk-forward) si fourni

Conventions: *_pct keys are in percent (0-100); keys without suffix are fractions (0-1); execution_time_ms in milliseconds; request_id derived from params.

Read-if: Vous modifiez l’exécution des backtests côté agents ou le format des résultats exposés.

Skip-if: Vous ne touchez qu’au moteur backtest/ (engine/simulator/performance).
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from metrics_types import normalize_metrics, pct_to_frac
from utils.observability import get_obs_logger

logger = get_obs_logger(__name__)

if TYPE_CHECKING:  # pragma: no cover
    from agents.integration import AgentBacktestMetrics, WalkForwardMetrics

BacktestFn = Callable[[str, Dict[str, Any], pd.DataFrame], "AgentBacktestMetrics"]
ValidationFn = Callable[[str, Dict[str, Any], pd.DataFrame, int, float], "WalkForwardMetrics"]


@dataclass
class BacktestRequest:
    """Requête de backtest formulée par un agent."""

    # Identification
    request_id: str = ""
    requested_by: str = ""  # Nom de l'agent
    hypothesis: str = ""     # Pourquoi ce test ? (valeur LLM)

    # Configuration
    strategy_name: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)

    # Options
    use_walk_forward: bool = True
    walk_forward_windows: int = 5
    train_ratio: float = 0.7

    # Timestamp
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.request_id:
            # Générer un ID basé sur les paramètres
            param_str = json.dumps(self.parameters, sort_keys=True)
            self.request_id = hashlib.md5(
                f"{self.strategy_name}:{param_str}".encode()
            ).hexdigest()[:8]


@dataclass
class BacktestResult:
    """Résultat d'un backtest exécuté."""

    request: BacktestRequest
    success: bool

    # Métriques principales
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    total_return: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0

    # Métriques Tier S
    sqn: float = 0.0
    calmar_ratio: float = 0.0
    recovery_factor: float = 0.0

    # Walk-Forward (si activé)
    train_sharpe: float = 0.0
    test_sharpe: float = 0.0
    overfitting_ratio: float = 0.0

    # Métadonnées
    execution_time_ms: float = 0.0
    error_message: str = ""

    # Données brutes (pour analyse détaillée)
    equity_curve: Optional[List[float]] = None
    trades: Optional[List[Dict]] = None

    def to_summary_dict(self) -> Dict[str, Any]:
        """Résumé pour le LLM."""
        return {
            "request_id": self.request.request_id,
            "hypothesis": self.request.hypothesis,
            "parameters": self.request.parameters,
            "success": self.success,
            "sharpe_ratio": round(self.sharpe_ratio, 3),
            "sortino_ratio": round(self.sortino_ratio, 3),
            "total_return": f"{self.total_return:.2%}",
            "max_drawdown": f"{self.max_drawdown:.2%}",
            "win_rate": f"{self.win_rate:.2%}",
            "total_trades": self.total_trades,
            "overfitting_ratio": round(self.overfitting_ratio, 2) if self.overfitting_ratio else None,
            "execution_time_ms": round(self.execution_time_ms, 1),
        }

    def to_analysis_prompt(self) -> str:
        """Format pour analyse LLM."""
        lines = [
            f"=== Backtest Result: {self.request.request_id} ===",
            f"Hypothesis: {self.request.hypothesis}",
            f"Parameters: {json.dumps(self.request.parameters)}",
            "",
            "Metrics:",
            f"  Sharpe Ratio: {self.sharpe_ratio:.3f}",
            f"  Sortino Ratio: {self.sortino_ratio:.3f}",
            f"  Total Return: {self.total_return:.2%}",
            f"  Max Drawdown: {self.max_drawdown:.2%}",
            f"  Win Rate: {self.win_rate:.2%}",
            f"  Profit Factor: {self.profit_factor:.2f}",
            f"  Total Trades: {self.total_trades}",
        ]

        if self.overfitting_ratio > 0:
            lines.extend([
                "",
                "Walk-Forward Analysis:",
                f"  Train Sharpe: {self.train_sharpe:.3f}",
                f"  Test Sharpe: {self.test_sharpe:.3f}",
                f"  Overfitting Ratio: {self.overfitting_ratio:.2f}",
                f"  {'⚠️ OVERFITTING DETECTED' if self.overfitting_ratio > 1.5 else '✓ Ratio acceptable'}",
            ])

        return "\n".join(lines)


@dataclass
class ExperimentHistory:
    """
    Historique complet des expériences (backtests).

    Permet au LLM de voir tous les tests précédents,
    comprendre ce qui a été essayé, et proposer de nouvelles directions.
    """

    experiments: List[BacktestResult] = field(default_factory=list)

    # Meilleure configuration trouvée
    best_result: Optional[BacktestResult] = None
    best_sharpe: float = float("-inf")

    # Statistiques
    total_experiments: int = 0
    total_time_ms: float = 0.0

    def add_result(self, result: BacktestResult) -> None:
        """Ajoute un résultat et met à jour les stats."""
        self.experiments.append(result)
        self.total_experiments += 1
        self.total_time_ms += result.execution_time_ms

        # Mettre à jour le meilleur si applicable
        if result.success and result.sharpe_ratio > self.best_sharpe:
            # Vérifier overfitting
            if result.overfitting_ratio == 0 or result.overfitting_ratio < 1.5:
                self.best_result = result
                self.best_sharpe = result.sharpe_ratio
                logger.info(
                    f"Nouveau meilleur résultat: Sharpe={result.sharpe_ratio:.3f} "
                    f"avec params={result.request.parameters}"
                )

    def get_tried_parameters(self) -> List[Dict[str, Any]]:
        """Retourne tous les paramètres déjà testés."""
        return [exp.request.parameters for exp in self.experiments]

    def get_summary_for_llm(self, last_n: int = 10) -> str:
        """Génère un résumé pour le LLM."""
        lines = [
            f"=== Experiment History ({self.total_experiments} total) ===",
            "",
        ]

        if self.best_result:
            lines.extend([
                "Best Configuration Found:",
                f"  Parameters: {json.dumps(self.best_result.request.parameters)}",
                f"  Sharpe: {self.best_sharpe:.3f}",
                f"  Return: {self.best_result.total_return:.2%}",
                f"  Drawdown: {self.best_result.max_drawdown:.2%}",
                "",
            ])

        # Dernières expériences
        recent = self.experiments[-last_n:] if len(self.experiments) > last_n else self.experiments

        lines.append(f"Last {len(recent)} Experiments:")
        for i, exp in enumerate(recent, 1):
            status = "✓" if exp.success else "✗"
            sharpe = f"{exp.sharpe_ratio:.2f}" if exp.success else "N/A"
            lines.append(
                f"  {i}. [{status}] {exp.request.hypothesis[:50]}... "
                f"Sharpe={sharpe}"
            )

        # Insights
        if len(self.experiments) >= 3:
            sharpes = [e.sharpe_ratio for e in self.experiments if e.success]
            if sharpes:
                lines.extend([
                    "",
                    "Insights:",
                    f"  Average Sharpe: {np.mean(sharpes):.3f}",
                    f"  Sharpe Range: [{min(sharpes):.3f}, {max(sharpes):.3f}]",
                    f"  Improvement: {'+' if len(sharpes) > 1 and sharpes[-1] > sharpes[0] else ''}"
                    f"{((sharpes[-1] - sharpes[0]) / abs(sharpes[0]) * 100):.1f}% from first to last"
                    if len(sharpes) > 1 and sharpes[0] != 0 else "",
                ])

        return "\n".join(lines)

    def analyze_parameter_sensitivity(self) -> Dict[str, Dict[str, float]]:
        """
        Analyse la sensibilité des paramètres.

        Utile pour le LLM : savoir quels paramètres ont le plus d'impact.
        """
        if len(self.experiments) < 3:
            return {}

        # Collecter les données
        param_values: Dict[str, List[Tuple[Any, float]]] = {}

        for exp in self.experiments:
            if not exp.success:
                continue
            for param, value in exp.request.parameters.items():
                if param not in param_values:
                    param_values[param] = []
                param_values[param].append((value, exp.sharpe_ratio))

        # Calculer la corrélation pour chaque paramètre
        sensitivity = {}
        for param, values in param_values.items():
            if len(values) < 3:
                continue

            # Convertir en arrays
            try:
                x = np.array([float(v[0]) for v in values])
                y = np.array([v[1] for v in values])

                # Corrélation
                if np.std(x) > 0 and np.std(y) > 0:
                    corr = np.corrcoef(x, y)[0, 1]
                    sensitivity[param] = {
                        "correlation": float(corr),
                        "impact": abs(float(corr)),
                        "direction": "positive" if corr > 0 else "negative",
                        "range_tested": [float(min(x)), float(max(x))],
                    }
            except (ValueError, TypeError):
                continue

        return sensitivity


class BacktestExecutor:
    """
    Exécuteur de backtests pour les agents LLM.

    L'agent peut :
    1. Demander un backtest avec une hypothèse
    2. Recevoir les résultats
    3. Analyser et formuler une nouvelle hypothèse
    4. Itérer

    Example:
        >>> executor = BacktestExecutor(engine, strategy, data)
        >>>
        >>> # L'agent formule une hypothèse
        >>> request = BacktestRequest(
        ...     hypothesis="Reducing fast_period should capture more signals",
        ...     parameters={"fast_period": 8, "slow_period": 21}
        ... )
        >>>
        >>> # Exécution
        >>> result = executor.run(request)
        >>>
        >>> # L'agent analyse
        >>> print(result.to_analysis_prompt())
    """

    def __init__(
        self,
        backtest_fn: BacktestFn,
        strategy_name: str,
        data: pd.DataFrame,
        validation_fn: Optional[ValidationFn] = None,
        strategy_description: str = "",
    ) -> None:
        """
        Initialise l'exécuteur.

        Args:
            backtest_fn: Fonction de backtest (strategy_name, params, data) -> metrics
            strategy_name: Nom de la stratégie
            data: DataFrame OHLCV
            validation_fn: Fonction de validation walk-forward optionnelle
        """
        self.backtest_fn = backtest_fn
        self.strategy_name = strategy_name
        self.data = data
        self.validation_fn = validation_fn
        self.strategy_description = strategy_description

        self.history = ExperimentHistory()

        logger.info(f"BacktestExecutor initialisé: strategy={strategy_name}, rows={len(data)}")

    def run(self, request: BacktestRequest) -> BacktestResult:
        """
        Exécute un backtest pour une requête d'agent.

        Returns:
            BacktestResult avec toutes les métriques
        """
        request.strategy_name = self.strategy_name

        hypothesis_preview = (
            request.hypothesis[:50] + "..." if request.hypothesis else "N/A"
        )
        logger.info(
            f"Exécution backtest: {request.request_id} | "
            f"Hypothèse: {hypothesis_preview}"
        )

        start_time = time.time()

        try:
            # Exécuter le backtest principal
            metrics_raw: AgentBacktestMetrics = self.backtest_fn(
                self.strategy_name,
                request.parameters,
                self.data
            )

            if any(
                key in metrics_raw
                for key in ("total_return_pct", "max_drawdown_pct", "win_rate_pct")
            ):
                metrics_frac = pct_to_frac(metrics_raw)
            else:
                metrics_frac = normalize_metrics(metrics_raw, "frac")

            result = BacktestResult(
                request=request,
                success=True,
                sharpe_ratio=metrics_frac.get("sharpe_ratio", 0),
                sortino_ratio=metrics_frac.get("sortino_ratio", 0),
                total_return=metrics_frac.get("total_return", 0),
                max_drawdown=metrics_frac.get("max_drawdown", 0),
                win_rate=metrics_frac.get("win_rate", 0),
                profit_factor=metrics_frac.get("profit_factor", 0),
                total_trades=metrics_frac.get("total_trades", 0),
                sqn=metrics_frac.get("sqn", 0),
                calmar_ratio=metrics_frac.get("calmar_ratio", 0),
                recovery_factor=metrics_frac.get("recovery_factor", 0),
                equity_curve=metrics_frac.get("equity_curve"),
                trades=metrics_frac.get("trades"),
            )

            # Walk-forward si demandé et disponible
            if request.use_walk_forward and self.validation_fn:
                try:
                    wf_result = self.validation_fn(
                        self.strategy_name,
                        request.parameters,
                        self.data,
                        n_windows=request.walk_forward_windows,
                        train_ratio=request.train_ratio,
                    )
                    result.train_sharpe = wf_result.get("train_sharpe", 0)
                    result.test_sharpe = wf_result.get("test_sharpe", 0)
                    result.overfitting_ratio = wf_result.get("overfitting_ratio", 0)
                except Exception as e:
                    logger.warning(f"Walk-forward échoué: {e}")

            result.execution_time_ms = (time.time() - start_time) * 1000

        except Exception as e:
            logger.error(f"Backtest échoué: {e}")
            result = BacktestResult(
                request=request,
                success=False,
                error_message=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
            )

        # Enregistrer dans l'historique
        self.history.add_result(result)

        return result

    def run_batch(self, requests: List[BacktestRequest]) -> List[BacktestResult]:
        """Exécute plusieurs backtests en séquence."""
        return [self.run(req) for req in requests]

    def get_context_for_agent(self) -> str:
        """
        Génère le contexte complet pour un agent LLM.

        Inclut :
        - Historique des expériences
        - Meilleure configuration
        - Analyse de sensibilité
        - Suggestions basées sur les patterns
        """
        lines: List[str] = []

        if self.strategy_description:
            lines.extend([
                "=== Strategy Overview ===",
                self.strategy_description.strip(),
                "",
            ])

        lines.extend([
            self.history.get_summary_for_llm(),
            "",
        ])

        # Analyse de sensibilité
        sensitivity = self.history.analyze_parameter_sensitivity()
        if sensitivity:
            lines.extend([
                "Parameter Sensitivity Analysis:",
            ])
            for param, stats in sorted(
                sensitivity.items(),
                key=lambda x: x[1]["impact"],
                reverse=True
            ):
                direction = "↑" if stats["direction"] == "positive" else "↓"
                lines.append(
                    f"  {param}: impact={stats['impact']:.2f} {direction} "
                    f"(range: {stats['range_tested']})"
                )
            lines.append("")

        # Paramètres non encore testés dans certaines plages
        if self.history.total_experiments > 0:
            lines.extend([
                "Observations:",
                f"  - {self.history.total_experiments} experiments completed",
                f"  - Total compute time: {self.history.total_time_ms/1000:.1f}s",
            ])

            if self.history.best_result:
                if self.history.best_result.overfitting_ratio > 1.3:
                    lines.append("  - ⚠️ Best config shows some overfitting tendency")
                if self.history.best_result.total_trades < 50:
                    lines.append("  - ⚠️ Low trade count - consider wider parameters")

        return "\n".join(lines)

    def suggest_next_experiments(self, n: int = 3) -> List[Dict[str, Any]]:
        """
        Suggère les prochaines expériences basées sur l'historique.

        Ce n'est PAS de l'intelligence LLM - c'est de l'exploration
        algorithmique pour guider le LLM.
        """
        suggestions = []

        if not self.history.best_result:
            return suggestions

        best_params = self.history.best_result.request.parameters
        sensitivity = self.history.analyze_parameter_sensitivity()

        # 1. Varier le paramètre le plus impactant
        if sensitivity:
            most_impactful = max(sensitivity.items(), key=lambda x: x[1]["impact"])
            param_name = most_impactful[0]
            if param_name in best_params:
                current = best_params[param_name]
                # Explorer dans la direction favorable
                if most_impactful[1]["direction"] == "positive":
                    new_value = current * 1.2
                else:
                    new_value = current * 0.8

                suggestions.append({
                    "type": "sensitivity_exploration",
                    "rationale": f"Explore {param_name} in favorable direction",
                    "parameters": {**best_params, param_name: int(new_value)},
                })

        # 2. Perturbation aléatoire autour du meilleur
        perturbed = {}
        for k, v in best_params.items():
            if isinstance(v, (int, float)):
                # ±10% perturbation
                perturbed[k] = int(v * (1 + np.random.uniform(-0.1, 0.1)))

        if perturbed:
            suggestions.append({
                "type": "local_search",
                "rationale": "Small perturbation around best config",
                "parameters": perturbed,
            })

        return suggestions[:n]
