"""
Module-ID: performance.parallel

Purpose: Parallélisation backtests - ProcessPoolExecutor/ThreadPoolExecutor + joblib.

Role in pipeline: performance optimization

Key components: ParallelRunner, parallel_sweep(), job chunking, progress tracking

Inputs: Function callable, param_grid, n_jobs (CPU count)

Outputs: List[results], timing stats, failure tracking

Dependencies: concurrent.futures, joblib (optionnel), numpy, pandas

Conventions: n_jobs=-1 (all CPUs); timeout protection; error aggregation.

Read-if: Modification parallelization strategy ou max_workers.

Skip-if: Vous appelez parallel_sweep(func, param_grid).
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import (
    FIRST_COMPLETED,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    as_completed,
    wait,
)
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional

import numpy as np
import pandas as pd

# Joblib pour parallélisation simple (optionnel)
try:
    from joblib import Parallel, delayed
    HAS_JOBLIB = True
except ImportError:
    HAS_JOBLIB = False

# psutil pour monitoring ressources (optionnel)
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logger = logging.getLogger(__name__)

# Shared worker state to avoid pickling large fixed kwargs per task.
_WORKER_FUNC: Optional[Callable[..., Any]] = None
_WORKER_KWARGS: Dict[str, Any] = {}


def _init_shared_worker(func: Callable[..., Any], fixed_kwargs: Dict[str, Any]) -> None:
    """Initialise un worker avec une fonction + kwargs partagés."""
    global _WORKER_FUNC, _WORKER_KWARGS
    _WORKER_FUNC = func
    _WORKER_KWARGS = fixed_kwargs


def _run_with_shared_kwargs(params: Dict[str, Any]) -> Any:
    """Exécute la fonction partagée avec les kwargs stockés en worker."""
    if _WORKER_FUNC is None:
        raise RuntimeError("Worker non initialisé (fonction manquante)")
    return _WORKER_FUNC(params, **_WORKER_KWARGS)


@dataclass
class ParallelConfig:
    """Configuration pour l'exécution parallèle."""
    max_workers: int = -1  # -1 = auto (nb CPU avec GPU multiplier)
    use_processes: bool = True  # True=multiprocessing, False=threading
    backend: str = "loky"  # Backend joblib: 'loky' (défaut, optimal), 'multiprocessing', 'threading'
    chunk_size: int = 10  # Taille des batches
    timeout: Optional[float] = None  # Timeout par tâche (secondes)
    memory_limit_gb: Optional[float] = None  # Limite mémoire
    max_in_flight: Optional[int] = None  # Nombre max de tâches en vol
    share_fixed_kwargs: bool = True  # Partager kwargs fixes via initializer
    continue_on_timeout: bool = False  # Continuer après un timeout

    # 🚀 NOUVEAUX PARAMÈTRES MULTI-GPU
    gpu_enabled: bool = True  # Activer optimisations GPU
    gpu_count: int = 2  # Nombre de GPUs disponibles
    gpu_memory_per_worker_mb: int = 2048  # Mémoire GPU par worker (MB)


@dataclass
class SweepResult:
    """Résultat d'un sweep parallèle."""
    results: List[Dict[str, Any]]
    total_time: float
    n_completed: int
    n_failed: int
    avg_time_per_task: float
    memory_peak_gb: Optional[float] = None


