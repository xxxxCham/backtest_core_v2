"""
Module-ID: utils.checkpoint

Purpose: Gestionnaire de checkpoints pour sauvegarde/reprise automatique d'opérations longues (sweeps, optimisations).

Role in pipeline: resilience / state management

Key components: CheckpointManager, CheckpointMetadata, checkpoint_context (context manager)

Inputs: operation_type (str), state (dict), checkpoint_dir (Path optionnel)

Outputs: Fichiers JSON checkpoint (state + metadata), resume capability après crash/interruption

Dependencies: json, pathlib, dataclasses, utils.log, hashlib

Conventions: Checkpoints JSON pour portabilité/lisibilité; checkpoint_id unique (hash params); progress 0.0-1.0; auto-save périodique; resume transparente via checkpoint_context(); nettoyage automatique anciens checkpoints.

Read-if: Gestion checkpoints pour sweeps, recovery après crash, ou state persistence long-running ops.

Skip-if: Opérations courtes sans besoin de resume/recovery.
"""

import hashlib
import json
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TypeVar

from utils.log import get_logger

logger = get_logger(__name__)

T = TypeVar('T')


@dataclass
class CheckpointMetadata:
    """
    Métadonnées d'un checkpoint.

    Attributes:
        checkpoint_id: Identifiant unique
        created_at: Timestamp création
        operation_type: Type d'opération (sweep, validation, etc.)
        progress: Progression (0.0 à 1.0)
        total_items: Nombre total d'éléments
        completed_items: Éléments terminés
        status: 'running', 'paused', 'completed', 'failed'
    """
    checkpoint_id: str
    created_at: str
    operation_type: str
    progress: float = 0.0
    total_items: int = 0
    completed_items: int = 0
    status: str = "running"
    last_updated: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CheckpointMetadata":
        """Crée depuis un dictionnaire."""
        return cls(**data)


@dataclass
class Checkpoint:
    """
    Point de sauvegarde complet.

    Attributes:
        metadata: Métadonnées du checkpoint
        state: État à sauvegarder (dict arbitraire)
        results: Résultats partiels accumulés
    """
    metadata: CheckpointMetadata
    state: Dict[str, Any] = field(default_factory=dict)
    results: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "metadata": self.metadata.to_dict(),
            "state": self.state,
            "results": self.results,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Checkpoint":
        """Crée depuis un dictionnaire."""
        return cls(
            metadata=CheckpointMetadata.from_dict(data["metadata"]),
            state=data.get("state", {}),
            results=data.get("results", []),
        )

    def add_result(self, result: Dict[str, Any]):
        """Ajoute un résultat."""
        self.results.append(result)
        self.metadata.completed_items = len(self.results)
        if self.metadata.total_items > 0:
            self.metadata.progress = len(self.results) / self.metadata.total_items
        self.metadata.last_updated = datetime.now().isoformat()


