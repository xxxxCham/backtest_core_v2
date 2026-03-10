"""
Module-ID: backtest.sweep

Purpose: Optimiser les paramètres via grid search parallélisé avec suivi temps réel et filtrage par contraintes.

Role in pipeline: optimization

Key components: SweepEngine, SweepResult, SweepResultItem, run_sweep

Inputs: param_grid (Dict ou liste), stratégie, DataFrame OHLCV, max_workers, constraints optionnelles

Outputs: SweepResult (best_result, all_results, stats, timing)

Dependencies: backtest.engine, performance.parallel, performance.monitor, utils.parameters

Conventions: Combinaisons générées via product(); contraintes appliquées; résultats triés par métrique cible; nb combinaisons plafonné.

Read-if: Paramétragedu sweep, parallelisation, monitoring ou ajout de contraintes.

Skip-if: Vous utilisez optuna/pareto au lieu de sweep classique.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import pandas as pd

if TYPE_CHECKING:
    from strategies.base import StrategyBase

from backtest.engine import BacktestEngine
from metrics_types import PerformanceMetricsPct, normalize_metrics
from performance.monitor import (
    ProgressBar,
    ResourceTracker,
)
from performance.parallel import (
    ParallelRunner,
    generate_param_grid,
)
from performance.profiler import Profiler
from backtest.sweep_numba import (
    normalize_numba_strategy_key,
    run_numba_sweep_items_if_supported,
    should_use_numba_backend,
)
from utils.parameters import compute_search_space_stats

logger = logging.getLogger(__name__)


def _normalize_metrics_pct(metrics: Dict[str, Any]) -> PerformanceMetricsPct:
    if not metrics:
        return {}
    return normalize_metrics(metrics, "pct")


@dataclass
class SweepResultItem:
    """Résultat d'une combinaison de paramètres."""
    params: Dict[str, Any]
    metrics: PerformanceMetricsPct
    success: bool
    error: Optional[str] = None


@dataclass
class SweepResults:
    """Résultats complets d'un sweep paramétrique."""
    items: List[SweepResultItem]
    best_params: Dict[str, Any]
    best_metrics: PerformanceMetricsPct
    total_time: float
    n_completed: int
    n_failed: int
    resource_stats: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        self.best_metrics = _normalize_metrics_pct(self.best_metrics)
        for item in self.items:
            item.metrics = _normalize_metrics_pct(item.metrics)

    def to_dataframe(self) -> pd.DataFrame:
        """Convertit les résultats en DataFrame."""
        rows = []
        for item in self.items:
            row = {**item.params, **item.metrics, "success": item.success}
            if item.error:
                row["error"] = item.error
            rows.append(row)
        return pd.DataFrame(rows)

    def get_top_n(self, n: int = 10, metric: str = "sharpe_ratio") -> pd.DataFrame:
        """Retourne les N meilleures combinaisons."""
        df = self.to_dataframe()
        if metric in df.columns:
            return df.nlargest(n, metric)
        return df.head(n)

    def summary(self) -> str:
        """Retourne un résumé textuel."""
        sharpe = self.best_metrics.get('sharpe_ratio', 0)
        total_pnl = self.best_metrics.get('total_pnl', 0)
        win_rate = self.best_metrics.get('win_rate_pct', 0)

        # Gérer le cas où les valeurs sont des strings (N/A)
        sharpe_str = f"{sharpe:.2f}" if isinstance(sharpe, (int, float)) else str(sharpe)
        pnl_str = f"${total_pnl:,.2f}" if isinstance(total_pnl, (int, float)) else str(total_pnl)
        wr_str = f"{win_rate:.1f}%" if isinstance(win_rate, (int, float)) else str(win_rate)

        return f"""
Sweep Results Summary
=====================
Completed: {self.n_completed}/{self.n_completed + self.n_failed}
Failed: {self.n_failed}
Total time: {self.total_time:.1f}s
Avg time/combo: {self.total_time / max(1, self.n_completed):.2f}s

Best Parameters:
{self.best_params}

Best Metrics:
  Sharpe: {sharpe_str}
  Total P&L: {pnl_str}
  Win Rate: {wr_str}
"""


