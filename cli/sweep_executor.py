"""
Module-ID: cli.sweep_executor

Purpose: Exécution des sweeps, grilles et optimisations Optuna en CLI.

Role in pipeline: Moteur d'exécution pour cmd_sweep, cmd_grid_backtest, cmd_optuna.

Key components: run_sweep, run_grid_backtest, run_optuna_optimization, CheckpointManager

Dependencies: backtest.engine, backtest.sweep, utils.parameters, optuna

Conventions: Progress callbacks, checkpoints automatiques, gestion mémoire.

Read-if: Modification de la logique d'exécution des optimisations.

Skip-if: Utilisation des commandes sans modifier le comportement.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass
class SweepConfig:
    """Configuration d'un sweep."""
    strategy_name: str
    data_path: Path
    symbol: str
    timeframe: str

    # Paramètres financiers
    initial_capital: float = 10000
    fees_bps: int = 10
    slippage_bps: int = 5

    # Paramètres sweep
    granularity: float = 1.0
    max_combinations: int = 10000
    metric: str = "sharpe_ratio"
    minimize: bool = False

    # Période
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    # Checkpoints
    checkpoint_every: int = 0
    checkpoint_seconds: float = 0


@dataclass
class SweepProgress:
    """État de progression d'un sweep."""
    completed: int = 0
    failed: int = 0
    total: int = 0

    best_score: float = float('-inf')
    best_params: Dict[str, Any] = field(default_factory=dict)
    best_metrics: Dict[str, Any] = field(default_factory=dict)

    start_time: float = field(default_factory=time.time)

    @property
    def elapsed(self) -> float:
        """Temps écoulé en secondes."""
        return time.time() - self.start_time

    @property
    def progress_pct(self) -> float:
        """Pourcentage de progression."""
        if self.total == 0:
            return 0
        return 100 * (self.completed + self.failed) / self.total

    @property
    def rate(self) -> float:
        """Combinaisons par seconde."""
        if self.elapsed == 0:
            return 0
        return (self.completed + self.failed) / self.elapsed

    @property
    def eta_seconds(self) -> float:
        """Temps restant estimé en secondes."""
        if self.rate == 0:
            return float('inf')
        remaining = self.total - (self.completed + self.failed)
        return remaining / self.rate


@dataclass
class SweepResult:
    """Résultat d'un sweep complet."""
    results: List[Dict[str, Any]]
    best_params: Dict[str, Any]
    best_metrics: Dict[str, Any]
    best_score: float

    total_combinations: int
    completed: int
    failed: int
    total_time: float

    strategy: str
    symbol: str
    timeframe: str


# =============================================================================
# CHECKPOINT MANAGER
# =============================================================================

class CheckpointManager:
    """Gère les checkpoints pour les optimisations longues."""

    def __init__(
        self,
        checkpoint_id: str,
        checkpoint_every: int = 0,
        checkpoint_seconds: float = 0,
        storage=None
    ):
        self.checkpoint_id = checkpoint_id
        self.checkpoint_every = checkpoint_every
        self.checkpoint_seconds = checkpoint_seconds
        self.storage = storage

        self.last_checkpoint_time = time.time()
        self.last_checkpoint_count = 0
        self.items: List[Dict] = []

    @property
    def enabled(self) -> bool:
        """Vérifie si les checkpoints sont activés."""
        return (self.checkpoint_every > 0 or self.checkpoint_seconds > 0) and self.storage is not None

    def add_result(self, result: Dict):
        """Ajoute un résultat au buffer de checkpoint."""
        self.items.append(result)

    def should_checkpoint(self, total_done: int) -> bool:
        """Vérifie si on doit faire un checkpoint maintenant."""
        if not self.enabled or total_done == 0:
            return False

        now = time.time()

        # Check par nombre
        if self.checkpoint_every > 0:
            if total_done - self.last_checkpoint_count >= self.checkpoint_every:
                return True

        # Check par temps
        if self.checkpoint_seconds > 0:
            if now - self.last_checkpoint_time >= self.checkpoint_seconds:
                return True

        return False

    def save_checkpoint(
        self,
        progress: SweepProgress,
        config: SweepConfig,
        status: str = "in_progress"
    ):
        """Sauvegarde un checkpoint."""
        if not self.enabled:
            return

        from backtest.sweep import SweepResults

        sweep_results = SweepResults(
            items=self.items,
            best_params=progress.best_params,
            best_metrics=progress.best_metrics,
            total_time=progress.elapsed,
            n_completed=progress.completed,
            n_failed=progress.failed,
        )

        extra_metadata = {
            "strategy": config.strategy_name,
            "symbol": config.symbol,
            "timeframe": config.timeframe,
            "total_combinations": config.max_combinations,
            "period_start": config.start_date,
            "period_end": config.end_date,
            "status": status,
        }

        self.storage.save_sweep_results(
            sweep_results,
            sweep_id=self.checkpoint_id,
            mode="sweep",
            extra_metadata=extra_metadata,
        )

        self.last_checkpoint_time = time.time()
        self.last_checkpoint_count = progress.completed + progress.failed


