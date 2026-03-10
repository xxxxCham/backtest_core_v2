"""
Module-ID: utils.parameters

Purpose: Gestion granularité paramètres, presets, contraintes (contrôle combinatoire).

Role in pipeline: configuration

Key components: ParameterSpec, Preset, ConstraintValidator, SearchSpaceStats, versioned presets

Inputs: Strategy parameter_specs, constraint rules, TOML presets

Outputs: Param grids, SearchSpaceStats, validated presets, versioned snapshots

Dependencies: dataclasses, pathlib, tomllib, typing

Conventions: Granularité 0.0=fin→1.0=grossier; BPS unités; presets source plages optim.

Read-if: Modification presets, contraintes, ou gestion versioning.

Skip-if: Vous appelez juste generate_param_grid() ou list_presets().

TABLE DES MATIÈRES (référence architecture)
==============================================

I.   INFRASTRUCTURE & CONFIGURATION (lignes ~35-250)
     1.1. Imports
     1.2. Logger et constantes
     1.3. Helpers privés de normalisation et conversion
          - _normalize_slug()
          - _to_builtin()
          - _semver_key(), _parse_created_at(), _preset_sort_key()
          - _parse_versioned_id(), _apply_versioned_defaults()
     1.4. Helpers privés de construction
          - _build_fixed_parameter_specs()
          - _compute_param_count() [DÉPLACÉ depuis ancienne ligne 355]
          - _get_repo_root(), _migrate_legacy_presets()

II.  TYPES & STRUCTURES DE DONNÉES (lignes ~250-410)
     2.1. ParameterSpec (dataclass)
     2.2. SearchSpaceStats (dataclass)
     2.3. Preset (dataclass)
     2.4. ParameterConstraint (dataclass)

III. GÉNÉRATION D'ESPACES DE RECHERCHE (lignes ~410-600)
     3.1. parameter_values() - Génération de valeurs selon granularité
     3.2. calculate_combinations() - Calcul du nombre de combinaisons
     3.3. generate_param_grid() - Grille cartésienne de paramètres
     3.4. compute_search_space_stats() - Statistiques unifiées

IV.  SYSTÈME DE CONTRAINTES (lignes ~600-850)
     4.1. ConstraintValidator (classe)
     4.2. COMMON_CONSTRAINTS (registre)
     4.3. get_common_constraints()
     4.4. generate_constrained_param_grid()

V.   PRESETS SIMPLES (IN-MEMORY) (lignes ~850-1070)
     5.1. Définitions des presets
          - SAFE_RANGES_PRESET
          - MINIMAL_PRESET
          - EMA_CROSS_PRESET
          - MACD_CROSS_PRESET
          - RSI_REVERSAL_PRESET
          - ATR_CHANNEL_PRESET
     5.2. Registre PRESETS
     5.3. Fonctions d'accès
          - get_preset()
          - list_presets()

VI.  PRESETS I/O (DISQUE) (lignes ~1070-1120)
     6.1. save_preset()
     6.2. load_preset()

VII. PRESETS VERSIONNÉS (SYSTÈME AVANCÉ) (lignes ~1120-1400)
     7.1. Configuration et gestion du répertoire
          - get_versioned_presets_dir()
     7.2. Sauvegarde et chargement
          - save_versioned_preset()
          - load_strategy_version()
     7.3. Listage et résolution
          - list_strategy_versions()
          - resolve_latest_version()
     7.4. Validation
          - validate_before_use()

VIII. EXPORTS (lignes ~1400-1450)
     8.1. __all__

---

NOTES IMPORTANTES
=================

SOURCE OF TRUTH pour les valeurs par défaut:
--------------------------------------------
Les valeurs par défaut (default) sont définies dans les classes de stratégies
(strategies/*.py) via la propriété `parameter_specs`.

Les PRESETS dans ce fichier définissent les PLAGES D'OPTIMISATION (min/max)
et peuvent avoir des defaults DIFFÉRENTS des stratégies pour certains cas d'usage
(ex: MINIMAL_PRESET avec granularité=1.0 pour tests rapides).

Règle: Les stratégies sont la source de vérité. Les presets sont des configurations
d'optimisation qui peuvent dériver de ces valeurs.

Architecture des responsabilités:
---------------------------------
- Chapitre I-II: Fondations (types, helpers)
- Chapitre III: Moteur de génération d'espaces de recherche
- Chapitre IV: Filtrage et contraintes
- Chapitre V-VI: Presets simples (configs prédéfinies)
- Chapitre VII: Système avancé de versioning (snapshot de résultats)

Concepts clés:
-------------
- Granularité 0% = très fin (beaucoup de valeurs)
- Granularité 100% = très grossier (peu de valeurs, souvent juste la médiane)
- Maximum 4 valeurs par paramètre (règle de plafonnement)
- Contraintes inter-paramètres (ex: slow > fast)
"""

# pylint: disable=too-many-lines

# =============================================================================
# I. INFRASTRUCTURE & CONFIGURATION
# =============================================================================

# --- 1.1. Imports ---
import json
import os
import re
import shutil
from decimal import Decimal, ROUND_FLOOR
from dataclasses import dataclass, field
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from utils.log import get_logger

logger = get_logger(__name__)


# --- 1.2. Logger et constantes ---
VERSIONED_PRESETS_DIR_ENV = "BACKTEST_PRESETS_DIR"
DEFAULT_STRATEGY_VERSION = "0.0.1"
_VERSIONED_NAME_RE = re.compile(
    r"^(?P<strategy>[a-z0-9_-]+)@(?P<version>[^_]+)__(?P<preset>[a-z0-9_-]+)$"
)


# --- 1.3. Helpers privés de normalisation et conversion ---

def _normalize_slug(value: str) -> str:
    """Normalise une chaîne en slug (minuscules, underscores)."""
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "preset"


def _to_builtin(value: Any) -> Any:
    """Convertit les types numpy en types Python natifs pour sérialisation JSON."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _to_builtin(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_builtin(v) for v in value]
    return value


def _parse_versioned_id(value: str) -> Optional[Dict[str, str]]:
    """Parse un ID de preset versionné (format: strategy@version__preset)."""
    match = _VERSIONED_NAME_RE.match(value)
    if not match:
        return None
    return match.groupdict()


def _semver_key(version: str) -> Tuple[int, int, int, str]:
    """Clé de tri pour semantic versioning."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version or "")
    if not match:
        return (0, 0, 0, version or "")
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch), version or "")


def _parse_created_at(value: Optional[str]) -> Optional[datetime]:
    """Parse une date ISO 8601."""
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1]
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _preset_sort_key(preset: "Preset") -> Tuple[Tuple[int, int, int, str], int, str]:
    """Clé de tri pour presets (par version, date, nom)."""
    meta = preset.metadata or {}
    version = meta.get("version") or ""
    created_at = _parse_created_at(meta.get("created_at"))
    created_rank = int(created_at.timestamp()) if created_at else 0
    return (_semver_key(version), created_rank, preset.name)


