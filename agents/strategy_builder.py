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
import builtins
import concurrent.futures
import csv
import importlib.util
import json
import math
import os
import pprint
import random
import re
import sys
import threading
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
from agents.indicator_context import (
    build_indicator_selection_guide,
    get_indicator_builder_access_example,
    get_indicator_builder_stable_alias_map,
    rank_indicator_selection,
)
from backtest.engine import BacktestEngine
from backtest.result_store import get_builder_sessions_dir
from indicators.registry import list_indicators
from metrics_types import normalize_metrics
from utils.observability import generate_run_id, get_obs_logger
from utils.template import render_prompt

from agents.thought_stream import ThoughtStream

logger = get_obs_logger(__name__)

# Dossier racine des sandbox
SANDBOX_ROOT = get_builder_sessions_dir()

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
    "pre": _LLM_PHASE_TIMEOUT_ANALYSIS,
}


def _is_interpreter_shutdown_runtime_error(exc: BaseException) -> bool:
    """Détecte le RuntimeError typique émis pendant l'arrêt de l'interpréteur."""
    if not isinstance(exc, RuntimeError):
        return False
    message = str(exc).lower()
    return (
        "interpreter shutdown" in message
        or "cannot schedule new futures after interpreter shutdown" in message
    )


def _get_streamlit_script_run_ctx() -> Any:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx()
    except (ImportError, AttributeError):
        return None


def _attach_streamlit_ctx_to_current_thread(st_ctx: Any) -> None:
    """Attache le ScriptRunContext au thread worker courant."""
    if st_ctx is None:
        return
    try:
        from streamlit.runtime.scriptrunner import add_script_run_ctx

        add_script_run_ctx(threading.current_thread(), st_ctx)
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
        pass


def _new_streamlit_aware_thread_pool(max_workers: int = 1) -> concurrent.futures.ThreadPoolExecutor:
    """Crée un pool compatible Streamlit pour éviter le spam ScriptRunContext."""
    st_ctx = _get_streamlit_script_run_ctx()
    if st_ctx is None:
        return concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    return concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers,
        initializer=_attach_streamlit_ctx_to_current_thread,
        initargs=(st_ctx,),
    )


SAFE_PATH_MODE_ENV = "BACKTEST_BUILDER_SAFE_PATH"

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
    "amplitude_hunter",
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
    "fvg",
    "swing",
    "smart_legs",
    "directional_bias",
    "markov_switching",
}

_DICT_INDICATOR_ALLOWED_KEYS: Dict[str, set[str]] = {
    "bollinger": {"upper", "middle", "lower"},
    "macd": {"macd", "signal", "histogram"},
    "stochastic": {"stoch_k", "stoch_d"},
    "adx": {"adx", "plus_di", "minus_di"},
    "amplitude_hunter": {"range_pct", "score"},
    "supertrend": {"supertrend", "direction"},
    "ichimoku": {"tenkan", "kijun", "senkou_a", "senkou_b", "chikou", "cloud_position"},
    "psar": {"sar", "trend", "signal"},
    "vortex": {"vi_plus", "vi_minus", "signal", "oscillator"},
    "stoch_rsi": {"k", "d", "signal"},
    "aroon": {"aroon_up", "aroon_down"},
    "donchian": {"upper", "middle", "lower"},
    "keltner": {"middle", "upper", "lower"},
    "pivot_points": {"pivot", "r1", "s1", "r2", "s2", "r3", "s3"},
    "fibonacci_levels": {"high", "low"},
    "fvg": {"fvg_bullish", "fvg_bearish"},
    "swing": {"swing_high", "swing_low"},
    "smart_legs": {"smart_leg_bullish", "smart_leg_bearish"},
    "directional_bias": {"bull_score", "bear_score", "net_bias"},
    "markov_switching": {"regime", "prob_regime_0", "prob_regime_1", "prob_regime_2", "prob_regime_3"},
}

_INDICATOR_ALIAS_HINTS = {
    "bollinger_upper": "indicators['bollinger']['upper']",
    "bollinger_middle": "indicators['bollinger']['middle']",
    "bollinger_lower": "indicators['bollinger']['lower']",
    "upper_bollinger": "indicators['bollinger']['upper']",
    "middle_bollinger": "indicators['bollinger']['middle']",
    "mid_bollinger": "indicators['bollinger']['middle']",
    "lower_bollinger": "indicators['bollinger']['lower']",
    "higher_bollinger": "indicators['bollinger']['upper']",
    "midline_bollinger": "indicators['bollinger']['middle']",
    "bb_upper": "indicators['bollinger']['upper']",
    "bb_middle": "indicators['bollinger']['middle']",
    "bb_lower": "indicators['bollinger']['lower']",
    "bb_mid": "indicators['bollinger']['middle']",
    "bb_std": "indicators['bollinger']['upper']",
    "macd_line": "indicators['macd']['macd']",
    "macd_signal": "indicators['macd']['signal']",
    "macd_histogram": "indicators['macd']['histogram']",
    "keltner_upper": "indicators['keltner']['upper']",
    "keltner_middle": "indicators['keltner']['middle']",
    "keltner_lower": "indicators['keltner']['lower']",
    "kelt_upper": "indicators['keltner']['upper']",
    "kelt_middle": "indicators['keltner']['middle']",
    "kelt_lower": "indicators['keltner']['lower']",
    "donchian_upper": "indicators['donchian']['upper']",
    "donchian_middle": "indicators['donchian']['middle']",
    "donchian_lower": "indicators['donchian']['lower']",
    "dc_upper": "indicators['donchian']['upper']",
    "dc_middle": "indicators['donchian']['middle']",
    "dc_lower": "indicators['donchian']['lower']",
    "cci_value": "indicators['cci']",
    "cci_values": "indicators['cci']",
    "ichimoku_tenkan": "indicators['ichimoku']['tenkan']",
    "ichimoku_kijun": "indicators['ichimoku']['kijun']",
    "ichimoku_senkou_a": "indicators['ichimoku']['senkou_a']",
    "ichimoku_senkou_b": "indicators['ichimoku']['senkou_b']",
    "ichimoku_chikou": "indicators['ichimoku']['chikou']",
    "ichimoku_cloud": "indicators['ichimoku']['cloud_position']",
    "psar_sar": "indicators['psar']['sar']",
    "psar_trend": "indicators['psar']['trend']",
    "psar_signal": "indicators['psar']['signal']",
    "parabolic_sar": "indicators['psar']['sar']",
    "vortex_vi_plus": "indicators['vortex']['vi_plus']",
    "vortex_vi_minus": "indicators['vortex']['vi_minus']",
    "vortex_signal": "indicators['vortex']['signal']",
    "vortex_oscillator": "indicators['vortex']['oscillator']",
    "vi_plus": "indicators['vortex']['vi_plus']",
    "vi_minus": "indicators['vortex']['vi_minus']",
    "aroon_up": "indicators['aroon']['aroon_up']",
    "aroon_down": "indicators['aroon']['aroon_down']",
    "aroon_upper": "indicators['aroon']['aroon_up']",
    "aroon_lower": "indicators['aroon']['aroon_down']",
    "pivot_points_pivot": "indicators['pivot_points']['pivot']",
    "pivot_points_r1": "indicators['pivot_points']['r1']",
    "pivot_points_s1": "indicators['pivot_points']['s1']",
    "pivot_points_r2": "indicators['pivot_points']['r2']",
    "pivot_points_s2": "indicators['pivot_points']['s2']",
    "pivot_points_r3": "indicators['pivot_points']['r3']",
    "pivot_points_s3": "indicators['pivot_points']['s3']",
    "adx_value": "indicators['adx']['adx']",
    "plus_di": "indicators['adx']['plus_di']",
    "minus_di": "indicators['adx']['minus_di']",
    "supertrend_value": "indicators['supertrend']['supertrend']",
    "supertrend_direction": "indicators['supertrend']['direction']",
    "stoch_k": "indicators['stochastic']['stoch_k']",
    "stoch_d": "indicators['stochastic']['stoch_d']",
    "stoch_rsi_k": "indicators['stoch_rsi']['k']",
    "stoch_rsi_d": "indicators['stoch_rsi']['d']",
    "stoch_rsi_signal": "indicators['stoch_rsi']['signal']",
    "srsi_k": "indicators['stoch_rsi']['k']",
    "srsi_d": "indicators['stoch_rsi']['d']",
    "fibonacci_levels_high": "indicators['fibonacci_levels']['high']",
    "fibonacci_levels_low": "indicators['fibonacci_levels']['low']",
}

_SEMANTIC_INDICATOR_ALIAS_HINTS = {
    "upper_bollinger": "indicators['bollinger']['upper']",
    "middle_bollinger": "indicators['bollinger']['middle']",
    "mid_bollinger": "indicators['bollinger']['middle']",
    "lower_bollinger": "indicators['bollinger']['lower']",
    "higher_bollinger": "indicators['bollinger']['upper']",
    "midline_bollinger": "indicators['bollinger']['middle']",
}

_INDICATOR_ACCESS_REWRITE_HINTS = {
    "adx_d": "indicators['adx']",
    "bear_score": "indicators['directional_bias']['bear_score']",
    "bb": "indicators['bollinger']",
    "bull_score": "indicators['directional_bias']['bull_score']",
    "donchian_band": "indicators['donchian']",
    "directional_bias_net": "indicators['directional_bias']['net_bias']",
    "fib_levels": "indicators['fibonacci_levels']",
    "fibonacci": "indicators['fibonacci_levels']",
    "klt": "indicators['keltner']",
    "net_bias": "indicators['directional_bias']['net_bias']",
    "obvi": "indicators['obv']",
    "plus_di": "indicators['adx']['plus_di']",
    "minus_di": "indicators['adx']['minus_di']",
    "aroon_up": "indicators['aroon']['aroon_up']",
    "aroon_down": "indicators['aroon']['aroon_down']",
    "pivot": "indicators['pivot_points']['pivot']",
    "st_direction": "indicators['supertrend']['direction']",
    "direction": "indicators['supertrend']['direction']",
    "rsi_arr": "indicators['rsi']",
    "rsi_data": "indicators['rsi']",
    "atr_14": "indicators['atr']",
    "volume_osc": "indicators['volume_oscillator']",
}

_PARAM_ACCESS_REWRITE_HINTS = {
    "warmup": "params.get('warmup', 50)",
    "leverage": "params.get('leverage', 1)",
    "atr_period": "params.get('atr_period', 14)",
    "stop_atr_mult": "params.get('stop_atr_mult', 1.5)",
    "tp_atr_mult": "params.get('tp_atr_mult', 3.0)",
    "sl_factor": "params.get('stop_atr_mult', 1.5)",
    "tp_factor": "params.get('tp_atr_mult', 3.0)",
}

