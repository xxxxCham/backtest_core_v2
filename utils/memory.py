"""
Module-ID: utils.memory

Purpose: Gestion mémoire intelligente (nettoyage auto, cache LRU, thresholds Windows).

Role in pipeline: performance / resilience

Key components: MemoryManager, ManagedCache, memory_pressure, cleanup_callback

Inputs: Thresholds (%, MB), objects à tracker

Outputs: Notifications pression mémoire, cache evictions

Dependencies: gc, psutil, threading, weakref, dataclasses

Conventions: Seuils configurables; thread-safe; integration Health Monitor; Windows-optimized.

Read-if: Modification thresholds, logique LRU, ou callbacks cleanup.

Skip-if: Vous utilisez juste MemoryManager.check().
"""

from __future__ import annotations

import gc
import logging
import threading
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Generator, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class MemoryConfig:
    """Configuration du gestionnaire mémoire."""

    # Seuils (en pourcentage)
    warning_threshold: float = 75.0
    critical_threshold: float = 90.0
    cleanup_threshold: float = 80.0

    # Comportement
    auto_cleanup: bool = True
    cleanup_interval: float = 30.0  # secondes
    aggressive_cleanup: bool = False

    # Limites
    max_cache_size_mb: float = 1024.0  # 1 GB
    max_array_size_mb: float = 512.0   # 512 MB

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "warning_threshold": self.warning_threshold,
            "critical_threshold": self.critical_threshold,
            "cleanup_threshold": self.cleanup_threshold,
            "auto_cleanup": self.auto_cleanup,
            "cleanup_interval": self.cleanup_interval,
            "aggressive_cleanup": self.aggressive_cleanup,
            "max_cache_size_mb": self.max_cache_size_mb,
            "max_array_size_mb": self.max_array_size_mb,
        }


@dataclass
class MemoryStats:
    """Statistiques mémoire."""

    total_cleanups: int = 0
    bytes_freed: int = 0
    peak_usage_mb: float = 0.0
    current_usage_mb: float = 0.0
    managed_objects: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "total_cleanups": self.total_cleanups,
            "bytes_freed_mb": round(self.bytes_freed / (1024**2), 2),
            "peak_usage_mb": round(self.peak_usage_mb, 2),
            "current_usage_mb": round(self.current_usage_mb, 2),
            "managed_objects": self.managed_objects,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
        }


class ManagedCache:
    """
    Cache avec gestion automatique de la taille.

    Éviction LRU quand la taille maximale est atteinte.
    """

    def __init__(self, max_size_mb: float = 512.0, name: str = "cache"):
        """
        Args:
            max_size_mb: Taille maximale en MB
            name: Nom du cache (pour logging)
        """
        self.max_size_bytes = int(max_size_mb * 1024 * 1024)
        self.name = name

        self._cache: Dict[str, Any] = {}
        self._access_order: List[str] = []
        self._sizes: Dict[str, int] = {}
        self._current_size = 0
        self._lock = threading.Lock()

        self._stats = MemoryStats()

    def _estimate_size(self, obj: Any) -> int:
        """Estime la taille d'un objet en bytes."""
        try:
            import numpy as np
            if isinstance(obj, np.ndarray):
                return obj.nbytes
        except ImportError:
            pass

        try:
            import pandas as pd
            if isinstance(obj, (pd.DataFrame, pd.Series)):
                return obj.memory_usage(deep=True).sum() if hasattr(obj, 'memory_usage') else 0
        except ImportError:
            pass

        # Estimation générique
        import sys
        return sys.getsizeof(obj)

    def get(self, key: str, default: Any = None) -> Any:
        """Récupère une valeur du cache."""
        with self._lock:
            if key in self._cache:
                # Mettre à jour l'ordre d'accès (LRU)
                if key in self._access_order:
                    self._access_order.remove(key)
                self._access_order.append(key)
                self._stats.cache_hits += 1
                return self._cache[key]

            self._stats.cache_misses += 1
            return default

    def set(self, key: str, value: Any) -> bool:
        """
        Ajoute une valeur au cache.

        Returns:
            True si ajouté, False si trop gros
        """
        size = self._estimate_size(value)

        # Vérifier si l'objet seul est trop gros
        if size > self.max_size_bytes:
            logger.warning(f"Objet trop gros pour cache {self.name}: {size / (1024**2):.1f} MB")
            return False

        with self._lock:
            # Éviction LRU si nécessaire
            while self._current_size + size > self.max_size_bytes and self._access_order:
                oldest_key = self._access_order.pop(0)
                if oldest_key in self._cache:
                    old_size = self._sizes.get(oldest_key, 0)
                    del self._cache[oldest_key]
                    del self._sizes[oldest_key]
                    self._current_size -= old_size
                    logger.debug(f"Cache {self.name}: éviction de {oldest_key}")

            # Supprimer l'ancienne valeur si existe
            if key in self._cache:
                old_size = self._sizes.get(key, 0)
                self._current_size -= old_size
                if key in self._access_order:
                    self._access_order.remove(key)

            # Ajouter la nouvelle valeur
            self._cache[key] = value
            self._sizes[key] = size
            self._access_order.append(key)
            self._current_size += size

            return True

    def delete(self, key: str) -> bool:
        """Supprime une entrée du cache."""
        with self._lock:
            if key in self._cache:
                size = self._sizes.get(key, 0)
                del self._cache[key]
                del self._sizes[key]
                self._current_size -= size
                if key in self._access_order:
                    self._access_order.remove(key)
                return True
            return False

    def clear(self) -> int:
        """Vide le cache et retourne les bytes libérés."""
        with self._lock:
            freed = self._current_size
            self._cache.clear()
            self._sizes.clear()
            self._access_order.clear()
            self._current_size = 0
            return freed

    def size_mb(self) -> float:
        """Retourne la taille actuelle en MB."""
        return self._current_size / (1024**2)

    def __len__(self) -> int:
        return len(self._cache)

    def __contains__(self, key: str) -> bool:
        return key in self._cache


