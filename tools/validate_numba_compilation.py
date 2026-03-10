"""
Valide la compilation Numba des kernels critiques.

Usage:
    python tools/validate_numba_compilation.py
"""
import sys
from pathlib import Path

# Ajouter project root au path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import numpy as np

def validate_kernel_compilation():
    """Valide que les kernels Numba compilent correctement en mode nopython."""
    print("🔍 Validation compilation Numba...")
    print("=" * 60)

    results = []

    # Test 1: _sweep_bollinger_full
    try:
        from backtest.sweep_numba import _sweep_bollinger_full

        closes = np.random.rand(1000).astype(np.float64)
        highs = closes * 1.01
        lows = closes * 0.99
        bb_periods = np.array([20, 25], dtype=np.float64)
        bb_stds = np.array([2.0, 2.5], dtype=np.float64)
        entry_zs = np.array([2.0, 2.5], dtype=np.float64)
        leverages = np.array([1.0, 1.0], dtype=np.float64)
        k_sls = np.array([1.5, 2.0], dtype=np.float64)

        # Forcer compilation JIT
        result = _sweep_bollinger_full(
            closes, highs, lows,
            bb_periods, bb_stds, entry_zs,
            leverages, k_sls,
            10000.0, 10.0, 5.0
        )

        # Vérifier signatures compilées
        sigs = _sweep_bollinger_full.signatures
        if len(sigs) > 0:
            results.append(("✅ _sweep_bollinger_full", f"{len(sigs)} signature(s)", True))
        else:
            results.append(("❌ _sweep_bollinger_full", "Non compilé (object mode?)", False))

    except Exception as e:
        results.append(("❌ _sweep_bollinger_full", f"Erreur: {e}", False))

    # Test 2: _simulate_trades_numba
    try:
        from backtest.simulator_fast import _simulate_trades_numba, HAS_NUMBA

        if not HAS_NUMBA:
            results.append(("⚠️ _simulate_trades_numba", "Numba non disponible", False))
        else:
            closes = np.random.rand(1000).astype(np.float64)
            highs = closes * 1.01
            lows = closes * 0.99
            signals = np.random.choice([-1, 0, 1], size=1000).astype(np.float64)

            # Forcer compilation
            result = _simulate_trades_numba(
                closes, highs, lows, signals,
                1.0, 1.5, 10000.0, 10.0, 5.0
            )

            sigs = _simulate_trades_numba.signatures
            if len(sigs) > 0:
                results.append(("✅ _simulate_trades_numba", f"{len(sigs)} signature(s)", True))
            else:
                results.append(("❌ _simulate_trades_numba", "Non compilé", False))

    except Exception as e:
        results.append(("❌ _simulate_trades_numba", f"Erreur: {e}", False))

    # Test 3: _sweep_ema_cross_full
    try:
        from backtest.sweep_numba import _sweep_ema_cross_full

        closes = np.random.rand(1000).astype(np.float64)
        highs = closes * 1.01
        lows = closes * 0.99
        fast_periods = np.array([12, 15], dtype=np.float64)
        slow_periods = np.array([26, 30], dtype=np.float64)
        leverages = np.array([1.0, 1.0], dtype=np.float64)
        k_sls = np.array([1.5, 2.0], dtype=np.float64)

        result = _sweep_ema_cross_full(
            closes, highs, lows,
            fast_periods, slow_periods,
            leverages, k_sls,
            10000.0, 10.0, 5.0
        )

        sigs = _sweep_ema_cross_full.signatures
        if len(sigs) > 0:
            results.append(("✅ _sweep_ema_cross_full", f"{len(sigs)} signature(s)", True))
        else:
            results.append(("❌ _sweep_ema_cross_full", "Non compilé", False))

    except Exception as e:
        results.append(("❌ _sweep_ema_cross_full", f"Erreur: {e}", False))

    # Test 4: _sweep_rsi_reversal_full
    try:
        from backtest.sweep_numba import _sweep_rsi_reversal_full

        closes = np.random.rand(1000).astype(np.float64)
        highs = closes * 1.01
        lows = closes * 0.99
        rsi_periods = np.array([14, 21], dtype=np.float64)
        overboughts = np.array([70, 75], dtype=np.float64)
        oversolds = np.array([30, 25], dtype=np.float64)
        leverages = np.array([1.0, 1.0], dtype=np.float64)
        k_sls = np.array([1.5, 2.0], dtype=np.float64)

        result = _sweep_rsi_reversal_full(
            closes, highs, lows,
            rsi_periods, overboughts, oversolds,
            leverages, k_sls,
            10000.0, 10.0, 5.0
        )

        sigs = _sweep_rsi_reversal_full.signatures
        if len(sigs) > 0:
            results.append(("✅ _sweep_rsi_reversal_full", f"{len(sigs)} signature(s)", True))
        else:
            results.append(("❌ _sweep_rsi_reversal_full", "Non compilé", False))

    except Exception as e:
        results.append(("❌ _sweep_rsi_reversal_full", f"Erreur: {e}", False))

    # Afficher résultats
    print("\nRÉSULTATS DE VALIDATION")
    print("=" * 60)

    all_ok = True
    for status, detail, ok in results:
        print(f"{status:<35} {detail}")
        if not ok:
            all_ok = False

    print("=" * 60)

    if all_ok:
        print("✅ SUCCÈS: Tous les kernels compilent en mode nopython")
        return 0
    else:
        print("❌ ÉCHEC: Certains kernels ont des problèmes de compilation")
        return 1


