#!/usr/bin/env python
"""Test Numba avec OpenMP (alternative à TBB)"""

import os
import sys

# Configuration AVANT import numba
os.environ['NUMBA_NUM_THREADS'] = '32'
os.environ['NUMBA_THREADING_LAYER'] = 'omp'  # OpenMP au lieu de TBB
os.environ['OMP_NUM_THREADS'] = '32'

import time
import numpy as np
import numba

print("=" * 70)
print("TEST NUMBA avec OpenMP")
print("=" * 70)

print(f"\nNumba version: {numba.__version__}")
print(f"NumPy version: {np.__version__}")
print(f"Threading layer: {numba.config.THREADING_LAYER}")
print(f"Threads: {numba.config.NUMBA_NUM_THREADS}")

# Test prange
@numba.njit(parallel=True, fastmath=True)
def test_prange(n):
    total = 0.0
    for i in numba.prange(n):
        total += i * 2.0
    return total

try:
    print("\nTest prange...")
    result = test_prange(1000)
    print(f"✓ Result: {result:.0f}")
    print(f"✓ Threading layer actif: {numba.config.THREADING_LAYER}")

    # Benchmark
    n = 10_000_000
    start = time.perf_counter()
    _ = test_prange(n)
    elapsed = time.perf_counter() - start
    print(f"✓ Benchmark: {n:,} itérations en {elapsed*1000:.1f} ms")

except Exception as e:
    print(f"✗ Erreur: {e}")
    sys.exit(1)

print("\n" + "=" * 70)
print("✅ Configuration OK avec OpenMP")
print("=" * 70)
