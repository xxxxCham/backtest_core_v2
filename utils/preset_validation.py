"""
Module-ID: utils.preset_validation

Purpose: Valide/remplit presets (cohérence indicateurs et params vs stratégies).

Role in pipeline: configuration

Key components: PresetValidationResult, validate_preset(), auto_fill_indicators_from_strategy()

Inputs: Preset dict, strategy name, expected indicators

Outputs: ValidationResult {is_valid, errors[], warnings[], summary()}

Dependencies: dataclasses, typing, log

Conventions: Auto-fill indicateurs depuis mapping; erreurs = breaks validité; warnings = info.

Read-if: Modification validation ou preset auto-fill.

Skip-if: Vous appelez juste validate_preset(preset_name).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

from utils.log import get_logger

if TYPE_CHECKING:
    from utils.parameters import Preset

logger = get_logger(__name__)


@dataclass
class PresetValidationResult:
    """Résultat de validation d'un Preset."""

    preset_name: str
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    indicators_match: bool
    indicators_expected: List[str]
    indicators_actual: List[str]

    def summary(self) -> str:
        """Retourne un résumé textuel."""
        if self.is_valid:
            return f"✓ {self.preset_name}: VALIDE"
        else:
            errors_str = ", ".join(self.errors)
            return f"✗ {self.preset_name}: INVALIDE - {errors_str}"


def auto_fill_indicators_from_strategy(strategy_name: str) -> List[str]:
    """
    Auto-remplit les indicateurs requis depuis le mapping de stratégie.

    Args:
        strategy_name: Nom de la stratégie

    Returns:
        Liste des indicateurs requis

    Example:
        >>> indicators = auto_fill_indicators_from_strategy("bollinger_atr")
        >>> print(indicators)
        ['bollinger', 'atr']
    """
    try:
        from strategies.indicators_mapping import get_required_indicators
        return get_required_indicators(strategy_name)
    except ImportError:
        logger.warning("Module indicators_mapping non disponible")
        return []
    except KeyError:
        logger.warning(f"Stratégie '{strategy_name}' non trouvée dans le mapping")
        return []


def validate_preset_against_strategy(
    preset: "Preset",  # type: ignore
    strategy_name: str
) -> PresetValidationResult:
    """
    Valide qu'un Preset correspond bien aux indicateurs requis par une stratégie.

    Args:
        preset: Instance de Preset à valider
        strategy_name: Nom de la stratégie associée

    Returns:
        PresetValidationResult avec tous les détails
    """
    errors = []
    warnings = []

    # Récupérer les indicateurs attendus
    try:
        from strategies.indicators_mapping import get_required_indicators
        expected_indicators = get_required_indicators(strategy_name)
    except ImportError:
        errors.append("Module indicators_mapping non disponible")
        return PresetValidationResult(
            preset_name=preset.name,
            is_valid=False,
            errors=errors,
            warnings=warnings,
            indicators_match=False,
            indicators_expected=[],
            indicators_actual=preset.indicators
        )
    except KeyError:
        errors.append(f"Stratégie '{strategy_name}' non trouvée")
        return PresetValidationResult(
            preset_name=preset.name,
            is_valid=False,
            errors=errors,
            warnings=warnings,
            indicators_match=False,
            indicators_expected=[],
            indicators_actual=preset.indicators
        )

    # Comparer les indicateurs
    expected_set = set(expected_indicators)
    actual_set = set(preset.indicators)

    if expected_set != actual_set:
        missing = expected_set - actual_set
        extra = actual_set - expected_set

        if missing:
            errors.append(f"Indicateurs manquants: {sorted(missing)}")
        if extra:
            warnings.append(f"Indicateurs en trop: {sorted(extra)}")

    indicators_match = expected_set == actual_set
    is_valid = len(errors) == 0 and indicators_match

    return PresetValidationResult(
        preset_name=preset.name,
        is_valid=is_valid,
        errors=errors,
        warnings=warnings,
        indicators_match=indicators_match,
        indicators_expected=expected_indicators,
        indicators_actual=preset.indicators
    )