_INDICATOR_CANONICAL_ALIASES = {
    "adx_value": "adx",
    "bear_score": "directional_bias",
    "bbands": "bollinger",
    "bull_score": "directional_bias",
    "directional_bias_net": "directional_bias",
    "fib_level": "fibonacci_levels",
    "fib_levels": "fibonacci_levels",
    "fibonacci": "fibonacci_levels",
    "fibonacci_level": "fibonacci_levels",
    "keltner_channel": "keltner",
    "klt": "keltner",
    "net_bias": "directional_bias",
    "obvi": "obv",
    "pivot": "pivot_points",
    "pivot_point": "pivot_points",
    "pivotpoints": "pivot_points",
    "pivots": "pivot_points",
    "rsci": "rsi",
    "stochrsi": "stoch_rsi",
    "super_trend": "supertrend",
    "vol_oscillator": "volume_oscillator",
    "volume_osc": "volume_oscillator",
    "volumeoscillator": "volume_oscillator",
    "williams": "williams_r",
    "williamsr": "williams_r",
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
_PYTHONISH_LINE_RE = re.compile(
    r"^\s*(from\s+|import\s+|class\s+|def\s+|@|if\s+|elif\s+|else\s*:|for\s+|while\s+|try\s*:|except\b|finally\s*:|return\b|signals\b|[A-Za-z_][A-Za-z0-9_]*\s*=)",
    re.IGNORECASE,
)
_NATURAL_LANGUAGE_LINE_RE = re.compile(
    r"^\s*(voici|here(?: is)?|sure|corrected code|explication|explanation|note|remarque|analyse|analysis|résumé|resume|stratégie|strategy)\b",
    re.IGNORECASE,
)

_AST_PARSE_RECOVERABLE_EXCEPTIONS = (
    SyntaxError,
    ValueError,
    KeyError,
    RuntimeError,
    AttributeError,
    TypeError,
    IndexError,
)


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
    - Interdit l'indexation 2D sur `signals` (Series 1D uniquement)
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
                    is_signals_loc_sub = (
                        isinstance(tgt.value, ast.Attribute)
                        and tgt.value.attr == "loc"
                        and isinstance(tgt.value.value, ast.Name)
                        and tgt.value.value.id == "signals"
                    )
                    is_signals_iloc_sub = (
                        isinstance(tgt.value, ast.Attribute)
                        and tgt.value.attr == "iloc"
                        and isinstance(tgt.value.value, ast.Name)
                        and tgt.value.value.id == "signals"
                    )
                    if not (is_signals_sub or is_signals_loc_sub or is_signals_iloc_sub):
                        continue

                    sl = tgt.slice
                    if isinstance(sl, ast.Tuple):
                        return False, _err(
                            ERR_SIG,
                            "Indexation 2D interdite sur `signals`: cette variable doit "
                            "rester une `pd.Series` 1D. Ne jamais écrire "
                            "`signals.loc[mask, 'long'/'short']`; utiliser "
                            "`signals[long_mask] = 1.0` et `signals[short_mask] = -1.0`.",
                        )
                    if isinstance(sl, ast.Slice):
                        lower = _const_value(sl.lower) if sl.lower is not None else None
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
            core_names: tuple[str, ...] = ("df", "indicators", "params")
            if item.name == "generate_signals":
                core_names: tuple[str, ...] = ("df", "indicators", "params", "warmup")
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

    # 3e. NameError probable: indicateur enregistré utilisé comme variable nue
    #     sans alias local explicite depuis indicators['...'].
    known_indicator_names = _get_known_indicator_names()
    if known_indicator_names:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name != GENERATED_CLASS_NAME:
                continue
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if item.name != "generate_signals":
                    continue
                arg_names = {a.arg for a in item.args.args}
                arg_names.update(a.arg for a in item.args.kwonlyargs)
                load_names, _store_names = _collect_name_load_store_sets(item)
                bound_names = _collect_bound_names(item)
                missing_indicators = sorted(
                    {
                        name
                        for name in load_names
                        if name in known_indicator_names
                        and name not in arg_names
                        and name not in bound_names
                    }
                )
                if missing_indicators:
                    indicator_name = missing_indicators[0]
                    return (
                        False,
                        _err(
                            ERR_IND,
                            "NameError probable: indicateur "
                            f"`{indicator_name}` utilisé comme variable nue dans "
                            "`generate_signals` sans alias local. "
                            f"{_indicator_access_hint(indicator_name)}",
                        ),
                    )
            break

    # 3e-bis. Variables libres / placeholders explicites dans les méthodes.
    module_bound_names = _collect_module_level_bound_names(tree)
    builtin_names = set(dir(builtins))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != GENERATED_CLASS_NAME:
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(item):
                if isinstance(sub, ast.Constant) and sub.value is Ellipsis:
                    return (
                        False,
                        _err(
                            ERR_AST,
                            f"Placeholder `...` interdit dans `{item.name}`. "
                            "Fournir une logique complète.",
                        ),
                    )
            load_names, _store_names = _collect_name_load_store_sets(item)
            bound_names = _collect_bound_names(item)
            allowed_names = bound_names | module_bound_names | builtin_names
            missing_names = sorted(
                {
                    name
                    for name in load_names
                    if name not in allowed_names and not name.startswith("__")
                }
            )
            if missing_names:
                missing_name = missing_names[0]
                return (
                    False,
                    _err(
                        ERR_CLASS,
                        f"NameError probable: `{missing_name}` utilisé dans "
                        f"`{item.name}` sans définition locale.",
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
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
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
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE).strip()
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
    cleaned = _strip_objective_prompt_leakage(cleaned)
    cleaned = cleaned.strip("`'\" \n\t")
    if len(cleaned) > 4000:
        cleaned = cleaned[:4000].rstrip()
    return cleaned


_OBJECTIVE_PROMPT_SENTENCE_RE = re.compile(
    r"^\s*(?:"
    r"e?vite|"
    r"tu dois|"
    r"le style doit|"
    r"format attendu|"
    r"exemple de format(?: acceptable| correct| rejet[ée])?|"
    r"en tant qu['’]assistant|"
    r"okay, let'?s dive|"
    r"first, i need|"
    r"i need to figure out|"
    r"r[ée]ponse(?: style)?"
    r")\b",
    re.IGNORECASE,
)

_OBJECTIVE_START_PATTERNS = (
    re.compile(r"(Strat[ée]gie(?:\s+de\s+[^.:\n]+)?\s+sur\b.*)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(Objectif(?:\s+de)?\s+Strat[ée]g(?:ique)?(?:\s+de\s+Trading)?\b.*)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(\[[^\]]+\]\s+sur\b.*)", re.IGNORECASE | re.DOTALL),
    re.compile(r"(Objectif\s+sur\b.*)", re.IGNORECASE | re.DOTALL),
)


def _strip_objective_prompt_leakage(text: str) -> str:
    """Retire les restes de méta-consignes quand le LLM recopie le prompt."""
    if not text:
        return ""

    normalized = re.sub(r"[*`#]+", "", str(text or "")).strip()
    if not normalized:
        return ""

    anchored = normalized
    anchor_found = False
    best_start: Optional[int] = None
    best_value = normalized
    for pattern in _OBJECTIVE_START_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        start = match.start(1)
        if best_start is None or start < best_start:
            best_start = start
            best_value = match.group(1).strip()
            anchor_found = True
    anchored = best_value

    kept_sentences: List[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", anchored):
        line = str(sentence or "").strip()
        if not line:
            continue
        if _OBJECTIVE_PROMPT_SENTENCE_RE.match(line):
            continue
        kept_sentences.append(line)

    cleaned = " ".join(kept_sentences).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned:
        return cleaned
    if anchor_found:
        return re.sub(r"\s+", " ", anchored).strip()
    return ""


def _looks_like_prompt_instruction_leakage(text: str) -> bool:
    """Détecte si un objectif ressemble encore à une réponse de prompt contaminée."""
    normalized = str(text or "").strip()
    if not normalized:
        return False
    lower = normalized.lower()
    if "okay, let's dive" in lower or "first, i need" in lower:
        return True
    if "en tant qu'assistant" in lower or "en tant qu’assistant" in lower:
        return True
    if _OBJECTIVE_PROMPT_SENTENCE_RE.match(normalized):
        return True
    return False


def _normalize_llm_text(value: Any, *, fallback: str = "", max_len: int = 1200) -> str:
    """Normalise un payload LLM potentiellement structuré en texte affichable."""
    text = ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, (dict, list, tuple, set)):
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
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
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
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
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
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
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
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


def _canonicalize_indicator_name(
    name: Any,
    *,
    known: Optional[set[str]] = None,
) -> Optional[str]:
    """Ramène les alias fréquents Builder vers un nom d'indicateur du registre."""
    raw = str(name or "").strip().lower()
    if not raw:
        return None

    normalized = raw.replace("-", "_").replace(" ", "_")
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    candidate = _INDICATOR_CANONICAL_ALIASES.get(normalized, normalized)

    if known is None:
        return candidate
    if candidate in known:
        return candidate
    if normalized in known:
        return normalized
    return None


def _binding_info_for_expr(
    node: ast.AST,
    bindings: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Retourne le binding connu pour une expression simple d'indicateur."""
    if isinstance(node, ast.Name):
        return bindings.get(node.id)

    indicator_name = _indicator_name_from_subscript(node)
    if indicator_name is None:
        indicator_name = _indicator_name_from_get_call(node)
    if indicator_name is not None:
        return {
            "kind": "dict" if indicator_name.lower() in _DICT_INDICATOR_NAMES else "array",
            "indicator": indicator_name,
        }

    if _is_np_nan_to_num_call(node) and getattr(node, "args", None):
        parent = _binding_info_for_expr(node.args[0], bindings)
        if parent is None:
            return None
        if parent["kind"] == "dict":
            return {
                "kind": "dict",
                "indicator": parent.get("indicator"),
            }
        return {
            "kind": "array",
            "indicator": parent.get("indicator"),
        }

    return None


def _binding_expr_label(node: ast.AST, binding: Optional[Dict[str, Any]] = None) -> str:
    """Construit un libellé court pour les messages d'erreur AST."""
    if isinstance(node, ast.Name):
        return node.id

    indicator_name = ""
    if binding is not None:
        indicator_name = str(binding.get("indicator") or "")
    if not indicator_name:
        indicator_name = _indicator_name_from_subscript(node) or _indicator_name_from_get_call(node) or ""
    if indicator_name:
        return f"indicators['{indicator_name}']"

    return "indicator expression"


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
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
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
                value_binding = _binding_info_for_expr(node.func.value, bindings)
                if value_binding and value_binding["kind"] == "dict" and attr not in {"get"}:
                    label = _binding_expr_label(node.func.value, value_binding)
                    hint_key = _dict_indicator_allowed_keys_hint(
                        str(value_binding.get("indicator") or label)
                    ).split(",")[0].strip()
                    if hint_key:
                        return (
                            False,
                            f"Usage invalide: `{label}.{attr}(...)` alors que `{label}` est "
                            "un indicator dict. Extraire une sous-clé puis travailler "
                            f"sur le ndarray correspondant (ex: {label}['{hint_key}']).",
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
                    binding = _binding_info_for_expr(operand, bindings)
                    if binding and binding["kind"] == "dict":
                        label = _binding_expr_label(operand, binding)
                        hint_key = _dict_indicator_allowed_keys_hint(
                            str(binding.get("indicator") or label)
                        ).split(",")[0].strip()
                        return (
                            False,
                            f"Usage invalide: comparaison `{label} ...` alors que "
                            f"`{label}` est un indicator dict. Utiliser une sous-clé "
                            f"(ex: {label}['{hint_key}']).",
                        )

            if isinstance(node, ast.BinOp):
                for operand in (node.left, node.right):
                    binding = _binding_info_for_expr(operand, bindings)
                    if binding and binding["kind"] == "dict":
                        label = _binding_expr_label(operand, binding)
                        hint_key = _dict_indicator_allowed_keys_hint(
                            str(binding.get("indicator") or label)
                        ).split(",")[0].strip()
                        return (
                            False,
                            f"Usage invalide: opération arithmétique sur `{label}` "
                            "qui est un indicator dict. Utiliser une sous-clé "
                            f"(ex: {label}['{hint_key}']).",
                        )

                if isinstance(node.op, (ast.BitAnd, ast.BitOr, ast.BitXor)):
                    for operand in (node.left, node.right):
                        binding = _binding_info_for_expr(operand, bindings)
                        if binding and binding["kind"] == "dict":
                            label = _binding_expr_label(operand, binding)
                            hint_key = _dict_indicator_allowed_keys_hint(
                                str(binding.get("indicator") or label)
                            ).split(",")[0].strip()
                            return (
                                False,
                                f"Usage invalide: opérateur logique bitwise appliqué à `{label}` "
                                "qui est un indicator dict. Comparer d'abord une sous-clé "
                                f"(ex: {label}['{hint_key}'] > seuil) puis combiner les masques.",
                            )
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
                    binding = _binding_info_for_expr(operand, bindings)
                    if binding and binding["kind"] == "dict":
                        label = _binding_expr_label(operand, binding)
                        hint_key = _dict_indicator_allowed_keys_hint(
                            str(binding.get("indicator") or label)
                        ).split(",")[0].strip()
                        return (
                            False,
                            f"Usage invalide: test booléen direct sur `{label}` "
                            "qui est un indicator dict. Utiliser une sous-clé "
                            f"(ex: {label}['{hint_key}']).",
                        )

            if isinstance(node, (ast.If, ast.While)):
                binding = _binding_info_for_expr(node.test, bindings)
                if binding and binding["kind"] == "dict":
                    label = _binding_expr_label(node.test, binding)
                    hint_key = _dict_indicator_allowed_keys_hint(
                        str(binding.get("indicator") or label)
                    ).split(",")[0].strip()
                    return (
                        False,
                        f"Usage invalide: condition `{label}` alors que `{label}` est un "
                        f"indicator dict. Utiliser une sous-clé (ex: {label}['{hint_key}']).",
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
        return _strip_non_python_noise(match.group(1)).strip()
    # Fallback : le texte entier
    return _strip_non_python_noise(text).strip()


def _strip_non_python_noise(text: str) -> str:
    """Retire le bruit fréquent des réponses LLM autour du code Python."""
    raw_lines = str(text or "").splitlines()
    cleaned_lines: List[str] = []
    seen_code = False

    for line in raw_lines:
        stripped = line.strip()

        if not stripped:
            if seen_code:
                cleaned_lines.append("")
            continue

        if stripped.startswith("```"):
            continue
        if stripped.lower() == "python":
            continue
        if _LOG_PREFIX_RE.match(line) or _PIPE_LOG_PREFIX_RE.match(line):
            continue
        if _TRACEBACK_LINE_RE.match(line) or _WINDOWS_PATH_LINE_RE.match(line):
            continue

        candidate = _strip_leading_list_marker(line)
        candidate_stripped = candidate.strip()

        if not seen_code:
            if _NATURAL_LANGUAGE_LINE_RE.match(candidate_stripped):
                continue
            if _PYTHONISH_LINE_RE.match(candidate_stripped) or candidate_stripped.startswith("#"):
                seen_code = True
                cleaned_lines.append(candidate)
            continue

        if _NATURAL_LANGUAGE_LINE_RE.match(candidate_stripped) and not _PYTHONISH_LINE_RE.match(candidate_stripped):
            continue
        cleaned_lines.append(candidate)

    if cleaned_lines:
        while cleaned_lines and not cleaned_lines[-1].strip():
            cleaned_lines.pop()
        if cleaned_lines:
            return "\n".join(cleaned_lines)
    return ""


def _sanitize_python_list_markers(code: str) -> str:
    """Supprime les marqueurs de liste LLM devant des lignes Python valides."""
    fixed_lines: List[str] = []
    for line in str(code or "").splitlines():
        candidate = _strip_leading_list_marker(line)
        if candidate != line and (
            _PYTHONISH_LINE_RE.match(candidate.lstrip()) or candidate.lstrip().startswith("#")
        ):
            fixed_lines.append(candidate)
        else:
            fixed_lines.append(line)
    return "\n".join(fixed_lines)


def _strip_leading_list_marker(line: str) -> str:
    """Retire `1.`/`-` au début d'une ligne en conservant l'indentation utile."""
    match = re.match(r"^(\s*)(?:[-*]|\d+[\.)])(.*)$", line)
    if not match:
        return line
    leading_ws, remainder = match.groups()
    if remainder.startswith((" ", "\t")):
        remainder = remainder[1:]
    return leading_ws + remainder


def _drop_obvious_non_python_lines(code: str) -> str:
    """Supprime les lignes manifestement non Python après extraction."""
    kept_lines: List[str] = []
    for line in str(code or "").splitlines():
        stripped = line.strip()
        if not stripped:
            kept_lines.append(line)
            continue
        if stripped.startswith("```") or stripped.lower() == "python":
            continue
        if _NATURAL_LANGUAGE_LINE_RE.match(stripped) and not _PYTHONISH_LINE_RE.match(stripped):
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines)


def _balance_brackets_outside_strings(code: str) -> str:
    """Rééquilibre prudemment les parenthèses/crochets/accolades hors chaînes."""
    open_to_close = {"(": ")", "[": "]", "{": "}"}
    closing_to_open = {")": "(", "]": "[", "}": "{"}
    stack: List[str] = []
    output: List[str] = []
    in_single = False
    in_double = False
    escape = False

    for ch in str(code or ""):
        if escape:
            output.append(ch)
            escape = False
            continue
        if ch == "\\":
            output.append(ch)
            escape = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            output.append(ch)
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            output.append(ch)
            continue
        if in_single or in_double:
            output.append(ch)
            continue
        if ch in open_to_close:
            stack.append(ch)
            output.append(ch)
            continue
        if ch in closing_to_open:
            expected_open = closing_to_open[ch]
            if stack and stack[-1] == expected_open:
                stack.pop()
                output.append(ch)
            else:
                continue
            continue
        output.append(ch)

    while stack:
        output.append(open_to_close[stack.pop()])

    return "".join(output)


def _salvage_complex_ast_syntax(code: str) -> str:
    """Tente des réparations syntaxiques conservatrices avant fallback.

    Objectif: corriger le bruit de sortie LLM et les déséquilibres simples qui
    empêchent `ast.parse` de construire l'arbre, sans réécrire la logique métier.
    """
    candidate = _strip_non_python_noise(code)
    candidate = _drop_obvious_non_python_lines(candidate)
    candidate = _sanitize_python_list_markers(candidate)

    attempts = [
        candidate,
        textwrap.dedent(candidate),
        _balance_brackets_outside_strings(candidate),
        _balance_brackets_outside_strings(textwrap.dedent(candidate)),
    ]

    seen: set[str] = set()
    for attempt in attempts:
        attempt = attempt.strip("\n")
        if not attempt or attempt in seen:
            continue
        seen.add(attempt)
        try:
            ast.parse(attempt)
            return attempt
        except SyntaxError:
            continue

    return candidate


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
        except (
            ValueError,
            KeyError,
            RuntimeError,
            AttributeError,
            TypeError,
            IndexError,
            NameError,
        ) as exc:
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


def validate_builder_dataset_exploitability(
    data: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
) -> tuple[bool, str]:
    """API partagée UI/Builder pour valider un dataset exploitable."""
    return _validate_builder_dataset_exploitability(
        data,
        symbol=symbol,
        timeframe=timeframe,
    )


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


def _get_known_indicator_names() -> set[str]:
    """Retourne les noms d'indicateurs du registre, en minuscules."""
    try:
        return {
            str(ind or "").strip().lower()
            for ind in list_indicators()
            if str(ind or "").strip()
        }
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
        return set(_DICT_INDICATOR_NAMES)


def _indicator_access_hint(indicator_name: str) -> str:
    """Retourne le hint d'accès recommandé pour un indicateur donné."""
    name = str(indicator_name or "").strip().lower()
    alias_hint = _INDICATOR_ALIAS_HINTS.get(name)
    if alias_hint:
        return alias_hint
    if name in _DICT_INDICATOR_NAMES:
        keys = sorted(_DICT_INDICATOR_ALLOWED_KEYS.get(name, set()))
        if keys:
            return f"indicators['{name}']['{keys[0]}']"
        return f"indicators['{name}']"
    return f"np.nan_to_num(indicators['{name}'])"


def _indicator_name_from_hint_expression(expr: str) -> Optional[str]:
    match = re.search(r"indicators\[['\"]([A-Za-z0-9_]+)['\"]\]", str(expr or ""))
    if not match:
        return None
    return str(match.group(1)).strip().lower() or None


def _infer_required_indicator_names_from_code(
    code: str,
    required_indicators: Optional[List[str]] = None,
) -> List[str]:
    """Infère les indicateurs réellement nécessaires à partir du code et des alias connus."""
    known = _get_known_indicator_names()
    inferred = _normalize_required_indicator_names(required_indicators)
    inferred_set = set(inferred)

    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        tree = None

    if tree is not None:
        for name in _collect_indicator_names(tree) | _collect_indicator_names_in_class(tree):
            normalized_name = str(name or "").strip().lower()
            if normalized_name in known and normalized_name not in inferred_set:
                inferred.append(normalized_name)
                inferred_set.add(normalized_name)

    search_space = [
        *_INDICATOR_ALIAS_HINTS.items(),
        *_INDICATOR_ACCESS_REWRITE_HINTS.items(),
    ]
    for alias, hint in search_space:
        if not re.search(rf"\b{re.escape(alias)}\b", code, flags=re.IGNORECASE):
            continue
        indicator_name = _indicator_name_from_hint_expression(hint)
        if indicator_name and indicator_name in known and indicator_name not in inferred_set:
            inferred.append(indicator_name)
            inferred_set.add(indicator_name)

    for indicator_name in sorted(known):
        if re.search(
            rf"\b{re.escape(indicator_name)}_(?:arr|array|data|values?)\b",
            code,
            flags=re.IGNORECASE,
        ) and indicator_name not in inferred_set:
            inferred.append(indicator_name)
            inferred_set.add(indicator_name)

    return inferred


def _rewrite_invalid_indicator_accesses(text: str) -> str:
    fixed = text
    for alias, replacement in _INDICATOR_ACCESS_REWRITE_HINTS.items():
        fixed = re.sub(
            rf"indicators\s*\[\s*['\"]{re.escape(alias)}['\"]\s*\]",
            replacement,
            fixed,
            flags=re.IGNORECASE,
        )
        fixed = re.sub(
            rf"indicators\.get\(\s*['\"]{re.escape(alias)}['\"]\s*(?:,\s*[^)]*)?\)",
            replacement,
            fixed,
            flags=re.IGNORECASE,
        )
    for name, replacement in _PARAM_ACCESS_REWRITE_HINTS.items():
        fixed = re.sub(
            rf"indicators\s*\[\s*['\"]{re.escape(name)}['\"]\s*\]",
            replacement,
            fixed,
            flags=re.IGNORECASE,
        )
        fixed = re.sub(
            rf"indicators\.get\(\s*['\"]{re.escape(name)}['\"]\s*(?:,\s*[^)]*)?\)",
            replacement,
            fixed,
            flags=re.IGNORECASE,
        )
    return fixed


def _collect_bound_names(fn: ast.AST) -> set[str]:
    """Collecte les noms localement définis dans une fonction/méthode."""
    bound: set[str] = set()

    args = getattr(getattr(fn, "args", None), "args", []) or []
    bound.update(arg.arg for arg in args if getattr(arg, "arg", None))
    kwonlyargs = getattr(getattr(fn, "args", None), "kwonlyargs", []) or []
    bound.update(arg.arg for arg in kwonlyargs if getattr(arg, "arg", None))

    _load_names, store_names = _collect_name_load_store_sets(fn)
    bound.update(store_names)

    for node in ast.walk(fn):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.ExceptHandler) and isinstance(node.name, str):
            bound.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])

    return bound


def _collect_module_level_bound_names(tree: ast.AST) -> set[str]:
    """Collecte les noms disponibles au scope module pour éviter les faux NameError."""
    bound: set[str] = set()

    for node in getattr(tree, "body", []) or []:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bound.add(node.target.id)

    return bound


def _normalize_required_indicator_names(required_indicators: Optional[List[str]]) -> List[str]:
    normalized: List[str] = []
    if not required_indicators:
        return normalized
    for item in required_indicators:
        if not isinstance(item, str):
            continue
        indicator_name = item.strip().lower()
        if indicator_name and indicator_name not in normalized:
            normalized.append(indicator_name)
    return normalized


def _extract_declared_required_indicators(code: str) -> List[str]:
    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "required_indicators":
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Return) or not isinstance(stmt.value, ast.List):
                continue
            items: List[str] = []
            for elt in stmt.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    items.append(str(elt.value))
            return _normalize_required_indicator_names(items)
    return []


