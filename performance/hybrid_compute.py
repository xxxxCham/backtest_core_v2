"""
Module-ID: performance.hybrid_compute

Purpose: Calcul CPU-only - répartition simplifiée des tâches.

Role in pipeline: performance optimization

Key components: HybridCompute, task scheduling, CPU load balancing

Strategy:
  - CPU: Calculs vectoriels et logiques séquentielles
  - GPU: Désactivé (mode CPU-only)

Inputs: Arrays NumPy, opération type, taille dataset

Outputs: Résultat calculé sur CPU

Dependencies: numpy, numba, device_backend

Conventions: Mode CPU-only strict.

Read-if: Modification scheduling ou seuils.

Skip-if: Utilisation via HybridCompute.auto_compute().
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

from performance.device_backend import ArrayBackend

logger = logging.getLogger(__name__)


class ComputeStrategy(Enum):
    """Stratégie de répartition des calculs."""
    AUTO = "auto"           # Décision automatique
    CPU_ONLY = "cpu_only"   # Forcer CPU
    GPU_ONLY = "gpu_only"   # Forcer GPU (désactivé)
    HYBRID = "hybrid"       # Répartition intelligente (CPU-only)


@dataclass
class ComputeThresholds:
    """
    Seuils de décision (CPU-only).
    """
    # Paramètres conservés pour compatibilité API (GPU désactivé)
    gpu_min_size: int = 50000
    gpu_heavy_ops: int = 20000
    gpu_max_memory_pct: float = 0.80
    transfer_cost_ms_per_mb: float = 0.01
    gpu_batch_size: int = 10000
    min_batch_for_gpu: int = 10

    @classmethod
    def from_env(cls) -> 'ComputeThresholds':
        """Charge les seuils depuis les variables d'environnement."""
        return cls(
            gpu_min_size=int(os.getenv("BACKTEST_GPU_MIN_SIZE", "1000")),
            gpu_heavy_ops=int(os.getenv("BACKTEST_GPU_HEAVY_OPS", "500")),
            gpu_max_memory_pct=float(os.getenv("BACKTEST_GPU_MAX_MEMORY", "0.80")),
            transfer_cost_ms_per_mb=float(os.getenv("BACKTEST_TRANSFER_COST", "0.01")),
            gpu_batch_size=int(os.getenv("BACKTEST_GPU_BATCH", "10000")),
        )


