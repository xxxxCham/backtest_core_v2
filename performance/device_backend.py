"""
Module-ID: performance.device_backend

Purpose: Backend abstrait NumPy (CPU-only) pour calculs vectorisés.

Role in pipeline: performance optimization

Key components: ArrayBackend, DeviceType enum, DeviceInfo, cpu_context()

Inputs: NumPy array, device_type (CPU uniquement)

Outputs: Operations via API unifiée (solve, dot, reduce, etc.)

Dependencies: numpy, contextmanager

Conventions: Mode CPU-only strict, aucun basculement GPU.

Read-if: Modification device switching ou operation dispatch.

Skip-if: Vous appelez backend = ArrayBackend.create() → backend.dot().
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class DeviceType(Enum):
    """Type de device pour les calculs."""
    CPU = "cpu"
    GPU = "gpu"
    AUTO = "auto"


@dataclass
class DeviceInfo:
    """Informations sur un device."""
    device_type: DeviceType
    name: str
    memory_total: Optional[int] = None  # En bytes
    memory_free: Optional[int] = None
    compute_capability: Optional[Tuple[int, int]] = None

    def __str__(self) -> str:
        if self.device_type == DeviceType.CPU:
            return f"CPU: {self.name}"
        mem_gb = (self.memory_total or 0) / (1024**3)
        return f"GPU: {self.name} ({mem_gb:.1f} GB)"


class ArrayBackend:
    """
    Backend abstrait pour calculs sur arrays.

    Fournit une API unifiée compatible NumPy.
    """

    _instance: Optional["ArrayBackend"] = None
    _initialized: bool = False

    def __new__(cls) -> "ArrayBackend":
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialise le backend."""
        if self._initialized:
            return

        self._device_type = DeviceType.CPU
        self._np = np  # NumPy uniquement (CPU-only)
        self._gpu_available = False
        self._device_info: Optional[DeviceInfo] = None

        # CPU-only strict: initialiser le backend CPU uniquement
        self._setup_cpu()

        self._initialized = True

    def _setup_cpu(self):
        """Configure le backend CPU."""
        import platform

        self._device_type = DeviceType.CPU
        self._np = np
        self._gpu_available = False
        self._device_info = DeviceInfo(
            device_type=DeviceType.CPU,
            name=platform.processor() or "Unknown CPU",
        )

    @property
    def device_type(self) -> DeviceType:
        """Retourne le type de device actuel."""
        return self._device_type

    @property
    def device_info(self) -> DeviceInfo:
        """Retourne les infos du device."""
        return self._device_info

    @property
    def gpu_available(self) -> bool:
        """Indique si un GPU est disponible."""
        return False

    @property
    def xp(self):
        """
        Retourne le module array (NumPy).

        Utilisez comme: backend.xp.array([1,2,3])
        """
        return self._np

    def use_device(self, device: DeviceType) -> bool:
        """
        Change le device actif.

        Args:
            device: Type de device souhaité

        Returns:
            True si le changement a réussi
        """
        if device == DeviceType.AUTO:
            device = DeviceType.CPU

        if device == DeviceType.GPU:
            logger.warning("GPU désactivé (mode CPU-only), utilisation CPU")
            device = DeviceType.CPU

        self._np = np
        self._device_type = DeviceType.CPU
        return True

    @contextmanager
    def device_context(self, device: DeviceType):
        """
        Context manager pour changer temporairement de device.

        Example:
            >>> with backend.device_context(DeviceType.GPU):
            >>>     result = backend.xp.sum(data)
        """
        old_device = self._device_type
        old_np = self._np

        try:
            self.use_device(device)
            yield
        finally:
            self._device_type = old_device
            self._np = old_np

    # === Array Operations ===

    def array(self, data, dtype=None) -> Any:
        """Crée un array sur le device actif."""
        return self._np.array(data, dtype=dtype)

    def zeros(self, shape, dtype=None) -> Any:
        """Crée un array de zéros."""
        return self._np.zeros(shape, dtype=dtype)

    def ones(self, shape, dtype=None) -> Any:
        """Crée un array de uns."""
        return self._np.ones(shape, dtype=dtype)

    def empty(self, shape, dtype=None) -> Any:
        """Crée un array non initialisé."""
        return self._np.empty(shape, dtype=dtype)

    def arange(self, *args, **kwargs) -> Any:
        """Crée une séquence."""
        return self._np.arange(*args, **kwargs)

    def linspace(self, *args, **kwargs) -> Any:
        """Crée un espace linéaire."""
        return self._np.linspace(*args, **kwargs)

    # === Math Operations ===

    def sum(self, a, axis=None, **kwargs) -> Any:
        """Somme."""
        return self._np.sum(a, axis=axis, **kwargs)

    def mean(self, a, axis=None, **kwargs) -> Any:
        """Moyenne."""
        return self._np.mean(a, axis=axis, **kwargs)

    def std(self, a, axis=None, **kwargs) -> Any:
        """Écart-type."""
        return self._np.std(a, axis=axis, **kwargs)

    def var(self, a, axis=None, **kwargs) -> Any:
        """Variance."""
        return self._np.var(a, axis=axis, **kwargs)

    def min(self, a, axis=None, **kwargs) -> Any:
        """Minimum."""
        return self._np.min(a, axis=axis, **kwargs)

    def max(self, a, axis=None, **kwargs) -> Any:
        """Maximum."""
        return self._np.max(a, axis=axis, **kwargs)

    def sqrt(self, x) -> Any:
        """Racine carrée."""
        return self._np.sqrt(x)

    def exp(self, x) -> Any:
        """Exponentielle."""
        return self._np.exp(x)

    def log(self, x) -> Any:
        """Logarithme naturel."""
        return self._np.log(x)

    def abs(self, x) -> Any:
        """Valeur absolue."""
        return self._np.abs(x)

    def clip(self, a, a_min, a_max) -> Any:
        """Clip values."""
        return self._np.clip(a, a_min, a_max)

    def diff(self, a, n=1, axis=-1) -> Any:
        """Différences."""
        return self._np.diff(a, n=n, axis=axis)

    def cumsum(self, a, axis=None) -> Any:
        """Somme cumulative."""
        return self._np.cumsum(a, axis=axis)

    def cumprod(self, a, axis=None) -> Any:
        """Produit cumulatif."""
        return self._np.cumprod(a, axis=axis)

    # === Comparison Operations ===

    def where(self, condition, x, y) -> Any:
        """Where conditionnel."""
        return self._np.where(condition, x, y)

    def argmax(self, a, axis=None) -> Any:
        """Index du maximum."""
        return self._np.argmax(a, axis=axis)

    def argmin(self, a, axis=None) -> Any:
        """Index du minimum."""
        return self._np.argmin(a, axis=axis)

    def maximum(self, x1, x2) -> Any:
        """Maximum element-wise."""
        return self._np.maximum(x1, x2)

    def minimum(self, x1, x2) -> Any:
        """Minimum element-wise."""
        return self._np.minimum(x1, x2)

    # === Rolling Operations ===

    def rolling_mean(self, data: Any, window: int) -> Any:
        """
        Moyenne mobile.

        Note: Cette opération est optimisée pour GPU via convolution.
        """
        if len(data) < window:
            return self._np.full(len(data), self._np.nan)

        # Utiliser convolve pour efficacité
        kernel = self._np.ones(window) / window
        result = self._np.convolve(data, kernel, mode='full')[:len(data)]
        result[:window-1] = self._np.nan

        return result

    def rolling_std(self, data: Any, window: int) -> Any:
        """
        Écart-type mobile.
        """
        n = len(data)
        if n < window:
            return self._np.full(n, self._np.nan)

        result = self._np.empty(n)
        result[:window-1] = self._np.nan

        for i in range(window - 1, n):
            result[i] = self._np.std(data[i-window+1:i+1])

        return result

    def rolling_max(self, data: Any, window: int) -> Any:
        """Maximum mobile."""
        n = len(data)
        if n < window:
            return self._np.full(n, self._np.nan)

        result = self._np.empty(n)
        result[:window-1] = self._np.nan

        for i in range(window - 1, n):
            result[i] = self._np.max(data[i-window+1:i+1])

        return result

    def rolling_min(self, data: Any, window: int) -> Any:
        """Minimum mobile."""
        n = len(data)
        if n < window:
            return self._np.full(n, self._np.nan)

        result = self._np.empty(n)
        result[:window-1] = self._np.nan

        for i in range(window - 1, n):
            result[i] = self._np.min(data[i-window+1:i+1])

        return result

    # === Conversion ===

    def to_numpy(self, arr) -> np.ndarray:
        """Convertit en numpy array (CPU-only)."""
        return np.asarray(arr)

    def from_numpy(self, arr: np.ndarray) -> Any:
        """Convertit numpy vers device actif (CPU-only)."""
        return arr

    # === Memory Management ===

    def memory_info(self) -> dict:
        """Retourne les infos mémoire du device."""
        import psutil
        mem = psutil.virtual_memory()
        return {
            "device": "CPU",
            "free": mem.available,
            "total": mem.total,
            "used": mem.used,
        }

    def clear_memory(self):
        """Libère la mémoire (CPU-only)."""
        return None