# =============================================================================
# GÉNÉRATION DE GRILLE
# =============================================================================

def build_param_grid_from_strategy(
    strategy_instance,
    granularity: float = 1.0,
    max_combinations: int = 10000,
    include_optional: bool = False
) -> Tuple[Dict[str, List], List[str]]:
    """
    Construit une grille de paramètres depuis une stratégie.

    Args:
        strategy_instance: Instance de la stratégie
        granularity: Niveau de granularité (1.0 = normal)
        max_combinations: Limite de combinaisons
        include_optional: Inclure les paramètres optionnels

    Returns:
        Tuple (param_grid, param_names)
    """
    from utils.parameters import ParameterSpec, generate_param_grid

    # Construire les specs
    param_specs = {}
    for name, (min_v, max_v) in strategy_instance.param_ranges.items():
        # Vérifier si paramètre optionnel
        if hasattr(strategy_instance, "parameter_specs"):
            spec = strategy_instance.parameter_specs.get(name)
            if spec and not getattr(spec, "optimize", True) and not include_optional:
                continue

        default = strategy_instance.default_params.get(name, (min_v + max_v) / 2)
        param_type = "int" if isinstance(default, int) else "float"

        param_specs[name] = ParameterSpec(
            name=name,
            min_val=min_v,
            max_val=max_v,
            default=default,
            param_type=param_type,
        )

    # Générer la grille
    grid = generate_param_grid(
        param_specs,
        granularity=granularity,
        max_total_combinations=max_combinations,
    )

    param_names = list(param_specs.keys())

    return list(grid), param_names


def build_simple_grid(
    param_ranges: Dict[str, Tuple[float, float]],
    defaults: Dict[str, Any],
    n_values: int = 3
) -> Tuple[List[Dict], List[str]]:
    """
    Construit une grille simple avec N valeurs par paramètre.

    Args:
        param_ranges: {param: (min, max)}
        defaults: Valeurs par défaut
        n_values: Nombre de valeurs par paramètre

    Returns:
        Tuple (list of param dicts, param names)
    """
    param_grid = {}

    for param_name, (min_val, max_val) in param_ranges.items():
        default = defaults.get(param_name, (min_val + max_val) / 2)

        if isinstance(default, int):
            step = max(1, (max_val - min_val) // (n_values - 1))
            values = [min_val + i * step for i in range(n_values)]
            values = [int(v) for v in values if v <= max_val]
        else:
            step = (max_val - min_val) / (n_values - 1)
            values = [min_val + i * step for i in range(n_values)]

        param_grid[param_name] = values

    # Générer toutes les combinaisons
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())

    all_combinations = []
    for combo in product(*param_values):
        all_combinations.append(dict(zip(param_names, combo)))

    return all_combinations, param_names


# =============================================================================
# EXÉCUTION SWEEP
# =============================================================================

