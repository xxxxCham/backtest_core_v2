"""
Module-ID: cli.validators

Purpose: Validation des arguments CLI, paramètres et fichiers.

Role in pipeline: Validation avant exécution des commandes.

Key components: validate_strategy, validate_data_file, validate_params, parse_param_grid

Dependencies: pathlib, json, strategies

Conventions: Retourne (success, value_or_error) tuples pour gestion d'erreur propre.

Read-if: Ajout de nouvelles validations CLI.

Skip-if: Utilisation des commandes existantes.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

import pandas as pd

# =============================================================================
# DATACLASSES RÉSULTATS
# =============================================================================

@dataclass
class ValidationResult:
    """Résultat d'une validation."""
    success: bool
    value: Any = None
    error: Optional[str] = None
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


# =============================================================================
# VALIDATION STRATÉGIE
# =============================================================================

def validate_strategy(strategy_name: str) -> ValidationResult:
    """
    Valide qu'une stratégie existe dans le registre.

    Args:
        strategy_name: Nom de la stratégie (case-insensitive)

    Returns:
        ValidationResult avec la classe de stratégie si succès
    """
    from strategies import get_strategy, list_strategies

    strategy_name = strategy_name.lower()
    strategy_class = get_strategy(strategy_name)

    if strategy_class is None:
        available = list_strategies()
        return ValidationResult(
            success=False,
            error=f"Stratégie '{strategy_name}' non trouvée. "
                  f"Disponibles: {', '.join(available[:5])}..."
        )

    return ValidationResult(success=True, value=strategy_class)


def get_strategy_info(strategy_name: str) -> ValidationResult:
    """
    Récupère les informations complètes d'une stratégie.

    Args:
        strategy_name: Nom de la stratégie

    Returns:
        ValidationResult avec dict d'infos {class, instance, params, ranges}
    """
    result = validate_strategy(strategy_name)
    if not result.success:
        return result

    try:
        strategy_class = result.value
        strategy_instance = strategy_class()

        info = {
            "class": strategy_class,
            "instance": strategy_instance,
            "default_params": strategy_instance.default_params,
            "param_ranges": strategy_instance.param_ranges,
            "parameter_specs": getattr(strategy_instance, "parameter_specs", {}),
        }

        return ValidationResult(success=True, value=info)
    except Exception as e:
        return ValidationResult(
            success=False,
            error=f"Erreur initialisation stratégie: {e}"
        )


# =============================================================================
# VALIDATION FICHIERS DONNÉES
# =============================================================================

def validate_data_file(data_path: Union[str, Path],
                       env_var: str = "BACKTEST_DATA_DIR") -> ValidationResult:
    """
    Valide et résout le chemin d'un fichier de données.

    Args:
        data_path: Chemin du fichier (absolu ou relatif)
        env_var: Variable d'environnement pour répertoire de données

    Returns:
        ValidationResult avec Path résolu si succès
    """
    from data.loader import resolve_data_file

    path = Path(data_path)

    # Essayer le chemin direct
    if path.exists():
        return ValidationResult(success=True, value=path)

    # Essayer avec BACKTEST_DATA_DIR
    data_dir = os.environ.get(env_var)
    if data_dir:
        alt_path = Path(data_dir) / path.name
        if alt_path.exists():
            return ValidationResult(success=True, value=alt_path)

    # Essayer dans data/sample_data
    sample_path = Path(__file__).parent.parent / "data" / "sample_data" / path.name
    if sample_path.exists():
        return ValidationResult(success=True, value=sample_path)

    # Utiliser resolve_data_file comme dernier recours
    try:
        resolved = resolve_data_file(path)
        if resolved.exists():
            return ValidationResult(success=True, value=resolved)
    except Exception:
        pass

    return ValidationResult(
        success=False,
        error=f"Fichier non trouvé: {data_path}. "
              f"Définissez {env_var} ou placez le fichier dans data/sample_data/"
    )