def _run_single_backtest_wrapper(
    params: Dict[str, Any],
    df: pd.DataFrame,
    strategy: "StrategyBase",
    initial_capital: float,
    silent_mode: bool = True,
    fast_metrics: bool = True,
) -> Dict[str, Any]:
    """
    Wrapper function pour exécuter un backtest en parallèle (picklable).

    Cette fonction est conçue pour être utilisée avec concurrent.futures:
    - Accepte tous les arguments nécessaires explicitement
    - Retourne un dict avec params, metrics, success, error
    - Gère les exceptions de manière robuste

    Args:
        params: Paramètres de la stratégie
        df: DataFrame OHLCV
        strategy: Instance de stratégie
        initial_capital: Capital initial
        silent_mode: Désactive les logs pour accélérer les sweeps
        fast_metrics: Utilise la version rapide des métriques

    Returns:
        Dict avec clés: params, metrics, success, error (optionnel)
    """
    try:
        engine = BacktestEngine(initial_capital=initial_capital)
        result = engine.run(
            df=df,
            strategy=strategy,
            params=params,
            silent_mode=silent_mode,
            fast_metrics=fast_metrics,
        )

        return {
            "params": params,
            "metrics": _normalize_metrics_pct(result.metrics),
            "success": True,
        }
    except Exception as e:
        logger.error(f"Backtest failed for params {params}: {e}")
        return {
            "params": params,
            "metrics": {},
            "success": False,
            "error": str(e),
        }


