"""
Module-ID: utils.observability

Purpose: Observabilité debug intelligent (lazy formatting, traces corrélées, sampling).

Role in pipeline: core / monitoring

Key components: get_obs_logger, trace_span, PerfCounters, DiagnosticPack, generate_run_id

Inputs: Module name, run_id, log level (env vars)

Outputs: Logs JSON structurés, traces span avec timing, pack diagnostique

Dependencies: logging, json, dataclasses, functools

Conventions: DEBUG mode lazy-evaluated; sampling configurable; run_id corrélé; zero overhead prod.

Read-if: Modification logging structure, sampling, ou diagnostic export.

Skip-if: Vous utilisez juste get_obs_logger().
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Generator, Optional

import numpy as np
import pandas as pd

# ============================================================================
# CONFIGURATION VIA ENV VARS
# ============================================================================

_LOG_LEVEL = os.getenv("BACKTEST_LOG_LEVEL", "INFO").upper()
_LOG_SAMPLE = float(os.getenv("BACKTEST_LOG_SAMPLE", "1.0"))
_LOG_JSON = os.getenv("BACKTEST_LOG_JSON", "0") == "1"
_LOG_FILE = os.getenv("BACKTEST_LOG_FILE", "")
_LOG_ROTATE_MB = int(os.getenv("BACKTEST_LOG_ROTATE_MB", "10"))

# Mapping niveaux
_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


# ============================================================================
# JSON FORMATTER (pour logs structurés)
# ============================================================================

class JSONFormatter(logging.Formatter):
    """Formateur JSON Lines pour logs structurés."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Ajouter les champs extra du LoggerAdapter
        if hasattr(record, "run_id") and record.run_id:
            log_obj["run_id"] = record.run_id
        if hasattr(record, "strategy"):
            log_obj["strategy"] = record.strategy
        if hasattr(record, "symbol"):
            log_obj["symbol"] = record.symbol
        if hasattr(record, "timeframe"):
            log_obj["timeframe"] = record.timeframe
        # Champs arbitraires
        if hasattr(record, "extra_fields"):
            log_obj.update(record.extra_fields)
        return json.dumps(log_obj, default=str)


class HumanFormatter(logging.Formatter):
    """Formateur lisible avec run_id en préfixe."""

    def __init__(self):
        super().__init__(
            "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
            datefmt="%H:%M:%S"
        )

    def format(self, record: logging.LogRecord) -> str:
        # Préfixer le message avec run_id si présent
        if hasattr(record, "run_id") and record.run_id:
            record.msg = f"[{record.run_id}] {record.msg}"
        return super().format(record)


# ============================================================================
# LOGGER ADAPTER AVEC CONTEXTE
# ============================================================================

class ObsLoggerAdapter(logging.LoggerAdapter):
    """
    Adapter qui injecte run_id et contexte dans chaque log.

    Le contexte est passé une seule fois à la création, puis réutilisé.
    """

    def __init__(
        self,
        logger: logging.Logger,
        run_id: Optional[str] = None,
        strategy: Optional[str] = None,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
    ):
        extra = {
            "run_id": run_id,
            "strategy": strategy,
            "symbol": symbol,
            "timeframe": timeframe,
        }
        super().__init__(logger, extra)
        self._sample_rate = _LOG_SAMPLE

    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        """Injecte le contexte dans chaque log."""
        extra = kwargs.get("extra", {})
        extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs

    def with_context(self, **fields) -> "ObsLoggerAdapter":
        """Crée un nouvel adapter avec contexte enrichi."""
        new_extra = {**self.extra, **fields}
        return ObsLoggerAdapter(
            self.logger,
            run_id=new_extra.get("run_id"),
            strategy=new_extra.get("strategy"),
            symbol=new_extra.get("symbol"),
            timeframe=new_extra.get("timeframe"),
        )

    def should_sample(self) -> bool:
        """Retourne True si ce run doit être loggé (sampling)."""
        return random.random() < self._sample_rate


# ============================================================================
# INITIALISATION GLOBALE
# ============================================================================

_initialized = False
_root_handler: Optional[logging.Handler] = None


