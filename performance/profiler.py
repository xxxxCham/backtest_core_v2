"""
Module-ID: performance.profiler

Purpose: Profiling cProfile/line_profiler - identifie goulots d'étranglement (CPU, ligne).

Role in pipeline: performance optimization

Key components: Profiler, ProfileStats, @profile_function decorator, save_report()

Inputs: Function/code block à profiler

Outputs: Stats {duration_ms, top_functions[], line_stats}, text report

Dependencies: cProfile, pstats, functools, time, pathlib

Conventions: Context manager support; CSV export; @profile decorator.

Read-if: Modification profiling strategy ou report format.

Skip-if: Vous appelez Profiler.start() → stop() → print_stats().
"""

from __future__ import annotations

import cProfile
import functools
import io
import logging
import os
import pstats
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar

logger = logging.getLogger(__name__)

# line_profiler (optionnel)
try:
    from line_profiler import LineProfiler
    HAS_LINE_PROFILER = True
except ImportError:
    HAS_LINE_PROFILER = False

# memory_profiler (optionnel)
try:
    from memory_profiler import memory_usage
    HAS_MEMORY_PROFILER = True
except ImportError:
    HAS_MEMORY_PROFILER = False

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class ProfileResult:
    """Résultat d'un profiling."""
    name: str
    total_time: float
    n_calls: int
    top_functions: List[Dict[str, Any]]
    memory_peak_mb: Optional[float] = None


class Profiler:
    """
    Profiler flexible avec support cProfile et line_profiler.

    Example:
        >>> profiler = Profiler("backtest_run")
        >>> profiler.start()
        >>>
        >>> result = engine.run(...)
        >>>
        >>> profiler.stop()
        >>> profiler.print_stats(top_n=20)
        >>> profiler.save_report("profile_output.txt")
    """

    def __init__(self, name: str = "profile", output_dir: Optional[str] = None):
        """
        Initialise le profiler.

        Args:
            name: Nom du profil (pour fichiers de sortie)
            output_dir: Répertoire de sortie (None = répertoire courant)
        """
        self.name = name
        self.output_dir = Path(output_dir) if output_dir else Path(".")

        self._profiler: Optional[cProfile.Profile] = None
        self._stats: Optional[pstats.Stats] = None
        self._start_time: float = 0.0
        self._end_time: float = 0.0
        self._is_running = False

    def start(self):
        """Démarre le profiling."""
        if self._is_running:
            logger.warning("Profiler déjà en cours")
            return

        self._profiler = cProfile.Profile()
        self._profiler.enable()
        self._start_time = time.time()
        self._is_running = True

        logger.debug(f"Profiler '{self.name}' démarré")

    def stop(self) -> ProfileResult:
        """
        Arrête le profiling et retourne les résultats.

        Returns:
            ProfileResult avec les statistiques
        """
        if not self._is_running:
            logger.warning("Profiler non démarré")
            return ProfileResult(
                name=self.name,
                total_time=0.0,
                n_calls=0,
                top_functions=[],
            )

        self._end_time = time.time()
        self._profiler.disable()
        self._is_running = False

        # Créer les stats
        stream = io.StringIO()
        self._stats = pstats.Stats(self._profiler, stream=stream)

        # Extraire les top fonctions
        self._stats.sort_stats("cumulative")

        top_functions = []
        for func, (cc, nc, tt, ct, callers) in list(self._stats.stats.items())[:20]:
            filename, lineno, name = func
            top_functions.append({
                "function": name,
                "file": filename,
                "line": lineno,
                "calls": nc,
                "total_time": tt,
                "cumulative_time": ct,
            })

        total_time = self._end_time - self._start_time
        n_calls = sum(s[1] for s in self._stats.stats.values())

        logger.debug(f"Profiler '{self.name}' arrêté: {total_time:.2f}s, {n_calls} appels")

        return ProfileResult(
            name=self.name,
            total_time=total_time,
            n_calls=n_calls,
            top_functions=top_functions,
        )

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
        return False

    def print_stats(self, top_n: int = 20, sort_by: str = "cumulative"):
        """
        Affiche les statistiques de profiling.

        Args:
            top_n: Nombre de fonctions à afficher
            sort_by: Critère de tri ('cumulative', 'time', 'calls')
        """
        if not self._stats:
            logger.warning("Pas de stats disponibles - avez-vous appelé stop()?")
            return

        print(f"\n{'='*60}")
        print(f"PROFILING REPORT: {self.name}")
        print(f"{'='*60}")
        print(f"Total time: {self._end_time - self._start_time:.3f}s")
        print(f"{'='*60}\n")

        self._stats.sort_stats(sort_by)
        self._stats.print_stats(top_n)

    def save_report(self, filename: Optional[str] = None):
        """
        Sauvegarde le rapport de profiling.

        Args:
            filename: Nom du fichier (None = auto-généré)
        """
        if not self._stats:
            logger.warning("Pas de stats disponibles")
            return

        if filename is None:
            filename = f"{self.name}_{int(time.time())}.prof"

        filepath = self.output_dir / filename

        # Sauvegarder le fichier binaire .prof
        if filepath.suffix == ".prof":
            self._profiler.dump_stats(str(filepath))
            logger.info(f"Profil binaire sauvé: {filepath}")

            # Aussi sauvegarder une version texte
            txt_path = filepath.with_suffix(".txt")
            with open(txt_path, "w") as f:
                stats = pstats.Stats(self._profiler, stream=f)
                stats.sort_stats("cumulative")
                stats.print_stats(50)
            logger.info(f"Rapport texte sauvé: {txt_path}")
        else:
            # Sauvegarder uniquement le texte
            with open(filepath, "w") as f:
                stats = pstats.Stats(self._profiler, stream=f)
                stats.sort_stats("cumulative")
                stats.print_stats(50)
            logger.info(f"Rapport sauvé: {filepath}")

    def get_slowest_functions(self, n: int = 10) -> List[Dict[str, Any]]:
        """
        Retourne les N fonctions les plus lentes.

        Args:
            n: Nombre de fonctions

        Returns:
            Liste de dicts avec infos sur chaque fonction
        """
        if not self._stats:
            return []

        self._stats.sort_stats("cumulative")

        slowest = []
        for func, (cc, nc, tt, ct, callers) in list(self._stats.stats.items())[:n]:
            filename, lineno, name = func
            slowest.append({
                "function": name,
                "file": os.path.basename(filename),
                "line": lineno,
                "calls": nc,
                "total_time_ms": tt * 1000,
                "cumulative_time_ms": ct * 1000,
                "time_per_call_ms": (ct / nc * 1000) if nc > 0 else 0,
            })

        return slowest


