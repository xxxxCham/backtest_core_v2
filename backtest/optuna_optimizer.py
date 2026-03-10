"""
Module-ID: backtest.optuna_optimizer

Purpose: Optimiser les paramètres via Optuna (bayésien TPE/CMA-ES) avec pruning et support multi-objectif.

Role in pipeline: optimization

Key components: OptunaOptimizer, OptunaResult, OptunaStudyConfig

Inputs: strategy_name, DataFrame OHLCV, param_space Dict, n_trials, métrique(s) à optimiser, contraintes optionnelles

Outputs: OptunaResult (best_params, best_value, study, history)

Dependencies: optuna (TPE/CMA-ES samplers), backtest.engine, utils.observability

Conventions: param_space Dict avec {"param_name": {"type": "int"/"float", "low": X, "high": Y}}; metric "sharpe_ratio" par défaut; directions {"metric": 1/-1}; pruning via MedianPruner/HyperbandPruner.

Read-if: Configuration optimisation bayésienne, pruning, multi-objectif (Pareto) ou gestion des trials.

Skip-if: Vous utilisez sweep/pareto au lieu d'optuna.
"""

from __future__ import annotations

import gc
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

if TYPE_CHECKING:
    from utils.config import Config

try:
    import optuna
    from optuna.pruners import HyperbandPruner, MedianPruner
    from optuna.samplers import CmaEsSampler, TPESampler
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False
    optuna = None

from backtest.engine import BacktestEngine
from metrics_types import PerformanceMetricsPct, normalize_metrics
from utils.observability import (
    PerfCounters,
    generate_run_id,
    get_obs_logger,
)

logger = logging.getLogger(__name__)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class ParamSpec:
    """Spécification d'un paramètre à optimiser."""
    name: str
    param_type: str  # "int", "float", "categorical"
    low: Optional[float] = None
    high: Optional[float] = None
    choices: Optional[List[Any]] = None
    step: Optional[float] = None
    log: bool = False  # Échelle logarithmique

    def suggest(self, trial: "optuna.Trial") -> Any:
        """Suggère une valeur pour ce paramètre."""
        if self.param_type == "int":
            return trial.suggest_int(
                self.name,
                int(self.low),
                int(self.high),
                step=int(self.step) if self.step else 1,
                log=self.log,
            )
        elif self.param_type == "float":
            return trial.suggest_float(
                self.name,
                self.low,
                self.high,
                step=self.step,
                log=self.log,
            )
        elif self.param_type == "categorical":
            return trial.suggest_categorical(self.name, self.choices)
        else:
            raise ValueError(f"Type de paramètre inconnu: {self.param_type}")


@dataclass
class OptimizationResult:
    """Résultat d'une optimisation Optuna."""
    best_params: Dict[str, Any]
    best_value: float
    best_metrics: PerformanceMetricsPct
    n_trials: int
    n_completed: int
    n_pruned: int
    total_time: float
    history: List[Dict[str, Any]] = field(default_factory=list)
    study: Optional[Any] = None  # optuna.Study

    def to_dataframe(self) -> pd.DataFrame:
        """Convertit l'historique en DataFrame."""
        return pd.DataFrame(self.history)

    def get_top_n(
        self, n: int = 10, ascending: bool = False
    ) -> pd.DataFrame:
        """Retourne les N meilleurs trials."""
        df = self.to_dataframe()
        if "value" in df.columns:
            return df.nsmallest(n, "value") if ascending else df.nlargest(
                n, "value"
            )
        return df.head(n)

    def summary(self) -> str:
        """Retourne un résumé textuel."""
        return f"""
Optuna Optimization Results
===========================
Trials: {self.n_completed}/{self.n_trials} completed, {self.n_pruned} pruned
Total time: {self.total_time:.1f}s
Avg time/trial: {self.total_time / max(1, self.n_completed):.2f}s

Best Value: {self.best_value:.4f}
Best Parameters:
{self.best_params}

Best Metrics:
  Sharpe: {self.best_metrics.get('sharpe_ratio', 'N/A')}
  Total Return: {self.best_metrics.get('total_return_pct', 'N/A')}
  Max Drawdown: {self.best_metrics.get('max_drawdown_pct', 'N/A')}
"""