def init_logging(
    level: Optional[str] = None,
    json_format: Optional[bool] = None,
    file_path: Optional[Path] = None,
    rotate_mb: Optional[int] = None,
) -> None:
    """
    Initialise le système de logging.

    Appelé automatiquement au premier get_obs_logger(), mais peut être
    appelé manuellement pour forcer une configuration spécifique.

    Args:
        level: Niveau de log (DEBUG, INFO, WARNING, ERROR)
        json_format: True pour JSON lines, False pour texte
        file_path: Chemin vers fichier de log (optionnel)
        rotate_mb: Taille max du fichier avant rotation (Mo)
    """
    global _initialized, _root_handler

    if _initialized:
        return

    # Utiliser env vars si pas spécifié
    level = level or _LOG_LEVEL
    json_format = json_format if json_format is not None else _LOG_JSON
    file_path = file_path or (Path(_LOG_FILE) if _LOG_FILE else None)
    rotate_mb = rotate_mb or _LOG_ROTATE_MB

    log_level = _LEVEL_MAP.get(level.upper(), logging.INFO)

    # Formateur
    formatter = JSONFormatter() if json_format else HumanFormatter()

    # Handler console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    # Handler fichier (optionnel)
    file_handler = None
    if file_path:
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=rotate_mb * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)

    # Configurer le root logger "backtest"
    root_logger = logging.getLogger("backtest")
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    if file_handler:
        root_logger.addHandler(file_handler)
    root_logger.propagate = False

    # Supprimer les warnings WebSocket répétés de Tornado (connexions fermées par client)
    tornado_ws_logger = logging.getLogger("tornado.websocket")
    tornado_ws_logger.setLevel(logging.ERROR)  # Ignorer les warnings WebSocketClosedError

    # Supprimer aussi les warnings de tornado.general liés aux WebSockets
    tornado_general_logger = logging.getLogger("tornado.general")
    tornado_general_logger.setLevel(logging.ERROR)

    _root_handler = console_handler
    _initialized = True


def get_obs_logger(
    name: str,
    run_id: Optional[str] = None,
    **context,
) -> ObsLoggerAdapter:
    """
    Obtient un logger avec contexte d'observabilité.

    Args:
        name: Nom du module (utiliser __name__)
        run_id: Identifiant unique du run (généré si None)
        **context: Champs additionnels (strategy, symbol, timeframe)

    Returns:
        ObsLoggerAdapter configuré

    Usage:
        logger = get_obs_logger(__name__, run_id="abc123", strategy="ema_cross")
        logger.info("Pipeline started")  # [abc123] Pipeline started
    """
    init_logging()

    # Préfixer avec "backtest." si pas déjà
    if not name.startswith("backtest."):
        name = f"backtest.{name}"

    logger = logging.getLogger(name)
    return ObsLoggerAdapter(
        logger,
        run_id=run_id,
        strategy=context.get("strategy"),
        symbol=context.get("symbol"),
        timeframe=context.get("timeframe"),
    )


def generate_run_id(
    strategy: Optional[str] = None,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    seed: Optional[int] = None
) -> str:
    """
    Génère un run_id unique et lisible pour traçabilité complète.

    Format court (si pas de paramètres): 8 caractères UUID
    Format complet: {strategy}_{symbol}_{timeframe}_{timestamp}_{unique}[_s{seed}]

    Args:
        strategy: Nom de la stratégie (ex: "ema_cross"). Si None, format court.
        symbol: Actif tradé (ex: "BTCUSDT")
        timeframe: Timeframe (ex: "1h", "4h", "1d")
        seed: Seed optionnel pour reproductibilité

    Returns:
        run_id unique et lisible

    Examples:
        >>> generate_run_id()  # Format court
        'a3f7b2c1'
        >>> generate_run_id("ema_cross", "BTCUSDT", "1h", 42)  # Format complet
        'ema_cross_BTCUSDT_1h_20250228_143052_a3f7b2c1_s42'
    """
    # Format court si pas de paramètres
    if not strategy and not symbol and not timeframe:
        return uuid.uuid4().hex[:8]

    # Format complet avec contexte
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique = uuid.uuid4().hex[:8]

    parts = []
    if strategy:
        parts.append(strategy)
    if symbol:
        parts.append(symbol)
    if timeframe:
        parts.append(timeframe)

    parts.extend([timestamp, unique])

    if seed is not None:
        parts.append(f"s{seed}")

    return "_".join(parts)


# ============================================================================
# TRACE SPAN - Mesure de durée
# ============================================================================

@contextmanager
def trace_span(
    logger: ObsLoggerAdapter,
    name: str,
    log_level: int = logging.DEBUG,
    **fields,
) -> Generator[Dict[str, Any], None, None]:
    """
    Context manager pour tracer la durée d'une opération.

    ZERO OVERHEAD si le niveau n'est pas activé:
    - Pas de string formatting
    - Pas de calcul de durée

    Args:
        logger: Logger avec contexte
        name: Nom du span (ex: "indicators", "simulation")
        log_level: Niveau de log (DEBUG par défaut)
        **fields: Champs additionnels à loguer

    Yields:
        Dict pour stocker des métriques pendant le span

    Usage:
        with trace_span(logger, "indicators", count=5) as span:
            # ... calculs ...
            span["computed"] = 42
    """
    span_data: Dict[str, Any] = {}

    # Check niveau AVANT toute opération
    if not logger.isEnabledFor(log_level):
        yield span_data
        return

    start = time.perf_counter()
    logger.log(log_level, "span_start: %s %s", name, fields or "")

    try:
        yield span_data
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        all_fields = {**fields, **span_data, "duration_ms": round(duration_ms, 2)}
        logger.log(log_level, "span_end: %s %s", name, all_fields)