def validate_all_presets() -> Dict[str, PresetValidationResult]:
    """
    Valide tous les Presets du registre.

    Returns:
        Dict mapping preset_name → PresetValidationResult
    """
    from utils.parameters import PRESETS

    # Mapping Preset → Stratégie
    preset_to_strategy = {
        "safe_ranges": "bollinger_atr",
        "minimal": "bollinger_atr",
        "ema_cross": "ema_cross",
        "macd_cross": "macd_cross",
        "rsi_reversal": "rsi_reversal",
        "atr_channel": "atr_channel",
    }

    results = {}

    for preset_name, preset in PRESETS.items():
        if preset_name in preset_to_strategy:
            strategy_name = preset_to_strategy[preset_name]
            result = validate_preset_against_strategy(preset, strategy_name)
            results[preset_name] = result
        else:
            logger.warning(f"Preset '{preset_name}' sans stratégie associée")

    return results


def create_preset_from_strategy(
    strategy_name: str,
    preset_name: Optional[str] = None,
    description: Optional[str] = None,
    granularity: float = 0.5
) -> "Preset":  # type: ignore
    """
    Crée un Preset automatiquement depuis une stratégie.

    Args:
        strategy_name: Nom de la stratégie
        preset_name: Nom du preset (défaut: strategy_name + "_default")
        description: Description (défaut: auto-généré)
        granularity: Granularité par défaut

    Returns:
        Instance de Preset avec indicateurs auto-remplis

    Example:
        >>> preset = create_preset_from_strategy("bollinger_atr")
        >>> print(preset.indicators)
        ['bollinger', 'atr']
    """
    from strategies.base import get_strategy
    from strategies.indicators_mapping import get_required_indicators
    from utils.parameters import Preset

    # Charger la stratégie
    strategy_class = get_strategy(strategy_name)
    strategy = strategy_class()

    # Auto-remplir les indicateurs
    indicators = get_required_indicators(strategy_name)

    # Générer le nom et la description
    if preset_name is None:
        preset_name = f"{strategy_name}_default"

    if description is None:
        description = f"Configuration auto-générée pour {strategy.name}"

    # Créer le Preset
    preset = Preset(
        name=preset_name,
        description=description,
        parameters=strategy.parameter_specs,
        indicators=indicators,
        default_granularity=granularity
    )

    return preset


def format_validation_report(results: Dict[str, PresetValidationResult]) -> str:
    """
    Formate un rapport de validation complet.

    Args:
        results: Résultats de validation

    Returns:
        Rapport formaté en texte
    """
    lines = ["=" * 80]
    lines.append("RAPPORT DE VALIDATION DES PRESETS")
    lines.append("=" * 80)
    lines.append("")

    valid_count = sum(1 for r in results.values() if r.is_valid)
    total_count = len(results)

    lines.append(f"✓ {valid_count}/{total_count} Presets valides")
    lines.append("")

    for preset_name, result in results.items():
        if result.is_valid:
            lines.append(f"✓ {result.preset_name}")
            lines.append(f"   Indicateurs: {result.indicators_actual}")
        else:
            lines.append(f"✗ {result.preset_name}")
            for error in result.errors:
                lines.append(f"   ERREUR: {error}")
            for warning in result.warnings:
                lines.append(f"   WARN: {warning}")
            lines.append(f"   Attendu: {result.indicators_expected}")
            lines.append(f"   Actuel:  {result.indicators_actual}")
        lines.append("")

    lines.append("=" * 80)

    return "\n".join(lines)


__all__ = [
    "PresetValidationResult",
    "auto_fill_indicators_from_strategy",
    "validate_preset_against_strategy",
    "validate_all_presets",
    "create_preset_from_strategy",
    "format_validation_report",
]
