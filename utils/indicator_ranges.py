"""
Module-ID: utils.indicator_ranges

Purpose: Charge plages paramétriques d'indicateurs depuis config/indicator_ranges.toml.

Role in pipeline: configuration

Key components: load_indicator_ranges(), _INDICATOR_RANGES_CACHE, tomllib wrapper

Inputs: TOML file config/indicator_ranges.toml

Outputs: Dict nested {indicator → param → spec} (cached)

Dependencies: tomllib/tomli, pathlib

Conventions: Cache global; None path → répertoire par défaut.

Read-if: Modification chargement config indicateurs.

Skip-if: Vous appelez load_indicator_ranges() en tant qu'utilisateur.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, TypedDict, Union

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older Python
    import tomli as tomllib


class ParamSpec(TypedDict, total=False):
    """
    Spécification d'un paramètre d'indicateur.

    Attributes:
        min: Valeur minimale
        max: Valeur maximale
        step: Pas d'incrémentation
        default: Valeur par défaut
        description: Description du paramètre
        options: Liste d'options valides (pour paramètres catégoriels)
        type: Type explicite ("string", "bool", etc.)
    """
    min: Union[int, float]
    max: Union[int, float]
    step: Union[int, float]
    default: Union[int, float, str, bool]
    description: str
    options: List[str]
    type: str


_INDICATOR_RANGES_CACHE: Optional[Dict[str, Dict[str, ParamSpec]]] = None


def load_indicator_ranges(path: Optional[Path] = None) -> Dict[str, Dict[str, ParamSpec]]:
    """
    Load indicator ranges from TOML.

    Args:
        path: Optional custom path to the TOML file.
              If None, uses config/indicator_ranges.toml.

    Returns:
        Nested dict from TOML (indicator -> param -> spec).
        Example: {"rsi": {"period": {"min": 7, "max": 21, "default": 14, ...}}}

    Raises:
        ValueError: If TOML file is corrupted.

    Note:
        Results are cached when path=None for performance.
    """
    global _INDICATOR_RANGES_CACHE

    use_cache = path is None
    if _INDICATOR_RANGES_CACHE is not None and use_cache:
        return _INDICATOR_RANGES_CACHE

    if path is None:
        path = Path(__file__).resolve().parents[1] / "config" / "indicator_ranges.toml"

    if not path.exists():
        raise FileNotFoundError(
            f"Fichier de configuration introuvable: {path}\n"
            f"Créez le fichier config/indicator_ranges.toml ou spécifiez un chemin valide."
        )

    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except PermissionError as e:
        raise PermissionError(
            f"Accès refusé au fichier: {path}\n"
            f"Vérifiez les permissions du fichier."
        ) from e
    except (tomllib.TOMLDecodeError if hasattr(tomllib, 'TOMLDecodeError') else Exception) as e:
        raise ValueError(
            f"Fichier TOML corrompu ou invalide: {path}\n"
            f"Erreur de parsing: {e}"
        ) from e
    except Exception as e:
        raise RuntimeError(
            f"Erreur inattendue lors du chargement de {path}: {e}"
        ) from e

    if use_cache:
        _INDICATOR_RANGES_CACHE = data

    return data


def get_indicator_param_specs(
    indicator_name: str,
    ranges: Optional[Dict[str, Dict[str, ParamSpec]]] = None
) -> Dict[str, ParamSpec]:
    """
    Return parameter specs for a single indicator.

    Args:
        indicator_name: Nom de l'indicateur (case-insensitive).
        ranges: Optional pre-loaded ranges dict. If None, loads from default path.

    Returns:
        Dict mapping parameter names to their specifications.
        Example: {"period": {"min": 7, "max": 21, "default": 14, ...}}

    Example:
        >>> specs = get_indicator_param_specs("rsi")
        >>> specs["period"]["default"]
        14
    """
    if ranges is None:
        ranges = load_indicator_ranges()

    return ranges.get(indicator_name.lower(), {})


__all__ = ["load_indicator_ranges", "get_indicator_param_specs", "ParamSpec"]