def profile_function(func: F) -> F:
    """
    Décorateur pour profiler une fonction.

    Affiche les statistiques de temps après chaque appel.

    Example:
        >>> @profile_function
        >>> def slow_function():
        ...     time.sleep(1)
        ...     return 42
        >>>
        >>> result = slow_function()
        # Affiche: slow_function executed in 1.001s
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        profiler = cProfile.Profile()
        profiler.enable()

        start = time.time()
        try:
            result = func(*args, **kwargs)
        finally:
            profiler.disable()
            elapsed = time.time() - start

            # Afficher un résumé
            stats = pstats.Stats(profiler)
            stats.sort_stats("cumulative")

            print(f"\n⏱️  {func.__name__} executed in {elapsed:.3f}s")
            print("   Top 5 internal calls:")

            for i, (key, val) in enumerate(list(stats.stats.items())[:5]):
                filename, lineno, name = key
                _, nc, tt, ct, _ = val
                print(f"   {i+1}. {name}: {ct*1000:.1f}ms ({nc} calls)")

        return result

    return wrapper  # type: ignore


def profile_memory(func: F) -> F:
    """
    Décorateur pour profiler la mémoire d'une fonction.

    Nécessite memory_profiler installé.

    Example:
        >>> @profile_memory
        >>> def memory_hungry():
        ...     data = [i for i in range(1000000)]
        ...     return len(data)
    """
    if not HAS_MEMORY_PROFILER:
        logger.warning("memory_profiler non disponible - décorateur ignoré")
        return func

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Mesurer usage mémoire
        mem_before = memory_usage(-1, interval=0.1, timeout=1)[0]

        result = func(*args, **kwargs)

        mem_after = memory_usage(-1, interval=0.1, timeout=1)[0]
        mem_diff = mem_after - mem_before

        print(f"\n🧠 {func.__name__} memory:")
        print(f"   Before: {mem_before:.1f} MB")
        print(f"   After:  {mem_after:.1f} MB")
        print(f"   Delta:  {mem_diff:+.1f} MB")

        return result

    return wrapper  # type: ignore


class TimingContext:
    """
    Context manager simple pour mesurer le temps.

    Example:
        >>> with TimingContext("data_loading"):
        ...     df = pd.read_csv("large_file.csv")
        # Affiche: data_loading: 2.345s
    """

    def __init__(self, name: str, verbose: bool = True):
        self.name = name
        self.verbose = verbose
        self.elapsed: float = 0.0

    def __enter__(self):
        self._start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.elapsed = time.time() - self._start
        if self.verbose:
            print(f"⏱️  {self.name}: {self.elapsed:.3f}s")
        return False


class LineProfilerWrapper:
    """
    Wrapper pour line_profiler avec API simplifiée.

    Nécessite line_profiler installé.

    Example:
        >>> lp = LineProfilerWrapper()
        >>> lp.add_function(my_slow_function)
        >>>
        >>> lp.run(my_slow_function, arg1, arg2)
        >>> lp.print_stats()
    """

    def __init__(self):
        if not HAS_LINE_PROFILER:
            raise ImportError(
                "line_profiler non installé. "
                "Installez avec: pip install line_profiler"
            )

        self._profiler = LineProfiler()
        self._functions: List[Callable] = []

    def add_function(self, func: Callable):
        """Ajoute une fonction à profiler."""
        self._profiler.add_function(func)
        self._functions.append(func)

    def run(self, func: Callable, *args, **kwargs) -> Any:
        """
        Exécute une fonction avec profiling ligne par ligne.

        Args:
            func: Fonction à exécuter
            *args, **kwargs: Arguments de la fonction

        Returns:
            Résultat de la fonction
        """
        if func not in self._functions:
            self.add_function(func)

        return self._profiler.runcall(func, *args, **kwargs)

    def print_stats(self):
        """Affiche les statistiques ligne par ligne."""
        self._profiler.print_stats()

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques sous forme de dict."""
        stats = {}

        for func, timings in self._profiler.get_stats().timings.items():
            filename, start_line, name = func

            lines = []
            for lineno, nhits, time_ns in timings:
                lines.append({
                    "line": lineno,
                    "hits": nhits,
                    "time_us": time_ns / 1000,  # ns -> us
                })

            stats[name] = {
                "file": filename,
                "start_line": start_line,
                "lines": lines,
            }

        return stats