def _build_generate_signals_indicator_binding_lines(required_indicators: Optional[List[str]]) -> List[str]:
    binding_lines: List[str] = []
    seen_lines: set[str] = set()

    for indicator_name in _normalize_required_indicator_names(required_indicators):
        if indicator_name in _DICT_INDICATOR_NAMES:
            access_example = get_indicator_builder_access_example(indicator_name)
            raw_lines = re.split(r";\s*|\n+", access_example)
            candidate_lines = [line.strip() for line in raw_lines if line.strip()]
        else:
            candidate_lines = [
                f"{indicator_name} = np.nan_to_num(indicators['{indicator_name}'])"
            ]

        for line in candidate_lines:
            normalized_line = line
            if re.match(r"^value\s*=", normalized_line):
                normalized_line = re.sub(r"^value\b", indicator_name, normalized_line)
            if normalized_line not in seen_lines:
                seen_lines.add(normalized_line)
                binding_lines.append(normalized_line)

        if indicator_name in _DICT_INDICATOR_NAMES:
            local_names: List[str] = []
            stable_alias_map = get_indicator_builder_stable_alias_map(indicator_name)
            for line in candidate_lines:
                normalized_line = line
                if re.match(r"^value\s*=", normalized_line):
                    normalized_line = re.sub(r"^value\b", indicator_name, normalized_line)
                match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", normalized_line)
                if not match:
                    continue
                lhs_name = match.group(1)
                if lhs_name not in local_names:
                    local_names.append(lhs_name)

            for lhs_name in local_names:
                if lhs_name == indicator_name:
                    continue
                stable_alias_name = stable_alias_map.get(
                    lhs_name,
                    f"{indicator_name}_{lhs_name}",
                )
                stable_alias_line = f"{stable_alias_name} = {lhs_name}"
                if stable_alias_line not in seen_lines:
                    seen_lines.add(stable_alias_line)
                    binding_lines.append(stable_alias_line)
        else:
            for alias_name in (f"{indicator_name}_arr", f"{indicator_name}_data"):
                alias_line = f"{alias_name} = {indicator_name}"
                if alias_line not in seen_lines:
                    seen_lines.add(alias_line)
                    binding_lines.append(alias_line)

    return binding_lines


