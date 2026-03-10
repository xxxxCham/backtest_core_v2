"""
Module-ID: data.indicator_bank

Purpose: Cache disque intelligent indicateurs - évite recalc via hash param+données.

Role in pipeline: performance

Key components: IndicatorBank, CacheEntry, CacheStats, hash_indicator_config()

Inputs: Indicator name, params, OHLCV data

Outputs: Cached array ou recalc si stale (TTL), CacheStats {hits, misses, hit_rate}

Dependencies: pandas, hashlib, pickle, pathlib, dataclasses, time

Conventions: TTL 7j défaut; clé hash (nom, params, données); éviction LRU.

Read-if: Modification cache policy ou TTL.

Skip-if: Vous appelez bank.get(indicator_name, params, df).
"""

import hashlib
import json
import os
import pickle
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from utils.log import get_logger

logger = get_logger(__name__)

# Helpers env (configuration cache)
def _env_bool(name: str, default: Optional[bool] = None) -> Optional[bool]:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    return default


def _env_int(name: str, default: Optional[int] = None) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: Optional[float] = None) -> Optional[float]:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default

# Support optionnel pour file locking (concurrence multiprocess)
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False
    try:
        from filelock import FileLock
        HAS_FILELOCK = True
    except ImportError:
        HAS_FILELOCK = False


@dataclass
class CacheStats:
    """Statistiques du cache."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    total_size_mb: float = 0.0
    entries_count: int = 0

    @property
    def hit_rate(self) -> float:
        """Taux de hit du cache."""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": self.hit_rate,
            "total_size_mb": self.total_size_mb,
            "entries_count": self.entries_count
        }


@dataclass
class CacheEntry:
    """Entrée de cache avec métadonnées."""
    key: str
    indicator_name: str
    params_hash: str
    data_hash: str
    created_at: float
    expires_at: float
    size_bytes: int
    filepath: Path

    def is_expired(self) -> bool:
        """Vérifie si l'entrée a expiré."""
        return time.time() > self.expires_at