def _get_cpu_count() -> int:
    """
    Retourne le nombre de CPUs optimisé pour setup CPU-only haute performance.

    🚀 OPTIMISÉ POUR RYZEN 9950X (32 threads) + DDR5 60GB:
    - Mode CPU-only: multiplier 2.0-2.5x pour saturer tous les threads
    - Utilise les cores logiques (SMT) pour maximiser le throughput
    - Variables d'environnement pour tuning fin
    """
    if HAS_PSUTIL:
        # Utiliser les cores LOGIQUES (avec SMT/Hyperthreading)
        logical_cores = psutil.cpu_count(logical=True) or os.cpu_count() or 4
        physical_cores = psutil.cpu_count(logical=False) or logical_cores

        # Override explicite (prioritaire) via BACKTEST_MAX_WORKERS
        env_override = os.environ.get("BACKTEST_MAX_WORKERS")
        if env_override:
            try:
                override = int(float(env_override))
            except (TypeError, ValueError):
                override = None
            if override and override > 0:
                max_workers = min(override, logical_cores)
                logger.debug(
                    "CPU Config override: BACKTEST_MAX_WORKERS=%s -> %s workers",
                    env_override,
                    max_workers,
                )
                return max(1, max_workers)

        # 🚀 OPTIMISATION CPU-ONLY: 2.5x pour saturer les 32 threads (Ryzen 9950X)
        # Configurable via BACKTEST_CPU_MULTIPLIER (défaut: 2.0 pour stabilité)
        cpu_multiplier = float(os.environ.get("BACKTEST_CPU_MULTIPLIER", "2.0"))

        # Calculer workers optimaux basé sur cores logiques
        optimized_count = int(physical_cores * cpu_multiplier)

        # Limiter aux cores logiques disponibles pour éviter oversubscription
        max_workers = min(optimized_count, logical_cores)

        logger.debug(
            f"CPU Config: {physical_cores} physical, {logical_cores} logical, "
            f"multiplier={cpu_multiplier}x -> {max_workers} workers"
        )

        return max(physical_cores, max_workers)
    # Fallback sans psutil
    env_override = os.environ.get("BACKTEST_MAX_WORKERS")
    if env_override:
        try:
            override = int(float(env_override))
        except (TypeError, ValueError):
            override = None
        if override and override > 0:
            return max(1, min(override, os.cpu_count() or override))
    return os.cpu_count() or 4


def _get_available_memory_gb() -> float:
    """Retourne la mémoire disponible en GB."""
    if HAS_PSUTIL:
        try:
            return psutil.virtual_memory().available / (1024 ** 3)
        except Exception:
            pass
    return 8.0  # Valeur par défaut


def get_recommended_chunk_size(default: int = 100, total_tasks: Optional[int] = None) -> int:
    """
    Retourne une taille de chunk adaptée à la RAM disponible.

    La logique existait déjà dans ParallelRunner, mais n'était pas facilement
    réutilisable par les autres couches.
    """
    available_gb = _get_available_memory_gb()

    if available_gb >= 32:
        chunk_size = max(default, 200)
    elif available_gb >= 16:
        chunk_size = max(default, 100)
    else:
        chunk_size = default

    if total_tasks is not None:
        chunk_size = max(1, min(chunk_size, total_tasks))

    return chunk_size


def get_recommended_worker_count(max_cap: Optional[int] = None) -> int:
    """
    Retourne un nombre de workers cohérent avec CPU + RAM disponible.
    """
    cpu_count = _get_cpu_count()
    available_ram = _get_available_memory_gb()

    ram_per_worker = 0.3 if available_ram >= 32 else 0.5
    ram_limited_workers = max(1, int(available_ram / ram_per_worker))
    optimal = max(1, min(cpu_count, ram_limited_workers))

    if max_cap is not None:
        optimal = min(optimal, max_cap)

    return max(1, optimal)


def get_recommended_max_in_flight(
    total_tasks: int,
    worker_count: int,
    memory_limit_gb: Optional[float] = None,
) -> int:
    """
    Retourne un nombre de tâches en vol adapté à la mémoire disponible.

    Le système avait déjà des heuristiques workers/chunks, mais le pool manuel UI
    et certains chemins fallback restaient figés sur des multiplicateurs constants.
    """
    if total_tasks <= 0:
        return 0

    available_gb = memory_limit_gb if memory_limit_gb is not None else _get_available_memory_gb()

    if available_gb >= 32:
        tasks_per_worker = 8
    elif available_gb >= 16:
        tasks_per_worker = 6
    elif available_gb >= 8:
        tasks_per_worker = 4
    else:
        tasks_per_worker = 2

    recommended = max(1, worker_count * tasks_per_worker)
    return min(recommended, total_tasks)


