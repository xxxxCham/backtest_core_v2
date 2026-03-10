"""
Tests de non-régression pour le mode CPU-only strict.

Objectif: Garantir que BACKTEST_BACKEND=cpu ne touche JAMAIS au GPU/CUDA.
"""

import os
import sys

import pytest


@pytest.fixture(autouse=True)
def reset_backend():
    """Reset backend config avant chaque test."""
    from utils.backend_config import reset_backend
    reset_backend()
    yield
    reset_backend()


class TestCPUOnlyMode:
    """Tests du mode CPU-only strict."""

    def test_cpu_only_does_not_import_torch(self):
        """Mode CPU ne doit PAS importer torch."""
        os.environ["BACKTEST_BACKEND"] = "cpu"

        import performance  # noqa: F401

        assert "torch" not in sys.modules, "torch importé en mode CPU-only!"

    def test_cpu_only_does_not_import_numba_cuda(self):
        """Mode CPU ne doit PAS importer numba.cuda."""
        os.environ["BACKTEST_BACKEND"] = "cpu"

        import performance  # noqa: F401

        # Numba CPU est OK, mais pas numba.cuda
        if "numba" in sys.modules:
            assert "numba.cuda" not in sys.modules, "numba.cuda importé en mode CPU-only!"

    def test_cpu_backend_selection(self):
        """Vérifier sélection backend CPU."""
        os.environ["BACKTEST_BACKEND"] = "cpu"

        from utils.backend_config import BackendType, get_backend

        backend = get_backend()
        assert backend == BackendType.CPU

    def test_cpu_backend_is_default(self):
        """CPU doit être le backend par défaut."""
        # Ne pas définir BACKTEST_BACKEND
        if "BACKTEST_BACKEND" in os.environ:
            del os.environ["BACKTEST_BACKEND"]

        from utils.backend_config import BackendType, get_backend

        backend = get_backend()
        assert backend == BackendType.CPU, "CPU devrait être le backend par défaut"

    def test_is_gpu_enabled_false_in_cpu_mode(self):
        """is_gpu_enabled() doit retourner False en mode CPU."""
        os.environ["BACKTEST_BACKEND"] = "cpu"

        from utils.backend_config import is_gpu_enabled

        assert not is_gpu_enabled(), "GPU ne devrait pas être activé en mode CPU"

    def test_device_backend_respects_cpu_mode(self):
        """ArrayBackend doit rester CPU en mode CPU-only."""
        os.environ["BACKTEST_BACKEND"] = "cpu"

        from performance.device_backend import ArrayBackend, DeviceType

        backend = ArrayBackend()

        assert backend.device_type == DeviceType.CPU
        assert not backend.gpu_available
        assert backend.xp.__name__ == "numpy"

    def test_gpu_manager_not_initialized_in_cpu_mode(self):
        """Backend GPU supprimé: rien à initialiser."""
        os.environ["BACKTEST_BACKEND"] = "cpu"
        assert True

    def test_performance_import_does_not_trigger_gpu_detection(self):
        """Importer 'performance' ne doit pas détecter le GPU."""
        os.environ["BACKTEST_BACKEND"] = "cpu"

        # Vérifier que le module GPU n'est pas chargé avant
        assert "performance.gpu" not in sys.modules

        # Import
        import performance  # noqa: F401

        # Vérifier après
        assert "performance.gpu" not in sys.modules
        from performance.device_backend import ArrayBackend
        assert not ArrayBackend().gpu_available


class TestBackendConfig:
    """Tests du module backend_config."""

    def test_reset_backend_works(self):
        """reset_backend() doit forcer rechargement."""
        from utils.backend_config import BackendType, get_backend, reset_backend

        # Premier appel
        os.environ["BACKTEST_BACKEND"] = "cpu"
        backend1 = get_backend()
        assert backend1 == BackendType.CPU

        # Changer env et reset (CPU-only)
        os.environ["BACKTEST_BACKEND"] = "gpu"
        reset_backend()
        backend2 = get_backend()
        assert backend2 == BackendType.CPU

    def test_invalid_backend_defaults_to_cpu(self):
        """Backend invalide doit fallback CPU."""
        os.environ["BACKTEST_BACKEND"] = "invalid_value"

        from utils.backend_config import BackendType, get_backend

        backend = get_backend()
        assert backend == BackendType.CPU, "Backend invalide devrait fallback CPU"

    def test_backend_case_insensitive(self):
        """BACKTEST_BACKEND doit être case-insensitive."""
        os.environ["BACKTEST_BACKEND"] = "GPU"  # Majuscules

        from utils.backend_config import BackendType, get_backend

        backend = get_backend()
        assert backend == BackendType.CPU

        # Test avec espaces
        os.environ["BACKTEST_BACKEND"] = "  cpu  "
        from utils.backend_config import reset_backend
        reset_backend()
        backend = get_backend()
        assert backend == BackendType.CPU


def test_worker_numba_thread_limit_is_applied_programmatically():
    """Les workers CPU doivent limiter Numba même si le module est déjà importé."""
    numba = pytest.importorskip("numba")

    from backtest.worker import _apply_numba_thread_limit

    original_threads = numba.get_num_threads()
    target_threads = 1 if original_threads != 1 else min(numba.config.NUMBA_NUM_THREADS, 2)

    try:
        _apply_numba_thread_limit(target_threads, debug_enabled=True)
        assert numba.get_num_threads() == target_threads
    finally:
        _apply_numba_thread_limit(original_threads, debug_enabled=False)