class HybridCompute:
    """
    Gestionnaire de calcul hybride CPU+GPU.

    Répartit intelligemment les tâches selon:
    - Taille des données
    - Type d'opération (vectorielle, logique, etc.)
    - Disponibilité GPU
    - Coût transfer CPU↔GPU

    Example:
        >>> hc = HybridCompute()
        >>> result = hc.auto_compute(data, operation="sma", window=20)
        >>> # → GPU si len(data) >= 1000, sinon CPU
    """

    _instance: Optional['HybridCompute'] = None

    def __new__(cls) -> 'HybridCompute':
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialise le gestionnaire hybride."""
        if hasattr(self, '_initialized'):
            return

        self.backend = ArrayBackend()
        self.thresholds = ComputeThresholds.from_env()
        self._gpu_available = False

        logger.info(
            f"HybridCompute initialisé - GPU: {self._gpu_available}, "
            f"Seuil GPU: {self.thresholds.gpu_min_size} points"
        )

        self._initialized = True

    @property
    def gpu_available(self) -> bool:
        """Indique si GPU disponible."""
        return self._gpu_available

    def should_use_gpu(
        self,
        data_size: int,
        operation_type: str = "vectorial",
        force_strategy: Optional[ComputeStrategy] = None,
    ) -> bool:
        """
        Décide si GPU doit être utilisé.

        Args:
            data_size: Nombre de points de données
            operation_type: Type d'opération ("vectorial", "sequential", "heavy")
            force_strategy: Forcer une stratégie spécifique

        Returns:
            True si GPU recommandé
        """
        # Mode CPU-only: GPU désactivé
        return False

    def estimate_transfer_cost(self, data_size: int, dtype=np.float64) -> float:
        """
        Estime le coût de transfer CPU→GPU (en ms).

        Args:
            data_size: Nombre de points
            dtype: Type de données

        Returns:
            Coût estimé en millisecondes
        """
        bytes_per_element = np.dtype(dtype).itemsize
        total_mb = (data_size * bytes_per_element) / (1024 * 1024)
        return total_mb * self.thresholds.transfer_cost_ms_per_mb

    def auto_compute(
        self,
        data: np.ndarray,
        operation: str,
        **kwargs,
    ) -> np.ndarray:
        """
        Calcule automatiquement sur device optimal.

        Args:
            data: Données d'entrée (NumPy array)
            operation: Type d'opération ("sma", "ema", "bollinger", etc.)
            **kwargs: Paramètres de l'opération

        Returns:
            Résultat calculé (NumPy array)
        """
        data_size = len(data) if hasattr(data, '__len__') else 1

        logger.debug(f"CPU compute: {operation} sur {data_size} points")
        return self._compute_cpu(data, operation, **kwargs)

    def _compute_gpu(
        self,
        data: np.ndarray,
        operation: str,
        **kwargs,
    ) -> np.ndarray:
        """GPU désactivé: fallback CPU."""
        return self._compute_cpu(data, operation, **kwargs)

    def _compute_cpu(
        self,
        data: np.ndarray,
        operation: str,
        **kwargs,
    ) -> np.ndarray:
        """
        Calcule sur CPU avec NumPy/Numba.

        Utilise les implémentations optimisées existantes.
        """
        import pandas as pd

        if operation == "sma":
            window = kwargs.get("window", 20)
            return pd.Series(data).rolling(window).mean().values

        elif operation == "ema":
            window = kwargs.get("window", 20)
            # Calcul EMA simple sans Numba (pour benchmark)
            alpha = 2 / (window + 1)
            result = np.zeros_like(data, dtype=np.float64)
            result[0] = data[0]
            for i in range(1, len(data)):
                result[i] = alpha * data[i] + (1 - alpha) * result[i-1]
            return result

        elif operation == "std":
            window = kwargs.get("window", 20)
            return pd.Series(data).rolling(window).std().values

        else:
            raise ValueError(f"Opération '{operation}' non supportée")

    def batch_compute(
        self,
        data_list: list[np.ndarray],
        operation: str,
        **kwargs,
    ) -> list[np.ndarray]:
        """
        Calcule par batch sur CPU.

        Args:
            data_list: Liste de datasets
            operation: Type d'opération
            **kwargs: Paramètres de l'opération

        Returns:
            Liste de résultats
        """
        return [self.auto_compute(data, operation, **kwargs) for data in data_list]


# ==================== API simplifiée ====================

_hybrid_compute: Optional[HybridCompute] = None


def get_hybrid_compute() -> HybridCompute:
    """Retourne l'instance singleton HybridCompute."""
    global _hybrid_compute
    if _hybrid_compute is None:
        _hybrid_compute = HybridCompute()
    return _hybrid_compute


def auto_compute(data: np.ndarray, operation: str, **kwargs) -> np.ndarray:
    """
    API simplifiée pour calcul CPU.

    Example:
        >>> result = auto_compute(prices, "sma", window=20)
    """
    hc = get_hybrid_compute()
    return hc.auto_compute(data, operation, **kwargs)


def batch_compute(data_list: list[np.ndarray], operation: str, **kwargs) -> list[np.ndarray]:
    """
    API simplifiée pour calcul batch CPU.

    Example:
        >>> results = batch_compute([prices1, prices2], "ema", window=12)
    """
    hc = get_hybrid_compute()
    return hc.batch_compute(data_list, operation, **kwargs)