# ======================== Fonctions utilitaires ========================

def run_with_profiling(
    func: Callable,
    *args,
    output_file: Optional[str] = None,
    **kwargs
) -> Any:
    """
    Exécute une fonction avec profiling complet.

    Args:
        func: Fonction à profiler
        *args: Arguments positionnels
        output_file: Fichier de sortie optionnel
        **kwargs: Arguments nommés

    Returns:
        Résultat de la fonction
    """
    profiler = Profiler(func.__name__)
    profiler.start()

    try:
        result = func(*args, **kwargs)
    finally:
        profiler.stop()
        profiler.print_stats(top_n=15)

        if output_file:
            profiler.save_report(output_file)

    return result


def benchmark_function(
    func: Callable,
    *args,
    n_runs: int = 10,
    warmup: int = 2,
    **kwargs
) -> Dict[str, float]:
    """
    Benchmark une fonction avec statistiques.

    Args:
        func: Fonction à benchmarker
        *args: Arguments positionnels
        n_runs: Nombre d'exécutions
        warmup: Nombre d'exécutions de warmup
        **kwargs: Arguments nommés

    Returns:
        Dict avec min, max, mean, std des temps
    """
    import statistics

    # Warmup
    for _ in range(warmup):
        func(*args, **kwargs)

    # Benchmark
    times = []
    for _ in range(n_runs):
        start = time.time()
        func(*args, **kwargs)
        times.append(time.time() - start)

    return {
        "min_ms": min(times) * 1000,
        "max_ms": max(times) * 1000,
        "mean_ms": statistics.mean(times) * 1000,
        "std_ms": statistics.stdev(times) * 1000 if len(times) > 1 else 0,
        "n_runs": n_runs,
    }
