"""
Module-ID: agents.strategy_builder

Purpose: Agent LLM capable de créer et itérer sur des stratégies de trading complètes
         en utilisant exclusivement les indicateurs du registry existant.

Role in pipeline: orchestration / génération de code

Key components: StrategyBuilder, BuilderSession, BuilderIteration

Inputs: Objectif textuel, DataFrame OHLCV, LLMClient/LLMConfig

Outputs: Stratégie générée dans sandbox_strategies/<session_id>/strategy.py,
         résultats de backtest par itération

Dependencies: agents.llm_client, agents.backtest_executor, agents.analyst,
              indicators.registry, strategies.base, backtest.engine, utils.template

Conventions: Code généré validé syntaxiquement avant exécution ; chargement dynamique
             via importlib ; nom de classe standardisé BuilderGeneratedStrategy ;
             isolation complète dans sandbox_strategies/.

Read-if: Ajout fonctionnalité au builder, modification boucle itérative, templates.

Skip-if: Vous utilisez uniquement les stratégies existantes ou l'AutonomousStrategist.
"""

from __future__ import annotations

import ast
import concurrent.futures
import csv
import hashlib
import importlib.util
import json
import math
import os
import pprint
import random
import re
import sys
import textwrap
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

import pandas as pd
import numpy as np
from agents.llm_client import LLMClient, LLMConfig, LLMMessage, create_llm_client
from agents.llm_router import LLMTopologyConfig, build_phase1_topology
from backtest.engine import BacktestEngine
from indicators.registry import calculate_indicator, list_indicators
from metrics_types import normalize_metrics
from utils.observability import generate_run_id, get_obs_logger
from utils.template import render_prompt

from agents.thought_stream import ThoughtStream

logger = get_obs_logger(__name__)

# Dossier racine des sandbox
SANDBOX_ROOT = Path(__file__).resolve().parent.parent / "sandbox_strategies"

# Nom de classe standardisé attendu dans le code généré
GENERATED_CLASS_NAME = "BuilderGeneratedStrategy"

# Nombre max d'échecs consécutifs avant arrêt (circuit breaker)
MAX_CONSECUTIVE_FAILURES = 3
# Nombre minimum de lignes pour considérer du code comme non-vide
MIN_CODE_LINES = 10
# Nombre max de tentatives de réalignement quand le LLM répond hors phase
MAX_PHASE_REALIGN_ATTEMPTS = 2
# Nombre mini d'itérations backtestées avant d'autoriser un arrêt LLM "stop"
MIN_SUCCESSFUL_ITERATIONS_BEFORE_STOP = 5
# Checkpoints de progression positive pour arrêter tôt les sessions peu prometteuses
POSITIVE_PROGRESS_GATE_CHECKPOINTS: Dict[int, int] = {6: 1, 9: 2}
MIN_TRADES_FOR_POSITIVE_PROGRESS = 1
# Quota max de fallbacks positifs comptabilisés dans la progression
MAX_POSITIVE_FALLBACK_COUNT = 1
# Nombre mini de trades pour accepter une stratégie en cours d'optimisation
MIN_TRADES_FOR_ACCEPT = 20
MAX_DRAWDOWN_PCT_FOR_ACCEPT = 35.0
MIN_RETURN_PCT_FOR_ACCEPT = 0.0
MIN_PROFIT_FACTOR_FOR_ACCEPT = 1.05
# Nombre max de fallbacks déterministes avant arrêt de la session
MAX_DETERMINISTIC_FALLBACKS = 4
MAX_SESSION_AUTO_RESETS = int(os.getenv("BACKTEST_BUILDER_MAX_SESSION_RESETS", "2"))
PROPOSAL_REALIGN_ATTEMPTS = 1
MIN_BUILDER_BARS = 300
MIN_SIGNAL_COUNT_FOR_DENSITY_PRECHECK = int(
    os.getenv("BACKTEST_BUILDER_MIN_SIGNAL_COUNT_FOR_DENSITY_PRECHECK", "200")
)
MAX_SIGNAL_DENSITY_PRECHECK = float(
    os.getenv("BACKTEST_BUILDER_MAX_SIGNAL_DENSITY_PRECHECK", "0.85")
)
MAX_REPEATED_SAME_SIGNAL_RATIO_PRECHECK = float(
    os.getenv(
        "BACKTEST_BUILDER_MAX_REPEATED_SAME_SIGNAL_RATIO_PRECHECK",
        "0.80",
    )
)

# Per-phase LLM call timeouts (seconds).
# Prevents single outlier calls (e.g. 8-minute code generation) from
# blocking the entire session. Env-overridable.
_LLM_PHASE_TIMEOUT_PROPOSAL = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_PROPOSAL", "120"))
_LLM_PHASE_TIMEOUT_CODE = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_CODE", "180"))
_LLM_PHASE_TIMEOUT_ANALYSIS = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_ANALYSIS", "90"))
_LLM_PHASE_TIMEOUT_DEFAULT = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_DEFAULT", "120"))

_LLM_PHASE_TIMEOUTS: Dict[str, int] = {
    "proposal": _LLM_PHASE_TIMEOUT_PROPOSAL,
    "code": _LLM_PHASE_TIMEOUT_CODE,
    "analysis": _LLM_PHASE_TIMEOUT_ANALYSIS,
    "pre": _LLM_PHASE_TIMEOUT_ANALYSIS,  # pre_reflection — same budget as analysis
}

# Mode safe-path JSON+DSL (off|prefer|strict)
SAFE_PATH_MODE_ENV = "BACKTEST_BUILDER_SAFE_PATH"

# Codes d'erreur stables
ERR_CLASS = "CLASS001"
ERR_AST = "AST001"
ERR_IND = "IND001"
ERR_SIG = "SIG001"
ERR_WARM = "WARM001"
ERR_PARAM = "PARAM001"
ERR_JSON = "JSON001"
ERR_DSL = "DSL001"
ERR_SANDBOX = "SANDBOX001"

_DICT_INDICATOR_NAMES = {
    "bollinger",
    "macd",
    "stochastic",
    "adx",
    "supertrend",
    "ichimoku",
    "psar",
    "vortex",
    "stoch_rsi",
    "aroon",
    "donchian",
    "keltner",
    "pivot_points",
    "fibonacci",
    "fibonacci_levels",
}

_DICT_INDICATOR_ALLOWED_KEYS: Dict[str, set[str]] = {
    "bollinger": {"upper", "middle", "lower"},
    "macd": {"macd", "signal", "histogram"},
    "stochastic": {"stoch_k", "stoch_d"},
    "adx": {"adx", "plus_di", "minus_di"},
    "supertrend": {"supertrend", "direction"},
    "ichimoku": {"tenkan", "kijun", "senkou_a", "senkou_b", "chikou", "cloud_position"},
    "psar": {"sar", "trend", "signal"},
    "vortex": {"vi_plus", "vi_minus", "signal", "oscillator"},
    "stoch_rsi": {"k", "d", "signal"},
    "aroon": {"aroon_up", "aroon_down"},
    "donchian": {"upper", "middle", "lower"},
    "keltner": {"middle", "upper", "lower"},
    "pivot_points": {"pivot", "r1", "s1", "r2", "s2", "r3", "s3"},
    # fibonacci_levels expose aussi des clés dynamiques de type level_XXX.
    "fibonacci_levels": {"high", "low"},
}

_INDICATOR_ALIAS_HINTS = {
    # Bollinger
    "bollinger_upper": "indicators['bollinger']['upper']",
    "bollinger_middle": "indicators['bollinger']['middle']",
    "bollinger_lower": "indicators['bollinger']['lower']",
    "bb_upper": "indicators['bollinger']['upper']",
    "bb_middle": "indicators['bollinger']['middle']",
    "bb_lower": "indicators['bollinger']['lower']",
    "bb_mid": "indicators['bollinger']['middle']",
    "bb_std": "indicators['bollinger']['upper']",
    # MACD
    "macd_line": "indicators['macd']['macd']",
    "macd_signal": "indicators['macd']['signal']",
    "macd_histogram": "indicators['macd']['histogram']",
    # Keltner
    "keltner_upper": "indicators['keltner']['upper']",
    "keltner_middle": "indicators['keltner']['middle']",
    "keltner_lower": "indicators['keltner']['lower']",
    "kelt_upper": "indicators['keltner']['upper']",
    "kelt_middle": "indicators['keltner']['middle']",
    "kelt_lower": "indicators['keltner']['lower']",
    # Donchian
    "donchian_upper": "indicators['donchian']['upper']",
    "donchian_middle": "indicators['donchian']['middle']",
    "donchian_lower": "indicators['donchian']['lower']",
    "dc_upper": "indicators['donchian']['upper']",
    "dc_middle": "indicators['donchian']['middle']",
    "dc_lower": "indicators['donchian']['lower']",
    # CCI (plain array — common wrong patterns)
    "cci_value": "indicators['cci']",
    "cci_values": "indicators['cci']",
    # Ichimoku
    "ichimoku_tenkan": "indicators['ichimoku']['tenkan']",
    "ichimoku_kijun": "indicators['ichimoku']['kijun']",
    "ichimoku_senkou_a": "indicators['ichimoku']['senkou_a']",
    "ichimoku_senkou_b": "indicators['ichimoku']['senkou_b']",
    "ichimoku_chikou": "indicators['ichimoku']['chikou']",
    "ichimoku_cloud": "indicators['ichimoku']['cloud_position']",
    # PSAR
    "psar_sar": "indicators['psar']['sar']",
    "psar_trend": "indicators['psar']['trend']",
    "psar_signal": "indicators['psar']['signal']",
    "parabolic_sar": "indicators['psar']['sar']",
    # Vortex
    "vortex_vi_plus": "indicators['vortex']['vi_plus']",
    "vortex_vi_minus": "indicators['vortex']['vi_minus']",
    "vortex_signal": "indicators['vortex']['signal']",
    "vortex_oscillator": "indicators['vortex']['oscillator']",
    "vi_plus": "indicators['vortex']['vi_plus']",
    "vi_minus": "indicators['vortex']['vi_minus']",
    # Aroon
    "aroon_up": "indicators['aroon']['aroon_up']",
    "aroon_down": "indicators['aroon']['aroon_down']",
    "aroon_upper": "indicators['aroon']['aroon_up']",
    "aroon_lower": "indicators['aroon']['aroon_down']",
    # Pivot Points
    "pivot_points_pivot": "indicators['pivot_points']['pivot']",
    "pivot_points_r1": "indicators['pivot_points']['r1']",
    "pivot_points_s1": "indicators['pivot_points']['s1']",
    "pivot_points_r2": "indicators['pivot_points']['r2']",
    "pivot_points_s2": "indicators['pivot_points']['s2']",
    "pivot_points_r3": "indicators['pivot_points']['r3']",
    "pivot_points_s3": "indicators['pivot_points']['s3']",
    # ADX
    "adx_value": "indicators['adx']['adx']",
    "plus_di": "indicators['adx']['plus_di']",
    "minus_di": "indicators['adx']['minus_di']",
    # Supertrend
    "supertrend_value": "indicators['supertrend']['supertrend']",
    "supertrend_direction": "indicators['supertrend']['direction']",
    # Stochastic
    "stoch_k": "indicators['stochastic']['stoch_k']",
    "stoch_d": "indicators['stochastic']['stoch_d']",
    # Stoch RSI
    "stoch_rsi_k": "indicators['stoch_rsi']['k']",
    "stoch_rsi_d": "indicators['stoch_rsi']['d']",
    "stoch_rsi_signal": "indicators['stoch_rsi']['signal']",
    "srsi_k": "indicators['stoch_rsi']['k']",
    "srsi_d": "indicators['stoch_rsi']['d']",
    # Fibonacci levels
    "fibonacci_levels_high": "indicators['fibonacci_levels']['high']",
    "fibonacci_levels_low": "indicators['fibonacci_levels']['low']",
}

_PROPOSAL_PLACEHOLDER_VALUES = {
    "",
    "-",
    "—",
    "n/a",
    "na",
    "none",
    "null",
    "brief description",
    "what you expect this change to achieve and why",
    "when to buy",
    "when to sell",
    "when to close",
}

_BUILDER_PROPOSAL_REQUIRED_KEYS = {
    "strategy_name",
    "used_indicators",
    "entry_long_logic",
    "exit_logic",
    "risk_management",
    "default_params",
    "parameter_specs",
}

_BUILDER_ALLOWED_WRITE_DF_COLUMNS = {
    "bb_stop_long",
    "bb_tp_long",
    "bb_stop_short",
    "bb_tp_short",
    "sl_level",
    "tp_level",
}

_LOG_PREFIX_RE = re.compile(r"^\s*\d{2}:\d{2}:\d{2}\s*\|\s*\w+\s*\|", re.IGNORECASE)
_PIPE_LOG_PREFIX_RE = re.compile(
    r"^\s*\|\s*(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*\|",
    re.IGNORECASE,
)
_TRACEBACK_LINE_RE = re.compile(r'^\s*File\s+"[^"]+",\s*line\s+\d+', re.IGNORECASE)
_WINDOWS_PATH_LINE_RE = re.compile(r"^\s*[A-Za-z]:\\")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BuilderIteration:
    """Résultat d'une itération du builder."""

    iteration: int
    hypothesis: str = ""
    code: str = ""
    backtest_result: Optional[Any] = None
    error: Optional[str] = None
    analysis: str = ""
    decision: str = ""  # "continue", "accept", "stop"
    change_type: str = ""  # "logic", "params", "both"
    diagnostic_category: str = ""  # computed by compute_diagnostic()
    diagnostic_detail: Dict[str, Any] = field(default_factory=dict)
    phase_feedback: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    is_fallback: bool = False  # True if deterministic fallback was used


@dataclass
class BuilderSession:
    """Session complète de construction de stratégie."""

    session_id: str
    objective: str
    session_dir: Path
    available_indicators: List[str] = field(default_factory=list)

    # État
    iterations: List[BuilderIteration] = field(default_factory=list)
    best_iteration: Optional[BuilderIteration] = None
    best_sharpe: float = float("-inf")
    best_score: float = float("-inf")
    status: str = "running"  # "running", "success", "failed", "max_iterations"
    auto_reset_count: int = 0
    recovery_events: List[Dict[str, Any]] = field(default_factory=list)

    # Configuration
    max_iterations: int = 10
    target_sharpe: float = 1.0
    start_time: datetime = field(default_factory=datetime.now)

    # Contexte de marché (transmis au LLM)
    symbol: str = "UNKNOWN"
    timeframe: str = "1h"
    n_bars: int = 0
    date_range_start: str = ""
    date_range_end: str = ""
    fees_bps: float = 10.0
    slippage_bps: float = 5.0
    initial_capital: float = 10000.0
    direction_constraint: str = "long_short"


def _iteration_is_recovery_anchor(
    iteration: Optional[BuilderIteration],
    *,
    allow_fallback: bool = False,
) -> bool:
    """Retourne True si l'itération peut servir de point de reprise."""
    if iteration is None:
        return False
    if iteration.error is not None:
        return False
    if iteration.backtest_result is None:
        return False
    if iteration.is_fallback and not allow_fallback:
        return False
    return True


def _select_session_recovery_anchor(
    session: BuilderSession,
    last_iteration: Optional[BuilderIteration] = None,
) -> tuple[Optional[BuilderIteration], str]:
    """Choisit le meilleur ancrage disponible pour un auto-reset de session."""
    if _iteration_is_recovery_anchor(session.best_iteration):
        return session.best_iteration, "best_iteration"

    if _iteration_is_recovery_anchor(last_iteration):
        return last_iteration, "last_iteration"

    for candidate in reversed(session.iterations):
        if _iteration_is_recovery_anchor(candidate):
            return candidate, "history_non_fallback"

    if _iteration_is_recovery_anchor(last_iteration, allow_fallback=True):
        return last_iteration, "last_iteration_fallback"

    for candidate in reversed(session.iterations):
        if _iteration_is_recovery_anchor(candidate, allow_fallback=True):
            return candidate, "history_fallback"

    return None, "none"


def _err(code: str, message: str) -> str:
    """Formate un message d'erreur avec code stable."""
    return f"[{code}] {message}"


def _safe_path_mode() -> str:
    """Retourne le mode safe-path normalisé: off|prefer|strict."""
    raw = os.getenv(SAFE_PATH_MODE_ENV, "off").strip().lower()
    if raw in {"prefer", "strict", "off"}:
        return raw
    if raw in {"1", "true", "yes", "on"}:
        return "prefer"
    return "off"


def _is_allowed_import(module_name: str) -> bool:
    """Allowlist stricte des imports dans le code généré."""
    root = (module_name or "").split(".")[0]
    return root in {"typing", "numpy", "pandas", "strategies", "utils"}


def _strict_sandbox_enabled() -> bool:
    """Active/désactive la sandbox runtime stricte."""
    raw = os.getenv("BACKTEST_BUILDER_STRICT_SANDBOX", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _sandbox_safe_builtins() -> Dict[str, Any]:
    """Construit un set minimal de builtins autorisés dans la sandbox."""
    return {
        "__build_class__": __build_class__,
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "Exception": Exception,
        "dict": dict,
        "enumerate": enumerate,
        "float": float,
        "int": int,
        "object": object,
        "len": len,
        "list": list,
        "max": max,
        "min": min,
        "pow": pow,
        "property": property,
        "range": range,
        "set": set,
        "staticmethod": staticmethod,
        "super": super,
        "sum": sum,
        "tuple": tuple,
        "type": type,
        "zip": zip,
        "isinstance": isinstance,
    }


def _sandbox_import(name: str, global_ns=None, local_ns=None, fromlist=(), level=0):
    """Import guard pour sandbox runtime."""
    if not _is_allowed_import(name):
        raise ImportError(_err(ERR_SANDBOX, f"Import runtime interdit: '{name}'"))
    return __import__(name, global_ns, local_ns, fromlist, level)


def _validate_signal_loop_and_warmup(tree: ast.AST) -> tuple[bool, str]:
    """Valide des patterns signaux/warmup dangereux.

    - Interdit les boucles indexées qui écrivent `signals.iloc[i]`
    - Interdit warmup destructif (`signals.iloc[x:] = 0`, `signals[:] = 0`)
    """
    for fn in _iter_generate_signals_functions(tree):
        for node in ast.walk(fn):
            if isinstance(node, ast.For):
                if (
                    isinstance(node.target, ast.Name)
                    and isinstance(node.iter, ast.Call)
                    and isinstance(node.iter.func, ast.Name)
                    and node.iter.func.id == "range"
                ):
                    return False, _err(
                        ERR_SIG,
                        "Boucle `for i in range(...)` interdite dans generate_signals. "
                        "Utiliser une logique vectorisée.",
                    )
                for sub in ast.walk(node):
                    if not isinstance(sub, ast.Subscript):
                        continue
                    # signals.iloc[i] = ...
                    if (
                        isinstance(sub.value, ast.Attribute)
                        and sub.value.attr == "iloc"
                        and isinstance(sub.value.value, ast.Name)
                        and sub.value.value.id == "signals"
                    ):
                        return False, _err(
                            ERR_SIG,
                            "Boucle indexée avec `signals.iloc[i]` interdite. "
                            "Utiliser des masques vectorisés.",
                        )

            # Warmup checks sur assignations
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for tgt in targets:
                    if not isinstance(tgt, ast.Subscript):
                        continue

                    # Pattern signals[...] ou signals.iloc[...]
                    is_signals_sub = (
                        isinstance(tgt.value, ast.Name) and tgt.value.id == "signals"
                    )
                    is_signals_iloc_sub = (
                        isinstance(tgt.value, ast.Attribute)
                        and tgt.value.attr == "iloc"
                        and isinstance(tgt.value.value, ast.Name)
                        and tgt.value.value.id == "signals"
                    )
                    if not (is_signals_sub or is_signals_iloc_sub):
                        continue

                    sl = tgt.slice
                    if isinstance(sl, ast.Slice):
                        lower = _const_value(sl.lower) if sl.lower is not None else None
                        upper = _const_value(sl.upper) if sl.upper is not None else None
                        # Autorisé: [:N] = 0 (warmup préfixe), N constant ou variable
                        if lower is None and sl.upper is not None:
                            continue
                        # Interdit: [N:] / [:] / [N:M]
                        return False, _err(
                            ERR_WARM,
                            "Warmup invalide: seule la forme `signals.iloc[:N] = 0.0` "
                            "(ou `signals[:N] = 0.0`) est autorisée.",
                        )

            if isinstance(node, ast.While):
                return False, _err(
                    ERR_SIG,
                    "Boucle `while` interdite dans generate_signals. "
                    "Utiliser une logique vectorisée.",
                )

    return True, ""


# ---------------------------------------------------------------------------
# Validation du code généré
# ---------------------------------------------------------------------------

def validate_generated_code(code: str) -> tuple[bool, str]:
    """
    Valide le code Python généré avant écriture/exécution.

    Vérifie :
    1. Syntaxe Python valide (ast.parse)
    2. Présence de la classe BuilderGeneratedStrategy
    3. Présence de generate_signals
    4. Absence d'imports dangereux (os.system, subprocess, eval, exec)

    Returns:
        (is_valid, error_message)
    """
    # 1. Syntaxe
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, _err(ERR_AST, f"Erreur de syntaxe ligne {e.lineno}: {e.msg}")

    # 1b. Sécurité sandbox prioritaire
    dangerous_patterns = [
        "os.system", "subprocess", "eval(", "exec(",
        "__import__", "shutil.rmtree", "open(",
    ]
    code_lower = code.lower()
    for pattern in dangerous_patterns:
        if pattern.lower() in code_lower:
            return False, _err(ERR_SANDBOX, f"Import/appel dangereux détecté: '{pattern}'")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _is_allowed_import(alias.name):
                    return False, _err(
                        ERR_SANDBOX,
                        f"Import interdit en sandbox: '{alias.name}'.",
                    )
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if not _is_allowed_import(mod):
                return False, _err(
                    ERR_SANDBOX,
                    f"Import interdit en sandbox: 'from {mod} import ...'.",
                )

    # 2. Vérifier la classe attendue
    class_names = [
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    ]
    if GENERATED_CLASS_NAME not in class_names:
        return False, _err(
            ERR_CLASS,
            f"Classe '{GENERATED_CLASS_NAME}' absente. Classes trouvées: {class_names}",
        )

    # 3. Vérifier generate_signals (dans la classe attendue)
    generate_fns = _iter_generate_signals_functions(tree)
    if not generate_fns:
        return False, _err(ERR_CLASS, "Méthode 'generate_signals' absente.")

    # 3a. Héritage strict StrategyBase (après vérif structure minimale)
    class_node = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == GENERATED_CLASS_NAME
        ),
        None,
    )
    if class_node is not None:
        base_names = {
            getattr(base, "id", None)
            for base in class_node.bases
            if isinstance(base, ast.Name)
        }
        base_names.update(
            getattr(base, "attr", None)
            for base in class_node.bases
            if isinstance(base, ast.Attribute)
        )
        if "StrategyBase" not in base_names:
            return False, _err(
                ERR_CLASS,
                "La classe générée doit hériter explicitement de StrategyBase.",
            )

    # 3b. Signature minimale (évite TypeError runtime)
    fn = generate_fns[0]
    if len(fn.args.args) < 4 and fn.args.vararg is None:
        return (
            False,
            _err(
                ERR_CLASS,
                "Signature invalide: generate_signals doit accepter "
                "(self, df, indicators, params).",
            ),
        )

    # 3c. default_params doit retourner un dict concret (pas une variable globale implicite)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != GENERATED_CLASS_NAME:
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name != "default_params":
                continue
            arg_names = {a.arg for a in item.args.args}
            arg_names.update(a.arg for a in item.args.kwonlyargs)
            _, store_names = _collect_name_load_store_sets(item)
            for sub in ast.walk(item):
                if not isinstance(sub, ast.Return):
                    continue
                if isinstance(sub.value, ast.Name):
                    name_id = sub.value.id
                    if name_id not in arg_names and name_id not in store_names:
                        return (
                            False,
                            _err(
                                ERR_PARAM,
                                "default_params invalide: `return "
                                f"{name_id}` référence un nom non défini. "
                                "Retourner un dict explicite (ex: {'leverage': 1, ...}) "
                                "ou un attribut `self.<...>`."
                            ),
                        )
        break

    # 3d. NameError probable: variables coeur utilisées sans définition
    #     (fréquent quand le LLM renomme l'argument `df` mais garde `df[...]` dans le corps)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != GENERATED_CLASS_NAME:
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            arg_names = {a.arg for a in item.args.args}
            arg_names.update(a.arg for a in item.args.kwonlyargs)
            load_names, store_names = _collect_name_load_store_sets(item)
            core_names = ("df", "indicators", "params")
            if item.name == "generate_signals":
                core_names = ("df", "indicators", "params", "warmup")
            for core in core_names:
                if core in load_names and core not in arg_names and core not in store_names:
                    return (
                        False,
                        _err(
                            ERR_CLASS,
                            f"NameError probable: `{core}` utilisé dans `{item.name}` "
                            "mais non défini (paramètre manquant ou variable non assignée).",
                        ),
                    )
        break

    # 3f. Verrouillage required_indicators: lecture seule (pas d'assignation)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and target.attr == "required_indicators"
            ):
                return False, _err(
                    ERR_CLASS,
                    "required_indicators est en lecture seule: assignation interdite.",
                )

    # 3f-bis. Éviter l'écrasement des aliases d'import numpy/pandas.
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != GENERATED_CLASS_NAME:
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(item):
                if isinstance(sub, ast.Assign):
                    targets = sub.targets
                elif isinstance(sub, ast.AnnAssign):
                    targets = [sub.target]
                elif isinstance(sub, ast.AugAssign):
                    targets = [sub.target]
                else:
                    continue
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {"np", "pd"}:
                        return False, _err(
                            ERR_CLASS,
                            f"Alias réservé `{target.id}` écrasé dans `{item.name}`. "
                            f"Ne jamais réassigner `{target.id}`.",
                        )
        break

    # 3g. Écriture df limitée aux colonnes SL/TP autorisées
    ohlcv_cols = {"open", "high", "low", "close", "volume"}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            continue
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign):
            targets = [node.target]
        else:
            targets = [node.target]
        for target in targets:
            if not isinstance(target, ast.Subscript):
                continue
            is_df = isinstance(target.value, ast.Name) and target.value.id == "df"
            is_df_loc = (
                isinstance(target.value, ast.Attribute)
                and target.value.attr == "loc"
                and isinstance(target.value.value, ast.Name)
                and target.value.value.id == "df"
            )
            if not (is_df or is_df_loc):
                continue
            col = _const_value(target.slice)
            if col is None and is_df_loc and isinstance(target.slice, ast.Tuple):
                items = list(target.slice.elts)
                if len(items) >= 2:
                    col = _const_value(items[1])
            if not isinstance(col, str):
                continue
            low = col.lower()
            if low in ohlcv_cols:
                return False, _err(
                    ERR_IND,
                    f"Écriture interdite dans df['{col}'] (OHLCV read-only).",
                )
            if col not in _BUILDER_ALLOWED_WRITE_DF_COLUMNS:
                hint = ""
                if "signal" in col.lower():
                    hint = " Use the `signals` variable instead of df columns for signal values."
                return False, _err(
                    ERR_IND,
                    f"Écriture df['{col}'] non autorisée. Colonnes autorisées: "
                    f"{', '.join(sorted(_BUILDER_ALLOWED_WRITE_DF_COLUMNS))}."
                    f"{hint}",
                )

    # 3e. Interdictions structurées signaux/warmup
    flow_ok, flow_err = _validate_signal_loop_and_warmup(tree)
    if not flow_ok:
        return False, flow_err

    # 4. Imports dangereux
    # 5. Accès invalide aux indicateurs via df[...] au lieu de indicators[...]
    try:
        known_indicators = {ind.lower() for ind in list_indicators()}
    except Exception:
        known_indicators = set()

    # 5b. Indicateurs inconnus via indicators[...] / indicators.get(...)
    used_indicators = _collect_indicator_names(tree) | _collect_indicator_names_in_class(tree)
    if known_indicators and used_indicators:
        unknown = sorted(
            {
                name for name in used_indicators
                if name.lower() not in known_indicators
            }
        )
        if unknown:
            ohlcv_and_runtime_cols = {
                "open", "high", "low", "close", "volume",
                *_BUILDER_ALLOWED_WRITE_DF_COLUMNS,
            }
            wrong_df_cols = [name for name in unknown if name.lower() in ohlcv_and_runtime_cols]
            if wrong_df_cols:
                return (
                    False,
                    _err(
                        ERR_IND,
                        "Colonnes de prix/runtime utilisées via `indicators[...]`: "
                        f"{wrong_df_cols}. Utiliser `df['colonne']` pour OHLCV/SL-TP.",
                    ),
                )
            hints = [
                f"{name} -> {_INDICATOR_ALIAS_HINTS[name.lower()]}"
                for name in unknown
                if name.lower() in _INDICATOR_ALIAS_HINTS
            ]
            hint_suffix = (
                f" Corrections possibles: {', '.join(hints)}."
                if hints
                else ""
            )
            return (
                False,
                "Indicateur(s) inconnu(s) via indicators détecté(s): "
                f"{unknown}. Utiliser uniquement les noms du registre."
                f"{hint_suffix}",
            )

    df_indexed = re.findall(r"df\s*\[\s*['\"]([^'\"]+)['\"]\s*\]", code)
    bad_df_cols = sorted(
        {col for col in df_indexed if col.lower() in known_indicators}
    )
    if bad_df_cols:
        return (
            False,
            _err(
                ERR_IND,
                "Accès indicateur invalide via df[...] détecté: "
                f"{bad_df_cols}. Utiliser indicators['name'].",
            ),
        )

    # 6. Mauvais usage de np.nan_to_num sur indicateurs dict (bollinger, macd, ...)
    for ind in _DICT_INDICATOR_NAMES:
        bad_pattern = (
            r"np\.nan_to_num\(\s*indicators\s*\[\s*['\"]"
            + re.escape(ind)
            + r"['\"]\s*\]\s*\)"
        )
        if re.search(bad_pattern, code):
            return (
                False,
                _err(
                    ERR_IND,
                    f"Usage invalide: np.nan_to_num(indicators['{ind}']) (dict). "
                    "Appliquer np.nan_to_num sur ses sous-clés.",
                ),
            )

    # 7. Validation sémantique AST (usage indicateurs/arrays)
    semantics_ok, semantics_err = _validate_indicator_usage_semantics(code)
    if not semantics_ok:
        return False, _err(ERR_IND, semantics_err)

    # 8. Validation légère ParameterSpec: rejeter aliases/typos source de dérive
    forbidden_paramspec_keys = (
        "min_value=",
        "max_value=",
        "minimum=",
        "maximum=",
        "paramtype=",
    )
    for key in forbidden_paramspec_keys:
        if key in code_lower:
            return False, _err(
                ERR_PARAM,
                "ParameterSpec invalide: utiliser min_val/max_val/param_type/step.",
            )

    return True, ""


def sanitize_objective_text(objective: Any) -> str:
    """Nettoie un objectif utilisateur et retire les contaminations de logs.

    Cas traités:
    - Collage accidentel de logs complets (INFO/WARNING/Traceback)
    - Objectif imbriqué dans une ligne de log `... objective='...' indicators=...`
    - Bruit visuel (lignes de séparation terminal)
    """
    text = str(objective or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""

    # Nettoyage résidus modèles de raisonnement
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL).strip()

    # Si un objectif est imbriqué dans des logs, récupérer la dernière occurrence
    lower = text.lower()
    marker = "objective='"
    last_idx = lower.rfind(marker)
    if last_idx >= 0:
        start = last_idx + len(marker)
        end = lower.find("' indicators=", start)
        if end == -1:
            end = lower.find("'\n", start)
        if end == -1:
            end = lower.find("'", start)
        if end > start:
            embedded = text[start:end].strip()
            if len(embedded) >= 20:
                text = embedded

    cleaned_lines: List[str] = []
    in_traceback_block = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue

        lower_line = line.lower()
        if "traceback (most recent call last)" in lower_line:
            in_traceback_block = True
            continue
        if in_traceback_block:
            continue

        if _LOG_PREFIX_RE.match(line):
            continue
        if _PIPE_LOG_PREFIX_RE.match(line):
            continue
        if lower_line.startswith("traceback"):
            continue
        if lower_line.startswith("during handling of the above exception"):
            continue
        if _TRACEBACK_LINE_RE.match(line):
            continue
        if _WINDOWS_PATH_LINE_RE.match(line):
            continue
        if line.startswith("PS "):
            continue
        if line.startswith("❱"):
            continue
        if re.match(r"^\d+\s*$", line):
            continue
        if "streamlitapiexception" in lower_line:
            continue
        if "site-packages\\streamlit" in lower_line:
            continue
        if lower_line.startswith("files\\python"):
            continue
        if re.match(r"^[═━\-]{10,}$", line):
            continue
        if re.match(r"^\^+$", line):
            continue

        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip("`'\" \n\t")
    if len(cleaned) > 4000:
        cleaned = cleaned[:4000].rstrip()
    return cleaned


def _normalize_llm_text(value: Any, *, fallback: str = "", max_len: int = 1200) -> str:
    """Normalise un payload LLM potentiellement structuré en texte affichable."""
    text = ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list, tuple, set)):
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except Exception:
            text = str(value)
    elif value is None:
        text = ""
    else:
        text = str(value)

    text = text.strip()
    if not text:
        text = str(fallback or "").strip()
    if not text:
        return ""
    if len(text) > max_len:
        text = text[:max_len].rstrip()
    return text


def _looks_like_log_pollution(text: str) -> bool:
    """Heuristique simple pour détecter un collage de logs/traceback."""
    if not text:
        return False
    lower = text.lower()
    if "traceback (most recent call last)" in lower:
        return True
    if "streamlitapiexception" in lower:
        return True
    if re.search(r"^\s*\d{2}:\d{2}:\d{2}\s*\|\s*\w+\s*\|", text, re.MULTILINE):
        return True
    if re.search(
        r"^\s*\|\s*(debug|info|warning|error|critical)\s*\|",
        text,
        re.MULTILINE | re.IGNORECASE,
    ):
        return True
    return False


def _safe_format_exception(exc: BaseException) -> str:
    """
    Formate une exception sans passer par traceback.format_exc/format_exception.

    Évite les crashs secondaires Python 3.12 quand le moteur de suggestion
    d'erreur évalue des propriétés qui relèvent elles-mêmes des exceptions.
    """
    try:
        tb = exc.__traceback__
    except Exception:
        tb = None

    lines: List[str] = []
    if tb is not None:
        try:
            for frame in traceback.extract_tb(tb):
                code_line = (frame.line or "").strip()
                lines.append(
                    f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}'
                )
                if code_line:
                    lines.append(f"    {code_line}")
        except Exception:
            lines = []

    header = f"{type(exc).__name__}: {exc}"
    if lines:
        return (
            "Traceback (most recent call last):\n"
            + "\n".join(lines)
            + f"\n{header}"
        )
    return header


def _metric_float(metrics: Dict[str, Any], key: str, default: float = 0.0) -> float:
    """Lecture float robuste d'une métrique sans écraser les zéros valides."""
    value = metrics.get(key, default)
    if value is None:
        return float(default)
    try:
        return float(value)
    except Exception:
        return float(default)


def _infer_direction_constraint_from_objective(objective: Any) -> str:
    """Déduit une contrainte long-only / short-only depuis l'objectif texte."""
    normalized = " ".join(str(objective or "").strip().lower().split())
    if not normalized:
        return "long_short"

    long_only_markers = (
        "only execute buy orders",
        "only execute buy order",
        "only buy orders",
        "buy signals",
        "buy-only",
        "long only",
        "long-only",
        "only execute long orders",
        "only execute long positions",
        "only take long trades",
        "uniquement des achats",
        "achat seulement",
        "long seulement",
    )
    short_only_markers = (
        "only execute sell orders",
        "only execute sell order",
        "only sell orders",
        "sell signals",
        "sell-only",
        "short only",
        "short-only",
        "only execute short orders",
        "only execute short positions",
        "only take short trades",
        "uniquement des ventes",
        "vente seulement",
        "short seulement",
    )

    long_only = any(marker in normalized for marker in long_only_markers)
    short_only = any(marker in normalized for marker in short_only_markers)

    if long_only and not short_only:
        return "long_only"
    if short_only and not long_only:
        return "short_only"
    return "long_short"


def _apply_signal_direction_constraint(
    signals: pd.Series,
    direction_constraint: str,
) -> pd.Series:
    """Neutralise le côté interdit pour les objectifs long-only / short-only."""
    direction = str(direction_constraint or "long_short").strip().lower()
    if direction not in {"long_only", "short_only"}:
        return signals

    constrained = signals.copy()
    values = constrained.to_numpy(copy=True)
    if direction == "long_only":
        values = np.where(values < 0.0, 0.0, values)
    else:
        values = np.where(values > 0.0, 0.0, values)
    return pd.Series(values, index=constrained.index, dtype=np.float64)


def _is_ruined_metrics(metrics: Dict[str, Any]) -> bool:
    """Détecte une configuration ruinée à partir des métriques de backtest."""
    ret = _metric_float(metrics, "total_return_pct", 0.0)
    max_dd = abs(_metric_float(metrics, "max_drawdown_pct", 0.0))
    account_ruined = bool(metrics.get("account_ruined", False))
    return account_ruined or ret <= -90.0 or max_dd >= 90.0


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def compute_continuous_builder_score(
    metrics: Dict[str, Any],
    *,
    target_sharpe: float = 1.0,
) -> Dict[str, Any]:
    """Score continu de qualité stratégie (sans seuil binaire brutal)."""
    sharpe = _metric_float(metrics, "sharpe_ratio", 0.0)
    ret = _metric_float(metrics, "total_return_pct", 0.0)
    max_dd = abs(_metric_float(metrics, "max_drawdown_pct", 0.0))
    profit_factor = _metric_float(metrics, "profit_factor", 1.0)
    trades = int(metrics.get("total_trades", 0) or 0)
    win_rate = _metric_float(metrics, "win_rate_pct", 35.0)
    ruined = _is_ruined_metrics(metrics)

    target = max(float(target_sharpe or 1.0), 0.5)

    components = {
        "sharpe": _clamp(sharpe / target, -1.5, 2.0) * 28.0,
        "return": _clamp(ret / 20.0, -1.5, 2.0) * 22.0,
        "profit_factor": _clamp((profit_factor - 1.0) / 0.35, -1.5, 2.0) * 16.0,
        "trades_confidence": _clamp(trades / 60.0, 0.0, 1.0) * 10.0,
        "win_rate": _clamp((win_rate - 35.0) / 20.0, -1.0, 1.5) * 6.0,
    }

    drawdown_excess_pct = max(0.0, max_dd - MAX_DRAWDOWN_PCT_FOR_ACCEPT)
    penalties = {
        "drawdown_pressure": _clamp((max_dd - 20.0) / 30.0, 0.0, 2.0) * 20.0,
        "drawdown_excess": _clamp(drawdown_excess_pct / 12.0, 0.0, 2.0) * 10.0,
        "insufficient_trades": 8.0 if trades < MIN_TRADES_FOR_ACCEPT else 0.0,
        "non_positive_return": 12.0 if ret <= 0.0 else 0.0,
        "ruined": 80.0 if ruined else 0.0,
    }

    raw_total = float(sum(components.values()) - sum(penalties.values()))
    score = _clamp(raw_total, -100.0, 100.0)

    return {
        "score": score,
        "components": components,
        "penalties": penalties,
        "drawdown_excess_pct": drawdown_excess_pct,
        "ruined": ruined,
    }


def _ranking_sharpe(
    metrics: Dict[str, Any],
    *,
    target_sharpe: float = 1.0,
) -> float:
    """Score de ranking continu (historique conservé pour compatibilité de nom)."""
    return float(
        compute_continuous_builder_score(
            metrics,
            target_sharpe=target_sharpe,
        ).get("score", -100.0)
    )


def _metrics_fingerprint(metrics: Dict[str, Any]) -> str:
    """Retourne un fingerprint stable des métriques clés pour détecter la stagnation."""
    keys = ("total_return_pct", "max_drawdown_pct", "total_trades", "win_rate_pct", "profit_factor")
    parts = []
    for k in keys:
        v = metrics.get(k, 0) or 0
        parts.append(f"{k}={float(v):.4f}")
    return "|".join(parts)


def _is_accept_candidate(
    metrics: Dict[str, Any],
    *,
    target_sharpe: float,
) -> tuple[bool, str]:
    """Vérifie si une itération est suffisamment robuste pour terminer en succès."""
    sharpe = _metric_float(metrics, "sharpe_ratio", 0.0)
    trades = int(metrics.get("total_trades", 0) or 0)
    ret = _metric_float(metrics, "total_return_pct", 0.0)
    max_dd = abs(_metric_float(metrics, "max_drawdown_pct", 0.0))
    profit_factor = _metric_float(metrics, "profit_factor", MIN_PROFIT_FACTOR_FOR_ACCEPT)
    score_payload = compute_continuous_builder_score(
        metrics,
        target_sharpe=target_sharpe,
    )
    quality_score = float(score_payload.get("score", -100.0))

    if _is_ruined_metrics(metrics):
        return False, "ruined_metrics"
    if trades < MIN_TRADES_FOR_ACCEPT:
        return False, "insufficient_trades"
    if sharpe < target_sharpe:
        return False, "target_sharpe_not_reached"
    if ret <= MIN_RETURN_PCT_FOR_ACCEPT:
        return False, "non_positive_return"
    if profit_factor < MIN_PROFIT_FACTOR_FOR_ACCEPT:
        return False, "profit_factor_too_low"
    if max_dd > (MAX_DRAWDOWN_PCT_FOR_ACCEPT + 25.0):
        return False, "drawdown_extreme"
    if quality_score < 35.0:
        return False, "quality_score_too_low"
    return True, "ok"


def _is_positive_progress_iteration(metrics: Dict[str, Any]) -> bool:
    """Détermine si une itération compte comme "positive" pour la progression."""
    if _is_ruined_metrics(metrics):
        return False
    ret = _metric_float(metrics, "total_return_pct", 0.0)
    trades = int(metrics.get("total_trades", 0) or 0)
    return ret > 0.0 and trades >= MIN_TRADES_FOR_POSITIVE_PROGRESS


def _count_positive_iterations(iterations: List[BuilderIteration]) -> int:
    """Compte les itérations backtestées positives dans l'historique de session.

    Fallback iterations with positive metrics are counted towards the quota,
    but limited to MAX_POSITIVE_FALLBACK_COUNT to prevent accepting
    sessions with only deterministic logic.
    """
    count = 0
    fallback_positive_count = 0

    for it in iterations:
        if it.backtest_result is None:
            continue

        metrics = it.backtest_result.metrics or {}
        is_positive = _is_positive_progress_iteration(metrics)

        if it.is_fallback:
            # Fallbacks positifs comptent avec quota limité
            if is_positive and fallback_positive_count < MAX_POSITIVE_FALLBACK_COUNT:
                count += 1
                fallback_positive_count += 1
        else:
            # Itérations LLM positives comptent toujours
            if is_positive:
                count += 1

    return count


def _required_positive_count_for_iteration(iteration_index: int) -> int:
    """Retourne le quota de runs positifs requis au checkpoint courant."""
    return int(POSITIVE_PROGRESS_GATE_CHECKPOINTS.get(iteration_index, 0) or 0)


def _const_value(node: ast.AST) -> Any:
    """Extrait une valeur constante AST (str/int/float) si possible."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Str):  # pragma: no cover - compat py<3.8
        return node.s
    return None


def _indicator_name_from_subscript(node: ast.AST) -> Optional[str]:
    """Retourne le nom d'indicateur pour indicators['name']."""
    if not isinstance(node, ast.Subscript):
        return None
    if not isinstance(node.value, ast.Name) or node.value.id != "indicators":
        return None
    key = _const_value(node.slice)
    if isinstance(key, str):
        return key
    return None


def _indicator_name_from_get_call(node: ast.AST) -> Optional[str]:
    """Retourne le nom d'indicateur pour indicators.get('name', ...)."""
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "get":
        return None
    if not isinstance(node.func.value, ast.Name) or node.func.value.id != "indicators":
        return None
    if not node.args:
        return None
    key = _const_value(node.args[0])
    if isinstance(key, str):
        return key
    return None


def _is_np_nan_to_num_call(node: ast.AST) -> bool:
    """Vérifie si le noeud est un appel np.nan_to_num(...)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "np"
        and node.func.attr == "nan_to_num"
    )


def _is_params_get_call(node: ast.AST) -> bool:
    """Vérifie si le noeud est un appel params.get(...)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "params"
        and node.func.attr == "get"
    )


def _is_params_subscript(node: ast.AST) -> bool:
    """Vérifie si le noeud est params['x']."""
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "params"
    )


def _is_scalar_cast_call(node: ast.AST) -> bool:
    """Vérifie si le noeud est un cast scalaire (float/int/bool)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"float", "int", "bool"}
    )


def _is_numeric_nonbool_constant(node: ast.AST) -> bool:
    """True si le noeud est une constante numérique non-bool."""
    if not isinstance(node, ast.Constant):
        return False
    return isinstance(node.value, (int, float)) and not isinstance(node.value, bool)


def _iter_generate_signals_functions(tree: ast.AST) -> List[ast.FunctionDef]:
    """Extrait les méthodes generate_signals de BuilderGeneratedStrategy."""
    out: List[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == GENERATED_CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "generate_signals":
                    out.append(item)
    return out


def _iter_child_nodes_excluding_nested_scopes(node: ast.AST) -> Any:
    """Itère récursivement sur les noeuds en excluant les scopes imbriqués.

    Objectif: analyser les Name Load/Store d'une méthode sans descendre dans
    des `def`/`class` internes (closures), qui ont leurs propres variables.
    """
    stack = list(ast.iter_child_nodes(node))
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(cur))


def _collect_name_load_store_sets(fn: ast.AST) -> tuple[set[str], set[str]]:
    """Collecte les noms utilisés (Load) et assignés (Store/Del) dans un noeud.

    Ne descend pas dans les scopes imbriqués (closures) pour éviter les faux
    positifs sur les variables capturées.
    """
    load: set[str] = set()
    store: set[str] = set()
    for node in _iter_child_nodes_excluding_nested_scopes(fn):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                load.add(node.id)
            elif isinstance(node.ctx, (ast.Store, ast.Del)):
                store.add(node.id)
    return load, store


def _collect_indicator_names(tree: ast.AST) -> set[str]:
    """Collecte les noms d'indicateurs référencés dans generate_signals."""
    names: set[str] = set()
    for fn in _iter_generate_signals_functions(tree):
        for node in ast.walk(fn):
            sub = _indicator_name_from_subscript(node)
            if sub:
                names.add(sub)
            got = _indicator_name_from_get_call(node)
            if got:
                names.add(got)
    return names


def _collect_indicator_names_in_class(tree: ast.AST) -> set[str]:
    """Collecte les indicateurs référencés dans toute la classe générée."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != GENERATED_CLASS_NAME:
            continue
        for sub in ast.walk(node):
            sub_name = _indicator_name_from_subscript(sub)
            if sub_name:
                names.add(sub_name)
            get_name = _indicator_name_from_get_call(sub)
            if get_name:
                names.add(get_name)
        break
    return names


def _dict_indicator_key_is_valid(indicator_name: str, key: Any) -> bool:
    """Valide une sous-clé pour un indicateur dict connu."""
    if not isinstance(key, str):
        return True
    name = indicator_name.lower()
    allowed = _DICT_INDICATOR_ALLOWED_KEYS.get(name)
    if not allowed:
        return True
    if key in allowed:
        return True
    if name in {"fibonacci", "fibonacci_levels"} and key.startswith("level_"):
        return True
    return False


def _dict_indicator_allowed_keys_hint(indicator_name: str) -> str:
    """Construit un hint compact des sous-clés valides."""
    name = indicator_name.lower()
    allowed = sorted(_DICT_INDICATOR_ALLOWED_KEYS.get(name, set()))
    if name in {"fibonacci", "fibonacci_levels"}:
        allowed = [*allowed, "level_XXX"]
    if not allowed:
        return "sous-clés string attendues"
    return ", ".join(allowed)


def _validate_indicator_usage_semantics(code: str) -> tuple[bool, str]:
    """Validation AST des usages indicateurs pour éviter erreurs runtime récurrentes."""
    try:
        tree = ast.parse(code)
    except Exception:
        return True, ""

    # var_name -> {"kind": "array|dict|values", "indicator": Optional[str]}
    bindings: Dict[str, Dict[str, Any]] = {}

    for fn in _iter_generate_signals_functions(tree):
        # Pass 1: collect bindings
        for node in ast.walk(fn):
            targets: List[ast.Name] = []
            value: Optional[ast.AST] = None

            if isinstance(node, ast.Assign):
                value = node.value
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        targets.append(t)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                value = node.value
                targets.append(node.target)
            else:
                continue

            if value is None or not targets:
                continue

            ind_name = _indicator_name_from_subscript(value)
            kind: Optional[str] = None
            if ind_name is not None:
                kind = "dict" if ind_name.lower() in _DICT_INDICATOR_NAMES else "array"
            elif _is_np_nan_to_num_call(value) and getattr(value, "args", None):
                arg0 = value.args[0]
                ind_name = _indicator_name_from_subscript(arg0)
                if ind_name is not None:
                    if ind_name.lower() in _DICT_INDICATOR_NAMES:
                        return (
                            False,
                            f"Usage invalide: np.nan_to_num(indicators['{ind_name}']) "
                            "(indicator dict).",
                        )
                    kind = "array"
                elif isinstance(arg0, ast.Name) and arg0.id in bindings:
                    if bindings[arg0.id]["kind"] == "dict":
                        return (
                            False,
                            f"Usage invalide: np.nan_to_num({arg0.id}) alors que "
                            f"{arg0.id} est un indicator dict.",
                        )
                    kind = "array"
            elif isinstance(value, ast.Attribute) and value.attr == "values":
                kind = "values"
            elif _is_params_get_call(value) or _is_params_subscript(value):
                kind = "scalar"
            elif _is_scalar_cast_call(value) and getattr(value, "args", None):
                arg0 = value.args[0]
                if _is_params_get_call(arg0) or _is_params_subscript(arg0):
                    kind = "scalar"
                elif isinstance(arg0, ast.Name):
                    b = bindings.get(arg0.id)
                    if b and b["kind"] == "scalar":
                        kind = "scalar"

            if kind is not None:
                for t in targets:
                    bindings[t.id] = {"kind": kind, "indicator": ind_name}

        # Pass 2: detect invalid usage
        for node in ast.walk(fn):
            # ndarray.shift(...) / ndarray.rolling(...)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if isinstance(node.func.value, ast.Name):
                    var = node.func.value.id
                    b = bindings.get(var)
                    if b and b["kind"] == "dict" and attr not in {"get"}:
                        return (
                            False,
                            f"Usage invalide: `{var}.{attr}(...)` alors que `{var}` est "
                            "un indicator dict. Extraire une sous-clé puis travailler "
                            "sur le ndarray correspondant.",
                        )
                if (
                    attr in {"shift", "rolling", "ewm"}
                    and isinstance(node.func.value, ast.Name)
                ):
                    var = node.func.value.id
                    b = bindings.get(var)
                    if b and b["kind"] in {"array", "values"}:
                        return (
                            False,
                            f"Usage invalide: {var}.{attr}(...) sur ndarray. "
                            "Utiliser pandas Series ou logique vectorisée numpy.",
                        )
                if attr in {"shift", "rolling", "ewm"}:
                    ind_name = _indicator_name_from_subscript(node.func.value)
                    if ind_name:
                        return (
                            False,
                            f"Usage invalide: indicators['{ind_name}'].{attr}(...) "
                            "sur ndarray. Utiliser une logique numpy.",
                        )

                # np.nan_to_num(var_dict)
                if _is_np_nan_to_num_call(node) and getattr(node, "args", None):
                    arg0 = node.args[0]
                    if isinstance(arg0, ast.Name):
                        b = bindings.get(arg0.id)
                        if b and b["kind"] == "dict":
                            return (
                                False,
                                f"Usage invalide: np.nan_to_num({arg0.id}) alors que "
                                f"{arg0.id} est un indicator dict.",
                            )

            # .iloc/.loc/.iat/.at sur indicateurs ndarray/dict
            if isinstance(node, ast.Attribute) and node.attr in {"iloc", "loc", "iat", "at"}:
                if isinstance(node.value, ast.Name):
                    var = node.value.id
                    b = bindings.get(var)
                    if b and b["kind"] in {"array", "values", "dict"}:
                        return (
                            False,
                            f"Usage invalide: {var}.{node.attr} sur indicateur "
                            "numpy/dict. Utiliser indexation numpy (`arr[i]`).",
                        )
                ind_name = _indicator_name_from_subscript(node.value)
                if ind_name:
                    return (
                        False,
                        f"Usage invalide: indicators['{ind_name}'].{node.attr} "
                        "n'est pas supporté. Utiliser indexation numpy (`arr[i]`).",
                    )

            # Subscript checks: multi-dim on 1D arrays, numeric key on dict indicators
            if isinstance(node, ast.Subscript):
                if isinstance(node.value, ast.Name):
                    var = node.value.id
                    b = bindings.get(var)
                    if b:
                        key = _const_value(node.slice)
                        if b["kind"] in {"array", "values"} and isinstance(node.slice, ast.Tuple):
                            return (
                                False,
                                f"Usage invalide: indexation multi-dim `{var}[..., ...]` "
                                "sur indicateur 1D.",
                            )
                        if b["kind"] in {"array", "values"} and isinstance(key, str):
                            return (
                                False,
                                f"Usage invalide: clé string `{var}['{key}']` sur "
                                "indicateur ndarray. Utiliser directement l'array.",
                            )
                        if b["kind"] == "dict" and isinstance(key, (int, float)):
                            return (
                                False,
                                f"Usage invalide: clé numérique `{var}[{key}]` sur "
                                "indicator dict; utiliser des sous-clés string.",
                            )
                        if b["kind"] == "dict" and isinstance(key, str):
                            ind = str(b.get("indicator") or "")
                            if ind and not _dict_indicator_key_is_valid(ind, key):
                                hint = _dict_indicator_allowed_keys_hint(ind)
                                return (
                                    False,
                                    f"Usage invalide: `{var}['{key}']` pour "
                                    f"indicateur dict '{ind}'. Sous-clés valides: {hint}.",
                                )

                # indicators['bollinger'][50] / indicators['ema']['ema_21']
                ind_name = _indicator_name_from_subscript(node.value)
                if ind_name:
                    key = _const_value(node.slice)
                    if ind_name.lower() in _DICT_INDICATOR_NAMES:
                        if isinstance(key, (int, float)):
                            return (
                                False,
                                f"Usage invalide: indicators['{ind_name}'][{key}] — "
                                "utiliser des sous-clés string.",
                            )
                        if isinstance(key, str) and not _dict_indicator_key_is_valid(ind_name, key):
                            hint = _dict_indicator_allowed_keys_hint(ind_name)
                            return (
                                False,
                                f"Usage invalide: indicators['{ind_name}']['{key}'] — "
                                f"sous-clé inconnue. Sous-clés valides: {hint}.",
                            )
                    elif isinstance(key, str):
                        return (
                            False,
                            f"Usage invalide: indicators['{ind_name}']['{key}'] — "
                            f"'{ind_name}' retourne un ndarray, pas un dict.",
                        )
                get_name = _indicator_name_from_get_call(node.value)
                if get_name:
                    key = _const_value(node.slice)
                    if get_name.lower() in _DICT_INDICATOR_NAMES:
                        if isinstance(key, (int, float)):
                            return (
                                False,
                                f"Usage invalide: indicators.get('{get_name}')[{key}] — "
                                "utiliser des sous-clés string.",
                            )
                        if isinstance(key, str) and not _dict_indicator_key_is_valid(get_name, key):
                            hint = _dict_indicator_allowed_keys_hint(get_name)
                            return (
                                False,
                                f"Usage invalide: indicators.get('{get_name}')['{key}'] — "
                                f"sous-clé inconnue. Sous-clés valides: {hint}.",
                            )
                    elif isinstance(key, str):
                        return (
                            False,
                            f"Usage invalide: indicators.get('{get_name}')['{key}'] — "
                            f"'{get_name}' retourne un ndarray, pas un dict.",
                        )

            # Comparaisons/arithmétiques directes sur dict indicators
            if isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                for operand in operands:
                    if isinstance(operand, ast.Name):
                        var = operand.id
                        b = bindings.get(var)
                        if b and b["kind"] == "dict":
                            hint_key = _dict_indicator_allowed_keys_hint(
                                str(b.get("indicator") or var)
                            ).split(",")[0].strip()
                            return (
                                False,
                                f"Usage invalide: comparaison `{var} ...` alors que "
                                f"`{var}` est un indicator dict. Utiliser une sous-clé "
                                f"(ex: {var}['{hint_key}']).",
                            )

            if isinstance(node, ast.BinOp):
                for operand in (node.left, node.right):
                    if isinstance(operand, ast.Name):
                        var = operand.id
                        b = bindings.get(var)
                        if b and b["kind"] == "dict":
                            hint_key = _dict_indicator_allowed_keys_hint(
                                str(b.get("indicator") or var)
                            ).split(",")[0].strip()
                            return (
                                False,
                                f"Usage invalide: opération arithmétique sur `{var}` "
                                "qui est un indicator dict. Utiliser une sous-clé "
                                f"(ex: {var}['{hint_key}']).",
                            )

                if isinstance(node.op, (ast.BitAnd, ast.BitOr, ast.BitXor)):
                    for operand in (node.left, node.right):
                        if isinstance(operand, ast.Name):
                            b = bindings.get(operand.id)
                            if b and b["kind"] == "scalar":
                                return (
                                    False,
                                    f"Usage invalide: opérateur logique bitwise avec "
                                    f"scalaire `{operand.id}`. Comparer d'abord la valeur "
                                    "scalaire (ex: `arr > threshold`) puis combiner les masques.",
                                )
                        if _is_numeric_nonbool_constant(operand):
                            return (
                                False,
                                "Usage invalide: opérateur logique bitwise avec constante "
                                "numérique. Utiliser des comparaisons booléennes de part et d'autre.",
                            )

            if isinstance(node, ast.BoolOp):
                for operand in node.values:
                    if isinstance(operand, ast.Name):
                        var = operand.id
                        b = bindings.get(var)
                        if b and b["kind"] == "dict":
                            hint_key = _dict_indicator_allowed_keys_hint(
                                str(b.get("indicator") or var)
                            ).split(",")[0].strip()
                            return (
                                False,
                                f"Usage invalide: test booléen direct sur `{var}` "
                                "qui est un indicator dict. Utiliser une sous-clé "
                                f"(ex: {var}['{hint_key}']).",
                            )

            if isinstance(node, (ast.If, ast.While)) and isinstance(node.test, ast.Name):
                var = node.test.id
                b = bindings.get(var)
                if b and b["kind"] == "dict":
                    hint_key = _dict_indicator_allowed_keys_hint(
                        str(b.get("indicator") or var)
                    ).split(",")[0].strip()
                    return (
                        False,
                        f"Usage invalide: condition `{var}` alors que `{var}` est un "
                        f"indicator dict. Utiliser une sous-clé (ex: {var}['{hint_key}']).",
                    )

    return True, ""


def _extract_json_from_response(text: str) -> Dict[str, Any]:
    """Extrait un bloc JSON depuis une réponse LLM (gère ```json ... ```, <think>, etc.)."""
    def _parse_json_dict(payload: str) -> Dict[str, Any]:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    # Nettoyer les tags <think> des modèles de raisonnement (qwen3, deepseek-r1, alia, etc.)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    text = text.strip()

    if not text:
        logger.warning("extract_json: réponse vide après nettoyage des tags <think>")
        return {}

    # Chercher bloc ```json ... ```
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        parsed = _parse_json_dict(match.group(1).strip())
        if parsed:
            return parsed

    # Essayer le texte brut
    parsed = _parse_json_dict(text.strip())
    if parsed:
        return parsed

    # Chercher premier { ... } englobant
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        parsed = _parse_json_dict(brace_match.group(0))
        if parsed:
            return parsed

    logger.warning(
        "extract_json: aucun JSON valide trouvé. Début réponse: %.200s",
        text[:200],
    )
    return {}


def _extract_python_from_response(text: str) -> str:
    """Extrait un bloc Python depuis une réponse LLM."""
    # Nettoyer les tags <think> des modèles de raisonnement
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
    text = text.strip()
    match = re.search(r"```(?:python)?\s*\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback : le texte entier
    return text.strip()


def _timeframe_to_timedelta(timeframe: str) -> Optional[pd.Timedelta]:
    """Convertit un timeframe texte en timedelta."""
    tf = str(timeframe or "").strip()
    match = re.match(r"^(\d+)([mhdwM])$", tf)
    if not match:
        return None
    n = int(match.group(1))
    unit = match.group(2)
    if unit == "m":
        return pd.Timedelta(minutes=n)
    if unit == "h":
        return pd.Timedelta(hours=n)
    if unit == "d":
        return pd.Timedelta(days=n)
    if unit == "w":
        return pd.Timedelta(weeks=n)
    if unit == "M":
        return pd.Timedelta(days=30 * n)
    return None


def _max_contiguous_segment_bars(df: pd.DataFrame, timeframe: str) -> int:
    """Retourne la taille max d'un segment continu hors gaps majeurs."""
    if df.empty:
        return 0
    expected = _timeframe_to_timedelta(timeframe)
    if expected is None:
        return len(df)
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex) or len(idx) <= 1:
        return len(df)
    diffs = idx[1:] - idx[:-1]
    major_gap = diffs > (expected * 3)
    if not np.any(major_gap):
        return len(df)
    cut_positions = np.where(major_gap)[0]
    starts = [0, *[int(pos) + 1 for pos in cut_positions]]
    ends = [*[int(pos) + 1 for pos in cut_positions], len(df)]
    lengths = [end - start for start, end in zip(starts, ends)]
    return max(lengths) if lengths else len(df)


def _validate_builder_dataset_exploitability(
    data: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
) -> tuple[bool, str]:
    """Valide que le dataset/timeframe est exploitable pour le Builder."""
    n_bars = int(len(data))
    if n_bars < MIN_BUILDER_BARS:
        return (
            False,
            (
                f"Dataset insuffisant pour Builder: {n_bars} barres (< {MIN_BUILDER_BARS}) "
                f"sur {symbol}/{timeframe}."
            ),
        )

    if symbol and symbol != "UNKNOWN":
        try:
            from data.config import find_optimal_periods

            periods = find_optimal_periods([symbol], [timeframe], min_period_days=30, max_periods=1)
            if not periods:
                return (
                    False,
                    (
                        "Aucun segment exploitable sans gaps majeurs détecté "
                        f"par data.config pour {symbol}/{timeframe}."
                    ),
                )
        except Exception as exc:
            logger.warning(
                "builder_dataset_quality_check_fallback symbol=%s timeframe=%s error=%s",
                symbol,
                timeframe,
                exc,
            )

    max_segment = _max_contiguous_segment_bars(data, timeframe)
    if max_segment < MIN_BUILDER_BARS:
        return (
            False,
            (
                "Aucun segment continu exploitable détecté: "
                f"segment max={max_segment} barres (< {MIN_BUILDER_BARS}) sur {symbol}/{timeframe}."
            ),
        )

    return True, ""


def _fix_class_name(code: str) -> str:
    """Renomme la première sous-classe StrategyBase en GENERATED_CLASS_NAME."""
    if re.search(rf"\bclass\s+{GENERATED_CLASS_NAME}\s*\(", code):
        return code
    # Chercher une sous-classe de StrategyBase
    match = re.search(r"class\s+(\w+)\s*\([^)]*StrategyBase[^)]*\)", code)
    if match:
        old_name = match.group(1)
        if old_name != GENERATED_CLASS_NAME:
            code = re.sub(rf"\b{re.escape(old_name)}\b", GENERATED_CLASS_NAME, code)
        return code
    # Pas de StrategyBase — renommer la première classe
    match = re.search(r"class\s+(\w+)\s*\(", code)
    if match:
        old_name = match.group(1)
        code = re.sub(
            rf"class\s+{re.escape(old_name)}\s*\(",
            f"class {GENERATED_CLASS_NAME}(",
            code, count=1,
        )
    return code


def _inject_generate_signals_core_param_aliases(code: str) -> str:
    """Injecte des alias pour éviter des NameError de variables coeur.

    Cas fréquent: `def generate_signals(self, data, indicators, params):` mais le
    corps fait `signals = ... index=df.index` / `close = df["close"]...`.
    On insère alors `df = data` en tête de méthode (idem pour `indicators/params`).
    """
    try:
        tree = ast.parse(code)
    except Exception:
        return code

    fns = _iter_generate_signals_functions(tree)
    if not fns:
        return code

    lines = code.split("\n")
    insertions: List[Tuple[int, List[str]]] = []

    for fn in fns:
        args = [a.arg for a in fn.args.args]
        if len(args) < 4:
            continue

        df_arg, ind_arg, params_arg = args[1], args[2], args[3]
        load_names, store_names = _collect_name_load_store_sets(fn)

        alias_raw: List[str] = []
        if "df" in load_names and "df" not in args and "df" not in store_names and df_arg != "df":
            alias_raw.append(f"df = {df_arg}")
        if (
            "indicators" in load_names
            and "indicators" not in args
            and "indicators" not in store_names
            and ind_arg != "indicators"
        ):
            alias_raw.append(f"indicators = {ind_arg}")
        if "params" in load_names and "params" not in args and "params" not in store_names and params_arg != "params":
            alias_raw.append(f"params = {params_arg}")
        if "warmup" in load_names and "warmup" not in args and "warmup" not in store_names:
            warmup_source = "params"
            if params_arg and params_arg in args and params_arg != "params":
                warmup_source = params_arg
            alias_raw.append(f"warmup = int({warmup_source}.get('warmup', 50))")

        if not alias_raw:
            continue

        insert_lineno: int
        if fn.body:
            first_stmt = fn.body[0]
            if (
                isinstance(first_stmt, ast.Expr)
                and isinstance(getattr(first_stmt, "value", None), ast.Constant)
                and isinstance(first_stmt.value.value, str)
            ):
                end = getattr(first_stmt, "end_lineno", None) or first_stmt.lineno
                insert_lineno = int(end) + 1
            else:
                insert_lineno = int(first_stmt.lineno)
        else:
            insert_lineno = int((getattr(fn, "end_lineno", None) or fn.lineno) + 1)

        insert_idx = max(0, min(len(lines), insert_lineno - 1))

        # Indentation = indentation de la première ligne de body (ou fallback def+4)
        indent = ""
        if 0 <= insert_idx < len(lines) and lines:
            indent = re.match(r"^(\s*)", lines[insert_idx]).group(1)
        else:
            def_line_idx = max(0, min(len(lines) - 1, int(fn.lineno) - 1)) if lines else 0
            def_indent = re.match(r"^(\s*)", lines[def_line_idx]).group(1) if lines else ""
            indent = def_indent + "    "

        insertions.append((insert_idx, [indent + line for line in alias_raw]))

    if not insertions:
        return code

    # Appliquer en reverse pour préserver les index
    for idx, new_lines in sorted(insertions, key=lambda x: x[0], reverse=True):
        lines[idx:idx] = new_lines

    return "\n".join(lines)


def _repair_code(code: str) -> str:
    """Auto-repair des erreurs courantes du code genere par LLM.

    Corrige:
    - Tags <think> des modeles de raisonnement (qwen3, deepseek-r1)
    - Docstrings triple-quoted non terminées (cause #1 de crash)
    - Nom de classe incorrect (cause #2 de crash)
    - np.nan_to_num() appliqué directement sur indicateurs dict
    - .shift() / .rolling() / .ewm() sur ndarray → remplacement numpy
    - .iloc / .loc sur indicateurs ndarray → indexation numpy
    - indicators['ema']['ema_XX'] → indicators['ema'] (array, pas dict)
    """
    # 1. Retirer les tags <think> des modeles de raisonnement
    code = re.sub(r"<think>.*?</think>\s*", "", code, flags=re.DOTALL)
    code = re.sub(r"<think>.*", "", code, flags=re.DOTALL)

    # 2. Supprimer le preamble non-Python (markdown, texte explicatif)
    #    avant la première ligne de code réelle (from/import/class/def)
    lines = code.split("\n")
    first_code_idx = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped and (
            stripped.startswith(("from ", "import ", "class ", "def ", "@"))
            or stripped.startswith("#!")
        ):
            first_code_idx = idx
            break
    if first_code_idx > 0:
        code = "\n".join(lines[first_code_idx:])

    # 3. Supprimer docstrings si syntax error + tenter un dedent sur erreurs d'indentation
    try:
        ast.parse(code)
    except SyntaxError as e:
        msg = str(getattr(e, "msg", "") or "").lower()
        if "unexpected indent" in msg or "unindent" in msg or "indentation" in msg:
            code = textwrap.dedent(code)
        code = _strip_docstrings(code)

    # 3. Fixer le nom de classe
    code = _fix_class_name(code)

    # 4. np.nan_to_num(indicators["bollinger"]) → indicateur dict accédé directement
    #    Remplacer par extraction des sous-clés
    for dict_ind in _DICT_INDICATOR_NAMES:
        # np.nan_to_num(indicators["bollinger"]) → indicators["bollinger"]
        code = re.sub(
            r"np\.nan_to_num\(\s*indicators\s*\[\s*['\"]"
            + re.escape(dict_ind)
            + r"['\"]\s*\]\s*\)",
            f'indicators["{dict_ind}"]',
            code,
        )
        # np.nan_to_num(indicators.get("bollinger")) → indicators.get("bollinger")
        code = re.sub(
            r"np\.nan_to_num\(\s*indicators\.get\(\s*['\"]"
            + re.escape(dict_ind)
            + r"['\"]\s*\)\s*\)",
            f'indicators.get("{dict_ind}")',
            code,
        )

    # 4b. Normaliser les sous-clés erronées courantes (stochastic)
    #     Certains modèles utilisent `indicators['stochastic']['signal|stochastic']`.
    code = re.sub(
        r"(indicators\s*\[\s*['\"]stochastic['\"]\s*\]\s*\[\s*['\"])(stochastic|k)(['\"]\s*\])",
        r"\1stoch_k\3",
        code,
        flags=re.IGNORECASE,
    )
    code = re.sub(
        r"(indicators\s*\[\s*['\"]stochastic['\"]\s*\]\s*\[\s*['\"])(signal|d)(['\"]\s*\])",
        r"\1stoch_d\3",
        code,
        flags=re.IGNORECASE,
    )

    # 5. .shift(N) sur ndarray → np.roll(..., N)
    #    pattern: var_name.shift(N)  → np.roll(var_name, N)
    code = re.sub(
        r"(\b\w+)\.shift\(\s*(\d+)\s*\)",
        r"np.roll(\1, \2)",
        code,
    )
    # .shift() sans arg → np.roll(..., 1)
    code = re.sub(
        r"(\b\w+)\.shift\(\s*\)",
        r"np.roll(\1, 1)",
        code,
    )

    # 6. indicators['ema']['ema_XX'] → indicators['ema']
    #    (ema/rsi/atr sont des plain arrays, pas des dicts)
    for arr_ind in ("ema", "rsi", "atr", "sma", "cci", "mfi",
                    "williams_r", "momentum", "obv", "roc"):
        code = re.sub(
            r"indicators\s*\[\s*['\"]"
            + re.escape(arr_ind)
            + r"['\"]\s*\]\s*\[\s*['\"][^'\"]*['\"]\s*\]",
            f'indicators["{arr_ind}"]',
            code,
        )

    # 7. Supprimer les imports incorrects "from indicators import ..."
    #    Le LLM local tente parfois d'importer directement les indicateurs
    #    alors qu'ils sont fournis via le dict `indicators`.
    code = re.sub(
        r"^from\s+indicators\s+import\s+[^\n]+\n?",
        "",
        code,
        flags=re.MULTILINE,
    )
    code = re.sub(
        r"^import\s+indicators\b[^\n]*\n?",
        "",
        code,
        flags=re.MULTILINE,
    )

    # 8. Garantir les imports obligatoires
    _REQUIRED_IMPORTS = [
        ("from typing import", "from typing import Any, Dict, List\n"),
        ("from strategies.base import StrategyBase", "from strategies.base import StrategyBase\n"),
        ("from utils.parameters import ParameterSpec", "from utils.parameters import ParameterSpec\n"),
        ("import numpy", "import numpy as np\n"),
        ("import pandas", "import pandas as pd\n"),
    ]
    for check_str, import_line in _REQUIRED_IMPORTS:
        if check_str not in code:
            code = import_line + code

    # 9. Garantir l'héritage StrategyBase
    #    Si la classe est définie sans parent ou avec un parent incorrect,
    #    forcer l'héritage de StrategyBase.
    code = re.sub(
        rf"class\s+{GENERATED_CLASS_NAME}\s*:\s*\n",
        f"class {GENERATED_CLASS_NAME}(StrategyBase):\n",
        code,
    )
    code = re.sub(
        rf"class\s+{GENERATED_CLASS_NAME}\s*\(\s*\)\s*:",
        f"class {GENERATED_CLASS_NAME}(StrategyBase):",
        code,
    )

    # 10. Alias variables coeur dans generate_signals (évite NameError df/indicators/params)
    code = _inject_generate_signals_core_param_aliases(code)

    # 11. Bare indicator variable repair — fix keltner['upper'] → indicators['keltner']['upper']
    #     and keltner_upper → np.nan_to_num(indicators['keltner']['upper'])
    for dict_ind, subkeys in _DICT_INDICATOR_ALLOWED_KEYS.items():
        # Pattern A: bare_name['subkey'] → indicators['bare_name']['subkey']
        # Only match if NOT preceded by indicators[ (already correct)
        code = re.sub(
            r"(?<!\[)\b" + re.escape(dict_ind) + r"\s*\[\s*(['\"])(\w+)\1\s*\]",
            lambda m, ind=dict_ind: (
                f'indicators["{ind}"]["{m.group(2)}"]'
                if m.group(2) in _DICT_INDICATOR_ALLOWED_KEYS.get(ind, set())
                else m.group(0)
            ),
            code,
        )
        # Pattern B: bare_name_subkey used as variable → np.nan_to_num(indicators['name']['subkey'])
        for subkey in sorted(subkeys, key=len, reverse=True):
            alias = f"{dict_ind}_{subkey}"
            # Only replace bare assignments like: keltner_upper = ... (don't touch indicators[...])
            # Replace usages in comparisons: (keltner_upper > X) → (np.nan_to_num(indicators[...]) > X)
            pattern = r"\b" + re.escape(alias) + r"\b"
            replacement = f"np.nan_to_num(indicators['{dict_ind}']['{subkey}'])"
            # Only if alias is used as a standalone name (not part of a string or indicators[])
            if re.search(pattern, code) and f"indicators['{dict_ind}']['{subkey}']" not in code:
                code = re.sub(pattern, replacement, code)

    # 12. Normaliser les noms d'indicateurs en lowercase (évite KeyError: 'SMA')
    code = re.sub(
        r"indicators\s*\[\s*['\"]([A-Za-z0-9_]+)['\"]\s*\]",
        lambda m: f"indicators['{m.group(1).lower()}']",
        code,
    )
    code = re.sub(
        r"indicators\.get\(\s*['\"]([A-Za-z0-9_]+)['\"]",
        lambda m: f"indicators.get('{m.group(1).lower()}'",
        code,
    )

    # 13. Notation pointée LLM (donchian.upper, adx.adx, ...) -> dict indicators.
    for dict_ind, subkeys in _DICT_INDICATOR_ALLOWED_KEYS.items():
        for subkey in subkeys:
            code = re.sub(
                rf"\b{re.escape(dict_ind)}\s*\.\s*{re.escape(subkey)}\b",
                f"indicators['{dict_ind}']['{subkey}']",
                code,
                flags=re.IGNORECASE,
            )

    # 14. Colonnes OHLCV / runtime SL-TP doivent venir de df (pas indicators).
    df_cols = {"open", "high", "low", "close", "volume", *_BUILDER_ALLOWED_WRITE_DF_COLUMNS}
    for col in sorted(df_cols):
        code = re.sub(
            rf"indicators\s*\[\s*['\"]{re.escape(col)}['\"]\s*\]",
            f"df['{col}']",
            code,
            flags=re.IGNORECASE,
        )
        code = re.sub(
            rf"indicators\.get\(\s*['\"]{re.escape(col)}['\"]\s*(?:,\s*[^)]*)?\)",
            f"df['{col}']",
            code,
            flags=re.IGNORECASE,
        )

    return code


def _extract_generate_signals_logic_block(code: str) -> str:
    """Extrait le bloc logique de generate_signals depuis une réponse LLM."""
    try:
        tree = ast.parse(code)
    except Exception:
        return ""

    lines = code.splitlines()
    for fn in _iter_generate_signals_functions(tree):
        if not fn.body:
            continue
        start = int(fn.body[0].lineno) - 1
        end = int(getattr(fn.body[-1], "end_lineno", fn.body[-1].lineno))
        block_lines = lines[start:end]
        stripped: List[str] = []
        for line in block_lines:
            s = line.strip()
            if not s:
                stripped.append(line)
                continue
            if re.match(r"^(signals|n|warmup)\s*=", s):
                continue
            if s == "return signals":
                continue
            stripped.append(line)
        return textwrap.dedent("\n".join(stripped)).strip()
    return ""


def _normalize_signal_assignments(logic: str) -> str:
    """Normalise les affectations de signaux vers -1.0/0.0/1.0."""
    logic = re.sub(r"(signals\s*\[[^\n]+\]\s*=\s*)1(?![\d.])", r"\g<1>1.0", logic)
    logic = re.sub(r"(signals\s*\[[^\n]+\]\s*=\s*)-1(?![\d.])", r"\g<1>-1.0", logic)
    logic = re.sub(r"(signals\s*\[[^\n]+\]\s*=\s*)0(?![\d.])", r"\g<1>0.0", logic)
    return logic


def _postprocess_llm_logic_block(logic: str, required_indicators: List[str]) -> str:
    """Corrige automatiquement des fautes mineures de logique LLM."""
    fixed = logic
    # Fix df['indicator_name'] -> indicators['indicator_name'] (required indicators)
    for ind in required_indicators:
        fixed = re.sub(
            rf"df\s*\[\s*['\"]{re.escape(ind)}['\"]\s*\]",
            f"indicators['{ind}']",
            fixed,
        )
    # Fix df['signal'] = X -> signals[...] = X (common LLM mistake)
    fixed = re.sub(
        r"df\s*\[\s*['\"]signals?['\"]\s*\]",
        "signals",
        fixed,
    )
    # Fix flat alias patterns: bollinger_upper -> indicators['bollinger']['upper'] etc.
    for alias, correct in _INDICATOR_ALIAS_HINTS.items():
        # Only fix bare-name usage (not already inside quotes/brackets)
        fixed = re.sub(
            rf"(?<!['\"\[])\b{re.escape(alias)}\b(?!['\"\]])",
            correct,
            fixed,
        )
    fixed = _normalize_signal_assignments(fixed)
    return fixed


def _validate_llm_logic_block(logic: str) -> tuple[bool, str]:
    """Valide le bloc logique LLM avant assemblage final."""
    if not logic.strip():
        return False, _err(ERR_CLASS, "Bloc logique LLM vide.")
    # Autoriser signals.iloc[:warmup] (slice warmup du template) mais interdire
    # tout autre .iloc[ (accès indexé non-vectorisé)
    if re.search(r"\.iloc\[(?!\s*:)", logic):
        return False, _err(ERR_SIG, "`.iloc[i]` interdit (accès indexé). Seul `signals.iloc[:warmup]` est autorisé.")
    if re.search(r"\bfor\s+\w+\s+in\s+range\s*\(", logic):
        return False, _err(ERR_SIG, "`for i in range(...)` interdit dans la logique Builder.")
    if re.search(r"\bwhile\b", logic):
        return False, _err(ERR_SIG, "`while` interdit dans la logique Builder.")
    if re.search(r"\bsignals\s*(?:\.[A-Za-z_]\w*)?\s*\[[^\]]*\]\s*=\s*(?:True|False)\b", logic):
        return False, _err(ERR_SIG, "Constantes booléennes True/False interdites dans les signaux.")
    if re.search(r"\bsignals\s*=\s*(?:True|False)\b", logic):
        return False, _err(ERR_SIG, "Constantes booléennes True/False interdites dans les signaux.")
    return True, ""


def _looks_like_valid_python_logic(logic: str) -> bool:
    """Vérifie qu'un bloc logique ressemble à du Python exécutable."""
    candidate = textwrap.dedent(str(logic or "")).strip()
    if not candidate:
        return False
    if not re.search(r"\b(if|signals|indicators|params|np\.|df\.|return|=)\b", candidate):
        return False
    wrapped = "def _tmp(df, indicators, params, signals):\n" + "\n".join(
        f"    {line}" if line.strip() else ""
        for line in candidate.splitlines()
    )
    try:
        ast.parse(wrapped)
    except SyntaxError:
        return False
    return True


def _format_parameter_specs_code(specs: Dict[str, Any]) -> str:
    """Construit le code Python pour la propriété parameter_specs."""
    if not isinstance(specs, dict) or not specs:
        return "        return {}\n"

    out: List[str] = ["        return {\n"]
    for name, spec in specs.items():
        if not isinstance(name, str) or not isinstance(spec, dict):
            continue
        min_v = spec.get("min")
        max_v = spec.get("max")
        default_v = spec.get("default")
        ptype = str(spec.get("type", "float"))
        step_v = spec.get("step")
        if min_v is None or max_v is None or default_v is None or ptype not in {"int", "float", "bool"}:
            continue
        if step_v is None:
            step_v = 1 if ptype == "int" else 0.1
        out.extend(
            [
                f"            {name!r}: ParameterSpec(\n",
                f"                name={name!r},\n",
                f"                min_val={min_v!r},\n",
                f"                max_val={max_v!r},\n",
                f"                default={default_v!r},\n",
                f"                param_type={ptype!r},\n",
                f"                step={step_v!r},\n",
                "            ),\n",
            ]
        )
    out.append("        }\n")
    return "".join(out)


def _build_deterministic_strategy_code(
    proposal: Dict[str, Any],
    llm_logic: str,
) -> str:
    """Assemble un code stratégie à squelette 100% déterministe."""
    strategy_name = str(proposal.get("strategy_name", "BuilderGenerated")).strip() or "BuilderGenerated"
    strategy_name = strategy_name.replace('"', "").replace("'", "")

    used = proposal.get("used_indicators", [])
    required_indicators: List[str] = []
    if isinstance(used, list):
        for item in used:
            if isinstance(item, str):
                ind = item.strip().lower()
                if ind and ind not in required_indicators:
                    required_indicators.append(ind)

    default_params = proposal.get("default_params", {})
    if not isinstance(default_params, dict):
        default_params = {}
    default_params.setdefault("leverage", 1)
    default_params.setdefault("warmup", 50)
    direction_constraint = str(
        proposal.get("direction_constraint", "long_short") or "long_short"
    ).strip().lower()

    default_params_literal = _format_python_dict_literal(default_params)
    default_params_lines = default_params_literal.splitlines() or ["{}"]
    if len(default_params_lines) == 1:
        default_params_block = f"        return {default_params_lines[0]}\n\n"
    else:
        default_params_block = "        return " + default_params_lines[0] + "\n"
        default_params_block += "".join(f"        {line}\n" for line in default_params_lines[1:])
        default_params_block += "\n"

    specs_block = _format_parameter_specs_code(proposal.get("parameter_specs", {}))
    normalized_logic = textwrap.dedent(llm_logic).strip("\n")
    logic_lines = normalized_logic.splitlines() if normalized_logic else ["pass"]
    logic_block = "\n".join(
        f"        {line}" if line.strip() else ""
        for line in logic_lines
    )
    direction_block = ""
    if direction_constraint == "long_only":
        direction_block = (
            "        # Objective constraint: long-only\n"
            "        signals[signals < 0.0] = 0.0\n"
        )
    elif direction_constraint == "short_only":
        direction_block = (
            "        # Objective constraint: short-only\n"
            "        signals[signals > 0.0] = 0.0\n"
        )

    return (
        "from typing import Any, Dict, List\n\n"
        "import numpy as np\n"
        "import pandas as pd\n\n"
        "from utils.parameters import ParameterSpec\n"
        "from strategies.base import StrategyBase\n\n\n"
        f"class {GENERATED_CLASS_NAME}(StrategyBase):\n"
        "    def __init__(self):\n"
        f"        super().__init__(name={strategy_name!r})\n\n"
        "    @property\n"
        "    def required_indicators(self) -> List[str]:\n"
        f"        return {required_indicators!r}\n\n"
        "    @property\n"
        "    def default_params(self) -> Dict[str, Any]:\n"
        f"{default_params_block}"
        "    @property\n"
        "    def parameter_specs(self) -> Dict[str, ParameterSpec]:\n"
        f"{specs_block}\n"
        "    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:\n"
        "        signals = pd.Series(0.0, index=df.index, dtype=np.float64)\n"
        "        n = len(df)\n"
        "        warmup = int(params.get('warmup', 50))\n"
        "        long_mask = np.zeros(n, dtype=bool)\n"
        "        short_mask = np.zeros(n, dtype=bool)\n"
        "        # === LOGIQUE LLM INSÉRÉE ICI UNIQUEMENT ===\n"
        f"{logic_block}\n"
        f"{direction_block}"
        "        signals.iloc[:warmup] = 0.0\n"
        "        return signals\n"
    )


def _build_deterministic_fallback_code(
    proposal: Dict[str, Any],
    variant: int = 0,
) -> str:
    """Construit un code de stratégie conservateur, robuste et syntaxiquement valide.

    Utilisé en dernier recours si le LLM renvoie un code invalide même après retry.
    Le paramètre ``variant`` permet de varier la logique quand le fallback est
    appelé plusieurs fois dans la même session (évite la stagnation).

    Variantes:
        0 — mean-reversion RSI/Bollinger + SL/TP ATR (impulsions, overtrading-safe)
        1 — trend-following Supertrend/ADX + SL/TP ATR (impulsions)
        2 — momentum RSI/EMA + SL/TP ATR (impulsions)
        3 — breakout Donchian/ADX + SL/TP ATR (aligné archetype breakout)
    """
    strategy_name = str(proposal.get("strategy_name", "BuilderFallback")).strip()
    if not strategy_name:
        strategy_name = "BuilderFallback"
    strategy_name = strategy_name.replace('"', "").replace("'", "")

    used = proposal.get("used_indicators", [])
    if not isinstance(used, list):
        used = []
    safe_used: List[str] = []
    for x in used:
        if isinstance(x, str):
            sx = x.strip().lower()
            if sx:
                if sx not in safe_used:
                    safe_used.append(sx)
    if len(safe_used) > 20:
        safe_used = safe_used[:20]

    default_params = proposal.get("default_params", {})
    if not isinstance(default_params, dict):
        default_params = {}
    default_params.setdefault("warmup", 50)
    default_params.setdefault("atr_period", 14)
    default_params.setdefault("stop_atr_mult", 1.5)
    default_params.setdefault("tp_atr_mult", 3.0)
    default_params["leverage"] = 1  # Force leverage=1 (not setdefault)
    direction_constraint = str(
        proposal.get("direction_constraint", "long_short") or "long_short"
    ).strip().lower()

    effective_variant = variant % 4
    if "donchian" in safe_used and "adx" in safe_used:
        effective_variant = 3

    if effective_variant == 1:
        # ── Variante 1: trend-following Supertrend/ADX ──
        for needed in ("supertrend", "adx", "atr"):
            if needed not in safe_used:
                safe_used.append(needed)
        default_params.setdefault("supertrend_atr_period", 10)
        default_params.setdefault("supertrend_multiplier", 3.0)
        default_params.setdefault("adx_period", 14)
        default_params.setdefault("adx_threshold", 20.0)
        signals_body = (
            "        stop_atr_mult = float(params.get('stop_atr_mult', 1.5))\n"
            "        tp_atr_mult = float(params.get('tp_atr_mult', 3.0))\n"
            "        adx_threshold = float(params.get('adx_threshold', 20.0))\n"
            "        close = np.nan_to_num(df['close'].values.astype(np.float64))\n"
            "        if len(close) < warmup + 2:\n"
            "            return signals\n"
            "        atr_raw = indicators.get('atr')\n"
            "        if isinstance(atr_raw, np.ndarray):\n"
            "            atr = np.nan_to_num(atr_raw.astype(np.float64))\n"
            "        else:\n"
            "            atr = np.full(n, 0.0)\n"
            "        st_raw = indicators.get('supertrend')\n"
            "        if isinstance(st_raw, dict):\n"
            "            direction = np.nan_to_num(st_raw.get('direction', np.zeros(n))).astype(np.float64)\n"
            "        else:\n"
            "            direction = np.full(n, 0.0)\n"
            "        adx_raw = indicators.get('adx')\n"
            "        if isinstance(adx_raw, dict):\n"
            "            adx = np.nan_to_num(adx_raw.get('adx', np.zeros(n))).astype(np.float64)\n"
            "        else:\n"
            "            adx = np.full(n, 0.0)\n"
            "        df.loc[:, 'bb_stop_long'] = np.nan\n"
            "        df.loc[:, 'bb_tp_long'] = np.nan\n"
            "        df.loc[:, 'bb_stop_short'] = np.nan\n"
            "        df.loc[:, 'bb_tp_short'] = np.nan\n"
            "        bull = direction > 0\n"
            "        bear = direction < 0\n"
            "        bull_prev = np.roll(bull, 1)\n"
            "        bear_prev = np.roll(bear, 1)\n"
            "        bull_prev[:1] = False\n"
            "        bear_prev[:1] = False\n"
            "        long_entry = bull & (~bull_prev) & (adx >= adx_threshold)\n"
            "        short_entry = bear & (~bear_prev) & (adx >= adx_threshold)\n"
            "        long_entry[:warmup] = False\n"
            "        short_entry[:warmup] = False\n"
            "        signals[long_entry] = 1.0\n"
            "        signals[short_entry] = -1.0\n"
            "        df.loc[long_entry, 'bb_stop_long'] = close[long_entry] - stop_atr_mult * atr[long_entry]\n"
            "        df.loc[long_entry, 'bb_tp_long'] = close[long_entry] + tp_atr_mult * atr[long_entry]\n"
            "        df.loc[short_entry, 'bb_stop_short'] = close[short_entry] + stop_atr_mult * atr[short_entry]\n"
            "        df.loc[short_entry, 'bb_tp_short'] = close[short_entry] - tp_atr_mult * atr[short_entry]\n"
        )
    elif effective_variant == 2:
        # ── Variante 2: momentum RSI/EMA ──
        for needed in ("rsi", "ema", "atr"):
            if needed not in safe_used:
                safe_used.append(needed)
        default_params.setdefault("rsi_mid", 50.0)
        default_params.setdefault("ema_period", 50)
        signals_body = (
            "        rsi_mid = float(params.get('rsi_mid', 50.0))\n"
            "        stop_atr_mult = float(params.get('stop_atr_mult', 1.5))\n"
            "        tp_atr_mult = float(params.get('tp_atr_mult', 3.0))\n"
            "        close = np.nan_to_num(df['close'].values.astype(np.float64))\n"
            "        if len(close) < warmup + 2:\n"
            "            return signals\n"
            "        atr_raw = indicators.get('atr')\n"
            "        if isinstance(atr_raw, np.ndarray):\n"
            "            atr = np.nan_to_num(atr_raw.astype(np.float64))\n"
            "        else:\n"
            "            atr = np.full(n, 0.0)\n"
            "        rsi_raw = indicators.get('rsi')\n"
            "        if isinstance(rsi_raw, np.ndarray):\n"
            "            rsi = np.nan_to_num(rsi_raw.astype(np.float64))\n"
            "        else:\n"
            "            rsi = np.full(n, 50.0)\n"
            "        ema_raw = indicators.get('ema')\n"
            "        if isinstance(ema_raw, np.ndarray):\n"
            "            ema = np.nan_to_num(ema_raw.astype(np.float64))\n"
            "        else:\n"
            "            ema = close.copy()\n"
            "        df.loc[:, 'bb_stop_long'] = np.nan\n"
            "        df.loc[:, 'bb_tp_long'] = np.nan\n"
            "        df.loc[:, 'bb_stop_short'] = np.nan\n"
            "        df.loc[:, 'bb_tp_short'] = np.nan\n"
            "        long_cond = (rsi > rsi_mid) & (close > ema)\n"
            "        short_cond = (rsi < rsi_mid) & (close < ema)\n"
            "        long_prev = np.roll(long_cond, 1)\n"
            "        short_prev = np.roll(short_cond, 1)\n"
            "        long_prev[:1] = False\n"
            "        short_prev[:1] = False\n"
            "        long_entry = long_cond & (~long_prev)\n"
            "        short_entry = short_cond & (~short_prev)\n"
            "        long_entry[:warmup] = False\n"
            "        short_entry[:warmup] = False\n"
            "        signals[long_entry] = 1.0\n"
            "        signals[short_entry] = -1.0\n"
            "        df.loc[long_entry, 'bb_stop_long'] = close[long_entry] - stop_atr_mult * atr[long_entry]\n"
            "        df.loc[long_entry, 'bb_tp_long'] = close[long_entry] + tp_atr_mult * atr[long_entry]\n"
            "        df.loc[short_entry, 'bb_stop_short'] = close[short_entry] + stop_atr_mult * atr[short_entry]\n"
            "        df.loc[short_entry, 'bb_tp_short'] = close[short_entry] - tp_atr_mult * atr[short_entry]\n"
        )
    elif effective_variant == 3:
        # ── Variante 3: breakout Donchian/ADX ──
        for needed in ("donchian", "adx", "atr"):
            if needed not in safe_used:
                safe_used.append(needed)
        default_params.setdefault("adx_threshold", 18.0)
        signals_body = (
            "        stop_atr_mult = float(params.get('stop_atr_mult', 1.5))\n"
            "        tp_atr_mult = float(params.get('tp_atr_mult', 3.0))\n"
            "        adx_threshold = float(params.get('adx_threshold', 18.0))\n"
            "        close = np.nan_to_num(df['close'].values.astype(np.float64))\n"
            "        if len(close) < warmup + 2:\n"
            "            return signals\n"
            "        atr_raw = indicators.get('atr')\n"
            "        if isinstance(atr_raw, np.ndarray):\n"
            "            atr = np.nan_to_num(atr_raw.astype(np.float64))\n"
            "        else:\n"
            "            atr = np.full(n, 0.0)\n"
            "        dc_raw = indicators.get('donchian')\n"
            "        if isinstance(dc_raw, dict):\n"
            "            dc_upper = np.nan_to_num(dc_raw.get('upper', np.full(n, np.inf)).astype(np.float64))\n"
            "            dc_lower = np.nan_to_num(dc_raw.get('lower', np.full(n, -np.inf)).astype(np.float64))\n"
            "        else:\n"
            "            dc_upper = np.full(n, np.inf)\n"
            "            dc_lower = np.full(n, -np.inf)\n"
            "        adx_raw = indicators.get('adx')\n"
            "        if isinstance(adx_raw, dict):\n"
            "            adx = np.nan_to_num(adx_raw.get('adx', np.zeros(n))).astype(np.float64)\n"
            "        else:\n"
            "            adx = np.full(n, 0.0)\n"
            "        df.loc[:, 'bb_stop_long'] = np.nan\n"
            "        df.loc[:, 'bb_tp_long'] = np.nan\n"
            "        df.loc[:, 'bb_stop_short'] = np.nan\n"
            "        df.loc[:, 'bb_tp_short'] = np.nan\n"
            "        dc_upper_prev = np.roll(dc_upper, 1)\n"
            "        dc_lower_prev = np.roll(dc_lower, 1)\n"
            "        dc_upper_prev[:1] = dc_upper[:1]\n"
            "        dc_lower_prev[:1] = dc_lower[:1]\n"
            "        long_cond = (close > dc_upper_prev) & (adx >= adx_threshold)\n"
            "        short_cond = (close < dc_lower_prev) & (adx >= adx_threshold)\n"
            "        long_prev = np.roll(long_cond, 1)\n"
            "        short_prev = np.roll(short_cond, 1)\n"
            "        long_prev[:1] = False\n"
            "        short_prev[:1] = False\n"
            "        long_entry = long_cond & (~long_prev)\n"
            "        short_entry = short_cond & (~short_prev)\n"
            "        long_entry[:warmup] = False\n"
            "        short_entry[:warmup] = False\n"
            "        signals[long_entry] = 1.0\n"
            "        signals[short_entry] = -1.0\n"
            "        df.loc[long_entry, 'bb_stop_long'] = close[long_entry] - stop_atr_mult * atr[long_entry]\n"
            "        df.loc[long_entry, 'bb_tp_long'] = close[long_entry] + tp_atr_mult * atr[long_entry]\n"
            "        df.loc[short_entry, 'bb_stop_short'] = close[short_entry] + stop_atr_mult * atr[short_entry]\n"
            "        df.loc[short_entry, 'bb_tp_short'] = close[short_entry] - tp_atr_mult * atr[short_entry]\n"
        )
    else:
        # ── Variante 0: mean-reversion RSI/Bollinger ──
        for needed in ("rsi", "bollinger", "atr"):
            if needed not in safe_used:
                safe_used.append(needed)
        default_params.setdefault("rsi_oversold", 30)
        default_params.setdefault("rsi_overbought", 70)
        signals_body = (
            "        rsi_oversold = float(params.get('rsi_oversold', 30))\n"
            "        rsi_overbought = float(params.get('rsi_overbought', 70))\n"
            "        stop_atr_mult = float(params.get('stop_atr_mult', 1.5))\n"
            "        tp_atr_mult = float(params.get('tp_atr_mult', 3.0))\n"
            "        close = np.nan_to_num(df['close'].values.astype(np.float64))\n"
            "        if len(close) < warmup + 2:\n"
            "            return signals\n"
            "        atr_raw = indicators.get('atr')\n"
            "        if isinstance(atr_raw, np.ndarray):\n"
            "            atr = np.nan_to_num(atr_raw.astype(np.float64))\n"
            "        else:\n"
            "            atr = np.full(n, 0.0)\n"
            "        rsi_raw = indicators.get('rsi')\n"
            "        bb_raw = indicators.get('bollinger')\n"
            "        has_rsi = isinstance(rsi_raw, np.ndarray)\n"
            "        has_bb = isinstance(bb_raw, dict)\n"
            "        if has_rsi:\n"
            "            rsi = np.nan_to_num(rsi_raw.astype(np.float64))\n"
            "        else:\n"
            "            rsi = np.full(n, 50.0)\n"
            "        if has_bb:\n"
            "            bb_lower = np.nan_to_num(bb_raw.get('lower', np.zeros(n)).astype(np.float64))\n"
            "            bb_upper = np.nan_to_num(bb_raw.get('upper', np.zeros(n)).astype(np.float64))\n"
            "        else:\n"
            "            bb_lower = np.full(n, 0.0)\n"
            "            bb_upper = np.full(n, np.inf)\n"
            "        df.loc[:, 'bb_stop_long'] = np.nan\n"
            "        df.loc[:, 'bb_tp_long'] = np.nan\n"
            "        df.loc[:, 'bb_stop_short'] = np.nan\n"
            "        df.loc[:, 'bb_tp_short'] = np.nan\n"
            "        long_cond = (rsi < rsi_oversold) & (close <= bb_lower)\n"
            "        short_cond = (rsi > rsi_overbought) & (close >= bb_upper)\n"
            "        long_prev = np.roll(long_cond, 1)\n"
            "        short_prev = np.roll(short_cond, 1)\n"
            "        long_prev[:1] = False\n"
            "        short_prev[:1] = False\n"
            "        long_entry = long_cond & (~long_prev)\n"
            "        short_entry = short_cond & (~short_prev)\n"
            "        long_entry[:warmup] = False\n"
            "        short_entry[:warmup] = False\n"
            "        signals[long_entry] = 1.0\n"
            "        signals[short_entry] = -1.0\n"
            "        df.loc[long_entry, 'bb_stop_long'] = close[long_entry] - stop_atr_mult * atr[long_entry]\n"
            "        df.loc[long_entry, 'bb_tp_long'] = close[long_entry] + tp_atr_mult * atr[long_entry]\n"
            "        df.loc[short_entry, 'bb_stop_short'] = close[short_entry] + stop_atr_mult * atr[short_entry]\n"
            "        df.loc[short_entry, 'bb_tp_short'] = close[short_entry] - tp_atr_mult * atr[short_entry]\n"
        )

    # ── Partie commune: assemblage du code final ──
    default_params_literal = _format_python_dict_literal(default_params)
    default_params_lines = default_params_literal.splitlines() or ["{}"]
    if len(default_params_lines) == 1:
        default_params_block = f"        return {default_params_lines[0]}\n\n"
    else:
        default_params_block = "        return " + default_params_lines[0] + "\n"
        default_params_block += "".join(
            f"        {line}\n" for line in default_params_lines[1:]
        )
        default_params_block += "\n"
    direction_block = ""
    if direction_constraint == "long_only":
        direction_block = (
            "        # Objective constraint: long-only\n"
            "        signals[signals < 0.0] = 0.0\n"
        )
    elif direction_constraint == "short_only":
        direction_block = (
            "        # Objective constraint: short-only\n"
            "        signals[signals > 0.0] = 0.0\n"
        )

    return (
        "from typing import Any, Dict, List\n\n"
        "import numpy as np\n"
        "import pandas as pd\n\n"
        "from utils.parameters import ParameterSpec\n"
        "from strategies.base import StrategyBase\n\n\n"
        f"class {GENERATED_CLASS_NAME}(StrategyBase):\n"
        "    def __init__(self):\n"
        f"        super().__init__(name=\"{strategy_name}\")\n\n"
        "    @property\n"
        "    def required_indicators(self) -> List[str]:\n"
        f"        return {safe_used!r}\n\n"
        "    @property\n"
        "    def default_params(self) -> Dict[str, Any]:\n"
        f"{default_params_block}"
        "    @property\n"
        "    def parameter_specs(self) -> Dict[str, ParameterSpec]:\n"
        "        return {}\n\n"
        "    def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series:\n"
        "        n = len(df)\n"
        "        signals = pd.Series(0.0, index=df.index, dtype=np.float64)\n"
        "        warmup = int(params.get('warmup', 50))\n"
        f"{signals_body}"
        f"{direction_block}"
        "        signals.iloc[:warmup] = 0.0\n"
        "        return signals\n"
    )


# Prefixes de ligne indiquant du vrai code Python (pas du texte de docstring)
_CODE_LINE_STARTS = (
    "def ", "class ", "@", "return ", "import ", "from ",
    "self.", "super(", "if ", "for ", "while ", "try:", "with ",
    "raise ", "yield ", "assert ", "pass", "break", "continue",
    "signals", "result", "n =", "n=",
)


def _strip_docstrings(code: str) -> str:
    """Supprime tous les blocs triple-quoted, y compris non terminés.

    Utilise une heuristique pour détecter la fin d'un docstring non terminé:
    si une ligne ressemble à du code Python (def, class, @, return, ...),
    on considère que le docstring est terminé et on préserve la ligne.
    """
    lines = code.split("\n")
    result = []
    in_docstring = False

    for line in lines:
        stripped = line.strip()

        if in_docstring:
            # Fermeture explicite du docstring
            if '"""' in stripped or "'''" in stripped:
                in_docstring = False
                continue
            # Heuristique: si la ligne ressemble à du code, le docstring
            # non terminé est considéré comme fini → préserver la ligne
            if stripped.startswith(_CODE_LINE_STARTS):
                in_docstring = False
                result.append(line)
                continue
            # Toujours dans le docstring → ignorer
            continue

        # Détecter l'ouverture d'un triple-quote
        for tq in ['"""', "'''"]:
            if tq in stripped:
                cnt = stripped.count(tq)
                if cnt >= 2:
                    # Docstring fermé sur la même ligne → ignorer la ligne
                    break
                # Docstring multi-ligne ouvert → commencer à ignorer
                in_docstring = True
                break
        else:
            # Pas de triple-quote → conserver la ligne
            result.append(line)

    return "\n".join(result)


def _normalize_proposal_keys(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise les clés JSON d'une proposition LLM (case-insensitive).

    Certains modèles locaux retournent des clés en casse mixte
    (ex: ``used_indiCATORS``, ``default_PARAMS``).  Cette fonction
    mappe chaque clé vers sa version canonique attendue.
    """
    if not proposal:
        return proposal

    _CANONICAL = {
        "strategy_name": "strategy_name",
        "hypothesis": "hypothesis",
        "change_type": "change_type",
        "used_indicators": "used_indicators",
        "indicator_params": "indicator_params",
        "entry_long_logic": "entry_long_logic",
        "entry_short_logic": "entry_short_logic",
        "exit_logic": "exit_logic",
        "risk_management": "risk_management",
        "default_params": "default_params",
        "parameter_specs": "parameter_specs",
    }
    # Build lowercase → canonical mapping
    lower_map = {k.lower(): v for k, v in _CANONICAL.items()}

    normalized: Dict[str, Any] = {}
    for key, value in proposal.items():
        canonical = lower_map.get(key.lower().replace(" ", "_"), key)
        normalized[canonical] = value

    # Canonicaliser parameter_specs et aliases de clés
    if isinstance(normalized.get("parameter_specs"), dict):
        normalized_specs: Dict[str, Any] = {}
        for param_name, raw_spec in normalized["parameter_specs"].items():
            if not isinstance(raw_spec, dict):
                normalized_specs[param_name] = raw_spec
                continue
            spec_lower = {
                str(k).strip().lower().replace(" ", "_"): v
                for k, v in raw_spec.items()
            }
            normalized_specs[param_name] = {
                "min": spec_lower.get("min", spec_lower.get("min_val", spec_lower.get("min_value"))),
                "max": spec_lower.get("max", spec_lower.get("max_val", spec_lower.get("max_value"))),
                "default": spec_lower.get("default"),
                "type": spec_lower.get("type", spec_lower.get("param_type")),
                "step": spec_lower.get("step"),
            }
        normalized["parameter_specs"] = normalized_specs

    # Normaliser change_type (certains LLM retournent "logic|params|both")
    if "change_type" in normalized:
        normalized["change_type"] = _normalize_change_type(
            normalized.get("change_type", "")
        )
    else:
        normalized["change_type"] = "logic"

    if "hypothesis" not in normalized:
        normalized["hypothesis"] = ""

    return normalized


def _flatten_nested_logic(val: Any) -> str:
    """Flatten a nested dict/list logic field into a plain string.

    LLMs sometimes output structures like:
      {"cross_any(close, donchian.middle) or adx < 25": {"description": "...", "indicators": [...]}}
    or nested "logic_expression" keys repeated multiple times.
    This extracts the meaningful rule as a plain string.
    """
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return " AND ".join(str(item) for item in val if item)
    if not isinstance(val, dict):
        return str(val)

    # Strategy 1: look for a "description" key anywhere in the nested structure
    desc = val.get("description", "")
    if isinstance(desc, str) and desc.strip():
        return desc.strip()

    # Strategy 2: if the dict has logic-like keys (conditions as keys), take the first one
    # e.g. {"close > bollinger.upper AND rsi > 50": {...}}
    for key in val:
        if key in ("logic_expression", "indicators", "description"):
            continue
        # The key itself is likely the logic expression
        inner = val[key]
        if isinstance(inner, dict):
            inner_desc = inner.get("description", "")
            if isinstance(inner_desc, str) and inner_desc.strip():
                return inner_desc.strip()
        # Fall back to using the key as the logic string
        return str(key).strip()

    # Strategy 3: recursively flatten the first nested dict value
    for key, inner in val.items():
        if isinstance(inner, dict):
            result = _flatten_nested_logic(inner)
            if result:
                return result

    # Last resort: serialize to compact string
    return json.dumps(val, ensure_ascii=False)[:200]


def _sanitize_proposal_payload(
    proposal: Dict[str, Any],
    *,
    available_indicators: List[str],
    objective: str = "",
    direction_constraint: Optional[str] = None,
) -> Dict[str, Any]:
    """Nettoie/sauve une proposition LLM sans relâcher le contrat final."""
    if not isinstance(proposal, dict):
        return {}

    allowed = {
        "strategy_name",
        "hypothesis",
        "change_type",
        "used_indicators",
        "indicator_params",
        "entry_long_logic",
        "entry_short_logic",
        "exit_logic",
        "risk_management",
        "default_params",
        "parameter_specs",
        "direction_constraint",
    }
    cleaned: Dict[str, Any] = {
        k: v for k, v in proposal.items() if k in allowed
    }

    # Fallbacks champs fréquents
    if not cleaned.get("entry_long_logic"):
        cleaned["entry_long_logic"] = str(
            proposal.get("long_logic")
            or proposal.get("long_entry")
            or proposal.get("long")
            or ""
        ).strip()
    if not cleaned.get("entry_short_logic"):
        cleaned["entry_short_logic"] = str(
            proposal.get("short_logic")
            or proposal.get("short_entry")
            or proposal.get("short")
            or ""
        ).strip()
    if not cleaned.get("exit_logic"):
        cleaned["exit_logic"] = "sortie sur signal inverse"

    if not cleaned.get("risk_management"):
        risk_raw = proposal.get("risk") or proposal.get("risk_rules")
        if isinstance(risk_raw, (dict, list)):
            cleaned["risk_management"] = json.dumps(risk_raw, ensure_ascii=False)
        else:
            cleaned["risk_management"] = str(risk_raw or "ATR stop/take-profit")

    # Indicateurs: normalisation + filtrage registre
    known = {x.lower() for x in available_indicators}
    used = cleaned.get("used_indicators", [])
    normalized_used: List[str] = []
    if isinstance(used, list):
        for item in used:
            if not isinstance(item, str):
                continue
            ind = item.strip().lower()
            if ind and ind in known and ind not in normalized_used:
                normalized_used.append(ind)
    if not normalized_used:
        normalized_used = ["atr"] if "atr" in known else sorted(known)[:2]
    cleaned["used_indicators"] = normalized_used

    # Params sécurisés (diagnostics ruine/no-trades)
    default_params = cleaned.get("default_params")
    if not isinstance(default_params, dict):
        default_params = {}
    default_params["leverage"] = min(2, max(1, int(default_params.get("leverage", 1) or 1)))
    default_params.setdefault("stop_atr_mult", 1.5)
    default_params.setdefault("tp_atr_mult", 3.0)
    default_params.setdefault("warmup", 50)
    cleaned["default_params"] = default_params

    specs = cleaned.get("parameter_specs")
    if not isinstance(specs, dict):
        specs = {}
    if "leverage" not in specs:
        specs["leverage"] = {"min": 1, "max": 2, "default": default_params["leverage"], "type": "int", "step": 1}
    if "stop_atr_mult" not in specs:
        specs["stop_atr_mult"] = {"min": 1.0, "max": 2.0, "default": default_params["stop_atr_mult"], "type": "float", "step": 0.1}
    if "tp_atr_mult" not in specs:
        specs["tp_atr_mult"] = {"min": 2.0, "max": 4.5, "default": default_params["tp_atr_mult"], "type": "float", "step": 0.1}
    cleaned["parameter_specs"] = specs

    cleaned["change_type"] = _normalize_change_type(cleaned.get("change_type", "logic"))
    cleaned["hypothesis"] = str(cleaned.get("hypothesis", "") or "").strip()
    if not cleaned["hypothesis"]:
        cleaned["hypothesis"] = "Ajustement structurel basé sur le diagnostic précédent."

    cleaned["strategy_name"] = str(cleaned.get("strategy_name", "builder_strategy") or "builder_strategy").strip()
    effective_direction = str(
        direction_constraint or _infer_direction_constraint_from_objective(objective)
    ).strip().lower()
    if effective_direction not in {"long_only", "short_only", "long_short"}:
        effective_direction = "long_short"
    cleaned["direction_constraint"] = effective_direction

    # Flatten nested JSON in logic fields: LLMs sometimes output dicts/lists
    # instead of plain strings for entry/exit logic (e.g. nested logic_expression).
    for key in ("entry_long_logic", "entry_short_logic", "exit_logic"):
        val = cleaned.get(key, "")
        if isinstance(val, dict):
            # Extract the first key or description from the nested dict
            val = _flatten_nested_logic(val)
        elif isinstance(val, list):
            # Join list items into a single string
            val = " AND ".join(str(item) for item in val if item)
        cleaned[key] = str(val or "").strip()

    # Scrub proposal logic fields: rewrite pandas idioms into numpy/vectorized hints.
    # This catches cases where the LLM embeds .iloc / df['signal'] / .rolling in
    # natural-language logic descriptions, which later leak into code generation.
    _PROPOSAL_SCRUB_PATTERNS = [
        (re.compile(r"\.iloc\b"), " (use numpy boolean indexing)"),
        (re.compile(r"\.loc\b"), " (use numpy boolean indexing)"),
        (re.compile(r"\.rolling\b"), " (pre-computed by indicator)"),
        (re.compile(r"\.shift\b"), " (use np.roll)"),
        (re.compile(r"\.ewm\b"), " (pre-computed by indicator)"),
        (re.compile(r"df\s*\[\s*['\"]signal['\"]\s*\]"), "signals array"),
    ]
    for key in ("entry_long_logic", "entry_short_logic", "exit_logic"):
        val = cleaned.get(key, "")
        if not isinstance(val, str):
            continue
        for pat, repl in _PROPOSAL_SCRUB_PATTERNS:
            val = pat.sub(repl, val)
        cleaned[key] = val

    if effective_direction == "long_only":
        cleaned["entry_short_logic"] = ""
    elif effective_direction == "short_only":
        cleaned["entry_long_logic"] = ""

    return cleaned


def _is_empty_proposal(proposal: Dict[str, Any]) -> bool:
    """Vérifie si une proposition LLM est vide ou inutilisable."""
    if not proposal:
        return True
    hyp = str(proposal.get("hypothesis", "")).strip()
    inds = proposal.get("used_indicators", [])
    if not hyp or hyp in ("—", "-", "N/A", ""):
        return True
    if not inds:
        return True
    return False


def _normalize_change_type(change_type: Any) -> str:
    """Normalise le type de changement dans {logic, params, both, accept}."""
    raw = str(change_type or "").strip().lower()
    if raw in {"logic", "params", "both", "accept"}:
        return raw
    if "param" in raw:
        return "params"
    if "logic" in raw:
        return "logic"
    if "accept" in raw:
        return "accept"
    return "logic"


def _build_deterministic_proposal_fallback(
    *,
    objective: str,
    available_indicators: List[str],
    last_iteration: Optional["BuilderIteration"] = None,
) -> Dict[str, Any]:
    """Construit une proposition contractuelle minimale quand le LLM dérape."""
    known = [x.strip().lower() for x in available_indicators if isinstance(x, str) and x.strip()]
    preferred = [
        x for x in ["rsi", "ema", "atr", "bollinger", "supertrend", "adx", "stochastic"]
        if x in known
    ]
    used = preferred[:3] if len(preferred) >= 3 else (preferred or known[:2] or ["atr"])

    change_type = "logic"
    if last_iteration and (last_iteration.diagnostic_category or "").strip().lower() in {"approaching_target", "stable_positive"}:
        change_type = "params"

    return {
        "strategy_name": "builder_strategy",
        "hypothesis": (
            "Fallback contractuel: proposition générée automatiquement pour maintenir "
            "la progression quand la sortie LLM n'est pas exploitable."
        ),
        "change_type": change_type,
        "used_indicators": used,
        "entry_long_logic": "Entrée long si momentum haussier confirmé et risque contrôlé.",
        "entry_short_logic": "Entrée short si momentum baissier confirmé et risque contrôlé.",
        "exit_logic": "Sortie sur signal inverse ou invalidation momentum.",
        "risk_management": "Leverage modéré, stop ATR, take-profit ATR.",
        "default_params": {
            "leverage": 1,
            "stop_atr_mult": 1.5,
            "tp_atr_mult": 3.0,
            "warmup": 50,
        },
        "parameter_specs": {
            "leverage": {"min": 1, "max": 2, "default": 1, "type": "int", "step": 1},
            "stop_atr_mult": {"min": 1.0, "max": 2.0, "default": 1.5, "type": "float", "step": 0.1},
            "tp_atr_mult": {"min": 2.0, "max": 4.5, "default": 3.0, "type": "float", "step": 0.1},
        },
    }


def _policy_change_type_override(
    *,
    session: "BuilderSession",
    last_iteration: Optional["BuilderIteration"],
) -> Optional[str]:
    """Force un type de modification cohérent avec le diagnostic récent.

    Objectif: éviter les oscillations `both` quand le problème est clairement
    structurel (ruined/no_trades/etc.).
    """
    if last_iteration is None:
        return None

    cat = str(getattr(last_iteration, "diagnostic_category", "") or "").strip().lower()
    sev = str(
        (getattr(last_iteration, "diagnostic_detail", {}) or {}).get("severity", "")
    ).strip().lower()

    # Pattern oscillant fréquent: ruined <-> no_trades
    recent = [
        str(getattr(it, "diagnostic_category", "") or "").strip().lower()
        for it in (session.iterations[-3:] if session.iterations else [])
        if str(getattr(it, "diagnostic_category", "") or "").strip()
    ]
    if len(recent) >= 2 and set(recent[-2:]).issubset({"ruined", "no_trades"}):
        return "logic"

    logic_cats = {
        "ruined",
        "no_trades",
        "overtrading",
        "wrong_direction",
        "high_drawdown",
        "needs_work",
    }
    param_cats = {"approaching_target", "marginal", "target_reached"}

    if cat in logic_cats:
        return "logic"
    if cat in param_cats and sev in {"info", "success"}:
        return "params"
    return None


def _is_placeholder_text(value: Any) -> bool:
    """Détecte un champ placeholder/générique au lieu d'une vraie consigne."""
    text = str(value or "").strip().lower()
    if text in _PROPOSAL_PLACEHOLDER_VALUES:
        return True
    return (
        "placeholder" in text
        or text.startswith("example")
        or text.startswith("exemple")
        or "to achieve and why" in text
    )


def _proposal_issues(proposal: Dict[str, Any]) -> List[str]:
    """Retourne la liste des raisons rendant une proposition invalide."""
    issues: List[str] = []
    if not proposal:
        issues.append("empty_payload")
        return issues

    allowed_top_keys = {
        "strategy_name",
        "hypothesis",
        "change_type",
        "used_indicators",
        "indicator_params",
        "entry_long_logic",
        "entry_short_logic",
        "exit_logic",
        "risk_management",
        "default_params",
        "parameter_specs",
        "direction_constraint",
    }
    required_top_keys = set(_BUILDER_PROPOSAL_REQUIRED_KEYS)

    unknown_keys = sorted(set(proposal.keys()) - allowed_top_keys)
    if unknown_keys:
        issues.append("json_additional_properties_root")

    missing_keys = sorted(k for k in required_top_keys if k not in proposal)
    if missing_keys:
        issues.append("json_missing_required")

    hyp = str(proposal.get("hypothesis", "")).strip()
    inds = proposal.get("used_indicators", [])
    if not hyp or hyp in ("—", "-", "N/A", ""):
        issues.append("missing_hypothesis")
    if not isinstance(inds, list) or not inds:
        issues.append("missing_used_indicators")

    critical_fields = (
        "hypothesis",
        "entry_long_logic",
        "exit_logic",
        "risk_management",
    )
    for key in critical_fields:
        if _is_placeholder_text(proposal.get(key, "")):
            issues.append(f"placeholder_{key}")

    default_params = proposal.get("default_params")
    if default_params is not None and not isinstance(default_params, dict):
        issues.append("default_params_not_dict")

    parameter_specs = proposal.get("parameter_specs")
    if parameter_specs is not None and not isinstance(parameter_specs, dict):
        issues.append("parameter_specs_not_dict")
    elif isinstance(parameter_specs, dict):
        allowed_spec_keys = {"min", "max", "default", "type", "step"}
        for param_name, spec in parameter_specs.items():
            if not isinstance(spec, dict):
                issues.append("parameter_spec_item_not_dict")
                continue
            extra_spec_keys = set(spec.keys()) - allowed_spec_keys
            if extra_spec_keys:
                issues.append("parameter_spec_additional_properties")
            # strict minimum schema
            for required in ("min", "max", "default", "type"):
                if spec.get(required) is None:
                    issues.append("parameter_spec_missing_required")
                    break
            ptype = str(spec.get("type", "")).strip().lower()
            if ptype and ptype not in {"int", "float", "bool"}:
                issues.append("parameter_spec_invalid_type")
            try:
                min_v = float(spec.get("min"))
                max_v = float(spec.get("max"))
                if min_v > max_v:
                    issues.append("parameter_spec_min_gt_max")
            except Exception:
                issues.append("parameter_spec_non_numeric_bounds")
            if "step" in spec and spec.get("step") is not None:
                try:
                    step = float(spec.get("step"))
                    if step <= 0:
                        issues.append("parameter_spec_invalid_step")
                except Exception:
                    issues.append("parameter_spec_invalid_step")

    ct = _normalize_change_type(proposal.get("change_type", "logic"))
    if ct not in ("logic", "params", "both", "accept"):
        issues.append("invalid_change_type")

    # Dédupliquer en conservant l'ordre
    dedup: List[str] = []
    for issue in issues:
        if issue not in dedup:
            dedup.append(issue)
    return dedup


def _proposal_has_placeholder_fields(proposal: Dict[str, Any]) -> bool:
    """Détecte les placeholders sur les champs critiques d'une proposition."""
    critical_fields = (
        "hypothesis",
        "entry_long_logic",
        "entry_short_logic",
        "exit_logic",
        "risk_management",
    )
    for key in critical_fields:
        if _is_placeholder_text(proposal.get(key, "")):
            return True
    return False


def _is_invalid_proposal(proposal: Dict[str, Any]) -> bool:
    """Validation minimale d'une proposition avant phase code."""
    return bool(_proposal_issues(proposal))


def _proposal_error_code(issues: List[str]) -> str:
    """Mappe les issues de proposition vers un code d'erreur stable."""
    if not issues:
        return ""
    joined = "|".join(issues)
    if "json_" in joined or "parameter_spec_" in joined:
        return ERR_JSON
    if "parameter" in joined or "default_params" in joined:
        return ERR_PARAM
    return ERR_DSL


def _build_code_from_proposal_dsl(proposal: Dict[str, Any]) -> str:
    """Safe path déterministe JSON+DSL -> template Python.

    Réutilise le template déterministe interne pour garantir un code
    syntaxiquement valide, rapide à générer et conforme au contrat moteur.
    """
    return _build_deterministic_fallback_code(proposal, variant=0)


def _coerce_and_validate_signals_runtime(signals: Any, df: pd.DataFrame) -> pd.Series:
    """Valide runtime les signaux selon le contrat moteur (-1/0/+1)."""
    if isinstance(signals, pd.Series):
        series = signals.copy()
    else:
        series = pd.Series(signals)

    # Règle de priorité same-bar: last-write-wins si index dupliqué.
    if getattr(series.index, "has_duplicates", False):
        series = series.groupby(level=0).last()

    if not series.index.equals(df.index):
        series = series.reindex(df.index)

    if len(series) != len(df):
        raise ValueError(
            _err(
                ERR_SIG,
                f"Longueur des signaux invalide: {len(series)} != {len(df)}.",
            )
        )
    series = pd.to_numeric(series, errors="coerce").fillna(0.0).astype(float)

    # Priorité documentée: la valeur finale de la barre est l'intention exécutable.
    # Toute amplitude non standard est réduite à son signe pour conformité moteur.
    values = series.values
    coerced = np.where(values > 0, 1.0, np.where(values < 0, -1.0, 0.0))
    series = pd.Series(coerced, index=df.index, dtype=np.float64)

    unique = set(np.unique(series.values).tolist())
    if not unique.issubset({-1.0, 0.0, 1.0}):
        raise ValueError(
            _err(ERR_SIG, f"Valeurs signaux hors contrat détectées: {sorted(unique)}")
        )

    return series


def _is_empty_code(code: str) -> bool:
    """Vérifie si le code généré est vide ou trivial."""
    stripped = code.strip()
    if not stripped:
        return True
    return len(stripped.splitlines()) < MIN_CODE_LINES


def _looks_like_python_code(text: str) -> bool:
    """Heuristique: détecte un contenu ressemblant à du code Python."""
    if not text:
        return False
    lowered = text.lower()
    markers = (
        "```python",
        "class ",
        "def ",
        "import ",
        "from ",
        "return ",
        "np.",
        "pd.",
    )
    return any(m in lowered for m in markers)


def _looks_like_json_object(text: str) -> bool:
    """Heuristique: détecte un contenu ressemblant à un objet JSON."""
    if not text:
        return False
    stripped = text.strip().lower()
    if stripped.startswith("```json"):
        return True
    return stripped.startswith("{") and stripped.endswith("}")


def _looks_like_strategy_code(raw_text: str, code: str) -> bool:
    """Validation heuristique du contenu attendu en phase code."""
    if _is_empty_code(code):
        return False
    if _looks_like_json_object(raw_text) and not _looks_like_python_code(raw_text):
        return False

    lowered = code.lower()
    return "class " in lowered and "generate_signals" in lowered


def _classify_raw_response(text: str) -> str:
    """Retourne la nature d'une réponse brute LLM pour debug de phase."""
    if not text or not text.strip():
        return "empty"
    if _looks_like_json_object(text):
        return "json"
    if _looks_like_python_code(text):
        return "python"
    return "text"


def _extract_required_indicators_signature(code: str) -> tuple[str, ...]:
    """Retourne une signature stable des required_indicators depuis le code."""
    try:
        tree = ast.parse(code)
    except Exception:
        return tuple()

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == GENERATED_CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "required_indicators":
                    for stmt in item.body:
                        if isinstance(stmt, ast.Return):
                            try:
                                value = ast.literal_eval(stmt.value)
                            except Exception:
                                return tuple()
                            if isinstance(value, (list, tuple)):
                                normalized = [str(v) for v in value]
                                return tuple(sorted(normalized))
    return tuple()


def _extract_generate_signals_signature(code: str) -> str:
    """Retourne une signature AST du corps de generate_signals."""
    try:
        tree = ast.parse(code)
    except Exception:
        return ""

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == GENERATED_CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "generate_signals":
                    return ast.dump(
                        ast.Module(body=item.body, type_ignores=[]),
                        include_attributes=False,
                    )
    return ""


def _params_only_contract_respected(previous_code: str, new_code: str) -> tuple[bool, str]:
    """Vérifie qu'une itération params-only n'a pas modifié la logique."""
    prev_inds = _extract_required_indicators_signature(previous_code)
    new_inds = _extract_required_indicators_signature(new_code)
    if prev_inds and new_inds and prev_inds != new_inds:
        return (
            False,
            f"required_indicators modifiés: avant={prev_inds} après={new_inds}",
        )

    prev_sig = _extract_generate_signals_signature(previous_code)
    new_sig = _extract_generate_signals_signature(new_code)
    if prev_sig and new_sig and prev_sig != new_sig:
        return (
            False,
            "generate_signals modifié alors que change_type=params",
        )

    return True, ""


def _format_python_dict_literal(data: Dict[str, Any]) -> str:
    """Formate un dict Python de manière stable pour insertion dans le code."""
    return pprint.pformat(data, width=88, sort_dicts=True, compact=False)


def _rewrite_default_params_from_proposal(
    previous_code: str,
    proposal: Dict[str, Any],
) -> Optional[str]:
    """Réécrit uniquement default_params dans un code existant (mode params-only)."""
    default_params = proposal.get("default_params")
    if not isinstance(default_params, dict) or not default_params:
        return None

    pattern = re.compile(
        r"(?ms)^(\s*)(def\s+default_params\s*\(\s*self\s*\)\s*(?:->\s*[^:\n]+)?\s*:)\n"
        r".*?(?=^\1(?:def\s+|@property)|^\s*class\s+|\Z)"
    )
    match = pattern.search(previous_code)
    if not match:
        return None

    indent = match.group(1)
    def_header = match.group(2)
    body_indent = indent + "    "
    literal = _format_python_dict_literal(default_params)
    literal_lines = literal.splitlines() or ["{}"]

    if len(literal_lines) == 1:
        return_stmt = f"{body_indent}return {literal_lines[0]}\n"
    else:
        return_stmt = f"{body_indent}return {literal_lines[0]}\n"
        return_stmt += "".join(f"{body_indent}{line}\n" for line in literal_lines[1:])

    replacement = f"{indent}{def_header}\n{return_stmt}"

    patched = previous_code[:match.start()] + replacement + previous_code[match.end():]
    return patched


# ---------------------------------------------------------------------------
# Diagnostic déterministe
# ---------------------------------------------------------------------------

def compute_diagnostic(
    metrics: Dict[str, Any],
    iteration_history: List[Dict[str, Any]],
    target_sharpe: float = 1.0,
) -> Dict[str, Any]:
    """
    Diagnostic déterministe basé sur les métriques de backtest et l'historique.

    Classifie le problème principal, grade chaque dimension (profitabilité,
    risque, efficacité, qualité signaux), recommande le type de modification
    et fournit des actions concrètes.

    Le LLM reçoit ce diagnostic pré-calculé et se concentre sur la SOLUTION
    créative plutôt que sur l'identification du problème.
    """
    # --- Extraction sécurisée ---
    n = metrics.get("total_trades", 0) or 0
    sharpe = metrics.get("sharpe_ratio", 0) or 0
    sortino = metrics.get("sortino_ratio", 0) or 0
    calmar = metrics.get("calmar_ratio", 0) or 0
    ret = metrics.get("total_return_pct", 0) or 0
    dd = abs(metrics.get("max_drawdown_pct", 0) or 0)
    wr = metrics.get("win_rate_pct", 0) or 0
    pf = metrics.get("profit_factor", 0) or 0
    exp = metrics.get("expectancy", 0) or 0
    avg_w = metrics.get("avg_win", 0) or 0
    avg_l = abs(metrics.get("avg_loss", 0) or 0)
    vol = metrics.get("volatility_annual", 0) or 0
    _rr = metrics.get("risk_reward_ratio", 0) or 0  # noqa: F841

    # --- Score card A/B/C/D/F ---
    def _g(v, thresholds):
        for grade, thresh in thresholds:
            if v >= thresh:
                return grade
        return "F"

    sc = {
        "profitability": {
            "grade": _g(ret, [("A", 20), ("B", 5), ("C", 0), ("D", -20)]),
            "detail": f"Return {ret:+.1f}%, PF {pf:.2f}, Expectancy {exp:.2f}",
        },
        "risk": {
            "grade": _g(-dd, [("A", -10), ("B", -25), ("C", -40), ("D", -60)]),
            "detail": f"MaxDD {dd:.1f}%, Vol {vol:.1f}%",
        },
        "efficiency": {
            "grade": _g(sharpe, [("A", 1.5), ("B", 1.0), ("C", 0.5), ("D", 0)]),
            "detail": f"Sharpe {sharpe:.3f}, Sortino {sortino:.3f}, Calmar {calmar:.3f}",
        },
        "signal_quality": {
            "grade": _g(wr, [("A", 50), ("B", 40), ("C", 35), ("D", 25)]),
            "detail": f"WR {wr:.1f}%, Trades {n}, AvgW/L {avg_w:.2f}/{avg_l:.2f}",
        },
    }
    continuous_score = compute_continuous_builder_score(
        metrics,
        target_sharpe=target_sharpe,
    )

    # --- Catégorie principale (par gravité décroissante) ---
    if n == 0:
        cat, sev, ct = "no_trades", "critical", "logic"
        summary = "Aucun trade — conditions d'entrée trop restrictives"
        actions = [
            "Relâcher les seuils (RSI 70→65, Bollinger 2.0σ→1.5σ)",
            "Réduire le nombre de conditions AND combinées",
            "Vérifier NaN handling: np.nan_to_num() avant comparaison",
            "S'assurer que les signaux retournent 1.0/-1.0 (pas True/False)",
        ]
        donts = [
            "Ne PAS ajuster les paramètres numériques — problème structurel",
            "Ne PAS ajouter plus de conditions",
        ]
    elif n < 5:
        cat, sev, ct = "insufficient_trades", "warning", "logic"
        summary = f"Seulement {n} trade(s) — statistiquement insignifiant"
        actions = [
            "Relâcher la condition d'entrée la plus restrictive",
            "Vérifier que exit_logic ne ferme pas immédiatement",
            "Utiliser des seuils moins extrêmes (RSI 80→70, ADX 30→20)",
            "Simplifier: 1 indicateur puis ajouter filtres progressivement",
        ]
        donts = ["Ne PAS interpréter Sharpe/PF avec < 5 trades"]
    elif ret < -90 or dd > 90:
        cat, sev, ct = "ruined", "critical", "logic"
        summary = f"Compte ruiné (Return {ret:.0f}%, DD {dd:.0f}%)"
        actions = [
            "URGENT: Réduire leverage à 1-2× max",
            "URGENT: Ajouter stop-loss ATR (1.5-2× ATR)",
            "Vérifier si signaux LONG/SHORT sont inversés",
            "Repartir d'une logique minimale avec SL/TP obligatoires",
        ]
        donts = [
            "Ne PAS garder la même structure+paramètres ajustés",
            "Ne PAS augmenter le leverage",
        ]
    elif n > 300 and wr < 35:
        cat, sev, ct = "overtrading", "warning", "logic"
        summary = f"Suractivité ({n} trades, WR {wr:.0f}%)"
        actions = [
            "Ajouter filtre tendance (ADX > 25 OU direction EMA longue)",
            "Augmenter seuils pour garder les signaux les plus forts",
            "Dédupliquer: pas de signal identique consécutif",
            "Ajouter cooldown minimum entre trades (N barres)",
        ]
        donts = ["Ne PAS juste ajuster numériquement sans filtrer"]
    elif dd > 50:
        cat, sev, ct = "high_drawdown", "warning", "logic"
        summary = f"Drawdown excessif ({dd:.0f}%)"
        actions = [
            "Ajouter/resserrer stop-loss (ATR 1.5× ou % du prix)",
            "Ajouter take-profit (ATR 2-3×)",
            "Réduire leverage si > 2×",
            "Filtre volatilité: ne pas trader si ATR > percentile_80",
        ]
        donts = ["Ne PAS ignorer le drawdown pour maximiser le rendement"]
    elif ret < -20 and n > 20:
        cat, sev, ct = "wrong_direction", "warning", "logic"
        summary = f"Direction probablement inversée (Return {ret:.0f}%, {n} trades)"
        actions = [
            "DIAGNOSTIC: signaux peut-être inversés (1.0=SHORT?)",
            "Tester: inverser tous les signaux (*= -1)",
            "Vérifier conditions LONG = attente de hausse",
            "Revoir exit_logic: positions fermées au mauvais moment?",
        ]
        donts = ["Ne PAS augmenter les params — la direction est le problème"]
    elif pf < 0.8 and n > 20:
        cat, sev, ct = "losing_per_trade", "warning", "both"
        rr_str = f"AvgWin={avg_w:.2f} vs AvgLoss={avg_l:.2f}" if avg_w > 0 else ""
        summary = f"PF faible ({pf:.2f}) — perd par trade. {rr_str}"
        actions = [
            "Améliorer ratio R/R: TP plus loin OU SL plus serré",
            "Ajouter confirmation: 2ème indicateur avant entrée",
            "Filtrer marchés en range (ADX < 20 = ne pas trader)",
            "Optimiser timing: attendre pullback après signal",
        ]
        donts = ["Ne PAS augmenter le volume de trades pour compenser"]
    elif wr < 30 and n > 20 and pf >= 0.8:
        cat, sev, ct = "low_win_rate", "info", "both"
        summary = f"WR bas ({wr:.0f}%) mais PF acceptable ({pf:.2f})"
        actions = [
            "Si PF > 1: stratégie OK malgré WR — affiner paramètres",
            "Sinon: améliorer timing entrée avec confirmation",
            "Filtre tendance pour trader dans la direction dominante",
            "Sorties plus agressives (trailing stop, break-even)",
        ]
        donts = []
    elif 0 < ret < 5 and sharpe < 0.5 and n > 20:
        cat, sev, ct = "marginal", "info", "params"
        summary = f"Rentable mais marginal (Return {ret:.1f}%, Sharpe {sharpe:.3f})"
        actions = [
            "Focus paramètres: ajuster ±20% les périodes indicateurs",
            "Optimiser ratio SL/TP (levier le plus efficace)",
            "La logique produit des résultats positifs — NE PAS la casser",
            "Tester de légers changements de seuils d'entrée",
        ]
        donts = ["Ne PAS restructurer la logique — elle fonctionne"]
    elif sharpe >= target_sharpe:
        cat, sev, ct = "target_reached", "success", "accept"
        robust = n > 20 and dd < 40
        summary = f"Cible atteinte (Sharpe {sharpe:.3f} >= {target_sharpe})"
        if not robust:
            summary += f" — robustifier ({'peu de trades' if n <= 20 else 'DD élevé'})"
        actions = ["Accepter" if robust else "Continuer pour robustifier"]
        donts = []
    elif target_sharpe > 0 and sharpe >= target_sharpe * 0.5:
        cat, sev, ct = "approaching_target", "info", "params"
        pct = sharpe / target_sharpe * 100
        summary = f"En progression ({pct:.0f}% de la cible Sharpe {target_sharpe})"
        actions = [
            "Fine-tuning UNIQUEMENT: ajuster seuils ±10-20%",
            "Optimiser SL ATR mult (tester 1.0 / 1.5 / 2.0 / 2.5)",
            "Optimiser TP ATR mult (tester 2.0 / 3.0 / 4.0)",
            "Ajuster périodes indicateurs (RSI 14→12 ou 14→16)",
        ]
        donts = [
            "Ne PAS changer la logique — elle fonctionne",
            "Ne PAS ajouter d'indicateurs (risque overfitting)",
        ]
    else:
        cat, sev, ct = "needs_work", "info", "both"
        summary = f"Résultats médiocres (Sharpe {sharpe:.3f}, Return {ret:.1f}%)"
        actions = [
            "Essayer une combinaison d'indicateurs différente",
            "Revoir logique d'entrée/sortie",
            "Simplifier: 1-2 indicateurs max avec logique claire",
        ]
        donts = []

    # --- Détection tendance historique ---
    trend, trend_detail = "first", ""

    if iteration_history:
        prev_sharpes = [float(h.get("sharpe", 0) or 0) for h in iteration_history]
        prev_cats = [h.get("diagnostic_category", "") for h in iteration_history]

        if prev_sharpes:
            delta = sharpe - prev_sharpes[-1]
            if delta > 0.05:
                trend, trend_detail = "improving", f"+{delta:.3f} vs précédent"
            elif delta < -0.05:
                trend, trend_detail = "declining", f"{delta:.3f} vs précédent"
            else:
                trend, trend_detail = "stable", f"Δ={delta:+.3f} (stagnant)"

        # Stagnation: même catégorie 3× consécutives
        recent = (prev_cats[-2:] + [cat]) if len(prev_cats) >= 2 else []
        if len(recent) == 3 and len(set(recent)) == 1 and recent[0]:
            trend = "stagnated"
            trend_detail = (
                f"Même problème '{cat}' 3× de suite — changer d'approche"
            )

        # Oscillation: sharpe en zigzag
        if len(prev_sharpes) >= 2:
            ds = [
                prev_sharpes[j + 1] - prev_sharpes[j]
                for j in range(len(prev_sharpes) - 1)
            ]
            ds.append(sharpe - prev_sharpes[-1])
            if len(ds) >= 2 and all(
                (ds[k] > 0) != (ds[k + 1] > 0) for k in range(len(ds) - 1)
            ):
                trend = "oscillating"
                trend_detail = "Zigzag — stabiliser les modifications"

    return {
        "category": cat,
        "severity": sev,
        "change_type": ct,
        "summary": summary,
        "actions": actions,
        "donts": donts,
        "trend": trend,
        "trend_detail": trend_detail,
        "score_card": sc,
        "continuous_score": round(float(continuous_score.get("score", 0.0)), 2),
        "score_breakdown": {
            "components": continuous_score.get("components", {}),
            "penalties": continuous_score.get("penalties", {}),
            "drawdown_excess_pct": continuous_score.get("drawdown_excess_pct", 0.0),
        },
    }


# ---------------------------------------------------------------------------
# Strategy Builder
# ---------------------------------------------------------------------------

class StrategyBuilder:
    """
    Agent capable de générer itérativement des stratégies de trading.

    Workflow :
    1. Recevoir un objectif (ex: "Trend-following BTC 30m avec Bollinger + ATR")
    2. Demander au LLM une proposition (indicateurs, logique, paramètres)
    3. Demander au LLM le code Python complet de la stratégie
    4. Valider le code (syntaxe + sécurité)
    5. Charger dynamiquement la stratégie
    6. Lancer un backtest via BacktestExecutor
    7. Analyser les résultats (LLM)
    8. Décider : itérer (modifier la logique) ou accepter

    Les stratégies générées sont isolées dans sandbox_strategies/<session_id>/.

    Example:
        >>> builder = StrategyBuilder(llm_config=LLMConfig.from_env())
        >>> session = builder.run(
        ...     objective="Trend-following BTC 30m avec Bollinger + ATR",
        ...     data=ohlcv_df,
        ...     max_iterations=5,
        ... )
        >>> print(session.best_sharpe)
    """

    def __init__(
        self,
        llm_config: Optional[LLMConfig] = None,
        llm_client: Optional[LLMClient] = None,
        llm_topology_config: Optional[LLMTopologyConfig | Dict[str, Any]] = None,
        phase_llm_clients: Optional[Dict[str, Any]] = None,
        stream_callback: Optional[Callable[[str, str], None]] = None,
        backtest_completed_callback: Optional[Callable[[Any], None]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        if llm_client is not None:
            self.llm = llm_client
        elif llm_config is not None:
            self.llm = create_llm_client(llm_config)
        else:
            self.llm = create_llm_client(LLMConfig.from_env())

        self.available_indicators = list_indicators()
        self.stream_callback = stream_callback
        self.backtest_completed_callback = backtest_completed_callback
        self.progress_callback = progress_callback
        self.phase_llm_clients = {
            str(key or "").strip(): value
            for key, value in dict(phase_llm_clients or {}).items()
            if str(key or "").strip() and value is not None
        }
        if isinstance(llm_topology_config, dict):
            llm_topology_config = LLMTopologyConfig.from_dict(llm_topology_config)
        self.llm_topology_config = llm_topology_config or build_phase1_topology(
            primary_host=getattr(getattr(self.llm, "config", None), "ollama_host", None)
        )

    def _emit_completed_backtest(
        self,
        bt_result: Any,
        *,
        session: Any = None,
        iteration_num: Optional[int] = None,
    ) -> None:
        """Notifie un backtest terminé proprement pour persistance immédiate."""
        callback = self.backtest_completed_callback
        if callback is None:
            return

        raw_result = getattr(bt_result, "run_result", None)
        if raw_result is None:
            return

        meta = getattr(raw_result, "meta", None)
        if isinstance(meta, dict) and session is not None:
            meta.setdefault("origin", "builder")
            meta.setdefault("mode", "builder")
            meta.setdefault("builder_session_id", getattr(session, "session_id", ""))
            meta.setdefault("builder_iteration", iteration_num)
            meta.setdefault("builder_objective", getattr(session, "objective", ""))

        try:
            callback(raw_result)
        except Exception:
            logger.exception(
                "builder_backtest_completed_callback_failed iteration=%s session=%s",
                iteration_num,
                getattr(session, "session_id", "unknown"),
            )

    def _emit_progress(self, event: str, **payload: Any) -> None:
        """Notifie l'UI de l'état courant d'une session Builder."""
        callback = self.progress_callback
        if callback is None:
            return
        message = {"event": event, **payload}
        try:
            callback(message)
        except Exception:
            logger.debug(
                "builder_progress_callback_failed event=%s",
                event,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # LLM call helper (streaming si callback défini)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_phase_client_key(phase: str) -> str:
        normalized = str(phase or "").strip().lower()
        if normalized.startswith("pre_reflection"):
            return "pre_reflection"
        if normalized.startswith("retry_proposal"):
            return "retry_proposal"
        if normalized.startswith("retry_code"):
            return "retry_code"
        if normalized.startswith("proposal"):
            return "proposal"
        if normalized.startswith("code"):
            return "code"
        if normalized.startswith("analysis"):
            return "analysis"
        if normalized.startswith("objective_gen"):
            return "objective_gen"
        return normalized.split("_")[0] if normalized else ""

    def _chat_llm(
        self,
        messages: List[LLMMessage],
        *,
        phase: str = "",
        json_mode: bool = False,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Any:
        """Appel LLM avec streaming optionnel et timeout par phase.

        Si ``self.stream_callback`` est défini et que le client supporte
        ``chat_stream``, chaque token généré est relayé via
        ``stream_callback(phase, chunk)`` à l'UI.

        Un timeout par phase empêche les outliers de bloquer la session
        (ex: un appel code qui prend 8 min au lieu de 15 s en médiane).
        """
        # Resolve phase-specific timeout
        base_phase = phase.split("_")[0] if phase else ""
        timeout_sec = _LLM_PHASE_TIMEOUTS.get(
            base_phase, _LLM_PHASE_TIMEOUT_DEFAULT
        )
        phase_client_key = self._resolve_phase_client_key(phase)
        llm_client = self.phase_llm_clients.get(phase_client_key, self.llm)
        client_config = getattr(llm_client, "config", None)
        route = self.llm_topology_config.resolve_builder_phase_route(
            phase,
            fallback_host=getattr(client_config, "ollama_host", None),
        )
        original_host = getattr(client_config, "ollama_host", None)
        if client_config is not None and route.ollama_host:
            client_config.ollama_host = route.ollama_host

        def _do_call():
            if self.stream_callback and hasattr(llm_client, "chat_stream"):
                return llm_client.chat_stream(
                    messages,
                    on_chunk=lambda c: self.stream_callback(phase, c),
                    json_mode=json_mode,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            return llm_client.chat(
                messages,
                json_mode=json_mode,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_do_call)
            # Quand le Builder est appelé depuis Streamlit, le callback de streaming
            # peut exécuter des `st.*` depuis ce worker thread. On propage donc le
            # ScriptRunContext pour éviter le spam "missing ScriptRunContext".
            try:
                from streamlit.runtime.scriptrunner import (
                    add_script_run_ctx as _st_add_ctx,
                    get_script_run_ctx as _st_get_ctx,
                )

                st_ctx = _st_get_ctx()
                if st_ctx is not None:
                    for th in list(getattr(pool, "_threads", ())):
                        try:
                            _st_add_ctx(th, st_ctx)
                        except Exception:
                            pass
            except Exception:
                # En mode non-Streamlit (CLI/tests), ignorer silencieusement.
                pass
            try:
                return future.result(timeout=timeout_sec)
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "builder_llm_timeout phase=%s timeout=%ds",
                    phase, timeout_sec,
                )
                # Return a stub response so callers can handle gracefully
                return SimpleNamespace(content="")
            finally:
                if client_config is not None:
                    client_config.ollama_host = original_host

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    @staticmethod
    def create_session_id(objective: str) -> str:
        """Génère un identifiant de session unique."""
        normalized = sanitize_objective_text(objective).lower()
        slug = re.sub(r"[^a-z0-9]+", "_", normalized)[:40].strip("_")
        if not slug:
            slug = "builder_session"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{ts}_{slug}"

    @staticmethod
    def get_session_dir(session_id: str) -> Path:
        """Retourne le chemin du dossier sandbox pour une session."""
        return SANDBOX_ROOT / session_id

    def _safe_save_session_summary(self, session: BuilderSession) -> None:
        """Checkpoint best-effort pour survivre aux arrêts anormaux."""
        try:
            self._save_session_summary(session)
        except Exception as exc:
            logger.warning(
                "builder_session_checkpoint_failed session=%s error=%s",
                getattr(session, "session_id", "unknown"),
                exc,
            )

    def _attempt_session_auto_reset(
        self,
        session: BuilderSession,
        *,
        iteration_num: int,
        trigger: str,
        reason: str,
        last_iteration: Optional[BuilderIteration],
        consecutive_failures: int,
        fallback_count: int,
    ) -> tuple[bool, Optional[BuilderIteration], int, int, Dict[str, Any]]:
        """Réinitialise proprement la session autour du meilleur ancrage disponible."""
        if session.auto_reset_count >= MAX_SESSION_AUTO_RESETS:
            return False, last_iteration, consecutive_failures, fallback_count, {
                "trigger": trigger,
                "reason": reason,
                "recovered": False,
                "reset_budget_exhausted": True,
                "reset_count": session.auto_reset_count,
            }

        anchor, anchor_source = _select_session_recovery_anchor(session, last_iteration)
        session.auto_reset_count += 1
        event = {
            "iteration": iteration_num,
            "trigger": trigger,
            "reason": reason,
            "recovered": True,
            "reset_count": session.auto_reset_count,
            "anchor_source": anchor_source,
            "anchor_iteration": anchor.iteration if anchor else None,
            "preserved_best_iteration": (
                session.best_iteration.iteration if session.best_iteration else None
            ),
            "consecutive_failures_before_reset": consecutive_failures,
            "fallback_count_before_reset": fallback_count,
            "timestamp": datetime.now().isoformat(),
        }
        session.recovery_events.append(event)
        logger.warning(
            "builder_session_auto_reset session=%s reset=%d trigger=%s anchor=%s anchor_iter=%s",
            session.session_id,
            session.auto_reset_count,
            trigger,
            anchor_source,
            anchor.iteration if anchor else None,
        )
        self._safe_save_session_summary(session)
        return True, anchor, 0, 0, event

    # ------------------------------------------------------------------
    # LLM interactions
    # ------------------------------------------------------------------

    def _ask_proposal(
        self,
        session: BuilderSession,
        last_iteration: Optional[BuilderIteration] = None,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """Demande au LLM une proposition de stratégie.

        Returns:
            (proposal, feedback)
        """
        context = {
            "objective": session.objective,
            "available_indicators": self.available_indicators,
            "iteration": len(session.iterations) + 1,
            "max_iterations": session.max_iterations,
            "direction_constraint": session.direction_constraint,
            # Contexte de marché
            "symbol": session.symbol,
            "timeframe": session.timeframe,
            "n_bars": session.n_bars,
            "date_range_start": session.date_range_start,
            "date_range_end": session.date_range_end,
            "fees_bps": session.fees_bps,
            "slippage_bps": session.slippage_bps,
            "initial_capital": session.initial_capital,
        }

        if last_iteration and last_iteration.backtest_result:
            metrics = last_iteration.backtest_result.metrics
            context["last_metrics"] = {
                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "sortino_ratio": metrics.get("sortino_ratio", 0),
                "calmar_ratio": metrics.get("calmar_ratio", 0),
                "total_return_pct": metrics.get("total_return_pct", 0),
                "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
                "volatility_annual": metrics.get("volatility_annual", 0),
                "win_rate_pct": metrics.get("win_rate_pct", 0),
                "total_trades": metrics.get("total_trades", 0),
                "profit_factor": metrics.get("profit_factor", 0),
                "expectancy": metrics.get("expectancy", 0),
                "avg_win": metrics.get("avg_win", 0),
                "avg_loss": metrics.get("avg_loss", 0),
                "risk_reward_ratio": metrics.get("risk_reward_ratio", 0),
            }
            context["last_code"] = last_iteration.code
            context["last_analysis"] = last_iteration.analysis
            context["best_sharpe"] = session.best_sharpe
            # Diagnostic pré-calculé de la dernière itération
            if last_iteration.diagnostic_detail:
                context["diagnostic"] = last_iteration.diagnostic_detail
            # Stagnation détectée : forcer le LLM à changer radicalement
            stag = (last_iteration.phase_feedback or {}).get("stagnation", {})
            if stag.get("identical_metrics"):
                context["stagnation_warning"] = (
                    "CRITICAL: Previous iteration produced IDENTICAL metrics. "
                    "Your changes had NO effect. You MUST change the fundamental "
                    "approach: use DIFFERENT indicators, DIFFERENT entry logic, "
                    "or DIFFERENT strategy type (e.g. trend-following instead of "
                    "mean-reversion). Do NOT repeat the same logic with minor tweaks."
                )

        if session.iterations:
            context["iteration_history"] = [
                {
                    "iteration": it.iteration,
                    "hypothesis": it.hypothesis,
                    "change_type": it.change_type,
                    "diagnostic_category": it.diagnostic_category,
                    "sharpe": (
                        it.backtest_result.metrics.get("sharpe_ratio", 0)
                        if it.backtest_result else None
                    ),
                    "return_pct": (
                        it.backtest_result.metrics.get("total_return_pct", 0)
                        if it.backtest_result else None
                    ),
                    "trades": (
                        it.backtest_result.metrics.get("total_trades", 0)
                        if it.backtest_result else None
                    ),
                    "error": it.error,
                    "is_fallback": it.is_fallback,
                }
                for it in session.iterations[-5:]
            ]

        prompt = render_prompt("strategy_builder_proposal.jinja2", context)
        base_messages = [
            LLMMessage(role="system", content=self._system_prompt_proposal()),
            LLMMessage(role="user", content=prompt),
        ]

        response = self._chat_llm(
            messages=base_messages,
            phase="proposal",
            json_mode=True,
            max_tokens=4096,
        )
        raw = response.content or ""
        feedback: Dict[str, Any] = {
            "phase": "proposal",
            "initial_kind": _classify_raw_response(raw),
            "realign_attempts": 0,
            "realign_success": False,
            "issues": [],
        }
        proposal = _normalize_proposal_keys(_extract_json_from_response(raw))
        proposal = _sanitize_proposal_payload(
            proposal,
            available_indicators=self.available_indicators,
            objective=session.objective,
            direction_constraint=session.direction_constraint,
        )
        issues = _proposal_issues(proposal)
        feedback["issues"] = issues
        if not issues:
            proposal["change_type"] = _normalize_change_type(
                proposal.get("change_type", "logic")
            )
            feedback["final_kind"] = feedback["initial_kind"]
            feedback["final_valid"] = True
            return proposal, feedback
        feedback["error_code"] = _proposal_error_code(issues)

        # Phase guard: certains modèles répondent du code / texte libre.
        for attempt in range(1, PROPOSAL_REALIGN_ATTEMPTS + 1):
            if _looks_like_python_code(raw):
                mismatch = "You answered with Python code, but this is PROPOSAL phase."
            elif _looks_like_json_object(raw):
                mismatch = "You answered JSON but with missing/placeholder fields."
            else:
                mismatch = "You answered with text/explanations, not strict strategy JSON."

            correction = (
                "PHASE LOCK: PROPOSAL ONLY.\n"
                f"{mismatch}\n\n"
                "Return EXACTLY one valid JSON object and nothing else.\n"
                "Forbidden in this phase: Python code, markdown, commentary, objective rewrite.\n"
                "All fields must be concrete (no placeholders like 'brief description').\n"
                "Required keys: strategy_name, used_indicators, entry_long_logic, "
                "exit_logic, risk_management, default_params, parameter_specs.\n"
                "Optional keys: hypothesis, change_type, entry_short_logic.\n"
                "change_type must be one of: logic, params, both, accept."
            )
            response = self._chat_llm(
                messages=[
                    *base_messages,
                    LLMMessage(role="assistant", content=raw[:4000]),
                    LLMMessage(role="user", content=correction),
                ],
                phase=f"proposal_realign_{attempt}",
                json_mode=(attempt == 1),
                max_tokens=4096,
            )
            raw = response.content or ""
            feedback["realign_attempts"] = attempt
            proposal = _normalize_proposal_keys(_extract_json_from_response(raw))
            proposal = _sanitize_proposal_payload(
                proposal,
                available_indicators=self.available_indicators,
                objective=session.objective,
                direction_constraint=session.direction_constraint,
            )
            issues = _proposal_issues(proposal)
            feedback["issues"] = issues
            if not issues:
                proposal["change_type"] = _normalize_change_type(
                    proposal.get("change_type", "logic")
                )
                feedback["realign_success"] = True
                feedback["final_kind"] = _classify_raw_response(raw)
                feedback["final_valid"] = True
                return proposal, feedback

        feedback["final_kind"] = _classify_raw_response(raw)
        feedback["final_valid"] = False
        feedback["error_code"] = _proposal_error_code(feedback.get("issues", []))
        return proposal, feedback

    def _ask_code(
        self,
        session: BuilderSession,
        proposal: Dict[str, Any],
        last_iteration: Optional[BuilderIteration] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """Demande au LLM de générer la logique Python de generate_signals.

        Returns:
            (code, feedback)
        """
        # Extraire les actions diagnostiques de la dernière itération
        diag_actions: List[str] = []
        diag_donts: List[str] = []
        if last_iteration is not None:
            diag_detail = getattr(last_iteration, "diagnostic_detail", {}) or {}
            diag_actions = diag_detail.get("actions", [])
            diag_donts = diag_detail.get("donts", [])

        context = {
            "objective": session.objective,
            "proposal": proposal,
            "available_indicators": self.available_indicators,
            "class_name": GENERATED_CLASS_NAME,
            "direction_constraint": session.direction_constraint,
            # Contexte de marché
            "symbol": session.symbol,
            "timeframe": session.timeframe,
            "n_bars": session.n_bars,
            "fees_bps": session.fees_bps,
            "slippage_bps": session.slippage_bps,
            "initial_capital": session.initial_capital,
            "previous_code": (
                last_iteration.code
                if last_iteration is not None and getattr(last_iteration, "code", "")
                else ""
            ),
            # Diagnostic de l'itération précédente (injecté dans le template)
            "diagnostic_actions": diag_actions,
            "diagnostic_donts": diag_donts,
        }

        prompt = render_prompt("strategy_builder_code.jinja2", context)
        safe_mode = _safe_path_mode()

        # Safe path JSON+DSL -> template (strict)
        if safe_mode == "strict":
            dsl_issues = _proposal_issues(proposal)
            if dsl_issues:
                fallback = _build_deterministic_fallback_code(proposal, variant=1)
                return fallback, {
                    "phase": "code",
                    "initial_kind": "dsl",
                    "realign_attempts": 0,
                    "realign_success": False,
                    "final_kind": "python",
                    "final_valid": True,
                    "source": "dsl_template_fallback",
                    "safe_path_mode": safe_mode,
                    "error_code": _proposal_error_code(dsl_issues) or ERR_DSL,
                }
            return _build_code_from_proposal_dsl(proposal), {
                "phase": "code",
                "initial_kind": "dsl",
                "realign_attempts": 0,
                "realign_success": False,
                "final_kind": "python",
                "final_valid": True,
                "source": "dsl_template",
                "safe_path_mode": safe_mode,
            }

        base_messages = [
            LLMMessage(role="system", content=self._system_prompt_code()),
            LLMMessage(role="user", content=prompt),
        ]

        response = self._chat_llm(
            messages=base_messages,
            phase="code",
            max_tokens=4096,
        )
        raw = response.content or ""
        feedback: Dict[str, Any] = {
            "phase": "code",
            "initial_kind": _classify_raw_response(raw),
            "realign_attempts": 0,
            "realign_success": False,
            "safe_path_mode": safe_mode,
        }
        code = _extract_python_from_response(raw)
        if code.strip() and _looks_like_valid_python_logic(code):
            feedback["final_kind"] = feedback["initial_kind"]
            feedback["final_valid"] = True
            return code, feedback

        # Phase guard: certains modèles reviennent en mode JSON/proposition.
        for attempt in range(1, MAX_PHASE_REALIGN_ATTEMPTS + 1):
            if _looks_like_json_object(raw):
                mismatch = "You answered JSON/proposal content, but this is LOGIC phase."
            elif _looks_like_python_code(raw):
                mismatch = "You answered Python but no usable logic body was extracted."
            else:
                mismatch = "You answered non-code text, not executable Python."

            correction = (
                "PHASE LOCK: LOGIC ONLY.\n"
                f"{mismatch}\n\n"
                "Return ONLY Python statements for generate_signals body.\n"
                "Do not output imports, class definition, function signature, JSON, "
                "objective rewrite, or commentary.\n"
                "No placeholders."
            )
            response = self._chat_llm(
                messages=[
                    *base_messages,
                    LLMMessage(role="assistant", content=raw[:6000]),
                    LLMMessage(role="user", content=correction),
                ],
                phase=f"code_realign_{attempt}",
                max_tokens=4096,
            )
            raw = response.content or ""
            feedback["realign_attempts"] = attempt
            code = _extract_python_from_response(raw)
            if code.strip() and _looks_like_valid_python_logic(code):
                feedback["realign_success"] = True
                feedback["final_kind"] = _classify_raw_response(raw)
                feedback["final_valid"] = True
                return code, feedback

        feedback["final_kind"] = _classify_raw_response(raw)
        feedback["final_valid"] = False
        if safe_mode == "prefer":
            dsl_issues = _proposal_issues(proposal)
            dsl_code = (
                _build_code_from_proposal_dsl(proposal)
                if not dsl_issues
                else _build_deterministic_fallback_code(proposal, variant=1)
            )
            return dsl_code, {
                "phase": "code",
                "initial_kind": feedback.get("initial_kind", "unknown"),
                "realign_attempts": feedback.get("realign_attempts", 0),
                "realign_success": feedback.get("realign_success", False),
                "final_kind": "python",
                "final_valid": True,
                "source": "dsl_template_prefer_fallback",
                "safe_path_mode": safe_mode,
                "error_code": _proposal_error_code(dsl_issues) or ERR_DSL,
            }
        return code, feedback

    def _retry_proposal_simple(self, objective: str) -> Dict[str, Any]:
        """Prompt simplifié quand le LLM ne répond pas au template riche.

        Tente d'abord avec json_mode, puis sans (certains modèles locaux
        gèrent mal le format JSON forcé).
        """
        indicators_str = ", ".join(self.available_indicators[:15])
        prompt = (
            f"Design a simple trading strategy for: {objective}\n\n"
            f"Available indicators: {indicators_str}\n\n"
            "Reply ONLY with this JSON:\n"
            "{\n"
            '  "strategy_name": "my_strategy",\n'
            '  "hypothesis": "one concrete sentence explaining why this setup should work",\n'
            '  "change_type": "logic",\n'
            '  "used_indicators": ["rsi", "bollinger"],\n'
            '  "entry_long_logic": "explicit rule with thresholds, e.g. RSI<30 and close<lower band",\n'
            '  "entry_short_logic": "explicit rule with thresholds, e.g. RSI>70 and close>upper band",\n'
            '  "exit_logic": "explicit close rule, e.g. mean reversion to middle band or RSI cross 50",\n'
            '  "risk_management": "ATR stop and ATR take-profit with concrete multipliers",\n'
            '  "default_params": {"rsi_period": 14, "rsi_oversold": 30, "rsi_overbought": 70, "stop_atr_mult": 1.5, "tp_atr_mult": 3.0},\n'
            '  "parameter_specs": {"rsi_period": {"min": 5, "max": 50, "default": 14, "type": "int"}}\n'
            "}"
        )
        sys_msg = LLMMessage(
            role="system",
            content=(
                "You are a quant trader. "
                "Reply ONLY with valid JSON. No commentary. No thinking. "
                "No placeholders."
            ),
        )
        user_msg = LLMMessage(role="user", content=prompt)

        # Tentative 1 : avec json_mode
        response = self._chat_llm(
            messages=[sys_msg, user_msg],
            phase="retry_proposal",
            json_mode=True,
            max_tokens=4096,
        )
        result = _normalize_proposal_keys(
            _extract_json_from_response(response.content)
        )
        if result:
            return result

        # Tentative 2 : sans json_mode (certains modèles locaux échouent avec format=json)
        logger.warning(
            "retry_proposal: json_mode a échoué, tentative sans json_mode. "
            "Réponse brute (200 premiers chars): %.200s",
            response.content[:200] if response.content else "(vide)",
        )
        response = self._chat_llm(
            messages=[sys_msg, user_msg],
            phase="retry_proposal_nojson",
            json_mode=False,
            max_tokens=4096,
        )
        return _normalize_proposal_keys(
            _extract_json_from_response(response.content)
        )

    def _retry_code_simple(self, proposal: Dict[str, Any]) -> str:
        """Prompt simplifié quand le LLM ne génère pas de code valide."""
        inds = proposal.get("used_indicators", ["rsi", "bollinger"])
        entry_l = proposal.get("entry_long_logic", "RSI < 30")
        entry_s = proposal.get("entry_short_logic", "RSI > 70")
        prompt = (
            "Generate ONLY the body lines to insert inside generate_signals.\n"
            "Do NOT generate class/imports/function signature.\n"
            f"Indicators available in this method: {inds}\n"
            f"LONG intent: {entry_l}\n"
            f"SHORT intent: {entry_s}\n\n"
            "IMPORTANT:\n"
            "- indicator values are numpy arrays (or dict of numpy arrays)\n"
            "- never use .iloc/.loc on indicators; use arr[i] or vectorized masks\n"
            "- never use for i in range(...) or while\n"
            "- bollinger must be indicators['bollinger']['upper|middle|lower']\n"
            "- donchian breakout should compare close vs previous band: prev_upper = np.roll(donchian_upper, 1)\n\n"
            "- adx must be indicators['adx']['adx|plus_di|minus_di'] (not indicators['adx'] directly)\n"
            "- supertrend must be indicators['supertrend']['supertrend|direction'] (no upper/lower)\n"
            "- stochastic must be indicators['stochastic']['stoch_k|stoch_d'] (no 'signal' key)\n"
            "- do not compare dict indicators directly (e.g. NEVER `adx > 25`)\n"
            "- for `&` / `|`, ensure both sides are boolean masks (no float/int scalar in bitwise op)\n\n"
            "- ema/rsi/atr are plain arrays: NEVER use indicators['ema']['ema_21'] style\n\n"
            "- ALWAYS include leverage=1 in default_params\n"
            "- If using ATR-based SL/TP: write df['bb_stop_long/bb_tp_long/bb_stop_short/bb_tp_short'] on entry bars\n\n"
            "- write only statements compatible with this pre-existing context:\n"
            "  signals = pd.Series(0.0, index=df.index, dtype=np.float64)\n"
            "- assign signals[...] only with 1.0, -1.0 or 0.0\n"
            "- never use True/False in signal assignments\n"
            "- return only a ```python code block with body lines\n"
        )
        response = self._chat_llm(
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "Generate ONLY Python code inside a ```python block. "
                        "No explanation. No commentary."
                    ),
                ),
                LLMMessage(role="user", content=prompt),
            ],
            phase="retry_code",
        )
        return _extract_python_from_response(response.content)

    def _retry_code_runtime_fix(
        self,
        proposal: Dict[str, Any],
        failing_code: str,
        runtime_error: str,
    ) -> str:
        """Demande une correction ciblée d'un code qui a échoué au runtime backtest."""
        prompt = (
            "The following strategy code failed at runtime during backtest.\n\n"
            f"Runtime error (may include traceback tail):\n{runtime_error}\n\n"
            "Fix ONLY what is necessary to remove the runtime error while keeping "
            "the strategy intent intact.\n"
            "Rules:\n"
            "- Class name must remain BuilderGeneratedStrategy\n"
            "- Keep required_indicators coherent with indicator usage\n"
            "- Keep generate_signals signature EXACTLY: "
            "def generate_signals(self, df: pd.DataFrame, indicators: Dict[str, Any], params: Dict[str, Any]) -> pd.Series\n"
            "- Never reference undefined globals like `df`, `indicators`, `params` inside helper methods; "
            "pass what you need as arguments.\n"
            "- Use indicators dict correctly (dict indicators via sub-keys)\n"
            "- Indicator values are numpy arrays; never call .iloc/.loc on indicators\n"
            "- Plain arrays (no sub-keys): ema, rsi, atr, cci, obv, mfi\n"
            "- Dict indicators (access sub-keys first):\n"
            "  bollinger['upper|middle|lower'], keltner['upper|middle|lower'],\n"
            "  donchian['upper|middle|lower'], macd['macd|signal|histogram'],\n"
            "  For Donchian/Bollinger/Keltner breakout rules, compare against previous band values via np.roll(..., 1)\n"
            "  adx['adx|plus_di|minus_di'], supertrend['supertrend|direction'],\n"
            "  stochastic['stoch_k|stoch_d'], stoch_rsi['k|d|signal'],\n"
            "  ichimoku['tenkan|kijun|senkou_a|senkou_b|chikou|cloud_position'],\n"
            "  psar['sar|trend|signal'], vortex['vi_plus|vi_minus|signal|oscillator'],\n"
            "  aroon['aroon_up|aroon_down'], pivot_points['pivot|r1|s1|r2|s2|r3|s3']\n"
            "- NEVER create bare variables like keltner_upper or donchian_lower\n"
            "- Do NOT compare dict indicators directly (e.g. avoid `adx > threshold`)\n"
            "- For bitwise `&` / `|`, each side must be a boolean mask expression\n"
            "- ALWAYS define long_mask/short_mask before using: long_mask = np.zeros(len(df), dtype=bool)\n"
            "- Do not use df['rsi']/df['ema']/df['bollinger']\n"
            "- Return only Python code in one ```python block\n\n"
            f"Current proposal context: {proposal}\n\n"
            "Failing code:\n"
            "```python\n"
            f"{failing_code}\n"
            "```"
        )
        try:
            response = self._chat_llm(
                messages=[
                    LLMMessage(
                        role="system",
                        content=(
                            "You are a senior Python quant developer. "
                            "Fix runtime errors in trading strategy code. "
                            "Output code only."
                        ),
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                phase="retry_code_runtime",
                max_tokens=4096,
            )
            return _extract_python_from_response(response.content)
        except Exception as llm_exc:
            logger.error(
                "retry_code_runtime_fix LLM call failed: %s\n"
                "runtime_error=%s\nfailing_code (first 500 chars)=%.500s",
                llm_exc,
                runtime_error,
                failing_code,
            )
            # Return empty string to let the orchestrator fall back to
            # deterministic fallback code instead of crashing.
            return ""

    def _ask_analysis(
        self,
        session: BuilderSession,
        iteration: BuilderIteration,
        diagnostic: Optional[Dict[str, Any]] = None,
        pre_reflection: str = "",
    ) -> tuple[str, str]:
        """Analyse le résultat et décide de continuer ou accepter.

        Args:
            diagnostic: résultat de compute_diagnostic() — enrichit le prompt.
            pre_reflection: self-critique du LLM faite pendant le backtest.

        Returns:
            (analysis_text, decision) où decision ∈ {"continue", "accept", "stop"}
        """
        if not iteration.backtest_result:
            return "Pas de résultat de backtest disponible.", "continue"

        metrics = iteration.backtest_result.metrics
        n_trades = metrics.get("total_trades", 0)
        sharpe = metrics.get("sharpe_ratio", 0)
        sortino = metrics.get("sortino_ratio", 0)
        ret = metrics.get("total_return_pct", 0)
        dd = metrics.get("max_drawdown_pct", 0)
        wr = metrics.get("win_rate_pct", 0)
        pf = metrics.get("profit_factor", 0)
        exp = metrics.get("expectancy", 0)

        # --- Construire le prompt enrichi ---
        lines = [
            f"## Analyse — itération {iteration.iteration}/{session.max_iterations}",
            f"Objectif: {session.objective}",
            f"Hypothèse testée: {iteration.hypothesis}",
            f"Marché: {session.symbol} {session.timeframe} ({session.n_bars} barres, {session.date_range_start} → {session.date_range_end})",
            f"Configuration: capital={session.initial_capital}$, fees={session.fees_bps}bps, slippage={session.slippage_bps}bps",
            "",
            "### Résultats",
            f"- Sharpe: {sharpe:.3f}  |  Sortino: {sortino:.3f}",
            f"- Return: {ret:+.2f}%  |  MaxDD: {dd:.2f}%",
            f"- Trades: {n_trades}  |  WinRate: {wr:.1f}%  |  PF: {pf:.2f}",
            f"- Expectancy: {exp:.3f}",
            f"- Meilleur Sharpe session: {session.best_sharpe:.3f}",
        ]

        # Diagnostic pré-calculé
        if diagnostic:
            lines.append("")
            lines.append("### Diagnostic automatique")
            lines.append(f"Catégorie: {diagnostic.get('category', '?')} ({diagnostic.get('severity', '?')})")
            lines.append(f"Résumé: {diagnostic.get('summary', '')}")
            lines.append(f"Modification: {diagnostic.get('change_type', '?')}")
            sc = diagnostic.get("score_card", {})
            if sc:
                grades = ", ".join(f"{k}: {v['grade']}" for k, v in sc.items())
                lines.append(f"Score card: {grades}")
            trend = diagnostic.get("trend", "")
            if trend:
                lines.append(f"Tendance: {trend} {diagnostic.get('trend_detail', '')}")
            for a in diagnostic.get("actions", []):
                lines.append(f"  → {a}")
            for d in diagnostic.get("donts", []):
                lines.append(f"  ⚠️ {d}")

            # Auto-accept si target atteint + robuste
            cat = diagnostic.get("category", "")
            if cat == "target_reached" and n_trades > 20 and abs(dd) < 40:
                return (
                    f"Cible atteinte (Sharpe {sharpe:.3f}), stratégie robuste "
                    f"({n_trades} trades, DD {dd:.1f}%). Acceptation automatique.",
                    "accept",
                )

            # Alerte stagnation
            if diagnostic.get("trend") == "stagnated":
                lines.append("")
                lines.append("⚠️ STAGNATION DÉTECTÉE — même catégorie 3× de suite.")
                lines.append("Tu DOIS changer d'approche radicalement.")

        # Inject pre-reflection (self-critique done during backtest)
        if pre_reflection:
            lines.append("")
            lines.append("### Pré-réflexion (auto-critique avant résultats)")
            lines.append(pre_reflection)
            lines.append("Utilise cette pré-réflexion pour enrichir ton analyse.")

        remaining = session.max_iterations - iteration.iteration

        # Calcul du prochain checkpoint
        positive_count = _count_positive_iterations(session.iterations)
        next_checkpoint = None
        next_required = None

        for checkpoint_iter in sorted(POSITIVE_PROGRESS_GATE_CHECKPOINTS.keys()):
            if iteration.iteration < checkpoint_iter:
                next_checkpoint = checkpoint_iter
                next_required = POSITIVE_PROGRESS_GATE_CHECKPOINTS[checkpoint_iter]
                break

        lines.append("")
        lines.append(f"Itérations restantes: {remaining}")

        if next_checkpoint:
            lines.append(
                f"⚠️ Prochain checkpoint qualité: itération {next_checkpoint} "
                f"(requis: {next_required} runs positifs, actuels: {positive_count})"
            )

        lines.append("")
        lines.append('Réponds en JSON: {{"analysis": "...", "decision": "accept|continue|stop", "suggestions": [...]}}')

        prompt = "\n".join(lines)

        response = self._chat_llm(
            messages=[
                LLMMessage(role="system", content=(
                    "Tu es un analyste quantitatif expert. "
                    "Analyse les résultats de backtest et le diagnostic fourni. "
                    "Décide: accept (cible atteinte + robuste), "
                    "continue (amélioration possible), stop (impasse). "
                    "Privilégie 'continue' tant que des tests supplémentaires "
                    "peuvent améliorer la stratégie. "
                    "Sois concis. Réponds en JSON."
                )),
                LLMMessage(role="user", content=prompt),
            ],
            phase="analysis",
            json_mode=True,
        )

        parsed = _extract_json_from_response(response.content)
        fallback_analysis = _normalize_llm_text(response.content, max_len=500)
        analysis = _normalize_llm_text(
            parsed.get("analysis", fallback_analysis),
            fallback=fallback_analysis,
            max_len=1200,
        )

        decision_raw = parsed.get("decision", "continue")
        decision = str(decision_raw or "").strip().lower()
        if decision not in ("continue", "accept", "stop"):
            decision = "continue"

        return analysis, decision

    def _ask_pre_reflection(
        self,
        session: "BuilderSession",
        proposal: Dict[str, Any],
        code: str,
        iteration_num: int,
    ) -> str:
        """Pre-reflection: the LLM self-critiques the code BEFORE seeing results.

        Called in parallel with the backtest so the LLM is productively occupied
        instead of idle. The output is injected into the analysis phase for
        better next-iteration planning.
        """
        history_lines = []
        for it in session.iterations[-3:]:
            if it.backtest_result:
                m = it.backtest_result.metrics
                history_lines.append(
                    f"  iter={it.iteration} sharpe={m.get('sharpe_ratio', 0):.3f} "
                    f"trades={m.get('total_trades', 0)} "
                    f"return={m.get('total_return_pct', 0):+.2f}%"
                )

        history_block = "\n".join(history_lines) if history_lines else "  (first iteration)"

        prompt = (
            f"ITERATION {iteration_num}/{session.max_iterations}\n"
            f"Objective: {session.objective}\n"
            f"Market: {session.symbol} {session.timeframe} ({session.n_bars} bars)\n\n"
            f"Hypothesis: {proposal.get('hypothesis', '?')}\n"
            f"Indicators: {', '.join(proposal.get('used_indicators', []))}\n"
            f"Entry long: {proposal.get('entry_long_logic', '?')}\n"
            f"Exit: {proposal.get('exit_logic', '?')}\n\n"
            f"Recent history:\n{history_block}\n\n"
            "The backtest is running NOW. You have NOT seen results yet.\n"
            "While waiting, prepare for the next iteration:\n"
            "1. What are the potential weaknesses of this strategy?\n"
            "2. If results are poor (negative return), what specific change would you try?\n"
            "3. If results are mediocre (low Sharpe), what parameter adjustments would help?\n"
            "4. What alternative approach would you try if the current one fails?\n\n"
            "Be concise (3-5 sentences max). Output ONLY a JSON: "
            '{"pre_reflection": "...", "backup_plan": "..."}'
        )

        try:
            response = self._chat_llm(
                messages=[
                    LLMMessage(role="system", content=(
                        "You are a quant strategy critic. The backtest is still running — "
                        "you have NOT seen results. Self-critique the strategy and prepare "
                        "a backup plan. Be concise and concrete."
                    )),
                    LLMMessage(role="user", content=prompt),
                ],
                phase="pre_reflection",
                json_mode=True,
                max_tokens=512,
            )
            parsed = _extract_json_from_response(response.content or "")
            reflection = str(parsed.get("pre_reflection", "")).strip()
            backup = str(parsed.get("backup_plan", "")).strip()
            if reflection or backup:
                return f"[Pre-reflection] {reflection}" + (
                    f"\n[Backup plan] {backup}" if backup else ""
                )
        except Exception as exc:
            logger.debug("pre_reflection_failed: %s", exc)
        return ""

    # ------------------------------------------------------------------
    # System prompts
    # ------------------------------------------------------------------

    @staticmethod
    def _system_prompt_proposal() -> str:
        return """You are an expert quantitative trading strategy designer.
You design strategies using ONLY the available indicators listed in the user prompt.
You NEVER invent new indicators — only combine existing ones with clever logic.

RULES:
- Respond with ONLY valid JSON (no markdown, no commentary, no thinking)
- Every indicator in used_indicators must exist in the available list
- Always include ATR-based stop-loss/take-profit in risk_management
- Use 2-3 indicators max to avoid overfitting
- Include realistic default_params with sensible ranges in parameter_specs
- hypothesis must explain WHY this combination should work, not just WHAT it does
- Never output placeholder values (e.g. "brief description", "when to BUY")
- This phase is proposal-only: NEVER output Python code

OUTPUT FORMAT — CRITICAL:
- entry_long_logic, entry_short_logic, exit_logic MUST be plain strings.
- NEVER nest JSON objects, dicts, "logic_expression", or "indicators" arrays inside logic fields.
- BAD: "exit_logic": {"logic_expression": {"close < donchian.middle": {"description": "...", "indicators": [...]}}}
- GOOD: "exit_logic": "close crosses below donchian middle band OR adx < 25"
- Keep each logic field to ONE concise sentence describing the boolean condition.

SEMANTIC CORRECTNESS:
- ATR is a volatility/distance metric, NOT a price level. Never compare close vs ATR directly.
  Good: "close crosses below lower Bollinger band AND ATR > threshold (volatile regime)"
  Bad: "EMA crosses above ATR" (meaningless — different units)
- Bollinger/Keltner/Donchian bands ARE price levels — compare close vs band.
- RSI/Stochastic/MFI are oscillators (0-100) — compare vs thresholds, not price.
- ADX measures trend strength (0-100) — use as a filter (ADX > 25), not as entry signal.
- Always ensure comparisons are between values of the same nature (price vs price, oscillator vs threshold).

Focus on signal quality, risk management, and robustness."""

    @staticmethod
    def _system_prompt_code() -> str:
        return """You are an expert Python developer specializing in trading systems.
Generate ONLY the logic body for generate_signals.

CRITICAL RULES:
1. Do NOT generate class/imports/function signature.
2. The host will inject your logic into a deterministic class skeleton.
3. generate_signals uses signals pd.Series with 1.0=LONG, -1.0=SHORT, 0.0=FLAT.
4. Use indicators from the 'indicators' dict (pre-computed by engine)
5. ALWAYS wrap indicators with np.nan_to_num() before any comparison
6. NEVER use os, subprocess, eval, exec, open, or __import__
7. ONLY import: numpy, pandas, strategies.base, utils.parameters
8. Do NOT use triple-quoted docstrings — use single-line # comments ONLY
9. Output ONLY Python code body lines in a ```python block. No text before or after.
10. Skip warmup: set signals.iloc[:50] = 0.0 to avoid NaN-driven false signals
11. STRICT CHANGE CONTRACT:
   - if proposal.change_type == "params": keep same required_indicators and same generate_signals logic.
     Only edit default_params (and optionally parameter_specs).
   - if proposal.change_type == "logic": modify logic/indicators/filters.
   - if proposal.change_type == "both": modify both logic and params.
12. This phase is logic-only: NEVER output JSON/proposal/objective rewrite.
13. Never access indicators via df['rsi']/df['ema']/df['bollinger']; always use indicators['name'].
14. For dict indicators (bollinger/macd/adx/stochastic/etc), access sub-keys before np.nan_to_num.
15. Indicator values are numpy arrays (or dict of numpy arrays): NEVER use .iloc/.loc/.shift/.rolling on indicators.
16. Bollinger must be used as indicators['bollinger']['upper|middle|lower'] (never indicators['bollinger_upper']).
17. EMA/RSI/ATR/CCI are plain arrays: NEVER use sub-keys like indicators['ema']['ema_21'].
    CCI is a plain array: use np.nan_to_num(indicators['cci']) directly.
18. ADX must be used as indicators['adx']['adx|plus_di|minus_di'] (never compare indicators['adx'] directly).
19. Supertrend must be used as indicators['supertrend']['supertrend|direction'] (no upper/lower keys).
20. Stochastic must be used as indicators['stochastic']['stoch_k|stoch_d'] (no 'signal' key).
21. Keltner must be used as indicators['keltner']['upper|middle|lower'] (same pattern as Bollinger).
22. Donchian must be used as indicators['donchian']['upper|middle|lower'] (same pattern as Bollinger).
22b. For breakout on Donchian/Bollinger/Keltner bands, compare close to previous band values via np.roll(band, 1).
23. Ichimoku must be used as indicators['ichimoku']['tenkan|kijun|senkou_a|senkou_b|chikou|cloud_position'].
24. PSAR must be used as indicators['psar']['sar|trend|signal'].
25. Vortex must be used as indicators['vortex']['vi_plus|vi_minus|signal|oscillator'].
26. Stoch_RSI must be used as indicators['stoch_rsi']['k|d|signal'] (NEVER compare indicators['stoch_rsi'] directly).
27. Aroon must be used as indicators['aroon']['aroon_up|aroon_down'].
28. Pivot_points must be used as indicators['pivot_points']['pivot|r1|s1|r2|s2|r3|s3'].
29. NEVER create bare variables like keltner_upper, donchian_lower, cci_value etc.
    Always extract from the indicators dict: e.g. kelt = indicators['keltner']; upper = np.nan_to_num(kelt['upper']).
30. For bitwise '&' and '|', both sides must be boolean mask expressions (never float/int scalars).
31. ALWAYS set "leverage": 1 in default_params. The backtest engine defaults to leverage=3 which ruins accounts.
32. Never assign `required_indicators` anywhere.
33. Never use `for i in range(...)` or `while` in signal logic.
34. ALWAYS define long_mask/short_mask before using them. Initialize with: long_mask = np.zeros(len(df), dtype=bool).
35. To implement ATR-based SL/TP, write price levels into the DataFrame columns:
    - df.loc[:, "bb_stop_long"] = entry_price - stop_atr_mult * atr  (NaN where no entry)
    - df.loc[:, "bb_tp_long"]   = entry_price + tp_atr_mult * atr    (NaN where no entry)
    - df.loc[:, "bb_stop_short"] / df.loc[:, "bb_tp_short"] for short positions.
    The simulator reads these columns automatically. Only write values on entry signal bars (NaN elsewhere).
36. If proposal logic contains cross_up(x, y), cross_down(x, y), or cross_any(x, y),
    implement them with vectorized numpy masks only (no shift/iloc/loops):
    prev_x = np.roll(x, 1); prev_y = np.roll(y, 1)
    prev_x[0] = np.nan; prev_y[0] = np.nan
    cross_up = (x > y) & (prev_x <= prev_y)
    cross_down = (x < y) & (prev_x >= prev_y)
    cross_any = cross_up | cross_down

COMMON MISTAKES (BAD → GOOD):
  BAD: rsi = df['rsi']                    → GOOD: rsi = np.nan_to_num(indicators['rsi'])
  BAD: upper = indicators['bollinger_upper'] → GOOD: upper = np.nan_to_num(indicators['bollinger']['upper'])
  BAD: signals.iloc[i] = 1.0              → GOOD: signals[long_mask] = 1.0
  BAD: atr.rolling(14).mean()             → GOOD: (already computed, just use the array)
  BAD: df['signal'] = 1                   → GOOD: signals[mask] = 1.0
  BAD: for i in range(n): signals[i]=...  → GOOD: signals[long_mask] = 1.0
  BAD: mask = close[50:] > ema[50:]       → GOOD: mask = (close > ema)  # full-length arrays
  BAD: diff = np.diff(close)              → GOOD: diff = np.insert(np.diff(close), 0, 0.0)  # keep length n

The logic block must be ready to execute inside generate_signals with ZERO modifications."""

    # ------------------------------------------------------------------
    # Core: load strategy dynamically
    # ------------------------------------------------------------------

    def _save_and_load(
        self,
        session: BuilderSession,
        code: str,
        iteration_num: int,
    ) -> type:
        """Sauvegarde le code et charge dynamiquement la classe.

        Raises:
            ImportError: Si le module ne peut pas être chargé
            AttributeError: Si la classe attendue n'existe pas
        """
        strategy_path = session.session_dir / "strategy.py"
        strategy_path.write_text(code, encoding="utf-8")

        # Sauvegarder aussi une copie versionnée
        versioned = session.session_dir / f"strategy_v{iteration_num}.py"
        versioned.write_text(code, encoding="utf-8")

        # Charger dynamiquement
        module_name = f"sandbox_{session.session_id}_v{iteration_num}"

        # Supprimer ancien module du cache si présent
        if module_name in sys.modules:
            del sys.modules[module_name]

        if _strict_sandbox_enabled():
            safe_builtins = _sandbox_safe_builtins()
            safe_builtins["__import__"] = _sandbox_import
            sandbox_globals: Dict[str, Any] = {
                "__name__": module_name,
                "__file__": str(strategy_path),
                "__builtins__": safe_builtins,
            }
            compiled = compile(code, str(strategy_path), "exec")
            exec(compiled, sandbox_globals, sandbox_globals)
            cls = sandbox_globals.get(GENERATED_CLASS_NAME)
        else:
            spec = importlib.util.spec_from_file_location(module_name, strategy_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Impossible de créer spec pour {strategy_path}")

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            cls = getattr(module, GENERATED_CLASS_NAME, None)

        if cls is None or not isinstance(cls, type):
            raise AttributeError(
                _err(
                    ERR_CLASS,
                    f"Classe '{GENERATED_CLASS_NAME}' absente du module généré",
                )
            )

        return cast(type, cls)

    # ------------------------------------------------------------------
    # Core: auto-fix required_indicators from code inspection
    # ------------------------------------------------------------------

    def _auto_fix_required_indicators(
        self, strategy_cls: type, code: str
    ) -> type:
        """Détecte les indicateurs utilisés dans le code généré et complète required_indicators.

        Scanne le code pour les patterns indicators["xxx"] et indicators['xxx'],
        cross-référence avec le registre, et monkey-patche la propriété si des
        indicateurs sont manquants.

        Returns:
            La classe (éventuellement patchée)
        """
        # Verrouillé: required_indicators doit rester déterministe via code généré.
        return strategy_cls


    def _precheck_signal_counts(
        self,
        strategy_cls: type,
        data: pd.DataFrame,
        params: Dict[str, Any],
        initial_capital: float = 10000.0,
        fees_bps: float = 10.0,
        slippage_bps: float = 5.0,
        direction_constraint: str = "long_short",
    ) -> Dict[str, Any]:
        """Estime le nombre de signaux avant simulation complète.

        Objectif: détecter très tôt les itérations "no trades" et éviter
        d'exécuter un backtest complet inutile.
        """
        try:
            engine = BacktestEngine(initial_capital=initial_capital, run_id=generate_run_id())
            strategy_instance = strategy_cls()

            base_params = getattr(strategy_instance, "default_params", {}) or {}
            merged_params = dict(base_params)
            merged_params.update(params or {})
            merged_params.setdefault("fees_bps", fees_bps)
            merged_params.setdefault("slippage_bps", slippage_bps)

            probe_df = data.copy(deep=True)
            indicators = engine._calculate_indicators(probe_df, strategy_instance, merged_params)
            raw_signals = strategy_instance.generate_signals(probe_df, indicators, merged_params)
            signals = _coerce_and_validate_signals_runtime(raw_signals, probe_df)
            signals = _apply_signal_direction_constraint(
                signals,
                direction_constraint,
            )

            signal_values = np.asarray(
                signals.values if hasattr(signals, "values") else signals,
                dtype=np.float64,
            )
            long_count = int((signal_values > 0).sum())
            short_count = int((signal_values < 0).sum())
            total_count = long_count + short_count
            bar_count = int(signal_values.size)
            nonzero_mask = signal_values != 0.0
            prev_values = np.roll(signal_values, 1)
            prev_values[0] = 0.0
            transition_nonzero = nonzero_mask & (signal_values != prev_values)
            repeated_same_nonzero = nonzero_mask & (signal_values == prev_values)
            transition_count = int(transition_nonzero.sum())
            repeated_same_count = int(repeated_same_nonzero.sum())
            signal_density = (
                float(total_count / bar_count) if bar_count > 0 else 0.0
            )
            transition_density = (
                float(transition_count / bar_count) if bar_count > 0 else 0.0
            )
            repeated_same_ratio = (
                float(repeated_same_count / total_count) if total_count > 0 else 0.0
            )

            return {
                "ok": True,
                "bar_count": bar_count,
                "long_signals": long_count,
                "short_signals": short_count,
                "total_signals": total_count,
                "signal_density": signal_density,
                "transition_signals": transition_count,
                "transition_density": transition_density,
                "repeated_same_signals": repeated_same_count,
                "repeated_same_ratio": repeated_same_ratio,
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "bar_count": 0,
                "long_signals": 0,
                "short_signals": 0,
                "total_signals": 0,
                "signal_density": 0.0,
                "transition_signals": 0,
                "transition_density": 0.0,
                "repeated_same_signals": 0,
                "repeated_same_ratio": 0.0,
            }

    def _is_pathological_signal_profile(self, signal_probe: Dict[str, Any]) -> bool:
        """Détecte un spam de signaux qui mérite un skip avant backtest complet."""
        if not signal_probe.get("ok"):
            return False

        total_signals = int(signal_probe.get("total_signals", 0) or 0)
        signal_density = float(signal_probe.get("signal_density", 0.0) or 0.0)
        repeated_same_ratio = float(signal_probe.get("repeated_same_ratio", 0.0) or 0.0)

        if total_signals < MIN_SIGNAL_COUNT_FOR_DENSITY_PRECHECK:
            return False

        return (
            signal_density >= MAX_SIGNAL_DENSITY_PRECHECK
            and repeated_same_ratio >= MAX_REPEATED_SAME_SIGNAL_RATIO_PRECHECK
        )

    @staticmethod
    def _build_precheck_overtrading_result(
        signal_probe: Dict[str, Any],
    ) -> SimpleNamespace:
        """Construit un résultat synthétique pour classifier un spam de signaux."""
        total_signals = int(signal_probe.get("total_signals", 0) or 0)
        signal_density = float(signal_probe.get("signal_density", 0.0) or 0.0)
        repeated_same_ratio = float(signal_probe.get("repeated_same_ratio", 0.0) or 0.0)

        metrics = {
            "total_return_pct": -10.0,
            "sharpe_ratio": -5.0,
            "sortino_ratio": -5.0,
            "calmar_ratio": -1.0,
            "max_drawdown_pct": -25.0,
            "total_trades": total_signals,
            "win_rate_pct": 0.0,
            "profit_factor": 0.5,
            "expectancy": -0.05,
            "avg_win": 0.0,
            "avg_loss": -1.0,
            "volatility_annual": 0.0,
        }

        return SimpleNamespace(
            success=True,
            metrics=metrics,
            sharpe_ratio=metrics["sharpe_ratio"],
            total_return_pct=metrics["total_return_pct"],
            max_drawdown_pct=metrics["max_drawdown_pct"],
            total_trades=metrics["total_trades"],
            execution_time_ms=0,
            meta={
                "precheck_skipped": True,
                "skip_reason": "pathological_signal_density",
                "signal_density": signal_density,
                "repeated_same_ratio": repeated_same_ratio,
            },
        )
    # ------------------------------------------------------------------
    # Core: run backtest on generated strategy
    # ------------------------------------------------------------------

    def _run_backtest(

        self,
        strategy_cls: type,
        data: pd.DataFrame,
        params: Dict[str, Any],
        initial_capital: float = 10000.0,
        symbol: str = "UNKNOWN",
        timeframe: str = "1h",
        fees_bps: float = 10.0,
        slippage_bps: float = 5.0,
        direction_constraint: str = "long_short",
    ) -> Any:
        """Lance un backtest sur la stratégie générée.

        Utilise BacktestEngine directement avec la classe instanciée.
        """
        run_id = generate_run_id()
        engine = BacktestEngine(initial_capital=initial_capital, run_id=run_id)

        # Instancier la stratégie
        strategy_instance = strategy_cls()
        original_generate_signals = strategy_instance.generate_signals

        def _guarded_generate_signals(df_local, indicators_local, params_local):
            try:
                raw = original_generate_signals(df_local, indicators_local, params_local)
            except IndexError as exc:
                # Enrichir le message pour que l'auto-fix LLM comprenne la cause
                raise IndexError(
                    f"{exc}. "
                    f"FIX: a boolean mask used for indexing has the wrong length. "
                    f"df has {len(df_local)} rows. Every boolean mask MUST also "
                    f"have exactly {len(df_local)} elements. "
                    f"Common cause: np.diff() returns n-1 elements, or "
                    f"array[window:] returns n-window elements. "
                    f"Use np.insert(np.diff(x), 0, 0.0) or np.zeros(n) with "
                    f"conditional fill instead of slicing."
                ) from exc
            constrained = _coerce_and_validate_signals_runtime(raw, df_local)
            return _apply_signal_direction_constraint(
                constrained,
                direction_constraint,
            )

        strategy_instance.generate_signals = _guarded_generate_signals

        # Injecter fees/slippage dans params pour le moteur
        merged_params = dict(params)
        merged_params.setdefault("fees_bps", fees_bps)
        merged_params.setdefault("slippage_bps", slippage_bps)

        # Exécuter le backtest via l'engine (mode objet)
        result = engine.run(
            df=data,
            strategy=strategy_instance,
            params=merged_params,
            symbol=symbol,
            timeframe=timeframe,
            silent_mode=True,
            # Builder privilégie la fiabilité des métriques (ruine, Sharpe, DD)
            # plutôt que la vitesse brute.
            fast_metrics=False,
        )

        # Convertir en résultat léger avec .metrics dict
        metrics_pct = normalize_metrics(result.metrics, "pct")

        return SimpleNamespace(
            success=True,
            metrics=metrics_pct,
            sharpe_ratio=metrics_pct.get("sharpe_ratio", 0.0),
            total_return_pct=metrics_pct.get("total_return_pct", 0.0),
            max_drawdown_pct=metrics_pct.get("max_drawdown_pct", 0.0),
            total_trades=metrics_pct.get("total_trades", 0),
            execution_time_ms=getattr(result, "execution_time_ms", 0),
            run_result=result,
        )

    # ------------------------------------------------------------------
    # Boucle principale
    # ------------------------------------------------------------------

    def run(
        self,
        objective: str,
        data: pd.DataFrame,
        *,
        max_iterations: int = 10,
        target_sharpe: float = 1.0,
        initial_capital: float = 10000.0,
        symbol: str = "UNKNOWN",
        timeframe: str = "1h",
        fees_bps: float = 10.0,
        slippage_bps: float = 5.0,
    ) -> BuilderSession:
        """
        Lance la boucle complète de construction de stratégie.

        Args:
            objective: Description textuelle de la stratégie souhaitée
            data: DataFrame OHLCV pour backtest
            max_iterations: Nombre max d'itérations
            target_sharpe: Sharpe cible pour acceptation automatique
            initial_capital: Capital initial pour les backtests
            symbol: Symbole/token (ex: BTCUSDT, DOGEUSDC)
            timeframe: Timeframe des données (ex: 1h, 5m, 4h)
            fees_bps: Frais de trading en basis points
            slippage_bps: Slippage en basis points

        Returns:
            BuilderSession avec l'historique complet et le meilleur résultat
        """
        raw_objective = str(objective or "")
        objective = sanitize_objective_text(raw_objective)
        if not objective and not _looks_like_log_pollution(raw_objective):
            objective = raw_objective.strip()
        if raw_objective.strip() != objective:
            logger.warning(
                "builder_objective_sanitized raw_len=%d clean_len=%d",
                len(raw_objective),
                len(objective),
            )
        if not objective:
            raise ValueError(
                "Objectif Builder vide ou invalide après nettoyage "
                "(probable collage de logs/traceback)."
            )

        session_id = self.create_session_id(objective)
        session_dir = self.get_session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        # Calculer le contexte de marché à partir des données
        n_bars = len(data)
        date_range_start = ""
        date_range_end = ""
        try:
            idx = data.index
            if hasattr(idx, 'min'):
                date_range_start = str(idx.min())[:19]
                date_range_end = str(idx.max())[:19]
        except Exception:
            pass

        session = BuilderSession(
            session_id=session_id,
            objective=objective,
            session_dir=session_dir,
            available_indicators=self.available_indicators,
            max_iterations=max_iterations,
            target_sharpe=target_sharpe,
            symbol=symbol,
            timeframe=timeframe,
            n_bars=n_bars,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            fees_bps=fees_bps,
            slippage_bps=slippage_bps,
            initial_capital=initial_capital,
        )
        session.direction_constraint = _infer_direction_constraint_from_objective(
            objective
        )
        self._emit_progress(
            "session_start",
            max_iterations=max_iterations,
            symbol=symbol,
            timeframe=timeframe,
        )

        dataset_ok, dataset_msg = _validate_builder_dataset_exploitability(
            data,
            symbol=symbol,
            timeframe=timeframe,
        )
        if not dataset_ok:
            logger.warning(
                "builder_timeframe_rejected symbol=%s timeframe=%s reason=%s",
                symbol,
                timeframe,
                dataset_msg,
            )
            session.status = "failed"
            iteration = BuilderIteration(iteration=1)
            iteration.error = dataset_msg
            session.iterations.append(iteration)
            self._save_session_summary(session)
            self._emit_progress(
                "session_done",
                status=session.status,
                total_iterations=len(session.iterations),
                best_sharpe=session.best_sharpe,
            )
            return session

        logger.info(
            "strategy_builder_start session=%s objective='%s' indicators=%d",
            session_id, objective, len(self.available_indicators),
        )

        # ── Flux de pensée temps réel ──
        model_name = getattr(getattr(self.llm, 'config', None), 'model', '?')
        ts = ThoughtStream(session_id, objective, model_name)

        last_iteration: Optional[BuilderIteration] = None
        consecutive_failures = 0
        fallback_count = 0  # compteur de fallbacks déterministes dans la session

        for i in range(1, max_iterations + 1):
            iteration = BuilderIteration(iteration=i)
            self._emit_progress(
                "iteration_start",
                iteration=i,
                max_iterations=max_iterations,
            )
            ts.iteration_start(i, max_iterations)

            # ── Circuit breaker ──
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                recovered, last_iteration, consecutive_failures, fallback_count, reset_event = (
                    self._attempt_session_auto_reset(
                        session,
                        iteration_num=i,
                        trigger="consecutive_failures",
                        reason=(
                            f"{consecutive_failures} échecs consécutifs "
                            f"(seuil={MAX_CONSECUTIVE_FAILURES})"
                        ),
                        last_iteration=last_iteration,
                        consecutive_failures=consecutive_failures,
                        fallback_count=fallback_count,
                    )
                )
                if recovered:
                    iteration.phase_feedback.setdefault("session_reset", {}).update(
                        reset_event
                    )
                    ts.warning(
                        "Auto-reset Builder: reprise sur le meilleur ancrage stable "
                        "disponible avant nouvelle tentative."
                    )
                else:
                    ts.circuit_breaker(consecutive_failures, MAX_CONSECUTIVE_FAILURES)
                    logger.warning(
                        "builder_circuit_breaker consecutive=%d",
                        consecutive_failures,
                    )
                    session.status = "failed"
                    break

            # ── Circuit breaker fallback ──
            if fallback_count >= MAX_DETERMINISTIC_FALLBACKS:
                recovered, last_iteration, consecutive_failures, fallback_count, reset_event = (
                    self._attempt_session_auto_reset(
                        session,
                        iteration_num=i,
                        trigger="deterministic_fallbacks",
                        reason=(
                            f"{fallback_count} fallbacks déterministes "
                            f"(seuil={MAX_DETERMINISTIC_FALLBACKS})"
                        ),
                        last_iteration=last_iteration,
                        consecutive_failures=consecutive_failures,
                        fallback_count=fallback_count,
                    )
                )
                if recovered:
                    iteration.phase_feedback.setdefault("session_reset", {}).update(
                        reset_event
                    )
                    ts.warning(
                        "Auto-reset Builder: saturation fallback détectée, "
                        "redémarrage sur une base plus saine."
                    )
                else:
                    ts.warning(
                        f"Arrêt: {fallback_count} fallbacks déterministes utilisés. "
                        "Le LLM ne parvient pas à générer du code valide pour cette API."
                    )
                    logger.warning(
                        "builder_fallback_circuit_breaker count=%d",
                        fallback_count,
                    )
                    session.status = "failed"
                    break

            try:
                # ── Phase 1 : Proposition ──
                logger.info("builder_iter_%d_proposal", i)
                self._emit_progress("phase_start", iteration=i, phase="proposal")
                ts.proposal_sent(has_previous=last_iteration is not None)
                t0 = time.perf_counter()
                proposal, proposal_feedback = self._ask_proposal(
                    session, last_iteration
                )
                iteration.phase_feedback["proposal"] = proposal_feedback
                dt_proposal = time.perf_counter() - t0

                # Garde : proposition vide → retry avec prompt simplifié
                if _is_invalid_proposal(proposal):
                    ts.warning(
                        "Proposition invalide après retry contractuel — fallback déterministe"
                    )
                    issues = _proposal_issues(proposal)
                    iteration.phase_feedback.setdefault("proposal", {})[
                        "issues_after_retry"
                    ] = issues
                    proposal = _build_deterministic_proposal_fallback(
                        objective=session.objective,
                        available_indicators=self.available_indicators,
                        last_iteration=last_iteration,
                    )
                    proposal = _sanitize_proposal_payload(
                        proposal,
                        available_indicators=self.available_indicators,
                        objective=session.objective,
                        direction_constraint=session.direction_constraint,
                    )
                    iteration.phase_feedback.setdefault("proposal", {})[
                        "fallback_deterministic_used"
                    ] = True
                    iteration.phase_feedback.setdefault("proposal", {})[
                        "source"
                    ] = "deterministic_fallback"

                iteration.hypothesis = proposal.get(
                    "hypothesis", f"Itération {i}"
                )
                proposal["change_type"] = _normalize_change_type(
                    proposal.get("change_type", "logic")
                )
                policy_ct = _policy_change_type_override(
                    session=session,
                    last_iteration=last_iteration,
                )
                if policy_ct and proposal["change_type"] != policy_ct:
                    iteration.phase_feedback.setdefault("proposal", {})[
                        "change_type_overridden"
                    ] = {
                        "from": proposal["change_type"],
                        "to": policy_ct,
                        "reason": "diagnostic_policy",
                    }
                    logger.info(
                        "builder_iter_%d_change_type_overridden from=%s to=%s",
                        i,
                        proposal["change_type"],
                        policy_ct,
                    )
                    proposal["change_type"] = policy_ct
                iteration.change_type = proposal["change_type"]
                self._emit_progress(
                    "phase_done",
                    iteration=i,
                    phase="proposal",
                    hypothesis=iteration.hypothesis,
                )
                ts.proposal_received(proposal, dt_proposal)

                # Valider que les indicateurs demandés existent
                used = proposal.get("used_indicators", [])
                unknown = [
                    ind for ind in used
                    if ind.lower() not in (x.lower() for x in self.available_indicators)
                ]
                if unknown:
                    logger.warning(
                        "builder_unknown_indicators unknown=%s", unknown
                    )
                    proposal["used_indicators"] = [
                        ind for ind in used if ind.lower() in
                        (x.lower() for x in self.available_indicators)
                    ]

                # ── Phase 2 : Génération de code ──
                logger.info("builder_iter_%d_codegen", i)
                self._emit_progress("phase_start", iteration=i, phase="code")
                ts.codegen_sent()
                t0 = time.perf_counter()
                change_type = _normalize_change_type(
                    proposal.get("change_type", "logic")
                )
                has_stable_base_code = bool(
                    last_iteration
                    and last_iteration.code
                    and last_iteration.error is None
                    and last_iteration.backtest_result is not None
                )
                if change_type == "params" and not has_stable_base_code:
                    iteration.phase_feedback.setdefault("proposal", {})[
                        "change_type_overridden"
                    ] = {
                        "from": "params",
                        "to": "logic",
                        "reason": "no_stable_base_code",
                    }
                    logger.info(
                        "builder_iter_%d_change_type_overridden from=params to=logic "
                        "reason=no_stable_base_code",
                        i,
                    )
                    change_type = "logic"
                    proposal["change_type"] = "logic"
                    iteration.change_type = "logic"
                code: str
                raw_code: str = ""
                code_feedback: Dict[str, Any] = {
                    "phase": "code",
                    "initial_kind": "local_patch",
                    "realign_attempts": 0,
                    "realign_success": False,
                    "final_valid": True,
                }
                if change_type == "params" and has_stable_base_code and last_iteration and last_iteration.code:
                    patched = _rewrite_default_params_from_proposal(
                        last_iteration.code, proposal,
                    )
                    if patched:
                        code = patched
                        code_feedback["source"] = "params_patch"
                        code_feedback["final_kind"] = "python"
                        iteration.phase_feedback["code"] = code_feedback
                        logger.info(
                            "builder_iter_%d_params_only_patch applied (no logic rewrite)",
                            i,
                        )
                    else:
                        raw_code, code_feedback = self._ask_code(
                            session, proposal, last_iteration
                        )
                        iteration.phase_feedback["code"] = code_feedback
                else:
                    raw_code, code_feedback = self._ask_code(
                        session, proposal, last_iteration
                    )
                    iteration.phase_feedback["code"] = code_feedback

                if not (change_type == "params" and has_stable_base_code and last_iteration and last_iteration.code and "source" in code_feedback and code_feedback.get("source") == "params_patch"):
                    req_inds = [
                        str(x).strip().lower()
                        for x in proposal.get("used_indicators", [])
                        if isinstance(x, str) and str(x).strip()
                    ]
                    logic_block = _extract_generate_signals_logic_block(raw_code)
                    if not logic_block.strip():
                        logic_block = _extract_python_from_response(raw_code)
                    logic_block = _postprocess_llm_logic_block(logic_block, req_inds)
                    logic_ok, logic_err = _validate_llm_logic_block(logic_block)
                    if not logic_ok:
                        code_feedback["validation_error"] = logic_err
                        ts.warning(f"Bloc logique invalide: {logic_err}")
                        retry_logic_raw = self._retry_code_simple(proposal)
                        retry_logic = _extract_python_from_response(retry_logic_raw)
                        retry_logic = _postprocess_llm_logic_block(retry_logic, req_inds)
                        retry_ok, retry_err = _validate_llm_logic_block(retry_logic)
                        if not retry_ok:
                            code_feedback["validation_error_retry"] = retry_err
                            fallback_code = _build_deterministic_fallback_code(
                                proposal,
                                variant=fallback_count,
                            )
                            fallback_count += 1
                            fallback_code = _repair_code(fallback_code)
                            is_valid_fb, error_msg_fb = validate_generated_code(fallback_code)
                            if is_valid_fb:
                                code = fallback_code
                                code_feedback["fallback_deterministic_used"] = True
                                code_feedback["source"] = "deterministic_fallback"
                                code_feedback["fallback_variant"] = fallback_count - 1
                                iteration.phase_feedback["code"] = code_feedback
                                ts.warning(
                                    "Bloc logique invalide après retry: fallback déterministe appliqué."
                                )
                                logger.warning(
                                    "builder_iter_%d_logic_invalid_retry_fallback variant=%d",
                                    i,
                                    fallback_count - 1,
                                )
                            else:
                                iteration.error = (
                                    "Bloc logique LLM invalide après retry + fallback invalide: "
                                    f"{error_msg_fb or retry_err}"
                                )
                                iteration.phase_feedback["code"] = code_feedback
                                consecutive_failures += 1
                                session.iterations.append(iteration)
                                self._safe_save_session_summary(session)
                                self._emit_progress(
                                    "iteration_error",
                                    iteration=i,
                                    phase="code",
                                    error=iteration.error,
                                )
                                last_iteration = iteration
                                continue
                        else:
                            logic_block = retry_logic
                            code_feedback["logic_retry_used"] = True
                            code = _build_deterministic_strategy_code(proposal, logic_block)
                    if "source" not in code_feedback:
                        code = _build_deterministic_strategy_code(proposal, logic_block)
                dt_code = time.perf_counter() - t0

                iteration.code = code
                ts.codegen_received(code, dt_code)

                # Contrat strict params-only: logique identique entre itérations.
                if change_type == "params" and last_iteration and last_iteration.code:
                    contract_ok, contract_reason = _params_only_contract_respected(
                        last_iteration.code,
                        code,
                    )
                    if not contract_ok:
                        ts.warning(f"Violation params-only: {contract_reason}")
                        logger.warning(
                            "builder_iter_%d_params_only_violation: %s",
                            i,
                            contract_reason,
                        )
                        patched = _rewrite_default_params_from_proposal(
                            last_iteration.code, proposal,
                        )
                        if patched:
                            code = patched
                            iteration.code = code
                            ts.warning(
                                "Correctif automatique appliqué: "
                                "logique précédente conservée, params réécrits."
                            )
                        else:
                            # Fallback non bloquant: conserver la version précédente
                            # plutôt que casser la session entière sur une itération params.
                            code = last_iteration.code
                            iteration.code = code
                            iteration.phase_feedback.setdefault("code", {})[
                                "params_contract_fallback"
                            ] = "reused_previous_code"
                            ts.warning(
                                "Fallback params-only: code précédent conservé "
                                "(patch default_params impossible)."
                            )

                # ── Phase 3 : Auto-repair + Validation syntaxe + sécurité ──
                code = _repair_code(code)
                iteration.code = code
                is_valid, error_msg = validate_generated_code(code)

                # Si invalide → retry avec prompt squelette + repair
                if not is_valid:
                    ts.warning(f"Code invalide: {error_msg} — retry simplifié")
                    ts.retry("code_validation", 2)
                    logger.warning(
                        "builder_iter_%d_invalid code=%s — retrying", i, error_msg,
                    )
                    iteration.phase_feedback.setdefault("code", {})[
                        "validation_error"
                    ] = error_msg
                    req_inds = [
                        str(x).strip().lower()
                        for x in proposal.get("used_indicators", [])
                        if isinstance(x, str) and str(x).strip()
                    ]
                    retry_logic_raw = self._retry_code_simple(proposal)
                    retry_logic = _extract_python_from_response(retry_logic_raw)
                    retry_logic = _postprocess_llm_logic_block(retry_logic, req_inds)
                    logic_ok, logic_err = _validate_llm_logic_block(retry_logic)
                    if not logic_ok:
                        is_valid_r, error_msg_r = False, logic_err
                        retry_code = ""
                    else:
                        retry_code = _build_deterministic_strategy_code(proposal, retry_logic)
                        retry_code = _repair_code(retry_code)
                        is_valid_r, error_msg_r = validate_generated_code(retry_code)
                    if is_valid_r:
                        code = retry_code
                        iteration.code = code
                        is_valid, error_msg = True, ""
                    else:
                        iteration.phase_feedback.setdefault("code", {})[
                            "validation_error_retry"
                        ] = error_msg_r
                        # Fallback déterministe pour ne pas perdre l'itération
                        fallback_code = _build_deterministic_fallback_code(
                            proposal, variant=fallback_count,
                        )
                        fallback_count += 1
                        fallback_code = _repair_code(fallback_code)
                        is_valid_fb, error_msg_fb = validate_generated_code(fallback_code)
                        if is_valid_fb:
                            code = fallback_code
                            iteration.code = code
                            iteration.phase_feedback.setdefault("code", {})[
                                "fallback_deterministic_used"
                            ] = True
                            iteration.phase_feedback.setdefault("code", {})[
                                "source"
                            ] = "deterministic_fallback"
                            iteration.phase_feedback.setdefault("code", {})[
                                "fallback_variant"
                            ] = fallback_count - 1
                            ts.warning(
                                f"Code LLM invalide après retry: fallback déterministe v{fallback_count - 1} appliqué."
                            )
                            is_valid, error_msg = True, ""
                        else:
                            error_msg = (
                                f"{error_msg} | retry: {error_msg_r} | "
                                f"fallback: {error_msg_fb}"
                            )

                ts.validation(is_valid, error_msg)
                if not is_valid:
                    iteration.error = f"Validation échouée: {error_msg}"
                    logger.warning("builder_iter_%d_invalid_final code=%s", i, error_msg)
                    consecutive_failures += 1
                    session.iterations.append(iteration)
                    self._safe_save_session_summary(session)
                    self._emit_progress(
                        "iteration_error",
                        iteration=i,
                        phase="validation",
                        error=iteration.error,
                    )
                    last_iteration = iteration
                    continue

                # ── Phase 4 : Chargement dynamique ──
                logger.info("builder_iter_%d_load", i)
                strategy_cls = self._save_and_load(session, code, i)

                # ── Phase 4b : Auto-fix required_indicators ──
                strategy_cls = self._auto_fix_required_indicators(
                    strategy_cls, code
                )

                # ── Phase 5 : Backtest + Pre-reflection (parallel) ──
                logger.info("builder_iter_%d_backtest", i)
                self._emit_progress("phase_start", iteration=i, phase="backtest")
                ts.backtest_start()
                default_params = proposal.get("default_params", {})

                pre_reflection_future = None
                pre_reflection_text = ""
                _pre_pool = None

                signal_probe = self._precheck_signal_counts(
                    strategy_cls,
                    data,
                    default_params,
                    initial_capital=initial_capital,
                    fees_bps=session.fees_bps,
                    slippage_bps=session.slippage_bps,
                    direction_constraint=session.direction_constraint,
                )
                iteration.phase_feedback.setdefault("precheck", {}).update(signal_probe)

                if signal_probe.get("ok") and int(signal_probe.get("total_signals", 0)) <= 0:
                    long_n = int(signal_probe.get("long_signals", 0) or 0)
                    short_n = int(signal_probe.get("short_signals", 0) or 0)
                    ts.warning(
                        "Pré-check: aucun signal d'entrée (long=0, short=0). "
                        "Itération marquée no_trades, changement logique forcé."
                    )
                    logger.warning(
                        "builder_iter_%d_precheck_no_signals long=%d short=%d",
                        i,
                        long_n,
                        short_n,
                    )
                    iteration.phase_feedback.setdefault("precheck", {})["backtest_skipped"] = True
                    proposal["_stagnation_detected"] = True
                    bt_result = SimpleNamespace(
                        success=True,
                        metrics={
                            "total_return_pct": 0.0,
                            "sharpe_ratio": 0.0,
                            "sortino_ratio": 0.0,
                            "calmar_ratio": 0.0,
                            "max_drawdown_pct": 0.0,
                            "total_trades": 0,
                            "win_rate_pct": 0.0,
                            "profit_factor": 1.0,
                            "expectancy": 0.0,
                        },
                        sharpe_ratio=0.0,
                        total_return_pct=0.0,
                        max_drawdown_pct=0.0,
                        total_trades=0,
                        execution_time_ms=0,
                    )
                elif self._is_pathological_signal_profile(signal_probe):
                    total_n = int(signal_probe.get("total_signals", 0) or 0)
                    density = float(signal_probe.get("signal_density", 0.0) or 0.0)
                    repeated_same_ratio = float(
                        signal_probe.get("repeated_same_ratio", 0.0) or 0.0
                    )
                    transition_n = int(signal_probe.get("transition_signals", 0) or 0)
                    ts.warning(
                        "Pré-check: densité de signaux aberrante "
                        f"({density:.1%}, répétitions identiques {repeated_same_ratio:.1%}, "
                        f"transitions {transition_n}). Backtest complet ignoré, "
                        "correction logique forcée."
                    )
                    logger.warning(
                        "builder_iter_%d_precheck_signal_spam total=%d density=%.3f "
                        "repeated_same_ratio=%.3f transitions=%d",
                        i,
                        total_n,
                        density,
                        repeated_same_ratio,
                        transition_n,
                    )
                    iteration.phase_feedback.setdefault("precheck", {}).update(
                        {
                            "pathological_signal_density": True,
                            "skip_reason": "pathological_signal_density",
                            "backtest_skipped": True,
                            "suggested_fix": (
                                "deduplicate_consecutive_signals_or_tighten_entry_logic"
                            ),
                        }
                    )
                    proposal["_stagnation_detected"] = True
                    bt_result = self._build_precheck_overtrading_result(signal_probe)
                else:
                    # Launch pre-reflection in parallel with backtest
                    pre_reflection_future = None
                    pre_reflection_text = ""
                    _pre_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                    try:
                        pre_reflection_future = _pre_pool.submit(
                            self._ask_pre_reflection,
                            session, proposal, code, i,
                        )
                    except Exception:
                        pass

                    try:
                        bt_result = self._run_backtest(
                            strategy_cls, data, default_params, initial_capital,
                            symbol=session.symbol,
                            timeframe=session.timeframe,
                            fees_bps=session.fees_bps,
                            slippage_bps=session.slippage_bps,
                            direction_constraint=session.direction_constraint,
                        )
                    except Exception as bt_exc:
                        bt_error = f"{type(bt_exc).__name__}: {bt_exc}"
                        tb = _safe_format_exception(bt_exc)
                        tb_tail = ""
                        if tb:
                            tb_lines = [line.rstrip() for line in tb.splitlines() if line.rstrip()]
                            tb_tail = "\n".join(tb_lines[-16:]).strip()
                        iteration.phase_feedback.setdefault("backtest", {})[
                            "runtime_error"
                        ] = bt_error
                        if tb_tail:
                            iteration.phase_feedback.setdefault("backtest", {})[
                                "runtime_traceback_tail"
                            ] = tb_tail
                        ts.warning(
                            f"Backtest runtime error: {bt_error} — tentative auto-fix"
                        )
                        logger.warning(
                            "builder_iter_%d_backtest_runtime_error: %s", i, bt_error
                        )

                        runtime_error_for_llm = bt_error
                        if tb_tail:
                            runtime_error_for_llm = (
                                f"{bt_error}\n\nTraceback (tail):\n{tb_tail}"
                            )

                        retry_code = self._retry_code_runtime_fix(
                            proposal=proposal,
                            failing_code=code,
                            runtime_error=runtime_error_for_llm,
                        )
                        retry_code = _repair_code(retry_code)
                        valid_retry, retry_err = validate_generated_code(retry_code)
                        used_runtime_fallback = False
                        if not valid_retry:
                            iteration.phase_feedback.setdefault("backtest", {})[
                                "runtime_fix_validation_error"
                            ] = retry_err
                            fallback_code = _build_deterministic_fallback_code(
                                proposal, variant=fallback_count,
                            )
                            fallback_count += 1
                            fallback_code = _repair_code(fallback_code)
                            valid_fb, fb_err = validate_generated_code(fallback_code)
                            if not valid_fb:
                                raise ValueError(
                                    "Runtime-fix invalide et fallback déterministe invalide: "
                                    f"{retry_err} | {fb_err}"
                                )
                            retry_code = fallback_code
                            used_runtime_fallback = True
                            iteration.phase_feedback.setdefault("backtest", {})[
                                "runtime_fix_fallback_deterministic_used"
                            ] = True
                            iteration.phase_feedback.setdefault("code", {})[
                                "source"
                            ] = "deterministic_fallback"

                        retry_cls = self._save_and_load(session, retry_code, i)
                        retry_cls = self._auto_fix_required_indicators(
                            retry_cls, retry_code
                        )
                        try:
                            bt_result = self._run_backtest(
                                retry_cls, data, default_params, initial_capital,
                                symbol=session.symbol,
                                timeframe=session.timeframe,
                                fees_bps=session.fees_bps,
                                slippage_bps=session.slippage_bps,
                                direction_constraint=session.direction_constraint,
                            )
                        except Exception as retry_bt_exc:
                            if used_runtime_fallback:
                                raise
                            iteration.phase_feedback.setdefault("backtest", {})[
                                "runtime_fix_retry_error"
                            ] = f"{type(retry_bt_exc).__name__}: {retry_bt_exc}"
                            fallback_code = _build_deterministic_fallback_code(
                                proposal, variant=fallback_count,
                            )
                            fallback_count += 1
                            fallback_code = _repair_code(fallback_code)
                            valid_fb2, fb_err2 = validate_generated_code(fallback_code)
                            if not valid_fb2:
                                raise ValueError(
                                    "Runtime-fix backtest failed and deterministic fallback "
                                    f"is invalid: {fb_err2}"
                                )
                            fallback_cls = self._save_and_load(session, fallback_code, i)
                            fallback_cls = self._auto_fix_required_indicators(
                                fallback_cls, fallback_code
                            )
                            bt_result = self._run_backtest(
                                fallback_cls, data, default_params, initial_capital,
                                symbol=session.symbol,
                                timeframe=session.timeframe,
                                fees_bps=session.fees_bps,
                                slippage_bps=session.slippage_bps,
                                direction_constraint=session.direction_constraint,
                            )
                            retry_code = fallback_code
                            used_runtime_fallback = True
                            iteration.phase_feedback.setdefault("backtest", {})[
                                "runtime_fix_fallback_deterministic_used"
                            ] = True
                            iteration.phase_feedback.setdefault("code", {})[
                                "source"
                            ] = "deterministic_fallback"
                        code = retry_code
                        iteration.code = retry_code
                        iteration.phase_feedback.setdefault("backtest", {})[
                            "runtime_fix_applied"
                        ] = True
                    self._emit_completed_backtest(
                        bt_result,
                        session=session,
                        iteration_num=i,
                    )
                iteration.backtest_result = bt_result
                self._emit_progress(
                    "phase_done",
                    iteration=i,
                    phase="backtest",
                    sharpe=bt_result.metrics.get("sharpe_ratio", 0.0),
                    total_return_pct=bt_result.metrics.get("total_return_pct", 0.0),
                    backtest_skipped=bool(
                        iteration.phase_feedback.get("precheck", {}).get(
                            "backtest_skipped"
                        )
                    ),
                )
                ts.backtest_result(bt_result.metrics)

                # Collect pre-reflection result (ran in parallel with backtest)
                if pre_reflection_future is not None:
                    try:
                        pre_reflection_text = pre_reflection_future.result(timeout=5)
                        if pre_reflection_text:
                            iteration.phase_feedback.setdefault("pre_reflection", {})[
                                "text"
                            ] = pre_reflection_text
                            ts._append(f"🧠  PRÉ-RÉFLEXION (pendant backtest)\n    {pre_reflection_text[:300]}\n\n")
                    except Exception:
                        pass
                    finally:
                        _pre_pool.shutdown(wait=False)

                # Backtest réussi → reset circuit breaker
                consecutive_failures = 0

                # ── Phase 6 : Mise à jour best ──
                # Detect if this iteration used a deterministic fallback
                _code_fb = iteration.phase_feedback.get("code", {})
                _prop_fb = iteration.phase_feedback.get("proposal", {})
                if (
                    _code_fb.get("fallback_deterministic_used")
                    or _code_fb.get("source") == "deterministic_fallback"
                    or _prop_fb.get("fallback_deterministic_used")
                    or _code_fb.get("runtime_fix_fallback_deterministic_used")
                ):
                    iteration.is_fallback = True

                metrics_cur = bt_result.metrics or {}
                sharpe = _metric_float(metrics_cur, "sharpe_ratio", float("-inf"))
                rank_score = _ranking_sharpe(
                    metrics_cur,
                    target_sharpe=session.target_sharpe,
                )
                score_payload = compute_continuous_builder_score(
                    metrics_cur,
                    target_sharpe=session.target_sharpe,
                )
                iteration.phase_feedback.setdefault("scoring", {}).update(
                    {
                        "continuous_score": score_payload.get("score"),
                        "drawdown_excess_pct": score_payload.get("drawdown_excess_pct"),
                        "components": score_payload.get("components"),
                        "penalties": score_payload.get("penalties"),
                    }
                )
                if math.isfinite(sharpe) and sharpe > session.best_sharpe:
                    session.best_sharpe = sharpe

                should_promote_best = False
                if session.best_iteration is None:
                    should_promote_best = True
                elif session.best_iteration.is_fallback and not iteration.is_fallback:
                    should_promote_best = True
                elif not iteration.is_fallback and rank_score > session.best_score:
                    should_promote_best = True

                if should_promote_best:
                    session.best_score = rank_score
                    session.best_iteration = iteration
                    ts.best_update(sharpe, i)
                elif iteration.is_fallback:
                    logger.info(
                        "builder_iter_%d_fallback_not_scored rank_score=%.3f",
                        i, rank_score,
                    )

                # ── Phase 6b : Détection de stagnation ──
                cur_fp = _metrics_fingerprint(metrics_cur)
                if last_iteration and last_iteration.backtest_result:
                    prev_fp = _metrics_fingerprint(
                        last_iteration.backtest_result.metrics or {}
                    )
                    if cur_fp == prev_fp:
                        iteration.phase_feedback.setdefault("stagnation", {})[
                            "identical_metrics"
                        ] = True
                        ts.warning(
                            "Stagnation détectée: métriques identiques à "
                            "l'itération précédente — forçage changement radical."
                        )
                        logger.warning(
                            "builder_iter_%d_stagnation fingerprint=%s",
                            i, cur_fp,
                        )
                        # Injecter un signal fort dans la proposition pour
                        # forcer le LLM à changer d'approche à l'itération suivante
                        proposal["_stagnation_detected"] = True

                # ── Phase 7 : Diagnostic déterministe + Analyse LLM ──
                logger.info("builder_iter_%d_diagnostic", i)
                diag_history = [
                    {
                        "sharpe": (
                            it.backtest_result.metrics.get("sharpe_ratio", 0)
                            if it.backtest_result else 0
                        ),
                        "diagnostic_category": it.diagnostic_category,
                    }
                    for it in session.iterations
                ]
                diag = compute_diagnostic(
                    bt_result.metrics, diag_history, session.target_sharpe,
                )
                iteration.diagnostic_category = diag["category"]
                iteration.diagnostic_detail = diag
                if not iteration.change_type:
                    iteration.change_type = _normalize_change_type(
                        diag.get("change_type", "logic")
                    )
                ts.diagnostic(diag)

                positive_required = _required_positive_count_for_iteration(i)
                if positive_required > 0:
                    positive_count = _count_positive_iterations(session.iterations)
                    if _is_positive_progress_iteration(metrics_cur):
                        positive_count += 1

                    # Logging détaillé du comptage pour diagnostic
                    fallback_positive_count = sum(
                        1 for it in session.iterations
                        if it.backtest_result and it.is_fallback
                        and _is_positive_progress_iteration(it.backtest_result.metrics or {})
                    )
                    llm_positive_count = positive_count - min(fallback_positive_count, MAX_POSITIVE_FALLBACK_COUNT)

                    iteration.phase_feedback.setdefault("decision", {})[
                        "positive_progress_gate"
                    ] = {
                        "iteration": i,
                        "required_positive": positive_required,
                        "observed_positive": positive_count,
                        "llm_positive": llm_positive_count,
                        "fallback_positive": min(fallback_positive_count, MAX_POSITIVE_FALLBACK_COUNT),
                    }
                    if positive_count < positive_required:
                        gate_msg = (
                            f"Arrêt anticipé: progression positive insuffisante "
                            f"au checkpoint {i} ({positive_count}/{positive_required} positifs, "
                            f"dont {llm_positive_count} LLM et {min(fallback_positive_count, MAX_POSITIVE_FALLBACK_COUNT)} fallback)."
                        )
                        ts.warning(gate_msg)
                        logger.info(
                            "builder_iter_%d_positive_gate_stop observed=%d required=%d "
                            "llm=%d fallback=%d",
                            i,
                            positive_count,
                            positive_required,
                            llm_positive_count,
                            min(fallback_positive_count, MAX_POSITIVE_FALLBACK_COUNT),
                        )
                        iteration.analysis = (
                            "[Policy] early stop triggered by positive progression gate "
                            f"at iteration {i}: {positive_count}/{positive_required}."
                        )
                        iteration.decision = "stop"
                        session.status = "failed"
                        session.iterations.append(iteration)
                        self._safe_save_session_summary(session)
                        self._emit_progress(
                            "iteration_done",
                            iteration=i,
                            decision=iteration.decision,
                            status=session.status,
                        )
                        last_iteration = iteration
                        break
                    logger.info(
                        "builder_iter_%d_positive_gate_pass observed=%d required=%d",
                        i,
                        positive_count,
                        positive_required,
                    )

                logger.info(
                    "builder_iter_%d_analysis diag=%s sev=%s",
                    i, diag["category"], diag["severity"],
                )
                self._emit_progress("phase_start", iteration=i, phase="analysis")
                ts.analysis_sent()
                t0 = time.perf_counter()
                analysis, decision = self._ask_analysis(
                    session, iteration, diag,
                    pre_reflection=pre_reflection_text,
                )
                dt_analysis = time.perf_counter() - t0

                # Garde anti-arrêt prématuré: forcer la phase d'ajustement
                # tant que la session n'a pas suffisamment itéré.
                successful_iters = (
                    sum(1 for it in session.iterations if it.backtest_result is not None)
                    + 1
                )
                if decision == "stop" and i < max_iterations:
                    if (
                        successful_iters < MIN_SUCCESSFUL_ITERATIONS_BEFORE_STOP
                        or session.best_sharpe < session.target_sharpe
                    ):
                        ts.warning(
                            "Décision 'stop' ignorée: poursuite obligatoire "
                            "de la phase test/ajustement."
                        )
                        logger.info(
                            "builder_iter_%d_stop_overridden successful_iters=%d "
                            "best_sharpe=%.3f target=%.3f",
                            i,
                            successful_iters,
                            session.best_sharpe,
                            session.target_sharpe,
                        )
                        decision = "continue"
                        analysis = (
                            f"{analysis}\n"
                            "[Policy] stop overridden to continue optimization."
                        )
                        iteration.phase_feedback.setdefault("decision", {})[
                            "stop_overridden"
                        ] = True

                trades = int(metrics_cur.get("total_trades", 0) or 0)
                max_dd = abs(float(metrics_cur.get("max_drawdown_pct", 0) or 0))
                accept_allowed, accept_reason = _is_accept_candidate(
                    metrics_cur,
                    target_sharpe=session.target_sharpe,
                )
                if decision == "accept" and i < max_iterations:
                    if not accept_allowed:
                        ts.warning(
                            "Décision 'accept' ignorée: qualité statistique "
                            "insuffisante, poursuite optimisation."
                        )
                        logger.info(
                            "builder_iter_%d_accept_overridden reason=%s trades=%d "
                            "best_sharpe=%.3f best_score=%.2f target=%.3f max_dd=%.2f",
                            i,
                            accept_reason,
                            trades,
                            session.best_sharpe,
                            session.best_score,
                            session.target_sharpe,
                            max_dd,
                        )
                        decision = "continue"
                        analysis = (
                            f"{analysis}\n"
                            "[Policy] accept overridden to continue optimization."
                        )
                        iteration.phase_feedback.setdefault("decision", {})[
                            "accept_overridden"
                        ] = True

                iteration.analysis = analysis
                iteration.decision = decision
                ts.analysis_received(
                    analysis, decision, iteration.change_type, dt_analysis,
                )

                session.iterations.append(iteration)
                self._safe_save_session_summary(session)
                self._emit_progress(
                    "iteration_done",
                    iteration=i,
                    decision=decision,
                    status="success" if decision == "accept" else "running",
                    best_sharpe=session.best_sharpe,
                )
                last_iteration = iteration

                logger.info(
                    "builder_iter_%d_done sharpe=%.3f decision=%s",
                    i, sharpe, decision,
                )

                if decision == "accept":
                    accept_now, accept_now_reason = _is_accept_candidate(
                        metrics_cur,
                        target_sharpe=session.target_sharpe,
                    )
                    if accept_now:
                        session.status = "success"
                    else:
                        session.status = "failed"
                        logger.info(
                            "builder_iter_%d_accept_rejected reason=%s",
                            i,
                            accept_now_reason,
                        )
                    break
                if decision == "stop":
                    best_metrics = (
                        session.best_iteration.backtest_result.metrics
                        if session.best_iteration and session.best_iteration.backtest_result
                        else {}
                    )
                    best_ok, best_reason = _is_accept_candidate(
                        best_metrics,
                        target_sharpe=session.target_sharpe,
                    )
                    session.status = "success" if best_ok else "failed"
                    if not best_ok:
                        logger.info(
                            "builder_iter_%d_stop_rejected_success reason=%s "
                            "best_sharpe=%.3f best_score=%.2f",
                            i,
                            best_reason,
                            session.best_sharpe,
                            session.best_score,
                        )
                    break

            except Exception as e:
                iteration.error = f"{type(e).__name__}: {e}"
                ts.error(i, str(e))
                consecutive_failures += 1
                logger.error(
                    "builder_iter_%d_error error=%s\n%s",
                    i, e, _safe_format_exception(e),
                )
                session.iterations.append(iteration)
                self._safe_save_session_summary(session)
                self._emit_progress(
                    "iteration_error",
                    iteration=i,
                    error=iteration.error,
                )
                last_iteration = iteration

        else:
            session.status = "max_iterations"

        ts.session_end(
            session.status, session.best_sharpe, len(session.iterations),
        )

        # Sauvegarder le résumé de session
        self._save_session_summary(session)

        logger.info(
            "strategy_builder_end session=%s status=%s best_sharpe=%.3f iters=%d",
            session.session_id, session.status,
            session.best_sharpe, len(session.iterations),
        )
        self._emit_progress(
            "session_done",
            status=session.status,
            total_iterations=len(session.iterations),
            best_sharpe=session.best_sharpe,
        )

        return session

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_session_summary(self, session: BuilderSession) -> None:
        """Sauvegarde un résumé JSON de la session."""
        iteration_rows: List[Dict[str, Any]] = []
        for it in session.iterations:
            metrics = (
                it.backtest_result.metrics
                if it.backtest_result and isinstance(it.backtest_result.metrics, dict)
                else {}
            )
            score_payload = (
                compute_continuous_builder_score(
                    metrics,
                    target_sharpe=session.target_sharpe,
                )
                if metrics
                else {}
            )
            row = {
                "iteration": it.iteration,
                "hypothesis": it.hypothesis,
                "change_type": it.change_type,
                "diagnostic_category": it.diagnostic_category,
                "error": it.error,
                "decision": it.decision,
                "sharpe": metrics.get("sharpe_ratio") if metrics else None,
                "return_pct": metrics.get("total_return_pct") if metrics else None,
                "max_drawdown_pct": metrics.get("max_drawdown_pct") if metrics else None,
                "profit_factor": metrics.get("profit_factor") if metrics else None,
                "win_rate_pct": metrics.get("win_rate_pct") if metrics else None,
                "trades": metrics.get("total_trades") if metrics else None,
                "continuous_score": score_payload.get("score") if score_payload else None,
                "score_breakdown": {
                    "components": score_payload.get("components", {}) if score_payload else {},
                    "penalties": score_payload.get("penalties", {}) if score_payload else {},
                    "drawdown_excess_pct": score_payload.get("drawdown_excess_pct", 0.0) if score_payload else 0.0,
                }
                if score_payload
                else None,
                "score_card": (
                    it.diagnostic_detail.get("score_card")
                    if it.diagnostic_detail else None
                ),
                "is_fallback": it.is_fallback,
                "phase_feedback": it.phase_feedback or None,
            }
            iteration_rows.append(row)

        leaderboard = sorted(
            [row for row in iteration_rows if row.get("continuous_score") is not None],
            key=lambda row: float(row.get("continuous_score") or -100.0),
            reverse=True,
        )
        for rank, row in enumerate(leaderboard, start=1):
            row["rank"] = rank

        summary = {
            "session_id": session.session_id,
            "objective": session.objective,
            "status": session.status,
            "best_sharpe": session.best_sharpe,
            "best_score": session.best_score,
            "auto_reset_count": session.auto_reset_count,
            "recovery_events": session.recovery_events,
            "total_iterations": len(session.iterations),
            "available_indicators": session.available_indicators,
            "iterations": iteration_rows,
            "leaderboard": leaderboard,
        }

        summary_path = session.session_dir / "session_summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, default=str),
            encoding="utf-8",
        )

        if leaderboard:
            csv_path = session.session_dir / "leaderboard_builder.csv"
            md_path = session.session_dir / "leaderboard_builder.md"
            csv_fields = [
                "rank",
                "iteration",
                "decision",
                "continuous_score",
                "sharpe",
                "return_pct",
                "max_drawdown_pct",
                "profit_factor",
                "win_rate_pct",
                "trades",
                "change_type",
                "diagnostic_category",
                "is_fallback",
                "error",
                "hypothesis",
            ]
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=csv_fields, extrasaction="ignore")
                writer.writeheader()
                for row in leaderboard:
                    writer.writerow(row)

            lines = [
                f"# Leaderboard Builder - session {session.session_id}",
                "",
                f"Objective: {session.objective}",
                f"Status: {session.status}",
                f"Best Sharpe: {session.best_sharpe:.3f}",
                f"Best Continuous Score: {session.best_score:.2f}",
                "",
                "| Rank | Iter | Score | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |",
                "|---|---|---|---|---|---|---|---|---|---|",
            ]
            for row in leaderboard:
                lines.append(
                    "| {rank} | {it} | {score:.2f} | {sharpe:.3f} | {ret:+.2f}% | {dd:.2f}% | {pf:.2f} | {trades} | {decision} | {cat} |".format(
                        rank=int(row.get("rank", 0) or 0),
                        it=int(row.get("iteration", 0) or 0),
                        score=float(row.get("continuous_score", 0.0) or 0.0),
                        sharpe=float(row.get("sharpe", 0.0) or 0.0),
                        ret=float(row.get("return_pct", 0.0) or 0.0),
                        dd=float(row.get("max_drawdown_pct", 0.0) or 0.0),
                        pf=float(row.get("profit_factor", 0.0) or 0.0),
                        trades=int(row.get("trades", 0) or 0),
                        decision=str(row.get("decision", "") or ""),
                        cat=str(row.get("diagnostic_category", "") or ""),
                    )
                )
            md_path.write_text("\n".join(lines), encoding="utf-8")

        # Auto-route into strategy catalog (best-effort, non-blocking).
        try:
            from catalog.strategy_catalog import upsert_from_builder_session
            upsert_from_builder_session(session)
        except Exception as exc:
            logger.warning("builder_catalog_upsert_failed session=%s error=%s", session.session_id, exc)


# ---------------------------------------------------------------------------
# Générateurs d'objectifs pour le mode autonome
# ---------------------------------------------------------------------------

# Groupes d'indicateurs par famille de stratégie (combinaisons cohérentes)
_INDICATOR_FAMILIES: Dict[str, Dict[str, Any]] = {
    "trend-following": {
        "label": "Trend-following",
        "primary": ["ema", "sma", "macd", "supertrend", "adx", "ichimoku", "vortex", "aroon"],
        "entry_templates": [
            "Entrée long quand {ind1} confirme une tendance haussière et {ind2} valide le momentum.",
            "Entrée sur croisement haussier de {ind1} avec filtre de tendance {ind2}.",
            "Position dans le sens de la tendance détectée par {ind1}, confirmée par {ind2}.",
        ],
        "exit_templates": [
            "Sortie sur retournement de {ind1} ou signal contraire de {ind2}.",
            "Sortie quand la tendance s'essouffle (divergence {ind1}/{ind2}).",
        ],
    },
    "mean-reversion": {
        "label": "Mean-reversion",
        "primary": ["bollinger", "rsi", "stochastic", "cci", "williams_r", "stoch_rsi", "keltner", "mfi", "obv"],
        "entry_templates": [
            "Entrée quand le prix touche la bande extrême de {ind1} avec {ind2} en zone de survente/surachat.",
            "Achat en survente ({ind1} < seuil) avec confirmation {ind2}, vente en surachat.",
            "Entrée contrariante quand {ind1} atteint un extrême et {ind2} montre un retournement.",
        ],
        "exit_templates": [
            "Sortie quand le prix revient vers la moyenne ({ind1} neutre).",
            "Take-profit au retour à la bande médiane, stop si {ind2} continue dans la tendance.",
        ],
    },
    "momentum": {
        "label": "Momentum",
        "primary": ["rsi", "macd", "momentum", "roc", "stochastic", "mfi"],
        "entry_templates": [
            "Entrée quand {ind1} dépasse son seuil de momentum avec confirmation {ind2}.",
            "Position quand le momentum ({ind1}) accélère et {ind2} est aligné.",
            "Entrée sur divergence haussière/baissière entre {ind1} et {ind2}.",
        ],
        "exit_templates": [
            "Sortie quand le momentum ({ind1}) s'épuise ou diverge du prix.",
            "Take-profit sur perte de momentum, stop basé sur ATR.",
        ],
    },
    "breakout": {
        "label": "Breakout",
        "primary": ["bollinger", "donchian", "keltner", "atr", "supertrend", "adx", "pivot_points", "psar", "ichimoku"],
        "entry_templates": [
            "Entrée sur cassure de la bande supérieure/inférieure de {ind1} avec volume confirmé.",
            "Position quand le prix sort du range {ind1} avec {ind2} montrant une expansion de volatilité.",
            "Entrée sur breakout validé par {ind1} et force de tendance ({ind2}).",
        ],
        "exit_templates": [
            "Sortie si le prix réintègre le range ou trailing stop basé sur ATR.",
            "Take-profit en multiple d'ATR, stop si faux breakout ({ind1} se contracte).",
        ],
    },
    "scalping": {
        "label": "Scalping",
        "primary": ["ema", "macd", "rsi", "stochastic", "vwap", "bollinger"],
        "entry_templates": [
            "Entrée rapide sur signal {ind1} avec confirmation {ind2} sur timeframe court.",
            "Scalp quand {ind1} croise en zone extrême avec {ind2} aligné.",
            "Entrée quand prix croise {ind1} avec {ind2} en confirmation, objectif serré.",
        ],
        "exit_templates": [
            "Sortie rapide : take-profit serré (1-1.5x ATR), stop-loss serré (0.5-1x ATR).",
            "Sortie sur premier signal de retournement de {ind1}.",
        ],
    },
    "multi-factor": {
        "label": "Multi-factor",
        "primary": ["ema", "rsi", "macd", "bollinger", "adx", "supertrend", "stochastic", "obv"],
        "entry_templates": [
            "Entrée quand au moins 3 facteurs sont alignés : tendance ({ind1}), momentum ({ind2}), volatilité ({ind3}).",
            "Signal composite : {ind1} + {ind2} + {ind3} doivent tous confirmer la direction.",
        ],
        "exit_templates": [
            "Sortie quand plus de la moitié des facteurs se retournent.",
            "Sortie progressive : réduction quand {ind1} diverge, clôture si {ind2} se retourne.",
        ],
    },
    "regime-adaptive": {
        "label": "Regime-adaptatif",
        "primary": ["adx", "atr", "bollinger", "keltner", "supertrend", "rsi", "vwap", "obv", "ema"],
        "entry_templates": [
            "Entrée en mode tendance si {ind1} signale un regime fort, sinon bascule en mode reversion avec {ind2}.",
            "Signal adaptatif : si volatilite elevee ({ind1}), suivre la cassure ; sinon trader le retour a la moyenne via {ind2}.",
            "Déclencher uniquement quand {ind1} et {ind2} confirment le meme regime de marche.",
        ],
        "exit_templates": [
            "Sortie lors d'un changement de regime detecte par {ind1}.",
            "Sortie adaptative : TP agressif en tendance, TP prudent en range.",
        ],
    },
}

# Templates de risk management
_RISK_TEMPLATES = [
    "Stop-loss = {sl_mult}x ATR, take-profit = {tp_mult}x ATR.",
    "Stop-loss dynamique basé sur ATR ({sl_mult}x), ratio risk/reward {rr}:1.",
    "Trailing stop à {sl_mult}x ATR, take-profit à {tp_mult}x ATR.",
    "Stop serré {sl_mult}x ATR pour limiter le drawdown, TP à {tp_mult}x ATR.",
]

# Cache global pour éviter de répéter les mêmes indicateurs et familles
_RECENT_INDICATORS: List[str] = []
_MAX_RECENT_INDICATORS = 8  # Évite de réutiliser les 8 derniers indicateurs principaux
_RECENT_FAMILIES: List[str] = []
_MAX_RECENT_FAMILIES = 3  # Évite de réutiliser les 3 dernières familles


def generate_random_objective(
    symbol: "str | List[str]" = "BTCUSDC",
    timeframe: "str | List[str]" = "1h",
    available_indicators: Optional[List[str]] = None,
) -> str:
    """Génère un objectif de stratégie aléatoire à partir de templates.

    Accepte des listes de symboles/timeframes : un couple est choisi
    aléatoirement pour diversifier les objectifs en mode autonome.

    Combine une famille de stratégie, des indicateurs du registry,
    des conditions d'entrée/sortie et du risk management.

    Returns:
        Objectif structuré en français prêt à être passé au StrategyBuilder.
    """
    global _RECENT_INDICATORS, _RECENT_FAMILIES

    # Normaliser listes → valeur unique (choix aléatoire)
    if isinstance(symbol, list):
        symbol = random.choice(symbol) if symbol else "BTCUSDC"
    if isinstance(timeframe, list):
        timeframe = random.choice(timeframe) if timeframe else "1h"

    if available_indicators is None:
        available_indicators = list_indicators()

    avail_lower = {ind.lower() for ind in available_indicators}

    # 🎯 Choisir une famille en évitant les récentes
    all_families = list(_INDICATOR_FAMILIES.keys())
    fresh_families = [f for f in all_families if f not in _RECENT_FAMILIES]

    # Si toutes les familles ont été utilisées récemment, réinitialiser
    if not fresh_families:
        fresh_families = all_families
        _RECENT_FAMILIES.clear()

    family_key = random.choice(fresh_families)
    family = _INDICATOR_FAMILIES[family_key]

    # Mettre à jour le cache des familles récentes
    _RECENT_FAMILIES.append(family_key)
    if len(_RECENT_FAMILIES) > _MAX_RECENT_FAMILIES:
        _RECENT_FAMILIES.pop(0)

    # Filtrer les indicateurs disponibles dans cette famille
    valid_primary = [ind for ind in family["primary"] if ind.lower() in avail_lower]
    if len(valid_primary) < 2:
        valid_primary = [ind for ind in available_indicators if ind.lower() != "atr"]

    # 🎯 Anti-répétition : retirer les indicateurs récemment utilisés
    recent_lower = {ind.lower() for ind in _RECENT_INDICATORS}
    fresh_indicators = [ind for ind in valid_primary if ind.lower() not in recent_lower]

    # Si tous les indicateurs ont été utilisés récemment, on réinitialise
    if len(fresh_indicators) < 2:
        fresh_indicators = valid_primary
        _RECENT_INDICATORS.clear()

    # Sélectionner 2-3 indicateurs parmi les frais
    n_indicators = random.randint(2, min(3, len(fresh_indicators)))
    selected = random.sample(fresh_indicators, n_indicators)

    # 🎯 Mettre à jour le cache des indicateurs récents
    for ind in selected:
        if ind.lower() != "atr":  # ATR n'est pas compté car toujours présent
            _RECENT_INDICATORS.append(ind)
            if len(_RECENT_INDICATORS) > _MAX_RECENT_INDICATORS:
                _RECENT_INDICATORS.pop(0)  # FIFO
    if "atr" not in [s.lower() for s in selected] and "atr" in avail_lower:
        selected.append("atr")

    # Générer l'entrée
    ind1 = selected[0].upper()
    ind2 = selected[1].upper() if len(selected) > 1 else selected[0].upper()
    ind3 = selected[2].upper() if len(selected) > 2 else ind1

    entry = random.choice(family["entry_templates"]).format(
        ind1=ind1, ind2=ind2, ind3=ind3,
    )
    exit_rule = random.choice(family["exit_templates"]).format(
        ind1=ind1, ind2=ind2, ind3=ind3,
    )

    # Risk management
    sl_mult = round(random.uniform(1.0, 2.5), 1)
    tp_mult = round(sl_mult * random.uniform(1.5, 3.0), 1)
    rr = round(tp_mult / sl_mult, 1)
    risk = random.choice(_RISK_TEMPLATES).format(
        sl_mult=sl_mult, tp_mult=tp_mult, rr=rr,
    )
    indicators_str = " + ".join(ind.upper() for ind in selected)

    objective = (
        f"Stratégie de {family['label']} sur {symbol} {timeframe}. "
        f"Indicateurs : {indicators_str}. "
        f"{entry} "
        f"{exit_rule} "
        f"{risk}"
    )

    return objective


def _build_positive_objective_bias_instruction(max_items: int = 3) -> str:
    """Construit une instruction de prompt à partir des objectifs historiquement positifs."""
    try:
        tracker = _get_exploration_tracker()
        summary = tracker.get_positive_bias_summary(limit=max_items)
    except Exception:
        return ""

    positive_count = int(summary.get("positive_count", 0) or 0)
    if positive_count <= 0:
        return ""

    def _extract_names(items: List[Dict[str, Any]]) -> List[str]:
        names: List[str] = []
        for item in items[:max(1, max_items)]:
            name = str(item.get("name", "")).strip()
            if name:
                names.append(name)
        return names

    family_names = _extract_names(cast(List[Dict[str, Any]], summary.get("top_families", [])))
    indicator_patterns = _extract_names(cast(List[Dict[str, Any]], summary.get("top_indicator_patterns", [])))
    novelty_names = _extract_names(cast(List[Dict[str, Any]], summary.get("top_novelty_angles", [])))

    lines = ["Ancrages performants issus des sessions precedentes:"]
    if family_names:
        lines.append(f"- Familles robustes detectees: {', '.join(family_names)}.")
    if indicator_patterns:
        lines.append(
            "- Combinaisons indicateurs deja positives: "
            f"{', '.join(indicator_patterns)}."
        )
    if novelty_names:
        lines.append(f"- Angles de nouveaute deja prometteurs: {', '.join(novelty_names)}.")
    lines.append(
        "- Reutilise au moins un ancrage positif, mais MUTER au moins deux dimensions "
        "(direction, filtre, risk management, ou contexte marche) pour eviter la copie."
    )
    return "\n".join(lines) + "\n\n"


def _sanitize_objective_indicators_section(
    objective: str,
    available_indicators: List[str],
) -> str:
    """Nettoie le bloc `Indicateurs:` pour ne garder que des noms calculables."""
    text = str(objective or "")
    if not text:
        return text

    allowed = [
        str(ind or "").strip().lower()
        for ind in (available_indicators or [])
        if str(ind or "").strip()
    ]
    if not allowed:
        return text
    allowed_set = set(allowed)

    alias_map = {
        "fibonacci_levels": "fibonacci",
        "fibonacci_level": "fibonacci",
        "williamsr": "williams_r",
        "williams": "williams_r",
        "stochrsi": "stoch_rsi",
    }
    preferred_fallback = [
        name
        for name in ("ema", "rsi", "bollinger", "macd", "stochastic", "adx", "atr")
        if name in allowed_set
    ]

    match = re.search(
        r"(Indicateurs?\s*:\s*)(.+?)(\.\s|\n|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return text

    prefix = str(match.group(1) or "")
    raw_block = str(match.group(2) or "")
    suffix = str(match.group(3) or "")

    extracted = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw_block)
    selected: List[str] = []
    for token in extracted:
        normalized = alias_map.get(token.lower(), token.lower())
        if normalized in allowed_set and normalized not in selected:
            selected.append(normalized)

    if "atr" in allowed_set and "atr" not in selected:
        selected.append("atr")

    if len(selected) < 2:
        for candidate in preferred_fallback:
            if candidate not in selected:
                selected.append(candidate)
            if len(selected) >= 3:
                break

    if not selected:
        return text

    rebuilt = f"{prefix}{' + '.join(ind.upper() for ind in selected[:4])}{suffix}"
    start, end = match.span()
    return f"{text[:start]}{rebuilt}{text[end:]}"


def generate_llm_objective(
    llm_client: Any,
    symbol: "str | List[str]" = "BTCUSDC",
    timeframe: "str | List[str]" = "1h",
    available_indicators: Optional[List[str]] = None,
    stream_callback: Optional[Callable[[str, str], None]] = None,
    recent_markets: Optional[List[Tuple[str, str]]] = None,
) -> str:
    """Génère un objectif de stratégie via un appel LLM.

    Accepte des listes de symboles/timeframes : le LLM est invité à
    choisir le couple le plus pertinent pour sa stratégie.

    Returns:
        Objectif en texte libre généré par le LLM.
    """
    if available_indicators is None:
        available_indicators = list_indicators()

    indicators_list = ", ".join(sorted(available_indicators))

    # Normaliser en listes pour construire le prompt multi-marché.
    # IMPORTANT : si None est passé, ne pas fallback sur BTCUSDC/1h.
    market_auto_selection = (symbol is None or timeframe is None)

    if market_auto_selection:
        # Mode auto : le marché sera choisi plus tard via recommend_market_context.
        # L'objectif doit rester neutre et utiliser les placeholders.
        market_instruction = (
            "Le marché (token + timeframe) est sélectionné automatiquement par une étape dédiée.\n"
            "Tu DOIS utiliser exactement les placeholders `{symbol}` et `{timeframe}` dans l'objectif.\n"
            "N'écris AUCUN token réel (BTCUSDC, ETHUSDC...) ni timeframe réel (1h, 15m...).\n\n"
        )
        symbols_list = []
        timeframes_list = []
    else:
        # Mode manuel ou multi-marché : comportement normal
        symbols_list = symbol if isinstance(symbol, list) else [symbol]
        timeframes_list = timeframe if isinstance(timeframe, list) else [timeframe]
        symbols_list = [s for s in symbols_list if s] or ["BTCUSDC"]
        timeframes_list = [t for t in timeframes_list if t] or ["1h"]

        # Construire l'instruction marché selon l'univers disponible
        if len(symbols_list) > 1 or len(timeframes_list) > 1:
            # Mélanger pour réduire le biais de position (BTC toujours 1er)
            shuffled_symbols = symbols_list.copy()
            random.shuffle(shuffled_symbols)
            shuffled_timeframes = timeframes_list.copy()
            random.shuffle(shuffled_timeframes)

            market_instruction = (
                f"Symboles disponibles (SEULS autorisés) : {', '.join(shuffled_symbols)}\n"
                f"Timeframes disponibles (SEULS autorisés) : {', '.join(shuffled_timeframes)}\n"
                "CHOISIS le symbole et le timeframe les plus adaptés à ta stratégie. "
                "Tu ne DOIS utiliser QUE des symboles et timeframes de ces listes. "
                "N'invente AUCUN timeframe (pas de 3m, 5m, 2h, etc. s'ils ne sont pas listés). "
                "Ne te limite pas à BTC — explore les altcoins si ta stratégie s'y prête mieux.\n\n"
            )
            # Injecter l'historique récent pour forcer la diversité
            if recent_markets:
                recent_str = ", ".join(f"{s} {tf}" for s, tf in recent_markets[-6:])
                market_instruction += (
                    f"IMPORTANT — Les marchés suivants ont DÉJÀ été utilisés récemment : {recent_str}. "
                    "Tu DOIS choisir un couple symbol/timeframe DIFFÉRENT de ceux-ci. "
                    "Varie les tokens ET les timeframes.\n\n"
                )
        else:
            market_instruction = f"Marché : {symbols_list[0]} en {timeframes_list[0]}.\n\n"

    system_msg = LLMMessage(
        role="system",
        content=(
            "Tu es un quant designer spécialisé en stratégies de trading crypto. "
            "Génère UN objectif de stratégie original et précis. "
            "Réponds UNIQUEMENT avec l'objectif, sans explication ni formatage markdown."
        ),
    )
    novelty_axes = [
        "asymetrie long/short (seuils differents)",
        "adaptation de regime (trend vs range)",
        "filtre anti-faux-signaux (confirmation inverse partielle)",
        "filtre horaire de liquidite",
        "gestion du risque non lineaire (SL/TP adaptes a la volatilite)",
        "gating par volatilite implicite/realisee",
        "combinaison de signaux contradictoires avec vote majoritaire",
    ]
    random.shuffle(novelty_axes)
    selected_axes = novelty_axes[:4]

    random_behaviors = [
        "mode_offbeat: prioriser des paires d'indicateurs rarement combinees",
        "mode_inverse: tester une logique inversee puis filtrer par regime",
        "mode_microstructure: ajouter un filtre de session/horaire et liquidite",
        "mode_risk_rotation: alterner profile risque serre/large selon volatilite",
        "mode_counter_consensus: exiger une confirmation contrarienne partielle",
    ]
    random.shuffle(random_behaviors)
    selected_behaviors = random_behaviors[:2]
    positive_bias_instruction = _build_positive_objective_bias_instruction(max_items=3)

    format_hint = (
        "Format attendu :\n"
        "[Style] sur {symbol} {timeframe}. "
        "Indicateurs : [ind1] + [ind2] + [ind3]. "
        "Entrées : [conditions]. "
        "Sorties : [conditions]. "
        "Risk management : [SL/TP]."
        if market_auto_selection
        else
        "Format attendu :\n"
        "[Style] sur [marché] [timeframe]. "
        "Indicateurs : [ind1] + [ind2] + [ind3]. "
        "Entrées : [conditions]. "
        "Sorties : [conditions]. "
        "Risk management : [SL/TP]."
    )

    user_msg = LLMMessage(
        role="user",
        content=(
            f"Génère un objectif de stratégie de trading.\n\n"
            f"{market_instruction}"
            f"Indicateurs disponibles : {indicators_list}\n\n"
            f"{positive_bias_instruction}"
            "Contraintes de diversification:\n"
            f"- Intègre au moins un axe 'hors sentiers battus' parmi: {', '.join(selected_axes)}.\n"
            f"- Comportements aleatoires imposes pour cette generation: {', '.join(selected_behaviors)}.\n"
            "- Evite les formulations generiques de type 'RSI<30/RSI>70' sans filtre additionnel.\n"
            "- Propose une hypothese testable et falsifiable.\n\n"
            f"{format_hint}\n\n"
            "Sois créatif : explore des combinaisons inhabituelles, "
            "des filtres originaux, des approches multi-timeframe conceptuelles. "
            "L'objectif doit faire 2-4 phrases."
        ),
    )

    if stream_callback and hasattr(llm_client, "chat_stream"):
        result = llm_client.chat_stream(
            [system_msg, user_msg],
            on_chunk=lambda c: stream_callback("objective_gen", c),
            max_tokens=300,
        )
    else:
        result = llm_client.chat([system_msg, user_msg], max_tokens=300)

    # Extraire .content si LLMResponse, sinon str()
    objective = str(getattr(result, "content", result) or "").strip()
    # Nettoyer les tags <think> si présents
    objective = re.sub(r"<think>.*?</think>", "", objective, flags=re.DOTALL).strip()
    objective = re.sub(r"<think>.*", "", objective, flags=re.DOTALL).strip()
    objective = sanitize_objective_text(objective)

    # Fallback si le LLM retourne du vide
    if not objective or len(objective) < 20:
        logger.warning("generate_llm_objective: résultat LLM vide, fallback template")
        if market_auto_selection:
            return generate_random_objective(
                symbol="{symbol}",
                timeframe="{timeframe}",
                available_indicators=available_indicators,
            )
        return generate_random_objective(symbol, timeframe, available_indicators)

    if market_auto_selection:
        # Nettoyage défensif : retire toute fuite de token/TF hardcodé.
        objective = _remove_hardcoded_tokens(objective)
        objective = _remove_hardcoded_timeframes(objective)

        # Garantit la présence des placeholders attendus.
        if "{symbol}" not in objective or "{timeframe}" not in objective:
            objective = re.sub(
                r"\bsur\s+crypto\b",
                "sur {symbol} {timeframe}",
                objective,
                flags=re.IGNORECASE,
            )
        if "{symbol}" not in objective or "{timeframe}" not in objective:
            objective = f"Stratégie sur {{symbol}} {{timeframe}}. {objective}"

        objective = _sanitize_objective_indicators_section(
            objective,
            available_indicators,
        )
        return sanitize_objective_text(objective)

    # ── Post-validation : remplacer les TF/tokens hallucinés ──
    tf_pattern = re.compile(r"\b(\d{1,2}[mhdwM])\b")
    found_tfs = tf_pattern.findall(objective)
    if timeframes_list:
        for found_tf in found_tfs:
            if found_tf not in timeframes_list:
                replacement = random.choice(timeframes_list)
                objective = objective.replace(found_tf, replacement, 1)
                logger.info(
                    "generate_llm_objective: TF halluciné '%s' → '%s'",
                    found_tf, replacement,
                )

    sym_upper_set = {s.upper() for s in symbols_list}
    # Vérifier que le symbole mentionné est valide
    sym_pattern = re.compile(r"\b([A-Z]{2,10}USDC)\b")
    found_syms = sym_pattern.findall(objective.upper())
    if symbols_list:
        for found_sym in found_syms:
            if found_sym not in sym_upper_set:
                replacement = random.choice(symbols_list)
                objective = re.sub(
                    re.escape(found_sym), replacement, objective,
                    count=1, flags=re.IGNORECASE,
                )
                logger.info(
                    "generate_llm_objective: token halluciné '%s' → '%s'",
                    found_sym, replacement,
                )

    objective = _sanitize_objective_indicators_section(
        objective,
        available_indicators,
    )
    return objective


def generate_llm_objective_from_seed(
    llm_client: Any,
    *,
    seed_objective: str,
    symbol: "str | List[str]" = "BTCUSDC",
    timeframe: "str | List[str]" = "1h",
    available_indicators: Optional[List[str]] = None,
    family: str = "",
    direction: str = "",
    risk_profile: str = "",
    novelty_angle: str = "",
    tags: Optional[List[str]] = None,
    stream_callback: Optional[Callable[[str, str], None]] = None,
    recent_markets: Optional[List[Tuple[str, str]]] = None,
) -> str:
    """Raffine une piste catalogue en objectif LLM plus adapté au setup étudié."""
    if available_indicators is None:
        available_indicators = list_indicators()

    seed_text = sanitize_objective_text(seed_objective)
    if not seed_text:
        return generate_llm_objective(
            llm_client,
            symbol=symbol,
            timeframe=timeframe,
            available_indicators=available_indicators,
            stream_callback=stream_callback,
            recent_markets=recent_markets,
        )

    indicators_list = ", ".join(sorted(available_indicators))
    market_auto_selection = (symbol is None or timeframe is None)

    if market_auto_selection:
        market_instruction = (
            "Le marché (token + timeframe) est sélectionné automatiquement par une étape dédiée.\n"
            "Tu DOIS utiliser exactement les placeholders `{symbol}` et `{timeframe}` dans l'objectif final.\n"
            "N'écris AUCUN token réel ni timeframe réel.\n\n"
        )
        symbols_list: List[str] = []
        timeframes_list: List[str] = []
    else:
        symbols_list = symbol if isinstance(symbol, list) else [symbol]
        timeframes_list = timeframe if isinstance(timeframe, list) else [timeframe]
        symbols_list = [s for s in symbols_list if s] or ["BTCUSDC"]
        timeframes_list = [t for t in timeframes_list if t] or ["1h"]
        if len(symbols_list) > 1 or len(timeframes_list) > 1:
            shuffled_symbols = symbols_list.copy()
            random.shuffle(shuffled_symbols)
            shuffled_timeframes = timeframes_list.copy()
            random.shuffle(shuffled_timeframes)
            market_instruction = (
                f"Symboles disponibles (SEULS autorisés) : {', '.join(shuffled_symbols)}\n"
                f"Timeframes disponibles (SEULS autorisés) : {', '.join(shuffled_timeframes)}\n"
                "Choisis le couple le plus pertinent pour étudier cette stratégie. "
                "N'utilise QUE ces symboles/timeframes.\n\n"
            )
            if recent_markets:
                recent_str = ", ".join(f"{s} {tf}" for s, tf in recent_markets[-6:])
                market_instruction += (
                    f"Les marchés suivants ont déjà été testés récemment : {recent_str}. "
                    "Privilégie un couple différent si cela reste cohérent.\n\n"
                )
        else:
            market_instruction = f"Marché à étudier : {symbols_list[0]} {timeframes_list[0]}.\n\n"

    seed_context = [
        f"Piste catalogue de départ : {seed_text}",
        f"Famille cible : {family or 'n/a'}",
        f"Direction visée : {direction or 'n/a'}",
        f"Profil de risque : {risk_profile or 'n/a'}",
        f"Angle de nouveauté : {novelty_angle or 'n/a'}",
    ]
    clean_tags = [str(tag or "").strip() for tag in (tags or []) if str(tag or "").strip()]
    if clean_tags:
        seed_context.append(f"Tags utiles : {', '.join(clean_tags)}")

    format_hint = (
        "Format attendu :\n"
        "[Style] sur {symbol} {timeframe}. "
        "Indicateurs : [ind1] + [ind2] + [ind3]. "
        "Entrées : [conditions]. "
        "Sorties : [conditions]. "
        "Risk management : [SL/TP]."
        if market_auto_selection
        else
        "Format attendu :\n"
        "[Style] sur [marché] [timeframe]. "
        "Indicateurs : [ind1] + [ind2] + [ind3]. "
        "Entrées : [conditions]. "
        "Sorties : [conditions]. "
        "Risk management : [SL/TP]."
    )

    system_msg = LLMMessage(
        role="system",
        content=(
            "Tu es un quant designer. On te donne une piste issue d'un catalogue brut. "
            "Ta tâche est de la transformer en UN objectif de recherche plus précis, plus robuste, "
            "et mieux adapté à la stratégie réellement étudiée. "
            "Tu peux reformuler, renforcer les filtres, ajuster la logique d'entrée/sortie et le risk management, "
            "mais tu dois conserver l'intention stratégique générale. "
            "Réponds UNIQUEMENT avec l'objectif final, sans markdown ni commentaire."
        ),
    )
    user_msg = LLMMessage(
        role="user",
        content=(
            f"{market_instruction}"
            f"{chr(10).join(seed_context)}\n\n"
            f"Indicateurs disponibles : {indicators_list}\n\n"
            "Contraintes :\n"
            "- Pars de la piste catalogue, mais reformule-la pour en faire une hypothèse testable et falsifiable.\n"
            "- Choisis les indicateurs les plus cohérents avec cette stratégie.\n"
            "- N'utilise QUE des indicateurs disponibles.\n"
            "- Evite les formulations génériques et les signaux trop triviaux.\n"
            "- L'objectif doit rester en 2-4 phrases.\n\n"
            f"{format_hint}"
        ),
    )

    if stream_callback and hasattr(llm_client, "chat_stream"):
        result = llm_client.chat_stream(
            [system_msg, user_msg],
            on_chunk=lambda c: stream_callback("objective_gen", c),
            max_tokens=320,
        )
    else:
        result = llm_client.chat([system_msg, user_msg], max_tokens=320)

    objective = str(getattr(result, "content", result) or "").strip()
    objective = re.sub(r"<think>.*?</think>", "", objective, flags=re.DOTALL).strip()
    objective = re.sub(r"<think>.*", "", objective, flags=re.DOTALL).strip()
    objective = sanitize_objective_text(objective)
    if not objective or len(objective) < 20:
        logger.warning("generate_llm_objective_from_seed: résultat LLM vide, fallback seed")
        objective = seed_text

    if market_auto_selection:
        objective = _remove_hardcoded_tokens(objective)
        objective = _remove_hardcoded_timeframes(objective)
        if "{symbol}" not in objective or "{timeframe}" not in objective:
            objective = f"Stratégie sur {{symbol}} {{timeframe}}. {objective}"
        objective = _sanitize_objective_indicators_section(
            objective,
            available_indicators,
        )
        return sanitize_objective_text(objective)

    tf_pattern = re.compile(r"\b(\d{1,2}[mhdwM])\b")
    found_tfs = tf_pattern.findall(objective)
    for found_tf in found_tfs:
        if found_tf not in timeframes_list:
            replacement = random.choice(timeframes_list)
            objective = objective.replace(found_tf, replacement, 1)

    sym_upper_set = {s.upper() for s in symbols_list}
    sym_pattern = re.compile(r"\b([A-Z]{2,10}USDC)\b")
    found_syms = sym_pattern.findall(objective.upper())
    for found_sym in found_syms:
        if found_sym not in sym_upper_set:
            replacement = random.choice(symbols_list)
            objective = re.sub(
                re.escape(found_sym), replacement, objective,
                count=1, flags=re.IGNORECASE,
            )

    objective = _sanitize_objective_indicators_section(
        objective,
        available_indicators,
    )
    return objective


# ---------------------------------------------------------------------------
# Catalogue d'objectifs pré-construits pour exploration systématique
# ---------------------------------------------------------------------------

@dataclass
class CatalogObjective:
    """Un objectif pré-construit du catalogue d'exploration."""

    id: str
    family: str
    indicators: List[str]
    direction: str          # "long_only", "short_only", "long_short"
    risk_profile: str       # "tight", "balanced", "wide"
    novelty_angle: str      # "classic", "regime_adaptive", "asymmetric", ...
    description: str        # Objectif formaté ({symbol} et {timeframe} en placeholders)
    sl_mult: float
    tp_mult: float
    tags: List[str] = field(default_factory=list)


_OBJECTIVE_COMPLEXITY_TAG_WEIGHTS: Dict[str, float] = {
    "stat_arb": 1.4,
    "zscore": 1.2,
    "multi_tf_proxy": 1.1,
    "double_rsi": 1.0,
    "volatility": 0.9,
    "volume_surge": 0.9,
    "momentum_filter": 0.85,
    "support_resistance": 0.75,
    "adx_filter": 0.7,
    "trend_filter": 0.55,
    "retrace": 0.45,
    "pullback": 0.45,
    "confirmation": 0.35,
    "cross": 0.2,
}


def _objective_complexity_score(obj: CatalogObjective) -> float:
    """Score simple de complexité exploitable pour piloter l'exploration."""
    indicators = [str(ind).strip().lower() for ind in obj.indicators if str(ind).strip()]
    core_indicators = {ind for ind in indicators if ind != "atr"}
    score = 0.95 * float(len(core_indicators))
    if "atr" in indicators:
        score += 0.15

    direction_bonus = {
        "long_short": 0.7,
        "long_only": 0.15,
        "short_only": 0.15,
    }
    score += direction_bonus.get(obj.direction, 0.2)
    score += {
        "tight": 0.0,
        "balanced": 0.15,
        "wide": 0.25,
        "neutral": 0.1,
    }.get(obj.risk_profile, 0.1)

    for tag in {str(tag).strip().lower() for tag in obj.tags if str(tag).strip()}:
        score += _OBJECTIVE_COMPLEXITY_TAG_WEIGHTS.get(tag, 0.0)

    return round(score, 4)


_CURATED_RISK_SL_TP = {
    "tight": (1.0, 2.0),
    "balanced": (1.5, 3.0),
    "wide": (2.0, 5.0),
    "neutral": (1.5, 3.0),
}

def _co(
    obj_id: str,
    family: str,
    indicators: List[str],
    direction: str,
    risk_profile: str,
    description: str,
    tags: Optional[List[str]] = None,
) -> CatalogObjective:
    """Raccourci pour construire un CatalogObjective curé."""
    sl, tp = _CURATED_RISK_SL_TP.get(risk_profile, (1.5, 3.0))
    if "atr" not in [i.lower() for i in indicators]:
        indicators = list(indicators) + ["atr"]
    return CatalogObjective(
        id=obj_id,
        family=family,
        indicators=indicators,
        direction=direction,
        risk_profile=risk_profile,
        novelty_angle="curated",
        description=description,
        sl_mult=sl,
        tp_mult=tp,
        tags=tags or [],
    )


# ---------------------------------------------------------------------------
# Catalogue curé — 50 fiches d'objectifs réalistes
# ---------------------------------------------------------------------------

_CURATED_CATALOG_RAW: List[Dict[str, Any]] = [
    # ── Momentum / Trend-following ──
    {
        "id": "momentum_ema_cross_sma_long_tight",
        "family": "momentum", "indicators": ["ema", "sma"],
        "direction": "long_only", "risk": "tight",
        "tags": ["momentum", "trend_following", "cross"],
        "desc": (
            "Strategie de Momentum / Trend-following sur {symbol} {timeframe}. "
            "Indicateurs : EMA(20), SMA(50), ATR. "
            "Entree long lorsque EMA(20) croise au-dessus de SMA(50), "
            "sortie sur retournement ou stop serre. "
            "Stop-loss = 1.0x ATR, take-profit = 2.0x ATR."
        ),
    },
    {
        "id": "momentum_ema_cross_sma_short_tight",
        "family": "momentum", "indicators": ["ema", "sma"],
        "direction": "short_only", "risk": "tight",
        "tags": ["momentum", "trend_following", "cross"],
        "desc": (
            "Strategie de Momentum / Trend-following sur {symbol} {timeframe}. "
            "Indicateurs : EMA(20), SMA(50), ATR. "
            "Entree short lorsque EMA(20) croise en dessous de SMA(50), "
            "sortie sur retournement. "
            "Stop-loss = 1.0x ATR, take-profit = 2.0x ATR."
        ),
    },
    {
        "id": "momentum_macd_signal_long_balanced",
        "family": "momentum", "indicators": ["macd"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["momentum", "trend_following", "macd"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : MACD (macd, signal, histogram), ATR. "
            "Entree long quand MACD au-dessus de sa ligne de signal "
            "et momentum positif durable. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "momentum_macd_signal_short_balanced",
        "family": "momentum", "indicators": ["macd"],
        "direction": "short_only", "risk": "balanced",
        "tags": ["momentum", "trend_following", "macd"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : MACD (macd, signal, histogram), ATR. "
            "Entree short quand MACD en dessous de sa ligne de signal "
            "et momentum negatif. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "momentum_rsi_filtered_long_balanced",
        "family": "momentum", "indicators": ["rsi", "ema"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["momentum", "rsi", "trend_filter"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : RSI(14), EMA(20), ATR. "
            "Entree long quand RSI > 50 et EMA(20) haussiere. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "momentum_rsi_filtered_short_balanced",
        "family": "momentum", "indicators": ["rsi", "ema"],
        "direction": "short_only", "risk": "balanced",
        "tags": ["momentum", "rsi", "trend_filter"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : RSI(14), EMA(20), ATR. "
            "Entree short quand RSI < 50 et EMA(20) baissiere. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "momentum_double_ema_trend_long_wide",
        "family": "momentum", "indicators": ["ema", "adx"],
        "direction": "long_only", "risk": "wide",
        "tags": ["momentum", "trend_following", "adx_filter"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : EMA(10), EMA(30), ADX, ATR. "
            "Entree long quand EMA(10) > EMA(30) avec filtre ADX >= 25. "
            "Stop-loss = 2.0x ATR, take-profit = 5.0x ATR."
        ),
    },
    {
        "id": "momentum_double_ema_trend_short_wide",
        "family": "momentum", "indicators": ["ema", "adx"],
        "direction": "short_only", "risk": "wide",
        "tags": ["momentum", "trend_following", "adx_filter"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : EMA(10), EMA(30), ADX, ATR. "
            "Entree short quand EMA(10) < EMA(30), ADX >= 25 confirme la tendance. "
            "Stop-loss = 2.0x ATR, take-profit = 5.0x ATR."
        ),
    },
    {
        "id": "momentum_volume_confirmed_long_balanced",
        "family": "momentum", "indicators": ["ema", "obv"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["momentum", "volume", "trend_following"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : EMA(20), OBV, ATR. "
            "Entree long sur hausse de volume (OBV croissant) + EMA haussiere. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "momentum_volume_confirmed_short_balanced",
        "family": "momentum", "indicators": ["ema", "obv"],
        "direction": "short_only", "risk": "balanced",
        "tags": ["momentum", "volume", "trend_following"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : EMA(20), OBV, ATR. "
            "Entree short sur volume croissant + tendance baissiere (EMA). "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    # ── Mean-reversion ──
    {
        "id": "meanrev_bb_rsi_long_tight",
        "family": "mean-reversion", "indicators": ["bollinger", "rsi"],
        "direction": "long_only", "risk": "tight",
        "tags": ["mean_reversion", "bollinger", "rsi", "oversold"],
        "desc": (
            "Strategie de Mean-reversion sur {symbol} {timeframe}. "
            "Indicateurs : Bollinger Bands(20,2), RSI(14), ATR. "
            "Entree long quand prix sous bande inferieure et RSI < 30. "
            "Stop-loss = 1.0x ATR, take-profit = 2.0x ATR."
        ),
    },
    {
        "id": "meanrev_bb_rsi_short_tight",
        "family": "mean-reversion", "indicators": ["bollinger", "rsi"],
        "direction": "short_only", "risk": "tight",
        "tags": ["mean_reversion", "bollinger", "rsi", "overbought"],
        "desc": (
            "Strategie de Mean-reversion sur {symbol} {timeframe}. "
            "Indicateurs : Bollinger Bands(20,2), RSI(14), ATR. "
            "Entree short quand prix dessus bande superieure et RSI > 70. "
            "Stop-loss = 1.0x ATR, take-profit = 2.0x ATR."
        ),
    },
    {
        "id": "meanrev_keltner_rsi_long_balanced",
        "family": "mean-reversion", "indicators": ["keltner", "rsi"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["mean_reversion", "keltner", "rsi"],
        "desc": (
            "Strategie de Mean-reversion sur {symbol} {timeframe}. "
            "Indicateurs : Keltner Channels, RSI(14), ATR. "
            "Entree long quand prix touche bande inferieure Keltner et RSI bas. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "meanrev_keltner_rsi_short_balanced",
        "family": "mean-reversion", "indicators": ["keltner", "rsi"],
        "direction": "short_only", "risk": "balanced",
        "tags": ["mean_reversion", "keltner", "rsi"],
        "desc": (
            "Strategie de Mean-reversion sur {symbol} {timeframe}. "
            "Indicateurs : Keltner Channels, RSI(14), ATR. "
            "Entree short quand prix touche bande superieure Keltner et RSI haut. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "meanrev_zscore_pair_spread_neutral",
        "family": "mean-reversion", "indicators": ["bollinger", "rsi"],
        "direction": "long_short", "risk": "balanced",
        "tags": ["mean_reversion", "stat_arb", "zscore"],
        "desc": (
            "Strategie de Mean-reversion / StatArb sur {symbol} {timeframe}. "
            "Indicateurs : Bollinger Bands (pour z-score), RSI(14), ATR. "
            "Entree long quand z-score (close - BB middle) / BB std < -2, "
            "entree short quand z-score > +2. Sortie retour a la moyenne. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "meanrev_rsi_oscillator_long_balanced",
        "family": "mean-reversion", "indicators": ["rsi"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["mean_reversion", "rsi", "double_rsi"],
        "desc": (
            "Strategie de Mean-reversion sur {symbol} {timeframe}. "
            "Indicateurs : RSI(14), ATR. "
            "Utiliser RSI court terme (params rsi_period=3) extreme bas (< 10) "
            "comme signal d'entree long, attente retour moyenne. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "meanrev_rsi_oscillator_short_balanced",
        "family": "mean-reversion", "indicators": ["rsi"],
        "direction": "short_only", "risk": "balanced",
        "tags": ["mean_reversion", "rsi", "double_rsi"],
        "desc": (
            "Strategie de Mean-reversion sur {symbol} {timeframe}. "
            "Indicateurs : RSI(14), ATR. "
            "Utiliser RSI court terme (params rsi_period=3) extreme haut (> 90) "
            "comme signal d'entree short, repli anticipe. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    # ── Breakout ──
    {
        "id": "breakout_pivot_point_long_balanced",
        "family": "breakout", "indicators": ["pivot_points", "obv"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["breakout", "pivot", "volume"],
        "desc": (
            "Strategie de Breakout sur {symbol} {timeframe}. "
            "Indicateurs : Pivot Points, OBV, ATR. "
            "Entree long sur cassure du pivot R1 avec hausse de volume (OBV). "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "breakout_pivot_point_short_balanced",
        "family": "breakout", "indicators": ["pivot_points", "obv"],
        "direction": "short_only", "risk": "balanced",
        "tags": ["breakout", "pivot", "volume"],
        "desc": (
            "Strategie de Breakout sur {symbol} {timeframe}. "
            "Indicateurs : Pivot Points, OBV, ATR. "
            "Entree short sur cassure du support S1 avec volume croissant. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "breakout_atr_volatility_long_wide",
        "family": "breakout", "indicators": ["ema"],
        "direction": "long_only", "risk": "wide",
        "tags": ["breakout", "volatility", "atr_expansion"],
        "desc": (
            "Strategie de Breakout / Volatility sur {symbol} {timeframe}. "
            "Indicateurs : ATR, EMA(20). "
            "Entree long quand ATR depasse 1.5x sa moyenne (expansion de volatilite) "
            "et prix au-dessus de EMA(20). Continuation haussiere attendue. "
            "Stop-loss = 2.0x ATR, take-profit = 5.0x ATR."
        ),
    },
    {
        "id": "breakout_atr_volatility_short_wide",
        "family": "breakout", "indicators": ["ema"],
        "direction": "short_only", "risk": "wide",
        "tags": ["breakout", "volatility", "atr_expansion"],
        "desc": (
            "Strategie de Breakout / Volatility sur {symbol} {timeframe}. "
            "Indicateurs : ATR, EMA(20). "
            "Entree short quand ATR en expansion + prix sous EMA(20). "
            "Tendance baissiere amplifiee par la volatilite. "
            "Stop-loss = 2.0x ATR, take-profit = 5.0x ATR."
        ),
    },
    {
        "id": "breakout_adx_threshold_long_balanced",
        "family": "breakout", "indicators": ["adx", "ema"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["breakout", "adx", "trend_strength"],
        "desc": (
            "Strategie de Breakout sur {symbol} {timeframe}. "
            "Indicateurs : ADX, EMA(20), ATR. "
            "Entree long quand ADX > 30 (tendance forte) et prix casse "
            "au-dessus de EMA(20). "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "breakout_adx_threshold_short_balanced",
        "family": "breakout", "indicators": ["adx", "ema"],
        "direction": "short_only", "risk": "balanced",
        "tags": ["breakout", "adx", "trend_strength"],
        "desc": (
            "Strategie de Breakout sur {symbol} {timeframe}. "
            "Indicateurs : ADX, EMA(20), ATR. "
            "Entree short quand ADX > 30 et prix casse sous EMA(20). "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    # ── Momentum (suite) ──
    {
        "id": "momentum_macd_histogram_long_balanced",
        "family": "momentum", "indicators": ["macd"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["momentum", "macd", "histogram"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : MACD (histogram), ATR. "
            "Entree long quand MACD histogram croissant et positif (signal fort). "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "momentum_macd_histogram_short_balanced",
        "family": "momentum", "indicators": ["macd"],
        "direction": "short_only", "risk": "balanced",
        "tags": ["momentum", "macd", "histogram"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : MACD (histogram), ATR. "
            "Entree short quand MACD histogram decroissant et negatif. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    # ── Mean-reversion (suite) ──
    {
        "id": "meanrev_stddev_extreme_long_tight",
        "family": "mean-reversion", "indicators": ["bollinger"],
        "direction": "long_only", "risk": "tight",
        "tags": ["mean_reversion", "stddev", "extreme"],
        "desc": (
            "Strategie de Mean-reversion sur {symbol} {timeframe}. "
            "Indicateurs : Bollinger Bands (ecart type), ATR. "
            "Entree long quand prix tombe sous bande inferieure (ecart type extreme). "
            "Retour attendu vers la moyenne. "
            "Stop-loss = 1.0x ATR, take-profit = 2.0x ATR."
        ),
    },
    {
        "id": "meanrev_stddev_extreme_short_tight",
        "family": "mean-reversion", "indicators": ["bollinger"],
        "direction": "short_only", "risk": "tight",
        "tags": ["mean_reversion", "stddev", "extreme"],
        "desc": (
            "Strategie de Mean-reversion sur {symbol} {timeframe}. "
            "Indicateurs : Bollinger Bands (ecart type), ATR. "
            "Entree short quand prix depasse bande superieure (exces haussier). "
            "Repli attendu. "
            "Stop-loss = 1.0x ATR, take-profit = 2.0x ATR."
        ),
    },
    # ── Momentum (ROC) ──
    {
        "id": "momentum_roc_confirmation_long_balanced",
        "family": "momentum", "indicators": ["ema"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["momentum", "roc", "confirmation"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : EMA(10), EMA(30), ATR. "
            "Calculer ROC = (close - close[12]) / close[12]. "
            "Entree long quand ROC > 0 et EMA(10) > EMA(30). "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "momentum_roc_confirmation_short_balanced",
        "family": "momentum", "indicators": ["ema"],
        "direction": "short_only", "risk": "balanced",
        "tags": ["momentum", "roc", "confirmation"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : EMA(10), EMA(30), ATR. "
            "Calculer ROC = (close - close[12]) / close[12]. "
            "Entree short quand ROC < 0 et EMA(10) < EMA(30). "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    # ── Breakout (stochastic) ──
    {
        "id": "breakout_stoch_exit_long_tight",
        "family": "breakout", "indicators": ["stochastic", "bollinger"],
        "direction": "long_only", "risk": "tight",
        "tags": ["breakout", "stochastic", "confirmation"],
        "desc": (
            "Strategie de Breakout sur {symbol} {timeframe}. "
            "Indicateurs : Stochastic, Bollinger Bands, ATR. "
            "Entree long apres breakout de la bande superieure Bollinger "
            "confirme par Stochastique > 80. "
            "Stop-loss = 1.0x ATR, take-profit = 2.0x ATR."
        ),
    },
    {
        "id": "breakout_stoch_exit_short_tight",
        "family": "breakout", "indicators": ["stochastic", "bollinger"],
        "direction": "short_only", "risk": "tight",
        "tags": ["breakout", "stochastic", "confirmation"],
        "desc": (
            "Strategie de Breakout sur {symbol} {timeframe}. "
            "Indicateurs : Stochastic, Bollinger Bands, ATR. "
            "Entree short apres breakout baissier de la bande inferieure "
            "confirme par Stochastique < 20. "
            "Stop-loss = 1.0x ATR, take-profit = 2.0x ATR."
        ),
    },
    # ── Momentum (EMA slope) ──
    {
        "id": "momentum_ema_slope_trend_long_balanced",
        "family": "momentum", "indicators": ["ema"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["momentum", "ema_slope", "acceleration"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : EMA(20), ATR. "
            "Calculer la pente de EMA(20) via np.diff. "
            "Entree long quand la pente est positive et accelere. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "momentum_ema_slope_trend_short_balanced",
        "family": "momentum", "indicators": ["ema"],
        "direction": "short_only", "risk": "balanced",
        "tags": ["momentum", "ema_slope", "acceleration"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : EMA(20), ATR. "
            "Calculer la pente de EMA(20) via np.diff. "
            "Entree short quand la pente est negative et accelere. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    # ── Mean-reversion (Bollinger mid revert) ──
    {
        "id": "meanrev_bollinger_mid_revert_long_balanced",
        "family": "mean-reversion", "indicators": ["bollinger"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["mean_reversion", "bollinger", "mid_revert"],
        "desc": (
            "Strategie de Mean-reversion sur {symbol} {timeframe}. "
            "Indicateurs : Bollinger Bands(20,2), ATR. "
            "Entree long quand prix rebondit depuis bande inferieure "
            "vers bande mediane. Sortie a la bande mediane. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "meanrev_bollinger_mid_revert_short_balanced",
        "family": "mean-reversion", "indicators": ["bollinger"],
        "direction": "short_only", "risk": "balanced",
        "tags": ["mean_reversion", "bollinger", "mid_revert"],
        "desc": (
            "Strategie de Mean-reversion sur {symbol} {timeframe}. "
            "Indicateurs : Bollinger Bands(20,2), ATR. "
            "Entree short quand prix rejete depuis bande superieure "
            "vers bande mediane. Sortie a la mediane. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    # ── Breakout (pivot retrace) ──
    {
        "id": "breakout_vwap_retrace_long_tight",
        "family": "breakout", "indicators": ["ema", "obv"],
        "direction": "long_only", "risk": "tight",
        "tags": ["breakout", "retrace", "pullback"],
        "desc": (
            "Strategie de Breakout sur {symbol} {timeframe}. "
            "Indicateurs : EMA(20), OBV, ATR. "
            "Entree long apres cassure de EMA(20) suivie d'un pullback "
            "leger (retracement < 50% du breakout) avec OBV en hausse. "
            "Stop-loss = 1.0x ATR, take-profit = 2.0x ATR."
        ),
    },
    {
        "id": "breakout_vwap_retrace_short_tight",
        "family": "breakout", "indicators": ["ema", "obv"],
        "direction": "short_only", "risk": "tight",
        "tags": ["breakout", "retrace", "pullback"],
        "desc": (
            "Strategie de Breakout sur {symbol} {timeframe}. "
            "Indicateurs : EMA(20), OBV, ATR. "
            "Entree short apres cassure sous EMA(20) + pullback leger "
            "avec OBV en baisse. "
            "Stop-loss = 1.0x ATR, take-profit = 2.0x ATR."
        ),
    },
    # ── Momentum (double RSI) ──
    {
        "id": "momentum_double_rsi_long_balanced",
        "family": "momentum", "indicators": ["rsi"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["momentum", "double_rsi", "cross"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : RSI(14), ATR. "
            "Calculer RSI rapide (period=5) et RSI lent (period=14). "
            "Entree long quand RSI(5) croise au-dessus de RSI(14). "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "momentum_double_rsi_short_balanced",
        "family": "momentum", "indicators": ["rsi"],
        "direction": "short_only", "risk": "balanced",
        "tags": ["momentum", "double_rsi", "cross"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : RSI(14), ATR. "
            "Calculer RSI rapide (period=5) et RSI lent (period=14). "
            "Entree short quand RSI(5) croise en dessous de RSI(14). "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    # ── Mean-reversion (ADX range) ──
    {
        "id": "meanrev_adx_range_long_tight",
        "family": "mean-reversion", "indicators": ["adx", "rsi"],
        "direction": "long_only", "risk": "tight",
        "tags": ["mean_reversion", "adx_range", "low_trend"],
        "desc": (
            "Strategie de Mean-reversion sur {symbol} {timeframe}. "
            "Indicateurs : ADX, RSI(14), ATR. "
            "Entree long quand ADX < 20 (marche lateral) et RSI < 30. "
            "Reversion en marche sans tendance. "
            "Stop-loss = 1.0x ATR, take-profit = 2.0x ATR."
        ),
    },
    {
        "id": "meanrev_adx_range_short_tight",
        "family": "mean-reversion", "indicators": ["adx", "rsi"],
        "direction": "short_only", "risk": "tight",
        "tags": ["mean_reversion", "adx_range", "low_trend"],
        "desc": (
            "Strategie de Mean-reversion sur {symbol} {timeframe}. "
            "Indicateurs : ADX, RSI(14), ATR. "
            "Entree short quand ADX < 20 (range) et RSI > 70. "
            "Retournement en marche lateral. "
            "Stop-loss = 1.0x ATR, take-profit = 2.0x ATR."
        ),
    },
    # ── Momentum (volume surge) ──
    {
        "id": "momentum_breakout_vol_surge_long_wide",
        "family": "momentum", "indicators": ["obv", "ema"],
        "direction": "long_only", "risk": "wide",
        "tags": ["momentum", "volatility", "volume_surge"],
        "desc": (
            "Strategie de Momentum / Volatility sur {symbol} {timeframe}. "
            "Indicateurs : OBV, EMA(20), ATR. "
            "Entree long sur fort sursaut de volume (OBV acceleration) "
            "avec ATR en expansion et prix au-dessus de EMA(20). "
            "Stop-loss = 2.0x ATR, take-profit = 5.0x ATR."
        ),
    },
    {
        "id": "momentum_breakout_vol_surge_short_wide",
        "family": "momentum", "indicators": ["obv", "ema"],
        "direction": "short_only", "risk": "wide",
        "tags": ["momentum", "volatility", "volume_surge"],
        "desc": (
            "Strategie de Momentum / Volatility sur {symbol} {timeframe}. "
            "Indicateurs : OBV, EMA(20), ATR. "
            "Entree short quand baisse accompagnee de volume (OBV chute) "
            "et prix sous EMA(20). "
            "Stop-loss = 2.0x ATR, take-profit = 5.0x ATR."
        ),
    },
    # ── Breakout (multi-timeframe proxy) ──
    {
        "id": "breakout_multiple_timeframe_long_balanced",
        "family": "breakout", "indicators": ["donchian", "adx"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["breakout", "multi_tf_proxy", "donchian"],
        "desc": (
            "Strategie de Breakout sur {symbol} {timeframe}. "
            "Indicateurs : Donchian Channels, ADX, ATR. "
            "Entree long sur cassure du Donchian upper (proxy multi-echelle) "
            "confirmee par ADX > 25. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "breakout_multiple_timeframe_short_balanced",
        "family": "breakout", "indicators": ["donchian", "adx"],
        "direction": "short_only", "risk": "balanced",
        "tags": ["breakout", "multi_tf_proxy", "donchian"],
        "desc": (
            "Strategie de Breakout sur {symbol} {timeframe}. "
            "Indicateurs : Donchian Channels, ADX, ATR. "
            "Entree short sur cassure du Donchian lower confirmee par ADX > 25. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    # ── Mean-reversion (momentum filter) ──
    {
        "id": "meanrev_momentum_filter_long_balanced",
        "family": "mean-reversion", "indicators": ["rsi", "ema"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["mean_reversion", "momentum_filter", "trend_neutral"],
        "desc": (
            "Strategie de Mean-reversion sur {symbol} {timeframe}. "
            "Indicateurs : RSI(14), EMA(20), ATR. "
            "Entree long quand RSI extreme bas (< 25) "
            "ET tendance neutre (prix proche de EMA, pas de forte pente). "
            "Reversion hors forte tendance. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    {
        "id": "meanrev_momentum_filter_short_balanced",
        "family": "mean-reversion", "indicators": ["rsi", "ema"],
        "direction": "short_only", "risk": "balanced",
        "tags": ["mean_reversion", "momentum_filter", "trend_neutral"],
        "desc": (
            "Strategie de Mean-reversion sur {symbol} {timeframe}. "
            "Indicateurs : RSI(14), EMA(20), ATR. "
            "Entree short quand RSI extreme haut (> 75) "
            "ET tendance neutre. Reversion short hors tendance forte. "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
    # ── Breakout (support/resistance) ──
    {
        "id": "breakout_sup_res_long_tight",
        "family": "breakout", "indicators": ["pivot_points"],
        "direction": "long_only", "risk": "tight",
        "tags": ["breakout", "support_resistance", "pivot"],
        "desc": (
            "Strategie de Breakout sur {symbol} {timeframe}. "
            "Indicateurs : Pivot Points, ATR. "
            "Entree long quand prix monte au-dessus du pivot R1 (resistance cle). "
            "Stop-loss = 1.0x ATR, take-profit = 2.0x ATR."
        ),
    },
    {
        "id": "breakout_sup_res_short_tight",
        "family": "breakout", "indicators": ["pivot_points"],
        "direction": "short_only", "risk": "tight",
        "tags": ["breakout", "support_resistance", "pivot"],
        "desc": (
            "Strategie de Breakout sur {symbol} {timeframe}. "
            "Indicateurs : Pivot Points, ATR. "
            "Entree short quand prix casse sous le support S1. "
            "Stop-loss = 1.0x ATR, take-profit = 2.0x ATR."
        ),
    },
    # ── Momentum (MACD zero cross) ──
    {
        "id": "momentum_macd_zero_cross_long_balanced",
        "family": "momentum", "indicators": ["macd"],
        "direction": "long_only", "risk": "balanced",
        "tags": ["momentum", "macd", "zero_cross"],
        "desc": (
            "Strategie de Momentum sur {symbol} {timeframe}. "
            "Indicateurs : MACD, ATR. "
            "Entree long quand MACD passe de negatif a positif (zero cross). "
            "Stop-loss = 1.5x ATR, take-profit = 3.0x ATR."
        ),
    },
]


def _build_objective_catalog() -> List[CatalogObjective]:
    """Construit le catalogue cure de 50 objectifs pre-definis."""
    catalog = [
        _co(
            obj_id=entry["id"],
            family=entry["family"],
            indicators=list(entry["indicators"]),
            direction=entry["direction"],
            risk_profile=entry["risk"],
            description=entry["desc"],
            tags=entry.get("tags"),
        )
        for entry in _CURATED_CATALOG_RAW
    ]

    family_counts: Dict[str, int] = {}
    for obj in catalog:
        family_counts[obj.family] = family_counts.get(obj.family, 0) + 1

    logger.info(
        "objective_catalog_built count=%d families=%s",
        len(catalog),
        family_counts,
    )
    return catalog


# Singleton catalogue (lazy init)
_OBJECTIVE_CATALOG: Optional[List[CatalogObjective]] = None


def get_objective_catalog() -> List[CatalogObjective]:
    """Retourne le catalogue d'objectifs (lazy init)."""
    global _OBJECTIVE_CATALOG
    if _OBJECTIVE_CATALOG is None:
        _OBJECTIVE_CATALOG = _build_objective_catalog()
    return _OBJECTIVE_CATALOG


# ---------------------------------------------------------------------------
# Exploration Tracker — persistance et suivi de couverture
# ---------------------------------------------------------------------------

class ExplorationTracker:
    """Gère l'exploration systématique du catalogue d'objectifs.

    Persiste l'état dans un fichier JSON pour survivre aux redémarrages.
    """

    STATE_FILE = SANDBOX_ROOT / "_exploration_state.json"
    _SELECTION_MODES = ("diversify", "hybrid", "exploit", "wildcard")

    def __init__(self, catalog: List[CatalogObjective]):
        self.catalog = catalog
        self.catalog_by_id: Dict[str, CatalogObjective] = {
            obj.id: obj for obj in catalog
        }
        self._catalog_hash = self._compute_catalog_hash()
        self.state = self._load_or_create_state()

    # -- persistence --

    def _compute_catalog_hash(self) -> str:
        ids = "|".join(obj.id for obj in self.catalog)
        return hashlib.md5(ids.encode()).hexdigest()[:16]

    def _load_or_create_state(self) -> Dict[str, Any]:
        if self.STATE_FILE.exists():
            try:
                with open(self.STATE_FILE, "r", encoding="utf-8") as f:
                    state = json.load(f)
                if state.get("catalog_hash") == self._catalog_hash:
                    return self._migrate_state(state)
                logger.info("exploration_tracker_catalog_changed — reset")
            except Exception:
                pass
        return self._fresh_state()

    def _fresh_state(self) -> Dict[str, Any]:
        order = [obj.id for obj in self.catalog]
        random.shuffle(order)
        selection_mode_counts = {mode: 0 for mode in self._SELECTION_MODES}
        return {
            "version": "2.0",
            "catalog_hash": self._catalog_hash,
            "exploration_order": order,
            "current_index": 0,
            "explored": {},
            "selection_mode_counts": selection_mode_counts,
            "last_selection_mode": "diversify",
        }

    def _migrate_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(state, dict):
            return self._fresh_state()

        if not isinstance(state.get("exploration_order"), list):
            state["exploration_order"] = [obj.id for obj in self.catalog]
        if not isinstance(state.get("explored"), dict):
            state["explored"] = {}
        if not isinstance(state.get("current_index"), int):
            state["current_index"] = 0

        mode_counts = state.get("selection_mode_counts")
        if not isinstance(mode_counts, dict):
            mode_counts = {}
        for mode in self._SELECTION_MODES:
            mode_counts[mode] = int(mode_counts.get(mode, 0) or 0)
        state["selection_mode_counts"] = mode_counts

        last_mode = str(state.get("last_selection_mode", "")).strip()
        if last_mode not in self._SELECTION_MODES:
            state["last_selection_mode"] = "diversify"

        state["version"] = "2.0"
        return state

    def _save(self) -> None:
        self.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.STATE_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)
        tmp.replace(self.STATE_FILE)

    @staticmethod
    def _normalized_entropy(counts: Dict[str, int]) -> float:
        total = sum(int(v) for v in counts.values())
        if total <= 0:
            return 0.0
        values = [int(v) for v in counts.values() if int(v) > 0]
        if len(values) <= 1:
            return 0.0
        entropy = 0.0
        for count in values:
            p = count / total
            entropy -= p * math.log(p)
        return round(entropy / math.log(len(values)), 4)

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            out = float(value)
        except Exception:
            return default
        if not math.isfinite(out):
            return default
        return out

    def _payload_positive_weight(self, payload: Dict[str, Any]) -> float:
        status = str(payload.get("status", "")).strip().lower()
        sharpe = self._safe_float(payload.get("best_sharpe", 0.0), default=0.0)
        ret_pct = self._safe_float(payload.get("best_return_pct", 0.0), default=0.0)

        baseline = 0.0
        if status == "success":
            baseline += 1.2
        if ret_pct > 0:
            baseline += min(ret_pct, 80.0) / 25.0
        if sharpe > 0:
            baseline += min(sharpe, 3.0) * 0.6

        if baseline <= 0.0 and status != "success":
            return 0.0
        if ret_pct <= 0 and sharpe < 0.4 and status != "success":
            return 0.0
        return round(max(baseline, 0.0), 4)

    def _build_positive_profiles(self) -> Dict[str, Any]:
        explored = self.state.get("explored", {})
        family_counts: Dict[str, float] = {}
        direction_counts: Dict[str, float] = {}
        risk_counts: Dict[str, float] = {}
        novelty_counts: Dict[str, float] = {}
        indicator_counts: Dict[str, float] = {}
        pattern_counts: Dict[str, float] = {}
        total_positive = 0
        weighted_total = 0.0

        for obj_id, payload_raw in explored.items():
            obj = self.catalog_by_id.get(obj_id)
            if obj is None:
                continue
            payload = cast(Dict[str, Any], payload_raw)
            weight = self._payload_positive_weight(payload)
            if weight <= 0:
                continue

            total_positive += 1
            weighted_total += weight
            family_counts[obj.family] = family_counts.get(obj.family, 0.0) + weight
            direction_counts[obj.direction] = direction_counts.get(obj.direction, 0.0) + weight
            risk_counts[obj.risk_profile] = risk_counts.get(obj.risk_profile, 0.0) + weight
            novelty_counts[obj.novelty_angle] = novelty_counts.get(obj.novelty_angle, 0.0) + weight

            clean_inds = [ind.lower() for ind in obj.indicators]
            for ind in clean_inds:
                indicator_counts[ind] = indicator_counts.get(ind, 0.0) + weight

            pattern_legs = [ind.upper() for ind in clean_inds if ind != "atr"]
            if not pattern_legs:
                pattern_legs = [ind.upper() for ind in clean_inds]
            if pattern_legs:
                pattern_name = " + ".join(sorted(pattern_legs[:3]))
                pattern_counts[pattern_name] = pattern_counts.get(pattern_name, 0.0) + weight

        return {
            "positive_count": total_positive,
            "weighted_total": round(weighted_total, 4),
            "family": family_counts,
            "direction": direction_counts,
            "risk": risk_counts,
            "novelty": novelty_counts,
            "indicator": indicator_counts,
            "pattern": pattern_counts,
        }

    def _choose_selection_mode(self, positive_count: int, explored_count: int) -> str:
        roll = random.random()
        if positive_count <= 0:
            if roll < 0.62:
                return "diversify"
            if roll < 0.88:
                return "hybrid"
            return "wildcard"

        if explored_count < 12:
            if roll < 0.55:
                return "diversify"
            if roll < 0.90:
                return "hybrid"
            return "wildcard"

        if roll < 0.35:
            return "diversify"
        if roll < 0.72:
            return "hybrid"
        if roll < 0.93:
            return "exploit"
        return "wildcard"

    def _recent_explored_ids(self, limit: int = 8) -> List[str]:
        explored = self.state.get("explored", {})
        ranked: List[Tuple[str, str]] = []
        for obj_id, payload in explored.items():
            if obj_id not in self.catalog_by_id:
                continue
            tested_at = str(payload.get("tested_at", ""))
            ranked.append((tested_at, obj_id))
        ranked.sort(reverse=True)
        return [obj_id for _, obj_id in ranked[:max(1, limit)]]

    def _build_explored_distributions(self) -> Dict[str, Dict[str, int]]:
        explored = self.state.get("explored", {})
        family_counts: Dict[str, int] = {}
        direction_counts: Dict[str, int] = {}
        risk_counts: Dict[str, int] = {}
        novelty_counts: Dict[str, int] = {}
        for obj_id in explored.keys():
            obj = self.catalog_by_id.get(obj_id)
            if obj is None:
                continue
            family_counts[obj.family] = family_counts.get(obj.family, 0) + 1
            direction_counts[obj.direction] = direction_counts.get(obj.direction, 0) + 1
            risk_counts[obj.risk_profile] = risk_counts.get(obj.risk_profile, 0) + 1
            novelty_counts[obj.novelty_angle] = novelty_counts.get(obj.novelty_angle, 0) + 1
        return {
            "family": family_counts,
            "direction": direction_counts,
            "risk": risk_counts,
            "novelty": novelty_counts,
        }

    # -- API --

    def get_next_objective(self) -> Optional[CatalogObjective]:
        """Retourne un objectif non exploré en combinant diversité et exploitation."""
        order = self.state.get("exploration_order", [])
        explored = self.state.get("explored", {})
        idx = int(self.state.get("current_index", 0))
        total = len(order)
        if total == 0:
            return None

        lookahead = min(max(24, total // 6), total)
        candidates: List[Tuple[int, str]] = []
        for pos in range(idx, min(total, idx + lookahead)):
            obj_id = order[pos]
            if obj_id not in explored and obj_id in self.catalog_by_id:
                candidates.append((pos, obj_id))

        if not candidates:
            for pos, obj_id in enumerate(order):
                if obj_id not in explored and obj_id in self.catalog_by_id:
                    candidates.append((pos, obj_id))
                    if len(candidates) >= lookahead:
                        break
        if not candidates:
            return None

        dists = self._build_explored_distributions()
        family_counts = dists["family"]
        direction_counts = dists["direction"]
        risk_counts = dists["risk"]
        novelty_counts = dists["novelty"]

        recent_ids = self._recent_explored_ids(limit=8)
        recent_objs = [self.catalog_by_id[obj_id] for obj_id in recent_ids if obj_id in self.catalog_by_id]
        latest_obj = recent_objs[0] if recent_objs else None
        recent_indicator_sets = [set(obj.indicators) for obj in recent_objs[:3]]
        positive_profiles = self._build_positive_profiles()
        positive_count = int(positive_profiles.get("positive_count", 0) or 0)

        selection_mode = self._choose_selection_mode(
            positive_count=positive_count,
            explored_count=len(explored),
        )
        mode_cfg = {
            "diversify": {"diversity_w": 1.35, "positive_w": 0.40, "random_w": 0.14, "top_k": 14},
            "hybrid": {"diversity_w": 1.00, "positive_w": 0.95, "random_w": 0.10, "top_k": 10},
            "exploit": {"diversity_w": 0.72, "positive_w": 1.70, "random_w": 0.06, "top_k": 6},
            "wildcard": {"diversity_w": 0.70, "positive_w": 0.65, "random_w": 0.36, "top_k": 18},
        }
        cfg = mode_cfg.get(selection_mode, mode_cfg["hybrid"])

        complexity_bias = 0.0
        if positive_count <= 0 and len(explored) < 6:
            complexity_bias = -0.18
        elif positive_count >= 2:
            complexity_bias = 0.55
        elif positive_count >= 1:
            complexity_bias = 0.32
        elif selection_mode == "wildcard":
            complexity_bias = 0.12

        pos_family = cast(Dict[str, float], positive_profiles.get("family", {}))
        pos_direction = cast(Dict[str, float], positive_profiles.get("direction", {}))
        pos_risk = cast(Dict[str, float], positive_profiles.get("risk", {}))
        pos_novelty = cast(Dict[str, float], positive_profiles.get("novelty", {}))
        pos_indicator = cast(Dict[str, float], positive_profiles.get("indicator", {}))
        pos_pattern = cast(Dict[str, float], positive_profiles.get("pattern", {}))

        max_family = max(pos_family.values(), default=0.0)
        max_direction = max(pos_direction.values(), default=0.0)
        max_risk = max(pos_risk.values(), default=0.0)
        max_novelty = max(pos_novelty.values(), default=0.0)
        max_indicator = max(pos_indicator.values(), default=0.0)
        max_pattern = max(pos_pattern.values(), default=0.0)

        def _norm(value: float, max_value: float) -> float:
            if max_value <= 0:
                return 0.0
            return float(value) / max_value

        scored_candidates: List[Tuple[int, str, float]] = []
        for pos, obj_id in candidates:
            obj = self.catalog_by_id[obj_id]
            complexity_score = _objective_complexity_score(obj)

            diversity_score = 0.0
            diversity_score += 2.8 / (1.0 + family_counts.get(obj.family, 0))
            diversity_score += 1.6 / (1.0 + direction_counts.get(obj.direction, 0))
            diversity_score += 1.1 / (1.0 + risk_counts.get(obj.risk_profile, 0))
            diversity_score += 1.3 / (1.0 + novelty_counts.get(obj.novelty_angle, 0))

            if latest_obj is not None:
                if obj.family == latest_obj.family:
                    diversity_score -= 1.8
                if obj.direction == latest_obj.direction:
                    diversity_score -= 0.6
                if obj.risk_profile == latest_obj.risk_profile:
                    diversity_score -= 0.4
                if obj.novelty_angle == latest_obj.novelty_angle:
                    diversity_score -= 0.5

            if recent_indicator_sets:
                overlap = max(len(set(obj.indicators) & inds) for inds in recent_indicator_sets)
                diversity_score -= 0.35 * float(overlap)

            indicators_key = [ind.lower() for ind in obj.indicators]
            pattern_legs = [ind.upper() for ind in indicators_key if ind != "atr"]
            if not pattern_legs:
                pattern_legs = [ind.upper() for ind in indicators_key]
            pattern_name = " + ".join(sorted(pattern_legs[:3])) if pattern_legs else ""
            indicator_scores = [
                _norm(pos_indicator.get(ind, 0.0), max_indicator)
                for ind in set(indicators_key)
            ]
            indicator_hit = (
                sum(indicator_scores) / len(indicator_scores)
                if indicator_scores else 0.0
            )

            positive_score = 0.0
            positive_score += 1.5 * _norm(pos_family.get(obj.family, 0.0), max_family)
            positive_score += 1.1 * _norm(pos_direction.get(obj.direction, 0.0), max_direction)
            positive_score += 0.9 * _norm(pos_risk.get(obj.risk_profile, 0.0), max_risk)
            positive_score += 1.1 * _norm(pos_novelty.get(obj.novelty_angle, 0.0), max_novelty)
            positive_score += 1.7 * indicator_hit
            positive_score += 0.9 * _norm(pos_pattern.get(pattern_name, 0.0), max_pattern)

            score = cfg["diversity_w"] * diversity_score
            score += cfg["positive_w"] * positive_score
            score += complexity_bias * complexity_score
            score -= 0.002 * max(pos - idx, 0)

            if positive_count <= 0 and complexity_score >= 3.8:
                score -= 0.25

            if selection_mode == "wildcard" and obj.novelty_angle != "classic":
                score += 0.15 + random.random() * 0.25
            if selection_mode == "exploit" and positive_count > 0 and obj.family in pos_family:
                score += 0.2
            score += random.random() * float(cfg["random_w"])

            scored_candidates.append((pos, obj_id, score))

        ranked = sorted(scored_candidates, key=lambda item: item[2], reverse=True)
        top_k = max(1, min(int(cfg["top_k"]), len(ranked)))
        sample_pool = ranked[:top_k]
        floor = min(score for _, _, score in sample_pool)
        weights = [max((score - floor) + 0.05, 0.01) for _, _, score in sample_pool]
        best_pos, best_id, best_score = random.choices(sample_pool, weights=weights, k=1)[0]

        self.state["current_index"] = best_pos
        mode_counts = self.state.get("selection_mode_counts", {})
        if not isinstance(mode_counts, dict):
            mode_counts = {}
        mode_counts[selection_mode] = int(mode_counts.get(selection_mode, 0) or 0) + 1
        self.state["selection_mode_counts"] = mode_counts
        self.state["last_selection_mode"] = selection_mode

        logger.info(
            "exploration_tracker_pick mode=%s candidates=%d positive=%d pick=%s score=%.3f",
            selection_mode,
            len(candidates),
            positive_count,
            best_id,
            best_score,
        )
        return self.catalog_by_id[best_id]

    def _advance_index(self) -> None:
        order = self.state.get("exploration_order", [])
        explored = self.state.get("explored", {})
        idx = int(self.state.get("current_index", 0)) + 1
        while idx < len(order) and order[idx] in explored:
            idx += 1
        self.state["current_index"] = idx

    def mark_explored(
        self,
        obj_id: str,
        *,
        status: str,
        best_sharpe: float,
        best_return_pct: float,
        session_id: str,
        symbol: str,
        timeframe: str,
    ) -> None:
        selection_mode = str(self.state.get("last_selection_mode", "diversify"))
        self.state["explored"][obj_id] = {
            "tested_at": datetime.now().isoformat(),
            "status": status,
            "best_sharpe": best_sharpe,
            "best_return_pct": best_return_pct,
            "session_id": session_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "selection_mode": selection_mode,
        }
        self._advance_index()
        self._save()

    @staticmethod
    def _top_weighted_entries(counts: Dict[str, float], limit: int = 3) -> List[Dict[str, Any]]:
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        top = ranked[:max(1, limit)]
        return [
            {"name": name, "weight": round(float(weight), 4)}
            for name, weight in top
        ]

    def get_positive_bias_summary(self, limit: int = 3) -> Dict[str, Any]:
        profiles = self._build_positive_profiles()
        positive_count = int(profiles.get("positive_count", 0) or 0)
        if positive_count <= 0:
            return {
                "positive_count": 0,
                "weighted_total": 0.0,
                "top_families": [],
                "top_indicator_patterns": [],
                "top_novelty_angles": [],
            }

        return {
            "positive_count": positive_count,
            "weighted_total": float(profiles.get("weighted_total", 0.0) or 0.0),
            "top_families": self._top_weighted_entries(
                cast(Dict[str, float], profiles.get("family", {})),
                limit=limit,
            ),
            "top_indicator_patterns": self._top_weighted_entries(
                cast(Dict[str, float], profiles.get("pattern", {})),
                limit=limit,
            ),
            "top_novelty_angles": self._top_weighted_entries(
                cast(Dict[str, float], profiles.get("novelty", {})),
                limit=limit,
            ),
        }

    def get_coverage_stats(self) -> Dict[str, Any]:
        total = len(self.catalog)
        explored = self.state["explored"]
        n_explored = len(explored)
        n_success = sum(1 for v in explored.values() if v.get("status") == "success")
        best = max(
            (v.get("best_sharpe", float("-inf")) for v in explored.values()),
            default=0.0,
        )
        dists = self._build_explored_distributions()
        family_counts = dists["family"]
        direction_counts = dists["direction"]
        risk_counts = dists["risk"]
        novelty_counts = dists["novelty"]
        positive_profiles = self._build_positive_profiles()
        positive_count = int(positive_profiles.get("positive_count", 0) or 0)
        selection_mode_counts = self.state.get("selection_mode_counts", {})
        if not isinstance(selection_mode_counts, dict):
            selection_mode_counts = {}
        selection_mode_counts = {
            mode: int(selection_mode_counts.get(mode, 0) or 0)
            for mode in self._SELECTION_MODES
        }

        return {
            "total_objectives": total,
            "explored_count": n_explored,
            "success_count": n_success,
            "coverage_pct": round(100.0 * n_explored / max(total, 1), 1),
            "best_sharpe_overall": round(best, 3),
            "selection_modes": selection_mode_counts,
            "diversity": {
                "family_entropy": self._normalized_entropy(family_counts),
                "direction_entropy": self._normalized_entropy(direction_counts),
                "risk_entropy": self._normalized_entropy(risk_counts),
                "novelty_entropy": self._normalized_entropy(novelty_counts),
                "family_distribution": dict(sorted(family_counts.items())),
                "direction_distribution": dict(sorted(direction_counts.items())),
                "risk_distribution": dict(sorted(risk_counts.items())),
                "novelty_distribution": dict(sorted(novelty_counts.items())),
            },
            "positive_frontier": {
                "positive_count": positive_count,
                "positive_rate_pct": round(100.0 * positive_count / max(n_explored, 1), 1),
                "weighted_total": round(float(positive_profiles.get("weighted_total", 0.0) or 0.0), 4),
                "family_distribution": {
                    k: round(v, 4)
                    for k, v in sorted(cast(Dict[str, float], positive_profiles.get("family", {})).items())
                },
                "indicator_distribution": {
                    k: round(v, 4)
                    for k, v in sorted(cast(Dict[str, float], positive_profiles.get("indicator", {})).items())
                },
                "novelty_distribution": {
                    k: round(v, 4)
                    for k, v in sorted(cast(Dict[str, float], positive_profiles.get("novelty", {})).items())
                },
                "top_patterns": self._top_weighted_entries(
                    cast(Dict[str, float], positive_profiles.get("pattern", {})),
                    limit=5,
                ),
            },
        }

    def reset(self) -> None:
        """Reset complet : re-shuffle et repart de zéro."""
        self.state = self._fresh_state()
        self._save()
        logger.info("exploration_tracker_reset")


# Singleton tracker (lazy init)
_EXPLORATION_TRACKER: Optional[ExplorationTracker] = None


def _get_exploration_tracker() -> ExplorationTracker:
    global _EXPLORATION_TRACKER
    if _EXPLORATION_TRACKER is None:
        _EXPLORATION_TRACKER = ExplorationTracker(get_objective_catalog())
    return _EXPLORATION_TRACKER


def get_next_catalog_objective(
    symbol: "str | List[str]" = "BTCUSDC",
    timeframe: "str | List[str]" = "1h",
) -> Optional[tuple[str, str]]:
    """Retourne (description, obj_id) du prochain objectif non exploré.

    Accepte des listes de symboles/timeframes : un couple est choisi
    aléatoirement. La sélection d'objectif est ensuite pondérée pour
    combiner diversité (exploration) et motifs historiquement positifs
    (exploitation), avec comportements aléatoires contrôlés.

    Si symbol=None ou timeframe=None, retire les tokens/TF hardcodés pour
    permettre sélection LLM intelligente (auto_market_pick).

    Returns:
        ``(objective_text, obj_id)`` ou ``None`` si le catalogue est épuisé.
    """
    # Normaliser listes → valeur unique (choix aléatoire) si fourni
    if isinstance(symbol, list):
        symbol = random.choice(symbol) if symbol else None
    if isinstance(timeframe, list):
        timeframe = random.choice(timeframe) if timeframe else None

    tracker = _get_exploration_tracker()
    obj = tracker.get_next_objective()
    if obj is None:
        return None

    text = obj.description

    # Remplacer placeholders si valeurs fournies
    if symbol is not None:
        text = text.replace("{symbol}", str(symbol))
    else:
        # symbol=None → Retirer tokens hardcodés (ex: "0GUSDC") pour sélection LLM
        text = _remove_hardcoded_tokens(text)

    if timeframe is not None:
        text = text.replace("{timeframe}", str(timeframe))
    else:
        # timeframe=None → Retirer TF hardcodés (ex: "1h") pour sélection LLM
        text = _remove_hardcoded_timeframes(text)

    return text, obj.id


def mark_catalog_objective_explored(
    obj_id: str,
    *,
    status: str,
    best_sharpe: float,
    best_return_pct: float = 0.0,
    session_id: str,
    symbol: str,
    timeframe: str,
) -> None:
    """Enregistre un objectif du catalogue comme exploré."""
    tracker = _get_exploration_tracker()
    tracker.mark_explored(
        obj_id,
        status=status,
        best_sharpe=best_sharpe,
        best_return_pct=best_return_pct,
        session_id=session_id,
        symbol=symbol,
        timeframe=timeframe,
    )


def get_catalog_coverage() -> Dict[str, Any]:
    """Retourne les statistiques de couverture du catalogue."""
    tracker = _get_exploration_tracker()
    return tracker.get_coverage_stats()


def reset_catalog_exploration() -> None:
    """Reset l'exploration du catalogue (re-shuffle)."""
    global _EXPLORATION_TRACKER
    tracker = _get_exploration_tracker()
    tracker.reset()
    _EXPLORATION_TRACKER = None  # force lazy re-init


def recommend_market_context(
    llm_client: Any,
    *,
    objective: str,
    candidate_symbols: List[str],
    candidate_timeframes: List[str],
    default_symbol: str = "BTCUSDC",
    default_timeframe: str = "1h",
    stream_callback: Optional[Callable[[str, str], None]] = None,
    recent_markets: Optional[List[Tuple[str, str]]] = None,
) -> Dict[str, Any]:
    """Recommande un couple (symbol, timeframe) adapté à un objectif Builder.

    Le choix est strictement borné à l'univers fourni (`candidate_symbols`,
    `candidate_timeframes`). En cas de réponse invalide du LLM, un fallback
    robuste est appliqué.
    """

    def _unique_non_empty(values: List[str], *, upper: bool = False) -> List[str]:
        out: List[str] = []
        seen: set[str] = set()
        for raw in values:
            val = str(raw or "").strip()
            if not val:
                continue
            if upper:
                val = val.upper()
            if val in seen:
                continue
            seen.add(val)
            out.append(val)
        return out

    def _find_objective_market_hints(
        objective_text: str,
        *,
        allowed_symbols: List[str],
        allowed_timeframes: List[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Extrait les indices explicites symbol/timeframe présents dans l'objectif."""
        text = sanitize_objective_text(objective_text)
        if not text:
            return None, None

        text_upper = text.upper()

        symbol_hits: List[Tuple[int, str]] = []
        for symbol in allowed_symbols:
            match = re.search(
                rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])",
                text_upper,
            )
            if match:
                symbol_hits.append((match.start(), symbol))

        timeframe_hits: List[Tuple[int, str]] = []
        for timeframe in allowed_timeframes:
            tf = str(timeframe or "").strip()
            if not tf:
                continue
            if re.fullmatch(r"\d+[mhdwM]", tf):
                match = re.search(
                    rf"(?<![A-Za-z0-9]){re.escape(tf[:-1])}\s*{re.escape(tf[-1])}(?![A-Za-z0-9])",
                    text,
                    flags=re.IGNORECASE,
                )
            else:
                match = re.search(
                    rf"(?<![A-Za-z0-9]){re.escape(tf)}(?![A-Za-z0-9])",
                    text,
                    flags=re.IGNORECASE,
                )
            if match:
                timeframe_hits.append((match.start(), tf))

        hinted_symbol = min(symbol_hits, key=lambda x: x[0])[1] if symbol_hits else None
        hinted_timeframe = (
            min(timeframe_hits, key=lambda x: x[0])[1]
            if timeframe_hits else None
        )
        return hinted_symbol, hinted_timeframe

    symbol_re = re.compile(r"^[A-Za-z0-9_.-]{2,24}$")
    timeframe_re = re.compile(r"^\d+[mhdwM]$")

    # Universe-first: don't inject default symbol/timeframe when a valid universe exists.
    symbols = _unique_non_empty(candidate_symbols, upper=True)
    if not symbols:
        symbols = _unique_non_empty([default_symbol or "BTCUSDC"], upper=True)
    symbols = [s for s in symbols if symbol_re.match(s)]

    timeframes = _unique_non_empty(candidate_timeframes, upper=False)
    if not timeframes:
        timeframes = _unique_non_empty([default_timeframe or "1h"], upper=False)
    timeframes = [tf for tf in timeframes if timeframe_re.match(tf)]

    # Fallback contractuel: prioriser le couple par défaut quand il est valide.
    # Utilisé pour les cas "réponse LLM invalide / hors univers" afin de garder
    # un comportement déterministe et prévisible côté tests et UI.
    strict_fallback_symbol = (
        str(default_symbol).strip().upper()
        if str(default_symbol).strip().upper() in symbols
        else (symbols[0] if symbols else "BTCUSDC")
    )
    strict_fallback_timeframe = (
        str(default_timeframe).strip()
        if str(default_timeframe).strip() in timeframes
        else (timeframes[0] if timeframes else "1h")
    )

    # Fallback initial (sera recalculé après détection du type de stratégie)
    _initial_fallback_symbol = (
        str(default_symbol).strip().upper()
        if str(default_symbol).strip().upper() in symbols
        else (random.choice(symbols) if symbols else "BTCUSDC")
    )
    _initial_fallback_timeframe = (
        str(default_timeframe).strip()
        if str(default_timeframe).strip() in timeframes
        else (random.choice(timeframes) if timeframes else "1h")
    )

    if not symbols or not timeframes:
        return {
            "symbol": strict_fallback_symbol,
            "timeframe": strict_fallback_timeframe,
            "confidence": 0.0,
            "reason": "Univers marché incomplet, fallback par défaut.",
            "source": "fallback_no_candidates",
        }

    clean_objective = sanitize_objective_text(objective)
    if not clean_objective:
        clean_objective = str(objective or "").strip()

    # Détecter le type de stratégie AVANT d'extraire les hints
    # (car si type détecté, on ignore les hints pour privilégier le tri intelligent)
    detected_strategy_type = None
    objective_lower = clean_objective.lower()

    if any(kw in objective_lower for kw in ["scalp", "court terme", "rapide"]):
        detected_strategy_type = "scalping"
    elif any(kw in objective_lower for kw in ["breakout", "cassure", "sortie.*range", "donchian"]):
        detected_strategy_type = "breakout"
    elif any(kw in objective_lower for kw in ["momentum", "directionnel"]):
        detected_strategy_type = "momentum"
    elif any(kw in objective_lower for kw in ["tendance", "trend", "suivre"]):
        detected_strategy_type = "trend"
    elif any(kw in objective_lower for kw in ["mean", "reversion", "retour", "moyenne", "bollinger", "survente"]):
        detected_strategy_type = "mean_reversion"

    # Trier les tokens selon le type de stratégie détecté
    ranked_symbols: List[str] = []
    if detected_strategy_type:
        from config.market_selection import rank_tokens_for_strategy
        # Mélange d'abord les candidats pour randomiser les égalités de score.
        # rank_tokens_for_strategy est stable: à score égal, l'ordre d'entrée est conservé.
        symbols_for_ranking = symbols.copy()
        random.shuffle(symbols_for_ranking)
        ranked_symbols = rank_tokens_for_strategy(symbols_for_ranking, detected_strategy_type)
        # Anti-biais de position: l'ordre envoyé au LLM est volontairement mélangé.
        # Le ranking reste conservé pour le fallback deterministic.
        shuffled_symbols = ranked_symbols.copy()
        random.shuffle(shuffled_symbols)
        logger.info(
            "Market selection: strategy_type=%s, ranked_tokens=%s, prompt_tokens_shuffled=YES",
            detected_strategy_type,
            ", ".join(ranked_symbols[:5]),  # Log top 5 ranking brut
        )
    else:
        # Fallback : shuffle aléatoire si type non détecté
        shuffled_symbols = symbols.copy()
        random.shuffle(shuffled_symbols)
        logger.info("Market selection: strategy_type=UNKNOWN, tokens=shuffled")

    # Mélanger les timeframes (pas de tri spécifique)
    shuffled_timeframes = timeframes.copy()
    random.shuffle(shuffled_timeframes)

    # Extraction des hints : SEULEMENT si aucun type de stratégie détecté
    # Si type détecté, on ignore les hints du catalogue pour privilégier le tri intelligent
    hinted_symbol = None
    hinted_timeframe = None

    if not detected_strategy_type:
        # Pas de type détecté : extraire les hints pour guider le LLM
        hinted_symbol, hinted_timeframe = _find_objective_market_hints(
            clean_objective,
            allowed_symbols=symbols,
            allowed_timeframes=timeframes,
        )
        logger.info(
            "Market selection: strategy_type=NONE → using hints, symbol=%s, timeframe=%s",
            hinted_symbol or "NONE",
            hinted_timeframe or "NONE"
        )
    else:
        # Type détecté : IGNORER les hints hardcodés pour privilégier le tri intelligent
        logger.info(
            "Market selection: strategy_type=%s → IGNORING hints from objective (prioritize intelligent ranking)",
            detected_strategy_type
        )

    recent_symbol_set = {
        str(s or "").strip().upper()
        for s, _ in (recent_markets or [])
        if str(s or "").strip()
    }

    # Fallback intelligent : éviter le biais top-1 quand plusieurs candidats sont valides.
    if hinted_symbol and hinted_symbol in symbols:
        fallback_symbol = hinted_symbol
    else:
        # Si stratégie détectée, piocher dans un pool top-N pour réduire le biais "toujours le même token".
        if detected_strategy_type and ranked_symbols:
            fallback_pool = ranked_symbols[: min(5, len(ranked_symbols))]
            non_recent_pool = [s for s in fallback_pool if s not in recent_symbol_set]
            if non_recent_pool:
                fallback_pool = non_recent_pool
            fallback_symbol = random.choice(fallback_pool) if fallback_pool else ranked_symbols[0]
        else:
            fallback_symbol = (
                shuffled_symbols[0] if shuffled_symbols else _initial_fallback_symbol
            )

    # Fallback timeframe : prioriser TF recommandés / hints / diversité.
    if detected_strategy_type:
        try:
            from config.market_selection import get_strategy_requirements
            reqs = get_strategy_requirements(detected_strategy_type)
            recommended_tfs = reqs.get("timeframes", ["1h"])
            # Choisir un TF recommandé disponible, sans biais de position dans la liste.
            recommended_available = [tf for tf in recommended_tfs if tf in timeframes]
            if recommended_available:
                fallback_timeframe = random.choice(recommended_available)
            else:
                fallback_timeframe = (
                    shuffled_timeframes[0] if shuffled_timeframes else _initial_fallback_timeframe
                )
        except Exception:
            fallback_timeframe = (
                shuffled_timeframes[0] if shuffled_timeframes else _initial_fallback_timeframe
            )
    elif hinted_timeframe and hinted_timeframe in timeframes:
        fallback_timeframe = hinted_timeframe
    else:
        fallback_timeframe = (
            shuffled_timeframes[0] if shuffled_timeframes else _initial_fallback_timeframe
        )

    logger.info(
        "Market selection: fallback=%s %s (source=%s)",
        fallback_symbol,
        fallback_timeframe,
        "strategy_optimized" if detected_strategy_type else "default"
    )

    # Validation diversité : désactiver si trop peu d'alternatives
    diversity_instruction = ""
    if recent_markets:
        from config.market_selection import get_diversity_min_alternatives

        available_combos = [(s, tf) for s in symbols for tf in timeframes]
        recent_window = recent_markets[-6:]  # Fenêtre de diversité (6 derniers)
        unused_combos = [c for c in available_combos if c not in recent_window]
        min_alts = get_diversity_min_alternatives()

        if len(unused_combos) >= min_alts:
            recent_str = ", ".join(f"{s} {tf}" for s, tf in recent_window)
            diversity_instruction = (
                f"\n- DÉJÀ UTILISÉS récemment : {recent_str}. "
                "Tu DOIS choisir un couple DIFFÉRENT. Varie tokens ET timeframes."
            )
            # Log structuré : diversité activée
            logger.info(
                "Market selection: diversity=ACTIVE, excluded_count=%d, alternatives=%d, recent=%s",
                len(recent_window),
                len(unused_combos),
                recent_str,
            )
        else:
            # Diversité désactivée : univers trop restreint
            logger.warning(
                "Market selection: diversity=DISABLED, reason=Univers restreint (%d alternatives < %d min), "
                "recent_count=%d",
                len(unused_combos),
                min_alts,
                len(recent_window),
            )
            diversity_instruction = ""  # Pas de contrainte

    objective_hint_instruction = ""
    hint_lines: List[str] = []

    # Détection conflit hints vs diversité
    hints_conflict = False
    if hinted_symbol and hinted_timeframe and recent_markets:
        hinted_combo = (hinted_symbol, hinted_timeframe)
        recent_window = recent_markets[-6:]
        if hinted_combo in recent_window:
            hints_conflict = True
            logger.warning(
                "Market selection: CONFLICT hints vs diversity, hinted=%s %s (already in recent_markets), "
                "priority=diversity → hints IGNORED",
                hinted_symbol, hinted_timeframe
            )
            # Annuler les hints (priorité à la diversité)
            hinted_symbol = None
            hinted_timeframe = None

    # Construction des instructions hints (si pas de conflit)
    if hinted_symbol:
        hint_lines.append(
            f"- L'objectif mentionne le symbole `{hinted_symbol}` : "
            "considère-le comme une préférence, pas comme une contrainte absolue."
        )
    if hinted_timeframe:
        hint_lines.append(
            f"- L'objectif mentionne le timeframe `{hinted_timeframe}` : "
            "considère-le comme une préférence, pas comme une contrainte absolue."
        )

    if hint_lines:
        objective_hint_instruction = "\n" + "\n".join(hint_lines)

        # Log structuré : hints détectés (si pas de conflit)
        from config.market_selection import get_hints_confidence_boost
        boost = get_hints_confidence_boost()
        logger.info(
            "Market selection: hints_detected=YES, symbol=%s, timeframe=%s, boost=+%.2f confidence",
            hinted_symbol or "NONE",
            hinted_timeframe or "NONE",
            boost if (hinted_symbol or hinted_timeframe) else 0.0,
        )

    system_msg = LLMMessage(
        role="system",
        content=(
            "Tu es un analyste quant. Choisis UN seul couple symbole/timeframe "
            "le plus pertinent pour l'objectif. Réponds en JSON strict uniquement."
        ),
    )
    # Enrichissement : recommandations TF/token basées sur type de stratégie détecté
    strategy_hints = ""
    try:
        if detected_strategy_type:
            from config.market_selection import get_strategy_requirements

            reqs = get_strategy_requirements(detected_strategy_type)
            recommended_tfs = reqs.get("timeframes", ["1h"])

            # Extraire top 5 tokens recommandés (déjà triés par rank_tokens_for_strategy)
            top_tokens = shuffled_symbols[:5]

            strategy_hints = (
                f"\n📊 RECOMMANDATION STRATÉGIE: **{detected_strategy_type.replace('_', ' ').title()}** détecté\n"
                f"  → TFs optimaux: {', '.join(recommended_tfs[:3])}\n"
                f"  → Tokens candidats pertinents (ordre mélangé): {', '.join(top_tokens)}\n"
                "  → IMPORTANT: Ne choisis PAS automatiquement le premier token de la liste.\n"
                "    Évalue l'adéquation avec l'objectif + la diversité récente.\n"
            )
    except Exception:
        pass  # Si détection échoue, continuer sans hints

    user_msg = LLMMessage(
        role="user",
        content=(
            "Objectif:\n"
            f"{clean_objective}\n\n"
            "Contraintes:\n"
            f"- symbol MUST be one of: {', '.join(shuffled_symbols)}\n"
            f"- timeframe MUST be one of: {', '.join(shuffled_timeframes)}\n"
            "- Anti-biais de position: ne sélectionne PAS automatiquement le premier élément des listes.\n"
            "- Si plusieurs choix sont valides, privilégie un couple moins récent (diversité).\n"
            f"{strategy_hints}"
            f"{objective_hint_instruction}\n"
            "- Retourne un JSON strict, sans markdown:\n"
            '{"symbol":"...","timeframe":"...","confidence":0.0,"reason":"..."}\n'
            f"- confidence doit être entre 0 et 1.{diversity_instruction}"
        ),
    )

    try:
        if stream_callback and hasattr(llm_client, "chat_stream"):
            raw = llm_client.chat_stream(
                [system_msg, user_msg],
                on_chunk=lambda c: stream_callback("market_pick", c),
                max_tokens=180,
            )
        else:
            raw = llm_client.chat([system_msg, user_msg], max_tokens=180)
        # Extraire .content si LLMResponse, sinon str()
        raw_text = str(getattr(raw, "content", raw) or "").strip()
    except Exception as exc:
        logger.warning("recommend_market_context: fallback exception=%s", exc)
        return {
            "symbol": fallback_symbol,
            "timeframe": fallback_timeframe,
            "confidence": 0.0,
            "reason": f"Échec appel LLM ({exc}). Fallback appliqué.",
            "source": "fallback_exception",
        }

    payload = _extract_json_from_response(raw_text)
    symbol = str(payload.get("symbol", "")).strip().upper()
    timeframe = str(payload.get("timeframe", "")).strip()

    try:
        confidence = float(payload.get("confidence", 0.5))
    except Exception:
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    reason = str(payload.get("reason", "") or "").strip()

    source = "llm"
    if symbol not in symbols:
        source = "fallback_out_of_universe"
        symbol = strict_fallback_symbol
    if timeframe not in timeframes:
        source = "fallback_out_of_universe"
        timeframe = strict_fallback_timeframe

    if not payload:
        source = "fallback_invalid_json"
        symbol = strict_fallback_symbol
        timeframe = strict_fallback_timeframe
        confidence = 0.0
        if not reason:
            reason = "Réponse LLM non parseable en JSON. Fallback appliqué."
    # Évite de rester figé sur le même couple déjà utilisé récemment.
    if recent_markets:
        recent_order = [
            (str(s or "").upper(), str(tf or "").strip())
            for s, tf in recent_markets
            if str(s or "").strip() and str(tf or "").strip()
        ]
        recent_pairs = set(recent_order)
        all_pairs = [(s, tf) for s in symbols for tf in timeframes]
        selected_pair = (symbol, timeframe)

        if selected_pair in recent_pairs and len(all_pairs) > 1:
            alternatives = [p for p in all_pairs if p not in recent_pairs]
            candidate_pool = alternatives

            # Si tout l'univers a déjà été vu, forcer une rotation sur le moins récent.
            if not candidate_pool:
                last_seen: Dict[Tuple[str, str], int] = {p: -1 for p in all_pairs}
                for idx, pair in enumerate(recent_order):
                    if pair in last_seen:
                        last_seen[pair] = idx
                candidate_pool = sorted(
                    [p for p in all_pairs if p != selected_pair],
                    key=lambda p: (last_seen.get(p, -1), p[0], p[1]),
                )

            preferred = candidate_pool
            if hinted_symbol and hinted_timeframe:
                same_symbol = [p for p in candidate_pool if p[0] == hinted_symbol]
                same_timeframe = [p for p in candidate_pool if p[1] == hinted_timeframe]
                preferred = same_symbol or same_timeframe or candidate_pool
            elif hinted_symbol:
                by_symbol = [p for p in candidate_pool if p[0] == hinted_symbol]
                preferred = by_symbol or candidate_pool
            elif hinted_timeframe:
                by_timeframe = [p for p in candidate_pool if p[1] == hinted_timeframe]
                preferred = by_timeframe or candidate_pool

            if preferred:
                symbol, timeframe = random.choice(preferred)
                source = f"{source}_diversity_override" if source != "llm" else "llm_diversity_override"
                confidence = min(confidence, 0.75)
                if reason:
                    reason = (
                        f"{reason} Couple récent évité automatiquement "
                        f"({selected_pair[0]} {selected_pair[1]})."
                    )
                else:
                    reason = (
                        f"Couple récent évité automatiquement "
                        f"({selected_pair[0]} {selected_pair[1]})."
                    )

    # Bonus léger si le LLM choisit spontanément les hints de l'objectif,
    # sans les forcer pour préserver la diversité multi-market.
    hint_matches: List[str] = []
    if hinted_symbol and symbol == hinted_symbol:
        hint_matches.append(f"symbol={hinted_symbol}")
    if hinted_timeframe and timeframe == hinted_timeframe:
        hint_matches.append(f"timeframe={hinted_timeframe}")
    if hint_matches:
        source = "llm_with_objective_hint" if source == "llm" else source
        confidence = max(confidence, 0.8)
        matched = ", ".join(hint_matches)
        if reason:
            reason = f"{reason} Hints objectif alignés ({matched})."
        else:
            reason = f"Hints objectif alignés ({matched})."

    if not reason:
        if source == "llm":
            reason = "Choix basé sur style de stratégie, volatilité attendue et fréquence des signaux."
        else:
            reason = "Choix par défaut suite à une réponse LLM non exploitable."
    if len(reason) > 280:
        reason = reason[:280].rstrip()

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "confidence": confidence,
        "reason": reason,
        "source": source,
    }


# ---------------------------------------------------------------------------
# Public wrapper – catalog integration
# ---------------------------------------------------------------------------

def compile_proposal_to_code(proposal: Dict[str, Any], variant: int = 0) -> str:
    """Compile un proposal JSON en code Python stratégie exécutable.

    Wrapper public autour de _build_deterministic_fallback_code, destiné
    au module catalog.gating pour le mini-backtest sans LLM.
    """
    return _build_deterministic_fallback_code(proposal, variant=variant)


# ---------------------------------------------------------------------------
# Parametric catalog — bridge avec le module catalog/
# ---------------------------------------------------------------------------

_PARAMETRIC_VARIANTS: Optional[List[Dict[str, Any]]] = None
_PARAMETRIC_INDEX: int = 0
_PARAMETRIC_SEED_USED: Optional[int] = None
_PARAMETRIC_DSL_OPERAND = r"[A-Za-z0-9_.]+"
_PARAMETRIC_FORBIDDEN_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("crosses", re.compile(r"\bcrosses\b", re.IGNORECASE)),
    (".iloc[", re.compile(r"\.iloc\s*\[", re.IGNORECASE)),
    ("df[", re.compile(r"\bdf\s*\[", re.IGNORECASE)),
    ("shift(", re.compile(r"\bshift\s*\(", re.IGNORECASE)),
    ("future", re.compile(r"\bfuture\b", re.IGNORECASE)),
    ("repaint", re.compile(r"\brepaint\w*\b", re.IGNORECASE)),
)


def _resolve_parametric_seed(seed: Optional[int]) -> int:
    """Résout un seed stable: explicite si fourni, sinon aléatoire par session."""
    if seed is None:
        return random.SystemRandom().randrange(1, 2**31 - 1)
    return int(seed)


def _shuffle_parametric_variants(variants: List[Dict[str, Any]], seed: int) -> None:
    """Mélange les variants de façon reproductible pour un seed donné."""
    if len(variants) < 2:
        return
    rng = random.Random(seed)
    rng.shuffle(variants)


def _normalize_cross_syntax(text: str) -> str:
    """Normalise les tokens "crosses" en helpers DSL non ambigus."""
    if not text:
        return ""

    normalized = str(text)

    # Legacy aliases -> contrat unique.
    normalized = re.sub(r"\bcross_above\s*\(", "cross_up(", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bcross_below\s*\(", "cross_down(", normalized, flags=re.IGNORECASE)

    # "x crosses above y" / "x crosses below y"
    normalized = re.sub(
        rf"\b({_PARAMETRIC_DSL_OPERAND})\s+crosses\s+above\s+({_PARAMETRIC_DSL_OPERAND})\b",
        r"cross_up(\1, \2)",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        rf"\b({_PARAMETRIC_DSL_OPERAND})\s+crosses\s+below\s+({_PARAMETRIC_DSL_OPERAND})\b",
        r"cross_down(\1, \2)",
        normalized,
        flags=re.IGNORECASE,
    )

    # "x crosses_above y" / "x crosses_below y"
    normalized = re.sub(
        rf"\b({_PARAMETRIC_DSL_OPERAND})\s+crosses_above\s+({_PARAMETRIC_DSL_OPERAND})\b",
        r"cross_up(\1, \2)",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        rf"\b({_PARAMETRIC_DSL_OPERAND})\s+crosses_below\s+({_PARAMETRIC_DSL_OPERAND})\b",
        r"cross_down(\1, \2)",
        normalized,
        flags=re.IGNORECASE,
    )

    # "x crosses y" -> cross_any(x, y)
    normalized = re.sub(
        rf"\b({_PARAMETRIC_DSL_OPERAND})\s+crosses\s+({_PARAMETRIC_DSL_OPERAND})\b",
        r"cross_any(\1, \2)",
        normalized,
        flags=re.IGNORECASE,
    )

    return normalized


def _scan_forbidden_parametric_tokens(text: str) -> List[str]:
    """Retourne les tokens interdits détectés dans un texte de variant."""
    if not text:
        return []
    found: List[str] = []
    for token, pattern in _PARAMETRIC_FORBIDDEN_PATTERNS:
        if pattern.search(text):
            found.append(token)
    return found


def _remove_hardcoded_tokens(text: str) -> str:
    """
    Retire les tokens crypto hardcodés d'un objectif (ex: "0GUSDC", "BTCUSDC").

    Remplace les patterns comme:
    - "sur 0GUSDC en" → "sur crypto en"
    - "sur BTCUSDC dans" → "sur crypto dans"
    - "[Momentum] sur 0GUSDC" → "[Momentum] sur crypto"

    Utilisé quand symbol=None pour permettre sélection LLM intelligente.
    """
    if not text:
        return text

    # Pattern : tokens crypto (XXXXXUSDC où XXXXX = lettres/chiffres)
    # Exemples : 0GUSDC, BTCUSDC, ETHUSDC, 1000SATSUSDC, etc.
    token_pattern = r'\b[A-Z0-9]{2,12}USDC\b'

    # Remplacer "sur TOKEN en/dans/..." par "sur crypto en/dans/..."
    text = re.sub(
        rf'sur\s+{token_pattern}\s+(en|dans|avec|pour)',
        r'sur crypto \1',
        text,
        flags=re.IGNORECASE
    )

    # Remplacer "TOKEN en/dans" restants par "crypto en/dans"
    text = re.sub(
        rf'{token_pattern}\s+(en|dans)',
        r'crypto \1',
        text,
        flags=re.IGNORECASE
    )

    # Filet final : remplace tout token crypto restant (ex: "sur BTCUSDC.")
    text = re.sub(
        token_pattern,
        'crypto',
        text,
        flags=re.IGNORECASE
    )

    # Nettoyer les doubles espaces
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def _remove_hardcoded_timeframes(text: str) -> str:
    """
    Retire les timeframes hardcodés d'un objectif (ex: "1h", "30m", "5m").

    Remplace les patterns comme:
    - "en 1h" → "en timeframe adapté"
    - "dans les 5m" → "dans un timeframe court"
    - "crypto 30m" → "crypto"

    Utilisé quand timeframe=None pour permettre sélection LLM intelligente.
    """
    if not text:
        return text

    # Pattern : timeframes (1m, 5m, 15m, 30m, 1h, 4h, 1d, etc.)
    tf_pattern = r'\b\d+[mhdwM]\b'

    # Remplacer "en/dans [TF]" par une description générique
    text = re.sub(
        rf'(en|dans)\s+(les?\s+)?{tf_pattern}',
        r'\1 timeframe adapté',
        text,
        flags=re.IGNORECASE
    )

    # Remplacer TF isolés restants
    text = re.sub(
        rf'\s+{tf_pattern}\b',
        '',
        text,
        flags=re.IGNORECASE
    )

    # Nettoyer les doubles espaces
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def normalize_variant_for_builder(
    variant: Any,
    *,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    run_id: str = "",
) -> Optional[Dict[str, Any]]:
    """Normalise et valide un variant paramétrique pour injection Builder."""
    raw: Dict[str, Any]
    if isinstance(variant, dict):
        raw = dict(variant)
    elif hasattr(variant, "to_dict") and callable(getattr(variant, "to_dict")):
        raw = cast(Dict[str, Any], variant.to_dict())
    else:
        raw = {
            "variant_id": str(getattr(variant, "variant_id", "") or ""),
            "archetype_id": str(getattr(variant, "archetype_id", "") or ""),
            "param_pack_id": str(getattr(variant, "param_pack_id", "") or ""),
            "params": getattr(variant, "params", {}) or {},
            "proposal": getattr(variant, "proposal", {}) or {},
            "builder_text": str(getattr(variant, "builder_text", "") or ""),
            "fingerprint": str(getattr(variant, "fingerprint", "") or ""),
            "provenance": getattr(variant, "provenance", {}) or {},
        }

    proposal = raw.get("proposal", {})
    if not isinstance(proposal, dict):
        proposal = {}
    proposal = dict(proposal)
    for field_name in ("entry_long_logic", "entry_short_logic", "exit_logic"):
        val = proposal.get(field_name, "")
        if isinstance(val, str) and val.strip():
            proposal[field_name] = _normalize_cross_syntax(val)

    builder_text = str(raw.get("builder_text", "") or "")
    if not builder_text and proposal:
        try:
            from catalog.builder_export import to_text_v1
            builder_text = to_text_v1(proposal)
        except Exception:
            builder_text = ""
    builder_text = _normalize_cross_syntax(builder_text)

    if symbol is not None:
        builder_text = builder_text.replace("{symbol}", str(symbol))
    else:
        # symbol=None → Retirer les tokens hardcodés pour permettre sélection LLM intelligente
        builder_text = _remove_hardcoded_tokens(builder_text)

    if timeframe is not None:
        builder_text = builder_text.replace("{timeframe}", str(timeframe))
    else:
        # timeframe=None → Retirer les TF hardcodés pour permettre sélection LLM intelligente
        builder_text = _remove_hardcoded_timeframes(builder_text)

    objective_text = sanitize_objective_text(builder_text)
    if not objective_text:
        objective_text = builder_text.strip()

    issues: List[str] = []
    for field_name in ("entry_long_logic", "entry_short_logic", "exit_logic"):
        issues.extend(
            f"{field_name}:{token}"
            for token in _scan_forbidden_parametric_tokens(str(proposal.get(field_name, "") or ""))
        )
    issues.extend(f"builder_text:{token}" for token in _scan_forbidden_parametric_tokens(builder_text))
    issues.extend(f"objective_text:{token}" for token in _scan_forbidden_parametric_tokens(objective_text))
    if not objective_text.strip():
        issues.append("objective_text:empty")

    if issues:
        logger.warning(
            "parametric_variant_rejected variant_id=%s issues=%s",
            raw.get("variant_id", ""),
            ",".join(issues),
        )
        return None

    provenance = raw.get("provenance", {})
    if not isinstance(provenance, dict):
        provenance = {}
    resolved_run_id = (
        str(run_id or "").strip()
        or str(raw.get("run_id", "") or "").strip()
        or str(provenance.get("run_id", "") or "").strip()
    )

    return {
        "run_id": resolved_run_id,
        "variant_id": str(raw.get("variant_id", "") or ""),
        "archetype_id": str(raw.get("archetype_id", "") or ""),
        "param_pack_id": str(raw.get("param_pack_id", "") or ""),
        "params": raw.get("params", {}) if isinstance(raw.get("params", {}), dict) else {},
        "proposal": proposal,
        "builder_text": builder_text,
        "fingerprint": str(raw.get("fingerprint", "") or ""),
        "objective_text": objective_text,
    }


def generate_parametric_catalog(
    config_path: Optional[str] = None,
    n_variants: int = 200,
    seed: Optional[int] = None,
) -> int:
    """Génère le catalogue paramétrique et le stocke en mémoire.

    Args:
        config_path: Chemin vers un CatalogConfig JSON. Si None, utilise
            les archetypes/param_packs par défaut du module catalog.
        n_variants: Nombre de variants cible (ignoré si config_path fourni).
        seed: Seed explicite pour reproductibilité. Si None, seed aléatoire
            (pour diversifier les sessions autonomes au redémarrage).

    Returns:
        Nombre de variants générés et valides.
    """
    global _PARAMETRIC_VARIANTS, _PARAMETRIC_INDEX, _PARAMETRIC_SEED_USED

    from catalog.chainer import generate_catalog
    from catalog.models import CatalogConfig

    if config_path:
        from pathlib import Path
        config = CatalogConfig.load(Path(config_path))
        resolved_seed = int(getattr(config, "seed", 42) or 42)
    else:
        resolved_seed = _resolve_parametric_seed(seed)
        config = CatalogConfig(
            seed=resolved_seed,
            n_variants_target=n_variants,
            batch_size=50,
            archetypes_dir="catalog/archetypes",
            param_packs_dir="catalog/param_packs",
        )
    if not str(getattr(config, "run_id", "") or "").strip():
        config.run_id = f"parametric_{generate_run_id()}"

    result = generate_catalog(config)

    normalized_variants: List[Dict[str, Any]] = []
    bridge_rejected = 0
    for variant in result.variants:
        normalized = normalize_variant_for_builder(
            variant,
            run_id=str(result.run_id or "").strip(),
        )
        if normalized is None:
            bridge_rejected += 1
            continue
        normalized_variants.append(normalized)

    _shuffle_parametric_variants(normalized_variants, seed=resolved_seed)
    _PARAMETRIC_VARIANTS = normalized_variants
    _PARAMETRIC_INDEX = 0
    _PARAMETRIC_SEED_USED = resolved_seed

    logger.info(
        "parametric_catalog_generated total=%d after_sanity=%d after_bridge=%d bridge_rejected=%d seed=%d",
        result.total_generated,
        len(result.variants),
        len(normalized_variants),
        bridge_rejected,
        resolved_seed,
    )
    return len(normalized_variants)


def get_next_parametric_objective(
    symbol: "str | List[str]" = "BTCUSDC",
    timeframe: "str | List[str]" = "1h",
) -> Optional[Dict[str, Any]]:
    """Retourne un objectif paramétrique structuré pour le prochain variant.

    Si le catalogue n'est pas encore généré, le génère automatiquement.
    Quand tous les variants ont été consommés, recommence (cycle).

    Returns:
        Dict structuré (incluant objective_text + métadonnées variant) ou None.
    """
    global _PARAMETRIC_VARIANTS, _PARAMETRIC_INDEX

    if _PARAMETRIC_VARIANTS is None:
        count = generate_parametric_catalog()
        if count == 0:
            return None

    if not _PARAMETRIC_VARIANTS:
        return None

    # Résoudre symbol/timeframe
    if isinstance(symbol, list):
        sym = random.choice(symbol) if symbol else "BTCUSDC"
    else:
        sym = symbol
    if isinstance(timeframe, list):
        tf = random.choice(timeframe) if timeframe else "1h"
    else:
        tf = timeframe

    # Sélection du variant courant (cycle) + sanity d'injection.
    attempts = len(_PARAMETRIC_VARIANTS)
    while attempts > 0:
        raw_variant = _PARAMETRIC_VARIANTS[_PARAMETRIC_INDEX % len(_PARAMETRIC_VARIANTS)]
        _PARAMETRIC_INDEX += 1
        attempts -= 1

        normalized = normalize_variant_for_builder(
            raw_variant,
            symbol=str(sym),
            timeframe=str(tf),
        )
        if normalized is not None:
            return normalized

    logger.warning("parametric_catalog_empty_after_injection_sanity")
    return None


def get_parametric_catalog_stats() -> Dict[str, Any]:
    """Retourne les statistiques du catalogue paramétrique."""
    if _PARAMETRIC_VARIANTS is None:
        return {"generated": False, "total": 0, "index": 0, "seed": _PARAMETRIC_SEED_USED}
    return {
        "generated": True,
        "total": len(_PARAMETRIC_VARIANTS),
        "index": _PARAMETRIC_INDEX,
        "coverage_pct": min(100.0, (_PARAMETRIC_INDEX / max(1, len(_PARAMETRIC_VARIANTS))) * 100),
        "seed": _PARAMETRIC_SEED_USED,
    }


def reset_parametric_catalog() -> None:
    """Reset le catalogue paramétrique (force re-génération au prochain appel)."""
    global _PARAMETRIC_VARIANTS, _PARAMETRIC_INDEX, _PARAMETRIC_SEED_USED
    _PARAMETRIC_VARIANTS = None
    _PARAMETRIC_INDEX = 0
    _PARAMETRIC_SEED_USED = None
    logger.info("parametric_catalog_reset")
