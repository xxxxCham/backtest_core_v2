"""
Module-ID: tools.benchmark_system

Purpose: Benchmark complet du système de backtest pour optimisation.

🚀 UTILISATION:
    python -m tools.benchmark_system
    python -m tools.benchmark_system --full
    python -m tools.benchmark_system --parallel-only

Teste:
1. Configuration CPU/RAM détectée
2. Performance Numba (séquentiel vs parallèle)
3. Performance joblib (différents workers/backends)
4. Performance sweep complet
5. Recommandations d'optimisation
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# Ajouter le répertoire parent au path
sys.path.insert(0, str(Path(__file__).parent.parent))

# psutil pour monitoring
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


@dataclass
class SystemInfo:
    """Informations système."""
    cpu_physical: int
    cpu_logical: int
    ram_total_gb: float
    ram_available_gb: float
    numba_threads: int
    numba_version: str
    python_version: str


@dataclass
class BenchmarkResult:
    """Résultat d'un benchmark."""
    name: str
    time_ms: float
    throughput: float  # items/sec
    cpu_usage_pct: float
    ram_usage_gb: float
    config: Dict[str, Any]


def get_system_info() -> SystemInfo:
    """Récupère les informations système."""
    import platform

    cpu_physical = os.cpu_count() or 4
    cpu_logical = cpu_physical

    if HAS_PSUTIL:
        cpu_physical = psutil.cpu_count(logical=False) or cpu_physical
        cpu_logical = psutil.cpu_count(logical=True) or cpu_logical
        ram_total = psutil.virtual_memory().total / (1024**3)
        ram_available = psutil.virtual_memory().available / (1024**3)
    else:
        ram_total = 8.0
        ram_available = 4.0

    # Numba info
    try:
        import numba
        numba_version = numba.__version__
        numba_threads = numba.get_num_threads()
    except ImportError:
        numba_version = "N/A"
        numba_threads = 1

    return SystemInfo(
        cpu_physical=cpu_physical,
        cpu_logical=cpu_logical,
        ram_total_gb=ram_total,
        ram_available_gb=ram_available,
        numba_threads=numba_threads,
        numba_version=numba_version,
        python_version=platform.python_version(),
    )


def print_system_info(info: SystemInfo):
    """Affiche les informations système."""
    print("\n" + "=" * 60)
    print("🖥️  CONFIGURATION SYSTÈME")
    print("=" * 60)
    print(f"  CPU Physical cores:    {info.cpu_physical}")
    print(f"  CPU Logical cores:     {info.cpu_logical} (SMT/HT)")
    print(f"  RAM Total:             {info.ram_total_gb:.1f} GB")
    print(f"  RAM Available:         {info.ram_available_gb:.1f} GB")
    print(f"  Numba version:         {info.numba_version}")
    print(f"  Numba threads:         {info.numba_threads}")
    print(f"  Python version:        {info.python_version}")
    print("=" * 60)


def generate_test_data(n_bars: int = 10000) -> pd.DataFrame:
    """Génère des données OHLCV de test."""
    np.random.seed(42)

    # Générer des prix réalistes
    returns = np.random.randn(n_bars) * 0.02
    close = 100 * np.exp(np.cumsum(returns))

    high = close * (1 + np.abs(np.random.randn(n_bars) * 0.01))
    low = close * (1 - np.abs(np.random.randn(n_bars) * 0.01))
    open_price = low + (high - low) * np.random.rand(n_bars)
    volume = np.random.randint(1000, 100000, n_bars)

    return pd.DataFrame({
        'open': open_price,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    })