def _build_generate_signals_indicator_binding_groups(
    required_indicators: Optional[List[str]],
) -> List[Tuple[str, List[str], List[str]]]:
    """Construit les lignes de binding par indicateur en séparant base et alias.

    Les lignes de base extraient l'indicateur depuis `indicators[...]`.
    Les alias dérivés (`rsi_arr = rsi`, `bollinger_upper = upper`, etc.) ne sont
    sûrs que si la base est injectée au même endroit ou déjà disponible avant.
    """
    groups: List[Tuple[str, List[str], List[str]]] = []

    for indicator_name in _normalize_required_indicator_names(required_indicators):
        base_lines: List[str] = []
        alias_lines: List[str] = []
        seen_local: set[str] = set()

        if indicator_name in _DICT_INDICATOR_NAMES:
            access_example = get_indicator_builder_access_example(indicator_name)
            raw_lines = re.split(r";\s*|\n+", access_example)
            candidate_lines = [line.strip() for line in raw_lines if line.strip()]
        else:
            candidate_lines = [
                f"{indicator_name} = np.nan_to_num(indicators['{indicator_name}'])"
            ]

        for line in candidate_lines:
            normalized_line = line
            if re.match(r"^value\s*=", normalized_line):
                normalized_line = re.sub(r"^value\b", indicator_name, normalized_line)
            base_lines.append(normalized_line)
            match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", normalized_line)
            if match:
                seen_local.add(match.group(1))

        if indicator_name in _DICT_INDICATOR_NAMES:
            stable_alias_map = get_indicator_builder_stable_alias_map(indicator_name)
            for lhs_name in list(seen_local):
                if lhs_name == indicator_name:
                    continue
                stable_alias_name = stable_alias_map.get(lhs_name, f"{indicator_name}_{lhs_name}")
                alias_lines.append(f"{stable_alias_name} = {lhs_name}")
        else:
            alias_lines.extend(
                [
                    f"{indicator_name}_arr = {indicator_name}",
                    f"{indicator_name}_data = {indicator_name}",
                ]
            )

        groups.append((indicator_name, base_lines, alias_lines))

    return groups


def _inject_generate_signals_indicator_bindings(
    code: str,
    required_indicators: Optional[List[str]] = None,
) -> str:
    """Injecte un préambule de bindings indicateurs dans generate_signals."""
    indicator_names = _infer_required_indicator_names_from_code(code, required_indicators)
    if not indicator_names:
        return code

    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return code

    fns = _iter_generate_signals_functions(tree)
    if not fns:
        return code

    binding_groups = _build_generate_signals_indicator_binding_groups(indicator_names)
    if not binding_groups:
        return code

    lines = code.split("\n")
    insertions: List[Tuple[int, List[str]]] = []

    for fn in fns:
        fn_start = max(0, int(fn.lineno) - 1)
        fn_end = max(fn_start, int(getattr(fn, "end_lineno", fn.lineno)))
        fn_source = "\n".join(lines[fn_start:fn_end])

        binding_lines: List[str] = []
        for _indicator_name, base_lines, alias_lines in binding_groups:
            existing_base = any(line in fn_source for line in base_lines)
            if existing_base:
                continue
            binding_lines.extend(line for line in base_lines if line not in fn_source)
            binding_lines.extend(line for line in alias_lines if line not in fn_source)

        if not binding_lines:
            continue

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
        if 0 <= insert_idx < len(lines) and lines:
            indent = re.match(r"^(\s*)", lines[insert_idx]).group(1)
        else:
            def_line_idx = max(0, min(len(lines) - 1, int(fn.lineno) - 1)) if lines else 0
            def_indent = re.match(r"^(\s*)", lines[def_line_idx]).group(1) if lines else ""
            indent = def_indent + "    "

        insertions.append((insert_idx, [indent + line for line in binding_lines]))

    if not insertions:
        return code

    for idx, new_lines in sorted(insertions, key=lambda x: x[0], reverse=True):
        lines[idx:idx] = new_lines

    return "\n".join(lines)


