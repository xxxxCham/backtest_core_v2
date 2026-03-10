"""
Benchmark Calcul Hybride CPU+GPU
================================

Compare performances CPU vs GPU vs HYBRIDE sur différentes tailles de datasets.

Teste:
1. Calculs indicateurs (SMA, EMA, Bollinger)
2. Seuils GPU (1000, 2000, 5000 points)
3. Batch processing multi-symboles
4. Sweeps parallèles multi-worker
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# Ajouter le projet au path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from performance.hybrid_compute import (
    HybridCompute,
    auto_compute,
    batch_compute,
)


def generate_test_data(size: int, seed: int = 42) -> np.ndarray:
    """Génère des données de test (prix OHLC simulés)."""
    np.random.seed(seed)
    base = 100
    returns = np.random.normal(0.0001, 0.02, size)
    prices = base * np.exp(np.cumsum(returns))
    return prices


def benchmark_single_operation(
    data: np.ndarray,
    operation: str,
    window: int = 20,
    n_iterations: int = 10,
) -> dict:
    """
    Benchmark une opération sur CPU vs GPU.

    Returns:
        Dict avec times_cpu, times_gpu, speedup
    """
    hc = HybridCompute()

    # Warmup
    _ = auto_compute(data, operation, window=window)

    # Benchmark CPU
    times_cpu = []
    for _ in range(n_iterations):
        start = time.perf_counter()
        _ = auto_compute(
            data, operation, window=window,
        )
        times_cpu.append((time.perf_counter() - start) * 1000)  # ms

    # Benchmark GPU (si disponible)
    times_gpu = []
    if hc.gpu_available:
        for _ in range(n_iterations):
            start = time.perf_counter()
            _ = hc._compute_gpu(data, operation, window=window)
            times_gpu.append((time.perf_counter() - start) * 1000)  # ms

    avg_cpu = np.mean(times_cpu)
    avg_gpu = np.mean(times_gpu) if times_gpu else None
    speedup = avg_cpu / avg_gpu if avg_gpu else None

    return {
        "operation": operation,
        "data_size": len(data),
        "window": window,
        "times_cpu_ms": times_cpu,
        "times_gpu_ms": times_gpu,
        "avg_cpu_ms": avg_cpu,
        "avg_gpu_ms": avg_gpu,
        "speedup": speedup,
        "cpu_std": np.std(times_cpu),
        "gpu_std": np.std(times_gpu) if times_gpu else None,
    }


def benchmark_dataset_sizes(operation: str = "sma", window: int = 20) -> pd.DataFrame:
    """
    Benchmark sur différentes tailles de dataset.

    Teste: 100, 500, 1000, 2000, 5000, 10000, 20000 points
    """
    sizes = [100, 500, 1000, 2000, 5000, 10000, 20000]
    results = []

    print(f"\n{'='*70}")
    print(f"BENCHMARK: {operation.upper()} (window={window})")
    print(f"{'='*70}")

    for size in sizes:
        data = generate_test_data(size)
        result = benchmark_single_operation(data, operation, window, n_iterations=10)
        results.append(result)

        gpu_str = f"{result['avg_gpu_ms']:.2f}ms" if result['avg_gpu_ms'] else "N/A"
        speedup_str = f"{result['speedup']:.2f}×" if result['speedup'] else "N/A"

        print(
            f"{size:>6} points | "
            f"CPU: {result['avg_cpu_ms']:>7.2f}ms | "
            f"GPU: {gpu_str:>10} | "
            f"Speedup: {speedup_str:>8}"
        )

    return pd.DataFrame(results)


def benchmark_batch_processing(n_symbols: int = 10, data_size: int = 5000) -> dict:
    """
    Benchmark batch processing multi-symboles.

    Simule un sweep multi-symboles avec calculs d'indicateurs.
    """
    print(f"\n{'='*70}")
    print(f"BENCHMARK BATCH: {n_symbols} symboles × {data_size} points")
    print(f"{'='*70}")

    # Générer données pour N symboles
    data_list = [generate_test_data(data_size, seed=i) for i in range(n_symbols)]

    hc = HybridCompute()

    # Warmup
    _ = batch_compute(data_list[:2], "sma", window=20)

    # Benchmark séquentiel CPU
    start = time.perf_counter()
    _ = [auto_compute(data, "sma", window=20) for data in data_list]
    time_cpu = (time.perf_counter() - start) * 1000

    # Benchmark batch GPU
    if hc.gpu_available:
        start = time.perf_counter()
        _ = batch_compute(data_list, "sma", window=20)
        time_gpu = (time.perf_counter() - start) * 1000
        speedup = time_cpu / time_gpu
    else:
        time_gpu = None
        speedup = None

    print(f"CPU séquentiel : {time_cpu:.2f}ms")
    if time_gpu:
        print(f"GPU batch      : {time_gpu:.2f}ms")
        print(f"Speedup        : {speedup:.2f}×")

    return {
        "n_symbols": n_symbols,
        "data_size": data_size,
        "time_cpu_ms": time_cpu,
        "time_gpu_ms": time_gpu,
        "speedup": speedup,
    }


def benchmark_sweep_simulation(
    n_combinations: int = 100,
    data_size: int = 2000,
) -> dict:
    """
    Simule un sweep avec calculs d'indicateurs répétés.

    Mesure l'impact du calcul hybride sur un sweep réaliste.
    """
    print(f"\n{'='*70}")
    print(f"BENCHMARK SWEEP: {n_combinations} combinaisons")
    print(f"{'='*70}")

    data = generate_test_data(data_size)
    hc = HybridCompute()

    # Warmup
    _ = auto_compute(data, "sma", window=20)

    # Simulation sweep avec variations de paramètres
    windows = [10, 15, 20, 30, 50]

    # CPU
    start = time.perf_counter()
    for _ in range(n_combinations):
        for window in windows:
            _ = auto_compute(data, "sma", window=window)
    time_cpu = (time.perf_counter() - start) * 1000

    # GPU (si disponible)
    if hc.gpu_available:
        start = time.perf_counter()
        for _ in range(n_combinations):
            for window in windows:
                _ = hc._compute_gpu(data, "sma", window=window)
        time_gpu = (time.perf_counter() - start) * 1000
        speedup = time_cpu / time_gpu
    else:
        time_gpu = None
        speedup = None

    ops_per_sec_cpu = (n_combinations * len(windows)) / (time_cpu / 1000)
    ops_per_sec_gpu = (n_combinations * len(windows)) / (time_gpu / 1000) if time_gpu else None

    print(f"CPU            : {time_cpu:.0f}ms ({ops_per_sec_cpu:.0f} ops/s)")
    if time_gpu:
        print(f"GPU            : {time_gpu:.0f}ms ({ops_per_sec_gpu:.0f} ops/s)")
        print(f"Speedup        : {speedup:.2f}×")

    return {
        "n_combinations": n_combinations,
        "data_size": data_size,
        "time_cpu_ms": time_cpu,
        "time_gpu_ms": time_gpu,
        "speedup": speedup,
        "ops_per_sec_cpu": ops_per_sec_cpu,
        "ops_per_sec_gpu": ops_per_sec_gpu,
    }


def run_full_benchmark():
    """Execute le benchmark complet."""
    print("\n" + "="*70)
    print("BENCHMARK CALCUL HYBRIDE CPU+GPU (RTX 5080)")
    print("="*70)

    hc = HybridCompute()
    print(f"\nGPU Disponible : {hc.gpu_available}")
    if hc.gpu_available:
        print(f"GPU Device     : {hc.backend.device_info}")
        print(f"Seuil GPU      : {hc.thresholds.gpu_min_size} points")

    # 1. Dataset sizes
    results_sma = benchmark_dataset_sizes("sma", window=20)
    results_ema = benchmark_dataset_sizes("ema", window=20)

    # 2. Batch processing
    batch_10 = benchmark_batch_processing(n_symbols=10, data_size=5000)
    batch_50 = benchmark_batch_processing(n_symbols=50, data_size=2000)

    # 3. Sweep simulation
    sweep_100 = benchmark_sweep_simulation(n_combinations=100, data_size=2000)
    sweep_500 = benchmark_sweep_simulation(n_combinations=500, data_size=5000)

    # Résumé
    print("\n" + "="*70)
    print("RÉSUMÉ")
    print("="*70)

    if hc.gpu_available:
        # Moyennes speedup
        speedups_sma = [r['speedup'] for r in results_sma.to_dict('records') if r['speedup']]
        speedups_ema = [r['speedup'] for r in results_ema.to_dict('records') if r['speedup']]

        avg_speedup_sma = np.mean(speedups_sma) if speedups_sma else None
        avg_speedup_ema = np.mean(speedups_ema) if speedups_ema else None

        print(f"\n✅ SMA Speedup moyen     : {avg_speedup_sma:.2f}×" if avg_speedup_sma else "N/A")
        print(f"✅ EMA Speedup moyen     : {avg_speedup_ema:.2f}×" if avg_speedup_ema else "N/A")
        print(f"✅ Batch 10×5k Speedup   : {batch_10['speedup']:.2f}×")
        print(f"✅ Batch 50×2k Speedup   : {batch_50['speedup']:.2f}×")
        print(f"✅ Sweep 100 Speedup     : {sweep_100['speedup']:.2f}×")
        print(f"✅ Sweep 500 Speedup     : {sweep_500['speedup']:.2f}×")

        print("\n🚀 GAIN ATTENDU SUR BACKTEST RÉEL:")
        # Estimation gain backtest
        # Hypothèse: 30% du temps en calculs indicateurs
        indicator_time_pct = 0.30
        avg_speedup = np.mean([avg_speedup_sma, avg_speedup_ema, sweep_500['speedup']])
        overall_speedup = 1 + (avg_speedup - 1) * indicator_time_pct

        print("   Baseline CPU    : 475 bt/s (30 workers)")
        print(f"   Avec GPU hybride: {475 * overall_speedup:.0f} bt/s")
        print(f"   Gain estimé     : +{(overall_speedup - 1) * 100:.1f}%")

        # Projection multi-symboles
        print("\n🎯 PROJECTION SWEEP MULTI-SYMBOLES:")
        print(f"   10 tokens × 5k barres : {batch_10['time_cpu_ms']:.0f}ms CPU → {batch_10['time_gpu_ms']:.0f}ms GPU")
        print(f"   50 tokens × 2k barres : {batch_50['time_cpu_ms']:.0f}ms CPU → {batch_50['time_gpu_ms']:.0f}ms GPU")
    else:
        print("\n❌ GPU non disponible - Benchmark CPU only")

    print("\n" + "="*70)


if __name__ == "__main__":
    run_full_benchmark()
