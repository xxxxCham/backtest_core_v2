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
import importlib.util
import itertools
import json
import os
import pprint
import re
import sys
import threading
import textwrap
import traceback
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
from agents.pipeline_instrumentation import (
    PipelineInstrumentation,
    AblationController,
)

from agents.builder_state import (
    BuilderIteration,
    BuilderSession,
    _select_session_recovery_anchor,
)
from agents.builder_code_validation import validate_generated_code  # noqa: F401
from agents.builder_code_repair import _repair_code  # noqa: F401
from config.market_selection import (
    evaluate_market_dataset,
    infer_strategy_type,
    normalize_universe_mode,
)

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
_LLM_PHASE_TIMEOUT_PROPOSAL_REALIGN = int(
    os.getenv("BACKTEST_BUILDER_TIMEOUT_PROPOSAL_REALIGN", "45")
)
_LLM_PHASE_TIMEOUT_RETRY_PROPOSAL = int(
    os.getenv("BACKTEST_BUILDER_TIMEOUT_RETRY_PROPOSAL", "45")
)
_LLM_PHASE_TIMEOUT_RETRY_CODE = int(
    os.getenv("BACKTEST_BUILDER_TIMEOUT_RETRY_CODE", "60")
)
_LLM_PHASE_TIMEOUT_RETRY_CODE_RUNTIME = int(
    os.getenv("BACKTEST_BUILDER_TIMEOUT_RETRY_CODE_RUNTIME", "90")
)
_LLM_PHASE_TIMEOUT_VISION_FLOOR = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_VISION_FLOOR", "300"))
_LLM_PHASE_TIMEOUT_REASONING_PROPOSAL_FLOOR = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_REASONING_PROPOSAL_FLOOR", "300"))
_LLM_PHASE_TIMEOUT_REASONING_CODE_FLOOR = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_REASONING_CODE_FLOOR", "420"))
_LLM_PHASE_TIMEOUT_REASONING_ANALYSIS_FLOOR = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_REASONING_ANALYSIS_FLOOR", "180"))
_LLM_PHASE_TIMEOUTS: Dict[str, int] = {
    "proposal": _LLM_PHASE_TIMEOUT_PROPOSAL,
    "proposal_realign": _LLM_PHASE_TIMEOUT_PROPOSAL_REALIGN,
    "retry_proposal": _LLM_PHASE_TIMEOUT_RETRY_PROPOSAL,
    "code": _LLM_PHASE_TIMEOUT_CODE,
    "retry_code": _LLM_PHASE_TIMEOUT_RETRY_CODE,
    "retry_code_runtime": _LLM_PHASE_TIMEOUT_RETRY_CODE_RUNTIME,
    "analysis": _LLM_PHASE_TIMEOUT_ANALYSIS,
    "pre": _LLM_PHASE_TIMEOUT_ANALYSIS,
    "pre_reflection": _LLM_PHASE_TIMEOUT_ANALYSIS,
}
_BUILDER_MAX_UNTRADABLE_RATIO = float(
    os.getenv("BACKTEST_BUILDER_MAX_UNTRADABLE_RATIO", "0.25")
)
_BUILDER_SWEEP_MAX_COMBINATIONS = max(
    1,
    int(os.getenv("BACKTEST_BUILDER_SWEEP_MAX_COMBINATIONS", "9")),
)
_BUILDER_SWEEP_MAX_PARAMS = max(
    1,
    int(os.getenv("BACKTEST_BUILDER_SWEEP_MAX_PARAMS", "3")),
)
_BUILDER_SWEEP_TOP_RESULTS = max(
    1,
    int(os.getenv("BACKTEST_BUILDER_SWEEP_TOP_RESULTS", "3")),
)
_BUILDER_SWEEP_EXCLUDED_PARAMS = frozenset(
    {
        "leverage",
        "warmup",
        "fees_bps",
        "slippage_bps",
    }
)


def _is_interpreter_shutdown_runtime_error(exc: BaseException) -> bool:
    """Détecte le RuntimeError typique émis pendant l'arrêt de l'interpréteur."""
    if not isinstance(exc, RuntimeError):
        return False
    message = str(exc).lower()
    return (
        "interpreter shutdown" in message
        or "cannot schedule new futures after interpreter shutdown" in message
    )


def _is_vision_model(model_name: str) -> bool:
    model_lower = str(model_name or "").lower()
    return any(
        pattern in model_lower
        for pattern in (
            "qwen3-vl",
            "qwen2-vl",
            "-vl",
            "vision",
            "llava",
            "multimodal",
        )
    )


def _is_reasoning_builder_model(model_name: str) -> bool:
    model_lower = str(model_name or "").lower()
    return any(
        pattern in model_lower
        for pattern in (
            "deepseek-r1",
            "qwq",
            "o1",
            "o3",
            "r1",
            "reasoning",
        )
    )


def _resolve_builder_phase_timeout(
    phase_key: str,
    base_timeout_sec: int,
    llm_client: Any,
) -> int:
    model_name = str(
        getattr(getattr(llm_client, "config", None), "model", "") or ""
    )
    timeout_sec = int(base_timeout_sec)

    if phase_key not in {"proposal", "code", "analysis", "pre"}:
        return timeout_sec

    if _is_reasoning_builder_model(model_name):
        floor_by_phase = {
            "proposal": _LLM_PHASE_TIMEOUT_REASONING_PROPOSAL_FLOOR,
            "code": _LLM_PHASE_TIMEOUT_REASONING_CODE_FLOOR,
            "analysis": _LLM_PHASE_TIMEOUT_REASONING_ANALYSIS_FLOOR,
            "pre": _LLM_PHASE_TIMEOUT_REASONING_ANALYSIS_FLOOR,
        }
        timeout_sec = max(timeout_sec, int(floor_by_phase.get(phase_key, timeout_sec)))
    elif _is_vision_model(model_name):
        floor_by_phase = {
            "proposal": _LLM_PHASE_TIMEOUT_VISION_FLOOR,
            "code": _LLM_PHASE_TIMEOUT_VISION_FLOOR,
            "analysis": max(_LLM_PHASE_TIMEOUT_ANALYSIS, 150),
            "pre": max(_LLM_PHASE_TIMEOUT_ANALYSIS, 150),
        }
        timeout_sec = max(timeout_sec, int(floor_by_phase.get(phase_key, timeout_sec)))

    return int(timeout_sec)


def _normalize_builder_timeout_phase(phase: str) -> str:
    normalized = str(phase or "").strip().lower()
    if normalized.startswith("proposal_realign"):
        return "proposal_realign"
    if normalized.startswith("retry_proposal"):
        return "retry_proposal"
    if normalized.startswith("retry_code_runtime"):
        return "retry_code_runtime"
    if normalized.startswith("retry_code"):
        return "retry_code"
    if normalized.startswith("pre_reflection"):
        return "pre_reflection"
    return normalized.split("_")[0] if normalized else ""


def _truncate_runtime_traceback_tail(
    text: Any,
    *,
    max_lines: int = 25,
    max_chars: int = 4000,
) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    lines = raw.splitlines()
    if len(lines) > max_lines:
        raw = "\n".join(lines[-max_lines:])
    if len(raw) > max_chars:
        raw = raw[-max_chars:]
    return raw.strip()


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