def _apply_versioned_defaults(
    preset: "Preset",
    strategy_name: str,
    parsed: Optional[Dict[str, str]],
    source_path: Optional[Path],
) -> None:
    """Applique les métadonnées par défaut à un preset versionné."""
    preset.metadata = preset.metadata or {}
    if "strategy" not in preset.metadata and strategy_name:
        preset.metadata["strategy"] = strategy_name
    if parsed:
        preset.metadata.setdefault("strategy_slug", parsed["strategy"])
        preset.metadata.setdefault("version", parsed["version"])
        preset.metadata.setdefault("preset_slug", parsed["preset"])
    if "preset_name" not in preset.metadata:
        preset.metadata["preset_name"] = preset.name
    if source_path is not None:
        preset.metadata.setdefault("source_path", str(source_path))


# --- 1.4. Helpers privés de construction ---

def _build_fixed_parameter_specs(
    params_values: Dict[str, Any]
) -> Dict[str, "ParameterSpec"]:
    """Construit des ParameterSpec à partir de valeurs fixes."""
    specs: Dict[str, "ParameterSpec"] = {}
    for name, raw_value in params_values.items():
        value = _to_builtin(raw_value)
        if isinstance(value, float) and value.is_integer():
            value = int(value)

        if isinstance(value, bool):
            specs[name] = ParameterSpec(
                name=name,
                min_val=0,
                max_val=1,
                default=int(value),
                step=1,
                param_type="bool",
                description="Fixed value",
            )
        elif isinstance(value, int):
            specs[name] = ParameterSpec(
                name=name,
                min_val=value,
                max_val=value,
                default=value,
                step=1,
                param_type="int",
                description="Fixed value",
            )
        elif isinstance(value, float):
            specs[name] = ParameterSpec(
                name=name,
                min_val=value,
                max_val=value,
                default=value,
                step=0.01,
                param_type="float",
                description="Fixed value",
            )
        else:
            raise ValueError(
                f"Unsupported param type for '{name}': {type(value)}"
            )
    return specs


def _compute_param_count(
    spec: Any,
    granularity: Optional[float] = None,
) -> int:
    """
    Calcule le nombre de valeurs pour un paramètre.

    Returns:
        Nombre de valeurs, ou -1 si continu
    """
    # Cas 1: ParameterSpec
    if isinstance(spec, ParameterSpec):
        if granularity is not None:
            # Utiliser la logique de granularité
            values = parameter_values(
                min_val=spec.min_val,
                max_val=spec.max_val,
                granularity=granularity,
                param_type=spec.param_type,
            )
            return len(values)
        elif spec.step and spec.step > 0:
            return int((spec.max_val - spec.min_val) / spec.step) + 1
        else:
            return -1  # Continu

    # Cas 1b: Liste/array explicite de valeurs
    if isinstance(spec, (list, np.ndarray)):
        try:
            return max(1, len(spec))
        except Exception:
            return 1

    # Cas 2: Tuple (min, max) ou (min, max, step)
    if isinstance(spec, tuple):
        if len(spec) == 3:
            min_v, max_v, step = spec
            if step and step > 0:
                return int((max_v - min_v) / step) + 1
            return -1
        elif len(spec) == 2:
            return -1  # Continu
        # Fallback: tuple de valeurs explicites
        return max(1, len(spec))

    # Cas 3: Dict avec "min", "max", "step"
    if isinstance(spec, dict):
        min_v = spec.get("min", spec.get("min_val"))
        max_v = spec.get("max", spec.get("max_val"))
        step = spec.get("step")
        count = spec.get("count")
        values = spec.get("values")

        # Priorité 1: count explicite (UI)
        if count is not None:
            try:
                return max(1, int(count))
            except Exception:
                return 1

        # Priorité 2: liste de valeurs explicite
        if isinstance(values, (list, tuple)):
            return max(1, len(values))

        # Priorité 3: calcul discret robuste
        if min_v is not None and max_v is not None:
            if step and step > 0:
                try:
                    n = int(round((float(max_v) - float(min_v)) / float(step))) + 1
                    return max(1, n)
                except Exception:
                    return 1
            return -1
        return 1

    return 1


def _get_repo_root() -> Path:
    """Retourne la racine du repository."""
    return Path(__file__).resolve().parents[1]


def _migrate_legacy_presets(target_dir: Path) -> None:
    """Migre les anciens presets depuis ui/data/presets vers le nouveau répertoire."""
    repo_root = _get_repo_root()
    legacy_dirs = [
        repo_root / "ui" / "data" / "presets",
    ]
    for legacy_dir in legacy_dirs:
        if not legacy_dir.exists():
            continue
        moved = 0
        for path in legacy_dir.glob("*.json"):
            target_dir.mkdir(parents=True, exist_ok=True)
            dest = target_dir / path.name
            if dest.exists():
                continue
            try:
                shutil.move(str(path), str(dest))
                moved += 1
            except Exception as exc:
                logger.warning(
                    "Failed to migrate preset %s: %s", path, exc
                )
        if moved:
            logger.info(
                "Migrated %s preset files from %s",
                moved,
                legacy_dir,
            )


# =============================================================================
# II. TYPES & STRUCTURES DE DONNÉES
# =============================================================================

# --- 2.1. ParameterSpec ---

@dataclass
class ParameterSpec:
    """
    Spécification d'un paramètre avec ses bornes et contraintes.

    Attributes:
        name: Nom du paramètre
        min_val: Valeur minimale
        max_val: Valeur maximale
        default: Valeur par défaut
        step: Pas d'incrémentation (optionnel)
        param_type: Type ('int', 'float', 'bool')
        description: Description pour l'UI
        optimize: Inclus par défaut dans l'exploration des grilles
    """
    name: str
    min_val: float
    max_val: float
    default: float
    step: Optional[float] = None
    param_type: str = "float"
    description: str = ""
    optimize: bool = True

    def __post_init__(self):
        if self.step is None:
            # Calculer un step raisonnable
            range_size = self.max_val - self.min_val
            if self.param_type == "int":
                self.step = max(1, int(range_size / 10))
            else:
                self.step = range_size / 10

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "min": self.min_val,
            "max": self.max_val,
            "default": self.default,
            "step": self.step,
            "type": self.param_type,
            "description": self.description,
            "optimize": self.optimize,
        }


# --- 2.2. SearchSpaceStats ---

@dataclass
class SearchSpaceStats:
    """
    Statistiques unifiées d'un espace de recherche.

    Utilisé par:
    - CLI sweep: pour afficher le nombre de combinaisons
    - UI Grille: pour valider avant exécution
    - UI LLM: pour estimer l'espace (si step connu)

    Attributes:
        total_combinations: Nombre total de combinaisons (-1 si continu)
        per_param_counts: Nombre de valeurs par paramètre
        warnings: Liste d'avertissements
        has_overflow: True si dépasse max_combinations
        is_continuous: True si au moins un param sans step
    """
    total_combinations: int
    per_param_counts: Dict[str, int]
    warnings: List[str]
    has_overflow: bool
    is_continuous: bool

    def summary(self) -> str:
        """Retourne un résumé textuel."""
        if self.is_continuous:
            return "Espace continu (exploration adaptative)"
        return f"{self.total_combinations:,} combinaisons"

    def to_dict(self) -> Dict[str, Any]:
        """Conversion en dict pour sérialisation."""
        return {
            "total_combinations": self.total_combinations,
            "per_param_counts": self.per_param_counts,
            "warnings": self.warnings,
            "has_overflow": self.has_overflow,
            "is_continuous": self.is_continuous,
        }


# --- 2.3. Preset ---

