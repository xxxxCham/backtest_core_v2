"""
Module-ID: performance.benchmark

Purpose: Suite benchmarks - compare implémentations (vectorisé, Numba, GPU).

Role in pipeline: performance testing

Key components: Benchmark, BenchmarkResult, @timeit, run_suite(), compare()

Inputs: Callable function/method, test data, iterations

Outputs: BenchmarkResult {duration_ms, memory_mb, throughput_items/s}

Dependencies: time, numpy, pandas, dataclasses

Conventions: CSV export; statistical analysis (min/max/mean); outlier removal.

Read-if: Modification benchmark methodology ou metrics.

Skip-if: Vous appelez Benchmark().run() ou compare_functions().
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from utils.log import get_logger

logger = get_logger(__name__)


@dataclass
class BenchmarkResult:
    """Résultat d'un benchmark."""
    name: str
    duration_ms: float
    memory_mb: float
    throughput_items_per_sec: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"{self.name:30s} | "
            f"{self.duration_ms:8.2f} ms | "
            f"{self.memory_mb:7.1f} MB | "
            f"{self.throughput_items_per_sec:10,.0f} items/s"
        )


@dataclass
class BenchmarkComparison:
    """Comparaison de plusieurs benchmarks."""
    results: List[BenchmarkResult]
    baseline_name: Optional[str] = None

    def summary(self) -> str:
        """Génère un résumé comparatif."""
        if not self.results:
            return "Aucun résultat"

        # Trier par durée
        sorted_results = sorted(self.results, key=lambda r: r.duration_ms)
        baseline = self._get_baseline()

        lines = []
        lines.append("=" * 90)
        lines.append("BENCHMARK RESULTS")
        lines.append("=" * 90)
        lines.append(
            f"{'Name':<30} | {'Time (ms)':>8} | {'Memory':>7} | {'Throughput':>10} | {'Speedup':>8}"
        )
        lines.append("-" * 90)

        for result in sorted_results:
            speedup = baseline.duration_ms / result.duration_ms if baseline else 1.0
            speedup_str = f"{speedup:7.2f}x" if speedup != 1.0 else "baseline"
            lines.append(f"{result} | {speedup_str:>8}")

        lines.append("=" * 90)

        # Winner
        winner = sorted_results[0]
        if baseline and winner.name != baseline.name:
            improvement = (baseline.duration_ms - winner.duration_ms) / baseline.duration_ms * 100
            lines.append(f"\n🏆 Winner: {winner.name}")
            lines.append(f"   {improvement:.1f}% faster than baseline")

        return "\n".join(lines)

    def _get_baseline(self) -> Optional[BenchmarkResult]:
        """Retourne le résultat baseline."""
        if self.baseline_name:
            for result in self.results:
                if result.name == self.baseline_name:
                    return result
        return self.results[0] if self.results else None


@contextmanager
def timer():
    """Context manager pour mesurer le temps d'exécution."""
    start = time.perf_counter()
    yield lambda: (time.perf_counter() - start) * 1000  # ms


def get_memory_usage() -> float:
    """Retourne l'utilisation mémoire actuelle en MB."""
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / (1024 ** 2)
    except ImportError:
        return 0.0


def benchmark_function(
    func: Callable,
    *args,
    name: str = None,
    n_items: int = None,
    warmup_runs: int = 2,
    benchmark_runs: int = 5,
    **kwargs
) -> BenchmarkResult:
    """
    Benchmark une fonction.

    Args:
        func: Fonction à benchmarker
        *args: Arguments positionnels
        name: Nom du benchmark
        n_items: Nombre d'items traités (pour throughput)
        warmup_runs: Nombre de runs de warm-up
        benchmark_runs: Nombre de runs de benchmark
        **kwargs: Arguments nommés

    Returns:
        BenchmarkResult
    """
    func_name = name or func.__name__

    # Warm-up
    for _ in range(warmup_runs):
        func(*args, **kwargs)

    # Benchmark
    durations = []
    mem_before = get_memory_usage()

    for _ in range(benchmark_runs):
        with timer() as get_time:
            func(*args, **kwargs)
        durations.append(get_time())

    mem_after = get_memory_usage()

    # Stats
    avg_duration = np.mean(durations)
    memory_used = max(0, mem_after - mem_before)

    throughput = 0.0
    if n_items and avg_duration > 0:
        throughput = (n_items * 1000) / avg_duration  # items per second

    return BenchmarkResult(
        name=func_name,
        duration_ms=avg_duration,
        memory_mb=memory_used,
        throughput_items_per_sec=throughput,
        metadata={
            "runs": benchmark_runs,
            "std_ms": np.std(durations),
            "min_ms": np.min(durations),
            "max_ms": np.max(durations),
        }
    )


# =============================================================================
# BENCHMARKS SPÉCIFIQUES
# =============================================================================