def extract_symbol_timeframe(data_path: Path,
                             default_symbol: str = "UNKNOWN",
                             default_timeframe: str = "1h") -> Tuple[str, str]:
    """
    Extrait symbol et timeframe du nom de fichier.

    Format attendu: SYMBOL_TIMEFRAME.ext (ex: BTCUSDC_1h.parquet)

    Args:
        data_path: Chemin du fichier
        default_symbol: Symbol par défaut si non détectable
        default_timeframe: Timeframe par défaut si non détectable

    Returns:
        Tuple (symbol, timeframe)
    """
    stem = data_path.stem
    parts = stem.split("_")

    symbol = parts[0] if parts else default_symbol
    timeframe = parts[1] if len(parts) > 1 else default_timeframe

    return symbol, timeframe


# =============================================================================
# VALIDATION PARAMÈTRES
# =============================================================================

def validate_param_value(name: str, value: Any,
                        min_val: float = None,
                        max_val: float = None,
                        param_type: str = None) -> ValidationResult:
    """
    Valide une valeur de paramètre.

    Args:
        name: Nom du paramètre
        value: Valeur à valider
        min_val: Valeur minimum autorisée
        max_val: Valeur maximum autorisée
        param_type: Type attendu ("int" ou "float")

    Returns:
        ValidationResult avec valeur convertie si succès
    """
    warnings = []

    # Conversion de type
    try:
        if param_type == "int":
            value = int(value)
        elif param_type == "float":
            value = float(value)
    except (ValueError, TypeError) as e:
        return ValidationResult(
            success=False,
            error=f"Paramètre '{name}': conversion impossible vers {param_type}: {e}"
        )

    # Validation bornes
    if min_val is not None and value < min_val:
        return ValidationResult(
            success=False,
            error=f"Paramètre '{name}': valeur {value} < minimum {min_val}"
        )

    if max_val is not None and value > max_val:
        return ValidationResult(
            success=False,
            error=f"Paramètre '{name}': valeur {value} > maximum {max_val}"
        )

    return ValidationResult(success=True, value=value, warnings=warnings)


def parse_param_grid(json_string: str) -> ValidationResult:
    """
    Parse une grille de paramètres depuis JSON.

    Format attendu: {"param1": [v1, v2, ...], "param2": [v1, v2, ...]}

    Args:
        json_string: String JSON de la grille

    Returns:
        ValidationResult avec dict de grille si succès
    """
    try:
        grid = json.loads(json_string)

        if not isinstance(grid, dict):
            return ValidationResult(
                success=False,
                error="La grille doit être un objet JSON {param: [valeurs]}"
            )

        # Valider que chaque valeur est une liste
        for param, values in grid.items():
            if not isinstance(values, list):
                return ValidationResult(
                    success=False,
                    error=f"Paramètre '{param}': doit être une liste de valeurs"
                )
            if len(values) == 0:
                return ValidationResult(
                    success=False,
                    error=f"Paramètre '{param}': liste vide non autorisée"
                )

        return ValidationResult(success=True, value=grid)

    except json.JSONDecodeError as e:
        return ValidationResult(
            success=False,
            error=f"JSON invalide: {e}"
        )


def parse_params_string(params_string: str) -> ValidationResult:
    """
    Parse des paramètres depuis une string key=value.

    Format: "param1=value1,param2=value2" ou JSON

    Args:
        params_string: String de paramètres

    Returns:
        ValidationResult avec dict de paramètres si succès
    """
    if not params_string:
        return ValidationResult(success=True, value={})

    # Essayer d'abord JSON
    try:
        params = json.loads(params_string)
        if isinstance(params, dict):
            return ValidationResult(success=True, value=params)
    except json.JSONDecodeError:
        pass

    # Parser format key=value,key=value
    params = {}
    try:
        for pair in params_string.split(","):
            if "=" not in pair:
                return ValidationResult(
                    success=False,
                    error=f"Format invalide: '{pair}'. Attendu: key=value"
                )

            key, value = pair.split("=", 1)
            key = key.strip()
            value = value.strip()

            # Auto-conversion des types
            if value.lower() == "true":
                params[key] = True
            elif value.lower() == "false":
                params[key] = False
            else:
                try:
                    # Essayer int
                    params[key] = int(value)
                except ValueError:
                    try:
                        # Essayer float
                        params[key] = float(value)
                    except ValueError:
                        # Garder string
                        params[key] = value

        return ValidationResult(success=True, value=params)

    except Exception as e:
        return ValidationResult(
            success=False,
            error=f"Erreur parsing paramètres: {e}"
        )


# =============================================================================
# VALIDATION DATES
# =============================================================================

