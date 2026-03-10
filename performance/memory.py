"""
Module-ID: performance.memory

Purpose: Gestion intelligente mémoire - chunking, préchargement, auto-cleanup.

Role in pipeline: performance optimization

Key components: ChunkedProcessor, MemoryManager, @chunked, auto_gc()

Inputs: Large DataFrame/Array, chunk_size, memory_limit_gb

Outputs: Processed chunks, memory usage stats, freed memory

Dependencies: numpy, pandas, gc, weakref, tempfile, psutil (optionnel)

Conventions: Chunks power-of-2; GC auto après threshold; spill disk si limit exceeded.

Read-if: Modification chunking strategy ou memory limits.

Skip-if: Vous appelez processor.process(df) iterator.
"""

from __future__ import annotations

import gc
import logging
import sys
import tempfile
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, TypeVar

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# psutil pour monitoring mémoire
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

T = TypeVar("T")


@dataclass
class MemoryStats:
    """Statistiques mémoire."""
    used_gb: float
    available_gb: float
    total_gb: float
    percent: float
    process_rss_gb: float  # Resident Set Size du process


def get_memory_info() -> MemoryStats:
    """Retourne les informations mémoire actuelles."""
    if HAS_PSUTIL:
        mem = psutil.virtual_memory()
        process = psutil.Process()
        rss = process.memory_info().rss / (1024**3)

        return MemoryStats(
            used_gb=mem.used / (1024**3),
            available_gb=mem.available / (1024**3),
            total_gb=mem.total / (1024**3),
            percent=mem.percent,
            process_rss_gb=rss,
        )
    else:
        return MemoryStats(
            used_gb=0.0,
            available_gb=8.0,
            total_gb=8.0,
            percent=0.0,
            process_rss_gb=0.0,
        )


def get_available_ram_gb() -> float:
    """Retourne la RAM disponible en GB."""
    return get_memory_info().available_gb


def get_object_size_mb(obj: Any) -> float:
    """Estime la taille d'un objet en MB."""
    if isinstance(obj, pd.DataFrame):
        return obj.memory_usage(deep=True).sum() / (1024**2)
    elif isinstance(obj, np.ndarray):
        return obj.nbytes / (1024**2)
    elif isinstance(obj, (list, tuple)):
        return sum(get_object_size_mb(item) for item in obj) + sys.getsizeof(obj) / (1024**2)
    elif isinstance(obj, dict):
        size = sys.getsizeof(obj)
        for k, v in obj.items():
            size += sys.getsizeof(k) + get_object_size_mb(v) * (1024**2)
        return size / (1024**2)
    else:
        return sys.getsizeof(obj) / (1024**2)