def get_recommended_joblib_batch_size(total_tasks: int, default_chunk_size: int = 100) -> int:
    """
    Retourne une taille de batch joblib alignée sur les chunks adaptatifs.
    """
    if total_tasks <= 0:
        return 1

    chunk_size = get_recommended_chunk_size(default=default_chunk_size, total_tasks=total_tasks)
    min_feedback_batches = 10
    feedback_bound = max(10, total_tasks // min_feedback_batches)
    return max(1, min(chunk_size, feedback_bound, total_tasks))


def generate_param_grid(param_ranges: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Génère toutes les combinaisons de paramètres.

    Args:
        param_ranges: Dict avec {param_name: [values]} ou {param_name: value}

    Returns:
        Liste de dicts, chaque dict étant une combinaison de paramètres

    Example:
        >>> grid = generate_param_grid({
        ...     "period": [10, 20, 30],
        ...     "threshold": [0.5, 1.0],
        ...     "leverage": 1  # Valeur fixe
        ... })
        >>> len(grid)  # 3 * 2 = 6 combinaisons
        6
    """
    import itertools

    # Normaliser: convertir valeurs scalaires en listes
    normalized = {}
    for key, value in param_ranges.items():
        if isinstance(value, (list, tuple, np.ndarray)):
            normalized[key] = list(value)
        else:
            normalized[key] = [value]

    # Générer le produit cartésien
    keys = list(normalized.keys())
    values = list(normalized.values())

    combinations = []
    for combo in itertools.product(*values):
        combinations.append(dict(zip(keys, combo)))

    return combinations


def parallel_sweep(
    func: Callable,
    param_grid: List[Dict[str, Any]],
    n_jobs: int = -1,
    backend: str = "loky",
    verbose: int = 0,
    **fixed_kwargs
) -> List[Any]:
    """
    Exécute une fonction sur une grille de paramètres en parallèle.

    Utilise joblib si disponible, sinon ProcessPoolExecutor.

    Args:
        func: Fonction à appeler, signature: func(params, **fixed_kwargs)
        param_grid: Liste de dicts de paramètres
        n_jobs: Nombre de workers (-1 = tous les CPUs)
        backend: Backend joblib ('loky', 'multiprocessing', 'threading')
        verbose: Niveau de verbosité (0-10)
        **fixed_kwargs: Arguments fixes passés à chaque appel

    Returns:
        Liste des résultats dans le même ordre que param_grid

    Example:
        >>> def run_backtest(params, data=None):
        ...     return {"params": params, "sharpe": 1.5}
        >>>
        >>> grid = [{"period": 10}, {"period": 20}]
        >>> results = parallel_sweep(run_backtest, grid, data=df)
    """
    if n_jobs == -1:
        n_jobs = _get_cpu_count()

    if HAS_JOBLIB:
        # Utiliser joblib (plus robuste et optimisé)
        results = Parallel(n_jobs=n_jobs, backend=backend, verbose=verbose)(
            delayed(func)(params, **fixed_kwargs) for params in param_grid
        )
        return results
    else:
        # Fallback sur concurrent.futures
        logger.info("joblib non disponible, utilisation de ProcessPoolExecutor")
        results = [None] * len(param_grid)

        with ProcessPoolExecutor(max_workers=n_jobs) as executor:
            futures = {
                executor.submit(func, params, **fixed_kwargs): i
                for i, params in enumerate(param_grid)
            }

            for future in as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    logger.error(f"Erreur tâche {idx}: {e}")
                    results[idx] = {"error": str(e)}

        return results


class ParallelRunner:
    """
    Gestionnaire de backtests parallèles avec monitoring et optimisation.

    Supporte:
    - Exécution multi-processus ou multi-thread
    - Chunking automatique pour gestion mémoire
    - Monitoring CPU/RAM en temps réel
    - Arrêt anticipé sur critère

    Example:
        >>> runner = ParallelRunner(max_workers=8)
        >>>
        >>> param_grid = generate_param_grid({
        ...     "bb_period": range(15, 35, 5),
        ...     "atr_mult": [1.5, 2.0, 2.5]
        ... })
        >>>
        >>> results = runner.run_sweep(
        ...     strategy=my_strategy,
        ...     data=df,
        ...     param_grid=param_grid
        ... )
    """

    def __init__(
        self,
        max_workers: Optional[int] = None,
        use_processes: bool = True,
        backend: str = "loky",
        chunk_size: int = 100,  # 🚀 Augmenté de 50 à 100 pour DDR5
        memory_limit_gb: Optional[float] = None,
        max_in_flight: Optional[int] = None,
        share_fixed_kwargs: bool = True,
        task_timeout: Optional[float] = None,
        continue_on_timeout: bool = False,
    ):
        """
        Initialise le runner parallèle.

        🚀 OPTIMISÉ POUR RYZEN 9950X + DDR5 60GB:
        - chunk_size=100 (vs 50) pour réduire overhead
        - max_workers auto = 32 threads
        - backend loky pour shared memory

        Args:
            max_workers: Nombre de workers (None = auto)
            use_processes: True=multiprocessing, False=threading
            backend: Backend joblib ('loky', 'multiprocessing', 'threading'). Défaut='loky' (optimal)
            chunk_size: Taille des batches (100-200 recommandé pour DDR5)
            memory_limit_gb: Limite mémoire (None = pas de limite)
            max_in_flight: Limite de tâches simultanées soumises (None = auto)
            share_fixed_kwargs: Partager les kwargs fixes via initializer (processes)
            task_timeout: Timeout par tâche (secondes)
            continue_on_timeout: Continuer après timeout (sinon arrêt)
        """
        self.max_workers = max_workers or self._calculate_optimal_workers()
        self.use_processes = use_processes
        self.backend = backend
        # 🚀 Chunk size adaptatif selon RAM disponible
        self.chunk_size = self._optimize_chunk_size(chunk_size)
        self.memory_limit_gb = memory_limit_gb
        self.max_in_flight = max_in_flight
        self.share_fixed_kwargs = share_fixed_kwargs
        self.task_timeout = task_timeout
        self.continue_on_timeout = continue_on_timeout

        # État
        self._stop_requested = False
        self._current_progress = 0
        self._total_tasks = 0

        # Callbacks
        self._progress_callback: Optional[Callable[[int, int], None]] = None

        # Déterminer si on peut utiliser joblib
        self._use_joblib = HAS_JOBLIB and backend in ("loky", "multiprocessing", "threading")

        logger.info(
            f"ParallelRunner initialisé: {self.max_workers} workers, "
            f"backend={'joblib-' + backend if self._use_joblib else ('processes' if use_processes else 'threads')}, "
            f"chunk_size={self.chunk_size}, max_in_flight={self.max_in_flight or 'auto'}"
        )

    def _optimize_chunk_size(self, default: int) -> int:
        """
        Optimise la taille des chunks selon la RAM disponible.

        🚀 DDR5 60GB: chunks plus gros pour réduire l'overhead
        """
        return get_recommended_chunk_size(default=default)

    def _calculate_optimal_workers(self) -> int:
        """Calcule le nombre optimal de workers."""
        return get_recommended_worker_count()

    def set_progress_callback(self, callback: Callable[[int, int], None]):
        """Définit un callback de progression: callback(completed, total)."""
        self._progress_callback = callback

    def request_stop(self):
        """Demande l'arrêt du sweep en cours."""
        self._stop_requested = True
        logger.info("Arrêt demandé pour le sweep en cours")

    def _chunk_grid(self, param_grid: List[Dict]) -> Iterator[List[Dict]]:
        """Divise la grille en chunks pour gestion mémoire."""
        for i in range(0, len(param_grid), self.chunk_size):
            yield param_grid[i:i + self.chunk_size]

    def run_sweep(
        self,
        run_func: Callable,
        param_grid: List[Dict[str, Any]],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        **fixed_kwargs
    ) -> SweepResult:
        """
        Exécute un sweep parallèle complet (OPTIMISÉ avec joblib/loky par défaut).

        Args:
            run_func: Fonction de backtest, signature: run_func(params, **kwargs)
            param_grid: Liste des combinaisons de paramètres
            progress_callback: Callback optionnel (completed, total)
            **fixed_kwargs: Arguments fixes (data, etc.)

        Returns:
            SweepResult avec tous les résultats et métriques
        """
        self._stop_requested = False
        self._total_tasks = len(param_grid)
        self._current_progress = 0

        if progress_callback:
            self._progress_callback = progress_callback

        logger.info(
            f"Démarrage sweep: {self._total_tasks} tâches, "
            f"{self.max_workers} workers, backend={self.backend if self._use_joblib else 'executor'}"
        )

        if self._total_tasks == 0:
            return SweepResult(
                results=[],
                total_time=0.0,
                n_completed=0,
                n_failed=0,
                avg_time_per_task=0.0,
                memory_peak_gb=None,
            )

        # 🚀 PRIORITÉ: Utiliser joblib avec backend loky si disponible (meilleure gestion mémoire)
        if self._use_joblib:
            return self._run_sweep_joblib(run_func, param_grid, **fixed_kwargs)
        else:
            return self._run_sweep_executor(run_func, param_grid, **fixed_kwargs)

    def _run_sweep_joblib(
        self,
        run_func: Callable,
        param_grid: List[Dict[str, Any]],
        **fixed_kwargs
    ) -> SweepResult:
        """
        Exécution du sweep via joblib (loky/multiprocessing/threading).

        Avantages:
        - Pas de pickling répétitif du DataFrame (shared memory automatique avec loky)
        - Meilleure gestion des ressources
        - Plus stable pour gros volumes
        """
        start_time = time.time()
        all_results = []
        n_failed = 0
        memory_peak = 0.0

        logger.info(f"Utilisation de joblib backend={self.backend}")

        # Wrapper pour capturer les erreurs et faire le suivi de progression
        def _safe_run_with_progress(idx: int, params: Dict[str, Any]) -> Dict[str, Any]:
            try:
                result = run_func(params, **fixed_kwargs)
                return {
                    "idx": idx,
                    "params": params,
                    "result": result,
                    "success": True,
                }
            except Exception as e:
                logger.error(f"Erreur tâche {idx}: {e}")
                return {
                    "idx": idx,
                    "params": params,
                    "error": str(e),
                    "success": False,
                }

        # Exécution parallèle avec joblib en mode batch pour feedback temps réel
        try:
            # verbose=0 pour pas de sortie, 10+ pour debug
            verbose_level = int(os.environ.get("JOBLIB_VERBOSE", "0"))

            # Réutiliser la logique de chunk_size adaptatif au lieu d'un second
            # système hardcodé 50/100.
            batch_size = get_recommended_joblib_batch_size(
                total_tasks=self._total_tasks,
                default_chunk_size=self.chunk_size,
            )

            logger.info(f"Joblib mode batch: {self._total_tasks} tâches, batch_size={batch_size}")

            # Tracking temps pour logs périodiques
            last_log_time = start_time
            batch_count = 0

            # Traiter par batch pour avoir des callbacks en temps réel
            for batch_start in range(0, self._total_tasks, batch_size):
                batch_end = min(batch_start + batch_size, self._total_tasks)
                batch_params = param_grid[batch_start:batch_end]

                # 🚀 OPTIMISATION DDR5: max_nbytes élevé pour éviter le memory mapping inutile
                # DDR5 @ 50GB/s -> copies en RAM ultra-rapides
                max_nbytes = os.environ.get("JOBLIB_MAX_NBYTES", "500M")

                # Exécuter un batch avec configuration optimisée DDR5
                batch_results = Parallel(
                    n_jobs=self.max_workers,
                    backend=self.backend,
                    verbose=verbose_level,
                    max_nbytes=max_nbytes,  # 🚀 DDR5: copies directes en RAM
                    batch_size="auto",  # Laisser joblib optimiser
                )(
                    delayed(_safe_run_with_progress)(batch_start + i, params)
                    for i, params in enumerate(batch_params)
                )

                # Trier ce batch par index
                batch_results.sort(key=lambda x: x["idx"])

                # Traiter résultats de ce batch immédiatement pour callbacks
                for r in batch_results:
                    if r["success"]:
                        all_results.append({
                            "params": r["params"],
                            "result": r["result"],
                            "success": True,
                        })
                    else:
                        all_results.append({
                            "params": r["params"],
                            "error": r.get("error", "Unknown error"),
                            "success": False,
                        })
                        n_failed += 1

                    # Callback de progression PENDANT l'exécution
                    self._current_progress += 1
                    if self._progress_callback:
                        self._progress_callback(self._current_progress, self._total_tasks)

                # Logs périodiques pour feedback (toutes les 5 batches ou 30s)
                batch_count += 1
                current_time = time.time()
                if batch_count % 5 == 0 or (current_time - last_log_time) >= 30.0:
                    elapsed = current_time - start_time
                    speed = self._current_progress / elapsed if elapsed > 0 else 0
                    logger.info(
                        f"Joblib progress: {self._current_progress}/{self._total_tasks} "
                        f"({self._current_progress/self._total_tasks*100:.1f}%) • "
                        f"{speed:.1f} tasks/s • batch {batch_count}"
                    )
                    last_log_time = current_time

                # Tracking mémoire à chaque batch
                if HAS_PSUTIL:
                    current_mem = psutil.virtual_memory().used / (1024 ** 3)
                    memory_peak = max(memory_peak, current_mem)

        except Exception as e:
            logger.error(f"Erreur fatale joblib: {e}")
            # Fallback sur executor
            logger.info("Repli sur ProcessPoolExecutor")
            return self._run_sweep_executor(run_func, param_grid, **fixed_kwargs)

        elapsed = time.time() - start_time
        n_completed = len([r for r in all_results if r.get("success")])

        logger.info(
            f"✅ Sweep joblib terminé: {n_completed}/{self._total_tasks} en {elapsed:.1f}s "
            f"({n_completed/elapsed:.1f} tâches/s)"
        )

        return SweepResult(
            results=all_results,
            total_time=elapsed,
            n_completed=n_completed,
            n_failed=n_failed,
            avg_time_per_task=elapsed / self._total_tasks if self._total_tasks else 0.0,
            memory_peak_gb=memory_peak if memory_peak > 0 else None,
        )

    def _run_sweep_executor(
        self,
        run_func: Callable,
        param_grid: List[Dict[str, Any]],
        **fixed_kwargs
    ) -> SweepResult:
        """
        Exécution du sweep via ProcessPoolExecutor/ThreadPoolExecutor (fallback).
        """
        start_time = time.time()
        all_results = []
        n_failed = 0
        memory_peak = 0.0

        # Choisir l'executor
        ExecutorClass = ProcessPoolExecutor if self.use_processes else ThreadPoolExecutor

        max_in_flight = self.max_in_flight
        if max_in_flight is None:
            max_in_flight = get_recommended_max_in_flight(
                total_tasks=self._total_tasks,
                worker_count=self.max_workers,
                memory_limit_gb=self.memory_limit_gb,
            )
        max_in_flight = min(max_in_flight, self._total_tasks)

        fixed_kwargs = dict(fixed_kwargs)
        use_shared_kwargs = (
            self.use_processes and self.share_fixed_kwargs and bool(fixed_kwargs)
        )

        executor_kwargs: Dict[str, Any] = {}
        submit_func = run_func
        submit_kwargs = fixed_kwargs
        if use_shared_kwargs:
            executor_kwargs = {
                "initializer": _init_shared_worker,
                "initargs": (run_func, fixed_kwargs),
            }
            submit_func = _run_with_shared_kwargs
            submit_kwargs = {}

        # ✅ Executor unique + limite de tâches en vol pour éviter l'overhead mémoire
        with ExecutorClass(max_workers=self.max_workers, **executor_kwargs) as executor:
            pending = {}
            submitted_at: Dict[Any, float] = {}
            param_iter = iter(param_grid)

            def submit_next() -> bool:
                try:
                    params = next(param_iter)
                except StopIteration:
                    return False
                future = executor.submit(submit_func, params, **submit_kwargs)
                pending[future] = params
                submitted_at[future] = time.time()
                return True

            for _ in range(max_in_flight):
                if not submit_next():
                    break

            while pending:
                if self._stop_requested:
                    logger.info("Sweep arrêté par demande utilisateur")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                done, _ = wait(
                    pending,
                    timeout=0.2,
                    return_when=FIRST_COMPLETED,
                )

                if not done:
                    # Timeout par tâche si configuré
                    if self.task_timeout is not None:
                        now = time.time()
                        timed_out = [
                            fut for fut, started in submitted_at.items()
                            if now - started > self.task_timeout
                        ]
                        for fut in timed_out:
                            params = pending.pop(fut, None)
                            submitted_at.pop(fut, None)
                            if params is None:
                                continue
                            fut.cancel()
                            all_results.append({
                                "params": params,
                                "error": f"timeout > {self.task_timeout}s",
                                "success": False,
                            })
                            n_failed += 1
                            self._current_progress += 1
                            if self._progress_callback:
                                self._progress_callback(self._current_progress, self._total_tasks)
                            if not self.continue_on_timeout:
                                self._stop_requested = True
                                break
                            if not self._stop_requested:
                                submit_next()
                    continue

                for future in done:
                    params = pending.pop(future)
                    submitted_at.pop(future, None)
                    try:
                        result = future.result()
                        all_results.append({
                            "params": params,
                            "result": result,
                            "success": True,
                        })
                    except Exception as e:
                        logger.error(f"Erreur: {params} -> {e}")
                        all_results.append({
                            "params": params,
                            "error": str(e),
                            "success": False,
                        })
                        n_failed += 1

                    self._current_progress += 1
                    if self._progress_callback:
                        self._progress_callback(self._current_progress, self._total_tasks)

                    # Tracking mémoire périodique (tous les 10 résultats pour éviter overhead)
                    if HAS_PSUTIL and self._current_progress % 10 == 0:
                        current_mem = psutil.virtual_memory().used / (1024 ** 3)
                        memory_peak = max(memory_peak, current_mem)

                        # Vérifier limite mémoire
                        if self.memory_limit_gb and current_mem > self.memory_limit_gb:
                            logger.warning(f"Limite mémoire atteinte: {current_mem:.1f} GB")
                            executor.shutdown(wait=False, cancel_futures=True)
                            self._stop_requested = True
                            break

                    if not self._stop_requested:
                        submit_next()

        elapsed = time.time() - start_time
        n_completed = len([r for r in all_results if r.get("success")])

        logger.info(
            f"✅ Sweep terminé: {n_completed}/{self._total_tasks} en {elapsed:.1f}s "
            f"({n_completed/elapsed:.1f} tâches/s)"
        )

        return SweepResult(
            results=all_results,
            total_time=elapsed,
            n_completed=n_completed,
            n_failed=n_failed,
            avg_time_per_task=elapsed / max(1, len(all_results)),
            memory_peak_gb=memory_peak if memory_peak > 0 else None
        )


def run_backtest_worker(
    params: Dict[str, Any],
    strategy_class: type,
    data: pd.DataFrame,
    indicators: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Worker function pour exécuter un backtest (picklable).

    Args:
        params: Paramètres de la stratégie
        strategy_class: Classe de stratégie à instancier
        data: DataFrame OHLCV
        indicators: Indicateurs précalculés

    Returns:
        Dict avec params et métriques de performance
    """
    try:
        strategy = strategy_class()
        result = strategy.run(data, indicators, params)

        # Calculer métriques simples
        signals = result.signals
        n_trades = int(np.sum(signals != 0))

        return {
            "params": params,
            "n_trades": n_trades,
            "success": True
        }
    except Exception as e:
        return {
            "params": params,
            "error": str(e),
            "success": False
        }


# ======================== Utilitaires de benchmark ========================

def benchmark_parallel_configs(
    func: Callable,
    sample_params: List[Dict],
    configs: Optional[List[ParallelConfig]] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Benchmark différentes configurations parallèles.

    Args:
        func: Fonction à tester
        sample_params: Échantillon de paramètres
        configs: Liste de configurations à tester (None = auto)
        **kwargs: Arguments fixes pour func

    Returns:
        Dict avec meilleure config et résultats de benchmark
    """
    if configs is None:
        cpu_count = _get_cpu_count()
        configs = [
            ParallelConfig(max_workers=cpu_count // 2, use_processes=True),
            ParallelConfig(max_workers=cpu_count, use_processes=True),
            ParallelConfig(max_workers=cpu_count * 2, use_processes=True),
            ParallelConfig(max_workers=cpu_count, use_processes=False),  # threading
        ]

    results = []

    for config in configs:
        runner = ParallelRunner(
            max_workers=config.max_workers,
            use_processes=config.use_processes,
            backend=getattr(config, "backend", "loky"),  # Utilise backend de config ou loky par défaut
            chunk_size=config.chunk_size,
            memory_limit_gb=config.memory_limit_gb,
            max_in_flight=config.max_in_flight,
            share_fixed_kwargs=config.share_fixed_kwargs,
            task_timeout=config.timeout,
            continue_on_timeout=config.continue_on_timeout,
        )

        start = time.time()
        runner.run_sweep(func, sample_params[:min(20, len(sample_params))], **kwargs)
        elapsed = time.time() - start

        results.append({
            "config": config,
            "elapsed": elapsed,
            "throughput": len(sample_params) / elapsed if elapsed > 0 else 0
        })

        logger.info(
            f"Config: {config.max_workers} workers, "
            f"{'process' if config.use_processes else 'thread'} -> "
            f"{elapsed:.2f}s ({results[-1]['throughput']:.1f} tâches/s)"
        )

    # Trouver la meilleure config
    best = max(results, key=lambda x: x["throughput"])

    return {
        "best_config": best["config"],
        "best_throughput": best["throughput"],
        "all_results": results
    }
