"""
Script de validation CPU-only mode.

Vérifie que le mode CPU-only respecte toutes les contraintes :
- Aucun import CuPy/torch/numba.cuda
- Backend correctement configuré
- Performance non dégradée
"""

import os
import sys
from pathlib import Path

# Ajouter repo à PYTHONPATH
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))


def print_header(text: str):
    """Affiche un header."""
    print(f"\n{'='*70}")
    print(f"  {text}")
    print('='*70)


def print_success(text: str):
    """Affiche un succès."""
    print(f"✅ {text}")


def print_error(text: str):
    """Affiche une erreur."""
    print(f"❌ {text}")


def print_warning(text: str):
    """Affiche un warning."""
    print(f"⚠️  {text}")


def check_backend_config():
    """Vérifie la configuration du backend."""
    print_header("Vérification Backend Config")

    # Forcer mode CPU
    os.environ["BACKTEST_BACKEND"] = "cpu"

    from utils.backend_config import BackendType, get_backend, is_gpu_enabled

    backend = get_backend()

    if backend == BackendType.CPU:
        print_success(f"Backend configuré: {backend.value}")
    else:
        print_error(f"Backend incorrect: {backend.value} (attendu: cpu)")
        return False

    if not is_gpu_enabled():
        print_success("GPU désactivé (is_gpu_enabled=False)")
    else:
        print_error("GPU activé alors que mode CPU-only!")
        return False

    return True


def check_no_gpu_imports():
    """Vérifie qu'aucun module GPU n'est importé."""
    print_header("Vérification Imports GPU")

    # Snapshot modules avant
    before = set(sys.modules.keys())

    # Import principal
    import performance  # noqa: F401

    # Snapshot après
    after = set(sys.modules.keys())
    new_modules = after - before

    # Modules GPU interdits
    forbidden = {"cupy", "torch", "numba.cuda"}

    violations = []
    for mod in new_modules:
        for forbidden_mod in forbidden:
            if forbidden_mod in mod:
                violations.append(mod)

    if not violations:
        print_success("Aucun import GPU détecté")
        return True
    else:
        print_error(f"Modules GPU importés: {violations}")
        return False


def check_device_backend():
    """Vérifie ArrayBackend reste CPU."""
    print_header("Vérification ArrayBackend")

    from performance.device_backend import ArrayBackend, DeviceType

    backend = ArrayBackend()

    checks = []

    # Check 1: Device type
    if backend.device_type == DeviceType.CPU:
        print_success(f"Device type: {backend.device_type.value}")
        checks.append(True)
    else:
        print_error(f"Device type incorrect: {backend.device_type.value}")
        checks.append(False)

    # Check 2: GPU available
    if not backend.gpu_available:
        print_success("GPU marqué comme non disponible")
        checks.append(True)
    else:
        print_error("GPU marqué comme disponible!")
        checks.append(False)

    # Check 3: Module array = numpy
    if backend.xp.__name__ == "numpy":
        print_success(f"Module array: {backend.xp.__name__}")
        checks.append(True)
    else:
        print_error(f"Module array incorrect: {backend.xp.__name__}")
        checks.append(False)

    return all(checks)


def check_gpu_manager():
    """Vérifie GPUDeviceManager non initialisé."""
    print_header("Vérification GPUDeviceManager")

    from performance.gpu import get_gpu_manager

    manager = get_gpu_manager()

    if manager is None:
        print_success("GPUDeviceManager non initialisé (lazy)")
        return True
    else:
        print_error("GPUDeviceManager initialisé en mode CPU-only!")
        return False


def check_numba_cache():
    """Vérifie .numba_cache dans .gitignore."""
    print_header("Vérification .numba_cache")

    gitignore_path = repo_root / ".gitignore"

    if not gitignore_path.exists():
        print_warning(".gitignore absent")
        return False

    content = gitignore_path.read_text()

    if ".numba_cache/" in content:
        print_success(".numba_cache/ dans .gitignore")
        return True
    else:
        print_error(".numba_cache/ absent de .gitignore")
        return False


def check_tests_exist():
    """Vérifie tests de non-régression présents."""
    print_header("Vérification Tests")

    test_file = repo_root / "tests" / "test_backend_cpu_only.py"

    if test_file.exists():
        print_success(f"Fichier de tests présent: {test_file.name}")

        # Compter tests
        content = test_file.read_text()
        test_count = content.count("def test_")

        print_success(f"Nombre de tests: {test_count}")
        return True
    else:
        print_error("Fichier de tests absent!")
        return False


def run_quick_benchmark():
    """Benchmark rapide pour vérifier performance."""
    print_header("Benchmark Rapide")

    try:
        import time

        import numpy as np

        from backtest.simulator_fast import HAS_NUMBA

        if not HAS_NUMBA:
            print_warning("Numba non disponible, benchmark skipped")
            return True

        # Générer données test
        n = 10000
        closes = np.random.randn(n).cumsum() + 100
        highs = closes + np.abs(np.random.randn(n))
        lows = closes - np.abs(np.random.randn(n))
        signals = np.random.choice([-1, 0, 1], size=n)

        # Warm-up JIT
        from backtest.simulator_fast import simulate_trades_fast
        import pandas as pd

        df_test = pd.DataFrame({
            "close": closes[:100],
            "high": highs[:100],
            "low": lows[:100],
        })
        _ = simulate_trades_fast(df_test, signals[:100], {"leverage": 1, "k_sl": 2})

        # Benchmark
        df_bench = pd.DataFrame({
            "close": closes,
            "high": highs,
            "low": lows,
        })

        start = time.perf_counter()
        _ = simulate_trades_fast(df_bench, signals, {"leverage": 1, "k_sl": 2})
        elapsed = time.perf_counter() - start

        print_success(f"Simulation {n} barres: {elapsed*1000:.2f}ms")

        if elapsed < 0.1:  # < 100ms = acceptable
            print_success("Performance acceptable")
            return True
        else:
            print_warning(f"Performance lente: {elapsed*1000:.0f}ms")
            return False

    except Exception as e:
        print_error(f"Erreur benchmark: {e}")
        return False


def main():
    """Exécute toutes les vérifications."""
    print_header("🔍 Validation CPU-Only Mode")
    print(f"Repo: {repo_root}")
    print(f"Python: {sys.version.split()[0]}")

    # Forcer backend CPU
    os.environ["BACKTEST_BACKEND"] = "cpu"

    checks = [
        ("Backend Config", check_backend_config),
        ("Imports GPU", check_no_gpu_imports),
        ("Device Backend", check_device_backend),
        ("GPU Manager", check_gpu_manager),
        (".numba_cache", check_numba_cache),
        ("Tests", check_tests_exist),
        ("Performance", run_quick_benchmark),
    ]

    results = []

    for name, check_fn in checks:
        try:
            result = check_fn()
            results.append((name, result))
        except Exception as e:
            print_error(f"Exception: {e}")
            results.append((name, False))

    # Résumé
    print_header("📊 Résumé")

    success_count = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅" if result else "❌"
        print(f"{status} {name}")

    print()
    if success_count == total:
        print_success(f"VALIDATION RÉUSSIE ({success_count}/{total})")
        return 0
    else:
        print_error(f"VALIDATION ÉCHOUÉE ({success_count}/{total})")
        return 1


if __name__ == "__main__":
    sys.exit(main())