def benchmark_numba(df: pd.DataFrame) -> List[BenchmarkResult]:
    """Benchmark du sweep Numba (intégré dans backtest/sweep_numba.py)."""
    try:
        from backtest.sweep_numba import benchmark_sweep_numba, HAS_NUMBA
        if not HAS_NUMBA:
            print("\n⚠️ Numba non disponible, skip benchmark")
            return []
    except ImportError:
        print("\n⚠️ Module sweep_numba non trouvé")
        return []

    results = []

    print("\n" + "-" * 60)
    print("🔢 BENCHMARK NUMBA SWEEP (Parallélisation complète)")
    print("-" * 60)

    # Benchmark avec différentes tailles
    for n_combos, n_bars in [(100, 5000), (500, 10000), (1000, 10000)]:
        result = benchmark_sweep_numba(n_combos=n_combos, n_bars=n_bars)
        results.append(BenchmarkResult(
            name=f"Numba sweep ({n_combos} combos × {n_bars} bars)",
            time_ms=result['total_time'] * 1000,
            throughput=result['throughput'],
            cpu_usage_pct=0,
            ram_usage_gb=0,
            config={"n_combos": n_combos, "n_bars": n_bars},
        ))

    return results


def benchmark_parallel_sweep(df: pd.DataFrame, n_combos: int = 100) -> List[BenchmarkResult]:
    """Benchmark du sweep parallèle avec différentes configurations."""
    from performance.parallel import ParallelRunner, generate_param_grid

    results = []

    # Générer grille de paramètres
    param_grid = generate_param_grid({
        "bb_period": list(range(15, 35, 5)),
        "bb_std": [1.5, 2.0, 2.5],
        "atr_period": [10, 14, 21],
    })[:n_combos]

    # Fonction de backtest simplifiée
    def dummy_backtest(params, data=None):
        # Simuler un backtest (~5-10ms)
        time.sleep(0.005)
        return {"params": params, "sharpe": np.random.rand()}

    # Configurations à tester
    worker_configs = [8, 16, 24, 32]

    print("\n" + "-" * 60)
    print(f"⚡ BENCHMARK SWEEP PARALLÈLE ({n_combos} combinaisons)")
    print("-" * 60)

    for n_workers in worker_configs:
        runner = ParallelRunner(
            max_workers=n_workers,
            backend="loky",
            chunk_size=50,
        )

        start = time.perf_counter()
        sweep_result = runner.run_sweep(dummy_backtest, param_grid, data=df)
        elapsed = time.perf_counter() - start

        throughput = n_combos / elapsed

        result = BenchmarkResult(
            name=f"Sweep {n_workers} workers",
            time_ms=elapsed * 1000,
            throughput=throughput,
            cpu_usage_pct=0,
            ram_usage_gb=sweep_result.memory_peak_gb or 0,
            config={"n_workers": n_workers, "n_combos": n_combos},
        )
        results.append(result)

        print(f"  {result.name}: {result.time_ms:.0f} ms ({throughput:.1f} backtests/s)")

    return results


def benchmark_real_backtest(df: pd.DataFrame, n_runs: int = 50) -> List[BenchmarkResult]:
    """Benchmark avec de vrais backtests."""
    try:
        from backtest.engine import BacktestEngine
        from strategies import get_strategy_class
    except ImportError as e:
        print(f"⚠️ Import backtest échoué: {e}")
        return []

    results = []

    print("\n" + "-" * 60)
    print(f"📊 BENCHMARK BACKTEST RÉEL ({n_runs} runs)")
    print("-" * 60)

    # Paramètres de test
    params = {
        "bb_period": 20,
        "bb_std": 2.0,
        "atr_period": 14,
        "leverage": 1,
    }

    # Test séquentiel
    start = time.perf_counter()
    for _ in range(n_runs):
        try:
            engine = BacktestEngine(strategy_name="bollinger_atr")
            _ = engine.run(df, params)
        except Exception as e:
            print(f"  Erreur backtest: {e}")
            break
    seq_time = time.perf_counter() - start

    if seq_time > 0:
        result = BenchmarkResult(
            name="Backtest séquentiel",
            time_ms=seq_time * 1000,
            throughput=n_runs / seq_time,
            cpu_usage_pct=0,
            ram_usage_gb=0,
            config={"n_runs": n_runs, "n_bars": len(df)},
        )
        results.append(result)
        print(f"  {result.name}: {result.time_ms:.0f} ms total ({result.throughput:.1f} runs/s)")

    return results