@dataclass
class Preset:
    """
    Preset de configuration (ex: Safe Ranges).

    Définit un ensemble d'indicateurs/paramètres pré-configurés
    pour un usage courant.
    """
    name: str
    description: str
    parameters: Dict[str, ParameterSpec] = field(default_factory=dict)
    indicators: List[str] = field(default_factory=list)
    default_granularity: float = 0.5
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {k: v.to_dict() for k, v in self.parameters.items()},
            "indicators": self.indicators,
            "default_granularity": self.default_granularity,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Preset":
        params = {}
        for name, spec in data.get("parameters", {}).items():
            params[name] = ParameterSpec(
                name=name,
                min_val=spec["min"],
                max_val=spec["max"],
                default=spec["default"],
                step=spec.get("step"),
                param_type=spec.get("type", "float"),
                description=spec.get("description", ""),
                optimize=spec.get("optimize", True)
            )

        return cls(
            name=data["name"],
            description=data.get("description", ""),
            parameters=params,
            indicators=data.get("indicators", []),
            default_granularity=data.get("default_granularity", 0.5),
            metadata=data.get("metadata", {}),
        )

    def get_default_values(self) -> Dict[str, Any]:
        """Retourne les valeurs par défaut de tous les paramètres."""
        return {name: spec.default for name, spec in self.parameters.items()}

    def estimate_combinations(
        self, granularity: Optional[float] = None
    ) -> int:
        """Estime le nombre de combinaisons pour une granularité donnée."""
        if granularity is None:
            g = self.default_granularity
        else:
            g = granularity
        total, _ = calculate_combinations(self.parameters, g)
        return total


# --- 2.4. RangeProposal ---

@dataclass
class RangeProposal:
    """
    Proposition de plages de paramètres pour grid search par le LLM.

    Permet au LLM de demander une exploration de paramètres au lieu de
    configurations individuelles (ex: "bb_period entre 20-25 avec step 1").

    Attributes:
        ranges: Dict {param_name: {"min": x, "max": y, "step": z}}
        rationale: Raison de cette exploration (pour logs/debug)
        optimize_for: Métrique cible (sharpe_ratio, sortino_ratio, etc.)
        max_combinations: Limite du nombre de combinaisons à tester
        early_stop_threshold: Arrêt anticipé si métrique atteinte

    Example:
        >>> proposal = RangeProposal(
        ...     ranges={
        ...         "bb_period": {"min": 20, "max": 25, "step": 1},
        ...         "bb_std": {"min": 2.0, "max": 2.5, "step": 0.1}
        ...     },
        ...     rationale="Explorer corrélation bb_period vs bb_std",
        ...     max_combinations=50
        ... )
    """
    ranges: Dict[str, Dict[str, float]]
    rationale: str
    optimize_for: str = "sharpe_ratio"
    max_combinations: int = 100
    early_stop_threshold: Optional[float] = None


# --- 2.5. ParameterConstraint ---

@dataclass
class ParameterConstraint:
    """
    Contrainte inter-paramètres pour filtrer les combinaisons invalides.

    Types de contraintes:
    - 'greater_than': param_a > param_b
    - 'less_than': param_a < param_b
    - 'ratio_min': param_a / param_b >= ratio
    - 'ratio_max': param_a / param_b <= ratio
    - 'sum_max': param_a + param_b <= value
    - 'custom': fonction personnalisée

    Examples:
        # slow_period doit être > fast_period
        ParameterConstraint('slow_period', 'greater_than', 'fast_period')

        # slow doit être au moins 1.5x plus grand que fast
        ParameterConstraint(
            'slow_period', 'ratio_min', 'fast_period', ratio=1.5
        )

        # Écart minimum de 5 entre slow et fast
        ParameterConstraint(
            'slow_period', 'difference_min', 'fast_period', value=5
        )
    """
    param_a: str
    constraint_type: str
    param_b: Optional[str] = None
    value: Optional[float] = None
    ratio: Optional[float] = None
    description: str = ""

    def validate(self, params: Dict[str, Any]) -> bool:
        """
        Vérifie si la combinaison de paramètres respecte la contrainte.

        Args:
            params: Dictionnaire des paramètres

        Returns:
            True si la contrainte est respectée
        """
        val_a = params.get(self.param_a)
        if val_a is None:
            return True  # Paramètre absent, skip

        if self.constraint_type == 'greater_than':
            val_b = params.get(self.param_b)
            if val_b is None:
                return True
            return val_a > val_b

        elif self.constraint_type == 'greater_than_equal':
            val_b = params.get(self.param_b)
            if val_b is None:
                return True
            return val_a >= val_b

        elif self.constraint_type == 'less_than':
            val_b = params.get(self.param_b)
            if val_b is None:
                return True
            return val_a < val_b

        elif self.constraint_type == 'less_than_equal':
            val_b = params.get(self.param_b)
            if val_b is None:
                return True
            return val_a <= val_b

        elif self.constraint_type == 'ratio_min':
            val_b = params.get(self.param_b)
            if val_b is None or val_b == 0:
                return True
            return (val_a / val_b) >= (self.ratio or 1.0)

        elif self.constraint_type == 'ratio_max':
            val_b = params.get(self.param_b)
            if val_b is None or val_b == 0:
                return True
            return (val_a / val_b) <= (self.ratio or 1.0)

        elif self.constraint_type == 'difference_min':
            val_b = params.get(self.param_b)
            if val_b is None:
                return True
            return (val_a - val_b) >= (self.value or 0)

        elif self.constraint_type == 'difference_max':
            val_b = params.get(self.param_b)
            if val_b is None:
                return True
            return (val_a - val_b) <= (self.value or float('inf'))

        elif self.constraint_type == 'min_value':
            return val_a >= (self.value or 0)

        elif self.constraint_type == 'max_value':
            return val_a <= (self.value or float('inf'))

        elif self.constraint_type == 'sum_max':
            val_b = params.get(self.param_b)
            if val_b is None:
                return True
            return (val_a + val_b) <= (self.value or float('inf'))

        elif self.constraint_type == 'sum_min':
            val_b = params.get(self.param_b)
            if val_b is None:
                return True
            return (val_a + val_b) >= (self.value or 0)

        else:
            logger.warning(
                "Type de contrainte inconnu: %s",
                self.constraint_type,
            )
            return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "param_a": self.param_a,
            "constraint_type": self.constraint_type,
            "param_b": self.param_b,
            "value": self.value,
            "ratio": self.ratio,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParameterConstraint":
        return cls(
            param_a=data["param_a"],
            constraint_type=data["constraint_type"],
            param_b=data.get("param_b"),
            value=data.get("value"),
            ratio=data.get("ratio"),
            description=data.get("description", ""),
        )


# =============================================================================
# III. GÉNÉRATION D'ESPACES DE RECHERCHE
# =============================================================================

