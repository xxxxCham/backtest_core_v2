"""Module-ID: utils.config_validator

Purpose: Valider les paramètres de configuration contre les contraintes définies dans indicator_ranges.toml

Role in pipeline: validation

Key components: validate_params, load_constraints, check_constraint

Inputs: Paramètres dict, nom de catégorie (ex: "ema_cross")

Outputs: Tuple (bool, list[str]) - (valide, liste_erreurs)

Dependencies: tomli (Python 3.11+) ou tomllib, pathlib

Conventions: Utilise eval() de manière sécurisée avec namespace restreint.

Read-if: Validation de paramètres avant backtest/optimisation

Skip-if: Vous ne faites que lire les configs sans les valider
"""

import sys
from pathlib import Path
from typing import Any

# Python 3.11+ a tomllib built-in, sinon utiliser tomli
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        raise ImportError(
            "Python < 3.11 nécessite 'tomli'. Installez avec: pip install tomli",
        )

from utils.log import get_logger

logger = get_logger(__name__)

# Cache global pour éviter de recharger le fichier TOML à chaque validation
_CONSTRAINTS_CACHE: dict[str, list[str]] = {}


def load_constraints(config_path: Path = None) -> dict[str, list[str]]:
    """Charge les contraintes depuis indicator_ranges.toml.

    Args:
        config_path: Chemin optionnel vers le fichier TOML.
                     Par défaut: config/indicator_ranges.toml

    Returns:
        Dict mapping category -> list of constraint expressions

    Example:
        >>> constraints = load_constraints()
        >>> constraints["ema_cross"]
        ["fast_period < slow_period"]

    """
    global _CONSTRAINTS_CACHE

    if _CONSTRAINTS_CACHE:
        return _CONSTRAINTS_CACHE

    if config_path is None:
        # Détecter le répertoire racine du projet
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent  # utils/ -> backtest_core/
        config_path = project_root / "config" / "indicator_ranges.toml"

    if not config_path.exists():
        logger.warning(f"Fichier de contraintes introuvable: {config_path}")
        return {}

    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    constraints = config.get("constraints", {})
    _CONSTRAINTS_CACHE = constraints

    logger.info(
        f"Contraintes chargées: {len(constraints)} catégories depuis {config_path}",
    )
    return constraints


def check_constraint(
    expression: str,
    params: dict[str, Any],
    safe_namespace: dict[str, Any] = None,
) -> tuple[bool, str]:
    """Évalue une expression de contrainte de manière sécurisée.

    Args:
        expression: Expression Python (ex: "fast_period < slow_period")
        params: Dictionnaire des paramètres avec leurs valeurs
        safe_namespace: Namespace optionnel pour eval (sécurité)

    Returns:
        (is_valid, error_message)

    Example:
        >>> params = {"fast_period": 12, "slow_period": 26}
        >>> check_constraint("fast_period < slow_period", params)
        (True, "")

    """
    if safe_namespace is None:
        # Namespace sécurisé: seulement les opérateurs de comparaison
        safe_namespace = {
            "__builtins__": {},
            # Opérateurs autorisés (pas de fonction dangereuse)
        }

    # Merger les paramètres dans le namespace
    eval_namespace = {**safe_namespace, **params}

    try:
        result = eval(expression, eval_namespace)
        if not isinstance(result, bool):
            logger.warning(
                f"Contrainte non booléenne: '{expression}' -> {result} (type: {type(result)})",
            )
            return False, f"Expression non booléenne: {expression}"

        if not result:
            return False, f"Contrainte violée: {expression}"

        return True, ""

    except NameError as e:
        # Paramètre manquant dans params (peut-être optionnel)
        missing_param = str(e).split("'")[1] if "'" in str(e) else "unknown"
        logger.debug(
            f"Paramètre manquant pour contrainte '{expression}': {missing_param}",
        )
        return True, ""  # On considère valide si paramètre optionnel manquant

    except Exception as e:
        logger.error(f"Erreur lors de l'évaluation de '{expression}': {e}")
        return False, f"Erreur évaluation: {expression} -> {e}"