class IndicatorBank:
    """
    Cache disque intelligent pour les indicateurs calculés.

    Usage:
        >>> bank = IndicatorBank(cache_dir=".indicator_cache")
        >>>
        >>> # Vérifier si en cache
        >>> result = bank.get("bollinger", params, df)
        >>> if result is None:
        ...     result = bollinger_bands(df["close"], **params)
        ...     bank.put("bollinger", params, df, result)
    """

    DEFAULT_TTL = 3600 * 24  # 24 heures
    DEFAULT_MAX_SIZE_MB = 500  # 500 MB max

    def __init__(
        self,
        cache_dir: Union[str, Path] = ".indicator_cache",
        ttl: int = DEFAULT_TTL,
        max_size_mb: float = DEFAULT_MAX_SIZE_MB,
        enabled: bool = True,
        disk_enabled: bool = True,
        memory_max_entries: int = 128
    ):
        """
        Initialise l'IndicatorBank.

        Args:
            cache_dir: Répertoire de cache
            ttl: Time-to-live en secondes (défaut: 24h)
            max_size_mb: Taille maximale du cache en MB
            enabled: Activer/désactiver le cache
            disk_enabled: Activer/désactiver le cache disque (mémoire reste active)
            memory_max_entries: Max entries kept in memory (0 disables)
        """
        self.cache_dir = Path(cache_dir)
        self._index_path = self.cache_dir / "index.json"
        self.ttl = ttl
        self.max_size_mb = max_size_mb
        self.enabled = enabled
        self.disk_enabled = disk_enabled
        self.memory_max_entries = int(memory_max_entries)

        self.stats = CacheStats()
        self._index: Dict[str, CacheEntry] = {}
        self._memory_cache: Dict[str, Tuple[float, Any]] = {}

        if enabled and self.disk_enabled:
            self._init_cache_dir()
            self._load_index()

    def _init_cache_dir(self) -> None:
        """Crée le répertoire de cache si nécessaire."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.cache_dir / "index.json"

    def _rebuild_index_from_files(self) -> None:
        """Reconstruit l'index en scannant les fichiers .pkl du cache."""
        if not self.disk_enabled:
            return
        logger.info("Reconstruction de l'index du cache à partir des fichiers existants...")
        self._index = {}

        try:
            # Nettoyer les fichiers temporaires orphelins (corruptions précédentes)
            for tmp_file in self.cache_dir.glob("*.tmp"):
                try:
                    tmp_file.unlink()
                    logger.debug(f"Fichier temporaire orphelin supprimé: {tmp_file.name}")
                except OSError as e:
                    logger.debug(f"Impossible de supprimer le fichier: {e}")

            # Nettoyer les lock files orphelins
            for lock_file in self.cache_dir.glob("*.lock"):
                try:
                    lock_file.unlink()
                    logger.debug(f"Lock file orphelin supprimé: {lock_file.name}")
                except OSError as e:
                    logger.debug(f"Impossible de supprimer le fichier: {e}")

            pkl_files = list(self.cache_dir.glob("*.pkl"))
            logger.info(f"Trouvé {len(pkl_files)} fichiers .pkl à indexer")

            for pkl_file in pkl_files:
                try:
                    # Extraire les métadonnées du nom de fichier
                    # Format: {indicator_name}_{params_hash}_{data_hash}.pkl
                    stem = pkl_file.stem
                    parts = stem.rsplit("_", 2)

                    if len(parts) != 3:
                        logger.debug(f"Fichier ignoré (format invalide): {pkl_file.name}")
                        continue

                    indicator_name, params_hash, data_hash = parts
                    key = stem

                    # Obtenir la taille du fichier
                    size_bytes = pkl_file.stat().st_size
                    created_at = pkl_file.stat().st_mtime
                    expires_at = created_at + self.ttl

                    entry = CacheEntry(
                        key=key,
                        indicator_name=indicator_name,
                        params_hash=params_hash,
                        data_hash=data_hash,
                        created_at=created_at,
                        expires_at=expires_at,
                        size_bytes=size_bytes,
                        filepath=pkl_file
                    )

                    # Ne garder que les entrées non expirées
                    if not entry.is_expired():
                        self._index[key] = entry
                    else:
                        logger.debug(f"Fichier expiré supprimé: {pkl_file.name}")
                        pkl_file.unlink(missing_ok=True)

                except Exception as e:
                    logger.debug(f"Erreur indexation fichier {pkl_file.name}: {e}")
                    continue

            logger.info(f"Index reconstruit: {len(self._index)} entrées valides")

            # Sauvegarder le nouvel index
            self._save_index()

        except Exception as e:
            logger.error(f"Erreur lors de la reconstruction de l'index: {e}")
            self._index = {}

    def _load_index(self) -> None:
        """Charge l'index du cache depuis le disque."""
        if not self.disk_enabled:
            return
        if self._index_path.exists():
            try:
                with open(self._index_path, "r") as f:
                    data = json.load(f)

                for key, entry_data in data.get("entries", {}).items():
                    entry = CacheEntry(
                        key=entry_data["key"],
                        indicator_name=entry_data["indicator_name"],
                        params_hash=entry_data["params_hash"],
                        data_hash=entry_data["data_hash"],
                        created_at=entry_data["created_at"],
                        expires_at=entry_data["expires_at"],
                        size_bytes=entry_data["size_bytes"],
                        filepath=Path(entry_data["filepath"])
                    )

                    # Vérifier si le fichier existe encore
                    if entry.filepath.exists() and not entry.is_expired():
                        self._index[key] = entry
                    else:
                        # Nettoyer l'entrée invalide
                        self._remove_entry(entry, update_index=False)

                logger.debug(f"Index chargé: {len(self._index)} entrées")

            except Exception as e:
                logger.warning(f"Erreur chargement index: {e}")
                logger.info("Tentative de reconstruction automatique de l'index...")
                self._rebuild_index_from_files()
        else:
            # Index n'existe pas, le reconstruire à partir des fichiers
            logger.info("Index absent, reconstruction à partir des fichiers existants...")
            self._rebuild_index_from_files()

    def _acquire_lock_file(
        self,
        lock_path: Path,
        timeout: float = 0.2,
        poll_interval: float = 0.02,
        stale_seconds: float = 60.0,
    ) -> bool:
        """Acquire a simple cross-process lock via atomic lock file creation."""
        start = time.time()
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.close(fd)
                return True
            except FileExistsError:
                try:
                    if time.time() - lock_path.stat().st_mtime > stale_seconds:
                        lock_path.unlink(missing_ok=True)
                        continue
                except OSError as e:
                    logger.debug(f"Impossible de supprimer le fichier: {e}")
                if time.time() - start >= timeout:
                    return False
                time.sleep(poll_interval)
            except Exception:
                return False

    def _save_index(self) -> None:
        """Sauvegarde l'index sur disque de manière atomique."""
        if not self.disk_enabled:
            return
        data = {
            "version": "1.0",
            "updated_at": time.time(),
            "entries": {}
        }

        for key, entry in self._index.items():
            data["entries"][key] = {
                "key": entry.key,
                "indicator_name": entry.indicator_name,
                "params_hash": entry.params_hash,
                "data_hash": entry.data_hash,
                "created_at": entry.created_at,
                "expires_at": entry.expires_at,
                "size_bytes": entry.size_bytes,
                "filepath": str(entry.filepath)
            }

        # Écriture atomique via fichier temporaire
        lock_path = self._index_path.with_suffix(".lock")
        tmp_path = self._index_path.with_suffix(f".{os.getpid()}.tmp")

        try:
            # Lock optionnel pour concurrence multiprocess
            if HAS_FCNTL:
                # Unix: utiliser fcntl
                with open(lock_path, "w") as lockfile:
                    fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX)
                    try:
                        # Écrire dans fichier temporaire
                        with open(tmp_path, "w") as f:
                            json.dump(data, f, indent=2)
                        # Remplacement atomique (garantie sur tous OS modernes)
                        os.replace(tmp_path, self._index_path)
                    finally:
                        fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)
            elif HAS_FILELOCK:
                # Cross-platform: utiliser filelock
                with FileLock(str(lock_path)):
                    with open(tmp_path, "w") as f:
                        json.dump(data, f, indent=2)
                    os.replace(tmp_path, self._index_path)
            else:
                # Pas de lock disponible, utiliser un lock file simple
                got_lock = self._acquire_lock_file(lock_path)
                if not got_lock:
                    logger.debug("Index save skipped (lock contention)")
                    return
                try:
                    with open(tmp_path, "w") as f:
                        json.dump(data, f, indent=2)
                    os.replace(tmp_path, self._index_path)
                finally:
                    lock_path.unlink(missing_ok=True)

        except Exception as e:
            if isinstance(e, PermissionError) or getattr(e, "winerror", None) in (5, 32):
                logger.debug(f"Erreur sauvegarde index (concurrence): {e}")
            else:
                logger.warning(f"Erreur sauvegarde index: {e}")
            # Nettoyer fichier temporaire en cas d'échec
            tmp_path.unlink(missing_ok=True)
            # Note: Les lock files ne sont pas supprimés ici pour éviter
            # les erreurs de permission sur Windows. Ils seront nettoyés
            # automatiquement lors de la reconstruction de l'index.

    def _get_data_hash(self, df: pd.DataFrame) -> str:
        """Build a short hash for the input data."""
        data_info = {
            "shape": df.shape,
            "columns": list(df.columns),
            "first_idx": str(df.index[0]) if len(df) > 0 else "",
            "last_idx": str(df.index[-1]) if len(df) > 0 else "",
            "checksum": float(df["close"].sum()) if "close" in df.columns else 0.0
        }
        data_str = json.dumps(data_info, sort_keys=True, default=str)
        return hashlib.sha256(data_str.encode("utf-8")).hexdigest()[:12]

    def _generate_key(
        self,
        indicator_name: str,
        params: Dict[str, Any],
        df: pd.DataFrame,
        data_hash: Optional[str] = None
    ) -> Tuple[str, str, str]:
        """
        Génère une clé de cache unique.

        La clé inclut automatiquement le backend (CPU/GPU) pour éviter
        que des résultats GPU (float32) soient utilisés en mode CPU (float64).

        Returns:
            Tuple (full_key, params_hash, data_hash)
        """
        # Inclure le backend dans la clé de cache pour éviter collisions CPU/GPU
        if "_backend" not in params:
            # Mode CPU-only: backend forcé à CPU
            params = {**params, "_backend": "cpu"}

        # Hash des paramètres
        params_str = json.dumps(params, sort_keys=True, default=str)
        params_hash = hashlib.sha256(params_str.encode("utf-8")).hexdigest()[:12]

        # Hash des données (basé sur shape, premier/dernier timestamp, checksum)
        if data_hash is None:
            data_hash = self._get_data_hash(df)

        full_key = f"{indicator_name}_{params_hash}_{data_hash}"

        return full_key, params_hash, data_hash

    def get_data_hash(self, df: pd.DataFrame) -> str:
        """Return a data hash that can be reused across indicators."""
        return self._get_data_hash(df)

    def _memory_get(self, key: str) -> Optional[Any]:
        if self.memory_max_entries <= 0:
            return None
        entry = self._memory_cache.get(key)
        if entry is None:
            return None
        expires_at, result = entry
        if time.time() > expires_at:
            self._memory_cache.pop(key, None)
            return None
        return result

    def _memory_put(self, key: str, expires_at: float, result: Any) -> None:
        if self.memory_max_entries <= 0:
            return
        if key in self._memory_cache:
            self._memory_cache.pop(key, None)
        self._memory_cache[key] = (expires_at, result)
        while len(self._memory_cache) > self.memory_max_entries:
            self._memory_cache.pop(next(iter(self._memory_cache)))

    def get(
        self,
        indicator_name: str,
        params: Dict[str, Any],
        df: pd.DataFrame,
        data_hash: Optional[str] = None,
        backend: str = "cpu"
    ) -> Optional[Any]:
        """
        Récupère un indicateur depuis le cache.

        Args:
            indicator_name: Nom de l'indicateur
            params: Paramètres utilisés
            df: DataFrame source
            backend: Backend utilisé ("cpu" ou "gpu") pour différencier le cache

        Returns:
            Résultat caché ou None si non trouvé/expiré
        """
        if not self.enabled:
            return None

        # Ajouter backend aux params pour différencier cache CPU vs GPU
        params_with_backend = {**params, "_backend": backend}
        key, _, _ = self._generate_key(indicator_name, params_with_backend, df, data_hash=data_hash)

        # Check memory cache first
        memory_result = self._memory_get(key)
        if memory_result is not None:
            self.stats.hits += 1
            return memory_result

        if not self.disk_enabled:
            self.stats.misses += 1
            return None

        entry = self._index.get(key)
        if entry is None:
            self.stats.misses += 1
            return None

        # Vérifier expiration
        if entry.is_expired():
            self._remove_entry(entry)
            self.stats.misses += 1
            return None

        # Charger les données
        try:
            with open(entry.filepath, "rb") as f:
                result = pickle.load(f)

            self.stats.hits += 1
            self._memory_put(key, entry.expires_at, result)
            logger.debug(f"Cache HIT: {indicator_name} [{key[:16]}]")
            return result

        except Exception as e:
            if isinstance(e, FileNotFoundError) or getattr(e, "winerror", None) == 2:
                logger.debug(f"Erreur lecture cache (fichier manquant): {e}")
            else:
                logger.warning(f"Erreur lecture cache: {e}")
            self._remove_entry(entry)
            self.stats.misses += 1
            return None

    def put(
        self,
        indicator_name: str,
        params: Dict[str, Any],
        df: pd.DataFrame,
        result: Any,
        ttl: Optional[int] = None,
        data_hash: Optional[str] = None,
        backend: str = "cpu"
    ) -> bool:
        """
        Stocke un indicateur dans le cache.

        Args:
            indicator_name: Nom de l'indicateur
            params: Paramètres utilisés
            df: DataFrame source
            result: Résultat à cacher
            ttl: TTL personnalisé (optionnel)
            backend: Backend utilisé ("cpu" ou "gpu") pour différencier le cache

        Returns:
            True si mis en cache avec succès
        """
        if not self.enabled:
            return False

        # Ajouter backend aux params pour différencier cache CPU vs GPU
        params_with_backend = {**params, "_backend": backend}
        key, params_hash, data_hash = self._generate_key(
            indicator_name, params_with_backend, df, data_hash=data_hash
        )

        # Sérialiser le résultat
        try:
            data = pickle.dumps(result)
            size_bytes = len(data)
        except Exception as e:
            logger.warning(f"Erreur sérialisation: {e}")
            return False

        # Cache mémoire (toujours actif si enabled)
        now = time.time()
        expires_at = now + (ttl or self.ttl)
        self._memory_put(key, expires_at, result)

        if not self.disk_enabled:
            self._update_stats()
            return True

        # Vérifier la taille
        self._enforce_size_limit(size_bytes)

        # Sauvegarder sur disque de manière atomique
        filepath = self.cache_dir / f"{key}.pkl"
        tmp_filepath = filepath.with_suffix(f".{os.getpid()}.tmp")
        lock_path = filepath.with_suffix(".lock")

        try:
            got_lock = self._acquire_lock_file(lock_path)
            if not got_lock:
                logger.debug(f"Cache write skipped (lock contention): {filepath.name}")
                return False
            try:
                # Écrire dans fichier temporaire
                with open(tmp_filepath, "wb") as f:
                    f.write(data)
                # Remplacement atomique (garantie sur tous OS modernes)
                os.replace(tmp_filepath, filepath)
            finally:
                lock_path.unlink(missing_ok=True)
        except Exception as e:
            if isinstance(e, PermissionError) or getattr(e, "winerror", None) in (5, 32):
                logger.debug(f"Erreur écriture cache (concurrence): {e}")
            else:
                logger.warning(f"Erreur écriture cache: {e}")
            # Nettoyer fichier temporaire en cas d'échec
            tmp_filepath.unlink(missing_ok=True)
            return False

        # Créer l'entrée d'index
        entry = CacheEntry(
            key=key,
            indicator_name=indicator_name,
            params_hash=params_hash,
            data_hash=data_hash,
            created_at=now,
            expires_at=expires_at,
            size_bytes=size_bytes,
            filepath=filepath
        )

        self._index[key] = entry
        self._save_index()
        self._update_stats()

        logger.debug(f"Cache PUT: {indicator_name} [{key[:16]}] ({size_bytes/1024:.1f}KB)")
        return True

    def _remove_entry(self, entry: CacheEntry, update_index: bool = True) -> None:
        """Supprime une entrée du cache."""
        try:
            if entry.filepath.exists():
                entry.filepath.unlink()
        except Exception:
            pass

        self._memory_cache.pop(entry.key, None)

        if entry.key in self._index:
            del self._index[entry.key]
            self.stats.evictions += 1

        if update_index:
            self._save_index()

    def _enforce_size_limit(self, new_size: int) -> None:
        """Applique la limite de taille en supprimant les anciennes entrées."""
        current_size = sum(e.size_bytes for e in self._index.values())
        target_size = self.max_size_mb * 1024 * 1024

        if current_size + new_size <= target_size:
            return

        # Trier par date de création (plus ancien en premier)
        sorted_entries = sorted(
            self._index.values(),
            key=lambda e: e.created_at
        )

        # Supprimer jusqu'à avoir assez de place
        while current_size + new_size > target_size and sorted_entries:
            entry = sorted_entries.pop(0)
            current_size -= entry.size_bytes
            self._remove_entry(entry, update_index=False)
            logger.debug(f"Eviction: {entry.indicator_name} [{entry.key[:16]}]")

        self._save_index()

    def _update_stats(self) -> None:
        """Met à jour les statistiques."""
        self.stats.entries_count = len(self._index)
        self.stats.total_size_mb = sum(
            e.size_bytes for e in self._index.values()
        ) / (1024 * 1024)

    def invalidate(self, indicator_name: Optional[str] = None) -> int:
        """
        Invalide des entrées du cache.

        Args:
            indicator_name: Si fourni, invalide seulement cet indicateur.
                           Si None, invalide tout le cache.

        Returns:
            Nombre d'entrées supprimées
        """
        if not self.enabled:
            return 0

        if indicator_name is None:
            self._memory_cache.clear()
        else:
            prefix = f"{indicator_name}_"
            keys_to_drop = [k for k in self._memory_cache if k.startswith(prefix)]
            for key in keys_to_drop:
                self._memory_cache.pop(key, None)

        count = 0
        entries_to_remove = []

        for key, entry in self._index.items():
            if indicator_name is None or entry.indicator_name == indicator_name:
                entries_to_remove.append(entry)

        for entry in entries_to_remove:
            self._remove_entry(entry, update_index=False)
            count += 1

        self._save_index()
        self._update_stats()

        logger.info(f"Cache invalidé: {count} entrées")
        return count

    def clear(self) -> None:
        """Vide complètement le cache."""
        if not self.enabled:
            return

        try:
            shutil.rmtree(self.cache_dir)
            self._init_cache_dir()
            self._index = {}
            self.stats = CacheStats()
            self._memory_cache.clear()
            logger.info("Cache vidé")
        except Exception as e:
            logger.warning(f"Erreur vidage cache: {e}")

    def cleanup_expired(self) -> int:
        """
        Supprime les entrées expirées.

        Returns:
            Nombre d'entrées supprimées
        """
        if not self.enabled:
            return 0

        count = 0
        entries_to_remove = []

        for entry in self._index.values():
            if entry.is_expired():
                entries_to_remove.append(entry)

        for entry in entries_to_remove:
            self._remove_entry(entry, update_index=False)
            count += 1

        if count > 0:
            self._save_index()
            self._update_stats()
            logger.info(f"Nettoyage: {count} entrées expirées supprimées")

        return count

    def get_stats(self) -> CacheStats:
        """Retourne les statistiques du cache."""
        self._update_stats()
        return self.stats

    def list_entries(self) -> List[Dict[str, Any]]:
        """Liste toutes les entrées du cache."""
        entries = []
        for entry in self._index.values():
            entries.append({
                "key": entry.key,
                "indicator": entry.indicator_name,
                "created_at": entry.created_at,
                "expires_at": entry.expires_at,
                "size_kb": entry.size_bytes / 1024,
                "expired": entry.is_expired()
            })
        return sorted(entries, key=lambda e: e["created_at"], reverse=True)