class ChunkedProcessor:
    """
    Processeur qui divise les données en chunks pour économiser la mémoire.

    Utile pour traiter de grands DataFrames sans saturer la RAM.

    Example:
        >>> processor = ChunkedProcessor(chunk_size=10000)
        >>>
        >>> results = []
        >>> for chunk_df in processor.iter_chunks(large_df):
        ...     result = process_data(chunk_df)
        ...     results.append(result)
        >>>
        >>> final = pd.concat(results)
    """

    def __init__(
        self,
        chunk_size: int = 10000,
        overlap: int = 0,
        memory_limit_gb: Optional[float] = None,
    ):
        """
        Initialise le processeur de chunks.

        Args:
            chunk_size: Nombre de lignes par chunk
            overlap: Chevauchement entre chunks (pour indicateurs rolling)
            memory_limit_gb: Limite mémoire optionnelle
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.memory_limit_gb = memory_limit_gb

        self._adaptive_size = chunk_size

    def _adjust_chunk_size(self):
        """Ajuste dynamiquement la taille des chunks selon la mémoire disponible."""
        if not self.memory_limit_gb:
            return

        mem = get_memory_info()

        # Si mémoire faible, réduire la taille des chunks
        if mem.available_gb < 1.0:
            self._adaptive_size = max(1000, self.chunk_size // 4)
            logger.warning(f"Mémoire faible! Chunk size réduit à {self._adaptive_size}")
        elif mem.available_gb < 2.0:
            self._adaptive_size = max(2000, self.chunk_size // 2)
        else:
            self._adaptive_size = self.chunk_size

    def iter_chunks(
        self,
        df: pd.DataFrame,
        copy: bool = False
    ) -> Generator[pd.DataFrame, None, None]:
        """
        Itère sur les chunks d'un DataFrame.

        Args:
            df: DataFrame à diviser
            copy: Créer une copie de chaque chunk (plus sûr mais plus lent)

        Yields:
            Chunks du DataFrame
        """
        n_rows = len(df)

        for start in range(0, n_rows, self._adaptive_size - self.overlap):
            self._adjust_chunk_size()

            end = min(start + self._adaptive_size, n_rows)

            if copy:
                yield df.iloc[start:end].copy()
            else:
                yield df.iloc[start:end]

            # Forcer garbage collection entre chunks si mémoire limite
            if self.memory_limit_gb:
                gc.collect()

    def process(
        self,
        df: pd.DataFrame,
        func: Callable[[pd.DataFrame], T],
        combine_func: Optional[Callable[[List[T]], T]] = None,
    ) -> T:
        """
        Traite un DataFrame par chunks et combine les résultats.

        Args:
            df: DataFrame à traiter
            func: Fonction à appliquer sur chaque chunk
            combine_func: Fonction pour combiner les résultats (None = list)

        Returns:
            Résultat combiné
        """
        results = []

        for i, chunk in enumerate(self.iter_chunks(df)):
            logger.debug(f"Processing chunk {i+1}, size={len(chunk)}")
            result = func(chunk)
            results.append(result)

        if combine_func:
            return combine_func(results)
        else:
            # Par défaut, concat si DataFrames, sinon list
            if results and isinstance(results[0], pd.DataFrame):
                return pd.concat(results, ignore_index=True)
            return results  # type: ignore


class MemoryManager:
    """
    Gestionnaire de mémoire avec limites et nettoyage automatique.

    Example:
        >>> with MemoryManager(limit_gb=8.0, auto_gc=True) as mm:
        ...     data = load_large_data()
        ...     results = process(data)
        ...     mm.check_and_cleanup()  # Nettoie si nécessaire
    """

    def __init__(
        self,
        limit_gb: Optional[float] = None,
        auto_gc: bool = True,
        gc_threshold_percent: float = 80.0,
    ):
        """
        Initialise le gestionnaire mémoire.

        Args:
            limit_gb: Limite mémoire en GB (None = pas de limite)
            auto_gc: Activer garbage collection automatique
            gc_threshold_percent: Seuil de mémoire pour déclencher GC
        """
        self.limit_gb = limit_gb
        self.auto_gc = auto_gc
        self.gc_threshold = gc_threshold_percent

        self._tracked_objects: List[weakref.ref] = []
        self._start_memory: float = 0.0
        self._gc_count: int = 0

    def __enter__(self):
        self._start_memory = get_memory_info().process_rss_gb
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Nettoyer les objets trackés
        self._tracked_objects.clear()

        # Forcer GC final
        gc.collect()

        end_memory = get_memory_info().process_rss_gb
        logger.debug(
            f"MemoryManager: début={self._start_memory:.2f}GB, "
            f"fin={end_memory:.2f}GB, GC={self._gc_count}"
        )

        return False

    def track(self, obj: Any) -> Any:
        """
        Track un objet pour nettoyage automatique.

        Args:
            obj: Objet à tracker

        Returns:
            L'objet lui-même
        """
        self._tracked_objects.append(weakref.ref(obj))
        return obj

    def check_and_cleanup(self, force: bool = False) -> bool:
        """
        Vérifie la mémoire et nettoie si nécessaire.

        Args:
            force: Forcer le nettoyage même si sous le seuil

        Returns:
            True si nettoyage effectué
        """
        mem = get_memory_info()

        should_cleanup = force

        if self.limit_gb and mem.process_rss_gb > self.limit_gb:
            should_cleanup = True
            logger.warning(f"Limite mémoire dépassée: {mem.process_rss_gb:.2f}GB > {self.limit_gb}GB")

        if mem.percent > self.gc_threshold:
            should_cleanup = True
            logger.warning(f"Seuil mémoire système atteint: {mem.percent:.1f}%")

        if should_cleanup and self.auto_gc:
            gc.collect()
            self._gc_count += 1
            return True

        return False

    def get_usage(self) -> Dict[str, float]:
        """Retourne les stats d'usage mémoire."""
        mem = get_memory_info()
        return {
            "process_gb": mem.process_rss_gb,
            "system_used_gb": mem.used_gb,
            "system_available_gb": mem.available_gb,
            "system_percent": mem.percent,
            "delta_gb": mem.process_rss_gb - self._start_memory,
        }