_DICT_INDICATOR_SAFE_SCALAR_KEYS: Dict[str, str] = {
    "adx": "adx",
    "supertrend": "supertrend",
    "directional_bias": "net_bias",
    "markov_switching": "regime",
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


def sanitize_objective_text(objective: Any, *, enable_leakage_filter: bool = True) -> str:
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
    if enable_leakage_filter:
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


def compute_builder_telemetry_score(
    metrics: Dict[str, Any],
    *,
    target_sharpe: float = 1.0,
) -> Dict[str, Any]:
    """Score composite de télémétrie Builder.

    Ce score reste purement informatif: il n'oriente plus l'acceptation, la
    promotion d'itération ni le routing des modèles. Il sert uniquement à
    l'observabilité et au diagnostic.
    """
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


def compute_continuous_builder_score(
    metrics: Dict[str, Any],
    *,
    target_sharpe: float = 1.0,
) -> Dict[str, Any]:
    """Alias de compatibilité vers `compute_builder_telemetry_score()`."""
    return compute_builder_telemetry_score(
        metrics,
        target_sharpe=target_sharpe,
    )


def _telemetry_score_from_metrics(
    metrics: Dict[str, Any],
    *,
    target_sharpe: float = 1.0,
) -> float:
    """Score composite de télémétrie dérivé des métriques brutes."""
    return float(
        compute_builder_telemetry_score(
            metrics,
            target_sharpe=target_sharpe,
        ).get("score", -100.0)
    )


def _ranking_sharpe(
    metrics: Dict[str, Any],
    *,
    target_sharpe: float = 1.0,
) -> float:
    """Alias de compatibilité vers `_telemetry_score_from_metrics()`."""
    return _telemetry_score_from_metrics(
        metrics,
        target_sharpe=target_sharpe,
    )


def _builder_iteration_selection_key(
    metrics: Dict[str, Any],
    *,
    is_fallback: bool = False,
    target_sharpe: float = 1.0,
) -> tuple[Any, ...]:
    """Clé lexicographique explicite pour comparer deux runs Builder.

    Cette politique remplace l'ancien arbitrage par score composite.
    Priorités, de la plus importante à la moins importante :
    1. run non-fallback
    2. métriques non ruinées
    3. rendement positif
    4. profit factor acceptable
    5. nombre minimum de trades atteint
    6. target Sharpe atteinte
    7. Sharpe plus élevé
    8. rendement plus élevé
    9. profit factor plus élevé
    10. drawdown plus faible
    11. plus de trades
    12. meilleur win rate
    """
    sharpe = _metric_float(metrics, "sharpe_ratio", float("-inf"))
    ret = _metric_float(metrics, "total_return_pct", float("-inf"))
    max_dd = abs(_metric_float(metrics, "max_drawdown_pct", float("inf")))
    profit_factor = _metric_float(metrics, "profit_factor", 0.0)
    trades = int(metrics.get("total_trades", 0) or 0)
    win_rate = _metric_float(metrics, "win_rate_pct", 0.0)
    ruined = _is_ruined_metrics(metrics)

    return (
        0 if is_fallback else 1,
        0 if ruined else 1,
        1 if ret > MIN_RETURN_PCT_FOR_ACCEPT else 0,
        1 if profit_factor >= MIN_PROFIT_FACTOR_FOR_ACCEPT else 0,
        1 if trades >= MIN_TRADES_FOR_ACCEPT else 0,
        1 if sharpe >= target_sharpe else 0,
        sharpe,
        ret,
        profit_factor,
        -max_dd,
        trades,
        win_rate,
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
    universe_mode: str = "canonical",
    strategy_type: str = "",
    purpose: str = "builder",
    objective: str = "",
) -> tuple[bool, str]:
    """Valide que le dataset/timeframe est exploitable pour le Builder."""
    evaluation = evaluate_market_dataset(
        data,
        symbol=symbol,
        timeframe=timeframe,
        universe_mode=normalize_universe_mode(universe_mode, purpose=purpose),
        purpose=purpose,
        strategy_type=infer_strategy_type(
            strategy_type=strategy_type,
            objective=objective,
        ),
        objective=objective,
    )
    if evaluation.get("accepted"):
        return True, ""
    reasons = list(evaluation.get("exclusion_reasons", []) or [])
    if not reasons:
        return False, f"Dataset non exploitable sur {symbol}/{timeframe}."
    return False, f"{symbol}/{timeframe}: " + " | ".join(str(reason) for reason in reasons)


def validate_builder_dataset_exploitability(
    data: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    universe_mode: str = "canonical",
    strategy_type: str = "",
    purpose: str = "builder",
    objective: str = "",
) -> tuple[bool, str]:
    """API partagée UI/Builder pour valider un dataset exploitable."""
    return _validate_builder_dataset_exploitability(
        data,
        symbol=symbol,
        timeframe=timeframe,
        universe_mode=universe_mode,
        strategy_type=strategy_type,
        purpose=purpose,
        objective=objective,
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


def _rewrite_base_strategy_aliases(code: str) -> str:
    """Normalise l'ancien alias BaseStrategy vers StrategyBase."""
    fixed = re.sub(
        r"from\s+strategies\.base_strategy\s+import\s+BaseStrategy\b",
        "from strategies.base import StrategyBase",
        code,
    )
    fixed = re.sub(r"\bBaseStrategy\b", "StrategyBase", fixed)
    return fixed


def _rewrite_signals_loc_assignments(code: str) -> str:
    """Réécrit les patterns `signals.loc[mask, 'long'/'short'] = ...` vers une série 1D."""

    def _replacement(match: re.Match[str]) -> str:
        mask_expr = str(match.group("mask") or "").strip()
        side = str(match.group("side") or "").strip().lower()
        raw_value = str(match.group("value") or "").strip()
        normalized_value = raw_value
        if side == "short":
            if re.fullmatch(r"0(?:\.0+)?", raw_value):
                normalized_value = "0.0"
            else:
                normalized_value = "-1.0"
        elif side == "long":
            if re.fullmatch(r"0(?:\.0+)?", raw_value):
                normalized_value = "0.0"
            else:
                normalized_value = "1.0"
        elif re.fullmatch(r"1(?:\.0+)?", raw_value):
            normalized_value = "1.0"
        elif re.fullmatch(r"-1(?:\.0+)?", raw_value):
            normalized_value = "-1.0"
        elif re.fullmatch(r"0(?:\.0+)?", raw_value):
            normalized_value = "0.0"
        return f"signals[{mask_expr}] = {normalized_value}"

    return re.sub(
        r"signals\s*\.loc\s*\[\s*(?P<mask>[^,\]\n]+)\s*,\s*['\"](?P<side>long|short)['\"]\s*\]\s*=\s*(?P<value>[^\n#]+)",
        _replacement,
        code,
        flags=re.IGNORECASE,
    )


def _rewrite_safe_dict_indicator_comparisons(code: str) -> str:
    """Réécrit quelques comparaisons directes ambiguës sur indicateurs dict quand la sous-clé sûre est connue."""
    compare_ops = r"(==|!=|>=|<=|>|<)"
    rewritten_lines: List[str] = []
    for raw_line in str(code or "").splitlines():
        line = raw_line
        for indicator_name, subkey in _DICT_INDICATOR_SAFE_SCALAR_KEYS.items():
            scalar_expr = f"np.nan_to_num(indicators['{indicator_name}']['{subkey}'])"
            indicator_expr = (
                rf"indicators\s*\[\s*['\"]{re.escape(indicator_name)}['\"]\s*\](?!\s*\[)"
            )
            get_expr = (
                rf"indicators\.get\(\s*['\"]{re.escape(indicator_name)}['\"]\s*(?:,\s*[^)]*)?\)(?!\s*\[)"
            )
            for expr in (indicator_expr, get_expr):
                line = re.sub(
                    rf"({expr})\s*{compare_ops}",
                    lambda m, replacement=scalar_expr: (
                        f"{replacement} {m.group(2)}"
                    ),
                    line,
                )
                line = re.sub(
                    rf"{compare_ops}\s*({expr})",
                    lambda m, replacement=scalar_expr: (
                        f"{m.group(1)} {replacement}"
                    ),
                    line,
                )
        rewritten_lines.append(line)
    return "\n".join(rewritten_lines)


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


def _dedupe_preserve_order(values: List[Any]) -> List[Any]:
    deduped: List[Any] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def _coerce_builder_sweep_value(value: Any, param_type: str) -> Any:
    normalized_type = str(param_type or "").strip().lower()
    if normalized_type == "bool":
        return bool(value)
    numeric = float(value)
    if normalized_type == "int":
        return int(round(numeric))
    return round(numeric, 6)


def _build_builder_sweep_values(
    param_name: str,
    default_value: Any,
    spec: Dict[str, Any],
) -> List[Any]:
    param_type = str(spec.get("type", "") or "").strip().lower()
    if param_name in _BUILDER_SWEEP_EXCLUDED_PARAMS:
        return [default_value]

    if param_type == "bool":
        return _dedupe_preserve_order([bool(default_value), not bool(default_value)])

    if param_type not in {"int", "float"}:
        return [default_value]

    try:
        min_v = float(spec.get("min"))
        max_v = float(spec.get("max"))
    except (ValueError, TypeError):
        return [default_value]

    if min_v > max_v:
        return [default_value]

    try:
        default_numeric = float(
            default_value if default_value is not None else spec.get("default")
        )
    except (ValueError, TypeError):
        default_numeric = float(spec.get("default", min_v) or min_v)

    default_numeric = min(max(default_numeric, min_v), max_v)

    step_numeric: Optional[float] = None
    if spec.get("step") is not None:
        try:
            step_numeric = float(spec.get("step"))
        except (ValueError, TypeError):
            step_numeric = None
        if step_numeric is not None and step_numeric <= 0:
            step_numeric = None

    if step_numeric is not None:
        raw_values = [
            default_numeric,
            max(min_v, default_numeric - step_numeric),
            min(max_v, default_numeric + step_numeric),
        ]
    else:
        raw_values = [default_numeric, min_v, max_v]

    coerced = _dedupe_preserve_order(
        [
            _coerce_builder_sweep_value(value, param_type)
            for value in raw_values
        ]
    )
    return coerced[:3] if coerced else [default_value]


def _build_builder_sweep_plan(proposal: Dict[str, Any]) -> Dict[str, Any]:
    change_type = _normalize_change_type(proposal.get("change_type", "logic"))
    if change_type == "accept":
        return {
            "enabled": False,
            "reason": "accept_change_type",
            "param_grid": [],
            "parameter_values": {},
            "param_names": [],
        }

    default_params = _sanitize_param_mapping(proposal.get("default_params"))
    parameter_specs = _sanitize_param_mapping(proposal.get("parameter_specs"))
    if not default_params or not parameter_specs:
        return {
            "enabled": False,
            "reason": "missing_parameter_specs",
            "param_grid": [],
            "parameter_values": {},
            "param_names": [],
        }

    sweep_candidates: List[tuple[str, List[Any]]] = []
    for param_name, spec in parameter_specs.items():
        if not isinstance(spec, dict):
            continue
        default_value = default_params.get(param_name, spec.get("default"))
        values = _build_builder_sweep_values(param_name, default_value, spec)
        if len(values) > 1:
            sweep_candidates.append((param_name, values))

    if not sweep_candidates:
        return {
            "enabled": False,
            "reason": "single_point_only",
            "param_grid": [],
            "parameter_values": {},
            "param_names": [],
        }

    selected: List[tuple[str, List[Any]]] = []
    current_combinations = 1
    for param_name, values in sweep_candidates[:_BUILDER_SWEEP_MAX_PARAMS]:
        limited_values = list(values[:3])
        while (
            len(limited_values) > 1
            and current_combinations * len(limited_values) > _BUILDER_SWEEP_MAX_COMBINATIONS
        ):
            limited_values = limited_values[:-1]
        if len(limited_values) <= 1:
            continue
        selected.append((param_name, limited_values))
        current_combinations *= len(limited_values)

    if not selected:
        return {
            "enabled": False,
            "reason": "max_combination_budget",
            "param_grid": [],
            "parameter_values": {},
            "param_names": [],
        }

    param_names = [param_name for param_name, _ in selected]
    parameter_values = {param_name: list(values) for param_name, values in selected}
    param_grid: List[Dict[str, Any]] = []
    for combo in itertools.product(*(values for _, values in selected)):
        params = dict(default_params)
        for param_name, value in zip(param_names, combo):
            params[param_name] = value
        param_grid.append(params)

    return {
        "enabled": len(param_grid) > 1,
        "reason": "" if len(param_grid) > 1 else "single_point_only",
        "param_grid": param_grid[:_BUILDER_SWEEP_MAX_COMBINATIONS],
        "parameter_values": parameter_values,
        "param_names": param_names,
    }


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


def _should_enable_stagnation_branching(
    last_iteration: Optional["BuilderIteration"],
) -> bool:
    """N'ouvre des branches supplémentaires qu'après vraie stagnation."""
    if last_iteration is None:
        return False
    stagnation = (getattr(last_iteration, "phase_feedback", {}) or {}).get("stagnation", {})
    return bool(stagnation.get("identical_metrics")) and _requires_indicator_exploration(last_iteration)


def _build_stagnation_branch_specs(
    previous_indicators: tuple[str, ...],
) -> List[Dict[str, str]]:
    previous_text = ", ".join(previous_indicators) if previous_indicators else "the previous indicator set"
    return [
        {
            "label": "keep",
            "directive": (
                "STAGNATION BRANCH: KEEP_SET. Reuse exactly the previous indicator set "
                f"({previous_text}) but materially change the logic, filters, sequencing, or regime interpretation. "
                "Do not add or remove indicators in this branch."
            ),
        },
        {
            "label": "add_one",
            "directive": (
                "STAGNATION BRANCH: ADD_ONE. Start from the previous indicator set "
                f"({previous_text}) and add exactly one new indicator from the available list. "
                "The added indicator must address the current failure mode."
            ),
        },
        {
            "label": "remove_or_replace",
            "directive": (
                "STAGNATION BRANCH: REMOVE_OR_REPLACE. Starting from the previous indicator set "
                f"({previous_text}), either remove one weak/noisy indicator or replace one previous indicator "
                "with a more relevant one. A smaller set is allowed if it improves clarity."
            ),
        },
    ]


def _is_logic_like_change_type(change_type: Any) -> bool:
    return _normalize_change_type(change_type) in {"logic", "both"}


def _should_trip_logic_stagnation_circuit(
    last_iteration: Optional["BuilderIteration"],
    iteration: "BuilderIteration",
) -> bool:
    if last_iteration is None:
        return False
    current_stagnation = (getattr(iteration, "phase_feedback", {}) or {}).get("stagnation", {})
    previous_stagnation = (getattr(last_iteration, "phase_feedback", {}) or {}).get("stagnation", {})
    if not bool(current_stagnation.get("identical_metrics")):
        return False
    if not bool(previous_stagnation.get("identical_metrics")):
        return False
    if not _is_logic_like_change_type(iteration.change_type):
        return False
    if not _is_logic_like_change_type(getattr(last_iteration, "change_type", "")):
        return False
    return True


def _select_best_branch_candidate(
    outcomes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    successful = [outcome for outcome in outcomes if not outcome.get("error") and outcome.get("bt_result") is not None]
    if not successful:
        return outcomes[0] if outcomes else {}

    branch_preference = {
        "add_one": 2,
        "remove_or_replace": 1,
        "keep": 0,
    }

    def _outcome_metrics(outcome: Dict[str, Any]) -> Dict[str, Any]:
        metrics = outcome.get("metrics")
        if isinstance(metrics, dict):
            return metrics
        bt_result = outcome.get("bt_result")
        bt_metrics = getattr(bt_result, "metrics", None)
        return bt_metrics if isinstance(bt_metrics, dict) else {}

    successful.sort(
        key=lambda outcome: (
            *_builder_iteration_selection_key(
                _outcome_metrics(outcome),
                is_fallback=bool(outcome.get("is_fallback", False)),
                target_sharpe=float(outcome.get("target_sharpe", 1.0) or 1.0),
            ),
            branch_preference.get(str(outcome.get("branch_label", "")), 0),
        ),
        reverse=True,
    )
    return successful[0]


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


def _extract_default_params_signature(code: str) -> Dict[str, Any]:
    """Retourne le dict literal de default_params depuis le code généré."""
    try:
        tree = ast.parse(code)
    except _AST_PARSE_RECOVERABLE_EXCEPTIONS:
        return {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == GENERATED_CLASS_NAME:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "default_params":
                    for stmt in item.body:
                        if isinstance(stmt, ast.Return):
                            try:
                                value = ast.literal_eval(stmt.value)
                            except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
                                return {}
                            if isinstance(value, dict):
                                return value
    return {}


def _proposal_has_meaningful_param_delta(
    previous_code: str,
    proposal: Dict[str, Any],
) -> bool:
    """Indique si une proposition params-only change réellement default_params."""
    previous_params = _sanitize_param_mapping(
        _extract_default_params_signature(previous_code)
    )
    current_params = _sanitize_param_mapping(proposal.get("default_params"))
    if not current_params:
        return False
    return current_params != previous_params


def _proposal_changes_indicator_set_in_params_mode(
    previous_code: str,
    proposal: Dict[str, Any],
) -> bool:
    """Détecte une proposition params-only qui change en réalité les indicateurs."""
    previous_indicators = {
        str(ind).strip().lower()
        for ind in _extract_required_indicators_signature(previous_code)
        if str(ind).strip()
    }
    current_indicators = {
        str(ind).strip().lower()
        for ind in proposal.get("used_indicators", [])
        if str(ind).strip()
    }
    if not previous_indicators or not current_indicators:
        return False
    return current_indicators != previous_indicators


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
    telemetry_score = compute_builder_telemetry_score(
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
        "telemetry_score": round(float(telemetry_score.get("score", 0.0)), 2),
        "continuous_score": round(float(telemetry_score.get("score", 0.0)), 2),
        "telemetry_breakdown": {
            "components": telemetry_score.get("components", {}),
            "penalties": telemetry_score.get("penalties", {}),
            "drawdown_excess_pct": telemetry_score.get("drawdown_excess_pct", 0.0),
        },
        "score_breakdown": {
            "components": telemetry_score.get("components", {}),
            "penalties": telemetry_score.get("penalties", {}),
            "drawdown_excess_pct": telemetry_score.get("drawdown_excess_pct", 0.0),
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
        # ── Instrumentation & Ablation ──
        self.instrumentation = PipelineInstrumentation(enabled=False)
        self.ablation = AblationController()

        # ── Politique et historique de diversité des indicateurs ──────────
        try:
            from config.indicator_history import load_policy
            self._indicator_policy = load_policy()
        except Exception:
            self._indicator_policy = {}
        self._indicator_history: Dict[str, Any] = {}  # chargé au début de chaque run

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
            meta.setdefault("universe_mode", getattr(session, "universe_mode", ""))
            meta.setdefault("universe_purpose", getattr(session, "universe_purpose", ""))
            meta.setdefault(
                "universe_strategy_type",
                getattr(session, "universe_strategy_type", ""),
            )

        try:
            callback(raw_result)
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
            logger.exception(
                "builder_backtest_completed_callback_failed iteration=%s session=%s",
                iteration_num,
                getattr(session, "session_id", "unknown"),
            )

    def _persist_session_strategy_code(
        self,
        session: BuilderSession,
        code: str,
    ) -> None:
        """Persiste le code effectivement retenu pour la session courante."""
        if not code:
            return
        try:
            (session.session_dir / "strategy.py").write_text(code, encoding="utf-8")
        except (
            ValueError,
            KeyError,
            RuntimeError,
            AttributeError,
            TypeError,
            IndexError,
            OSError,
        ):
            logger.debug(
                "builder_strategy_code_persist_failed session=%s",
                getattr(session, "session_id", "unknown"),
                exc_info=True,
            )

    def _persist_runtime_checkpoint(
        self,
        session: BuilderSession,
        *,
        iteration_num: int,
        stage: str,
        status: str,
        branch_label: str = "main",
        error: str = "",
        traceback_tail: str = "",
        proposal_feedback: Optional[Dict[str, Any]] = None,
        code_feedback: Optional[Dict[str, Any]] = None,
        precheck_feedback: Optional[Dict[str, Any]] = None,
        backtest_feedback: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persiste un checkpoint léger pour diagnostiquer un crash intra-itération."""
        timestamp = datetime.now().isoformat()
        checkpoint_path = (
            session.session_dir / f"iteration_{int(iteration_num):03d}_runtime_checkpoint.json"
        )
        latest_path = session.session_dir / "runtime_checkpoint.json"

        payload: Dict[str, Any] = {}
        try:
            if checkpoint_path.exists():
                raw_payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                if isinstance(raw_payload, dict):
                    payload = dict(raw_payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            payload = {}

        events = payload.get("events", [])
        if not isinstance(events, list):
            events = []

        trimmed_error = str(error or "").strip()
        trimmed_traceback = _truncate_runtime_traceback_tail(traceback_tail)
        event_payload: Dict[str, Any] = {
            "timestamp": timestamp,
            "stage": str(stage or "").strip(),
            "status": str(status or "").strip(),
        }
        if trimmed_error:
            event_payload["error"] = trimmed_error
        if trimmed_traceback:
            event_payload["traceback_tail"] = trimmed_traceback
        events = [*events[-19:], event_payload]

        serialized_payload = {
            "session_id": session.session_id,
            "objective": session.objective,
            "iteration": int(iteration_num),
            "branch_label": str(branch_label or "main"),
            "stage": str(stage or "").strip(),
            "status": str(status or "").strip(),
            "updated_at": timestamp,
            "strategy_file": "strategy.py",
            "strategy_version_file": f"strategy_v{int(iteration_num)}.py",
            "error": trimmed_error or None,
            "traceback_tail": trimmed_traceback or None,
            "proposal_feedback": dict(proposal_feedback or {}),
            "code_feedback": dict(code_feedback or {}),
            "precheck_feedback": dict(precheck_feedback or {}),
            "backtest_feedback": dict(backtest_feedback or {}),
            "events": events,
        }
        if isinstance(extra, dict) and extra:
            serialized_payload["extra"] = dict(extra)

        for destination in (checkpoint_path, latest_path):
            try:
                destination.write_text(
                    json.dumps(serialized_payload, indent=2, default=str),
                    encoding="utf-8",
                )
            except (
                OSError,
                ValueError,
                RuntimeError,
                AttributeError,
                TypeError,
                IndexError,
            ):
                logger.debug(
                    "builder_runtime_checkpoint_persist_failed session=%s stage=%s status=%s",
                    getattr(session, "session_id", "unknown"),
                    stage,
                    status,
                    exc_info=True,
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
        timeout_phase_key = _normalize_builder_timeout_phase(phase)
        timeout_sec = _LLM_PHASE_TIMEOUTS.get(
            timeout_phase_key,
            _LLM_PHASE_TIMEOUTS.get(
                timeout_phase_key.split("_")[0] if timeout_phase_key else "",
                _LLM_PHASE_TIMEOUT_DEFAULT,
            ),
        )
        phase_client_key = self._resolve_phase_client_key(phase)
        llm_client = self.phase_llm_clients.get(phase_client_key, self.llm)
        timeout_sec = _resolve_builder_phase_timeout(
            timeout_phase_key,
            timeout_sec,
            llm_client,
        )
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
            except (ConnectionError, OSError) as exc:
                logger.warning(
                    "builder_llm_connection_error phase=%s error=%s",
                    phase, exc,
                )
                return SimpleNamespace(content="")
            except Exception as exc:
                logger.error(
                    "builder_llm_unexpected_error phase=%s error=%s",
                    phase, exc,
                    exc_info=True,
                )
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
        branch_directive: str = "",
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
        if self.ablation.is_enabled("indicator_ranking"):
            _inter_hist = getattr(self, "_indicator_history", {})
            _pol = getattr(self, "_indicator_policy", {})
            from config.indicator_history import get_banned_indicators, get_recent_indicators, get_recent_families
            _banned = get_banned_indicators(_inter_hist, _pol) if _pol.get("enabled", True) else set()
            _inter_recent = get_recent_indicators(_inter_hist, _pol) if _pol.get("enabled", True) else []
            _prev_families = get_recent_families(_inter_hist, _pol) if _pol.get("enabled", True) else []
            ordered_prompt_indicators = rank_indicator_selection(
                self.available_indicators,
                objective=session.objective,
                diagnostic=diagnostic_detail,
                previous_indicators=previous_indicators,
                session_seed=f"{session.session_id}:proposal:{len(session.iterations)+1}",
                prefer_diversity=prefer_diversity,
                banned_indicators=_banned,
                inter_session_indicators=_inter_recent,
                inter_session_penalty=float(_pol.get("previous_penalty", 0.0)),
                inter_session_novelty_bonus=float(_pol.get("novelty_bonus", 0.0)) if prefer_diversity else 0.0,
                previous_families=_prev_families,
                family_penalty=float(_pol.get("family_penalty", 0.0)),
                family_bonus=float(_pol.get("family_bonus", 0.0)),
            )
        else:
            ordered_prompt_indicators = list(self.available_indicators)

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
            if diagnostic_detail and self.ablation.is_enabled("diagnostic_context"):
                context["diagnostic"] = diagnostic_detail
            last_phase_feedback = (
                last_iteration.phase_feedback.to_dict()
                if hasattr(last_iteration.phase_feedback, "to_dict")
                else (last_iteration.phase_feedback or {})
            )
            last_backtest_feedback = (
                last_phase_feedback.get("backtest", {})
                if isinstance(last_phase_feedback, dict)
                else {}
            )
            if (
                isinstance(last_backtest_feedback, dict)
                and last_backtest_feedback.get("mode") == "sweep"
            ):
                context["last_sweep"] = {
                    "total_tested": last_backtest_feedback.get("sweep_total_tested", 0),
                    "success": last_backtest_feedback.get("sweep_success", 0),
                    "failed": last_backtest_feedback.get("sweep_failed", 0),
                    "best_params": last_backtest_feedback.get("sweep_best_params", {}),
                    "top_results": last_backtest_feedback.get("sweep_top_results", []),
                }
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

        if branch_directive:
            context["branch_directive"] = branch_directive

        if session.iterations and self.ablation.is_enabled("iteration_history"):
            def _iteration_backtest_feedback(
                iteration_row: BuilderIteration,
            ) -> Dict[str, Any]:
                raw_feedback = (
                    iteration_row.phase_feedback.to_dict()
                    if hasattr(iteration_row.phase_feedback, "to_dict")
                    else (iteration_row.phase_feedback or {})
                )
                if not isinstance(raw_feedback, dict):
                    return {}
                backtest_feedback = raw_feedback.get("backtest", {})
                return backtest_feedback if isinstance(backtest_feedback, dict) else {}

            context["iteration_history"] = [
                {
                    "backtest_feedback": _iteration_backtest_feedback(it),
                    "iteration": it.iteration,
                    "hypothesis": it.hypothesis,
                    "change_type": it.change_type,
                    "diagnostic_category": it.diagnostic_category,
                    "decision": it.decision,
                    "indicators": list(it.used_indicators or []),
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
                    "win_rate": (
                        it.backtest_result.metrics.get("win_rate_pct", 0)
                        if it.backtest_result else None
                    ),
                    "max_drawdown_pct": (
                        it.backtest_result.metrics.get("max_drawdown_pct", 0)
                        if it.backtest_result else None
                    ),
                    "profit_factor": (
                        it.backtest_result.metrics.get("profit_factor", 0)
                        if it.backtest_result else None
                    ),
                    "error": it.error,
                    "is_fallback": it.is_fallback,
                    "evaluation_mode": _iteration_backtest_feedback(it).get("mode", ""),
                    "sweep_total_tested": _iteration_backtest_feedback(it).get("sweep_total_tested"),
                    "params_used": _iteration_backtest_feedback(it).get("params_used"),
                }
                for it in session.iterations[-5:]
            ]

        # Fournir la meilleure config session pour ancrer le modèle
        best_it = session.best_iteration
        if best_it is not None and best_it.backtest_result is not None:
            bm = best_it.backtest_result.metrics or {}
            context["best_so_far"] = {
                "iteration": best_it.iteration,
                "hypothesis": best_it.hypothesis,
                "indicators": list(best_it.used_indicators or []),
                "sharpe": bm.get("sharpe_ratio", 0),
                "return_pct": bm.get("total_return_pct", 0),
                "max_drawdown_pct": bm.get("max_drawdown_pct", 0),
                "win_rate": bm.get("win_rate_pct", 0),
                "trades": bm.get("total_trades", 0),
                "profit_factor": bm.get("profit_factor", 0),
            }

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
        if self.ablation.is_enabled("proposal_sanitize"):
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
            if self.ablation.is_enabled("proposal_sanitize"):
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

    def _execute_proposal_candidate(
        self,
        *,
        session: BuilderSession,
        proposal: Dict[str, Any],
        proposal_feedback: Dict[str, Any],
        last_iteration: Optional[BuilderIteration],
        iteration_num: int,
        data: pd.DataFrame,
        initial_capital: float,
        fallback_count: int,
        branch_label: str = "main",
    ) -> tuple[Dict[str, Any], int]:
        from agents.builder_candidate_executor import (
            execute_proposal_candidate_v2,
        )

        return execute_proposal_candidate_v2(
            self,
            session=session,
            proposal=proposal,
            proposal_feedback=proposal_feedback,
            last_iteration=last_iteration,
            iteration_num=iteration_num,
            data=data,
            initial_capital=initial_capital,
            fallback_count=fallback_count,
            branch_label=branch_label,
        )

    def _instrument_candidate_outcome(
        self,
        outcome: Dict[str, Any],
        iteration_num: int,
    ) -> None:
        """Enregistre les données d'un outcome candidat dans la trace courante."""
        instr = self.instrumentation
        if not instr.enabled:
            return
        trace = instr._current_trace
        if trace is None:
            return
        trace.ablation_config = dict(self.ablation.get_config())

        proposal = outcome.get("proposal") or {}
        code_fb = outcome.get("code_feedback") or {}
        precheck_fb = outcome.get("precheck_feedback") or {}
        backtest_fb = outcome.get("backtest_feedback") or {}
        metrics = outcome.get("metrics") or {}
        scoring = outcome.get("scoring_payload") or {}
        code = outcome.get("code", "")

        instr.record_proposal(
            trace,
            proposal,
            source=code_fb.get("source", "llm"),
        )
        instr.record_code(
            trace,
            code,
            source=code_fb.get("source", "llm"),
            valid_first=code_fb.get("final_valid", False),
            repair_applied=bool(code_fb.get("repair_applied")),
            fallback_used=bool(
                code_fb.get("fallback_deterministic_used")
                or code_fb.get("source") == "deterministic_fallback"
            ),
            fallback_variant=code_fb.get("fallback_variant", -1),
        )
        if code_fb.get("repair_applied"):
            instr.record_restriction(
                trace,
                "code_repair",
                effect="helper",
                phase="code_repair",
            )
        if (
            code_fb.get("fallback_deterministic_used")
            or code_fb.get("source") == "deterministic_fallback"
        ):
            instr.record_restriction(
                trace,
                "deterministic_fallback",
                effect="helper",
                phase="code_gen",
                metadata={
                    "variant": int(code_fb.get("fallback_variant", -1) or -1),
                },
            )
        instr.record_precheck(
            trace,
            passed=not precheck_fb.get("backtest_skipped", False),
            signal_count=int(precheck_fb.get("signal_count", 0)),
            error=precheck_fb.get("skip_reason"),
        )
        if precheck_fb.get("backtest_skipped"):
            instr.record_restriction(
                trace,
                "precheck",
                effect="blocker",
                phase="precheck",
                detail=str(precheck_fb.get("skip_reason", "") or ""),
            )
        if outcome.get("bt_result") is not None:
            instr.record_backtest(
                trace,
                metrics,
                runtime_fix=bool(backtest_fb.get("runtime_fix_applied")),
                runtime_error=backtest_fb.get("runtime_error"),
            )
            if backtest_fb.get("runtime_fix_applied"):
                instr.record_restriction(
                    trace,
                    "runtime_fix",
                    effect="helper",
                    phase="runtime_fix",
                    detail=str(backtest_fb.get("runtime_error", "") or ""),
                )
        if scoring:
            instr.record_scoring(
                trace,
                scoring,
                rank_score=float(outcome.get("rank_score", float("-inf"))),
            )

        trace.is_fallback = bool(outcome.get("is_fallback", False))

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
        if last_iteration is not None and self.ablation.is_enabled("diagnostic_context"):
            diag_detail = getattr(last_iteration, "diagnostic_detail", {}) or {}
            diag_actions = diag_detail.get("actions", [])
            diag_donts = diag_detail.get("donts", [])

        if self.ablation.is_enabled("indicator_ranking"):
            _inter_hist2 = getattr(self, "_indicator_history", {})
            _pol2 = getattr(self, "_indicator_policy", {})
            from config.indicator_history import get_banned_indicators, get_recent_indicators, get_recent_families
            _banned2 = get_banned_indicators(_inter_hist2, _pol2) if _pol2.get("enabled", True) else set()
            _inter_recent2 = get_recent_indicators(_inter_hist2, _pol2) if _pol2.get("enabled", True) else []
            _prev_families2 = get_recent_families(_inter_hist2, _pol2) if _pol2.get("enabled", True) else []
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
                banned_indicators=_banned2,
                inter_session_indicators=_inter_recent2,
                inter_session_penalty=float(_pol2.get("previous_penalty", 0.0)),
                inter_session_novelty_bonus=0.0,
                previous_families=_prev_families2,
                family_penalty=float(_pol2.get("family_penalty", 0.0)),
                family_bonus=float(_pol2.get("family_bonus", 0.0)),
            )
        else:
            ordered_code_indicators = list(self.available_indicators)

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

        phase_feedback = (
            iteration.phase_feedback.to_dict()
            if hasattr(iteration.phase_feedback, "to_dict")
            else (iteration.phase_feedback or {})
        )
        backtest_feedback = (
            phase_feedback.get("backtest", {})
            if isinstance(phase_feedback, dict)
            else {}
        )
        if (
            isinstance(backtest_feedback, dict)
            and backtest_feedback.get("mode") == "sweep"
        ):
            lines.extend(
                [
                    "",
                    "### Sweep paramétrique",
                    (
                        f"- Combinaisons testées: "
                        f"{int(backtest_feedback.get('sweep_total_tested', 0) or 0)} "
                        f"({int(backtest_feedback.get('sweep_success', 0) or 0)} ok / "
                        f"{int(backtest_feedback.get('sweep_failed', 0) or 0)} échec)"
                    ),
                    (
                        " - Meilleurs paramètres: "
                        + json.dumps(
                            backtest_feedback.get("sweep_best_params", {}) or {},
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    ),
                ]
            )
            top_results = backtest_feedback.get("sweep_top_results", [])
            if isinstance(top_results, list):
                for rank, row in enumerate(top_results[:3], start=1):
                    if not isinstance(row, dict):
                        continue
                    lines.append(
                        "  - Top {rank}: score={score:.2f} sharpe={sharpe:.3f} "
                        "ret={ret:+.2f}% dd={dd:.2f}% trades={trades} params={params}".format(
                            rank=rank,
                            score=float(row.get("telemetry_score", 0.0) or 0.0),
                            sharpe=float(row.get("sharpe_ratio", 0.0) or 0.0),
                            ret=float(row.get("total_return_pct", 0.0) or 0.0),
                            dd=float(row.get("max_drawdown_pct", 0.0) or 0.0),
                            trades=int(row.get("total_trades", 0) or 0),
                            params=json.dumps(
                                row.get("params", {}) or {},
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        )
                    )

        # Historique complet de la session (tendance visible itération par itération)
        if len(session.iterations) > 1:
            lines.append("")
            lines.append("### Historique de la session")
            for prev_it in session.iterations:
                if prev_it.backtest_result:
                    pm = prev_it.backtest_result.metrics or {}
                    ps = float(pm.get("sharpe_ratio", 0) or 0)
                    pr = float(pm.get("total_return_pct", 0) or 0)
                    pd_ = float(pm.get("max_drawdown_pct", 0) or 0)
                    pt = int(pm.get("total_trades", 0) or 0)
                    pwr = float(pm.get("win_rate_pct", 0) or 0)
                    best_mark = (
                        " ★"
                        if session.best_iteration is not None
                        and prev_it.iteration == session.best_iteration.iteration
                        else ""
                    )
                    lines.append(
                        f"  iter {prev_it.iteration}{best_mark}: "
                        f"Sharpe={ps:.3f} Ret={pr:+.2f}% DD={pd_:.1f}% "
                        f"WR={pwr:.1f}% Trades={pt} "
                        f"→ {prev_it.decision or '?'} [{prev_it.diagnostic_category or '-'}]"
                        + (f" indicators=[{', '.join(prev_it.used_indicators)}]" if prev_it.used_indicators else "")
                    )
                else:
                    lines.append(
                        f"  iter {prev_it.iteration}: ⚠️ pas de backtest"
                        + (f" ({prev_it.error[:60]})" if prev_it.error else "")
                    )
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
                    f"Il reste {remaining} itérations disponibles. "
                    "RÈGLE STRICTE pour 'stop': réservé uniquement quand (a) le compte est ruiné "
                    "ET toutes les tentatives répétées échouent de la même façon depuis ≥3 itérations, "
                    "OU (b) aucun trade n'a été généré depuis ≥3 itérations consécutives sans amélioration. "
                    "RÈGLE 'continue': utilise 'continue' pour TOUTES les autres situations — "
                    "résultats négatifs sur 1-2 itérations, overtrading, mauvais win rate, "
                    "drawdown élevé — ce sont des problèmes réparables. "
                    "RÈGLE 'accept': uniquement si Sharpe atteint la cible ET stratégie robuste (>20 trades, DD<40%). "
                    "Ne stoppe JAMAIS après une seule itération négative. "
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
- Prefer compact strategies, but allow 1 to 5 indicators when justified.
- It is valid to remove an indicator, replace one, or add one if that materially improves the hypothesis.
- Include realistic default_params with sensible ranges in parameter_specs
- parameter_specs drive a limited Builder sweep after code generation; keep the range compact and focus on 2 to 4 impactful numeric params
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

    def _run_backtest_with_optional_sweep(
        self,
        strategy_cls: type,
        data: pd.DataFrame,
        proposal: Dict[str, Any],
        *,
        initial_capital: float = 10000.0,
        symbol: str = "UNKNOWN",
        timeframe: str = "1h",
        fees_bps: float = 10.0,
        slippage_bps: float = 5.0,
        direction_constraint: str = "long_short",
        target_sharpe: float = 1.0,
    ) -> tuple[Any, Dict[str, Any]]:
        base_params = dict(_sanitize_param_mapping(proposal.get("default_params")))
        sweep_plan = _build_builder_sweep_plan(proposal)
        if not sweep_plan.get("enabled"):
            bt_result = self._run_backtest(
                strategy_cls,
                data,
                base_params,
                initial_capital,
                symbol=symbol,
                timeframe=timeframe,
                fees_bps=fees_bps,
                slippage_bps=slippage_bps,
                direction_constraint=direction_constraint,
            )
            raw_result = getattr(bt_result, "run_result", None)
            if raw_result is not None and isinstance(getattr(raw_result, "meta", None), dict):
                raw_result.meta["builder_evaluation_mode"] = "single"
                raw_result.meta["params"] = dict(base_params)
            return bt_result, {
                "mode": "single",
                "params_used": dict(base_params),
                "sweep_skipped_reason": sweep_plan.get("reason", ""),
            }

        start = datetime.now()
        best_result = None
        best_params: Dict[str, Any] = {}
        best_selection_key = None
        best_score = float("-inf")
        success_count = 0
        fail_count = 0
        first_error: Optional[BaseException] = None
        successful_rows: List[Dict[str, Any]] = []

        for candidate_params in sweep_plan.get("param_grid", []):
            try:
                bt_result = self._run_backtest(
                    strategy_cls,
                    data,
                    dict(candidate_params),
                    initial_capital,
                    symbol=symbol,
                    timeframe=timeframe,
                    fees_bps=fees_bps,
                    slippage_bps=slippage_bps,
                    direction_constraint=direction_constraint,
                )
                metrics = dict(getattr(bt_result, "metrics", {}) or {})
                score_payload = compute_builder_telemetry_score(
                    metrics,
                    target_sharpe=target_sharpe,
                )
                selection_key = _builder_iteration_selection_key(
                    metrics,
                    is_fallback=False,
                    target_sharpe=target_sharpe,
                )
                success_count += 1
                successful_rows.append(
                    {
                        "params": dict(candidate_params),
                        "telemetry_score": score_payload.get("score"),
                        "sharpe_ratio": metrics.get("sharpe_ratio"),
                        "total_return_pct": metrics.get("total_return_pct"),
                        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                        "profit_factor": metrics.get("profit_factor"),
                        "total_trades": metrics.get("total_trades"),
                    }
                )
                if best_selection_key is None or selection_key > best_selection_key:
                    best_selection_key = selection_key
                    best_score = float(score_payload.get("score", float("-inf")) or float("-inf"))
                    best_result = bt_result
                    best_params = dict(candidate_params)
            except (
                ValueError,
                KeyError,
                RuntimeError,
                AttributeError,
                TypeError,
                IndexError,
                NameError,
            ) as exc:
                fail_count += 1
                if first_error is None:
                    first_error = exc

        if best_result is None:
            if first_error is not None:
                raise first_error
            raise RuntimeError("Aucune combinaison sweep exploitable")

        duration_ms = (datetime.now() - start).total_seconds() * 1000.0
        successful_rows.sort(
            key=lambda row: float(row.get("telemetry_score", float("-inf")) or float("-inf")),
            reverse=True,
        )

        raw_result = getattr(best_result, "run_result", None)
        if raw_result is not None and isinstance(getattr(raw_result, "meta", None), dict):
            raw_result.meta["builder_evaluation_mode"] = "sweep"
            raw_result.meta["builder_sweep_total_tested"] = int(
                len(sweep_plan.get("param_grid", []))
            )
            raw_result.meta["builder_sweep_success"] = int(success_count)
            raw_result.meta["builder_sweep_failed"] = int(fail_count)
            raw_result.meta["builder_sweep_best_params"] = dict(best_params)
            raw_result.meta["builder_sweep_parameter_values"] = dict(
                sweep_plan.get("parameter_values", {})
            )
            raw_result.meta["params"] = dict(best_params)

        return best_result, {
            "mode": "sweep",
            "params_used": dict(best_params),
            "sweep_total_tested": int(len(sweep_plan.get("param_grid", []))),
            "sweep_success": int(success_count),
            "sweep_failed": int(fail_count),
            "sweep_duration_ms": round(duration_ms, 3),
            "sweep_param_names": list(sweep_plan.get("param_names", [])),
            "sweep_candidate_values": dict(sweep_plan.get("parameter_values", {})),
            "sweep_best_params": dict(best_params),
            "sweep_top_results": successful_rows[:_BUILDER_SWEEP_TOP_RESULTS],
            "sweep_selection_score": best_score,
        }

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
        universe_mode: str = "canonical",
        universe_purpose: str = "builder",
        universe_strategy_type: str = "",
        universe_meta: Optional[Dict[str, Any]] = None,
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
            universe_mode: Mode d'univers (`canonical` par défaut)
            universe_purpose: Usage courant (builder/validation/graduation)
            universe_strategy_type: Type de stratégie normalisé si déjà connu
            universe_meta: Métadonnées additionnelles du filtrage univers

        Returns:
            BuilderSession avec l'historique complet et le meilleur résultat
        """
        from agents.builder_loop import run_builder_loop_v2

        raw_objective = str(objective or "")
        objective = sanitize_objective_text(
            raw_objective,
            enable_leakage_filter=self.ablation.is_enabled("prompt_leakage_filter"),
        )
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

        n_bars = len(data)
        date_range_start = ""
        date_range_end = ""
        try:
            idx = data.index
            if hasattr(idx, "min"):
                date_range_start = str(idx.min())[:19]
                date_range_end = str(idx.max())[:19]
        except (
            ValueError,
            KeyError,
            RuntimeError,
            AttributeError,
            TypeError,
            IndexError,
        ):
            pass

        session = BuilderSession(
            session_id=session_id,
            objective=objective,
            session_dir=session_dir,
            available_indicators=list(self.available_indicators),
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
            universe_mode=normalize_universe_mode(
                universe_mode,
                purpose=universe_purpose,
            ),
            universe_purpose=str(universe_purpose or "builder"),
            universe_strategy_type=infer_strategy_type(
                strategy_type=universe_strategy_type,
                objective=objective,
            ),
            universe_meta=(
                dict(universe_meta)
                if isinstance(universe_meta, dict)
                else {}
            ),
            builder_execution_mode=str(
                getattr(self, "builder_execution_mode", "mono_single_llm")
                or "mono_single_llm"
            ),
            orchestration_mode=str(
                getattr(self, "orchestration_mode", "single_llm")
                or "single_llm"
            ),
            instrumentation_enabled=bool(self.instrumentation.enabled),
            ablation_config=dict(self.ablation.get_config()),
            multi_llm_profile=str(
                getattr(self, "multi_llm_profile", "") or ""
            ),
            multi_llm_role_overrides=dict(
                getattr(self, "multi_llm_role_overrides", {}) or {}
            ),
            multi_llm_assignments=list(
                getattr(self, "multi_llm_assignments", []) or []
            ),
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
            universe_mode=session.universe_mode,
            strategy_type=session.universe_strategy_type,
            purpose=session.universe_purpose,
            objective=objective,
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
            session_id,
            objective,
            len(self.available_indicators),
        )

        # Charger l'historique de diversité au début du run
        try:
            from config.indicator_history import load_history, load_policy
            self._indicator_policy = load_policy()
            self._indicator_history = load_history(self._indicator_policy) if self._indicator_policy.get("enabled", True) else {}
        except Exception:
            self._indicator_history = {}

        model_name = getattr(getattr(self.llm, "config", None), "model", "?")
        thought_stream = ThoughtStream(session_id, objective, model_name)
        run_builder_loop_v2(
            self,
            session=session,
            data=data,
            initial_capital=initial_capital,
            thought_stream=thought_stream,
        )

        thought_stream.session_end(
            session.status,
            session.best_sharpe,
            len(session.iterations),
        )

        session.instrumentation_enabled = bool(self.instrumentation.enabled)
        session.ablation_config = dict(self.ablation.get_config())
        session.instrumentation_summary = (
            self.instrumentation.session_summary()
            if self.instrumentation.enabled
            else {}
        )
        session.restriction_events = dict(
            session.instrumentation_summary.get("restriction_events", {}) or {}
        )
        session.pipeline_traces_path = ""

        if self.instrumentation.enabled and self.instrumentation.traces:
            try:
                traces_path = session_dir / "pipeline_traces.json"
                self.instrumentation.export_traces_json(traces_path)
                session.pipeline_traces_path = traces_path.name
                logger.info(
                    "builder_instrumentation_exported path=%s traces=%d",
                    traces_path,
                    len(self.instrumentation.traces),
                )
            except (OSError, ValueError, TypeError):
                logger.warning(
                    "builder_instrumentation_export_failed session=%s",
                    session.session_id,
                    exc_info=True,
                )

        self._save_session_summary(session)

        logger.info(
            "strategy_builder_end session=%s status=%s best_sharpe=%.3f iters=%d",
            session.session_id,
            session.status,
            session.best_sharpe,
            len(session.iterations),
        )
        self._emit_progress(
            "session_done",
            status=session.status,
            total_iterations=len(session.iterations),
            best_sharpe=session.best_sharpe,
        )

        # Mettre à jour l'historique de diversité après la session
        try:
            policy = getattr(self, "_indicator_policy", {})
            if policy.get("enabled", True):
                from config.indicator_history import (
                    infer_families_from_indicators,
                    update_history,
                )
                all_used: List[str] = []
                for it in session.iterations:
                    for ind in (it.used_indicators or []):
                        key = str(ind).strip().lower()
                        if key and key not in all_used:
                            all_used.append(key)
                families_used = infer_families_from_indicators(all_used)
                update_history(all_used, families_used=families_used, policy=policy)
                logger.debug(
                    "indicator_history_updated session=%s indicators=%s families=%s",
                    session.session_id,
                    all_used,
                    families_used,
                )
        except Exception:
            logger.debug("indicator_history_update_failed", exc_info=True)

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
            phase_feedback = (
                it.phase_feedback.to_dict()
                if hasattr(it.phase_feedback, "to_dict")
                else (it.phase_feedback if isinstance(it.phase_feedback, dict) else {})
            )
            backtest_feedback = (
                phase_feedback.get("backtest", {})
                if isinstance(phase_feedback, dict)
                else {}
            )
            if not isinstance(backtest_feedback, dict):
                backtest_feedback = {}
            score_payload = (
                compute_builder_telemetry_score(
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
                "evaluation_mode": backtest_feedback.get("mode"),
                "params_used": backtest_feedback.get("params_used"),
                "sweep_total_tested": backtest_feedback.get("sweep_total_tested"),
                "sweep_success": backtest_feedback.get("sweep_success"),
                "sweep_failed": backtest_feedback.get("sweep_failed"),
                "sharpe": metrics.get("sharpe_ratio") if metrics else None,
                "total_pnl": metrics.get("total_pnl") if metrics else None,
                "return_pct": metrics.get("total_return_pct") if metrics else None,
                "max_drawdown_pct": metrics.get("max_drawdown_pct") if metrics else None,
                "profit_factor": metrics.get("profit_factor") if metrics else None,
                "win_rate_pct": metrics.get("win_rate_pct") if metrics else None,
                "trades": metrics.get("total_trades") if metrics else None,
                "telemetry_score": score_payload.get("score") if score_payload else None,
                "continuous_score": score_payload.get("score") if score_payload else None,
                "telemetry_breakdown": {
                    "components": score_payload.get("components", {}) if score_payload else {},
                    "penalties": score_payload.get("penalties", {}) if score_payload else {},
                    "drawdown_excess_pct": score_payload.get("drawdown_excess_pct", 0.0) if score_payload else 0.0,
                }
                if score_payload
                else None,
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
                "phase_feedback": phase_feedback or None,
            }
            iteration_rows.append(row)

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
            [row for row in iteration_rows if row.get("sharpe") is not None],
            key=lambda row: _builder_iteration_selection_key(
                {
                    "sharpe_ratio": row.get("sharpe"),
                    "total_return_pct": row.get("return_pct"),
                    "max_drawdown_pct": row.get("max_drawdown_pct"),
                    "profit_factor": row.get("profit_factor"),
                    "total_trades": row.get("trades"),
                    "win_rate_pct": row.get("win_rate_pct"),
                },
                is_fallback=bool(row.get("is_fallback", False)),
                target_sharpe=session.target_sharpe,
            ),
            reverse=True,
        )
        for rank, row in enumerate(leaderboard, start=1):
            row["rank"] = rank

        summary = {
            "session_id": session.session_id,
            "objective": session.objective,
            "status": session.status,
            "best_sharpe": session.best_sharpe,
            "best_telemetry_score": session.best_score,
            "best_score": session.best_score,
            "symbol": session.symbol,
            "timeframe": session.timeframe,
            "n_bars": session.n_bars,
            "date_range_start": session.date_range_start,
            "date_range_end": session.date_range_end,
            "initial_capital": session.initial_capital,
            "fees_bps": session.fees_bps,
            "slippage_bps": session.slippage_bps,
            "universe_mode": session.universe_mode,
            "universe_purpose": session.universe_purpose,
            "universe_strategy_type": session.universe_strategy_type,
            "universe_meta": session.universe_meta,
            "start_time": session.start_time.isoformat(),
            "auto_reset_count": session.auto_reset_count,
            "recovery_events": session.recovery_events,
            "total_iterations": len(session.iterations),
            "available_indicators": session.available_indicators,
            "builder_execution_mode": session.builder_execution_mode,
            "orchestration_mode": session.orchestration_mode,
            "instrumentation_enabled": session.instrumentation_enabled,
            "instrumentation_summary": session.instrumentation_summary,
            "ablation_config": session.ablation_config,
            "pipeline_traces_path": session.pipeline_traces_path,
            "restriction_events": session.restriction_events,
            "multi_llm_profile": (
                session.multi_llm_profile
                if session.orchestration_mode == "multi_llm"
                else ""
            ),
            "multi_llm_role_overrides": (
                session.multi_llm_role_overrides
                if session.orchestration_mode == "multi_llm"
                else {}
            ),
            "multi_llm_assignments": (
                session.multi_llm_assignments
                if session.orchestration_mode == "multi_llm"
                else []
            ),
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
                "evaluation_mode",
                "sweep_total_tested",
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
                "",
                "| Rank | Iter | Sharpe | Return % | Max DD % | PF | Trades | Decision | Category |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
            for row in leaderboard:
                lines.append(
                    "| {rank} | {it} | {sharpe:.3f} | {ret:+.2f}% | {dd:.2f}% | {pf:.2f} | {trades} | {decision} | {cat} |".format(
                        rank=int(row.get("rank", 0) or 0),
                        it=int(row.get("iteration", 0) or 0),
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
# Générateurs d'objectifs pour le mode autonome (delegated)
# ---------------------------------------------------------------------------

def generate_random_objective(
    symbol: "str | List[str]" = "BTCUSDC",
    timeframe: "str | List[str]" = "1h",
    available_indicators: Optional[List[str]] = None,
) -> str:
    from agents.builder_objectives import generate_random_objective as _impl

    return _impl(
        symbol=symbol,
        timeframe=timeframe,
        available_indicators=available_indicators,
    )


def generate_llm_objective(
    llm_client: Any,
    symbol: "str | List[str]" = "BTCUSDC",
    timeframe: "str | List[str]" = "1h",
    available_indicators: Optional[List[str]] = None,
    stream_callback: Optional[Callable[[str, str], None]] = None,
    recent_markets: Optional[List[Tuple[str, str]]] = None,
) -> str:
    from agents.builder_objectives import generate_llm_objective as _impl

    return _impl(
        llm_client,
        symbol=symbol,
        timeframe=timeframe,
        available_indicators=available_indicators,
        stream_callback=stream_callback,
        recent_markets=recent_markets,
    )


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
    from agents.builder_objectives import generate_llm_objective_from_seed as _impl

    return _impl(
        llm_client,
        seed_objective=seed_objective,
        symbol=symbol,
        timeframe=timeframe,
        available_indicators=available_indicators,
        family=family,
        direction=direction,
        risk_profile=risk_profile,
        novelty_angle=novelty_angle,
        tags=tags,
        stream_callback=stream_callback,
        recent_markets=recent_markets,
    )


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
    from agents.builder_objectives import recommend_market_context as _impl

    return _impl(
        llm_client,
        objective=objective,
        candidate_symbols=candidate_symbols,
        candidate_timeframes=candidate_timeframes,
        default_symbol=default_symbol,
        default_timeframe=default_timeframe,
        stream_callback=stream_callback,
        recent_markets=recent_markets,
    )


def compile_proposal_to_code(proposal: Dict[str, Any], variant: int = 0) -> str:
    from agents.builder_objectives import compile_proposal_to_code as _impl

    return _impl(proposal, variant=variant)