def check_numba_config():
    """Affiche la configuration Numba."""
    try:
        import numba
        print("\n📋 CONFIGURATION NUMBA")
        print("=" * 60)
        print(f"Version Numba: {numba.__version__}")
        print(f"Threading layer: {numba.config.THREADING_LAYER}")
        print(f"CPU count: {numba.config.NUMBA_NUM_THREADS}")
        print(f"Cache enabled: {numba.config.CACHE_DIR is not None}")
        if numba.config.CACHE_DIR:
            print(f"Cache directory: {numba.config.CACHE_DIR}")
        print("=" * 60)
    except Exception as e:
        print(f"⚠️ Impossible d'afficher config Numba: {e}")


def check_memory_allocations():
    """Détecte les allocations mémoire dans les kernels."""
    print("\n🔍 DÉTECTION ALLOCATIONS MÉMOIRE")
    print("=" * 60)

    import inspect
    from backtest import sweep_numba

    kernels = [
        ('_sweep_bollinger_full', sweep_numba._sweep_bollinger_full),
        ('_sweep_ema_cross_full', sweep_numba._sweep_ema_cross_full),
        ('_sweep_rsi_reversal_full', sweep_numba._sweep_rsi_reversal_full),
    ]

    for name, kernel in kernels:
        try:
            source = inspect.getsource(kernel)
            # Chercher np.zeros, np.empty, np.array dans prange
            lines = source.split('\n')
            in_prange = False
            allocations = []

            for i, line in enumerate(lines):
                if 'prange(' in line:
                    in_prange = True
                if in_prange and ('np.zeros' in line or 'np.empty' in line or 'np.array(' in line):
                    allocations.append((i+1, line.strip()))

            if allocations:
                print(f"⚠️ {name}: {len(allocations)} allocation(s) dans prange")
                for lineno, code in allocations[:3]:  # Montrer max 3
                    print(f"   Ligne ~{lineno}: {code[:60]}...")
            else:
                print(f"✅ {name}: Pas d'allocations dans prange")

        except Exception as e:
            print(f"⚠️ {name}: Impossible d'analyser ({e})")

    print("=" * 60)


if __name__ == "__main__":
    check_numba_config()
    check_memory_allocations()
    exit_code = validate_kernel_compilation()

    print("\n💡 RECOMMANDATIONS")
    print("=" * 60)
    print("Voir: .tmp_diagnostic_numba_performance.md")
    print("     → Optimisations détaillées avec code patches")
    print("=" * 60)

    sys.exit(exit_code)