# Instance globale
_default_bank: Optional[IndicatorBank] = None


def get_indicator_bank(
    cache_dir: Union[str, Path] = ".indicator_cache",
    disk_enabled: Optional[bool] = None,
    **kwargs
) -> IndicatorBank:
    """
    Retourne l'instance globale de l'IndicatorBank.

    Args:
        cache_dir: Répertoire de cache
        **kwargs: Arguments supplémentaires pour IndicatorBank

    Returns:
        Instance IndicatorBank
    """
    global _default_bank

    # Config via variables d'environnement (priorité à INDICATOR_CACHE_*)
    env_enabled = _env_bool("INDICATOR_CACHE_ENABLED")
    env_disk_enabled = _env_bool("INDICATOR_CACHE_DISK_ENABLED")
    env_ttl = _env_int("INDICATOR_CACHE_TTL")
    env_max_entries = _env_int("INDICATOR_CACHE_MAX_ENTRIES")
    env_max_size_mb = _env_float("INDICATOR_CACHE_MAX_SIZE_MB")
    env_cache_dir = os.getenv("INDICATOR_CACHE_DIR")

    if disk_enabled is None:
        if env_disk_enabled is not None:
            disk_enabled = env_disk_enabled
        else:
            env_value = os.getenv("BACKTEST_INDICATOR_DISK_CACHE")
            if env_value is not None:
                disk_enabled = env_value.strip().lower() not in ("0", "false", "no", "off")
    if env_cache_dir:
        cache_dir = env_cache_dir
    if env_enabled is not None and "enabled" not in kwargs:
        kwargs["enabled"] = env_enabled
    if env_ttl is not None and "ttl" not in kwargs:
        kwargs["ttl"] = env_ttl
    if env_max_entries is not None and "memory_max_entries" not in kwargs:
        kwargs["memory_max_entries"] = env_max_entries
    if env_max_size_mb is not None and "max_size_mb" not in kwargs:
        kwargs["max_size_mb"] = env_max_size_mb

    if _default_bank is None:
        _default_bank = IndicatorBank(
            cache_dir=cache_dir,
            disk_enabled=True if disk_enabled is None else disk_enabled,
            **kwargs
        )
    else:
        # Appliquer les overrides dynamiquement (si variables env changent)
        if env_cache_dir:
            new_path = Path(cache_dir)
            if _default_bank.cache_dir != new_path:
                _default_bank.cache_dir = new_path
                _default_bank._index_path = new_path / "index.json"
                if _default_bank.disk_enabled:
                    _default_bank._init_cache_dir()
                    _default_bank._load_index()
        if disk_enabled is not None:
            _default_bank.disk_enabled = disk_enabled
        if "enabled" in kwargs:
            _default_bank.enabled = bool(kwargs["enabled"])
        if "ttl" in kwargs:
            _default_bank.ttl = int(kwargs["ttl"])
        if "memory_max_entries" in kwargs:
            _default_bank.memory_max_entries = int(kwargs["memory_max_entries"])
        if "max_size_mb" in kwargs:
            _default_bank.max_size_mb = float(kwargs["max_size_mb"])

    return _default_bank


def cached_indicator(indicator_func):
    """
    Décorateur pour cacher automatiquement les résultats d'un indicateur.

    Usage:
        @cached_indicator
        def my_indicator(df, params):
            # calculs...
            return result
    """
    def wrapper(df: pd.DataFrame, params: Dict[str, Any]):
        bank = get_indicator_bank()
        indicator_name = indicator_func.__name__

        # Vérifier le cache
        result = bank.get(indicator_name, params, df)
        if result is not None:
            return result

        # Calculer
        result = indicator_func(df, params)

        # Mettre en cache
        bank.put(indicator_name, params, df, result)

        return result

    wrapper.__name__ = indicator_func.__name__
    wrapper.__doc__ = indicator_func.__doc__
    return wrapper


__all__ = [
    "IndicatorBank",
    "CacheStats",
    "CacheEntry",
    "get_indicator_bank",
    "cached_indicator",
]
