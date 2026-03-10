"""
Module-ID: utils.log

Purpose: Logging simplifié avec colorisation optionnelle (legacy).

Role in pipeline: core

Key components: get_logger, ColoredFormatter, setup_logging

Inputs: Module name, level (DEBUG/INFO/WARNING/ERROR)

Outputs: Logger configuré avec couleurs optionnelles

Dependencies: logging, colorama (optionnel), sys

Conventions: Colorama auto-detect; fallback sans couleurs; logger par module.

Read-if: Modification format logs, niveaux, couleurs.

Skip-if: Vous utilisez juste get_logger().
"""

import logging
import sys
from typing import Optional

# Import optionnel de colorama pour logs colorés
try:
    from colorama import Fore, Style, init
    init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False
    # Fallback: pas de couleurs

    class _DummyColor:
        def __getattr__(self, name):
            return ""

    Fore = Style = _DummyColor()

# Cache des loggers pour éviter duplication
_loggers: dict[str, logging.Logger] = {}


class ColoredFormatter(logging.Formatter):
    """Formatter avec colorisation par niveau de log."""

    # Couleurs par niveau
    COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record):
        """Formate le message avec couleurs."""
        if COLORAMA_AVAILABLE:
            # Appliquer la couleur selon le niveau
            levelname_color = self.COLORS.get(record.levelno, "")
            record.levelname = f"{levelname_color}{record.levelname}{Style.RESET_ALL}"
        return super().format(record)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Obtient un logger configuré pour le module spécifié.

    Args:
        name: Nom du module (utilise __name__ généralement)

    Returns:
        Logger configuré avec format standard
    """
    if name is None:
        name = "backtest_core"

    # Retourner le logger en cache si existe
    if name in _loggers:
        return _loggers[name]

    # Créer nouveau logger
    logger = logging.getLogger(name)

    # Éviter duplication si déjà configuré
    if not logger.handlers:
        logger.setLevel(logging.INFO)

        # Handler console
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)

        # Format simple et lisible avec colorisation
        formatter = ColoredFormatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        # Éviter propagation vers le root logger
        logger.propagate = False

    _loggers[name] = logger
    return logger


def set_level(level: str) -> None:
    """
    Change le niveau de log global.

    Args:
        level: 'DEBUG', 'INFO', 'WARNING', 'ERROR'
    """
    level_map = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR
    }

    log_level = level_map.get(level.upper(), logging.INFO)

    for logger in _loggers.values():
        logger.setLevel(log_level)
        for handler in logger.handlers:
            handler.setLevel(log_level)


class CountingHandler(logging.Handler):
    """
    Handler qui compte les warnings et erreurs pour statistiques de run.

    Usage:
        counting_handler = CountingHandler()
        logger.addHandler(counting_handler)

        # Plus tard
        warnings_count = counting_handler.warnings
        errors_count = counting_handler.errors
    """

    def __init__(self):
        """Initialise le compteur."""
        super().__init__()
        self.warnings = 0
        self.errors = 0

    def emit(self, record):
        """Compte les warnings et erreurs."""
        if record.levelno == logging.WARNING:
            self.warnings += 1
        elif record.levelno >= logging.ERROR:
            self.errors += 1

    def reset(self):
        """Réinitialise les compteurs."""
        self.warnings = 0
        self.errors = 0


__all__ = ["get_logger", "set_level", "CountingHandler"]