class SweepEngine:
    """
    Moteur de sweep paramétrique avec parallélisation et monitoring.

    Features:
    - Exécution parallèle sur tous les CPU
    - Monitoring temps réel (CPU, RAM)
    - Barre de progression
    - Arrêt anticipé optionnel
    - Profiling optionnel

    Example:
        >>> engine = SweepEngine(max_workers=8)
        >>>
        >>> results = engine.run_sweep(
        ...     df=data,
        ...     strategy=my_strategy,
        ...     param_grid={
        ...         "period": range(10, 30, 5),
        ...         "threshold": [0.5, 1.0, 1.5]
        ...     },
        ...     optimize_for="sharpe_ratio"
        ... )
        >>>
        >>> print(results.best_params)
    """

    def __init__(
        self,
        max_workers: Optional[int] = None,
        use_processes: bool = True,
        initial_capital: float = 10000.0,
        enable_profiling: bool = False,
        auto_save: bool = True,
        save_individual_runs: bool = False,
        silent_mode: bool = True,
        fast_metrics: bool = True,
    ):
        """
        Initialise le moteur de sweep.

        Args:
            max_workers: Nombre de workers parallèles (None = auto)
            use_processes: Utiliser multiprocessing (True) ou threading (False)
            initial_capital: Capital de départ
            enable_profiling: Activer le profiling des performances
            auto_save: Sauvegarder automatiquement le résumé du sweep
            save_individual_runs: Sauvegarder chaque run individuel (False = résumé uniquement)
            silent_mode: Désactiver les logs internes pendant le sweep
            fast_metrics: Utiliser les métriques rapides (Sharpe/Sortino)
        """
        self.max_workers = max_workers
        self.use_processes = use_processes
        self.initial_capital = initial_capital
        self.enable_profiling = enable_profiling
        self.auto_save = auto_save
        self.save_individual_runs = save_individual_runs
        self.silent_mode = silent_mode
        self.fast_metrics = fast_metrics

        self._runner = ParallelRunner(
            max_workers=max_workers,
            use_processes=use_processes,
            backend="loky",  # Optimal: évite pickling répétitif du DataFrame
        )

        self._stop_requested = False

        logger.info(
            f"SweepEngine initialisé: {self._runner.max_workers} workers, "
            f"capital=${initial_capital:,.0f}, auto_save={auto_save}, "
            f"save_individual_runs={save_individual_runs}"
        )

    def run_sweep(
        self,
        df: pd.DataFrame,
        strategy: Union["StrategyBase", str],
        param_grid: Dict[str, Any],
        *,
        optimize_for: str = "sharpe_ratio",
        minimize: bool = False,
        show_progress: bool = True,
        early_stop_threshold: Optional[float] = None,
        silent_mode: Optional[bool] = None,
        fast_metrics: Optional[bool] = None,
        indicator_cache_config: Optional[Dict[str, Any]] = None,
    ) -> SweepResults:
        """
        Exécute un sweep paramétrique complet.

        Args:
            df: DataFrame OHLCV
            strategy: Stratégie à tester
            param_grid: Dict des plages de paramètres
            optimize_for: Métrique à optimiser
            indicator_cache_config: Config personnalisée IndicatorBank
                                   (ex: {"memory_max_entries": 100000, "disk_enabled": False})
            minimize: True pour minimiser (ex: drawdown)
            show_progress: Afficher la progression
            early_stop_threshold: Arrêter si métrique atteint ce seuil
            silent_mode: Désactiver logs internes (None = valeur engine)
            fast_metrics: Utiliser métriques rapides (None = valeur engine)

        Returns:
            SweepResults avec tous les résultats et le meilleur
        """
        self._stop_requested = False
        start_time = time.time()
        silent_mode = self.silent_mode if silent_mode is None else silent_mode
        fast_metrics = self.fast_metrics if fast_metrics is None else fast_metrics

        # Mode CPU-only: pas d'initialisation GPU

        # Calculer les statistiques d'espace de recherche
        try:
            stats = compute_search_space_stats(param_grid, max_combinations=100000)
            logger.info(f"Search space: {stats.summary()}")

            if stats.warnings:
                for warning in stats.warnings:
                    logger.warning(f"⚠️ {warning}")

            # Log détaillé par paramètre
            for param_name, count in stats.per_param_counts.items():
                if count > 0:
                    logger.debug(f"  {param_name}: {count} valeurs")
        except Exception as e:
            logger.warning(f"Failed to compute search space stats: {e}")

        # Générer toutes les combinaisons
        combinations = generate_param_grid(param_grid)
        n_combos = len(combinations)

        logger.info(f"Démarrage sweep: {n_combos} combinaisons")

        # Résoudre la stratégie si c'est un nom, en conservant la clé canonique
        strategy_key = strategy if isinstance(strategy, str) else getattr(strategy, "name", "")
        if isinstance(strategy, str):
            strategy = self._get_strategy_by_name(strategy)
        strategy_name = normalize_numba_strategy_key(strategy_key)

        # Tracker de ressources
        tracker = ResourceTracker(interval=1.0)
        tracker.start()

        results: List[SweepResultItem] = []
        best_value = float("-inf") if not minimize else float("inf")
        best_params: Dict[str, Any] = {}
        best_metrics: PerformanceMetricsPct = {}

        # Profiler optionnel
        profiler = Profiler("sweep") if self.enable_profiling else None
        if profiler:
            profiler.start()

        try:
            used_numba_backend = False

            if should_use_numba_backend(
                strategy_name,
                metric=optimize_for,
                total_combos=n_combos,
            ):
                logger.info("SweepEngine: backend Numba activé pour %s (%s combos)", strategy_name, n_combos)

                if show_progress:
                    pbar = ProgressBar(total=n_combos, description="Sweep")
                    pbar.__enter__()
                else:
                    pbar = None

                def progress_callback_numba(current: int, total: int, _best: Dict[str, Any]) -> None:
                    if pbar:
                        pbar.update(current)

                numba_items = run_numba_sweep_items_if_supported(
                    df=df,
                    strategy_key=strategy_name,
                    param_grid=combinations,
                    metric=optimize_for,
                    initial_capital=self.initial_capital,
                    progress_callback=progress_callback_numba if show_progress else None,
                    should_stop=lambda: self._stop_requested,
                )

                if pbar:
                    pbar.__exit__(None, None, None)

                for item_data in numba_items or []:
                    metrics = _normalize_metrics_pct(item_data["metrics"])
                    item = SweepResultItem(
                        params=item_data["params"],
                        metrics=metrics,
                        success=True,
                    )
                    results.append(item)

                    if optimize_for in item.metrics:
                        value = item.metrics[optimize_for]
                        is_better = (
                            (not minimize and value > best_value) or
                            (minimize and value < best_value)
                        )
                        if is_better:
                            best_value = value
                            best_params = item.params.copy()
                            best_metrics = item.metrics.copy()

                used_numba_backend = numba_items is not None

            if not used_numba_backend:
                # Callback de progression pour intégration avec ProgressBar
                pbar = None
                if show_progress:
                    pbar = ProgressBar(total=n_combos, description="Sweep")
                    pbar.__enter__()

                def progress_callback(current: int, total: int):
                    """Callback appelé par ParallelRunner pour mettre à jour la progress bar."""
                    if pbar:
                        pbar.update(current)

                # Exécution parallèle via ParallelRunner
                parallel_result = self._runner.run_sweep(
                    run_func=_run_single_backtest_wrapper,
                    param_grid=combinations,
                    progress_callback=progress_callback if show_progress else None,
                    # Fixed kwargs passés à chaque appel de _run_single_backtest_wrapper
                    df=df,
                    strategy=strategy,
                    initial_capital=self.initial_capital,
                    silent_mode=silent_mode,
                    fast_metrics=fast_metrics,
                )

                if pbar:
                    pbar.__exit__(None, None, None)

                # Traiter les résultats du ParallelRunner
                for item_data in parallel_result.results:
                    # Vérifier si un arrêt d'urgence a été demandé
                    if self._stop_requested:
                        logger.warning("🛑 Arrêt d'urgence détecté - Interruption du sweep")
                        break

                    if item_data.get("success"):
                        result = item_data["result"]
                        metrics = _normalize_metrics_pct(result.get("metrics", {}))
                        item = SweepResultItem(
                            params=result["params"],
                            metrics=metrics,
                            success=result["success"],
                            error=result.get("error"),
                        )
                    else:
                        # Cas d'erreur
                        item = SweepResultItem(
                            params=item_data["params"],
                            metrics={},
                            success=False,
                            error=item_data.get("error", "Unknown error"),
                        )

                    results.append(item)

                    # Mise à jour du meilleur
                    if item.success and optimize_for in item.metrics:
                        value = item.metrics[optimize_for]
                        is_better = (
                            (not minimize and value > best_value) or
                            (minimize and value < best_value)
                        )
                        if is_better:
                            best_value = value
                            best_params = item.params.copy()
                            best_metrics = item.metrics.copy()

                            # Early stopping (post-traitement)
                            if early_stop_threshold is not None:
                                if (not minimize and best_value >= early_stop_threshold) or \
                                   (minimize and best_value <= early_stop_threshold):
                                    logger.info(f"Early stop: {optimize_for}={best_value:.4f}")
                                    # Note: avec ParallelRunner, les tâches restantes sont déjà lancées
                                    # mais on arrête le traitement des résultats
                                    break

        finally:
            # Arrêter le tracking
            resource_stats = tracker.stop()

            if profiler:
                profiler.stop()
                if self.enable_profiling:
                    profiler.print_stats(top_n=10)

            # Mode CPU-only: pas de cleanup GPU

        total_time = time.time() - start_time
        n_completed = sum(1 for r in results if r.success)
        n_failed = sum(1 for r in results if not r.success)

        logger.info(f"Sweep terminé: {n_completed}/{n_combos} en {total_time:.1f}s")
        logger.info(f"Meilleur {optimize_for}: {best_value:.4f}")

        sweep_results = SweepResults(
            items=results,
            best_params=best_params,
            best_metrics=best_metrics,
            total_time=total_time,
            n_completed=n_completed,
            n_failed=n_failed,
            resource_stats={
                "cpu_avg": resource_stats.cpu_avg,
                "cpu_max": resource_stats.cpu_max,
                "memory_max_gb": resource_stats.memory_max_gb,
                "duration": resource_stats.duration_seconds,
            }
        )

        # Sauvegarde automatique si activée
        if self.auto_save:
            try:
                from backtest.storage import get_storage
                storage = get_storage()
                sweep_id = storage.save_sweep_results(sweep_results)
                logger.info(f"✅ Sweep sauvegardé: {sweep_id}")

                # Sauvegarder runs individuels si demandé (⚠️ peut générer beaucoup de dossiers)
                if self.save_individual_runs:
                    logger.info(f"💾 Sauvegarde de {n_completed} runs individuels...")
                    saved_count = 0
                    for item in results:
                        if item.success:
                            # Reconstruire un RunResult minimal pour storage
                            # Note: on n'a pas equity/returns dans SweepResultItem
                            # donc on sauvegarde uniquement les métriques
                            run_id = f"{sweep_id}_{saved_count:04d}"
                            metadata_path = storage.storage_dir / run_id
                            metadata_path.mkdir(parents=True, exist_ok=True)

                            metadata = {
                                "run_id": run_id,
                                "sweep_id": sweep_id,
                                "params": item.params,
                                "metrics": item.metrics,
                                "timestamp": datetime.now().isoformat(),
                            }

                            with open(metadata_path / "metadata.json", "w") as f:
                                json.dump(metadata, f, indent=2)

                            saved_count += 1

                    logger.info(f"✅ {saved_count} runs individuels sauvegardés")
            except Exception as e:
                logger.warning(f"⚠️ Sauvegarde automatique échouée: {e}")

        return sweep_results

    def run_sweep_parallel(
        self,
        df: pd.DataFrame,
        strategy: Union["StrategyBase", str],
        param_grid: Dict[str, Any],
        *,
        optimize_for: str = "sharpe_ratio",
        minimize: bool = False,
        silent_mode: Optional[bool] = None,
        fast_metrics: Optional[bool] = None,
    ) -> SweepResults:
        """
        Exécute un sweep paramétrique en parallèle (multiprocessing).

        Note: Le multiprocessing nécessite que strategy soit picklable.
        Pour des stratégies complexes, utilisez run_sweep().

        Args:
            df: DataFrame OHLCV
            strategy: Stratégie à tester
            param_grid: Dict des plages de paramètres
            optimize_for: Métrique à optimiser
            minimize: True pour minimiser
            silent_mode: Désactiver logs internes (None = valeur engine)
            fast_metrics: Utiliser métriques rapides (None = valeur engine)

        Returns:
            SweepResults
        """
        start_time = time.time()
        silent_mode = self.silent_mode if silent_mode is None else silent_mode
        fast_metrics = self.fast_metrics if fast_metrics is None else fast_metrics

        combinations = generate_param_grid(param_grid)
        n_combos = len(combinations)

        logger.info(f"Démarrage sweep parallèle: {n_combos} combinaisons, {self._runner.max_workers} workers")

        if isinstance(strategy, str):
            strategy = self._get_strategy_by_name(strategy)

        # Utiliser le runner parallèle
        parallel_result = self._runner.run_sweep(
            run_func=_run_single_backtest_wrapper,
            param_grid=combinations,
            df=df,
            strategy=strategy,
            initial_capital=self.initial_capital,
            silent_mode=silent_mode,
            fast_metrics=fast_metrics,
        )

        # Convertir les résultats
        results: List[SweepResultItem] = []
        best_value = float("-inf") if not minimize else float("inf")
        best_params: Dict[str, Any] = {}
        best_metrics: PerformanceMetricsPct = {}

        for item in parallel_result.results:
            if item.get("success"):
                metrics = _normalize_metrics_pct(item["result"].get("metrics", {}))
                result_item = SweepResultItem(
                    params=item["result"]["params"],
                    metrics=metrics,
                    success=True,
                )
            else:
                result_item = SweepResultItem(
                    params=item["params"],
                    metrics={},
                    success=False,
                    error=item.get("error"),
                )

            results.append(result_item)

            if result_item.success and optimize_for in result_item.metrics:
                value = result_item.metrics[optimize_for]
                is_better = (
                    (not minimize and value > best_value) or
                    (minimize and value < best_value)
                )
                if is_better:
                    best_value = value
                    best_params = result_item.params.copy()
                    best_metrics = result_item.metrics.copy()

        total_time = time.time() - start_time

        sweep_results = SweepResults(
            items=results,
            best_params=best_params,
            best_metrics=best_metrics,
            total_time=total_time,
            n_completed=parallel_result.n_completed,
            n_failed=parallel_result.n_failed,
            resource_stats={
                "memory_peak_gb": parallel_result.memory_peak_gb,
                "avg_time_per_task": parallel_result.avg_time_per_task,
            }
        )

        # Sauvegarde automatique si activée
        if self.auto_save:
            try:
                from backtest.storage import get_storage
                storage = get_storage()
                sweep_id = storage.save_sweep_results(sweep_results)
                logger.info(f"✅ Sweep parallèle sauvegardé: {sweep_id}")
            except Exception as e:
                logger.warning(f"⚠️ Sauvegarde automatique échouée: {e}")

        return sweep_results

    def request_stop(self):
        """Demande l'arrêt du sweep en cours."""
        self._stop_requested = True
        self._runner.request_stop()
        logger.info("Arrêt du sweep demandé")

    def is_stopped(self) -> bool:
        """Vérifie si un arrêt a été demandé."""
        return self._stop_requested

    def _get_strategy_by_name(self, name: str) -> "StrategyBase":
        """Récupère une stratégie par son nom."""
        from strategies import get_strategy, list_strategies

        available = list_strategies()
        name_lower = name.lower().replace("-", "_").replace(" ", "_")

        if name_lower not in available:
            raise ValueError(f"Stratégie inconnue: {name}. Disponibles: {available}")

        return get_strategy(name_lower)()


# ======================== Fonctions utilitaires ========================

def quick_sweep(
    df: pd.DataFrame,
    strategy: Union["StrategyBase", str],
    param_grid: Dict[str, Any],
    optimize_for: str = "sharpe_ratio",
    max_workers: int = 4,
) -> SweepResults:
    """
    Fonction raccourcie pour un sweep rapide.

    Args:
        df: DataFrame OHLCV
        strategy: Stratégie à tester
        param_grid: Grille de paramètres
        optimize_for: Métrique cible
        max_workers: Nombre de workers

    Returns:
        SweepResults

    Example:
        >>> results = quick_sweep(
        ...     df=data,
        ...     strategy="bollinger_atr",
        ...     param_grid={"entry_z": [1.5, 2.0, 2.5]},
        ... )
    """
    engine = SweepEngine(max_workers=max_workers)
    return engine.run_sweep(
        df=df,
        strategy=strategy,
        param_grid=param_grid,
        optimize_for=optimize_for,
        show_progress=True,
    )


# Docstring update summary
# - Docstring de module normalisée (LLM-friendly) centrée sur grid search parallélisé
# - Conventions génération/contraintes/tri explicitées
# - Read-if/Skip-if ajoutés pour orienter le tri
