#!/usr/bin/env python
"""
Diagnostic complet du crash Numba sweep.
Teste chaque étape isolément pour identifier le point de blocage.
"""
import os
import sys
import time
import traceback

import psutil

# Configurer l'environnement AVANT les imports Numba
os.environ['NUMBA_NUM_THREADS'] = '16'  # Réduire à 16 (physiques) au lieu de 32 (SMT)
os.environ['NUMBA_THREADING_LAYER'] = 'omp'  # OpenMP plus stable que TBB
os.environ['OMP_NUM_THREADS'] = '16'

def print_status(step: str, status: str = "...", flush: bool = True):
    """Affiche le status avec horodatage."""
    timestamp = time.strftime("%H:%M:%S")
    mem = psutil.Process().memory_info().rss / (1024**3)
    cpu = psutil.cpu_percent(interval=0.1)
    print(f"[{timestamp}] [{cpu:5.1f}% CPU] [{mem:.1f} GB RAM] {step}: {status}", flush=flush)

print("=" * 70)
print("DIAGNOSTIC CRASH NUMBA SWEEP")
print("=" * 70)

# ============================================================================
# ÉTAPE 1: Vérifier la mémoire et CPU disponibles
# ============================================================================
print_status("Étape 1", "Vérification système")
mem = psutil.virtual_memory()
print(f"  RAM totale: {mem.total / (1024**3):.1f} GB")
print(f"  RAM disponible: {mem.available / (1024**3):.1f} GB ({mem.percent}% utilisé)")
print(f"  CPU cores: {psutil.cpu_count(logical=False)} physiques, {psutil.cpu_count(logical=True)} logiques")

if mem.available < 4 * 1024**3:  # < 4 GB
    print("⚠️ ATTENTION: Moins de 4 GB de RAM disponible!")
    print("   Fermez des applications avant de continuer.")
    sys.exit(1)
print_status("Étape 1", "✅ OK")

# ============================================================================
# ÉTAPE 2: Import des modules (sans JIT)
# ============================================================================
print_status("Étape 2", "Imports de base")
try:
    import numpy as np
    import pandas as pd
    print_status("Étape 2", "✅ numpy/pandas OK")
except Exception as e:
    print_status("Étape 2", f"❌ ÉCHEC: {e}")
    sys.exit(1)

# ============================================================================
# ÉTAPE 3: Import Numba (déclenche compilation potentielle)
# ============================================================================
print_status("Étape 3", "Import Numba")
try:
    import numba
    print(f"  Numba version: {numba.__version__}")
    print(f"  NUMBA_NUM_THREADS: {os.environ.get('NUMBA_NUM_THREADS', 'non défini')}")
    print_status("Étape 3", "✅ Numba importé")
except Exception as e:
    print_status("Étape 3", f"❌ ÉCHEC: {e}")
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# ÉTAPE 4: Charger les données
# ============================================================================
print_status("Étape 4", "Chargement données")
try:
    # Chercher un fichier parquet
    data_dir = os.environ.get('BACKTEST_DATA_DIR', 'd:/data')
    parquet_files = []
    for root, dirs, files in os.walk(data_dir):
        for f in files:
            if f.endswith('.parquet'):
                parquet_files.append(os.path.join(root, f))
        if parquet_files:
            break

    if not parquet_files:
        print("  Aucun fichier parquet trouvé, création données synthétiques...")
        n_bars = 10000
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(n_bars) * 0.5)
        df = pd.DataFrame({
            'open': close * (1 + np.random.randn(n_bars) * 0.001),
            'high': close * (1 + np.abs(np.random.randn(n_bars)) * 0.005),
            'low': close * (1 - np.abs(np.random.randn(n_bars)) * 0.005),
            'close': close,
            'volume': np.random.randint(1000, 10000, n_bars),
        })
    else:
        data_file = parquet_files[0]
        print(f"  Chargement: {data_file}")
        df = pd.read_parquet(data_file)

    n_bars = len(df)
    print(f"  Lignes chargées: {n_bars:,}")
    print(f"  Colonnes: {list(df.columns)}")
    print_status("Étape 4", "✅ Données prêtes")
except Exception as e:
    print_status("Étape 4", f"❌ ÉCHEC: {e}")
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# ÉTAPE 5: Extraction arrays numpy
# ============================================================================
print_status("Étape 5", "Extraction arrays")
try:
    closes = df['close'].values.astype(np.float64)
    highs = df['high'].values.astype(np.float64)
    lows = df['low'].values.astype(np.float64)

    print(f"  closes: shape={closes.shape}, dtype={closes.dtype}")
    print(f"  highs: shape={highs.shape}, dtype={highs.dtype}")
    print(f"  lows: shape={lows.shape}, dtype={lows.dtype}")
    print_status("Étape 5", "✅ Arrays extraits")
except Exception as e:
    print_status("Étape 5", f"❌ ÉCHEC: {e}")
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# ÉTAPE 6: Import sweep_numba (déclenche JIT compilation)
# ============================================================================
print_status("Étape 6", "Import sweep_numba")
print("  ⚠️ Cette étape peut prendre 30-60 secondes à la première exécution (JIT)...")
try:
    start = time.perf_counter()
    from backtest.sweep_numba import run_numba_sweep
    elapsed = time.perf_counter() - start
    print(f"  Import terminé en {elapsed:.2f}s")
    print_status("Étape 6", "✅ sweep_numba importé")