def parameter_values(
    min_val: float,
    max_val: float,
    granularity: float = 0.5,
    base_steps: int = 10,
    max_values: int = 4,
    param_type: str = "float"
) -> np.ndarray:
    """
    Génère les valeurs d'un paramètre selon la granularité.

    Cette fonction applique une logique de réduction intelligente:
    - Granularité 0% = maximum de valeurs (jusqu'à base_steps)
    - Granularité 100% = valeur médiane uniquement
    - Plafond de max_values valeurs pour éviter l'explosion combinatoire
    - Réduction dynamique si la plage est petite

    Args:
        min_val: Valeur minimale
        max_val: Valeur maximale
        granularity: Coefficient de granularité (0.0 à 1.0)
        base_steps: Nombre de pas de base (avant réduction)
        max_values: Nombre maximum de valeurs retournées
        param_type: Type de paramètre ('int', 'float')

    Returns:
        Array numpy des valeurs à tester

    Examples:
        >>> parameter_values(10, 50, granularity=0.0)  # Fin
        array([10., 20., 30., 40., 50.])

        >>> parameter_values(10, 50, granularity=1.0)  # Grossier
        array([30.])  # Juste la médiane
    """
    # Cas dégénéré
    if min_val >= max_val:
        return np.array([min_val])

    granularity = float(granularity)
    if granularity < 0.0:
        granularity = 0.0
    elif granularity > 1.0:
        granularity = 1.0

    range_size = max_val - min_val

    # Granularité maximale = juste la médiane
    if granularity >= 0.99:
        median = (min_val + max_val) / 2
        if param_type == "int":
            return np.array([int(round(median))])
        return np.array([median])

    # Calculer le nombre de valeurs selon la granularité.
    # Plus la granularité est élevée, plus on réduit agressivement.
    # Forme non-linéaire pour éviter une explosion combinatoire avec de nombreux paramètres.
    effective_steps = max(1, int(base_steps * (1 - granularity) ** 2))

    # Réduction dynamique pour petites plages
    # Si la plage est < 5% de la valeur moyenne, réduire encore
    avg_val = (min_val + max_val) / 2
    if avg_val > 0:
        relative_range = range_size / avg_val
        if relative_range < 0.05:
            effective_steps = max(1, effective_steps // 2)

    # Appliquer le plafond
    n_values = min(effective_steps + 1, max_values)

    # Générer les valeurs
    if n_values == 1:
        values = np.array([(min_val + max_val) / 2])
    else:
        values = np.linspace(min_val, max_val, n_values)

    # Convertir en entiers si nécessaire
    if param_type == "int":
        values = np.unique(np.round(values).astype(int))
        # S'assurer qu'on respecte encore le plafond après arrondis
        if len(values) > max_values:
            indices = np.linspace(0, len(values) - 1, max_values, dtype=int)
            values = values[indices]

    return values


def calculate_combinations(
    params_specs: Dict[str, ParameterSpec],
    granularity: float = 0.5,
    max_values_per_param: int = 4
) -> Tuple[int, Dict[str, np.ndarray]]:
    """
    Calcule le nombre total de combinaisons et les valeurs pour chaque
    paramètre.

    Args:
        params_specs: Dictionnaire des spécifications de paramètres
        granularity: Granularité globale
        max_values_per_param: Plafond par paramètre

    Returns:
        Tuple (nombre_total_combinaisons, dict_valeurs_par_param)
    """
    param_values_dict = {}
    total = 1

    for name, spec in params_specs.items():
        values = parameter_values(
            min_val=spec.min_val,
            max_val=spec.max_val,
            granularity=granularity,
            max_values=max_values_per_param,
            param_type=spec.param_type
        )
        param_values_dict[name] = values
        total *= len(values)

    return total, param_values_dict


def generate_param_grid(
    params_specs: Dict[str, ParameterSpec],
    granularity: float = 0.5,
    max_values_per_param: int = 4,
    max_total_combinations: int = 10000
) -> List[Dict[str, Any]]:
    """
    Génère une grille de combinaisons de paramètres.

    Args:
        params_specs: Spécifications des paramètres
        granularity: Granularité
        max_values_per_param: Plafond par paramètre
        max_total_combinations: Limite totale de combinaisons

    Returns:
        Liste de dictionnaires, chaque dict = une combinaison

    Raises:
        ValueError: Si le nombre de combinaisons dépasse la limite
    """
    total, param_values = calculate_combinations(
        params_specs, granularity, max_values_per_param
    )

    if total > max_total_combinations:
        raise ValueError(
            f"Trop de combinaisons ({total:,}). "
            f"Augmentez la granularité ou réduisez les paramètres. "
            f"Limite: {max_total_combinations:,}"
        )

    # Générer toutes les combinaisons via produit cartésien
    param_names = list(param_values.keys())
    param_arrays = [param_values[name] for name in param_names]

    combinations = []
    for combo in product(*param_arrays):
        combinations.append(dict(zip(param_names, combo)))

    return combinations


def compute_search_space_stats(
    param_space: Dict[str, Any],
    max_combinations: int = 100000,
    granularity: Optional[float] = None,
) -> SearchSpaceStats:
    """
    Calcule les statistiques d'un espace de recherche de manière unifiée.

    Cette fonction accepte plusieurs formats d'entrée:
    - Dict[str, ParameterSpec]: spécifications complètes
    - Dict[str, Tuple[min, max]]: bornes seulement (continu)
    - Dict[str, Tuple[min, max, step]]: bornes avec step (discret)
    - Dict[str, dict]: avec clés "min", "max", "step" (optionnel)

    Args:
        param_space: Dictionnaire décrivant l'espace des paramètres
        max_combinations: Seuil d'avertissement pour overflow
        granularity: Si fourni, utilise parameter_values() pour le calcul

    Returns:
        SearchSpaceStats avec toutes les statistiques

    Examples:
        >>> # Avec ParameterSpec
        >>> stats = compute_search_space_stats({"fast": spec1, "slow": spec2})

        >>> # Avec tuples (min, max, step)
        >>> stats = compute_search_space_stats({
        ...     "fast_period": (5, 20, 1),
        ...     "slow_period": (20, 50, 5),
        ... })

        >>> # Avec bornes seulement (retourne is_continuous=True)
        >>> stats = compute_search_space_stats({
        ...     "fast_period": (5, 20),
        ...     "slow_period": (20, 50),
        ... })
    """
    total = 1
    counts: Dict[str, int] = {}
    warnings: List[str] = []
    is_continuous = False

    for name, spec in param_space.items():
        count = _compute_param_count(spec, granularity)

        if count == -1:
            is_continuous = True
            counts[name] = -1
        else:
            counts[name] = count
            if count > 0:
                total *= count

    # Si continu, total n'a pas de sens
    if is_continuous:
        total = -1
        warnings.append(
            "Espace continu: nombre de combinaisons non défini (pas de step)"
        )

    # Vérifier overflow
    has_overflow = not is_continuous and total > max_combinations
    if has_overflow:
        warnings.append(f"Limite dépassée: {total:,} > {max_combinations:,}")

    return SearchSpaceStats(
        total_combinations=total,
        per_param_counts=counts,
        warnings=warnings,
        has_overflow=has_overflow,
        is_continuous=is_continuous,
    )


# --- 3.5. normalize_param_ranges ---

def _infer_step_decimals(step: float) -> int:
    step_str = f"{step:.12f}".rstrip("0").rstrip(".")
    if "." in step_str:
        return len(step_str.split(".")[1])
    return 0


def _build_param_values_from_range(
    min_v: float,
    max_v: float,
    step: float,
    is_int: bool,
) -> List[float]:
    if step is None or step <= 0 or max_v < min_v:
        return [float(min_v)]

    if is_int:
        step_int = max(1, int(round(step)))
        return list(range(int(min_v), int(max_v) + 1, step_int))

    step_dec = Decimal(str(step))
    min_dec = Decimal(str(min_v))
    max_dec = Decimal(str(max_v))
    if step_dec <= 0:
        return [float(min_v)]

    count = int(((max_dec - min_dec) / step_dec).to_integral_value(rounding=ROUND_FLOOR)) + 1
    decimals = _infer_step_decimals(step)
    quant = Decimal(1).scaleb(-decimals) if decimals > 0 else None

    values: List[float] = []
    for i in range(count):
        v = min_dec + step_dec * i
        if v > max_dec:
            break
        if quant is not None:
            v = v.quantize(quant)
        val = float(v)
        if not values or val != values[-1]:
            values.append(val)

    if not values:
        values = [float(min_v)]

    return values


def normalize_param_ranges(
    param_specs: Any,
    ranges: Dict[str, Dict[str, float]]
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """
    Normalise et valide des ranges de paramètres contre les ParameterSpec.

    - Clamp aux bornes des ParameterSpec
    - Vérifie min <= max, step > 0
    - Rejette clés inconnues
    - Recalcule count/values pour stats et exécution

    Args:
        param_specs: Liste ou dict de ParameterSpec
        ranges: Ranges demandées {param: {"min": x, "max": y, "step": z}}

    Returns:
        Tuple (normalized_ranges, warnings)

    Raises:
        ValueError: Si ranges invalides (param inconnu, min > max, etc.)

    Example:
        >>> specs = [
        ...     ParameterSpec("bb_period", min_val=10, max_val=50, default=20, step=1),
        ...     ParameterSpec("bb_std", min_val=1.0, max_val=3.0, default=2.0, step=0.1)
        ... ]
        >>> ranges = {
        ...     "bb_period": {"min": 20, "max": 25, "step": 1},
        ...     "bb_std": {"min": 2.0, "max": 2.5, "step": 0.1}
        ... }
        >>> normalized, warnings = normalize_param_ranges(specs, ranges)
        >>> normalized["bb_period"]["values"]
        [20, 21, 22, 23, 24, 25]
    """
    normalized: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []

    if isinstance(param_specs, dict):
        specs_dict = param_specs
    else:
        specs_dict = {spec.name: spec for spec in param_specs or []}

    for param_name, range_def in ranges.items():
        # Vérifier que le paramètre existe
        if param_name not in specs_dict:
            raise ValueError(
                f"Paramètre inconnu '{param_name}'. "
                f"Paramètres disponibles: {list(specs_dict.keys())}"
            )

        spec = specs_dict[param_name]

        # Extraire min/max/step
        if not isinstance(range_def, dict):
            raise ValueError(
                f"Paramètre '{param_name}': format invalide (attendu dict avec min/max/step)"
            )
        min_val = range_def.get("min")
        max_val = range_def.get("max")
        step = range_def.get("step")

        if min_val is None or max_val is None:
            raise ValueError(
                f"Paramètre '{param_name}': 'min' et 'max' sont obligatoires"
            )

        # Clamp aux bornes du ParameterSpec
        clamped_min = max(min_val, spec.min_val)
        clamped_max = min(max_val, spec.max_val)

        # Log si clamping appliqué
        if clamped_min != min_val or clamped_max != max_val:
            warnings.append(
                f"{param_name}: plage clampée "
                f"[{min_val}, {max_val}] → [{clamped_min}, {clamped_max}] "
                f"(limites: [{spec.min_val}, {spec.max_val}])"
            )

        # Vérifier cohérence min/max
        if clamped_min > clamped_max:
            raise ValueError(
                f"Paramètre '{param_name}': min ({clamped_min}) > max ({clamped_max}) "
                f"après clamping aux limites [{spec.min_val}, {spec.max_val}]"
            )

        # Utiliser step fourni ou step du spec
        if step is None or step <= 0:
            step = spec.step if spec.step is not None else (clamped_max - clamped_min) / 10
            if step is None or step <= 0:
                range_size = float(clamped_max) - float(clamped_min)
                if spec.param_type == "int":
                    step = max(1, int(range_size / 10)) if range_size > 0 else 1
                else:
                    step = range_size / 10 if range_size > 0 else 0.1

        if step <= 0:
            raise ValueError(
                f"Paramètre '{param_name}': step doit être > 0 (reçu: {step})"
            )

        is_int = spec.param_type == "int" or spec.param_type is int
        if is_int:
            clamped_min = int(round(clamped_min))
            clamped_max = int(round(clamped_max))
            step = max(1, int(round(step)))

        values = _build_param_values_from_range(
            clamped_min,
            clamped_max,
            step,
            is_int=is_int,
        )

        if not values:
            raise ValueError(
                f"Paramètre '{param_name}': aucune valeur générée "
                f"(min={clamped_min}, max={clamped_max}, step={step})"
            )

        normalized[param_name] = {
            "min": clamped_min,
            "max": clamped_max,
            "step": step,
            "count": len(values),
            "values": values,
        }

    logger.info(
        "Ranges normalisées: %s paramètres, %s valeurs totales",
        len(normalized),
        sum(len(r.get("values", [])) for r in normalized.values()),
    )

    return normalized, warnings


def normalize_param_grid_values(
    param_specs: Any,
    param_grid: Dict[str, Any],
) -> Tuple[Dict[str, List[Any]], List[str]]:
    """
    Normalise une grille explicite de valeurs par paramètre.

    - Convertit en liste si scalaire
    - Filtre les valeurs hors bornes des ParameterSpec
    - Rejette clés inconnues

    Returns:
        Tuple (normalized_param_grid, warnings)
    """
    if isinstance(param_specs, dict):
        specs_dict = param_specs
    else:
        specs_dict = {spec.name: spec for spec in param_specs or []}

    normalized: Dict[str, List[Any]] = {}
    warnings: List[str] = []

    for param_name, values in param_grid.items():
        if param_name not in specs_dict:
            raise ValueError(
                f"Paramètre inconnu '{param_name}'. "
                f"Paramètres disponibles: {list(specs_dict.keys())}"
            )

        spec = specs_dict[param_name]
        if isinstance(values, (list, tuple, np.ndarray)):
            values_list = list(values)
        else:
            values_list = [values]

        filtered: List[Any] = []
        removed = 0
        is_int = spec.param_type == "int" or spec.param_type is int

        for value in values_list:
            try:
                v = int(value) if is_int else float(value)
            except (TypeError, ValueError):
                removed += 1
                continue

            if v < spec.min_val or v > spec.max_val:
                removed += 1
                continue

            filtered.append(v)

        if removed:
            warnings.append(
                f"{param_name}: {removed} valeur(s) hors bornes supprimées "
                f"(limites: [{spec.min_val}, {spec.max_val}])"
            )

        if not filtered:
            raise ValueError(
                f"Paramètre '{param_name}': aucune valeur valide après filtrage "
                f"(limites: [{spec.min_val}, {spec.max_val}])"
            )

        normalized[param_name] = filtered

    return normalized, warnings


# =============================================================================
# IV. SYSTÈME DE CONTRAINTES
# =============================================================================

class ConstraintValidator:
    """
    Validateur de contraintes pour filtrer les combinaisons de paramètres.

    Usage:
        validator = ConstraintValidator()
        validator.add_constraint(
            ParameterConstraint('slow', 'greater_than', 'fast')
        )

        # Filtrer une grille
        valid_combos = validator.filter_grid(param_grid)

        # Vérifier une combinaison
        is_valid = validator.validate({'slow': 26, 'fast': 12})
    """

    def __init__(
        self, constraints: Optional[List[ParameterConstraint]] = None
    ):
        self.constraints: List[ParameterConstraint] = constraints or []

    def add_constraint(self, constraint: ParameterConstraint) -> None:
        """Ajoute une contrainte."""
        self.constraints.append(constraint)
        logger.debug(
            "Contrainte ajoutée: %s %s",
            constraint.param_a,
            constraint.constraint_type,
        )

    def add_greater_than(
        self, param_a: str, param_b: str, description: str = ""
    ) -> None:
        """Raccourci pour ajouter une contrainte param_a > param_b."""
        self.add_constraint(ParameterConstraint(
            param_a=param_a,
            constraint_type='greater_than',
            param_b=param_b,
            description=description or f"{param_a} doit être > {param_b}"
        ))

    def add_ratio_min(
        self,
        param_a: str,
        param_b: str,
        ratio: float,
        description: str = "",
    ) -> None:
        """Raccourci pour ajouter une contrainte param_a / param_b >= ratio."""
        self.add_constraint(ParameterConstraint(
            param_a=param_a,
            constraint_type='ratio_min',
            param_b=param_b,
            ratio=ratio,
            description=description
            or f"{param_a} / {param_b} doit être >= {ratio}"
        ))

    def add_difference_min(
        self,
        param_a: str,
        param_b: str,
        diff: float,
        description: str = "",
    ) -> None:
        """Raccourci pour ajouter une contrainte param_a - param_b >= diff."""
        self.add_constraint(ParameterConstraint(
            param_a=param_a,
            constraint_type='difference_min',
            param_b=param_b,
            value=diff,
            description=description
            or f"{param_a} - {param_b} doit être >= {diff}"
        ))

    def validate(self, params: Dict[str, Any]) -> bool:
        """
        Vérifie si une combinaison de paramètres respecte toutes les
        contraintes.

        Args:
            params: Dictionnaire des paramètres

        Returns:
            True si toutes les contraintes sont respectées
        """
        return all(c.validate(params) for c in self.constraints)

    def filter_grid(
        self,
        param_grid: List[Dict[str, Any]],
        log_filtered: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Filtre une grille de paramètres selon les contraintes.

        Args:
            param_grid: Liste de combinaisons de paramètres
            log_filtered: Si True, log les combinaisons filtrées

        Returns:
            Liste des combinaisons valides
        """
        if not self.constraints:
            return param_grid

        valid = []
        filtered_count = 0

        for params in param_grid:
            if self.validate(params):
                valid.append(params)
            else:
                filtered_count += 1
                if log_filtered:
                    logger.debug("Combinaison filtrée: %s", params)

        if filtered_count > 0:
            logger.info(
                "Contraintes: %s/%s combinaisons filtrées (%s valides)",
                filtered_count,
                len(param_grid),
                len(valid),
            )

        return valid

    def get_violations(self, params: Dict[str, Any]) -> List[str]:
        """
        Retourne la liste des contraintes violées.

        Args:
            params: Dictionnaire des paramètres

        Returns:
            Liste des descriptions des contraintes violées
        """
        violations = []
        for constraint in self.constraints:
            if not constraint.validate(params):
                desc = constraint.description or (
                    f"{constraint.param_a} {constraint.constraint_type} "
                    f"{constraint.param_b or constraint.value}"
                )
                violations.append(desc)
        return violations

    def to_dict(self) -> List[Dict[str, Any]]:
        return [c.to_dict() for c in self.constraints]

    @classmethod
    def from_dict(cls, data: List[Dict[str, Any]]) -> "ConstraintValidator":
        constraints = [ParameterConstraint.from_dict(c) for c in data]
        return cls(constraints=constraints)


# Contraintes prédéfinies courantes
COMMON_CONSTRAINTS = {
    "ema_cross": ConstraintValidator([
        ParameterConstraint(
            param_a="slow_period",
            constraint_type="greater_than",
            param_b="fast_period",
            description="La période lente doit être > période rapide"
        ),
        ParameterConstraint(
            param_a="slow_period",
            constraint_type="ratio_min",
            param_b="fast_period",
            ratio=1.5,
            description="La période lente doit être au moins 1.5x la rapide"
        ),
    ]),
    "bollinger": ConstraintValidator([
        ParameterConstraint(
            param_a="bb_std",
            constraint_type="min_value",
            value=1.0,
            description="L'écart-type doit être >= 1.0"
        ),
    ]),
    "atr_stop": ConstraintValidator([
        ParameterConstraint(
            param_a="k_sl",
            constraint_type="min_value",
            value=0.5,
            description="Le multiplicateur SL doit être >= 0.5"
        ),
        ParameterConstraint(
            param_a="k_sl",
            constraint_type="max_value",
            value=5.0,
            description="Le multiplicateur SL doit être <= 5.0"
        ),
    ]),
}


def get_common_constraints(strategy_type: str) -> ConstraintValidator:
    """Récupère les contraintes prédéfinies pour un type de stratégie."""
    return COMMON_CONSTRAINTS.get(strategy_type, ConstraintValidator())


def generate_constrained_param_grid(
    params_specs: Dict[str, ParameterSpec],
    constraints: Optional[ConstraintValidator] = None,
    granularity: float = 0.5,
    max_values_per_param: int = 4,
    max_total_combinations: int = 10000
) -> List[Dict[str, Any]]:
    """
    Génère une grille de paramètres avec filtrage par contraintes.

    Args:
        params_specs: Spécifications des paramètres
        constraints: Validateur de contraintes (optionnel)
        granularity: Granularité
        max_values_per_param: Plafond par paramètre
        max_total_combinations: Limite totale de combinaisons

    Returns:
        Liste de combinaisons valides
    """
    # Générer la grille brute
    grid = generate_param_grid(
        params_specs=params_specs,
        granularity=granularity,
        max_values_per_param=max_values_per_param,
        max_total_combinations=max_total_combinations
    )

    # Appliquer les contraintes si présentes
    if constraints:
        grid = constraints.filter_grid(grid)

    return grid


# =============================================================================
# V. PRESETS SIMPLES (IN-MEMORY)
# =============================================================================

# --- 5.1. Définitions des presets ---

SAFE_RANGES_PRESET = Preset(
    name="Safe Ranges",
    description="Configuration conservative avec 4 indicateurs de base. "
                "~750 combinaisons pour une optimisation rapide.",
    parameters={
        # Bollinger Bands
        "bb_period": ParameterSpec(
            name="bb_period",
            min_val=10,
            max_val=50,
            default=20,
            param_type="int",
            description="Période des Bandes de Bollinger"
        ),
        "bb_std": ParameterSpec(
            name="bb_std",
            min_val=1.5,
            max_val=3.0,
            default=2.0,
            param_type="float",
            description="Nombre d'écarts-types pour les bandes"
        ),
        # ATR
        "atr_period": ParameterSpec(
            name="atr_period",
            min_val=7,
            max_val=21,
            default=14,
            param_type="int",
            description="Période de l'ATR"
        ),
        # Stop Loss
        "k_sl": ParameterSpec(
            name="k_sl",
            min_val=1.0,
            max_val=3.0,
            default=1.5,
            param_type="float",
            description="Multiplicateur ATR pour stop-loss"
        ),
        # Leverage (non optimisé, fixé à 1)
        "leverage": ParameterSpec(
            name="leverage",
            min_val=1,
            max_val=1,
            default=1,
            param_type="int",
            description="Levier de trading (fixé à 1)",
            optimize=False,
        ),
    },
    indicators=["bollinger", "atr"],
    default_granularity=0.5
)


MINIMAL_PRESET = Preset(
    name="Minimal",
    description="Configuration minimale pour tests rapides. "
                "Paramètres par défaut, pas d'optimisation.",
    parameters={
        "bb_period": ParameterSpec("bb_period", 20, 20, 20, param_type="int"),
        "bb_std": ParameterSpec("bb_std", 2.0, 2.0, 2.0),
        "atr_period": ParameterSpec(
            "atr_period", 14, 14, 14, param_type="int"
        ),
        "k_sl": ParameterSpec("k_sl", 1.5, 1.5, 1.5),
        "leverage": ParameterSpec("leverage", 1, 1, 1, param_type="int", optimize=False),
    },
    indicators=["bollinger", "atr"],
    default_granularity=1.0
)


EMA_CROSS_PRESET = Preset(
    name="EMA Cross",
    description="Configuration pour stratégie de croisement EMA.",
    parameters={
        "fast_period": ParameterSpec(
            name="fast_period",
            min_val=5,
            max_val=20,
            default=12,
            param_type="int",
            description="Période EMA rapide"
        ),
        "slow_period": ParameterSpec(
            name="slow_period",
            min_val=20,
            max_val=50,
            default=26,
            param_type="int",
            description="Période EMA lente"
        ),
        "k_sl": ParameterSpec(
            name="k_sl",
            min_val=1.0,
            max_val=3.0,
            default=2.0,
            param_type="float",
            description="Multiplicateur pour stop-loss %"
        ),
        "leverage": ParameterSpec(
            name="leverage",
            min_val=1,
            max_val=1,
            default=1,
            param_type="int",
            description="Levier de trading (fixé à 1)",
            optimize=False,
        ),
    },
    indicators=[],  # EMA calculée internement par la stratégie
    default_granularity=0.5
)


MACD_CROSS_PRESET = Preset(
    name="MACD Cross",
    description="Configuration pour stratégie MACD Crossover. "
                "~256 combinaisons.",
    parameters={
        "fast_period": ParameterSpec(
            name="fast_period",
            min_val=8,
            max_val=20,
            default=12,
            param_type="int",
            description="Période EMA rapide MACD"
        ),
        "slow_period": ParameterSpec(
            name="slow_period",
            min_val=20,
            max_val=35,
            default=26,
            param_type="int",
            description="Période EMA lente MACD"
        ),
        "signal_period": ParameterSpec(
            name="signal_period",
            min_val=5,
            max_val=15,
            default=9,
            param_type="int",
            description="Période ligne signal"
        ),
        "leverage": ParameterSpec(
            name="leverage",
            min_val=1,
            max_val=1,
            default=1,
            param_type="int",
            description="Levier de trading (fixé à 1)",
            optimize=False,
        ),
    },
    indicators=["macd"],
    default_granularity=0.5
)


RSI_REVERSAL_PRESET = Preset(
    name="RSI Reversal",
    description="Configuration pour stratégie RSI mean-reversion. "
                "~256 combinaisons.",
    parameters={
        "rsi_period": ParameterSpec(
            name="rsi_period",
            min_val=7,
            max_val=21,
            default=14,
            param_type="int",
            description="Période RSI"
        ),
        "oversold_level": ParameterSpec(
            name="oversold_level",
            min_val=20,
            max_val=40,
            default=30,
            param_type="int",
            description="Seuil survente"
        ),
        "overbought_level": ParameterSpec(
            name="overbought_level",
            min_val=60,
            max_val=80,
            default=70,
            param_type="int",
            description="Seuil surachat"
        ),
        "leverage": ParameterSpec(
            name="leverage",
            min_val=1,
            max_val=1,
            default=1,
            param_type="int",
            description="Levier de trading (fixé à 1)",
            optimize=False,
        ),
    },
    indicators=["rsi"],
    default_granularity=0.5
)


ATR_CHANNEL_PRESET = Preset(
    name="ATR Channel",
    description="Configuration pour stratégie ATR Channel breakout. "
                "~256 combinaisons.",
    parameters={
        "atr_period": ParameterSpec(
            name="atr_period",
            min_val=7,
            max_val=21,
            default=14,
            param_type="int",
            description="Période ATR et EMA"
        ),
        "atr_mult": ParameterSpec(
            name="atr_mult",
            min_val=1.0,
            max_val=4.0,
            default=2.0,
            param_type="float",
            description="Multiplicateur ATR pour canal"
        ),
        "leverage": ParameterSpec(
            name="leverage",
            min_val=1,
            max_val=1,
            default=1,
            param_type="int",
            description="Levier de trading (fixé à 1)",
            optimize=False,
        ),
    },
    indicators=["atr", "ema"],
    default_granularity=0.5
)


BOLLINGER_ATR_PRESET = Preset(
    name="Bollinger ATR",
    description="Configuration pour stratégie Bollinger + filtre ATR. ~128-2000 combinaisons selon granularité.",
    parameters={
        "bb_period": ParameterSpec(
            name="bb_period",
            min_val=10,
            max_val=40,
            default=20,
            param_type="int",
            description="Période des bandes de Bollinger",
        ),
        "bb_std": ParameterSpec(
            name="bb_std",
            min_val=1.5,
            max_val=3.0,
            default=2.0,
            param_type="float",
            description="Écart-type des bandes",
        ),
        "entry_z": ParameterSpec(
            name="entry_z",
            min_val=1.0,
            max_val=3.0,
            default=2.0,
            param_type="float",
            description="Seuil Z-score d'entrée",
        ),
        "atr_period": ParameterSpec(
            name="atr_period",
            min_val=7,
            max_val=21,
            default=14,
            param_type="int",
            description="Période ATR",
        ),
        "atr_percentile": ParameterSpec(
            name="atr_percentile",
            min_val=10,
            max_val=60,
            default=30,
            param_type="int",
            description="Percentile de filtre volatilité (ATR)",
        ),
        "k_sl": ParameterSpec(
            name="k_sl",
            min_val=0.5,
            max_val=3.0,
            default=1.5,
            param_type="float",
            description="Multiplicateur stop-loss (ATR)",
        ),
        "leverage": ParameterSpec(
            name="leverage",
            min_val=1,
            max_val=1,
            default=1,
            param_type="int",
            description="Levier de trading (fixé à 1)",
            optimize=False,
        ),
    },
    indicators=["bollinger", "atr"],
    default_granularity=0.7,
)


# --- 5.2. Registre PRESETS ---

PRESETS: Dict[str, Preset] = {
    "safe_ranges": SAFE_RANGES_PRESET,
    "minimal": MINIMAL_PRESET,
    "bollinger_atr": BOLLINGER_ATR_PRESET,
    "ema_cross": EMA_CROSS_PRESET,
    "macd_cross": MACD_CROSS_PRESET,
    "rsi_reversal": RSI_REVERSAL_PRESET,
    "atr_channel": ATR_CHANNEL_PRESET,
}


# --- 5.3. Fonctions d'accès ---

def get_preset(name: str) -> Preset:
    """Récupère un preset par son nom."""
    if name not in PRESETS:
        available = ", ".join(PRESETS.keys())
        raise ValueError(
            f"Preset '{name}' non trouvé. Disponibles: {available}"
        )
    return PRESETS[name]


def list_presets() -> List[str]:
    """Liste les presets disponibles."""
    return list(PRESETS.keys())


# =============================================================================
# VI. PRESETS I/O (DISQUE)
# =============================================================================

def save_preset(preset: Preset, filepath: Path) -> None:
    """Sauvegarde un preset en JSON."""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(preset.to_dict(), f, indent=2, ensure_ascii=False)


def load_preset(filepath: Path) -> Preset:
    """Charge un preset depuis un fichier JSON."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Preset.from_dict(data)


# =============================================================================
# VII. PRESETS VERSIONNÉS (SYSTÈME AVANCÉ)
# =============================================================================

# --- 7.1. Configuration et gestion du répertoire ---

def get_versioned_presets_dir() -> Path:
    """Return directory for versioned presets."""
    env_value = os.getenv(VERSIONED_PRESETS_DIR_ENV)
    if env_value:
        return Path(env_value)
    repo_root = _get_repo_root()
    target = repo_root / "data" / "presets"
    _migrate_legacy_presets(target)
    return target


# --- 7.2. Sauvegarde et chargement ---

def save_versioned_preset(
    strategy_name: str,
    version: str,
    preset_name: str,
    params_values: Dict[str, Any],
    indicators: Optional[List[str]] = None,
    description: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    *,
    origin: Optional[str] = None,
    origin_run_id: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Preset:
    """
    Save a versioned preset to disk and return it.

    Naming convention:
        <strategy>@<version>__<preset_slug>
    """
    preset_name = (preset_name or "winner").strip() or "winner"
    version = (version or DEFAULT_STRATEGY_VERSION).strip()
    if not version:
        version = DEFAULT_STRATEGY_VERSION
    strategy_slug = _normalize_slug(strategy_name)
    preset_slug = _normalize_slug(preset_name)
    preset_id = f"{strategy_slug}@{version}__{preset_slug}"

    if indicators is None:
        from utils.preset_validation import auto_fill_indicators_from_strategy
        indicators = auto_fill_indicators_from_strategy(strategy_name)

    params_values = params_values or {}
    param_specs = _build_fixed_parameter_specs(params_values)
    created_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    metadata: Dict[str, Any] = {
        "strategy": strategy_name,
        "strategy_slug": strategy_slug,
        "version": version,
        "preset_name": preset_name,
        "preset_slug": preset_slug,
        "origin": origin or "manual",
        "created_at": created_at,
        "params_values": _to_builtin(params_values),
    }
    if metrics:
        metadata["metrics"] = _to_builtin(metrics)
    if origin_run_id:
        metadata["origin_run_id"] = origin_run_id
    if extra_metadata:
        metadata.update(_to_builtin(extra_metadata))

    preset = Preset(
        name=preset_id,
        description=description or f"Versioned preset for {strategy_name}",
        parameters=param_specs,
        indicators=indicators or [],
        default_granularity=0.5,
        metadata=metadata,
    )

    presets_dir = get_versioned_presets_dir()
    presets_dir.mkdir(parents=True, exist_ok=True)
    filepath = presets_dir / f"{preset_id}.json"
    if filepath.exists():
        logger.warning("Overwriting preset file: %s", filepath)
    save_preset(preset, filepath)
    return preset


def load_strategy_version(
    strategy_name: str,
    version: Optional[str] = None,
    preset_name: Optional[str] = None,
) -> Preset:
    """
    Load a versioned preset for a strategy, validated against indicators.
    """
    presets = list_strategy_versions(strategy_name)
    if not presets:
        raise ValueError(
            f"No versioned presets found for strategy '{strategy_name}'"
        )

    if version is None:
        version = resolve_latest_version(strategy_name)
    version = version.strip()

    filtered = [
        p for p in presets
        if (p.metadata or {}).get("version") == version
    ]

    if preset_name:
        preset_slug = _normalize_slug(preset_name)
        filtered = [
            p for p in filtered
            if (
                (p.metadata or {}).get("preset_slug") == preset_slug
                or (p.metadata or {}).get("preset_name") == preset_name
                or p.name == preset_name
            )
        ]

    if not filtered:
        raise ValueError(
            "No matching versioned preset for strategy "
            f"'{strategy_name}' version='{version}'"
        )

    filtered.sort(key=_preset_sort_key, reverse=True)
    preset = filtered[0]
    return validate_before_use(preset, strategy_name)


# --- 7.3. Listage et résolution ---

def list_strategy_versions(strategy_name: str) -> List[Preset]:
    """List versioned presets for a strategy."""
    presets_dir = get_versioned_presets_dir()
    if not presets_dir.exists():
        return []

    strategy_slug = _normalize_slug(strategy_name)
    presets: List[Preset] = []

    for path in presets_dir.glob("*.json"):
        parsed = _parse_versioned_id(path.stem)
        if not parsed or parsed["strategy"] != strategy_slug:
            continue
        try:
            preset = load_preset(path)
        except Exception as exc:
            logger.warning("Failed to load preset %s: %s", path, exc)
            continue
        _apply_versioned_defaults(preset, strategy_name, parsed, path)
        presets.append(preset)

    presets.sort(key=_preset_sort_key, reverse=True)
    return presets


def resolve_latest_version(strategy_name: str) -> str:
    """Resolve latest version for a strategy or fallback default."""
    presets = list_strategy_versions(strategy_name)
    if not presets:
        return DEFAULT_STRATEGY_VERSION
    versions = [
        (preset.metadata or {}).get("version", "")
        for preset in presets
    ]
    versions = [v for v in versions if v]
    if not versions:
        return DEFAULT_STRATEGY_VERSION
    versions.sort(key=_semver_key, reverse=True)
    return versions[0]


# --- 7.4. Validation ---

def validate_before_use(preset: Preset, strategy_name: str) -> Preset:
    """Validate preset against strategy indicators before use."""
    from utils.preset_validation import validate_preset_against_strategy

    result = validate_preset_against_strategy(preset, strategy_name)
    if not result.is_valid:
        details = "; ".join(result.errors + result.warnings)
        raise ValueError(
            f"Preset validation failed for '{strategy_name}': {details}"
        )
    return preset


# =============================================================================
# VIII. EXPORTS
# =============================================================================

__all__ = [
    # Types
    "ParameterSpec",
    "ParameterConstraint",
    "ConstraintValidator",
    "Preset",
    "SearchSpaceStats",
    "RangeProposal",
    # Search space generation
    "parameter_values",
    "calculate_combinations",
    "compute_search_space_stats",
    "normalize_param_ranges",
    "normalize_param_grid_values",
    "generate_param_grid",
    "generate_constrained_param_grid",
    # Presets simple
    "get_preset",
    "list_presets",
    "save_preset",
    "load_preset",
    # Presets versionnés
    "get_versioned_presets_dir",
    "save_versioned_preset",
    "list_strategy_versions",
    "load_strategy_version",
    "resolve_latest_version",
    "validate_before_use",
    "DEFAULT_STRATEGY_VERSION",
    # Contraintes
    "get_common_constraints",
    "COMMON_CONSTRAINTS",
    # Presets prédéfinis
    "SAFE_RANGES_PRESET",
    "MINIMAL_PRESET",
    "EMA_CROSS_PRESET",
    "MACD_CROSS_PRESET",
    "RSI_REVERSAL_PRESET",
    "ATR_CHANNEL_PRESET",
    "PRESETS",
]

