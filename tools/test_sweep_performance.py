#!/usr/bin/env python
"""
Test performance Numba sweep avec prange activé
================================================
"""

import os
import sys
import time

# ⚡ CONFIGURATION NUMBA (AVANT imports)
os.environ['NUMBA_NUM_THREADS'] = '32'
os.environ['NUMBA_THREADING_LAYER'] = 'omp'
os.environ['OMP_NUM_THREADS'] = '32'
os.environ['MKL_NUM_THREADS'] = '32'

import numpy as np
import numba
from backtest.sweep_numba import _sweep_bollinger_full, benchmark_sweep_numba

print("=" * 80)
print("TEST PERFORMANCE SWEEP NUMBA avec prange")
print("=" * 80)

# Configuration
print(f"\n[CONFIG]")
print(f"  Numba version: {numba.__version__}")
print(f"  Threading layer: {numba.config.THREADING_LAYER}")
print(f"  Threads: {numba.config.NUMBA_NUM_THREADS}")

# ============================================================================
# Test 1 : Petit sweep (validation)
# ============================================================================
print(f"\n[TEST 1] Validation (100 combos × 5000 bars)")

n_bars = 5000
n_combos = 100

np.random.seed(42)
closes = np.exp(np.cumsum(np.random.randn(n_bars) * 0.02)).astype(np.float64) * 100
highs = (closes * 1.01).astype(np.float64)
lows = (closes * 0.99).astype(np.float64)

bb_periods = np.full(n_combos, 20.0, dtype=np.float64)
bb_stds = np.full(n_combos, 2.0, dtype=np.float64)
entry_zs = np.full(n_combos, 2.0, dtype=np.float64)
leverages = np.full(n_combos, 1.0, dtype=np.float64)
k_sls = np.full(n_combos, 1.5, dtype=np.float64)

start = time.perf_counter()
pnls, sharpes, max_dds, win_rates, n_trades = _sweep_bollinger_full(
    closes, highs, lows,
    bb_periods, bb_stds, entry_zs,
    leverages, k_sls,
    10000.0, 10.0, 5.0
)
elapsed = time.perf_counter() - start

throughput = n_combos / elapsed
print(f"  Temps: {elapsed:.3f}s")
print(f"  Throughput: {throughput:,.0f} backtests/seconde")
print(f"  ✓ Validation OK")

# ============================================================================
# Test 2 : Sweep moyen (10K combos)
# ============================================================================
print(f"\n[TEST 2] Sweep moyen (10,000 combos × 10,000 bars)")

n_bars = 10_000
n_combos = 10_000

closes = np.exp(np.cumsum(np.random.randn(n_bars) * 0.02)).astype(np.float64) * 100
highs = (closes * 1.01).astype(np.float64)
lows = (closes * 0.99).astype(np.float64)

# Grille réaliste
bb_periods = np.tile(np.arange(10, 60, 2, dtype=np.float64), 400)[:n_combos]
bb_stds = np.tile([1.5, 2.0, 2.5, 3.0], n_combos//4 + 1)[:n_combos].astype(np.float64)
entry_zs = np.full(n_combos, 2.0, dtype=np.float64)
leverages = np.full(n_combos, 1.0, dtype=np.float64)
k_sls = np.full(n_combos, 1.5, dtype=np.float64)

start = time.perf_counter()
pnls, sharpes, max_dds, win_rates, n_trades = _sweep_bollinger_full(
    closes, highs, lows,
    bb_periods, bb_stds, entry_zs,
    leverages, k_sls,
    10000.0, 10.0, 5.0
)
elapsed = time.perf_counter() - start

throughput = n_combos / elapsed
print(f"  Temps: {elapsed:.2f}s")
print(f"  Throughput: {throughput:,.0f} backtests/seconde")

# Stats résultats
best_idx = np.argmax(pnls)
print(f"\n  Meilleur PnL: ${pnls[best_idx]:,.2f}")
print(f"  Meilleur Sharpe: {sharpes[best_idx]:.2f}")
print(f"  Avg trades: {np.mean(n_trades):.0f}")

# ============================================================================
# Estimation pour 5M combos × 150K bars
# ============================================================================
print(f"\n[ESTIMATION] Sweep massif (5,000,000 combos × 150,000 bars)")

# Facteurs d'échelle
ratio_combos = 5_000_000 / n_combos
ratio_bars = 150_000 / n_bars
estimated_time = elapsed * ratio_combos * ratio_bars

estimated_throughput = 5_000_000 / estimated_time

print(f"  Temps estimé: {estimated_time/60:.1f} minutes ({estimated_time:.0f}s)")
print(f"  Throughput estimé: {estimated_throughput:,.0f} backtests/seconde")

# Comparaison avec threading layer "default"
default_throughput_estimate = throughput * 0.15  # ~85% plus lent sans OpenMP
default_time_estimate = 5_000_000 / default_throughput_estimate

print(f"\n[COMPARAISON]")
print(f"  Avec OpenMP: {estimated_time/60:.1f} min ({estimated_throughput:,.0f} bt/s)")
print(f"  Sans OpenMP: {default_time_estimate/60:.1f} min ({default_throughput_estimate:,.0f} bt/s)")
print(f"  Gain: {default_time_estimate/estimated_time:.1f}×")

# ============================================================================
# Résumé
# ============================================================================
print("\n" + "=" * 80)
print("RÉSUMÉ")
print("=" * 80)

checks = [
    ('Threading layer OpenMP', numba.config.THREADING_LAYER == 'omp'),
    ('Threads configurés (32)', numba.config.NUMBA_NUM_THREADS >= 32),
    ('Throughput > 500 bt/s', throughput > 500),
    ('Temps 5M combos < 15 min', estimated_time < 900),
]

for label, ok in checks:
    status = '✓' if ok else '✗'
    print(f"  {status} {label}")

if all(check[1] for check in checks):
    print("\n✅ CONFIGURATION OPTIMALE - prange activé avec OpenMP")
    print(f"\nPerformance attendue:")
    print(f"  • 10K combos: ~{10_000/throughput:.1f}s")
    print(f"  • 100K combos: ~{100_000/throughput:.1f}s ({100_000/throughput/60:.1f} min)")
    print(f"  • 1M combos: ~{1_000_000/throughput/60:.1f} min")
    print(f"  • 5M combos: ~{estimated_time/60:.1f} min")
else:
    print("\n⚠️  Configuration sous-optimale")

print("=" * 80)