def benchmark_indicator_calculation(
    data_size: int = 10000,
    period: int = 20
) -> BenchmarkComparison:
    """
    Benchmark le calcul d'indicateurs techniques.

    Compare:
    - Calcul natif pandas
    - Calcul NumPy vectorisé
    - Calcul avec Numba (si disponible)
    """
    # Données de test
    np.random.seed(42)
    prices = 100 + np.cumsum(np.random.randn(data_size) * 0.5)
    prices_series = pd.Series(prices)

    results = []

    # 1. Pandas rolling
    def pandas_sma():
        return prices_series.rolling(window=period).mean().values

    results.append(benchmark_function(
        pandas_sma,
        name="Pandas Rolling SMA",
        n_items=data_size
    ))

    # 2. NumPy convolve
    def numpy_convolve():
        kernel = np.ones(period) / period
        return np.convolve(prices, kernel, mode='same')

    results.append(benchmark_function(
        numpy_convolve,
        name="NumPy Convolve SMA",
        n_items=data_size
    ))

    # 3. Numba (si disponible)
    try:
        from numba import njit

        @njit(cache=True)
        def numba_sma(prices, period):
            n = len(prices)
            result = np.empty(n)
            result[:period-1] = np.nan

            for i in range(period-1, n):
                result[i] = np.mean(prices[i-period+1:i+1])

            return result

        # Warm-up compilation
        _ = numba_sma(prices, period)

        results.append(benchmark_function(
            lambda: numba_sma(prices, period),
            name="Numba JIT SMA",
            n_items=data_size
        ))
    except ImportError:
        logger.warning("Numba non disponible pour benchmark")

    return BenchmarkComparison(results, baseline_name="Pandas Rolling SMA")


def benchmark_simulator_performance(
    n_bars: int = 10000,
    n_signals: int = 500
) -> BenchmarkComparison:
    """
    Benchmark la simulation de trades.

    Compare:
    - Simulateur Python pur (simulator.py)
    - Simulateur Numba (simulator_fast.py)
    """
    from backtest.simulator import simulate_trades

    # Données de test
    np.random.seed(42)
    dates = pd.date_range("2020-01-01", periods=n_bars, freq="1h")
    close = 100 + np.cumsum(np.random.randn(n_bars) * 0.5)

    df = pd.DataFrame({
        "timestamp": dates,
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": np.random.randint(1000, 10000, n_bars)
    }).set_index("timestamp")

    # Signaux aléatoires
    signals = pd.Series(np.random.choice([0, 1, -1], size=n_bars, p=[0.95, 0.025, 0.025]), index=df.index)

    params = {
        "leverage": 1,
        "k_sl": 1.5,
        "initial_capital": 10000,
        "fees_bps": 10,
        "slippage_bps": 5
    }

    results = []

    # 1. Simulateur standard
    results.append(benchmark_function(
        simulate_trades,
        df, signals, params,
        name="Simulator (Python)",
        n_items=n_bars,
        benchmark_runs=3
    ))

    # 2. Simulateur Numba (si disponible)
    try:
        from backtest.simulator_fast import HAS_NUMBA, simulate_trades_fast

        if HAS_NUMBA:
            results.append(benchmark_function(
                simulate_trades_fast,
                df, signals, params,
                name="Simulator (Numba JIT)",
                n_items=n_bars,
                benchmark_runs=3
            ))
    except ImportError:
        logger.warning("simulator_fast non disponible")

    return BenchmarkComparison(results, baseline_name="Simulator (Python)")


def benchmark_gpu_vs_cpu(
    data_size: int = 100000
) -> BenchmarkComparison:
    """
    Benchmark CPU-only (GPU désactivé).
    """
    results = []

    # Données de test
    np.random.seed(42)
    data = np.random.randn(data_size)

    # 1. CPU (NumPy)
    def numpy_operations():
        x = np.array(data)
        y = np.sqrt(np.abs(x))
        z = np.exp(-y ** 2)
        return np.sum(z)

    results.append(benchmark_function(
        numpy_operations,
        name="NumPy (CPU)",
        n_items=data_size
    ))

    return BenchmarkComparison(results, baseline_name="NumPy (CPU)")


def run_all_benchmarks(verbose: bool = True) -> Dict[str, BenchmarkComparison]:
    """
    Exécute tous les benchmarks.

    Args:
        verbose: Afficher les résultats

    Returns:
        Dict des comparaisons par catégorie
    """
    benchmarks = {}

    logger.info("=" * 80)
    logger.info("DÉMARRAGE SUITE DE BENCHMARKS")
    logger.info("=" * 80)

    # 1. Indicateurs
    logger.info("\n[1/3] Benchmark Indicateurs...")
    benchmarks["indicators"] = benchmark_indicator_calculation()
    if verbose:
        print(benchmarks["indicators"].summary())

    # 2. Simulateur
    logger.info("\n[2/3] Benchmark Simulateur...")
    benchmarks["simulator"] = benchmark_simulator_performance()
    if verbose:
        print(benchmarks["simulator"].summary())

    # 3. GPU vs CPU
    logger.info("\n[3/3] Benchmark GPU vs CPU...")
    benchmarks["gpu"] = benchmark_gpu_vs_cpu()
    if verbose:
        print(benchmarks["gpu"].summary())

    logger.info("\n" + "=" * 80)
    logger.info("BENCHMARKS TERMINÉS")
    logger.info("=" * 80)

    return benchmarks


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Exécuter les benchmarks de performance")
    parser.add_argument(
        "--category",
        choices=["indicators", "simulator", "gpu", "all"],
        default="all",
        help="Catégorie de benchmark à exécuter"
    )
    parser.add_argument(
        "--size",
        type=int,
        default=10000,
        help="Taille des données de test"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Mode silencieux (pas d'affichage)"
    )

    args = parser.parse_args()

    if args.category == "all":
        run_all_benchmarks(verbose=not args.quiet)
    elif args.category == "indicators":
        comp = benchmark_indicator_calculation(data_size=args.size)
        if not args.quiet:
            print(comp.summary())
    elif args.category == "simulator":
        comp = benchmark_simulator_performance(n_bars=args.size)
        if not args.quiet:
            print(comp.summary())
    elif args.category == "gpu":
        comp = benchmark_gpu_vs_cpu(data_size=args.size)
        if not args.quiet:
            print(comp.summary())