def run_sweep(
    config: SweepConfig,
    df: pd.DataFrame,
    param_grid: List[Dict],
    on_progress: Optional[Callable[[SweepProgress], None]] = None,
    on_result: Optional[Callable[[Dict], None]] = None,
) -> SweepResult:
    """
    Exécute un sweep paramétrique.

    Args:
        config: Configuration du sweep
        df: DataFrame OHLCV
        param_grid: Liste des combinaisons de paramètres
        on_progress: Callback de progression
        on_result: Callback par résultat

    Returns:
        SweepResult avec tous les résultats
    """
    from backtest.engine import BacktestEngine
    from backtest.sweep_numba import (
        normalize_numba_metric_name,
        normalize_numba_strategy_key,
        run_numba_sweep_items_if_supported,
    )
    from utils.config import Config

    # Configuration
    engine_config = Config(
        fees_bps=config.fees_bps,
        slippage_bps=config.slippage_bps,
    )

    # Initialisation
    progress = SweepProgress(total=len(param_grid))

    # Checkpoint manager
    checkpoint_mgr = None
    if config.checkpoint_every > 0 or config.checkpoint_seconds > 0:
        from backtest.storage import get_storage
        storage = get_storage()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        checkpoint_id = f"sweep_{config.strategy_name}_{config.symbol}_{timestamp}"
        checkpoint_mgr = CheckpointManager(
            checkpoint_id=checkpoint_id,
            checkpoint_every=config.checkpoint_every,
            checkpoint_seconds=config.checkpoint_seconds,
            storage=storage,
        )

    minimize = config.minimize
    if minimize:
        progress.best_score = float('inf')

    results = []
    strategy_key = normalize_numba_strategy_key(config.strategy_name)
    metric_key = normalize_numba_metric_name(config.metric)

    def consume_numba_chunk(
        chunk_items: List[Dict[str, Any]],
        completed: int,
        total: int,
        _best_result: Optional[Dict[str, Any]],
    ) -> None:
        for item_data in chunk_items:
            metrics = item_data.get("metrics", {})
            score = item_data.get("score", metrics.get(metric_key, 0))
            result_item = {
                "params": item_data.get("params", {}),
                "metrics": metrics,
                "score": score,
            }
            results.append(result_item)

            is_better = (
                (score < progress.best_score) if minimize else (score > progress.best_score)
            )
            if is_better:
                progress.best_score = score
                progress.best_params = result_item["params"].copy()
                progress.best_metrics = metrics.copy()

            if checkpoint_mgr:
                checkpoint_mgr.add_result(result_item)

            if on_result:
                on_result(result_item)

        progress.completed = completed
        progress.total = total

        if on_progress:
            on_progress(progress)

        if checkpoint_mgr and checkpoint_mgr.should_checkpoint(progress.completed + progress.failed):
            checkpoint_mgr.save_checkpoint(progress, config)

    numba_items = run_numba_sweep_items_if_supported(
        df=df,
        strategy_key=strategy_key,
        param_grid=param_grid,
        metric=metric_key,
        initial_capital=config.initial_capital,
        fees_bps=config.fees_bps,
        slippage_bps=config.slippage_bps,
        result_chunk_callback=consume_numba_chunk,
    )

    if numba_items is not None:
        if numba_items and not results:
            consume_numba_chunk(numba_items, len(numba_items), len(param_grid), None)

        if checkpoint_mgr:
            checkpoint_mgr.save_checkpoint(progress, config, status="completed")

        return SweepResult(
            results=results,
            best_params=progress.best_params,
            best_metrics=progress.best_metrics,
            best_score=progress.best_score,
            total_combinations=len(param_grid),
            completed=progress.completed,
            failed=progress.failed,
            total_time=progress.elapsed,
            strategy=config.strategy_name,
            symbol=config.symbol,
            timeframe=config.timeframe,
        )

    for params in param_grid:
        engine = BacktestEngine(
            initial_capital=config.initial_capital,
            config=engine_config,
        )

        try:
            result = engine.run(
                df=df,
                strategy=config.strategy_name,
                params=params,
                symbol=config.symbol,
                timeframe=config.timeframe,
            )

            metrics = result.metrics.to_dict() if hasattr(result.metrics, 'to_dict') else result.metrics
            score = metrics.get(metric_key, metrics.get(config.metric, 0))

            result_item = {
                "params": params,
                "metrics": metrics,
                "score": score,
            }
            results.append(result_item)

            # Mettre à jour le meilleur
            is_better = (score < progress.best_score) if minimize else (score > progress.best_score)
            if is_better:
                progress.best_score = score
                progress.best_params = params.copy()
                progress.best_metrics = metrics.copy()

            progress.completed += 1

            if checkpoint_mgr:
                checkpoint_mgr.add_result(result_item)

            if on_result:
                on_result(result_item)

        except Exception as e:
            progress.failed += 1
            results.append({
                "params": params,
                "error": str(e),
            })

        # Progress callback
        if on_progress:
            on_progress(progress)

        # Checkpoint si nécessaire
        if checkpoint_mgr and checkpoint_mgr.should_checkpoint(progress.completed + progress.failed):
            checkpoint_mgr.save_checkpoint(progress, config)

    # Checkpoint final
    if checkpoint_mgr:
        checkpoint_mgr.save_checkpoint(progress, config, status="completed")

    return SweepResult(
        results=results,
        best_params=progress.best_params,
        best_metrics=progress.best_metrics,
        best_score=progress.best_score,
        total_combinations=len(param_grid),
        completed=progress.completed,
        failed=progress.failed,
        total_time=progress.elapsed,
        strategy=config.strategy_name,
        symbol=config.symbol,
        timeframe=config.timeframe,
    )