class DataFrameCache:
    """
    Cache intelligent pour DataFrames avec gestion mémoire.

    Supporte le spillage sur disque si la mémoire est saturée.

    Example:
        >>> cache = DataFrameCache(max_memory_gb=2.0)
        >>>
        >>> cache.put("btc_1h", btc_df)
        >>> cache.put("eth_1h", eth_df)
        >>>
        >>> btc = cache.get("btc_1h")
    """

    def __init__(
        self,
        max_memory_gb: float = 2.0,
        spill_to_disk: bool = True,
        cache_dir: Optional[str] = None,
    ):
        """
        Initialise le cache.

        Args:
            max_memory_gb: Mémoire max pour le cache
            spill_to_disk: Écrire sur disque si mémoire saturée
            cache_dir: Répertoire pour fichiers temporaires
        """
        self.max_memory_gb = max_memory_gb
        self.spill_to_disk = spill_to_disk
        self.cache_dir = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "backtest_cache"

        self._memory_cache: Dict[str, pd.DataFrame] = {}
        self._disk_cache: Dict[str, Path] = {}
        self._access_times: Dict[str, float] = {}
        self._sizes: Dict[str, float] = {}  # en MB

        # Créer le répertoire cache
        if spill_to_disk:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _current_memory_mb(self) -> float:
        """Calcule la mémoire utilisée par le cache."""
        return sum(self._sizes.get(k, 0) for k in self._memory_cache)

    def _evict_lru(self, needed_mb: float):
        """Évince les entrées LRU pour libérer de la mémoire."""
        while self._memory_cache and self._current_memory_mb() + needed_mb > self.max_memory_gb * 1024:
            # Trouver l'entrée la moins récemment utilisée
            lru_key = min(self._memory_cache.keys(), key=lambda k: self._access_times.get(k, 0))

            if self.spill_to_disk:
                # Spiller sur disque
                df = self._memory_cache[lru_key]
                disk_path = self.cache_dir / f"{lru_key}.parquet"
                df.to_parquet(disk_path)
                self._disk_cache[lru_key] = disk_path
                logger.debug(f"Spilled {lru_key} to disk ({self._sizes[lru_key]:.1f}MB)")

            del self._memory_cache[lru_key]

    def put(self, key: str, df: pd.DataFrame):
        """
        Ajoute un DataFrame au cache.

        Args:
            key: Clé unique
            df: DataFrame à cacher
        """
        size_mb = get_object_size_mb(df)

        # Éviction si nécessaire
        if size_mb < self.max_memory_gb * 1024:
            self._evict_lru(size_mb)

        self._memory_cache[key] = df
        self._access_times[key] = time.time()
        self._sizes[key] = size_mb

        # Retirer du cache disque si présent
        if key in self._disk_cache:
            try:
                self._disk_cache[key].unlink()
            except Exception:
                pass
            del self._disk_cache[key]

    def get(self, key: str) -> Optional[pd.DataFrame]:
        """
        Récupère un DataFrame du cache.

        Args:
            key: Clé du DataFrame

        Returns:
            DataFrame ou None si non trouvé
        """
        # Vérifier cache mémoire
        if key in self._memory_cache:
            self._access_times[key] = time.time()
            return self._memory_cache[key]

        # Vérifier cache disque
        if key in self._disk_cache:
            disk_path = self._disk_cache[key]
            if disk_path.exists():
                df = pd.read_parquet(disk_path)

                # Remettre en mémoire si possible
                size_mb = get_object_size_mb(df)
                if self._current_memory_mb() + size_mb <= self.max_memory_gb * 1024:
                    self._memory_cache[key] = df
                    self._access_times[key] = time.time()

                return df

        return None

    def contains(self, key: str) -> bool:
        """Vérifie si une clé existe dans le cache."""
        return key in self._memory_cache or key in self._disk_cache

    def clear(self):
        """Vide le cache."""
        self._memory_cache.clear()
        self._access_times.clear()
        self._sizes.clear()

        # Supprimer fichiers disque
        for path in self._disk_cache.values():
            try:
                path.unlink()
            except Exception:
                pass
        self._disk_cache.clear()

    def stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du cache."""
        return {
            "memory_items": len(self._memory_cache),
            "disk_items": len(self._disk_cache),
            "memory_used_mb": self._current_memory_mb(),
            "memory_limit_mb": self.max_memory_gb * 1024,
            "keys": list(self._memory_cache.keys()) + list(self._disk_cache.keys()),
        }


# ======================== Fonctions utilitaires ========================

@contextmanager
def memory_efficient_mode():
    """
    Context manager pour mode économie mémoire.

    Active GC agressif et réduit les allocations.

    Example:
        >>> with memory_efficient_mode():
        ...     process_large_data()
    """
    # Sauvegarder les seuils GC
    old_thresholds = gc.get_threshold()

    try:
        # GC plus agressif
        gc.set_threshold(100, 5, 5)
        gc.collect()
        yield
    finally:
        # Restaurer
        gc.set_threshold(*old_thresholds)
        gc.collect()


def optimize_dataframe(df: pd.DataFrame, inplace: bool = False) -> pd.DataFrame:
    """
    Optimise la mémoire d'un DataFrame en réduisant les types.

    Args:
        df: DataFrame à optimiser
        inplace: Modifier en place

    Returns:
        DataFrame optimisé
    """
    if not inplace:
        df = df.copy()

    for col in df.columns:
        col_type = df[col].dtype

        if col_type == "float64":
            # Essayer float32
            df[col] = pd.to_numeric(df[col], downcast="float")

        elif col_type == "int64":
            # Réduire la taille des entiers
            df[col] = pd.to_numeric(df[col], downcast="integer")

        elif col_type == "object":
            # Convertir en category si peu de valeurs uniques
            n_unique = df[col].nunique()
            if n_unique / len(df) < 0.5:  # Moins de 50% de valeurs uniques
                df[col] = df[col].astype("category")

    return df


def estimate_memory_needed(
    n_rows: int,
    n_strategies: int,
    n_indicators: int = 5,
) -> float:
    """
    Estime la mémoire nécessaire pour un backtest.

    Args:
        n_rows: Nombre de lignes de données
        n_strategies: Nombre de combinaisons de paramètres
        n_indicators: Nombre d'indicateurs

    Returns:
        Estimation en GB
    """
    # Base: ~100 bytes par ligne pour OHLCV
    base_data_mb = n_rows * 100 / (1024**2)

    # Indicateurs: ~50 bytes par indicateur par ligne
    indicators_mb = n_rows * n_indicators * 50 / (1024**2)

    # Résultats: ~200 bytes par stratégie
    results_mb = n_strategies * 200 / (1024**2)

    # Overhead Python/Pandas: x2
    total_mb = (base_data_mb + indicators_mb + results_mb) * 2

    return total_mb / 1024  # En GB