def validate_date_range(start: Optional[str], end: Optional[str]) -> ValidationResult:
    """
    Valide une plage de dates.

    Args:
        start: Date de début (format YYYY-MM-DD ou None)
        end: Date de fin (format YYYY-MM-DD ou None)

    Returns:
        ValidationResult avec tuple (start_ts, end_ts) si succès
    """
    start_ts = None
    end_ts = None

    if start:
        try:
            start_ts = pd.Timestamp(start, tz="UTC")
        except Exception:
            return ValidationResult(
                success=False,
                error=f"Date de début invalide: {start}. Format attendu: YYYY-MM-DD"
            )

    if end:
        try:
            end_ts = pd.Timestamp(end, tz="UTC")
        except Exception:
            return ValidationResult(
                success=False,
                error=f"Date de fin invalide: {end}. Format attendu: YYYY-MM-DD"
            )

    if start_ts and end_ts and start_ts >= end_ts:
        return ValidationResult(
            success=False,
            error=f"Date de début ({start}) >= date de fin ({end})"
        )

    return ValidationResult(success=True, value=(start_ts, end_ts))


def apply_date_filter(df: pd.DataFrame,
                     start: Optional[str],
                     end: Optional[str]) -> ValidationResult:
    """
    Applique un filtre de dates à un DataFrame OHLCV.

    Args:
        df: DataFrame avec index DatetimeIndex
        start: Date de début (format YYYY-MM-DD ou None)
        end: Date de fin (format YYYY-MM-DD ou None)

    Returns:
        ValidationResult avec DataFrame filtré si succès
    """
    if not start and not end:
        return ValidationResult(success=True, value=df)

    result = validate_date_range(start, end)
    if not result.success:
        return result

    start_ts, end_ts = result.value
    filtered_df = df.copy()

    if start_ts is not None:
        filtered_df = filtered_df[filtered_df.index >= start_ts]
    if end_ts is not None:
        filtered_df = filtered_df[filtered_df.index <= end_ts]

    if filtered_df.empty:
        return ValidationResult(
            success=False,
            error=f"Aucune donnée dans la période {start} - {end}"
        )

    return ValidationResult(success=True, value=filtered_df)


# =============================================================================
# VALIDATION MÉTRIQUES
# =============================================================================

METRIC_ALIASES = {
    "sharpe": "sharpe_ratio",
    "sortino": "sortino_ratio",
    "total_return": "total_return_pct",
    "return": "total_return_pct",
    "pnl": "total_pnl",
    "drawdown": "max_drawdown_pct",
    "max_drawdown": "max_drawdown_pct",
    "winrate": "win_rate_pct",
    "win_rate": "win_rate_pct",
    # Formes complètes
    "sharpe_ratio": "sharpe_ratio",
    "sortino_ratio": "sortino_ratio",
    "total_return_pct": "total_return_pct",
    "total_pnl": "total_pnl",
    "max_drawdown_pct": "max_drawdown_pct",
    "win_rate_pct": "win_rate_pct",
    "profit_factor": "profit_factor",
}


def normalize_metric_name(metric: str) -> str:
    """Normalise le nom d'une métrique CLI en nom interne."""
    return METRIC_ALIASES.get(metric.lower(), metric)


def validate_metric(metric: str) -> ValidationResult:
    """
    Valide un nom de métrique.

    Args:
        metric: Nom de la métrique (peut être un alias)

    Returns:
        ValidationResult avec nom normalisé si succès
    """
    normalized = normalize_metric_name(metric)

    valid_metrics = set(METRIC_ALIASES.values())

    if normalized not in valid_metrics:
        return ValidationResult(
            success=False,
            error=f"Métrique '{metric}' inconnue. "
                  f"Valides: {', '.join(sorted(valid_metrics))}"
        )

    return ValidationResult(success=True, value=normalized)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Dataclasses
    "ValidationResult",
    # Stratégies
    "validate_strategy",
    "get_strategy_info",
    # Fichiers
    "validate_data_file",
    "extract_symbol_timeframe",
    # Paramètres
    "validate_param_value",
    "parse_param_grid",
    "parse_params_string",
    # Dates
    "validate_date_range",
    "apply_date_filter",
    # Métriques
    "METRIC_ALIASES",
    "normalize_metric_name",
    "validate_metric",
]