except Exception as e:
    print_status("Étape 6", f"❌ ÉCHEC: {e}")
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# ÉTAPE 7: Test avec une PETITE grille (3 combos)
# ============================================================================
print_status("Étape 7", "Test micro-sweep (3 combos)")
try:
    param_grid = [
        {'bb_period': 20, 'bb_std': 2.0, 'entry_z': 2.0, 'leverage': 1.0, 'k_sl': 1.5},
        {'bb_period': 25, 'bb_std': 2.5, 'entry_z': 2.0, 'leverage': 1.0, 'k_sl': 1.5},
        {'bb_period': 30, 'bb_std': 3.0, 'entry_z': 2.0, 'leverage': 1.0, 'k_sl': 1.5},
    ]

    start = time.perf_counter()
    results = run_numba_sweep(
        df=df,
        strategy_key='bollinger_atr',
        param_grid=param_grid,
        initial_capital=10000.0,
        fees_bps=10.0,
        slippage_bps=5.0,
    )
    elapsed = time.perf_counter() - start

    print(f"  Résultats: {len(results)} configs")
    for i, r in enumerate(results):
        print(f"    [{i}] PnL=${r['total_pnl']:,.2f}, Sharpe={r['sharpe_ratio']:.2f}")
    print(f"  Temps: {elapsed:.3f}s ({len(param_grid)/elapsed:,.0f} bt/s)")
    print_status("Étape 7", "✅ Micro-sweep OK")
except Exception as e:
    print_status("Étape 7", f"❌ ÉCHEC: {e}")
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# ÉTAPE 8: Test avec une grille MOYENNE (100 combos)
# ============================================================================
print_status("Étape 8", "Test sweep moyen (100 combos)")
try:
    param_grid = [
        {'bb_period': float(bb), 'bb_std': float(std), 'entry_z': 2.0, 'leverage': 1.0, 'k_sl': 1.5}
        for bb in range(10, 30, 2)  # 10 valeurs
        for std in [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]  # 10 valeurs
    ]  # = 100 combos

    print(f"  Grille générée: {len(param_grid)} combinaisons")

    start = time.perf_counter()
    results = run_numba_sweep(
        df=df,
        strategy_key='bollinger_atr',
        param_grid=param_grid,
        initial_capital=10000.0,
        fees_bps=10.0,
        slippage_bps=5.0,
    )
    elapsed = time.perf_counter() - start

    best = max(results, key=lambda r: r['total_pnl'])
    print(f"  Meilleur PnL: ${best['total_pnl']:,.2f}")
    print(f"  Temps: {elapsed:.3f}s ({len(param_grid)/elapsed:,.0f} bt/s)")
    print_status("Étape 8", "✅ Sweep moyen OK")
except Exception as e:
    print_status("Étape 8", f"❌ ÉCHEC: {e}")
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# ÉTAPE 9: Test avec une GRANDE grille (1000 combos)
# ============================================================================
print_status("Étape 9", "Test sweep large (1000 combos)")
try:
    param_grid = [
        {'bb_period': float(bb), 'bb_std': float(std/10), 'entry_z': float(ez/10), 'leverage': 1.0, 'k_sl': 1.5}
        for bb in range(10, 35)  # 25 valeurs
        for std in range(15, 45, 3)  # 10 valeurs
        for ez in range(15, 35, 5)  # 4 valeurs
    ]  # = 1000 combos

    print(f"  Grille générée: {len(param_grid)} combinaisons")

    start = time.perf_counter()
    results = run_numba_sweep(
        df=df,
        strategy_key='bollinger_atr',
        param_grid=param_grid,
        initial_capital=10000.0,
        fees_bps=10.0,
        slippage_bps=5.0,
    )
    elapsed = time.perf_counter() - start

    best = max(results, key=lambda r: r['total_pnl'])
    print(f"  Meilleur PnL: ${best['total_pnl']:,.2f}")
    print(f"  Temps: {elapsed:.3f}s ({len(param_grid)/elapsed:,.0f} bt/s)")
    print_status("Étape 9", "✅ Sweep large OK")
except Exception as e:
    print_status("Étape 9", f"❌ ÉCHEC: {e}")
    traceback.print_exc()
    sys.exit(1)

# ============================================================================
# RÉSUMÉ
# ============================================================================
print()
print("=" * 70)
print("✅ DIAGNOSTIC COMPLET - TOUS LES TESTS PASSENT")
print("=" * 70)
print()
print("Si le système plante dans l'UI mais pas ici, le problème est:")
print("  1. Taille de la grille UI >> 1000 combos")
print("  2. Conflit avec le thread Streamlit")
print("  3. Autre module UI qui consomme RAM/CPU")
print()
print("Recommandations:")
print("  - Limiter les grilles UI à < 10,000 combos")
print("  - Utiliser NUMBA_NUM_THREADS=16 (physiques, pas SMT)")
print("  - Fermer les navigateurs/apps gourmandes")