# Singleton global
_backend: Optional[ArrayBackend] = None


def get_backend() -> ArrayBackend:
    """Retourne le backend singleton."""
    global _backend
    if _backend is None:
        _backend = ArrayBackend()
    return _backend


def use_gpu(enable: bool = True) -> bool:
    """
    Active ou désactive l'utilisation du GPU.

    Args:
        enable: True pour GPU, False pour CPU

    Returns:
        True si le changement a réussi
    """
    backend = get_backend()
    device = DeviceType.GPU if enable else DeviceType.CPU
    return backend.use_device(device)


def use_cpu() -> bool:
    """Force l'utilisation du CPU."""
    return use_gpu(False)


def is_gpu_available() -> bool:
    """Vérifie si un GPU est disponible."""
    return get_backend().gpu_available


def get_device_info() -> DeviceInfo:
    """Retourne les infos du device actuel."""
    return get_backend().device_info


@contextmanager
def gpu_context():
    """Context manager CPU-only (GPU désactivé)."""
    backend = get_backend()
    with backend.device_context(DeviceType.CPU):
        yield backend


@contextmanager
def cpu_context():
    """Context manager pour utiliser temporairement le CPU."""
    backend = get_backend()
    with backend.device_context(DeviceType.CPU):
        yield backend


def array_like(data, dtype=None):
    """Crée un array sur le device actif."""
    return get_backend().array(data, dtype=dtype)


__all__ = [
    "DeviceType",
    "DeviceInfo",
    "ArrayBackend",
    "get_backend",
    "use_gpu",
    "use_cpu",
    "is_gpu_available",
    "get_device_info",
    "gpu_context",
    "cpu_context",
    "array_like",
]
