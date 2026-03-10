"""
Module-ID: utils.backend_config

Purpose: Configuration centralisée du backend de calcul (CPU/GPU/Auto).

Role in pipeline: infrastructure

Key components: BackendType enum, get_backend(), is_gpu_enabled()

Inputs: Variable d'environnement BACKTEST_BACKEND (ignorée en CPU-only)

Outputs: BackendType sélectionné

Dependencies: os, enum

Conventions: Défaut=CPU (mode strict), GPU=opt-in explicite.

Read-if: Modification sélection backend ou ajout nouveau mode.

Skip-if: Vous utilisez juste is_gpu_enabled() pour vérifier.
"""

from enum import Enum
from typing import Optional

__all__ = ["BackendType", "get_backend", "is_gpu_enabled", "reset_backend"]


class BackendType(Enum):
    """Type de backend pour les calculs."""
    CPU = "cpu"
    GPU = "gpu"
    AUTO = "auto"


# Cache global du backend sélectionné
_BACKEND: Optional[BackendType] = None


def get_backend() -> BackendType:
    """
    Retourne le backend (CPU-only).

    Returns:
        BackendType sélectionné

    Examples:
        >>> import os
        >>> os.environ["BACKTEST_BACKEND"] = "cpu"
        >>> get_backend()
        <BackendType.CPU: 'cpu'>

        >>> os.environ["BACKTEST_BACKEND"] = "gpu"
        >>> get_backend()
        <BackendType.CPU: 'cpu'>
    """
    global _BACKEND

    if _BACKEND is None:
        # CPU-only strict
        _BACKEND = BackendType.CPU

    return _BACKEND


def is_gpu_enabled() -> bool:
    """
    Retourne True si le GPU peut être utilisé.

    Mode CPU-only: retourne toujours False.

    Returns:
        bool: True si GPU autorisé

    Examples:
        >>> import os
        >>> os.environ["BACKTEST_BACKEND"] = "cpu"
        >>> is_gpu_enabled()
        False

        >>> os.environ["BACKTEST_BACKEND"] = "gpu"
        >>> is_gpu_enabled()
        False
    """
    return False


def reset_backend() -> None:
    """
    Réinitialise le cache du backend (pour tests uniquement).

    Examples:
        >>> import os
        >>> os.environ["BACKTEST_BACKEND"] = "cpu"
        >>> get_backend()
        <BackendType.CPU: 'cpu'>
        >>> os.environ["BACKTEST_BACKEND"] = "gpu"
        >>> reset_backend()
        >>> get_backend()
        <BackendType.CPU: 'cpu'>
    """
    global _BACKEND
    _BACKEND = None
