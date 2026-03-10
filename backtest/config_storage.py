"""
Module-ID: backtest.config_storage

Purpose: Centraliser les chemins de stockage des artefacts (rapports, logs, etc.).

Role in pipeline: configuration / storage

Key components: get_artifacts_root

Inputs: Optionnel root explicite ou variable d'environnement

Outputs: pathlib.Path vers le répertoire d'artefacts

Dependencies: pathlib, os

Conventions: utilise "artifacts/" par défaut; création automatique des dossiers.

Read-if: Vous gérez les chemins de sortie des artefacts.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

DEFAULT_ARTIFACTS_DIR = Path("artifacts")


def get_artifacts_root(
    root: Optional[Union[str, Path]] = None,
    *,
    create: bool = True,
) -> Path:
    """
    Retourne le répertoire racine des artefacts.

    Args:
        root: Chemin explicite (str/Path). Si None, utilise l'env ou le défaut.
        create: Créer le dossier si inexistant

    Returns:
        Path vers le répertoire d'artefacts
    """
    if root is None:
        env_root = os.getenv("BACKTEST_ARTIFACTS_DIR")
        root = env_root if env_root else DEFAULT_ARTIFACTS_DIR

    path = Path(root).expanduser()
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


__all__ = ["get_artifacts_root"]