def _inject_generate_signals_core_param_aliases(code: str) -> str:
    """Injecte des alias pour éviter des NameError de variables coeur.

    Cas fréquent: `def generate_signals(self, data, indicators, params):` mais le
    corps fait `signals = ... index=df.index` / `close = df["close"]...`.
    On insère alors `df = data` en tête de méthode (idem pour `indicators/params`).
    """
    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
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

        for param_name, replacement in _PARAM_ACCESS_REWRITE_HINTS.items():
            if param_name == "warmup":
                continue
            if param_name in load_names and param_name not in args and param_name not in store_names:
                alias_raw.append(f"{param_name} = {replacement}")

        for ohlcv_col in ("open", "high", "low", "close", "volume"):
            if ohlcv_col in load_names and ohlcv_col not in args and ohlcv_col not in store_names:
                alias_raw.append(
                    f"{ohlcv_col} = np.nan_to_num(df['{ohlcv_col}'].values.astype(np.float64))"
                )
        if "price" in load_names and "price" not in args and "price" not in store_names:
            if not any(line.startswith("close = ") for line in alias_raw):
                alias_raw.append("close = np.nan_to_num(df['close'].values.astype(np.float64))")
            alias_raw.append("price = close")

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


def _inject_generate_signals_indicator_aliases(code: str) -> str:
    """Injecte des alias d'indicateurs nus dans generate_signals quand l'intention est claire."""
    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return code

    fns = _iter_generate_signals_functions(tree)
    if not fns:
        return code

    known_indicators = _get_known_indicator_names()
    if not known_indicators:
        return code

    lines = code.split("\n")
    insertions: List[Tuple[int, List[str]]] = []

    for fn in fns:
        load_names, _store_names = _collect_name_load_store_sets(fn)
        bound_names = _collect_bound_names(fn)
        missing_indicator_names = sorted(
            {
                name
                for name in load_names
                if name in known_indicators and name not in bound_names
            }
        )
        if not missing_indicator_names:
            continue

        alias_raw: List[str] = []
        for indicator_name in missing_indicator_names:
            if indicator_name in _DICT_INDICATOR_NAMES:
                alias_raw.append(
                    f"{indicator_name} = indicators['{indicator_name}']"
                )
            else:
                alias_raw.append(
                    f"{indicator_name} = np.nan_to_num(indicators['{indicator_name}'])"
                )

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
        if 0 <= insert_idx < len(lines) and lines:
            indent = re.match(r"^(\s*)", lines[insert_idx]).group(1)
        else:
            def_line_idx = max(0, min(len(lines) - 1, int(fn.lineno) - 1)) if lines else 0
            def_indent = re.match(r"^(\s*)", lines[def_line_idx]).group(1) if lines else ""
            indent = def_indent + "    "

        insertions.append((insert_idx, [indent + line for line in alias_raw]))

    if not insertions:
        return code

    for idx, new_lines in sorted(insertions, key=lambda x: x[0], reverse=True):
        lines[idx:idx] = new_lines

    return "\n".join(lines)


def _repair_code(code: str, required_indicators: Optional[List[str]] = None) -> str:
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
    code = _salvage_complex_ast_syntax(code)

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
    code = _drop_obvious_non_python_lines(code)
    code = _sanitize_python_list_markers(code)

    # 3. Supprimer docstrings si syntax error + tenter un dedent sur erreurs d'indentation
    try:
        ast.parse(code)
    except SyntaxError as e:
        msg = str(getattr(e, "msg", "") or "").lower()
        if "unexpected indent" in msg or "unindent" in msg or "indentation" in msg:
            code = textwrap.dedent(code)
        code = _strip_docstrings(code)
        code = _salvage_complex_ast_syntax(code)

    # 3. Fixer le nom de classe
    code = _fix_class_name(code)

    # 3b. Réécrire les faux accès indicators[...] qui désignent des alias ou des params.
    code = _rewrite_invalid_indicator_accesses(code)
    for alias, correct in _SEMANTIC_INDICATOR_ALIAS_HINTS.items():
        code = re.sub(
            rf"(?<!['\"\[])(?<![A-Za-z0-9_]){re.escape(alias)}(?!['\"])(?![A-Za-z0-9_])",
            correct,
            code,
        )

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

    # 10a. Préambule systématique des indicateurs déclarés/attendus dans generate_signals
    code = _inject_generate_signals_indicator_bindings(code, required_indicators)

    # 10b. Alias indicateurs nus dans generate_signals (évite NameError coppock_curve, rsi, etc.)
    code = _inject_generate_signals_indicator_aliases(code)

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
            pattern = r"\b" + re.escape(alias) + r"\b(?!\s*=)"
            replacement = f"np.nan_to_num(indicators['{dict_ind}']['{subkey}'])"
            code = re.sub(pattern, replacement, code)

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

    for dict_ind, subkeys in _DICT_INDICATOR_ALLOWED_KEYS.items():
        for subkey in subkeys:
            code = re.sub(
                rf"\b{re.escape(dict_ind)}\s*\.\s*{re.escape(subkey)}\b",
                f"indicators['{dict_ind}']['{subkey}']",
                code,
                flags=re.IGNORECASE,
            )

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

    for alias, correct in _SEMANTIC_INDICATOR_ALIAS_HINTS.items():
        code = re.sub(
            rf"(?<!['\"\[])(?<![A-Za-z0-9_]){re.escape(alias)}(?!['\"])(?![A-Za-z0-9_])",
            correct,
            code,
        )

    return code