def validate_params(
    category: str,
    params: dict[str, Any],
    config_path: Path = None,
) -> tuple[bool, list[str]]:
    """Valide les paramètres d'une catégorie contre ses contraintes.

    Args:
        category: Nom de la catégorie (ex: "ema_cross", "rsi", "macd")
        params: Dictionnaire des paramètres avec leurs valeurs
        config_path: Chemin optionnel vers indicator_ranges.toml

    Returns:
        (is_valid, list_of_errors)

    Example:
        >>> params = {"fast_period": 50, "slow_period": 26}  # INVALIDE!
        >>> is_valid, errors = validate_params("ema_cross", params)
        >>> print(is_valid, errors)
        False ['Contrainte violée: fast_period < slow_period']

        >>> params = {"fast_period": 12, "slow_period": 26}  # VALIDE
        >>> is_valid, errors = validate_params("ema_cross", params)
        >>> print(is_valid, errors)
        True []

    """
    constraints = load_constraints(config_path)

    if category not in constraints:
        logger.debug(f"Aucune contrainte définie pour la catégorie: {category}")
        return True, []

    constraint_rules = constraints[category]
    errors = []

    for rule in constraint_rules:
        is_valid, error_msg = check_constraint(rule, params)
        if not is_valid and error_msg:
            errors.append(error_msg)

    is_valid = len(errors) == 0

    if not is_valid:
        logger.warning(
            f"Validation échouée pour {category}: {len(errors)} contrainte(s) violée(s)",
        )
        for error in errors:
            logger.warning(f"  - {error}")

    return is_valid, errors


def validate_preset(preset_dict: dict[str, Any]) -> tuple[bool, list[str]]:
    """Valide un preset complet (depuis profitable_presets.toml).

    Args:
        preset_dict: Dict contenant 'strategy' et 'params'

    Returns:
        (is_valid, list_of_errors)

    Example:
        >>> preset = {
        ...     "strategy": "ema_cross",
        ...     "params": {"fast_period": 15, "slow_period": 50}
        ... }
        >>> is_valid, errors = validate_preset(preset)
        >>> print(is_valid)
        True

    """
    if "strategy" not in preset_dict:
        return False, ["Clé 'strategy' manquante dans le preset"]

    strategy = preset_dict["strategy"]
    params = preset_dict.get("params", {})

    return validate_params(strategy, params)


# ==========================================================================
# TESTS UNITAIRES (exécutables avec: python -m utils.config_validator)
# ==========================================================================

if __name__ == "__main__":
    print("=== Tests de validation de contraintes ===\n")

    # Test 1: EMA Cross valide
    print("Test 1: EMA Cross valide")
    params = {"fast_period": 15, "slow_period": 50}
    is_valid, errors = validate_params("ema_cross", params)
    assert is_valid, f"Devrait être valide: {errors}"
    print(f"✅ PASS: {params} -> valide\n")

    # Test 2: EMA Cross invalide (fast > slow)
    print("Test 2: EMA Cross invalide")
    params = {"fast_period": 50, "slow_period": 26}
    is_valid, errors = validate_params("ema_cross", params)
    assert not is_valid, "Devrait être invalide"
    print(f"✅ PASS: {params} -> invalide ({errors})\n")

    # Test 3: RSI valide
    print("Test 3: RSI valide")
    params = {"oversold": 30, "overbought": 70}
    is_valid, errors = validate_params("rsi", params)
    assert is_valid, f"Devrait être valide: {errors}"
    print(f"✅ PASS: {params} -> valide\n")

    # Test 4: RSI invalide (oversold > overbought)
    print("Test 4: RSI invalide")
    params = {"oversold": 70, "overbought": 30}
    is_valid, errors = validate_params("rsi", params)
    assert not is_valid, "Devrait être invalide"
    print(f"✅ PASS: {params} -> invalide ({errors})\n")

    # Test 5: MACD valide
    print("Test 5: MACD valide")
    params = {"fast_period": 12, "slow_period": 26, "signal_period": 9}
    is_valid, errors = validate_params("macd", params)
    assert is_valid, f"Devrait être valide: {errors}"
    print(f"✅ PASS: {params} -> valide\n")

    # Test 6: MACD invalide (fast >= slow)
    print("Test 6: MACD invalide")
    params = {"fast_period": 26, "slow_period": 12, "signal_period": 9}
    is_valid, errors = validate_params("macd", params)
    assert not is_valid, "Devrait être invalide"
    print(f"✅ PASS: {params} -> invalide ({errors})\n")

    # Test 7: Preset complet
    print("Test 7: Validation preset complet")
    preset = {
        "strategy": "rsi_reversal",
        "params": {"rsi_period": 14, "overbought": 70, "oversold": 30},
    }
    is_valid, errors = validate_preset(preset)
    assert is_valid, f"Devrait être valide: {errors}"
    print("✅ PASS: Preset rsi_reversal -> valide\n")

    # Test 8: Catégorie sans contraintes
    print("Test 8: Catégorie sans contraintes (bollinger)")
    params = {"period": 20, "std_dev": 2.0}
    is_valid, errors = validate_params("bollinger", params)
    assert is_valid, "Devrait être valide (aucune contrainte)"
    print("✅ PASS: bollinger sans contraintes -> valide\n")

    print("=== 🎉 Tous les tests passent! ===")