@dataclass
class MultiObjectiveResult:
    """Résultat d'une optimisation multi-objectif."""
    pareto_front: List[Dict[str, Any]]
    n_trials: int
    total_time: float
    study: Optional[Any] = None

    def to_dataframe(self) -> pd.DataFrame:
        """Convertit le front de Pareto en DataFrame."""
        return pd.DataFrame(self.pareto_front)


# ============================================================================
# OPTIMIZER CLASS
# ============================================================================

class OptunaOptimizer:
    """
    Optimiseur bayésien pour stratégies de trading.

    Utilise Optuna (TPE sampler par défaut) pour explorer efficacement
    l'espace des paramètres avec moins d'évaluations que le grid search.

    Features:
    - Optimisation single/multi-objectif
    - Pruning automatique (early stopping)
    - Contraintes sur les paramètres
    - Intégration walk-forward
    - Logs structurés avec run_id

    Example:
        >>> optimizer = OptunaOptimizer(
        ...     strategy_name="ema_cross",
        ...     data=ohlcv_df,
        ...     param_space={
        ...         "fast_period": {"type": "int", "low": 5, "high": 50},
        ...         "slow_period": {"type": "int", "low": 20, "high": 200},
        ...     },
        ...     constraints=[("slow_period", ">", "fast_period")],
        ... )
        >>> result = optimizer.optimize(n_trials=100)
    """

    def __init__(
        self,
        strategy_name: str,
        data: pd.DataFrame,
        param_space: Dict[str, Dict[str, Any]],
        *,
        initial_capital: float = 10000.0,
        constraints: Optional[List[Tuple[str, str, str]]] = None,
        seed: int = 42,
        auto_save: bool = True,
        early_stop_patience: Optional[int] = None,
        config: Optional["Config"] = None,
        symbol: str = "UNKNOWN",
        timeframe: str = "1m",
    ):
        """
        Initialise l'optimiseur.

        Args:
            strategy_name: Nom de la stratégie à optimiser
            data: DataFrame OHLCV
            param_space: Espace des paramètres à explorer
                Format: {"param_name": {"type": "int/float/categorical", ...}}
            initial_capital: Capital de départ
            constraints: Contraintes entre paramètres
                Format: [("param1", ">", "param2"), ...]
            seed: Seed pour reproductibilité
            auto_save: Sauvegarder automatiquement le meilleur résultat
            early_stop_patience: Arrêt anticipé après N trials sans amélioration (None = désactivé)
            config: Configuration du moteur (frais, slippage, etc.)
            symbol: Symbole pour les metadonnees
            timeframe: Timeframe pour les metadonnees
        """
        if not OPTUNA_AVAILABLE:
            raise ImportError(
                "Optuna n'est pas installé. "
                "Installez-le avec: pip install optuna"
            )

        self.strategy_name = strategy_name
        self.data = data
        self.initial_capital = initial_capital
        self.constraints = constraints or []
        self.seed = seed
        self.auto_save = auto_save
        self.early_stop_patience = early_stop_patience
        self.config = config
        self.symbol = symbol
        self.timeframe = timeframe
        self.run_id = generate_run_id()

        # Parser l'espace des paramètres
        self.param_specs = self._parse_param_space(param_space)

        # Logger avec contexte
        self.logger = get_obs_logger(
            __name__, run_id=self.run_id, strategy=strategy_name
        )

        # Compteurs de performance
        self.counters = PerfCounters()

        # Cache pour éviter les recalculs
        self._engine: Optional[BacktestEngine] = None
        self._best_metrics: PerformanceMetricsPct = {}

        # Tracking en temps réel pour l'UI (accessible depuis callbacks)
        self.best_pnl: float = float("-inf")
        self.best_return_pct: float = float("-inf")
        self.last_pnl: float = 0.0
        self.last_return_pct: float = 0.0

        self.logger.info(
            "optuna_optimizer_init params=%s constraints=%s early_stop=%s",
            len(self.param_specs), len(self.constraints), early_stop_patience or "disabled"
        )

    def _parse_param_space(
        self, param_space: Dict[str, Dict[str, Any]]
    ) -> List[ParamSpec]:
        """Parse l'espace des paramètres en ParamSpec."""
        specs = []
        for name, config in param_space.items():
            spec = ParamSpec(
                name=name,
                param_type=config.get("type", "float"),
                low=config.get("low"),
                high=config.get("high"),
                choices=config.get("choices"),
                step=config.get("step"),
                log=config.get("log", False),
            )
            specs.append(spec)
        return specs

    def _check_constraints(self, params: Dict[str, Any]) -> bool:
        """Vérifie que les contraintes sont respectées."""
        for left, op, right in self.constraints:
            left_val = params.get(left, 0)
            right_val = params.get(right, 0) if isinstance(right, str) else right

            if op == ">":
                if not left_val > right_val:
                    return False
            elif op == ">=":
                if not left_val >= right_val:
                    return False
            elif op == "<":
                if not left_val < right_val:
                    return False
            elif op == "<=":
                if not left_val <= right_val:
                    return False
            elif op == "!=":
                if not left_val != right_val:
                    return False
            elif op == "==":
                if not left_val == right_val:
                    return False

        return True

    def _create_early_stop_callback(
        self, patience: int, direction: str = "maximize", metric_index: int = 0
    ) -> Callable[["optuna.Study", "optuna.Trial"], None]:
        """
        Crée un callback d'early stopping pour Optuna.

        Arrête l'optimisation après 'patience' trials sans amélioration.

        Args:
            patience: Nombre de trials sans amélioration avant arrêt
            direction: "maximize" ou "minimize"
            metric_index: Index de la métrique pour multi-objectif (0 par défaut)

        Returns:
            Callback Optuna
        """
        best_score: Optional[float] = None
        no_improve_trials = 0

        def callback(study: "optuna.Study", trial: "optuna.Trial") -> None:
            nonlocal best_score, no_improve_trials

            # Ignorer les trials pruned ou failed
            if trial.state != optuna.trial.TrialState.COMPLETE:
                return

            # Support multi-objectif : utiliser trial.values[metric_index]
            try:
                score = trial.values[metric_index] if hasattr(trial, "values") and trial.values else trial.value
            except (AttributeError, IndexError):
                # Fallback pour single-objectif
                score = trial.value

            # Première itération ou amélioration détectée
            if best_score is None:
                best_score = score
                no_improve_trials = 0
                self.logger.debug(
                    "early_stop_init best_score=%.4f trial=%s",
                    score, trial.number
                )
            else:
                improved = (
                    score > best_score if direction == "maximize"
                    else score < best_score
                )

                if improved:
                    self.logger.debug(
                        "early_stop_improve old=%.4f new=%.4f trial=%s",
                        best_score, score, trial.number
                    )
                    best_score = score
                    no_improve_trials = 0
                else:
                    no_improve_trials += 1
                    self.logger.debug(
                        "early_stop_no_improve count=%s/%s trial=%s",
                        no_improve_trials, patience, trial.number
                    )

            # Arrêt anticipé si patience dépassée
            if no_improve_trials >= patience:
                self.logger.info(
                    "early_stop_triggered trials_without_improvement=%s best_score=%.4f",
                    no_improve_trials, best_score
                )
                study.stop()

        return callback

    def _create_objective(
        self,
        metric: str = "sharpe_ratio",
        direction: str = "maximize",
        use_walk_forward: bool = False,
    ) -> Callable[["optuna.Trial"], float]:
        """
        Crée la fonction objectif pour Optuna.

        Args:
            metric: Métrique à optimiser
            direction: "maximize" ou "minimize"
            use_walk_forward: Utiliser validation walk-forward

        Returns:
            Fonction objectif callable
        """
        # Créer l'engine une seule fois
        if self._engine is None:
            engine_kwargs = {
                "initial_capital": self.initial_capital,
                "run_id": self.run_id,
            }
            if self.config is not None:
                engine_kwargs["config"] = self.config
            self._engine = BacktestEngine(**engine_kwargs)

        def objective(trial: "optuna.Trial") -> float:
            # Suggérer les paramètres
            params = {}
            for spec in self.param_specs:
                params[spec.name] = spec.suggest(trial)

            # Vérifier les contraintes
            if not self._check_constraints(params):
                # Pénaliser les combinaisons invalides
                return float("-inf") if direction == "maximize" else float("inf")

            try:
                # Exécuter le backtest avec mode rapide pour optimisation
                result = self._engine.run(
                    df=self.data,
                    strategy=self.strategy_name,
                    params=params,
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                    silent_mode=True,     # Pas de logs pour performance
                    fast_metrics=True,    # Mode NumPy pur pour Sharpe (10x plus rapide)
                )

                # Log des métriques disponibles au premier trial
                if trial.number == 0:
                    available_metrics = sorted(result.metrics.keys())
                    self.logger.info(
                        "trial_0_metrics_available count=%s metrics=[%s]",
                        len(available_metrics),
                        ", ".join(available_metrics)
                    )

                # Extraire la métrique (STRICT: crash si absente)
                if metric not in result.metrics:
                    available = ", ".join(sorted(result.metrics.keys()))
                    msg = (
                        f"Optuna metric '{metric}' not found in result.metrics. "
                        f"Available metrics: [{available}]. "
                        f"trial={trial.number} params={params}"
                    )
                    self.logger.error(msg)
                    raise KeyError(msg)

                value = float(result.metrics[metric])

                # Extraire P&L et Return pour tracking temps réel UI
                current_pnl = float(result.metrics.get("total_pnl", 0.0))
                current_return = float(result.metrics.get("total_return_pct", 0.0))
                self.last_pnl = current_pnl
                self.last_return_pct = current_return

                # Mettre à jour les meilleurs scores (basé sur P&L, pas sur la métrique optimisée)
                if current_pnl > self.best_pnl:
                    self.best_pnl = current_pnl
                    self.best_return_pct = current_return

                # Stocker dans trial.user_attrs pour accès depuis callbacks
                # OPTIMISATION: Ne stocker que les infos essentielles pour réduire la mémoire
                trial.set_user_attr("pnl", current_pnl)
                trial.set_user_attr("return_pct", current_return)
                # Supprimé: best_pnl_so_far et best_return_so_far (redondant, accessible via optimizer)

                # OPTIMISATION: Garbage collection périodique pour les gros runs
                if trial.number > 0 and trial.number % 500 == 0:
                    gc.collect()

                # Stocker les meilleures métriques
                if (direction == "maximize" and value > self._best_metrics.get(
                    metric, float("-inf")
                )) or (direction == "minimize" and value < self._best_metrics.get(
                    metric, float("inf")
                )):
                    self._best_metrics = normalize_metrics(result.metrics, "pct")

                # Log pour debug
                self.logger.debug(
                    "trial_%s params=%s %s=%.4f",
                    trial.number, params, metric, value
                )

                return value

            except KeyError:
                raise
            except Exception as e:
                self.logger.warning(
                    "trial_%s_failed error=%s", trial.number, str(e)
                )
                # Retourner une valeur très mauvaise
                return float("-inf") if direction == "maximize" else float("inf")

        return objective

    def optimize(
        self,
        n_trials: int = 100,
        metric: str = "sharpe_ratio",
        direction: str = "maximize",
        *,
        timeout: Optional[float] = None,
        sampler: str = "tpe",
        pruner: str = "median",
        n_startup_trials: int = 10,
        show_progress: bool = True,
        callbacks: Optional[List[Callable]] = None,
        early_stop_patience: Optional[int] = None,
    ) -> OptimizationResult:
        """
        Lance l'optimisation.

        Args:
            n_trials: Nombre de trials à exécuter
            metric: Métrique à optimiser
            direction: "maximize" ou "minimize"
            timeout: Timeout en secondes (optionnel)
            sampler: Algorithme ("tpe", "cmaes", "random")
            pruner: Stratégie de pruning ("median", "hyperband", "none")
            n_startup_trials: Trials aléatoires avant TPE
            show_progress: Afficher la progression
            callbacks: Callbacks Optuna optionnels
            early_stop_patience: Arrêt après N trials sans amélioration (None = utiliser valeur __init__)

        Returns:
            OptimizationResult avec les meilleurs paramètres
        """
        self.logger.info(
            "optimization_start n_trials=%s metric=%s direction=%s",
            n_trials, metric, direction
        )

        self.counters.start("total")
        start_time = time.time()

        # Créer le sampler
        # OPTIMISATION: Pour les gros runs (>1000 trials), limiter l'historique TPE
        # pour éviter le ralentissement O(n²)
        if sampler == "tpe":
            # n_ei_candidates: nombre de candidats évalués (défaut 24, on garde)
            # consider_prior: utiliser la distribution prior
            # consider_magic_clip: éviter les valeurs extrêmes
            optuna_sampler = TPESampler(
                seed=self.seed,
                n_startup_trials=n_startup_trials,
                # Limiter l'historique pour les gros runs (garde les 500 meilleurs trials récents)
                consider_prior=True,
                consider_magic_clip=True,
            )
        elif sampler == "cmaes":
            optuna_sampler = CmaEsSampler(seed=self.seed)
        else:
            optuna_sampler = optuna.samplers.RandomSampler(seed=self.seed)

        # Créer le pruner
        if pruner == "median":
            optuna_pruner = MedianPruner(
                n_startup_trials=n_startup_trials,
                n_warmup_steps=5,
            )
        elif pruner == "hyperband":
            optuna_pruner = HyperbandPruner()
        else:
            optuna_pruner = optuna.pruners.NopPruner()

        # Créer l'étude
        study = optuna.create_study(
            direction=direction,
            sampler=optuna_sampler,
            pruner=optuna_pruner,
        )

        # Configurer le logging Optuna
        if not show_progress:
            optuna.logging.set_verbosity(optuna.logging.WARNING)

        # Créer l'objectif
        objective = self._create_objective(metric, direction)

        # Préparer les callbacks (early stopping si configuré)
        final_callbacks = callbacks or []

        # Utiliser early_stop_patience de l'argument ou de l'instance
        patience = early_stop_patience if early_stop_patience is not None else self.early_stop_patience

        if patience and patience > 0:
            early_stop_cb = self._create_early_stop_callback(patience, direction)
            final_callbacks.append(early_stop_cb)
            self.logger.info(
                "early_stop_enabled patience=%s direction=%s",
                patience, direction
            )

        # Lancer l'optimisation
        study.optimize(
            objective,
            n_trials=n_trials,
            timeout=timeout,
            callbacks=final_callbacks if final_callbacks else None,
            show_progress_bar=show_progress,
        )

        self.counters.stop("total")
        total_time = time.time() - start_time

        # Construire l'historique
        history = []
        for trial in study.trials:
            if trial.state == optuna.trial.TrialState.COMPLETE:
                history.append({
                    "trial": trial.number,
                    "value": trial.value,
                    **trial.params,
                })

        # Compter les trials
        n_completed = len([
            t for t in study.trials
            if t.state == optuna.trial.TrialState.COMPLETE
        ])
        n_pruned = len([
            t for t in study.trials
            if t.state == optuna.trial.TrialState.PRUNED
        ])

        result = OptimizationResult(
            best_params=study.best_params,
            best_value=study.best_value,
            best_metrics=self._best_metrics,
            n_trials=n_trials,
            n_completed=n_completed,
            n_pruned=n_pruned,
            total_time=total_time,
            history=history,
            study=study,
        )

        self.logger.info(
            "optimization_end duration=%.1fs best_%s=%.4f",
            total_time, metric, study.best_value
        )

        # Sauvegarde automatique si activée
        if self.auto_save:
            try:
                import pandas as pd

                from backtest.engine import RunResult
                from backtest.storage import get_storage

                storage = get_storage()

                n_bars = int(len(self.data))
                period_start = ""
                period_end = ""
                if isinstance(self.data.index, pd.DatetimeIndex) and n_bars > 0:
                    period_start = str(self.data.index[0])
                    period_end = str(self.data.index[-1])

                # Créer un RunResult minimal pour storage (sans equity/trades détaillés)
                # car Optuna optimise les paramètres, pas les runs complets
                run_result = RunResult(
                    equity=pd.Series(dtype=float),  # Vide
                    returns=pd.Series(dtype=float),  # Vide
                    trades=pd.DataFrame(),  # Vide
                    metrics=self._best_metrics,
                    meta={
                        "run_id": f"optuna_{self.run_id}",
                        "strategy": self.strategy_name,
                        "symbol": self.symbol,
                        "timeframe": self.timeframe,
                        "params": result.best_params,
                        "optimizer": "optuna",
                        "n_trials": result.n_trials,
                        "n_completed": result.n_completed,
                        "n_bars": n_bars,
                        "n_trades": int((result.best_metrics or {}).get("total_trades", 0) or 0),
                        "period_start": period_start,
                        "period_end": period_end,
                        "duration_sec": float(result.total_time),
                    }
                )

                saved_run_id = storage.save_result(run_result)
                self.logger.info(f"✅ Meilleur résultat Optuna sauvegardé: {saved_run_id}")

            except Exception as e:
                self.logger.warning(f"⚠️ Sauvegarde automatique échouée: {e}")

        return result

    def optimize_multi_objective(
        self,
        n_trials: int = 100,
        metrics: List[str] = None,
        directions: List[str] = None,
        *,
        timeout: Optional[float] = None,
        show_progress: bool = True,
        early_stop_patience: Optional[int] = None,
    ) -> MultiObjectiveResult:
        """
        Optimisation multi-objectif (front de Pareto).

        Args:
            n_trials: Nombre de trials
            metrics: Liste des métriques à optimiser
            directions: Liste des directions ("maximize"/"minimize")
            timeout: Timeout en secondes
            show_progress: Afficher la progression
            early_stop_patience: Arrêt après N trials sans amélioration (None = utiliser valeur __init__)

        Returns:
            MultiObjectiveResult avec le front de Pareto

        Example:
            >>> result = optimizer.optimize_multi_objective(
            ...     n_trials=100,
            ...     metrics=["sharpe_ratio", "max_drawdown_pct"],
            ...     directions=["maximize", "minimize"],
            ... )
        """
        metrics = metrics or ["sharpe_ratio", "max_drawdown_pct"]
        directions = directions or ["maximize", "minimize"]

        self.logger.info(
            "multi_objective_start n_trials=%s metrics=%s",
            n_trials, metrics
        )

        start_time = time.time()

        # Créer l'engine
        if self._engine is None:
            engine_kwargs = {
                "initial_capital": self.initial_capital,
                "run_id": self.run_id,
            }
            if self.config is not None:
                engine_kwargs["config"] = self.config
            self._engine = BacktestEngine(**engine_kwargs)

        def multi_objective(trial: "optuna.Trial") -> List[float]:
            # Suggérer les paramètres
            params = {}
            for spec in self.param_specs:
                params[spec.name] = spec.suggest(trial)

            # Vérifier les contraintes
            if not self._check_constraints(params):
                return [
                    float("-inf") if d == "maximize" else float("inf")
                    for d in directions
                ]

            try:
                result = self._engine.run(
                    df=self.data,
                    strategy=self.strategy_name,
                    params=params,
                    symbol=self.symbol,
                    timeframe=self.timeframe,
                )

                # Log des métriques disponibles au premier trial
                if trial.number == 0:
                    available_metrics = sorted(result.metrics.keys())
                    self.logger.info(
                        "multi_obj_trial_0_metrics count=%s metrics=[%s]",
                        len(available_metrics),
                        ", ".join(available_metrics)
                    )

                # Extraire les métriques (STRICT: crash si absente)
                values = []
                for m in metrics:
                    if m not in result.metrics:
                        available = ", ".join(sorted(result.metrics.keys()))
                        msg = (
                            f"Multi-objective metric '{m}' not found in result.metrics. "
                            f"Available metrics: [{available}]. "
                            f"trial={trial.number} params={params}"
                        )
                        self.logger.error(msg)
                        raise KeyError(msg)
                    values.append(float(result.metrics[m]))

                # Log des valeurs extraites
                self.logger.debug(
                    "trial_%s metrics_extracted %s",
                    trial.number,
                    dict(zip(metrics, values))
                )

                return values

            except KeyError:
                raise
            except Exception as e:
                self.logger.warning(
                    "trial_%s_failed error=%s", trial.number, str(e)
                )
                return [
                    float("-inf") if d == "maximize" else float("inf")
                    for d in directions
                ]

        # Créer l'étude multi-objectif
        study = optuna.create_study(
            directions=directions,
            sampler=TPESampler(seed=self.seed),
        )

        if not show_progress:
            optuna.logging.set_verbosity(optuna.logging.WARNING)

        # Early stopping pour multi-objectif (sur métrique primaire)
        callbacks = []
        patience = early_stop_patience if early_stop_patience is not None else self.early_stop_patience

        if patience and patience > 0:
            # Utiliser la première métrique (index 0) comme référence pour early stopping
            early_stop_cb = self._create_early_stop_callback(
                patience,
                directions[0],
                metric_index=0  # Première métrique
            )
            callbacks.append(early_stop_cb)
            self.logger.info(
                "early_stop_enabled patience=%s primary_metric=%s",
                patience, metrics[0]
            )

        study.optimize(
            multi_objective,
            n_trials=n_trials,
            timeout=timeout,
            callbacks=callbacks if callbacks else None,
            show_progress_bar=show_progress,
        )

        total_time = time.time() - start_time

        # Extraire le front de Pareto
        pareto_front = []
        for trial in study.best_trials:
            entry = {
                "trial": trial.number,
                **{m: v for m, v in zip(metrics, trial.values)},
                **trial.params,
            }
            pareto_front.append(entry)

        result = MultiObjectiveResult(
            pareto_front=pareto_front,
            n_trials=n_trials,
            total_time=total_time,
            study=study,
        )

        self.logger.info(
            "multi_objective_end duration=%.1fs pareto_size=%s",
            total_time, len(pareto_front)
        )

        return result


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def quick_optimize(
    strategy_name: str,
    data: pd.DataFrame,
    param_space: Dict[str, Dict[str, Any]],
    n_trials: int = 100,
    metric: str = "sharpe_ratio",
    **kwargs,
) -> OptimizationResult:
    """
    Raccourci pour une optimisation rapide.

    Args:
        strategy_name: Nom de la stratégie
        data: DataFrame OHLCV
        param_space: Espace des paramètres
        n_trials: Nombre de trials
        metric: Métrique à optimiser
        **kwargs: Arguments additionnels pour OptunaOptimizer

    Returns:
        OptimizationResult

    Example:
        >>> result = quick_optimize(
        ...     "ema_cross",
        ...     df,
        ...     param_space={
        ...         "fast_period": {"type": "int", "low": 5, "high": 50},
        ...         "slow_period": {"type": "int", "low": 20, "high": 200},
        ...     },
        ...     n_trials=50,
        ...     constraints=[("slow_period", ">", "fast_period")],
        ... )
    """
    if not OPTUNA_AVAILABLE:
        raise ImportError("Optuna non installé: pip install optuna")

    constraints = kwargs.pop("constraints", None)

    optimizer = OptunaOptimizer(
        strategy_name=strategy_name,
        data=data,
        param_space=param_space,
        constraints=constraints,
        **kwargs,
    )

    return optimizer.optimize(n_trials=n_trials, metric=metric)