def _extract_generate_signals_logic_block(code: str) -> str:
    """Extrait le bloc logique de generate_signals depuis une réponse LLM."""
    candidates: List[str] = []
    direct = str(code or "")
    salvaged = _salvage_complex_ast_syntax(direct)
    extracted = _extract_python_from_response(direct)
    for candidate in (direct, salvaged, extracted):
        candidate = str(candidate or "")
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    for candidate in candidates:
        try:
            tree = ast.parse(candidate)
        except (SyntaxError, IndentationError, ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
            continue

        lines = candidate.splitlines()
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


def _rewrite_cross_helper_calls(logic: str) -> str:
    """Réécrit quelques pseudo-helpers de croisement en masques numpy explicites."""

    def _cross_replacement(lhs: str, direction: str, rhs: str) -> str:
        lhs = lhs.strip()
        rhs = rhs.strip()
        if direction in {"above", "over"}:
            return f"(({lhs} > {rhs}) & (np.roll({lhs}, 1) <= np.roll({rhs}, 1)))"
        return f"(({lhs} < {rhs}) & (np.roll({lhs}, 1) >= np.roll({rhs}, 1)))"

    fixed = logic
    fixed = re.sub(
        r"\bcrosses_(above|over|below|under)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)",
        lambda m: _cross_replacement(m.group(2), m.group(1), m.group(3)),
        fixed,
        flags=re.IGNORECASE,
    )
    fixed = re.sub(
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s+cross(?:es)?\s+(above|over|below|under)\s+([A-Za-z_][A-Za-z0-9_]*)\b",
        lambda m: _cross_replacement(m.group(1), m.group(2).lower(), m.group(3)),
        fixed,
        flags=re.IGNORECASE,
    )
    return fixed


def _normalize_same_slice_vector_comparisons(logic: str) -> str:
    """Réécrit les comparaisons symétriquement slicées en comparaisons pleine longueur.

    Exemple: `close[warmup:] > ema[warmup:]` devient `close > ema`, ce qui évite
    les masques plus courts que `df` et les erreurs de broadcast/indexation.
    """

    slice_token = r"(?:\d+|warmup)"
    fixed = logic
    fixed = re.sub(
        rf"\b([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*({slice_token})\s*:\s*\]\s*(==|!=|>=|<=|>|<)\s*([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*\2\s*:\s*\]",
        r"\1 \3 \4",
        fixed,
    )
    fixed = re.sub(
        rf"\b([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*({slice_token})\s*:\s*\]\s*(\&|\|)\s*([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*\2\s*:\s*\]",
        r"\1 \3 \4",
        fixed,
    )
    return fixed


def _normalize_boolean_keyword_mask_ops(logic: str) -> str:
    """Réécrit certains `and/or` en `&/|` pour des affectations de masques.

    Reste volontairement conservateur: on ne touche qu'aux lignes d'affectation
    de variables de type masque/entry/exit, et uniquement si l'opérateur est
    homogène sur la ligne.
    """

    target_name_re = re.compile(
        r"^\s*([A-Za-z_][A-Za-z0-9_]*(?:_mask|_entry|_exit|_cond|_signal)|long_mask|short_mask|long_entry|short_entry)\s*=\s*(.+)$"
    )

    fixed_lines: List[str] = []
    for line in str(logic or "").splitlines():
        match = target_name_re.match(line)
        if not match or (" and " not in line and " or " not in line):
            fixed_lines.append(line)
            continue

        lhs, rhs = match.groups()
        rhs = rhs.strip()
        if " and " in rhs and " or " in rhs:
            fixed_lines.append(line)
            continue
        if any(token in rhs for token in {"'", '"', "lambda ", " for ", " if "}):
            fixed_lines.append(line)
            continue

        if " and " in rhs:
            parts = [part.strip() for part in rhs.split(" and ") if part.strip()]
            if len(parts) >= 2:
                fixed_lines.append(f"{lhs} = ((" + ") & (".join(parts) + "))")
                continue
        if " or " in rhs:
            parts = [part.strip() for part in rhs.split(" or ") if part.strip()]
            if len(parts) >= 2:
                fixed_lines.append(f"{lhs} = ((" + ") | (".join(parts) + "))")
                continue

        fixed_lines.append(line)

    return "\n".join(fixed_lines)


def _normalize_truncated_signal_mask_assignments(logic: str) -> str:
    """Répare `signals[mask[1:]] = ...` quand le masque est tronqué inutilement."""
    slice_token = r"(?:\d+|warmup)"
    fixed = logic
    fixed = re.sub(
        rf"signals\s*\[\s*([A-Za-z_][A-Za-z0-9_]*)\s*\[\s*{slice_token}\s*:\s*\]\s*\]",
        r"signals[\1]",
        fixed,
    )
    return fixed


def _postprocess_llm_logic_block(logic: str, required_indicators: List[str]) -> str:
    """Corrige automatiquement des fautes mineures de logique LLM."""
    fixed = logic
    fixed = _rewrite_cross_helper_calls(fixed)
    fixed = _normalize_same_slice_vector_comparisons(fixed)
    fixed = _normalize_boolean_keyword_mask_ops(fixed)
    fixed = _normalize_truncated_signal_mask_assignments(fixed)
    fixed = re.sub(r"signals\s*\.loc\s*\[", "signals[", fixed)
    fixed = re.sub(r"signals\s*\.notnull\s*\(\s*\)", "(signals != 0.0)", fixed)
    fixed = re.sub(r"signals\s*\.isnull\s*\(\s*\)", "(signals == 0.0)", fixed)
    fixed = _rewrite_invalid_indicator_accesses(fixed)
    for ind in required_indicators:
        fixed = re.sub(
            rf"df\s*\[\s*['\"]{re.escape(ind)}['\"]\s*\]",
            f"indicators['{ind}']",
            fixed,
        )
    fixed = re.sub(
        r"df\s*\[\s*['\"]signals?['\"]\s*\]",
        "signals",
        fixed,
    )
    for alias, correct in _INDICATOR_ALIAS_HINTS.items():
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
    if re.search(r"\.iloc\[(?!\s*:)", logic):
        return False, _err(ERR_SIG, "`.iloc[i]` interdit (accès indexé). Seul `signals.iloc[:warmup]` est autorisé.")
    if re.search(r"\bsignals\.loc\b|\bsignals\s*\.\s*notnull\s*\(", logic):
        return False, _err(ERR_SIG, "Usage pandas direct sur `signals` interdit; utiliser des masques numpy/vectorises.")
    if re.search(r"\[['\"][^'\"]*\|[^'\"]*['\"]\]", logic):
        return False, _err(ERR_IND, "Sous-cles concatenees avec `|` interdites; acceder a une seule sous-cle a la fois.")
    if re.search(r"\bcrosses_(?:above|below|over|under)[a-z_]*\b", logic):
        return False, _err(ERR_SIG, "Pseudo-helper `crosses_*` interdit; exprimer le croisement avec np.roll et comparaisons explicites.")
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
    required_indicators = _normalize_required_indicator_names(
        cast(Optional[List[str]], used if isinstance(used, list) else None)
    )

    default_params = proposal.get("default_params", {})
    if not isinstance(default_params, dict):
        default_params = {}
    default_params.setdefault("leverage", 1)
    default_params.setdefault("warmup", 50)
    direction_constraint = str(proposal.get("direction_constraint", "long_short") or "long_short").strip().lower()

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
    indicator_binding_lines = _build_generate_signals_indicator_binding_lines(required_indicators)
    indicator_binding_block = "".join(
        f"        {line}\n" for line in indicator_binding_lines
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
        f"{indicator_binding_block}"
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
    safe_used = _normalize_required_indicator_names(
        cast(Optional[List[str]], used if isinstance(used, list) else None)
    )
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
    indicator_binding_lines = _build_generate_signals_indicator_binding_lines(safe_used)
    indicator_binding_block = "".join(
        f"        {line}\n" for line in indicator_binding_lines
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
        f"{indicator_binding_block}"
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


def _looks_pathological_param_name(name: str) -> bool:
    """Détecte les noms de paramètres manifestement dégénérés produits par un LLM."""
    candidate = str(name or "").strip().lower()
    if not candidate:
        return True
    if len(candidate) > 64:
        return True
    if re.search(r"([^_]+(?:_[^_]+)*)_(?:\1){1,}$", candidate):
        return True
    chunks = [part for part in candidate.split("_") if part]
    if len(chunks) >= 6:
        seen = set()
        duplicate_count = 0
        for chunk in chunks:
            if chunk in seen:
                duplicate_count += 1
            else:
                seen.add(chunk)
        if duplicate_count >= 3:
            return True
    return False


def _sanitize_param_mapping(raw: Any) -> Dict[str, Any]:
    """Conserve uniquement les paramètres au nom raisonnable."""
    if not isinstance(raw, dict):
        return {}
    cleaned: Dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        param_name = key.strip()
        if not param_name or _looks_pathological_param_name(param_name):
            continue
        cleaned[param_name] = value
    return cleaned


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
    known = {str(x or "").strip().lower() for x in available_indicators if str(x or "").strip()}
    used = cleaned.get("used_indicators", [])
    normalized_used: List[str] = []
    if isinstance(used, list):
        for item in used:
            ind = _canonicalize_indicator_name(item, known=known)
            if ind and ind not in normalized_used:
                normalized_used.append(ind)
    if not normalized_used:
        normalized_used = ["atr"] if "atr" in known else sorted(known)[:2]
    cleaned["used_indicators"] = normalized_used

    # Params sécurisés (diagnostics ruine/no-trades)
    default_params = _sanitize_param_mapping(cleaned.get("default_params"))
    default_params["leverage"] = min(2, max(1, int(default_params.get("leverage", 1) or 1)))
    default_params.setdefault("stop_atr_mult", 1.5)
    default_params.setdefault("tp_atr_mult", 3.0)
    default_params.setdefault("warmup", 50)
    cleaned["default_params"] = default_params

    specs = _sanitize_param_mapping(cleaned.get("parameter_specs"))
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


def _previous_iteration_indicators(
    last_iteration: Optional["BuilderIteration"],
) -> tuple[str, ...]:
    """Retourne les indicateurs de l'itération précédente depuis son code validé."""
    if last_iteration is None or not getattr(last_iteration, "code", ""):
        return tuple()
    return _extract_required_indicators_signature(last_iteration.code)


def _requires_indicator_exploration(
    last_iteration: Optional["BuilderIteration"],
) -> bool:
    """Indique si la prochaine proposition doit explorer de nouveaux indicateurs."""
    if last_iteration is None:
        return False

    stag = (getattr(last_iteration, "phase_feedback", {}) or {}).get("stagnation", {})
    if bool(stag.get("identical_metrics")):
        return True

    cat = str(getattr(last_iteration, "diagnostic_category", "") or "").strip().lower()
    return cat in {
        "ruined",
        "no_trades",
        "overtrading",
        "wrong_direction",
        "high_drawdown",
        "needs_work",
    }


def _proposal_reuses_previous_indicator_set(
    proposal: Dict[str, Any],
    previous_indicators: tuple[str, ...],
) -> bool:
    """Retourne True si la proposition recycle exactement le même set d'indicateurs."""
    if not previous_indicators:
        return False
    current = {
        str(ind).strip().lower()
        for ind in proposal.get("used_indicators", [])
        if str(ind).strip()
    }
    previous = {str(ind).strip().lower() for ind in previous_indicators if str(ind).strip()}
    return bool(current) and current == previous


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
            except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
                issues.append("parameter_spec_non_numeric_bounds")
            if "step" in spec and spec.get("step") is not None:
                try:
                    step = float(spec.get("step"))
                    if step <= 0:
                        issues.append("parameter_spec_invalid_step")
                except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
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
    coerced = np.sign(values).astype(np.float64)
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
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return tuple()

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == GENERATED_CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "required_indicators":
                    for stmt in item.body:
                        if isinstance(stmt, ast.Return):
                            try:
                                value = ast.literal_eval(stmt.value)
                            except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
                                return tuple()
                            if isinstance(value, (list, tuple)):
                                normalized = [str(v) for v in value]
                                return tuple(sorted(normalized))
    return tuple()


def _extract_generate_signals_signature(code: str) -> str:
    """Retourne une signature AST du corps de generate_signals."""
    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
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
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
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
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
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

        with _new_streamlit_aware_thread_pool(max_workers=1) as pool:
            try:
                future = pool.submit(_do_call)
            except RuntimeError as exc:
                if _is_interpreter_shutdown_runtime_error(exc):
                    logger.info(
                        "builder_llm_submit_aborted phase=%s reason=interpreter_shutdown",
                        phase,
                    )
                    raise KeyboardInterrupt() from exc
                raise
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
        except (
            ValueError,
            KeyError,
            RuntimeError,
            AttributeError,
            TypeError,
            IndexError,
            NameError,
        ) as exc:
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
        previous_indicators = list(_previous_iteration_indicators(last_iteration))
        diagnostic_detail = (
            dict(last_iteration.diagnostic_detail)
            if last_iteration is not None and last_iteration.diagnostic_detail
            else {}
        )
        prefer_diversity = bool(
            last_iteration is not None
            and _requires_indicator_exploration(last_iteration)
        )
        ordered_prompt_indicators = rank_indicator_selection(
            self.available_indicators,
            objective=session.objective,
            diagnostic=diagnostic_detail,
            previous_indicators=previous_indicators,
            session_seed=f"{session.session_id}:proposal:{len(session.iterations)+1}",
            prefer_diversity=prefer_diversity,
        )

        context = {
            "objective": session.objective,
            "available_indicators": ordered_prompt_indicators,
            "available_indicator_guide": build_indicator_selection_guide(
                ordered_prompt_indicators
            ),
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
            if previous_indicators:
                context["previous_indicators"] = previous_indicators
            # Diagnostic pré-calculé de la dernière itération
            if diagnostic_detail:
                context["diagnostic"] = diagnostic_detail
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
            context["should_consider_indicator_expansion"] = _requires_indicator_exploration(
                last_iteration
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

        ordered_code_indicators = rank_indicator_selection(
            self.available_indicators,
            objective=(
                f"{session.objective} {proposal.get('hypothesis', '')} "
                f"{' '.join(proposal.get('used_indicators', []) or [])}"
            ),
            diagnostic=(last_iteration.diagnostic_detail if last_iteration else {}),
            previous_indicators=proposal.get("used_indicators", []),
            session_seed=f"{session.session_id}:code:{len(session.iterations)+1}",
            prefer_diversity=False,
        )

        context = {
            "objective": session.objective,
            "proposal": proposal,
            "available_indicators": ordered_code_indicators,
            "available_indicator_guide": build_indicator_selection_guide(
                ordered_code_indicators
            ),
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
            "- use vectorized masks ONLY; no arr[i], no loops, no row-by-row logic\n"
            "- if you need previous values, use np.roll(array, 1)\n"
            "- never use for i in range(...) or while\n"
            "- never use signals.loc[...] or signals.notnull(); write signals[mask] = 1.0/-1.0 only\n"
            "- bollinger keys are separate: indicators['bollinger']['upper'], ['middle'], ['lower']\n"
            "- donchian breakout should compare close vs previous band: prev_upper = np.roll(donchian_upper, 1)\n\n"
            "- adx keys are separate: indicators['adx']['adx'], ['plus_di'], ['minus_di'] (not indicators['adx'] directly)\n"
            "- supertrend keys are separate: indicators['supertrend']['supertrend'] and ['direction']\n"
            "- stochastic keys are separate: indicators['stochastic']['stoch_k'] and ['stoch_d'] (no 'signal' key)\n"
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
            "  bollinger['upper'/'middle'/'lower'], keltner['upper'/'middle'/'lower'],\n"
            "  donchian['upper'/'middle'/'lower'], macd['macd'/'signal'/'histogram'],\n"
            "  For Donchian/Bollinger/Keltner breakout rules, compare against previous band values via np.roll(..., 1)\n"
            "  adx['adx'/'plus_di'/'minus_di'], supertrend['supertrend'/'direction'],\n"
            "  stochastic['stoch_k'/'stoch_d'], stoch_rsi['k'/'d'/'signal'],\n"
            "  ichimoku['tenkan'/'kijun'/'senkou_a'/'senkou_b'/'chikou'/'cloud_position'],\n"
            "  psar['sar'/'trend'/'signal'], vortex['vi_plus'/'vi_minus'/'signal'/'oscillator'],\n"
            "  aroon['aroon_up'/'aroon_down'], pivot_points['pivot'/'r1'/'s1'/'r2'/'s2'/'r3'/'s3']\n"
            "- NEVER create bare variables like keltner_upper or donchian_lower\n"
            "- Do NOT compare dict indicators directly (e.g. avoid `adx > threshold`)\n"
            "- For bitwise `&` / `|`, each side must be a boolean mask expression\n"
            "- ALWAYS define long_mask/short_mask before using: long_mask = np.zeros(len(df), dtype=bool)\n"
            "- `signals` MUST stay a 1D pd.Series: never create `long`/`short` columns, "
            "never write `signals.loc[mask, 'long']`, use only `signals[mask] = 1.0/-1.0`\n"
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
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError) as llm_exc:
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
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError) as exc:
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
- Markov Switching is a regime filter — use regime/probability state to gate trades, not as a fast trigger by itself.
- Directional Bias is a composite context score — use it to confirm or veto entries, not as a standalone raw trigger.
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
16. Bollinger must be used via separate sub-keys like indicators['bollinger']['upper'] / ['middle'] / ['lower'] (never indicators['bollinger_upper']).
17. EMA/RSI/ATR/CCI are plain arrays: NEVER use sub-keys like indicators['ema']['ema_21'].
    CCI is a plain array: use np.nan_to_num(indicators['cci']) directly.
18. ADX must be used via separate sub-keys indicators['adx']['adx'] / ['plus_di'] / ['minus_di'] (never compare indicators['adx'] directly).
19. Supertrend must be used via indicators['supertrend']['supertrend'] and ['direction'] (no upper/lower keys).
20. Stochastic must be used via indicators['stochastic']['stoch_k'] and ['stoch_d'] (no 'signal' key).
21. Keltner must be used via separate sub-keys indicators['keltner']['upper'] / ['middle'] / ['lower'].
22. Donchian must be used via separate sub-keys indicators['donchian']['upper'] / ['middle'] / ['lower'].
22b. For breakout on Donchian/Bollinger/Keltner bands, compare close to previous band values via np.roll(band, 1).
23. Ichimoku must be used via separate sub-keys like tenkan, kijun, senkou_a, senkou_b, chikou, cloud_position.
24. PSAR must be used via separate sub-keys sar, trend, signal.
25. Vortex must be used via separate sub-keys vi_plus, vi_minus, signal, oscillator.
26. Stoch_RSI must be used via separate sub-keys k, d, signal (NEVER compare indicators['stoch_rsi'] directly).
27. Aroon must be used via separate sub-keys aroon_up and aroon_down.
28. Pivot_points must be used via separate sub-keys pivot, r1, s1, r2, s2, r3, s3.
29. NEVER create bare variables like keltner_upper, donchian_lower, cci_value etc.
    Always extract from the indicators dict: e.g. kelt = indicators['keltner']; upper = np.nan_to_num(kelt['upper']).
30. For bitwise '&' and '|', both sides must be boolean mask expressions (never float/int scalars).
31. ALWAYS set "leverage": 1 in default_params. The backtest engine defaults to leverage=3 which ruins accounts.
32. Never assign `required_indicators` anywhere.
33. Never use `for i in range(...)` or `while` in signal logic.
34. ALWAYS define long_mask/short_mask before using them. Initialize with: long_mask = np.zeros(len(df), dtype=bool).
34b. `signals` is always a 1D pd.Series: never index a second dimension, never create `long`/`short` columns, never write `signals.loc[mask, 'long']`.
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
        declared = _extract_declared_required_indicators(code)
        inferred = _infer_required_indicator_names_from_code(code, declared)
        if not inferred:
            return strategy_cls

        declared_tuple = tuple(_normalize_required_indicator_names(declared))
        inferred_tuple = tuple(_normalize_required_indicator_names(inferred))
        if inferred_tuple == declared_tuple:
            return strategy_cls

        logger.info(
            "builder_required_indicators_auto_fix before=%s after=%s",
            declared_tuple,
            inferred_tuple,
        )

        patched_required = list(inferred_tuple)
        setattr(strategy_cls, "_builder_required_indicators_auto_fixed", patched_required)
        strategy_cls.required_indicators = property(
            lambda self, _patched=tuple(patched_required): list(_patched)
        )
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
            indicators = engine.calculate_indicators(probe_df, strategy_instance, merged_params)
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
        except (
            ValueError,
            KeyError,
            RuntimeError,
            AttributeError,
            TypeError,
            IndexError,
            NameError,
        ) as exc:
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
            except NameError as exc:
                missing_name = ""
                match = re.search(r"name '([^']+)' is not defined", str(exc))
                if match:
                    missing_name = match.group(1)
                detail = (
                    f"`{missing_name}` is not defined"
                    if missing_name
                    else str(exc)
                )
                raise RuntimeError(
                    "NameError in generate_signals: "
                    f"{detail}. FIX: every intermediate variable must be "
                    "defined before use; remove placeholder names and inline "
                    "or bind the final boolean expression explicitly."
                ) from exc
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
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
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
                            fallback_code = _repair_code(fallback_code, req_inds)
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
                code = _repair_code(
                    code,
                    [
                        str(x).strip().lower()
                        for x in proposal.get("used_indicators", [])
                        if isinstance(x, str) and str(x).strip()
                    ],
                )
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
                        retry_code = _repair_code(retry_code, req_inds)
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
                        fallback_code = _repair_code(fallback_code, req_inds)
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
                pre_reflection_pool: Optional[concurrent.futures.ThreadPoolExecutor] = None

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
                    try:
                        pre_reflection_pool = _new_streamlit_aware_thread_pool(max_workers=1)
                        pre_reflection_future = pre_reflection_pool.submit(
                            self._ask_pre_reflection,
                            session, proposal, code, i,
                        )
                    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
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
                    except (
                        ValueError,
                        KeyError,
                        RuntimeError,
                        AttributeError,
                        TypeError,
                        IndexError,
                        NameError,
                    ) as bt_exc:
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
                        retry_code = _repair_code(
                            retry_code,
                            [
                                str(x).strip().lower()
                                for x in proposal.get("used_indicators", [])
                                if isinstance(x, str) and str(x).strip()
                            ],
                        )
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
                            fallback_code = _repair_code(
                                fallback_code,
                                [
                                    str(x).strip().lower()
                                    for x in proposal.get("used_indicators", [])
                                    if isinstance(x, str) and str(x).strip()
                                ],
                            )
                            valid_fb, fb_err = validate_generated_code(fallback_code)
                            if not valid_fb:
                                raise ValueError(
                                    "Runtime-fix invalide et fallback déterministe invalide: "
                                    f"{retry_err} | {fb_err}"
                                ) from bt_exc
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
                        except (
                            ValueError,
                            KeyError,
                            RuntimeError,
                            AttributeError,
                            TypeError,
                            IndexError,
                            NameError,
                        ) as retry_bt_exc:
                            if used_runtime_fallback:
                                raise
                            iteration.phase_feedback.setdefault("backtest", {})[
                                "runtime_fix_retry_error"
                            ] = f"{type(retry_bt_exc).__name__}: {retry_bt_exc}"
                            fallback_code = _build_deterministic_fallback_code(
                                proposal, variant=fallback_count,
                            )
                            fallback_count += 1
                            fallback_code = _repair_code(
                                fallback_code,
                                [
                                    str(x).strip().lower()
                                    for x in proposal.get("used_indicators", [])
                                    if isinstance(x, str) and str(x).strip()
                                ],
                            )
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
                            ts.append(f"🧠  PRÉ-RÉFLEXION (pendant backtest)\n    {pre_reflection_text[:300]}\n\n")
                    except concurrent.futures.TimeoutError:
                        iteration.phase_feedback.setdefault("pre_reflection", {})[
                            "timeout"
                        ] = True
                    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
                        pass
                    finally:
                        if pre_reflection_pool is not None:
                            pre_reflection_pool.shutdown(wait=False)

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

            except KeyboardInterrupt:
                logger.info(
                    "builder_iter_%d_interrupted reason=keyboard_interrupt_or_interpreter_shutdown",
                    i,
                )
                raise
            except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError) as e:
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
        last_runtime_feedback = {
            "last_runtime_error": None,
            "last_runtime_error_iteration": None,
            "last_runtime_traceback_tail": None,
        }
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
                "total_pnl": metrics.get("total_pnl") if metrics else None,
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

            phase_feedback = it.phase_feedback if isinstance(it.phase_feedback, dict) else {}
            backtest_feedback = (
                phase_feedback.get("backtest", {})
                if isinstance(phase_feedback, dict)
                else {}
            )
            if not isinstance(backtest_feedback, dict):
                backtest_feedback = {}
            runtime_error = str(backtest_feedback.get("runtime_error") or "").strip()
            runtime_traceback_tail = str(
                backtest_feedback.get("runtime_traceback_tail") or ""
            ).strip()
            if runtime_error or runtime_traceback_tail:
                last_runtime_feedback = {
                    "last_runtime_error": runtime_error or None,
                    "last_runtime_error_iteration": it.iteration,
                    "last_runtime_traceback_tail": runtime_traceback_tail or None,
                }

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
            "symbol": session.symbol,
            "timeframe": session.timeframe,
            "n_bars": session.n_bars,
            "date_range_start": session.date_range_start,
            "date_range_end": session.date_range_end,
            "initial_capital": session.initial_capital,
            "fees_bps": session.fees_bps,
            "slippage_bps": session.slippage_bps,
            "start_time": session.start_time.isoformat(),
            "auto_reset_count": session.auto_reset_count,
            "recovery_events": session.recovery_events,
            "total_iterations": len(session.iterations),
            "available_indicators": session.available_indicators,
            "last_runtime_error": last_runtime_feedback.get("last_runtime_error"),
            "last_runtime_error_iteration": last_runtime_feedback.get("last_runtime_error_iteration"),
            "last_runtime_traceback_tail": last_runtime_feedback.get("last_runtime_traceback_tail"),
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
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError) as exc:
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
        normalized = _canonicalize_indicator_name(token, known=allowed_set)
        if normalized and normalized not in selected:
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


def _sanitize_objective_indicator_candidates(
    raw_indicators: Any,
    available_indicators: List[str],
) -> List[str]:
    """Normalise une liste d'indicateurs issus d'un payload structuré."""
    allowed = [
        str(ind or "").strip().lower()
        for ind in (available_indicators or [])
        if str(ind or "").strip()
    ]
    allowed_set = set(allowed)
    if not allowed_set:
        return []

    raw_tokens: List[str] = []
    if isinstance(raw_indicators, str):
        raw_tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", raw_indicators)
    elif isinstance(raw_indicators, (list, tuple, set)):
        raw_tokens = [str(item or "") for item in raw_indicators]

    selected: List[str] = []
    for token in raw_tokens:
        normalized = _canonicalize_indicator_name(token, known=allowed_set)
        if normalized and normalized not in selected:
            selected.append(normalized)

    if len(selected) < 2:
        preferred = [
            name
            for name in ("ema", "rsi", "bollinger", "macd", "stochastic", "adx", "atr")
            if name in allowed_set and name not in selected
        ]
        for candidate in preferred:
            selected.append(candidate)
            if len(selected) >= 3:
                break

    return selected[:4]


def _request_structured_objective_payload(
    llm_client: Any,
    *,
    system_prompt: str,
    user_prompt: str,
    stream_callback: Optional[Callable[[str, str], None]],
    max_tokens: int,
) -> tuple[Dict[str, Any], str]:
    """Demande un handoff JSON pour la génération d'objectif."""
    messages = [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content=user_prompt),
    ]
    if stream_callback and hasattr(llm_client, "chat_stream"):
        raw = llm_client.chat_stream(
            messages,
            on_chunk=lambda c: stream_callback("objective_gen", c),
            max_tokens=max_tokens,
            json_mode=True,
        )
    else:
        raw = llm_client.chat(messages, max_tokens=max_tokens, json_mode=True)

    raw_text = str(getattr(raw, "content", raw) or "").strip()
    return _extract_json_from_response(raw_text), raw_text


def _resolve_structured_objective_market(
    payload: Dict[str, Any],
    *,
    market_auto_selection: bool,
    symbols_list: List[str],
    timeframes_list: List[str],
) -> tuple[str, str]:
    if market_auto_selection:
        return "{symbol}", "{timeframe}"

    symbol_value = str(payload.get("symbol", "") or "").strip().upper()
    timeframe_value = str(payload.get("timeframe", "") or "").strip()

    if symbols_list:
        allowed_symbols = {str(item or "").strip().upper() for item in symbols_list}
        if symbol_value not in allowed_symbols:
            symbol_value = str(symbols_list[0] or "").strip().upper()
    if timeframes_list:
        allowed_timeframes = {str(item or "").strip() for item in timeframes_list}
        if timeframe_value not in allowed_timeframes:
            timeframe_value = str(timeframes_list[0] or "").strip()

    return symbol_value, timeframe_value


def _structured_objective_to_text(
    payload: Dict[str, Any],
    *,
    available_indicators: List[str],
    market_auto_selection: bool,
    symbols_list: List[str],
    timeframes_list: List[str],
) -> str:
    """Reconstruit un objectif lisible depuis un payload JSON."""
    if not isinstance(payload, dict) or not payload:
        return ""

    if not any(
        str(payload.get(key, "") or "").strip()
        for key in ("objective", "style", "entry_logic", "exit_logic", "risk_management", "hypothesis")
    ) and not payload.get("used_indicators"):
        return ""

    objective = _normalize_llm_text(payload.get("objective"), max_len=900)
    objective = sanitize_objective_text(objective)
    if objective and not _looks_like_prompt_instruction_leakage(objective):
        return objective

    symbol_value, timeframe_value = _resolve_structured_objective_market(
        payload,
        market_auto_selection=market_auto_selection,
        symbols_list=symbols_list,
        timeframes_list=timeframes_list,
    )
    style = _normalize_llm_text(payload.get("style"), max_len=80) or "Stratégie"
    entry_logic = _normalize_llm_text(payload.get("entry_logic"), max_len=260)
    exit_logic = _normalize_llm_text(payload.get("exit_logic"), max_len=260)
    risk_management = _normalize_llm_text(payload.get("risk_management"), max_len=220)
    hypothesis = _normalize_llm_text(payload.get("hypothesis"), max_len=220)
    indicators = _sanitize_objective_indicator_candidates(
        payload.get("used_indicators"),
        available_indicators,
    )

    parts: List[str] = []
    market_label = f"{symbol_value} {timeframe_value}".strip()
    parts.append(f"[{style}] sur {market_label}.")
    if indicators:
        parts.append(f"Indicateurs : {' + '.join(ind.upper() for ind in indicators)}.")
    if hypothesis:
        parts.append(f"Hypothèse : {hypothesis}.")
    if entry_logic:
        parts.append(f"Entrées : {entry_logic}.")
    if exit_logic:
        parts.append(f"Sorties : {exit_logic}.")
    if risk_management:
        parts.append(f"Risk management : {risk_management}.")

    return " ".join(part.strip() for part in parts if part.strip()).strip()


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
    system_prompt = (
        "Tu es un quant designer specialise en strategies de trading crypto. "
        "Tu dois produire un handoff STRUCTURE et exploitable par un Builder. "
        "Reponds UNIQUEMENT avec un objet JSON valide, sans markdown ni commentaire."
    )
    if market_auto_selection:
        market_contract = (
            "- symbol MUST be exactly `{symbol}`.\n"
            "- timeframe MUST be exactly `{timeframe}`.\n"
        )
    else:
        allowed_symbols = ", ".join(symbols_list)
        allowed_timeframes = ", ".join(timeframes_list)
        market_contract = (
            f"- symbol MUST be one of: {allowed_symbols}.\n"
            f"- timeframe MUST be one of: {allowed_timeframes}.\n"
        )

    user_prompt = (
        "Genere un objectif de strategie de trading sous forme de JSON.\n\n"
        f"{market_instruction}"
        f"Indicateurs disponibles : {indicators_list}\n\n"
        "Contraintes de diversification:\n"
        f"- Integre au moins un axe 'hors sentiers battus' parmi: {', '.join(selected_axes)}.\n"
        f"- Comportements aleatoires imposes pour cette generation: {', '.join(selected_behaviors)}.\n"
        "- Evite les formulations generiques de type 'RSI<30/RSI>70' sans filtre additionnel.\n"
        "- Propose une hypothese testable et falsifiable.\n"
        "- Explore des combinaisons inhabituelles, des filtres originaux, des approches multi-timeframe conceptuelles.\n"
        "- used_indicators doit contenir 2 a 4 indicateurs maximum.\n"
        "- objective doit etre un texte court de 2 a 4 phrases maximum.\n"
        f"{market_contract}"
        "- Tous les indicateurs doivent provenir strictement de la liste disponible.\n\n"
        "Retourne EXACTEMENT ce schema JSON:\n"
        "{\n"
        '  "objective": "texte final lisible par un humain",\n'
        '  "style": "nom court de la logique",\n'
        '  "symbol": "marche cible",\n'
        '  "timeframe": "timeframe cible",\n'
        '  "used_indicators": ["indicator_1", "indicator_2"],\n'
        '  "entry_logic": "condition d entree",\n'
        '  "exit_logic": "condition de sortie",\n'
        '  "risk_management": "resume du risk management",\n'
        '  "hypothesis": "pourquoi cette strategie peut fonctionner"\n'
        "}"
    )

    payload, raw_text = _request_structured_objective_payload(
        llm_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        stream_callback=stream_callback,
        max_tokens=420,
    )
    objective = _structured_objective_to_text(
        payload,
        available_indicators=available_indicators,
        market_auto_selection=market_auto_selection,
        symbols_list=symbols_list,
        timeframes_list=timeframes_list,
    )
    if not objective:
        objective = sanitize_objective_text(raw_text)
    if _looks_like_prompt_instruction_leakage(objective):
        logger.warning(
            "generate_llm_objective: contamination de prompt detectee, fallback template",
        )
        objective = ""

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

    if market_auto_selection:
        market_contract = (
            "- symbol MUST be exactly `{symbol}`.\n"
            "- timeframe MUST be exactly `{timeframe}`.\n"
        )
    else:
        market_contract = (
            f"- symbol MUST be one of: {', '.join(symbols_list)}.\n"
            f"- timeframe MUST be one of: {', '.join(timeframes_list)}.\n"
        )

    system_prompt = (
        "Tu es un quant designer. On te donne une piste catalogue brute. "
        "Ta tache est de la transformer en un objectif de recherche plus precis, plus robuste "
        "et mieux adapte au setup etudie, tout en conservant l intention strategique generale. "
        "Reponds UNIQUEMENT avec un objet JSON valide."
    )
    user_prompt = (
        f"{market_instruction}"
        f"{chr(10).join(seed_context)}\n\n"
        f"Indicateurs disponibles : {indicators_list}\n\n"
        "Contraintes :\n"
        "- Pars de la piste catalogue, mais reformule-la pour en faire une hypothese testable et falsifiable.\n"
        "- Choisis les indicateurs les plus coherents avec cette strategie.\n"
        "- N'utilise QUE des indicateurs disponibles.\n"
        "- used_indicators doit contenir 2 a 4 indicateurs maximum.\n"
        "- objective doit rester en 2 a 4 phrases.\n"
        "- Evite les formulations generiques et les signaux trop triviaux.\n"
        f"{market_contract}"
        "Retourne EXACTEMENT ce schema JSON:\n"
        "{\n"
        '  "objective": "texte final lisible par un humain",\n'
        '  "style": "nom court de la logique",\n'
        '  "symbol": "marche cible",\n'
        '  "timeframe": "timeframe cible",\n'
        '  "used_indicators": ["indicator_1", "indicator_2"],\n'
        '  "entry_logic": "condition d entree",\n'
        '  "exit_logic": "condition de sortie",\n'
        '  "risk_management": "resume du risk management",\n'
        '  "hypothesis": "pourquoi cette strategie peut fonctionner"\n'
        "}"
    )

    payload, raw_text = _request_structured_objective_payload(
        llm_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        stream_callback=stream_callback,
        max_tokens=440,
    )
    objective = _structured_objective_to_text(
        payload,
        available_indicators=available_indicators,
        market_auto_selection=market_auto_selection,
        symbols_list=symbols_list,
        timeframes_list=timeframes_list,
    )
    if not objective:
        objective = sanitize_objective_text(raw_text)
    if _looks_like_prompt_instruction_leakage(objective):
        logger.warning(
            "generate_llm_objective_from_seed: contamination de prompt detectee, fallback seed",
        )
        objective = ""
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
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
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
    if hinted_symbol and hinted_timeframe and recent_markets:
        hinted_combo = (hinted_symbol, hinted_timeframe)
        recent_window = recent_markets[-6:]
        if hinted_combo in recent_window:
            # Conflict detection done in strategy recommendation logic
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
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
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
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError) as exc:
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
    except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
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