class MemoryManager:
    """
    Gestionnaire de mémoire intelligent.

    Features:
    - Surveillance automatique de l'usage mémoire
    - Nettoyage intelligent (garbage collection)
    - Gestion de caches avec éviction LRU
    - Support objets faibles (weak references)

    Example:
        >>> manager = MemoryManager()
        >>> manager.start_auto_cleanup()
        >>>
        >>> # Utiliser un cache managé
        >>> cache = manager.create_cache("indicators", max_size_mb=256)
        >>> cache.set("ema_20", data)
        >>>
        >>> # Contexte avec nettoyage automatique
        >>> with manager.memory_context():
        >>>     # Code gourmand en mémoire
        >>>     pass  # Nettoyage automatique à la sortie
    """

    def __init__(self, config: Optional[MemoryConfig] = None):
        """
        Args:
            config: Configuration personnalisée
        """
        self.config = config or MemoryConfig()
        self._stats = MemoryStats()

        self._caches: Dict[str, ManagedCache] = {}
        self._weak_refs: Set[weakref.ref] = set()
        self._cleanup_callbacks: List[Callable[[], int]] = []

        self._auto_cleanup_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()

        # Importer psutil si disponible
        self._has_psutil = self._check_psutil()

        logger.debug("MemoryManager initialisé")

    def _check_psutil(self) -> bool:
        """Vérifie si psutil est disponible."""
        try:
            import psutil
            return psutil is not None
        except ImportError:
            return False

    def get_memory_usage(self) -> float:
        """Retourne l'usage mémoire en pourcentage."""
        if self._has_psutil:
            import psutil
            return psutil.virtual_memory().percent
        return 50.0  # Estimation par défaut

    def get_memory_available_mb(self) -> float:
        """Retourne la mémoire disponible en MB."""
        if self._has_psutil:
            import psutil
            return psutil.virtual_memory().available / (1024**2)
        return 4096.0  # Estimation 4GB

    def get_process_memory_mb(self) -> float:
        """Retourne la mémoire utilisée par le processus en MB."""
        if self._has_psutil:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / (1024**2)
        return 0.0

    def create_cache(self, name: str, max_size_mb: float = 512.0) -> ManagedCache:
        """
        Crée un cache managé.

        Args:
            name: Nom unique du cache
            max_size_mb: Taille maximale

        Returns:
            ManagedCache instance
        """
        with self._lock:
            if name in self._caches:
                return self._caches[name]

            cache = ManagedCache(max_size_mb=max_size_mb, name=name)
            self._caches[name] = cache
            logger.debug(f"Cache '{name}' créé ({max_size_mb:.0f} MB max)")
            return cache

    def get_cache(self, name: str) -> Optional[ManagedCache]:
        """Récupère un cache existant."""
        return self._caches.get(name)

    def register_cleanup_callback(self, callback: Callable[[], int]) -> None:
        """
        Enregistre un callback de nettoyage.

        Le callback doit retourner le nombre de bytes libérés.
        """
        self._cleanup_callbacks.append(callback)

    def cleanup(self, aggressive: bool = False) -> int:
        """
        Effectue un nettoyage mémoire.

        Args:
            aggressive: Si True, force un nettoyage complet

        Returns:
            Bytes libérés (estimation)
        """
        bytes_freed = 0

        # 1. Garbage collection Python
        gc.collect()

        # 2. Nettoyer les caches si mémoire haute
        usage = self.get_memory_usage()

        if aggressive or usage > self.config.cleanup_threshold:
            for name, cache in self._caches.items():
                if aggressive:
                    freed = cache.clear()
                    bytes_freed += freed
                    logger.debug(f"Cache {name} vidé: {freed / (1024**2):.1f} MB")
                else:
                    # Éviction partielle (50% des entrées)
                    target = len(cache) // 2
                    for _ in range(target):
                        if cache._access_order:
                            key = cache._access_order[0]
                            cache.delete(key)

        # 3. Appeler les callbacks enregistrés
        for callback in self._cleanup_callbacks:
            try:
                freed = callback()
                bytes_freed += freed
            except Exception as e:
                logger.error(f"Erreur callback cleanup: {e}")

        # 4. Nettoyer les weak references mortes
        dead_refs = [ref for ref in self._weak_refs if ref() is None]
        for ref in dead_refs:
            self._weak_refs.discard(ref)

        # 5. GC final
        gc.collect()

        # Mettre à jour les stats
        self._stats.total_cleanups += 1
        self._stats.bytes_freed += bytes_freed
        self._stats.current_usage_mb = self.get_process_memory_mb()
        self._stats.peak_usage_mb = max(
            self._stats.peak_usage_mb,
            self._stats.current_usage_mb
        )

        logger.debug(f"Cleanup effectué: ~{bytes_freed / (1024**2):.1f} MB libérés")

        return bytes_freed

    def start_auto_cleanup(self) -> None:
        """Démarre le nettoyage automatique."""
        if self._running:
            return

        self._running = True

        def cleanup_loop():
            while self._running:
                try:
                    usage = self.get_memory_usage()

                    if usage > self.config.critical_threshold:
                        logger.warning(f"Mémoire critique ({usage:.1f}%), nettoyage agressif")
                        self.cleanup(aggressive=True)
                    elif usage > self.config.cleanup_threshold:
                        logger.debug(f"Mémoire haute ({usage:.1f}%), nettoyage")
                        self.cleanup(aggressive=False)

                except Exception as e:
                    logger.error(f"Erreur auto-cleanup: {e}")

                time.sleep(self.config.cleanup_interval)

        self._auto_cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        self._auto_cleanup_thread.start()
        logger.info("Auto-cleanup démarré")

    def stop_auto_cleanup(self) -> None:
        """Arrête le nettoyage automatique."""
        self._running = False
        if self._auto_cleanup_thread:
            self._auto_cleanup_thread.join(timeout=5.0)
            self._auto_cleanup_thread = None
        logger.info("Auto-cleanup arrêté")

    @contextmanager
    def memory_context(
        self,
        cleanup_after: bool = True,
        check_before: bool = True
    ) -> Generator[None, None, None]:
        """
        Context manager pour opérations gourmandes en mémoire.

        Args:
            cleanup_after: Nettoyer à la sortie
            check_before: Vérifier la mémoire avant

        Example:
            >>> with manager.memory_context():
            >>>     # Code gourmand
            >>>     result = heavy_computation()
        """
        if check_before:
            usage = self.get_memory_usage()
            if usage > self.config.warning_threshold:
                logger.warning(f"Mémoire haute avant opération: {usage:.1f}%")
                self.cleanup()

        try:
            yield
        finally:
            if cleanup_after:
                self.cleanup()

    def track_object(self, obj: Any) -> None:
        """Track un objet via weak reference pour monitoring."""
        try:
            ref = weakref.ref(obj)
            self._weak_refs.add(ref)
            self._stats.managed_objects += 1
        except TypeError:
            # L'objet ne supporte pas les weak references
            pass

    def get_stats(self) -> MemoryStats:
        """Retourne les statistiques."""
        self._stats.current_usage_mb = self.get_process_memory_mb()

        # Compter les objets vivants
        alive = sum(1 for ref in self._weak_refs if ref() is not None)
        self._stats.managed_objects = alive

        # Agréger les stats des caches
        for cache in self._caches.values():
            self._stats.cache_hits += cache._stats.cache_hits
            self._stats.cache_misses += cache._stats.cache_misses

        return self._stats

    def get_cache_summary(self) -> Dict[str, Dict[str, Any]]:
        """Retourne un résumé de tous les caches."""
        return {
            name: {
                "size_mb": cache.size_mb(),
                "entries": len(cache),
                "max_size_mb": cache.max_size_bytes / (1024**2),
            }
            for name, cache in self._caches.items()
        }

    def summary(self) -> str:
        """Retourne un résumé textuel."""
        stats = self.get_stats()

        lines = [
            "=== Memory Manager ===",
            f"Process Memory: {stats.current_usage_mb:.1f} MB",
            f"Peak Memory: {stats.peak_usage_mb:.1f} MB",
            f"System Memory: {self.get_memory_usage():.1f}%",
            f"Total Cleanups: {stats.total_cleanups}",
            f"Bytes Freed: {stats.bytes_freed / (1024**2):.1f} MB",
            "",
            "Caches:",
        ]

        for name, info in self.get_cache_summary().items():
            lines.append(f"  {name}: {info['size_mb']:.1f}/{info['max_size_mb']:.0f} MB ({info['entries']} entries)")

        return "\n".join(lines)


# Singleton global
_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """Retourne le gestionnaire mémoire singleton."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager


def cleanup_memory(aggressive: bool = False) -> int:
    """Raccourci pour nettoyer la mémoire."""
    return get_memory_manager().cleanup(aggressive)


__all__ = [
    "MemoryConfig",
    "MemoryStats",
    "ManagedCache",
    "MemoryManager",
    "get_memory_manager",
    "cleanup_memory",
]