# ============================================================================
# SAFE STATS - Résumés sans dump complet
# ============================================================================

def safe_stats_df(df: pd.DataFrame, max_rows: int = 3) -> Dict[str, Any]:
    """
    Statistiques sûres d'un DataFrame (jamais le contenu complet).

    Args:
        df: DataFrame à résumer
        max_rows: Nombre max de lignes pour head() (défaut: 3)

    Returns:
        Dict avec shape, dtypes, nan_count, sample_values
    """
    if df is None or df.empty:
        return {"shape": (0, 0), "empty": True}

    stats = {
        "shape": df.shape,
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "nan_count": int(df.isna().sum().sum()),
        "memory_mb": round(df.memory_usage(deep=True).sum() / 1024 / 1024, 2),
    }

    # Index info
    if isinstance(df.index, pd.DatetimeIndex):
        stats["index_range"] = [str(df.index.min()), str(df.index.max())]

    # Sample (head) seulement si demandé
    if max_rows > 0 and len(df) > 0:
        stats["head"] = df.head(max_rows).to_dict("records")

    return stats


def safe_stats_array(x: np.ndarray, name: str = "array") -> Dict[str, Any]:
    """
    Statistiques sûres d'un array numpy.

    Args:
        x: Array à résumer
        name: Nom pour identification

    Returns:
        Dict avec shape, dtype, nan_count, min/max/mean
    """
    if x is None:
        return {"name": name, "value": None}

    if not isinstance(x, np.ndarray):
        return {"name": name, "type": type(x).__name__, "value": str(x)[:100]}

    stats = {
        "name": name,
        "shape": x.shape,
        "dtype": str(x.dtype),
    }

    # Stats numériques (protégé contre types non-numériques)
    if np.issubdtype(x.dtype, np.number):
        finite_mask = np.isfinite(x)
        stats["nan_count"] = int((~finite_mask).sum())
        if finite_mask.any():
            finite_x = x[finite_mask]
            stats["min"] = float(np.min(finite_x))
            stats["max"] = float(np.max(finite_x))
            stats["mean"] = float(np.mean(finite_x))

    return stats


def safe_stats_series(s: pd.Series, name: str = "series") -> Dict[str, Any]:
    """
    Statistiques sûres d'une Series pandas.
    """
    if s is None or s.empty:
        return {"name": name, "empty": True}

    return {
        "name": name,
        "shape": s.shape,
        "dtype": str(s.dtype),
        "nan_count": int(s.isna().sum()),
        "min": float(s.min()) if pd.api.types.is_numeric_dtype(s) else None,
        "max": float(s.max()) if pd.api.types.is_numeric_dtype(s) else None,
    }


# ============================================================================
# PERF COUNTERS - Compteurs légers O(1)
# ============================================================================

@dataclass
class PerfCounters:
    """
    Compteurs de performance légers pour le pipeline.

    Usage:
        counters = PerfCounters()
        counters.start("indicators")
        # ... calculs ...
        counters.stop("indicators")

        print(counters.summary())
    """
    _starts: Dict[str, float] = field(default_factory=dict)
    _durations: Dict[str, float] = field(default_factory=dict)
    _counts: Dict[str, int] = field(default_factory=dict)

    def start(self, name: str) -> None:
        """Démarre un chrono."""
        self._starts[name] = time.perf_counter()

    def stop(self, name: str) -> float:
        """Arrête un chrono et retourne la durée en ms."""
        if name not in self._starts:
            return 0.0
        duration_ms = (time.perf_counter() - self._starts[name]) * 1000
        self._durations[name] = duration_ms
        return duration_ms

    def increment(self, name: str, delta: int = 1) -> None:
        """Incrémente un compteur."""
        self._counts[name] = self._counts.get(name, 0) + delta

    def get_duration(self, name: str) -> float:
        """Retourne la durée en ms."""
        return self._durations.get(name, 0.0)

    def summary(self) -> Dict[str, Any]:
        """Retourne un résumé des compteurs."""
        return {
            "durations_ms": {k: round(v, 2) for k, v in self._durations.items()},
            "counts": self._counts.copy(),
            "total_ms": round(sum(self._durations.values()), 2),
        }


# ============================================================================
# DIAGNOSTIC PACK
# ============================================================================

