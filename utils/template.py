"""
Module-ID: utils.template

Purpose: Template Jinja2 centralisé pour prompts LLM agents.

Role in pipeline: orchestration / LLM

Key components: render_prompt, TemplateLoader, prompt templates (analyst.jinja2, etc.)

Inputs: Template name, context dict (strategy, metrics, proposals)

Outputs: Prompt string formaté prêt pour LLM

Dependencies: jinja2, pathlib, logging

Conventions: Templates dans templates/ folder; variables contexte nommées; fallback strings si fichier manquant.

Read-if: Modification templates, variables contexte.

Skip-if: Vous appelez juste render_prompt().
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from jinja2.runtime import Undefined

from utils.observability import get_obs_logger

logger = get_obs_logger(__name__)

# Chemin vers le dossier templates (robuste pour installation en paquet)
# Utiliser importlib.resources pour Python 3.9+, sinon fallback
try:
    # Python 3.9+
    from importlib.resources import files
    TEMPLATES_DIR = Path(str(files("backtest_core") / "templates"))
except (ImportError, TypeError):
    # Fallback pour Python < 3.9 ou si backtest_core n'est pas un paquet installé
    try:
        from importlib_resources import files
        TEMPLATES_DIR = Path(str(files("backtest_core") / "templates"))
    except (ImportError, TypeError):
        # Dernier fallback : utiliser le chemin relatif résolu
        TEMPLATES_DIR = (Path(__file__).resolve().parent.parent / "strategies" / "templates").expanduser()

# Environment Jinja2 global (lazy init)
_jinja_env: Optional[Environment] = None


def get_jinja_env() -> Environment:
    """
    Retourne l'environnement Jinja2 (singleton).

    Returns:
        Environment Jinja2 configuré
    """
    global _jinja_env

    if _jinja_env is None:
        _jinja_env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=False,  # Pas d'auto-escape pour les prompts
            trim_blocks=True,  # Supprimer les newlines après {% %}
            lstrip_blocks=True,  # Supprimer indentation avant {% %}
        )

        # Ajouter des filtres personnalisés si nécessaire
        def _format_float(x: Any, n: int = 2) -> str:
            if x is None or isinstance(x, Undefined):
                return "N/A"
            try:
                return f"{float(x):.{int(n)}f}"
            except Exception:
                return "N/A"

        def _format_percent(x: Any) -> str:
            if x is None or isinstance(x, Undefined):
                return "N/A"
            try:
                return f"{float(x):.2%}"
            except Exception:
                return "N/A"

        _jinja_env.filters['format_percent'] = _format_percent
        _jinja_env.filters['format_float'] = _format_float

        logger.debug(f"Jinja2 environment initialisé: {TEMPLATES_DIR}")

    return _jinja_env


def render_prompt(template_name: str, context: Dict[str, Any]) -> str:
    """
    Rend un template de prompt avec le contexte fourni.

    Args:
        template_name: Nom du fichier template (ex: "analyst.jinja2")
        context: Dictionnaire de variables à injecter dans le template

    Returns:
        Prompt rendu sous forme de chaîne

    Raises:
        TemplateNotFound: Si le template n'existe pas
        Exception: Si erreur de rendu

    Example:
        >>> prompt = render_prompt("analyst.jinja2", {
        ...     "strategy_name": "ema_cross",
        ...     "current_metrics": {"sharpe_ratio": 1.5},
        ... })
    """
    try:
        env = get_jinja_env()
        template = env.get_template(template_name)
        rendered = template.render(**context)

        logger.debug(f"Template '{template_name}' rendu avec {len(context)} variables")
        return rendered

    except TemplateNotFound:
        logger.error(f"Template introuvable: {template_name}")
        raise
    except Exception as e:
        logger.error(f"Erreur rendu template '{template_name}': {e}")
        raise


def render_prompt_from_string(template_str: str, context: Dict[str, Any]) -> str:
    """
    Rend un template à partir d'une chaîne (pour tests ou usage ponctuel).

    Args:
        template_str: Template Jinja2 sous forme de chaîne
        context: Dictionnaire de variables

    Returns:
        Prompt rendu

    Example:
        >>> render_prompt_from_string("Hello {{ name }}", {"name": "Agent"})
        'Hello Agent'
    """
    env = get_jinja_env()
    template = env.from_string(template_str)
    return template.render(**context)


def list_available_templates() -> list[str]:
    """
    Liste tous les templates disponibles.

    Returns:
        Liste des noms de fichiers templates
    """
    if not TEMPLATES_DIR.exists():
        return []

    templates = [
        f.name for f in TEMPLATES_DIR.glob("*.jinja2")
    ]
    return sorted(templates)


# Fonction helper pour formater les métriques
def format_metrics_summary(metrics: Any) -> str:
    """
    Formate un objet MetricsSnapshot en résumé texte.

    Args:
        metrics: Objet avec attributs sharpe_ratio, total_return, etc.

    Returns:
        Résumé formaté
    """
    if not metrics:
        return "No metrics available"

    lines = [
        "Performance Metrics:",
        f"  Sharpe Ratio: {metrics.sharpe_ratio:.3f}",
        f"  Total Return: {metrics.total_return:.2%}",
        f"  Max Drawdown: {metrics.max_drawdown:.2%}",
        f"  Win Rate: {metrics.win_rate:.2%}",
        f"  Profit Factor: {metrics.profit_factor:.2f}",
        f"  Total Trades: {metrics.total_trades}",
    ]

    return "\n".join(lines)


# Ajouter le helper comme filtre Jinja2
def _register_filters():
    """Enregistre les filtres personnalisés."""
    env = get_jinja_env()
    env.filters['format_metrics'] = format_metrics_summary


# Initialiser les filtres au chargement du module
_register_filters()