def print_recommendations(info: SystemInfo, results: List[BenchmarkResult]):
    """Affiche les recommandations d'optimisation."""
    print("\n" + "=" * 60)
    print("💡 RECOMMANDATIONS D'OPTIMISATION")
    print("=" * 60)

    # Recommandations CPU
    optimal_workers = min(info.cpu_logical, int(info.cpu_physical * 2.5))
    print(f"\n🔧 Configuration CPU recommandée:")
    print(f"   BACKTEST_CPU_MULTIPLIER=2.0  (actuellement {info.cpu_physical * 2} workers)")
    print(f"   Workers optimaux: {optimal_workers}")

    # Recommandations Numba
    if info.numba_threads < info.cpu_logical:
        print(f"\n🔧 Configuration Numba:")
        print(f"   NUMBA_NUM_THREADS={info.cpu_logical}  (actuellement {info.numba_threads})")

    # Recommandations RAM
    if info.ram_total_gb >= 32:
        print(f"\n🔧 Configuration RAM ({info.ram_total_gb:.0f} GB DDR5):")
        print(f"   JOBLIB_MAX_NBYTES=500M  (copies directes en RAM)")
        print(f"   Pré-chargement données en RAM recommandé")

    # Trouver la meilleure config de sweep
    sweep_results = [r for r in results if "Sweep" in r.name]
    if sweep_results:
        best = max(sweep_results, key=lambda r: r.throughput)
        print(f"\n🏆 Meilleure configuration sweep:")
        print(f"   {best.name}: {best.throughput:.1f} backtests/sec")

    # Variables d'environnement recommandées
    print("\n📝 Variables d'environnement (.env):")
    print("-" * 40)
    print(f"BACKTEST_CPU_MULTIPLIER=2.0")
    print(f"NUMBA_NUM_THREADS={info.cpu_logical}")
    print(f"NUMBA_CACHE_DIR=.numba_cache")
    print(f"JOBLIB_MAX_NBYTES=500M")
    print(f"JOBLIB_VERBOSE=0")
    print(f"OMP_NUM_THREADS={info.cpu_logical}")
    print(f"MKL_NUM_THREADS={info.cpu_logical}")
    print("-" * 40)

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Benchmark système backtest")
    parser.add_argument("--full", action="store_true", help="Benchmark complet")
    parser.add_argument("--parallel-only", action="store_true", help="Benchmark parallèle uniquement")
    parser.add_argument("--numba-only", action="store_true", help="Benchmark Numba uniquement")
    parser.add_argument("--n-bars", type=int, default=10000, help="Nombre de barres de test")
    parser.add_argument("--n-combos", type=int, default=100, help="Nombre de combinaisons sweep")
    args = parser.parse_args()

    print("\n🚀 BENCHMARK SYSTÈME BACKTEST CORE")
    print("=" * 60)

    # Info système
    info = get_system_info()
    print_system_info(info)

    # Générer données de test
    print(f"\n📊 Génération données de test ({args.n_bars} barres)...")
    df = generate_test_data(args.n_bars)

    all_results = []

    # Benchmarks
    if args.numba_only or args.full or not (args.parallel_only):
        results = benchmark_numba(df)
        all_results.extend(results)

    if args.parallel_only or args.full or not (args.numba_only):
        results = benchmark_parallel_sweep(df, args.n_combos)
        all_results.extend(results)

    if args.full:
        results = benchmark_real_backtest(df)
        all_results.extend(results)

    # Recommandations
    print_recommendations(info, all_results)

    print("\n✅ Benchmark terminé!")


if __name__ == "__main__":
    main()