class CheckpointManager:
    """
    Gestionnaire de checkpoints pour opérations longues.

    Example:
        >>> manager = CheckpointManager("./checkpoints")
        >>>
        >>> # Créer un nouveau checkpoint
        >>> checkpoint = manager.create("sweep", total_items=100)
        >>>
        >>> # Boucle avec sauvegarde périodique
        >>> for i, params in enumerate(param_grid):
        ...     result = run_backtest(params)
        ...     checkpoint.add_result({"params": params, "score": result})
        ...
        ...     if i % 10 == 0:
        ...         manager.save(checkpoint)
        >>>
        >>> # Marquer comme terminé
        >>> manager.complete(checkpoint)
    """

    def __init__(
        self,
        checkpoint_dir: str = ".checkpoints",
        auto_save_interval: int = 10,
        max_checkpoints: int = 5,
    ):
        """
        Initialise le gestionnaire.

        Args:
            checkpoint_dir: Répertoire de stockage
            auto_save_interval: Intervalle de sauvegarde auto (en items)
            max_checkpoints: Nombre max de checkpoints à conserver
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.auto_save_interval = auto_save_interval
        self.max_checkpoints = max_checkpoints

        # Créer le répertoire si nécessaire
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"CheckpointManager initialisé: {self.checkpoint_dir}")

    def _generate_id(self, operation_type: str) -> str:
        """Génère un ID unique pour le checkpoint."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        hash_part = hashlib.md5(
            f"{operation_type}_{time.time()}".encode()
        ).hexdigest()[:8]
        return f"{operation_type}_{timestamp}_{hash_part}"

    def _get_checkpoint_path(self, checkpoint_id: str) -> Path:
        """Retourne le chemin du fichier checkpoint."""
        return self.checkpoint_dir / f"{checkpoint_id}.json"

    def create(
        self,
        operation_type: str,
        total_items: int = 0,
        initial_state: Optional[Dict[str, Any]] = None,
    ) -> Checkpoint:
        """
        Crée un nouveau checkpoint.

        Args:
            operation_type: Type d'opération (ex: "sweep", "validation")
            total_items: Nombre total d'éléments à traiter
            initial_state: État initial optionnel

        Returns:
            Nouveau Checkpoint
        """
        checkpoint_id = self._generate_id(operation_type)

        metadata = CheckpointMetadata(
            checkpoint_id=checkpoint_id,
            created_at=datetime.now().isoformat(),
            operation_type=operation_type,
            total_items=total_items,
            status="running",
        )

        checkpoint = Checkpoint(
            metadata=metadata,
            state=initial_state or {},
            results=[],
        )

        # Sauvegarde initiale
        self.save(checkpoint)

        logger.info(f"Checkpoint créé: {checkpoint_id}")

        return checkpoint

    def save(self, checkpoint: Checkpoint):
        """
        Sauvegarde un checkpoint.

        Args:
            checkpoint: Checkpoint à sauvegarder
        """
        checkpoint.metadata.last_updated = datetime.now().isoformat()

        path = self._get_checkpoint_path(checkpoint.metadata.checkpoint_id)

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(checkpoint.to_dict(), f, indent=2, ensure_ascii=False)

        logger.debug(
            f"Checkpoint sauvegardé: {checkpoint.metadata.checkpoint_id} "
            f"({checkpoint.metadata.completed_items}/{checkpoint.metadata.total_items})"
        )

        # Nettoyer les vieux checkpoints
        self._cleanup_old_checkpoints(checkpoint.metadata.operation_type)

    def load(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """
        Charge un checkpoint existant.

        Args:
            checkpoint_id: ID du checkpoint

        Returns:
            Checkpoint chargé ou None si non trouvé
        """
        path = self._get_checkpoint_path(checkpoint_id)

        if not path.exists():
            logger.warning(f"Checkpoint non trouvé: {checkpoint_id}")
            return None

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            checkpoint = Checkpoint.from_dict(data)
            logger.info(
                f"Checkpoint chargé: {checkpoint_id} "
                f"(progress: {checkpoint.metadata.progress:.1%})"
            )
            return checkpoint

        except Exception as e:
            logger.error(f"Erreur chargement checkpoint: {e}")
            return None

    def find_latest(self, operation_type: str) -> Optional[Checkpoint]:
        """
        Trouve le checkpoint le plus récent pour un type d'opération.

        Args:
            operation_type: Type d'opération

        Returns:
            Checkpoint le plus récent ou None
        """
        checkpoints = self.list_checkpoints(operation_type)

        if not checkpoints:
            return None

        # Trier par date de création
        checkpoints.sort(key=lambda c: c.metadata.created_at, reverse=True)

        return checkpoints[0]

    def find_incomplete(self, operation_type: str) -> Optional[Checkpoint]:
        """
        Trouve un checkpoint incomplet pour reprise.

        Args:
            operation_type: Type d'opération

        Returns:
            Checkpoint incomplet le plus récent ou None
        """
        checkpoints = self.list_checkpoints(operation_type)

        # Filtrer les incomplets
        incomplete = [
            c for c in checkpoints
            if c.metadata.status in ("running", "paused")
        ]

        if not incomplete:
            return None

        # Trier par date
        incomplete.sort(key=lambda c: c.metadata.created_at, reverse=True)

        return incomplete[0]

    def list_checkpoints(
        self,
        operation_type: Optional[str] = None
    ) -> List[Checkpoint]:
        """
        Liste tous les checkpoints.

        Args:
            operation_type: Filtrer par type (optionnel)

        Returns:
            Liste des checkpoints
        """
        checkpoints = []

        for path in self.checkpoint_dir.glob("*.json"):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                checkpoint = Checkpoint.from_dict(data)

                if operation_type is None or \
                   checkpoint.metadata.operation_type == operation_type:
                    checkpoints.append(checkpoint)

            except Exception as e:
                logger.warning(f"Erreur lecture {path}: {e}")

        return checkpoints

    def complete(self, checkpoint: Checkpoint):
        """
        Marque un checkpoint comme terminé.

        Args:
            checkpoint: Checkpoint à marquer
        """
        checkpoint.metadata.status = "completed"
        checkpoint.metadata.progress = 1.0
        self.save(checkpoint)
        logger.info(f"Checkpoint terminé: {checkpoint.metadata.checkpoint_id}")

    def fail(self, checkpoint: Checkpoint, error: str):
        """
        Marque un checkpoint comme échoué.

        Args:
            checkpoint: Checkpoint
            error: Message d'erreur
        """
        checkpoint.metadata.status = "failed"
        checkpoint.metadata.error_message = error
        self.save(checkpoint)
        logger.error(f"Checkpoint échoué: {checkpoint.metadata.checkpoint_id}")

    def pause(self, checkpoint: Checkpoint):
        """
        Met en pause un checkpoint.

        Args:
            checkpoint: Checkpoint à mettre en pause
        """
        checkpoint.metadata.status = "paused"
        self.save(checkpoint)
        logger.info(f"Checkpoint en pause: {checkpoint.metadata.checkpoint_id}")

    def delete(self, checkpoint_id: str):
        """
        Supprime un checkpoint.

        Args:
            checkpoint_id: ID du checkpoint
        """
        path = self._get_checkpoint_path(checkpoint_id)

        if path.exists():
            path.unlink()
            logger.info(f"Checkpoint supprimé: {checkpoint_id}")

    def _cleanup_old_checkpoints(self, operation_type: str):
        """
        Nettoie les vieux checkpoints pour économiser l'espace.

        Garde seulement les max_checkpoints plus récents par type.
        """
        checkpoints = self.list_checkpoints(operation_type)

        # Trier par date (plus récent en premier)
        checkpoints.sort(key=lambda c: c.metadata.created_at, reverse=True)

        # Supprimer les excédentaires
        for checkpoint in checkpoints[self.max_checkpoints:]:
            if checkpoint.metadata.status == "completed":
                self.delete(checkpoint.metadata.checkpoint_id)

    @contextmanager
    def checkpoint_context(
        self,
        operation_type: str,
        total_items: int,
        resume: bool = True,
    ):
        """
        Context manager pour checkpoint automatique.

        Args:
            operation_type: Type d'opération
            total_items: Nombre total d'éléments
            resume: Tenter de reprendre un checkpoint existant

        Yields:
            Tuple (checkpoint, start_index)
        """
        # Essayer de reprendre
        checkpoint = None
        start_index = 0

        if resume:
            checkpoint = self.find_incomplete(operation_type)
            if checkpoint:
                start_index = checkpoint.metadata.completed_items
                checkpoint.metadata.status = "running"
                logger.info(
                    f"Reprise checkpoint: {checkpoint.metadata.checkpoint_id} "
                    f"à l'index {start_index}"
                )

        # Créer nouveau si pas de reprise
        if checkpoint is None:
            checkpoint = self.create(operation_type, total_items)

        try:
            yield checkpoint, start_index
            self.complete(checkpoint)
        except KeyboardInterrupt:
            self.pause(checkpoint)
            raise
        except Exception as e:
            self.fail(checkpoint, str(e))
            raise


# Singleton global
_default_manager: Optional[CheckpointManager] = None


def get_checkpoint_manager(
    checkpoint_dir: str = ".checkpoints"
) -> CheckpointManager:
    """
    Récupère le gestionnaire de checkpoints global.

    Args:
        checkpoint_dir: Répertoire de stockage

    Returns:
        CheckpointManager singleton
    """
    global _default_manager

    if _default_manager is None:
        _default_manager = CheckpointManager(checkpoint_dir)

    return _default_manager