# =============================================================================
# EXÉCUTION OPTUNA
# =============================================================================

def run_optuna_optimization(
    strategy_name: str,
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    n_trials: int = 100,
    metric: str = "sharpe_ratio",
    direction: str = "maximize",
    sampler: str = "tpe",
    pruner: bool = True,
    n_jobs: int = 1,
    timeout: Optional[float] = None,
    initial_capital: float = 10000,
    fees_bps: int = 10,
    slippage_bps: int = 5,
    on_trial_complete: Optional[Callable] = None,
    quiet: bool = False,
) -> Dict[str, Any]:
    """
    Exécute une optimisation Optuna.

    Args:
        strategy_name: Nom de la stratégie
        df: DataFrame OHLCV
        symbol: Symbole
        timeframe: Timeframe
        n_trials: Nombre d'essais
        metric: Métrique à optimiser
        direction: "maximize" ou "minimize"
        sampler: Type de sampler ("tpe", "cmaes", "random")
        pruner: Activer le pruning
        n_jobs: Nombre de jobs parallèles
        timeout: Timeout en secondes
        initial_capital: Capital initial
        fees_bps: Frais en basis points
        slippage_bps: Slippage en basis points
        on_trial_complete: Callback après chaque trial
        quiet: Mode silencieux

    Returns:
        Dict avec résultats complets
    """
    try:
        from backtest.optuna_optimizer import (
            OPTUNA_AVAILABLE,
            OptunaOptimizer,
            suggest_param_space,
        )
    except ImportError:
        raise ImportError("Module optuna_optimizer non disponible")

    if not OPTUNA_AVAILABLE:
        raise ImportError("Optuna n'est pas installé: pip install optuna")

    from strategies import get_strategy
    from utils.config import Config

    # Récupérer la stratégie
    strategy_class = get_strategy(strategy_name)
    if not strategy_class:
        raise ValueError(f"Stratégie '{strategy_name}' non trouvée")

    strategy_instance = strategy_class()

    # Construire l'espace de paramètres
    param_space = suggest_param_space(strategy_instance)

    # Configuration
    config = Config(fees_bps=fees_bps, slippage_bps=slippage_bps)

    # Créer l'optimiseur
    optimizer = OptunaOptimizer(
        strategy_name=strategy_name,
        param_space=param_space,
        df=df,
        symbol=symbol,
        timeframe=timeframe,
        initial_capital=initial_capital,
        config=config,
        metric=metric,
        direction=direction,
    )

    # Exécuter l'optimisation
    result = optimizer.optimize(
        n_trials=n_trials,
        sampler=sampler,
        pruner=pruner,
        n_jobs=n_jobs,
        timeout=timeout,
        show_progress=not quiet,
        callback=on_trial_complete,
    )

    return {
        "best_params": result.best_params,
        "best_value": result.best_value,
        "best_metrics": result.best_metrics,
        "n_completed": result.n_completed,
        "n_pruned": result.n_pruned,
        "total_time": result.total_time,
        "history": result.history,
        "study": result.study,
    }


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Dataclasses
    "SweepConfig",
    "SweepProgress",
    "SweepResult",
    # Classes
    "CheckpointManager",
    # Fonctions grille
    "build_param_grid_from_strategy",
    "build_simple_grid",
    # Exécution
    "run_sweep",
    "run_optuna_optimization",
]
