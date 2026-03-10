#!/usr/bin/env python
"""
Test configuration Numba/NumPy Threading
=========================================
Vérifie que prange et numpy sont correctement activés.
"""

import os
import sys
import time
import numpy as np

print("=" * 70)
print("TEST CONFIGURATION NUMBA/NUMPY THREADING")
print("=" * 70)

# ============================================================================
# 1. Configuration variables d'environnement
# ============================================================================
print("\n[1/5] Variables d'environnement...")

# Configurer AVANT import numba
os.environ['NUMBA_NUM_THREADS'] = '32'
os.environ['NUMBA_THREADING_LAYER'] = 'tbb'
os.environ['OMP_NUM_THREADS'] = '32'
os.environ['MKL_NUM_THREADS'] = '32'

for var in ['NUMBA_NUM_THREADS', 'NUMBA_THREADING_LAYER', 'OMP_NUM_THREADS']:
    val = os.environ.get(var, 'NON DÉFINI')
    status = '✓' if val != 'NON DÉFINI' else '✗'
    print(f"  {status} {var}={val}")

# ============================================================================
# 2. Import et versions
# ============================================================================
print("\n[2/5] Versions packages...")

try:
    import numba
    print(f"  ✓ Numba: {numba.__version__}")
except ImportError as e:
    print(f"  ✗ Numba non installé: {e}")
    sys.exit(1)

print(f"  ✓ NumPy: {np.__version__}")

# ============================================================================
# 3. Configuration Numba
# ============================================================================
print("\n[3/5] Configuration Numba...")

print(f"  Threading layer: {numba.config.THREADING_LAYER}")
print(f"  Threads configurés: {numba.config.NUMBA_NUM_THREADS}")
print(f"  CPU count: {numba.config.NUMBA_DEFAULT_NUM_THREADS}")

if numba.config.THREADING_LAYER != 'tbb':
    print("  ⚠️  WARNING: Threading layer n'est pas TBB")
    print("  → Performance sous-optimale attendue")
    print("  → Installer TBB: pip install tbb")
else:
    print("  ✓ TBB activé (optimal)")

# ============================================================================
# 4. Test prange simple
# ============================================================================
print("\n[4/5] Test prange parallélisation...")

@numba.njit(parallel=True, fastmath=True, cache=True)
def test_prange_sum(n):
    total = 0.0
    for i in numba.prange(n):
        total += i * 2.0
    return total

# Warmup JIT
_ = test_prange_sum(100)

# Benchmark
n = 10_000_000
start = time.perf_counter()
result = test_prange_sum(n)
elapsed = time.perf_counter() - start

expected = n * (n - 1)
print(f"  Résultat: {result:.0f} (attendu: {expected:.0f})")
print(f"  Temps: {elapsed*1000:.2f} ms")
print(f"  ✓ Test prange: {'OK' if abs(result - expected) < 1 else 'ERREUR'}")

# ============================================================================
# 5. Test sweep Numba (mini benchmark)
# ============================================================================
print("\n[5/5] Benchmark sweep Numba (simulation backtest)...")

@numba.njit(parallel=True, fastmath=True, cache=True, nogil=True)
def mini_sweep_benchmark(closes, n_combos):
    """Mini sweep : calcule SMA sur n_combos périodes différentes."""
    n_bars = len(closes)
    results = np.zeros(n_combos, dtype=np.float64)

    for combo in numba.prange(n_combos):
        period = 10 + combo  # Périodes 10, 11, 12, ...
        sma_sum = 0.0

        for i in range(period, n_bars):
            window_sum = 0.0
            for j in range(period):
                window_sum += closes[i - period + 1 + j]
            sma_sum += window_sum / period

        results[combo] = sma_sum

    return results

# Génération données test
n_bars = 50_000
n_combos = 1000
closes = np.random.randn(n_bars).astype(np.float64) * 100 + 10000

# Warmup
_ = mini_sweep_benchmark(closes[:100], 10)

# Benchmark
print(f"  Configuration: {n_combos:,} combos × {n_bars:,} bars")
start = time.perf_counter()
results = mini_sweep_benchmark(closes, n_combos)
elapsed = time.perf_counter() - start

throughput = n_combos / elapsed
print(f"  Temps total: {elapsed:.2f}s")
print(f"  ✓ Throughput: {throughput:,.0f} backtests/seconde")

# Estimation scaling
print(f"\n  Estimation pour 5M combos × 150K bars:")
ratio_combos = 5_000_000 / n_combos
ratio_bars = 150_000 / n_bars
adjusted_time = elapsed * ratio_combos * ratio_bars
print(f"    → Temps estimé: {adjusted_time/60:.1f} minutes ({adjusted_time:.0f}s)")
print(f"    → Throughput estimé: {5_000_000/adjusted_time:,.0f} bt/s")

# ============================================================================
# Résumé
# ============================================================================
print("\n" + "=" * 70)
print("RÉSUMÉ")
print("=" * 70)

checks = [
    ('NUMBA_NUM_THREADS défini', os.environ.get('NUMBA_NUM_THREADS') is not None),
    ('Threading layer = tbb', numba.config.THREADING_LAYER == 'tbb'),
    ('prange fonctionne', abs(result - expected) < 1),
    ('Throughput > 500 bt/s', throughput > 500),
]

all_ok = all(check[1] for check in checks)

for label, ok in checks:
    status = '✓' if ok else '✗'
    print(f"  {status} {label}")

if all_ok:
    print("\n✅ Configuration OPTIMALE - prange activé correctement")
else:
    print("\n⚠️  Configuration SOUS-OPTIMALE")
    print("\nActions recommandées:")
    print("  1. pip install tbb")
    print("  2. Relancer ce script")
    print("  3. Consulter NUMBA_SETUP.md")

print("=" * 70)
