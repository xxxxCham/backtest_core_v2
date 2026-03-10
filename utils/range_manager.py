"""
Module-ID: utils.range_manager

Purpose: Gestion centralisée des plages min/max pour tous les indicateurs et stratégies.

Role in pipeline: configuration

Key components: RangeManager, load_indicator_ranges, save_indicator_ranges, apply_ranges_to_strategy

Inputs: config/indicator_ranges.toml, strategy parameter_specs

Outputs: Plages personnalisées appliquées aux stratégies

Dependencies: toml, pathlib, typing

Conventions: Toutes les modifications passent par ce module pour garantir la cohérence.

Read-if: Modification des plages de paramètres, ajout de nouvelles stratégies/indicateurs.

Skip-if: Utilisation simple des plages existantes.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import tomli
import tomli_w

from utils.parameters import ParameterSpec


@dataclass
class RangeConfig:
    """Configuration d'une plage de paramètre."""
    min: float
    max: float
    step: float
    default: Any
    description: str
    options: Optional[List[str]] = None
    param_type: Optional[str] = None


class RangeManager:
    """
    Gestionnaire centralisé des plages de paramètres.

    Permet de:
    - Charger les plages depuis indicator_ranges.toml
    - Modifier les plages dynamiquement
    - Sauvegarder les modifications
    - Appliquer les plages aux stratégies
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialise le gestionnaire.

        Args:
            config_path: Chemin vers indicator_ranges.toml
        """
        if config_path is None:
            # Chemin par défaut
            repo_root = Path(__file__).parent.parent
            config_path = repo_root / "config" / "indicator_ranges.toml"

        self.config_path = Path(config_path)
        self.ranges: Dict[str, Dict[str, RangeConfig]] = {}
        self._load_ranges()

    def _load_ranges(self) -> None:
        """Charge les plages depuis le fichier TOML."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Fichier de configuration non trouvé: {self.config_path}")

        with open(self.config_path, "rb") as f:
            data = tomli.load(f)

        # Convertir les données en RangeConfig
        for category_param, values in data.items():
            if "." in category_param:
                category, param = category_param.rsplit(".", 1)
            else:
                category = "global"
                param = category_param

            if category not in self.ranges:
                self.ranges[category] = {}

            self.ranges[category][param] = RangeConfig(
                min=values.get("min"),
                max=values.get("max"),
                step=values.get("step", 1),
                default=values.get("default"),
                description=values.get("description", ""),
                options=values.get("options"),
                param_type=values.get("type")
            )

    def get_range(self, category: str, param: str) -> Optional[RangeConfig]:
        """
        Récupère la configuration d'une plage.

        Args:
            category: Catégorie (ex: "ema", "rsi", "bollinger")
            param: Nom du paramètre (ex: "period", "std_dev")

        Returns:
            RangeConfig ou None si non trouvé
        """
        return self.ranges.get(category, {}).get(param)

    def update_range(self, category: str, param: str,
                    min_val: Optional[float] = None,
                    max_val: Optional[float] = None,
                    step: Optional[float] = None,
                    default: Optional[Any] = None) -> None:
        """
        Met à jour une plage existante.

        Args:
            category: Catégorie de l'indicateur/stratégie
            param: Nom du paramètre
            min_val: Nouvelle valeur minimale (optionnel)
            max_val: Nouvelle valeur maximale (optionnel)
            step: Nouveau pas (optionnel)
            default: Nouvelle valeur par défaut (optionnel)
        """
        if category not in self.ranges:
            raise ValueError(f"Catégorie inconnue: {category}")

        if param not in self.ranges[category]:
            raise ValueError(f"Paramètre inconnu: {category}.{param}")

        range_cfg = self.ranges[category][param]

        if min_val is not None:
            range_cfg.min = min_val
        if max_val is not None:
            range_cfg.max = max_val
        if step is not None:
            range_cfg.step = step
        if default is not None:
            range_cfg.default = default

    def add_range(self, category: str, param: str, range_config: RangeConfig) -> None:
        """
        Ajoute une nouvelle plage.

        Args:
            category: Catégorie de l'indicateur/stratégie
            param: Nom du paramètre
            range_config: Configuration de la plage
        """
        if category not in self.ranges:
            self.ranges[category] = {}

        self.ranges[category][param] = range_config

    def save_ranges(self, backup: bool = True) -> None:
        """
        Sauvegarde les plages modifiées dans le fichier TOML.

        Args:
            backup: Créer une sauvegarde avant modification
        """
        if backup and self.config_path.exists():
            backup_path = self.config_path.with_suffix(".toml.bak")
            import shutil
            shutil.copy2(self.config_path, backup_path)

        # Convertir les RangeConfig en dict pour TOML
        data = {}
        for category, params in sorted(self.ranges.items()):
            for param, range_cfg in sorted(params.items()):
                key = f"{category}.{param}"
                data[key] = {
                    "min": range_cfg.min,
                    "max": range_cfg.max,
                    "step": range_cfg.step,
                    "default": range_cfg.default,
                    "description": range_cfg.description
                }
                if range_cfg.options:
                    data[key]["options"] = range_cfg.options
                if range_cfg.param_type:
                    data[key]["type"] = range_cfg.param_type

        with open(self.config_path, "wb") as f:
            tomli_w.dump(data, f)

    def apply_to_parameter_spec(self, spec: ParameterSpec,
                                category: str, param: str) -> ParameterSpec:
        """
        Applique une plage à un ParameterSpec existant.

        Args:
            spec: ParameterSpec original
            category: Catégorie de recherche
            param: Nom du paramètre

        Returns:
            Nouveau ParameterSpec avec plages appliquées
        """
        range_cfg = self.get_range(category, param)

        if range_cfg is None:
            return spec  # Pas de plage définie, retourner l'original

        # Créer un nouveau ParameterSpec avec les plages mises à jour
        return ParameterSpec(
            name=spec.name,
            min_val=range_cfg.min if range_cfg.min is not None else spec.min_val,
            max_val=range_cfg.max if range_cfg.max is not None else spec.max_val,
            default=range_cfg.default if range_cfg.default is not None else spec.default,
            step=range_cfg.step if range_cfg.step is not None else spec.step,
            param_type=spec.param_type,
            description=range_cfg.description or spec.description,
            optimize=spec.optimize,
            options=range_cfg.options or spec.options
        )

    def get_all_categories(self) -> List[str]:
        """Retourne toutes les catégories disponibles."""
        return sorted(self.ranges.keys())

    def get_category_params(self, category: str) -> List[str]:
        """
        Retourne tous les paramètres d'une catégorie.

        Args:
            category: Nom de la catégorie

        Returns:
            Liste des noms de paramètres
        """
        return sorted(self.ranges.get(category, {}).keys())

    def get_all_ranges(self) -> Dict[str, Dict[str, RangeConfig]]:
        """Retourne toutes les plages chargées."""
        return self.ranges

    def export_to_dict(self) -> Dict[str, Any]:
        """
        Exporte toutes les plages en dictionnaire.

        Returns:
            Dictionnaire hiérarchique {category: {param: {...}}}
        """
        result = {}
        for category, params in self.ranges.items():
            result[category] = {}
            for param, range_cfg in params.items():
                result[category][param] = {
                    "min": range_cfg.min,
                    "max": range_cfg.max,
                    "step": range_cfg.step,
                    "default": range_cfg.default,
                    "description": range_cfg.description
                }
                if range_cfg.options:
                    result[category][param]["options"] = range_cfg.options
                if range_cfg.param_type:
                    result[category][param]["type"] = range_cfg.param_type
        return result


# Fonctions utilitaires globales

def load_indicator_ranges(config_path: Optional[Path] = None) -> RangeManager:
    """
    Charge le gestionnaire de plages.

    Args:
        config_path: Chemin vers indicator_ranges.toml (optionnel)

    Returns:
        Instance de RangeManager
    """
    return RangeManager(config_path)


def apply_ranges_to_strategy(strategy_name: str,
                             parameter_specs: Dict[str, ParameterSpec],
                             range_manager: Optional[RangeManager] = None) -> Dict[str, ParameterSpec]:
    """
    Applique les plages du fichier de configuration aux parameter_specs d'une stratégie.

    Args:
        strategy_name: Nom de la stratégie (ex: "ema_cross", "rsi_reversal")
        parameter_specs: Dict des ParameterSpec originaux
        range_manager: Instance de RangeManager (créée automatiquement si None)

    Returns:
        Nouveau dict de ParameterSpec avec plages appliquées
    """
    if range_manager is None:
        range_manager = load_indicator_ranges()

    updated_specs = {}

    for param_name, spec in parameter_specs.items():
        # Essayer d'abord avec le nom de la stratégie
        updated_spec = range_manager.apply_to_parameter_spec(
            spec, strategy_name, param_name
        )

        # Si pas trouvé, essayer avec le nom du paramètre comme catégorie
        # (ex: "rsi" pour rsi_period)
        if updated_spec == spec:
            # Extraire la catégorie du nom (rsi_period -> rsi)
            category = param_name.split("_")[0]
            updated_spec = range_manager.apply_to_parameter_spec(
                spec, category, param_name.replace(f"{category}_", "")
            )

        updated_specs[param_name] = updated_spec

    return updated_specs


def get_strategy_ranges(strategy_name: str,
                       range_manager: Optional[RangeManager] = None) -> Dict[str, RangeConfig]:
    """
    Récupère toutes les plages définies pour une stratégie.

    Args:
        strategy_name: Nom de la stratégie
        range_manager: Instance de RangeManager (créée automatiquement si None)

    Returns:
        Dict {param_name: RangeConfig}
    """
    if range_manager is None:
        range_manager = load_indicator_ranges()

    return range_manager.ranges.get(strategy_name, {})


# Singleton global (lazy loading)
_global_range_manager: Optional[RangeManager] = None


def get_global_range_manager() -> RangeManager:
    """Retourne l'instance globale de RangeManager (singleton)."""
    global _global_range_manager
    if _global_range_manager is None:
        _global_range_manager = load_indicator_ranges()
    return _global_range_manager