@dataclass
class DiagnosticPack:
    """Pack diagnostic compact pour analyse rapide."""
    run_id: str
    timestamp: str
    strategy: Optional[str]
    symbol: Optional[str]
    timeframe: Optional[str]
    params: Dict[str, Any]
    counters: Dict[str, Any]
    result_summary: Dict[str, Any]
    error: Optional[str]
    error_type: Optional[str]

    def to_json(self) -> str:
        """Sérialise en JSON compact."""
        return json.dumps(asdict(self), indent=2, default=str)

    def to_file(self, path: Path) -> None:
        """Exporte vers un fichier."""
        path.write_text(self.to_json(), encoding="utf-8")


def build_diagnostic_summary(
    run_id: str,
    request: Optional[Dict[str, Any]] = None,
    result: Optional[Any] = None,  # RunResult ou dict
    counters: Optional[PerfCounters] = None,
    last_exception: Optional[Exception] = None,
) -> DiagnosticPack:
    """
    Construit un pack diagnostic compact.

    Args:
        run_id: Identifiant du run
        request: Dict de la requête (strategy, params, etc.)
        result: Résultat du backtest (RunResult ou dict de metrics)
        counters: Compteurs de performance
        last_exception: Dernière exception si erreur

    Returns:
        DiagnosticPack prêt à exporter
    """
    request = request or {}

    # Extraire les infos du résultat
    result_summary = {}
    if result is not None:
        if hasattr(result, "metrics"):
            # RunResult
            metrics = result.metrics
            result_summary = {
                "sharpe_ratio": metrics.get("sharpe_ratio"),
                "total_return": metrics.get("total_return"),
                "max_drawdown": metrics.get("max_drawdown"),
                "total_trades": metrics.get("total_trades"),
                "win_rate": metrics.get("win_rate"),
            }
        elif isinstance(result, dict):
            result_summary = {
                k: result.get(k)
                for k in ["sharpe_ratio", "total_return", "max_drawdown", "total_trades"]
                if k in result
            }

    return DiagnosticPack(
        run_id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        strategy=request.get("strategy"),
        symbol=request.get("symbol"),
        timeframe=request.get("timeframe"),
        params=request.get("params", {}),
        counters=counters.summary() if counters else {},
        result_summary=result_summary,
        error=str(last_exception) if last_exception else None,
        error_type=type(last_exception).__name__ if last_exception else None,
    )


# ============================================================================
# CONFIGURATION DYNAMIQUE (UI toggle)
# ============================================================================

def set_log_level(level: str) -> None:
    """
    Change le niveau de log dynamiquement.

    Utilisé par le toggle UI pour activer DEBUG à la volée.
    Met à jour tous les loggers (backtest, backtest_core et leurs enfants).
    """
    log_level = _LEVEL_MAP.get(level.upper(), logging.INFO)

    # Mettre à jour le logger "backtest" et ses enfants
    root_logger = logging.getLogger("backtest")
    root_logger.setLevel(log_level)
    for handler in root_logger.handlers:
        handler.setLevel(log_level)

    # Mettre à jour aussi "backtest_core" utilisé par utils.log
    core_logger = logging.getLogger("backtest_core")
    core_logger.setLevel(log_level)
    for handler in core_logger.handlers:
        handler.setLevel(log_level)

    # Mettre à jour tous les loggers enfants existants
    for name, logger in logging.Logger.manager.loggerDict.items():
        if isinstance(logger, logging.Logger) and (
            name.startswith("backtest.") or name.startswith("backtest_core.")
        ):
            logger.setLevel(log_level)
            for handler in logger.handlers:
                handler.setLevel(log_level)


def set_sample_rate(rate: float) -> None:
    """Change le taux d'échantillonnage (0.0 à 1.0)."""
    global _LOG_SAMPLE
    _LOG_SAMPLE = max(0.0, min(1.0, rate))


def is_debug_enabled() -> bool:
    """Retourne True si DEBUG est activé."""
    # Vérifier les deux loggers racines
    backtest_debug = logging.getLogger("backtest").isEnabledFor(logging.DEBUG)
    core_debug = logging.getLogger("backtest_core").isEnabledFor(logging.DEBUG)
    return backtest_debug or core_debug


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Loggers
    "get_obs_logger",
    "init_logging",
    "generate_run_id",
    "ObsLoggerAdapter",
    # Spans
    "trace_span",
    # Stats sûres
    "safe_stats_df",
    "safe_stats_array",
    "safe_stats_series",
    # Compteurs
    "PerfCounters",
    # Diagnostic
    "DiagnosticPack",
    "build_diagnostic_summary",
    # Config dynamique
    "set_log_level",
    "set_sample_rate",
    "is_debug_enabled",
]
