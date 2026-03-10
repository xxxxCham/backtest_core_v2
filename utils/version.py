"""
Module-ID: utils.version

Purpose: Gestion version et traçabilité Git (commit hash pour reproducibilité).

Role in pipeline: observability

Key components: get_git_commit(), get_version(), BUILD_INFO

Inputs: None (queries Git locally)

Outputs: Commit hash short/long, version string, build metadata

Dependencies: subprocess, pathlib

Conventions: git rev-parse pour commit; short=True (7 chars) défaut.

Read-if: Modification version retrieval ou build metadata.

Skip-if: Vous appelez get_git_commit().
"""

import subprocess


def get_git_commit(short: bool = True) -> str:
    """
    Récupère le hash du commit Git courant.

    Utile pour traçabilité : permet de savoir quelle version du code
    a produit un résultat de backtest spécifique.

    Args:
        short: Si True, retourne hash court (7 chars). Si False, hash complet.

    Returns:
        Hash du commit Git ou "unknown" si indisponible

    Examples:
        >>> commit = get_git_commit()
        >>> print(f"Run exécuté avec commit: {commit}")
        Run exécuté avec commit: a3f7b2c
    """
    try:
        cmd = ["git", "rev-parse"]
        if short:
            cmd.append("--short")
        cmd.append("HEAD")

        commit = subprocess.check_output(
            cmd,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2  # Timeout pour éviter blocage
        ).strip()

        return commit if commit else "unknown"

    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        # Git non disponible, pas un repo git, ou timeout
        return "unknown"


def get_git_branch() -> str:
    """
    Récupère le nom de la branche Git courante.

    Returns:
        Nom de la branche ou "unknown" si indisponible
    """
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2
        ).strip()

        return branch if branch else "unknown"

    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


def is_git_dirty() -> bool:
    """
    Vérifie si le répertoire Git a des modifications non committées.

    Returns:
        True si modifications présentes, False sinon ou si Git indisponible
    """
    try:
        result = subprocess.check_output(
            ["git", "status", "--porcelain"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2
        ).strip()

        return len(result) > 0

    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


__all__ = ["get_git_commit", "get_git_branch", "is_git_dirty"]