def suggest_param_space(strategy_name: str) -> Dict[str, Dict[str, Any]]:
    """
    Suggère un espace de paramètres pour une stratégie.

    Args:
        strategy_name: Nom de la stratégie

    Returns:
        Dict avec l'espace des paramètres suggéré
    """
    # Espaces par défaut pour les stratégies connues
    default_spaces = {
        "ema_cross": {
            "fast_period": {"type": "int", "low": 5, "high": 50},
            "slow_period": {"type": "int", "low": 20, "high": 200},
        },
        "bollinger_atr": {
            "bb_period": {"type": "int", "low": 10, "high": 50},
            "bb_std": {"type": "float", "low": 1.5, "high": 3.0, "step": 0.1},
            "atr_period": {"type": "int", "low": 7, "high": 28},
            "atr_mult": {"type": "float", "low": 1.0, "high": 3.0, "step": 0.1},
        },
        "rsi_reversal": {
            "rsi_period": {"type": "int", "low": 7, "high": 28},
            "oversold_level": {"type": "int", "low": 20, "high": 40},
            "overbought_level": {"type": "int", "low": 60, "high": 80},
        },
        "macd_cross": {
            "fast_period": {"type": "int", "low": 8, "high": 20},
            "slow_period": {"type": "int", "low": 20, "high": 35},
            "signal_period": {"type": "int", "low": 5, "high": 15},
        },
    }

    if strategy_name in default_spaces:
        return default_spaces[strategy_name]

    # Espace générique
    return {
        "param1": {"type": "float", "low": 0.1, "high": 10.0},
        "param2": {"type": "int", "low": 5, "high": 50},
    }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "OptunaOptimizer",
    "OptimizationResult",
    "MultiObjectiveResult",
    "ParamSpec",
    "quick_optimize",
    "suggest_param_space",
    "OPTUNA_AVAILABLE",
]


# Docstring update summary
# - Docstring de module normalisée (LLM-friendly) centrée sur optimisation bayésienne
# - Conventions Optuna (param_space format, directions, pruning) explicitées
# - Read-if/Skip-if ajoutés pour tri rapide
