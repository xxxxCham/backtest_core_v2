# ruff: noqa: I001,F401
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
import importlib.util
import json
import os
import re
import shutil
import sys
import textwrap
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, cast

import numpy as np
import pandas as pd
from agents.llm_client import LLMClient, LLMConfig, LLMMessage, StreamAbortRequest, create_llm_client
from agents.llm_router import LLMTopologyConfig, build_phase1_topology
from agents.indicator_context import (
    build_indicator_selection_guide,
    get_indicator_builder_access_example,
    get_indicator_builder_stable_alias_map,
    rank_indicator_selection,
    shuffle_indicator_presentation_order,
)
from backtest.engine import BacktestEngine
from backtest.result_store import get_builder_sessions_dir
from indicators.registry import list_indicators
from indicators.schema import (
    DICT_INDICATOR_NAMES as SCHEMA_DICT_INDICATOR_NAMES,
    DICT_INDICATOR_OUTPUT_KEYS,
    INDICATOR_ACCESS_ALIASES,
    PARAMETER_ALIAS_ACCESS,
    SEMANTIC_INDICATOR_ALIASES,
)
from metrics_types import normalize_metrics
from utils.observability import generate_run_id, get_obs_logger
from utils.template import render_prompt

from agents.thought_stream import BuilderLiveEvent, ThoughtStream
from agents.pipeline_instrumentation import (
    PipelineInstrumentation,
    AblationController,
)

from agents.builder_state import (
    BuilderIteration,
    BuilderSession,
    IterationContext,
)
from config.market_selection import (
    evaluate_market_dataset,
    infer_strategy_type,
    normalize_universe_mode,
)
# pylint: disable=broad-except
# pylint: disable=protected-access

logger = get_obs_logger(__name__)

# Dossier racine des sandbox
SANDBOX_ROOT = get_builder_sessions_dir()

# Nombre max d'échecs consécutifs avant arrêt (circuit breaker)
MAX_CONSECUTIVE_FAILURES = 3
# Nombre minimum de lignes pour considérer du code comme non-vide
MIN_CODE_LINES = 10
# Nombre max de tentatives de réalignement quand le LLM répond hors phase
MAX_PHASE_REALIGN_ATTEMPTS = 2
# -- Constantes importées depuis builder_constants (source unique) --
from agents.builder_constants import (  # noqa: E402
    DEFAULT_MAX_ITERATIONS,
    GENERATED_CLASS_NAME,
    POSITIVE_PROGRESS_GATE_CHECKPOINTS,
    _AST_PARSE_RECOVERABLE_EXCEPTIONS,
)

from agents.builder_code_validation import (  # noqa: E402
    validate_generated_code,
    _get_known_indicator_names,
    _is_allowed_import,
    _validate_signal_loop_and_warmup,
)

from agents.builder_code_repair import (  # noqa: E402
    _repair_code,
    _infer_required_indicator_names_from_code,
    _inject_generate_signals_core_param_aliases,
    _inject_generate_signals_indicator_aliases,
    _inject_generate_signals_indicator_bindings,
    _rewrite_safe_dict_indicator_comparisons,
    _rewrite_invalid_indicator_accesses,
)

# -- Fonctions scoring/diagnostic re-exportées depuis builder_diagnostics --
from agents.builder_diagnostics import (  # noqa: E402
    _builder_iteration_selection_key,
    _count_positive_iterations,
    _is_accept_candidate,
    _ranking_sharpe,
    classify_builder_candidate_tier,
    compute_builder_telemetry_score,
    compute_continuous_builder_score,
)

# -- Utilitaires AST et parsing importés depuis builder_ast_utils --
from agents.builder_ast_utils import (  # noqa: E402
    _collect_bound_names,
    _collect_name_load_store_sets,
    _const_value,
    _extract_declared_required_indicators,
    _extract_default_params_signature,
    _extract_generate_signals_logic_block,
    _extract_json_from_response,
    _extract_python_from_response,
    _indicator_name_from_get_call,
    _indicator_name_from_subscript,
    _is_np_nan_to_num_call,
    _iter_generate_signals_functions,
    _normalize_required_indicator_names,
)

# -- Parsing d'objectifs et noms d'indicateurs depuis builder_objective_parser --
from agents.builder_objective_parser import (  # noqa: E402
    _canonicalize_indicator_name,
    _extract_objective_indicator_names,
    sanitize_objective_text,
)

# -- I/O de session depuis builder_session_io --
from agents.builder_session_io import (  # noqa: E402
    BUILDER_MEMORY_CODE_MAX_CHARS,
    BUILDER_MEMORY_PROPOSAL_MAX_CHARS,
    create_session_id,
    format_builder_cross_session_memory,
    get_session_dir,
    load_builder_cross_session_memory,
    persist_session_strategy_code,
    persist_runtime_checkpoint,
    safe_save_session_summary,
    save_session_summary,
    attempt_session_auto_reset,
)

from agents.builder_state import (  # noqa: E402
    _select_session_recovery_anchor,
)

# -- Utilitaires texte depuis builder_text_utils --
from agents.builder_text_utils import (  # noqa: E402
    _err,
    _format_python_dict_literal,
    _normalize_llm_text,
    _looks_like_log_pollution,
)

# -- Helpers de proposition depuis builder_proposal_helpers --
from agents.builder_proposal_helpers import (  # noqa: E402
    _build_builder_sweep_plan,
    _infer_direction_constraint_from_objective,
    _normalize_change_type,
    _normalize_proposal_keys,
    _proposal_changes_indicator_set_in_params_mode,
    _proposal_error_code,
    _proposal_has_meaningful_param_delta,
    _proposal_issues,
    _sanitize_param_mapping,
    _sanitize_proposal_payload,
)

from agents.builder_model_profiles import (  # noqa: E402
    build_builder_model_prompt_guidance,
)

# -- Helpers de politique depuis builder_policy_helpers --
from agents.builder_policy_helpers import (  # noqa: E402
    _build_stagnation_branch_specs,
    _policy_change_type_override,
    _previous_iteration_indicators,
    _requires_indicator_exploration,
    _select_best_branch_candidate,
    _should_enable_stagnation_branching,
    _should_trip_logic_stagnation_circuit,
)

PROPOSAL_REALIGN_ATTEMPTS = 1
MIN_BUILDER_BARS = 300
MIN_SIGNAL_COUNT_FOR_DENSITY_PRECHECK = int(os.getenv("BACKTEST_BUILDER_MIN_SIGNAL_COUNT_FOR_DENSITY_PRECHECK", "200"))
MAX_SIGNAL_DENSITY_PRECHECK = float(os.getenv("BACKTEST_BUILDER_MAX_SIGNAL_DENSITY_PRECHECK", "0.55"))
MAX_SIGNAL_TRANSITION_DENSITY_PRECHECK = float(
    os.getenv(
        "BACKTEST_BUILDER_MAX_SIGNAL_TRANSITION_DENSITY_PRECHECK",
        "0.30",
    )
)
MAX_REPEATED_SAME_SIGNAL_RATIO_PRECHECK = float(
    os.getenv(
        "BACKTEST_BUILDER_MAX_REPEATED_SAME_SIGNAL_RATIO_PRECHECK",
        "0.65",
    )
)
# Limite la fenêtre du précheck (dry-run signal density) aux N dernières bougies.
# Sans troncature, calculate_indicators + generate_signals tournent sur tout le
# dataset, ce qui rend l'optimisation 0-trade peu rentable sur 5m/15m. 5000 = ~17j
# de 5m, ~52j de 15m, ~104j de 30m, ~208j de 1h, ~833j de 4h : suffisant pour
# observer si la logique de signaux se déclenche du tout. 0 = pas de troncature.
PRECHECK_MAX_BARS = int(os.getenv("BACKTEST_BUILDER_PRECHECK_MAX_BARS", "5000"))

# Per-phase LLM call timeouts (seconds).
# Prevents single outlier calls (e.g. 8-minute code generation) from
# blocking the entire session. Env-overridable.
_LLM_PHASE_TIMEOUT_PROPOSAL = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_PROPOSAL", "120"))
_LLM_PHASE_TIMEOUT_CODE = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_CODE", "180"))
_LLM_PHASE_TIMEOUT_ANALYSIS = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_ANALYSIS", "90"))
_LLM_PHASE_TIMEOUT_DEFAULT = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_DEFAULT", "120"))
_LLM_PHASE_TIMEOUT_PROPOSAL_REALIGN = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_PROPOSAL_REALIGN", "45"))
_LLM_PHASE_TIMEOUT_RETRY_PROPOSAL = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_RETRY_PROPOSAL", "45"))
_LLM_PHASE_TIMEOUT_RETRY_CODE = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_RETRY_CODE", "60"))
_LLM_PHASE_TIMEOUT_RETRY_CODE_RUNTIME = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_RETRY_CODE_RUNTIME", "90"))
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
_BUILDER_MAX_UNTRADABLE_RATIO = float(os.getenv("BACKTEST_BUILDER_MAX_UNTRADABLE_RATIO", "0.25"))
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


def _resume_safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resume_safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _resume_parse_datetime(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.now()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now()


def _resume_session_id(parent_session_id: str, mode: str) -> str:
    parent_slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(parent_session_id or "session")).strip("_")
    if not parent_slug:
        parent_slug = "session"
    parent_slug = parent_slug[-52:]
    mode_slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(mode or "resume")).strip("_") or "resume"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_resume_{mode_slug}_{parent_slug}"


def _resume_strategy_path(source_session_dir: Path, iteration_num: int) -> Path | None:
    candidates = [
        source_session_dir / f"strategy_v{iteration_num}.py",
        source_session_dir / f"strategy_v{iteration_num:03d}.py",
    ]
    if iteration_num <= 0:
        candidates.append(source_session_dir / "strategy.py")
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _resume_strategy_code(source_session_dir: Path, iteration_num: int) -> str:
    candidate = _resume_strategy_path(source_session_dir, iteration_num)
    if candidate is None and iteration_num > 0:
        candidate = source_session_dir / "strategy.py"
    if candidate is None or not candidate.exists() or not candidate.is_file():
        return ""
    try:
        return candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _resume_metrics_from_iteration_row(row: dict[str, Any]) -> dict[str, Any]:
    metrics = {
        "sharpe_ratio": row.get("sharpe"),
        "total_pnl": row.get("total_pnl"),
        "total_return_pct": row.get("return_pct"),
        "max_drawdown_pct": row.get("max_drawdown_pct"),
        "profit_factor": row.get("profit_factor"),
        "win_rate_pct": row.get("win_rate_pct"),
        "total_trades": row.get("trades"),
    }
    return {key: value for key, value in metrics.items() if value is not None}


def _resume_load_seed_iterations(summary: dict[str, Any], source_session_dir: Path) -> list[BuilderIteration]:
    rows = summary.get("iterations") if isinstance(summary.get("iterations"), list) else []
    seed_iterations: list[BuilderIteration] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        iteration_num = _resume_safe_int(row.get("iteration"))
        if iteration_num <= 0:
            continue
        metrics = _resume_metrics_from_iteration_row(row)
        phase_feedback = row.get("phase_feedback") if isinstance(row.get("phase_feedback"), dict) else {}
        seed_iterations.append(
            BuilderIteration(
                iteration=iteration_num,
                hypothesis=str(row.get("hypothesis") or ""),
                code=_resume_strategy_code(source_session_dir, iteration_num),
                backtest_result=SimpleNamespace(metrics=metrics) if metrics else None,
                error=str(row.get("error") or "") or None,
                decision=str(row.get("decision") or ""),
                change_type=str(row.get("change_type") or ""),
                diagnostic_category=str(row.get("diagnostic_category") or ""),
                phase_feedback=phase_feedback,
                timestamp=_resume_parse_datetime(row.get("timestamp")),
                is_fallback=bool(row.get("is_fallback", False)),
                used_indicators=[
                    str(indicator)
                    for indicator in list(row.get("used_indicators") or [])
                    if str(indicator or "").strip()
                ],
            ),
        )
    return sorted(seed_iterations, key=lambda candidate: int(candidate.iteration or 0))


def _resume_copy_strategy_files(source_session_dir: Path, target_session_dir: Path) -> None:
    target_session_dir.mkdir(parents=True, exist_ok=True)
    for source_path in sorted(source_session_dir.glob("strategy*.py")):
        if not source_path.is_file():
            continue
        target_path = target_session_dir / source_path.name
        if target_path.exists():
            continue
        try:
            shutil.copy2(source_path, target_path)
        except OSError:
            logger.debug(
                "builder_resume_strategy_copy_failed source=%s target=%s",
                source_path,
                target_path,
                exc_info=True,
            )


def _resume_seed_session_state(session: BuilderSession, seed_iterations: list[BuilderIteration]) -> None:
    session.iterations = sorted(seed_iterations, key=lambda candidate: int(candidate.iteration or 0))
    for iteration in session.iterations:
        metrics = (
            iteration.backtest_result.metrics
            if iteration.backtest_result is not None
            and isinstance(getattr(iteration.backtest_result, "metrics", None), dict)
            else {}
        )
        if not metrics:
            continue
        sharpe = _resume_safe_float(metrics.get("sharpe_ratio"), float("-inf"))
        if np.isfinite(sharpe) and sharpe > getattr(session, "best_raw_sharpe", float("-inf")):
            session.best_raw_sharpe = sharpe
        candidate_key = _builder_iteration_selection_key(
            metrics,
            is_fallback=bool(iteration.is_fallback),
            target_sharpe=session.target_sharpe,
        )
        best_metrics = (
            session.best_iteration.backtest_result.metrics
            if session.best_iteration is not None
            and session.best_iteration.backtest_result is not None
            and isinstance(getattr(session.best_iteration.backtest_result, "metrics", None), dict)
            else {}
        )
        best_key = (
            _builder_iteration_selection_key(
                best_metrics,
                is_fallback=bool(getattr(session.best_iteration, "is_fallback", False)),
                target_sharpe=session.target_sharpe,
            )
            if best_metrics
            else None
        )
        if session.best_iteration is None or best_key is None or candidate_key > best_key:
            session.best_iteration = iteration
            score_payload = compute_builder_telemetry_score(
                metrics,
                target_sharpe=session.target_sharpe,
            )
            session.best_score = float(score_payload.get("score", float("-inf")) or float("-inf"))
            session.best_sharpe = sharpe


def _is_interpreter_shutdown_runtime_error(exc: BaseException) -> bool:
    """Détecte le RuntimeError typique émis pendant l'arrêt de l'interpréteur."""
    if not isinstance(exc, RuntimeError):
        return False
    message = str(exc).lower()
    return "interpreter shutdown" in message or "cannot schedule new futures after interpreter shutdown" in message


def _is_vision_model(model_name: str) -> bool:
    model_lower = str(model_name or "").lower()
    return any(
        pattern in model_lower
        for pattern in (
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
    model_name = str(getattr(getattr(llm_client, "config", None), "model", "") or "")
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
_INDICATOR_PERFORMANCE_PRIORS_CACHE: Dict[str, float] | None = None

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
    "market_volatility": "indicators['vix']",
    "volatility": "indicators['vix']",
    "vix_proxy": "indicators['vix']",
    "mci": "indicators['choppiness_index']",
    "chop": "indicators['choppiness_index']",
    "choppiness": "indicators['choppiness_index']",
    "market_choppiness_index": "indicators['choppiness_index']",
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
    "market_volatility": "indicators['vix']",
    "volatility": "indicators['vix']",
    "vix_proxy": "indicators['vix']",
    "implied_volatility_proxy": "indicators['vix']",
    "mci": "indicators['choppiness_index']",
    "chop": "indicators['choppiness_index']",
    "choppiness": "indicators['choppiness_index']",
    "market_choppiness_index": "indicators['choppiness_index']",
    "trix_line": "indicators['trix']",
    "trix_value": "indicators['trix']",
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

# Active source of truth: indicators.schema. These module-level names remain
# for compatibility, but their runtime content is schema-derived.
_DICT_INDICATOR_NAMES = set(SCHEMA_DICT_INDICATOR_NAMES)
_DICT_INDICATOR_ALLOWED_KEYS = {name: set(keys) for name, keys in DICT_INDICATOR_OUTPUT_KEYS.items()}
_INDICATOR_ALIAS_HINTS = dict(SEMANTIC_INDICATOR_ALIASES)
_SEMANTIC_INDICATOR_ALIAS_HINTS = dict(SEMANTIC_INDICATOR_ALIASES)
_INDICATOR_ACCESS_REWRITE_HINTS = dict(INDICATOR_ACCESS_ALIASES)
_PARAM_ACCESS_REWRITE_HINTS = dict(PARAMETER_ALIAS_ACCESS)

def _safe_path_mode(universe_purpose: str = "") -> str:
    """Retourne le mode safe-path normalisé: off|prefer|strict."""
    raw_env = os.getenv(SAFE_PATH_MODE_ENV)
    if raw_env is None:
        return "prefer" if str(universe_purpose or "").strip().lower() == "builder_autonomous" else "off"
    raw = raw_env.strip().lower()
    if raw in {"prefer", "strict", "off"}:
        return raw
    if raw in {"1", "true", "yes", "on"}:
        return "prefer"
    return "off"


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


# ---------------------------------------------------------------------------
# Validation du code généré
# ---------------------------------------------------------------------------


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

    _node_args = getattr(node, "args", None)
    if _is_np_nan_to_num_call(node) and _node_args:
        parent = _binding_info_for_expr(_node_args[0], bindings)
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
    return False, f"{symbol}/{timeframe}: " + " | ".join(
        _format_builder_dataset_exclusion_reason(str(reason)) for reason in reasons
    )


def _format_builder_dataset_exclusion_reason(reason: str) -> str:
    """Garde les diagnostics Builder compatibles avec l'UI/tests historiques."""
    text = str(reason or "").strip()
    lower = text.lower()
    translations = (
        ("continuous segment insufficient", "segment continu insuffisant"),
        ("dataset insufficient", "dataset insuffisant"),
        ("tradable ratio too low", "trop peu tradable"),
        ("outside canonical universe", "hors univers canonique"),
        ("listing too recent", "listing trop recent"),
        ("tradable ratio below canonical threshold", "ratio tradable sous seuil canonique"),
        ("median dollar volume insufficient", "volume dollar median insuffisant"),
        ("median volume insufficient", "volume median insuffisant"),
    )
    for prefix, replacement in translations:
        if lower.startswith(prefix):
            return replacement + text[len(prefix) :]
    return text


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


def _build_generate_signals_indicator_binding_lines(required_indicators: Optional[List[str]]) -> List[str]:
    binding_lines: List[str] = []
    seen_lines: set[str] = set()

    for indicator_name in _normalize_required_indicator_names(required_indicators):
        if indicator_name in _DICT_INDICATOR_NAMES:
            access_example = get_indicator_builder_access_example(indicator_name)
            raw_lines = re.split(r";\s*|\n+", access_example)
            candidate_lines = [line.strip() for line in raw_lines if line.strip()]
        else:
            candidate_lines = [f"{indicator_name} = np.nan_to_num(indicators['{indicator_name}'])"]

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
        return False, _err(
            ERR_SIG, "Usage pandas direct sur `signals` interdit; utiliser des masques numpy/vectorises."
        )
    if re.search(r"\[['\"][^'\"]*\|[^'\"]*['\"]\]", logic):
        return False, _err(
            ERR_IND, "Sous-cles concatenees avec `|` interdites; acceder a une seule sous-cle a la fois."
        )
    if re.search(r"\bcrosses_(?:above|below|over|under)[a-z_]*\b", logic):
        return False, _err(
            ERR_SIG,
            "Pseudo-helper `crosses_*` interdit; exprimer le croisement avec np.roll et comparaisons explicites.",
        )
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
        f"    {line}" if line.strip() else "" for line in candidate.splitlines()
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


def _sanitize_indicator_params_for_code(
    raw: Any,
    required_indicators: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Normalise les `indicator_params` d'une proposition pour le code généré."""
    if not isinstance(raw, dict) or not raw:
        return {}
    known = {str(ind or "").strip().lower() for ind in required_indicators if str(ind or "").strip()}
    sanitized: Dict[str, Dict[str, Any]] = {}
    for raw_name, raw_params in raw.items():
        if not isinstance(raw_name, str):
            continue
        indicator_name = _canonicalize_indicator_name(raw_name, known=known) or raw_name.strip().lower()
        if not indicator_name or (known and indicator_name not in known):
            continue
        params = _sanitize_param_mapping(raw_params)
        if params:
            sanitized[indicator_name] = params
    return sanitized


def _format_indicator_params_method_code(
    indicator_params: Dict[str, Dict[str, Any]],
) -> str:
    """Construit une surcharge `get_indicator_params` pour préserver le raisonnement LLM."""
    if not indicator_params:
        return ""
    literal = _format_python_dict_literal(indicator_params)
    literal_lines = literal.splitlines() or ["{}"]
    if len(literal_lines) == 1:
        static_params_block = f"        static_params = {literal_lines[0]}\n"
    else:
        static_params_block = f"        static_params = {literal_lines[0]}\n"
        static_params_block += "".join(f"        {line}\n" for line in literal_lines[1:])
    return (
        "    def get_indicator_params(self, indicator_name: str, params: Dict[str, Any]) -> Dict[str, Any]:\n"
        f"{static_params_block}"
        "        key = str(indicator_name or '').strip().lower()\n"
        "        base_params = super().get_indicator_params(indicator_name, params)\n"
        "        merged = dict(static_params.get(key, {}))\n"
        "        merged.update(base_params)\n"
        "        return merged\n\n"
    )


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
    indicator_params = _sanitize_indicator_params_for_code(
        proposal.get("indicator_params"),
        required_indicators,
    )
    indicator_params_method_block = _format_indicator_params_method_code(indicator_params)
    normalized_logic = textwrap.dedent(llm_logic).strip("\n")
    logic_lines = normalized_logic.splitlines() if normalized_logic else ["pass"]
    logic_block = "\n".join(f"        {line}" if line.strip() else "" for line in logic_lines)
    indicator_binding_lines = _build_generate_signals_indicator_binding_lines(required_indicators)
    indicator_binding_block = "".join(f"        {line}\n" for line in indicator_binding_lines)
    direction_block = ""
    if direction_constraint == "long_only":
        direction_block = "        # Objective constraint: long-only\n        signals[signals < 0.0] = 0.0\n"
    elif direction_constraint == "short_only":
        direction_block = "        # Objective constraint: short-only\n        signals[signals > 0.0] = 0.0\n"

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
        f"{indicator_params_method_block}"
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


# ── Blocs communs aux variantes de fallback déterministe ──
_FB_PREAMBLE = (
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
)

_FB_INIT_SLTP_COLS = (
    "        df.loc[:, 'bb_stop_long'] = np.nan\n"
    "        df.loc[:, 'bb_tp_long'] = np.nan\n"
    "        df.loc[:, 'bb_stop_short'] = np.nan\n"
    "        df.loc[:, 'bb_tp_short'] = np.nan\n"
)

_FB_ENTRY_FILTER = (
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


def _fb_extract_indicator(name: str, kind: str = "array", fallback_val: str = "0.0") -> str:
    """Génère le code d'extraction d'un indicateur pour le fallback déterministe."""
    var = name.replace(".", "_")
    if kind == "dict_field":
        return ""  # handled inline by callers needing dict subfields
    return (
        f"        {var}_raw = indicators.get('{name}')\n"
        f"        if isinstance({var}_raw, np.ndarray):\n"
        f"            {var} = np.nan_to_num({var}_raw.astype(np.float64))\n"
        f"        else:\n"
        f"            {var} = np.full(n, {fallback_val})\n"
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
    safe_used = _normalize_required_indicator_names(cast(Optional[List[str]], used if isinstance(used, list) else None))
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
    direction_constraint = str(proposal.get("direction_constraint", "long_short") or "long_short").strip().lower()

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
        variant_extract = (
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
        )
        variant_conditions = (
            "        adx_threshold = float(params.get('adx_threshold', 20.0))\n"
            "        bull = direction > 0\n"
            "        bear = direction < 0\n"
            "        bull_prev = np.roll(bull, 1)\n"
            "        bear_prev = np.roll(bear, 1)\n"
            "        bull_prev[:1] = False\n"
            "        bear_prev[:1] = False\n"
            "        long_cond = bull & (~bull_prev) & (adx >= adx_threshold)\n"
            "        short_cond = bear & (~bear_prev) & (adx >= adx_threshold)\n"
        )
    elif effective_variant == 2:
        # ── Variante 2: momentum RSI/EMA ──
        for needed in ("rsi", "ema", "atr"):
            if needed not in safe_used:
                safe_used.append(needed)
        default_params.setdefault("rsi_mid", 50.0)
        default_params.setdefault("ema_period", 50)
        variant_extract = (
            _fb_extract_indicator("rsi", fallback_val="50.0")
            + "        ema_raw = indicators.get('ema')\n"
            "        if isinstance(ema_raw, np.ndarray):\n"
            "            ema = np.nan_to_num(ema_raw.astype(np.float64))\n"
            "        else:\n"
            "            ema = close.copy()\n"
        )
        variant_conditions = (
            "        rsi_mid = float(params.get('rsi_mid', 50.0))\n"
            "        long_cond = (rsi > rsi_mid) & (close > ema)\n"
            "        short_cond = (rsi < rsi_mid) & (close < ema)\n"
        )
    elif effective_variant == 3:
        # ── Variante 3: breakout Donchian/ADX ──
        for needed in ("donchian", "adx", "atr"):
            if needed not in safe_used:
                safe_used.append(needed)
        default_params.setdefault("adx_threshold", 18.0)
        variant_extract = (
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
        )
        variant_conditions = (
            "        adx_threshold = float(params.get('adx_threshold', 18.0))\n"
            "        dc_upper_prev = np.roll(dc_upper, 1)\n"
            "        dc_lower_prev = np.roll(dc_lower, 1)\n"
            "        dc_upper_prev[:1] = dc_upper[:1]\n"
            "        dc_lower_prev[:1] = dc_lower[:1]\n"
            "        long_cond = (close > dc_upper_prev) & (adx >= adx_threshold)\n"
            "        short_cond = (close < dc_lower_prev) & (adx >= adx_threshold)\n"
        )
    else:
        # ── Variante 0: mean-reversion RSI/Bollinger ──
        for needed in ("rsi", "bollinger", "atr"):
            if needed not in safe_used:
                safe_used.append(needed)
        default_params.setdefault("rsi_oversold", 30)
        default_params.setdefault("rsi_overbought", 70)
        variant_extract = (
            _fb_extract_indicator("rsi", fallback_val="50.0")
            + "        bb_raw = indicators.get('bollinger')\n"
            "        has_bb = isinstance(bb_raw, dict)\n"
            "        if has_bb:\n"
            "            bb_lower = np.nan_to_num(bb_raw.get('lower', np.zeros(n)).astype(np.float64))\n"
            "            bb_upper = np.nan_to_num(bb_raw.get('upper', np.zeros(n)).astype(np.float64))\n"
            "        else:\n"
            "            bb_lower = np.full(n, 0.0)\n"
            "            bb_upper = np.full(n, np.inf)\n"
        )
        variant_conditions = (
            "        rsi_oversold = float(params.get('rsi_oversold', 30))\n"
            "        rsi_overbought = float(params.get('rsi_overbought', 70))\n"
            "        long_cond = (rsi < rsi_oversold) & (close <= bb_lower)\n"
            "        short_cond = (rsi > rsi_overbought) & (close >= bb_upper)\n"
        )

    signals_body = _FB_PREAMBLE + variant_extract + _FB_INIT_SLTP_COLS + variant_conditions + _FB_ENTRY_FILTER

    # ── Partie commune: assemblage du code final ──
    default_params_literal = _format_python_dict_literal(default_params)
    default_params_lines = default_params_literal.splitlines() or ["{}"]
    if len(default_params_lines) == 1:
        default_params_block = f"        return {default_params_lines[0]}\n\n"
    else:
        default_params_block = "        return " + default_params_lines[0] + "\n"
        default_params_block += "".join(f"        {line}\n" for line in default_params_lines[1:])
        default_params_block += "\n"
    direction_block = ""
    if direction_constraint == "long_only":
        direction_block = "        # Objective constraint: long-only\n        signals[signals < 0.0] = 0.0\n"
    elif direction_constraint == "short_only":
        direction_block = "        # Objective constraint: short-only\n        signals[signals > 0.0] = 0.0\n"
    indicator_binding_lines = _build_generate_signals_indicator_binding_lines(safe_used)
    indicator_binding_block = "".join(f"        {line}\n" for line in indicator_binding_lines)

    return (
        "from typing import Any, Dict, List\n\n"
        "import numpy as np\n"
        "import pandas as pd\n\n"
        "from utils.parameters import ParameterSpec\n"
        "from strategies.base import StrategyBase\n\n\n"
        f"class {GENERATED_CLASS_NAME}(StrategyBase):\n"
        "    def __init__(self):\n"
        f'        super().__init__(name="{strategy_name}")\n\n'
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


def _extract_phase_feedback(
    iteration: Optional["BuilderIteration"],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Extrait (phase_feedback_dict, backtest_feedback_dict) d'une itération.

    Élimine le pattern dupliqué 8 lignes `to_dict() / isinstance / .get("backtest")`
    utilisé dans _ask_proposal et _ask_analysis.
    """
    if iteration is None:
        return {}, {}
    raw = iteration.phase_feedback
    phase = raw.to_dict() if hasattr(raw, "to_dict") else (raw or {})
    if not isinstance(phase, dict):
        phase = {}
    backtest = phase.get("backtest", {})
    if not isinstance(backtest, dict):
        backtest = {}
    return phase, backtest


def _classify_raw_response_mismatch(raw: str, *, phase: str = "proposal") -> str:
    """Retourne le message de décalage de phase pour une réponse LLM brute."""
    if phase == "proposal":
        if _looks_like_python_code(raw):
            return "You answered with Python code, but this is PROPOSAL phase."
        if _looks_like_json_object(raw):
            return "You answered JSON but with missing/placeholder fields."
        return "You answered with text/explanations, not strict strategy JSON."
    # phase == "logic"
    if _looks_like_json_object(raw):
        return "You answered JSON/proposal content, but this is LOGIC phase."
    if _looks_like_python_code(raw):
        return "You answered Python but no usable logic body was extracted."
    return "You answered non-code text, not executable Python."


def _format_sweep_context_lines(backtest_feedback: Dict[str, Any]) -> List[str]:
    """Formate les lignes de contexte sweep pour l'analyse LLM."""
    lines: List[str] = [
        "",
        "### Sweep paramétrique",
        (
            f"- Combinaisons testées: "
            f"{int(backtest_feedback.get('sweep_total_tested', 0))} "
            f"({int(backtest_feedback.get('sweep_success', 0))} ok / "
            f"{int(backtest_feedback.get('sweep_failed', 0))} échec)"
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
    top_results = backtest_feedback.get("sweep_top_results", [])
    if isinstance(top_results, list):
        for rank, row in enumerate(top_results[:3], start=1):
            if not isinstance(row, dict):
                continue
            lines.append(
                "  - Top {rank}: score={score:.2f} sharpe={sharpe:.3f} "
                "ret={ret:+.2f}% dd={dd:.2f}% trades={trades} params={params}".format(
                    rank=rank,
                    score=float(row.get("telemetry_score", 0.0)),
                    sharpe=float(row.get("sharpe_ratio", 0.0)),
                    ret=float(row.get("total_return_pct", 0.0)),
                    dd=float(row.get("max_drawdown_pct", 0.0)),
                    trades=int(row.get("total_trades", 0)),
                    params=json.dumps(
                        row.get("params", {}) or {},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
            )
    return lines


def _check_auto_accept(
    diagnostic: Dict[str, Any],
    *,
    n_trades: int,
    dd: float,
    sharpe: float,
) -> Optional[tuple[str, str]]:
    """Vérifie les critères d'acceptation automatique. Retourne (message, 'accept') ou None."""
    cat = diagnostic.get("category", "")
    if cat == "target_reached" and n_trades > 20 and abs(dd) < 40:
        return (
            f"Cible atteinte (Sharpe {sharpe:.3f}), stratégie robuste "
            f"({n_trades} trades, DD {dd:.1f}%). Acceptation automatique.",
            "accept",
        )
    return None


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

    unique = set(np.unique(np.asarray(series.values)).tolist())  # type: ignore[call-overload]
    if not unique.issubset({-1.0, 0.0, 1.0}):
        raise ValueError(_err(ERR_SIG, f"Valeurs signaux hors contrat détectées: {sorted(unique)}"))

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


def _classify_raw_response(text: str) -> str:
    """Retourne la nature d'une réponse brute LLM pour debug de phase."""
    if not text or not text.strip():
        return "empty"
    if _looks_like_json_object(text):
        return "json"
    if _looks_like_python_code(text):
        return "python"
    return "text"


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
        self._active_thought_stream: Optional[Any] = None
        self._active_builder_session_id: str = ""
        self.phase_llm_clients = {
            str(key or "").strip(): value
            for key, value in dict(phase_llm_clients or {}).items()
            if str(key or "").strip() and value is not None
        }
        self.builder_execution_mode: str = "mono_single_llm"
        self.orchestration_mode: str = "single_llm"
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
        except Exception:  # noqa: BLE001
            self._indicator_policy = {}
        self._indicator_history: Dict[str, Any] = {}  # chargé au début de chaque run

    def _iter_llm_clients(self) -> List[Any]:
        ordered: List[Any] = []
        seen: set[int] = set()
        for client in [self.llm, *list(self.phase_llm_clients.values())]:
            if client is None:
                continue
            marker = id(client)
            if marker in seen:
                continue
            seen.add(marker)
            ordered.append(client)
        return ordered

    def _abort_active_llm_streams(self) -> bool:
        aborted_any = False
        for client in self._iter_llm_clients():
            abort = getattr(client, "abort_current_stream", None)
            if not callable(abort):
                continue
            try:
                aborted_any = bool(abort()) or aborted_any
            except Exception:  # noqa: BLE001
                logger.debug(
                    "builder_abort_active_llm_stream_failed client=%s",
                    type(client).__name__,
                    exc_info=True,
                )
        return aborted_any

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

    def _persist_session_strategy_code(self, session, code):
        persist_session_strategy_code(session, code)

    def _persist_runtime_checkpoint(self, session, **kwargs):
        persist_runtime_checkpoint(session, **kwargs)

    @staticmethod
    def _default_live_status(event: str) -> str:
        if event in {"phase_start", "session_start", "iteration_start"}:
            return "start"
        if event == "proposal_selected":
            return "selected"
        if event in {"iteration_error"}:
            return "error"
        if event == "warning":
            return "warning"
        if event == "session_done":
            return "done"
        return "done"

    @staticmethod
    def _live_phase_label(phase: str) -> str:
        labels = {
            "proposal": "proposition",
            "code": "generation code",
            "save_and_load": "sauvegarde / chargement",
            "precheck": "precheck signaux",
            "analysis": "analyse",
            "backtest": "backtest",
            "runtime_fix": "reparation runtime",
            "runtime_fix_fallback_backtest": "backtest fallback",
            "validation": "validation",
        }
        normalized = str(phase or "").strip()
        return labels.get(normalized, normalized or "activite Builder")

    @staticmethod
    def _live_branch_suffix(branch_label: str, *, include_main: bool = False) -> str:
        cleaned = str(branch_label or "").strip()
        if not cleaned:
            return ""
        if cleaned == "main" and not include_main:
            return ""
        return f" | branche `{cleaned}`"

    def _build_live_event(self, event: str, **payload: Any) -> Dict[str, Any]:
        raw_payload = dict(payload or {})
        iteration = int(raw_payload.pop("iteration", 0))
        phase = str(raw_payload.pop("phase", "") or "")
        branch_label = str(raw_payload.pop("branch_label", "") or "")
        selected_branch_label = str(raw_payload.pop("selected_branch_label", "") or "")
        status = str(raw_payload.pop("status", "") or self._default_live_status(event))
        explicit_message = str(raw_payload.pop("message", "") or "").strip()
        session_id = str(raw_payload.pop("session_id", "") or self._active_builder_session_id or "")
        if not session_id:
            thought_stream = self._active_thought_stream
            session_id = str(getattr(thought_stream, "session_id", "") or "") if thought_stream else ""
        if event == "proposal_selected" and not selected_branch_label:
            selected_branch_label = branch_label
        message = explicit_message or self._format_live_message(
            event=event,
            iteration=iteration,
            phase=phase,
            status=status,
            branch_label=branch_label,
            selected_branch_label=selected_branch_label,
            payload=raw_payload,
        )
        live_event = BuilderLiveEvent(
            event=str(event or ""),
            timestamp=datetime.utcnow().isoformat(timespec="seconds") + "Z",
            session_id=session_id,
            iteration=iteration,
            branch_label=branch_label,
            selected_branch_label=selected_branch_label,
            phase=phase,
            status=status,
            message=message,
            payload=raw_payload,
        )
        return live_event.to_dict()

    def _format_live_message(
        self,
        *,
        event: str,
        iteration: int,
        phase: str,
        status: str,
        branch_label: str,
        selected_branch_label: str,
        payload: Dict[str, Any],
    ) -> str:
        if event == "session_start":
            symbol = str(payload.get("symbol", "") or "").strip()
            timeframe = str(payload.get("timeframe", "") or "").strip()
            market = f" sur {symbol} {timeframe}".rstrip()
            return f"Initialisation de la session Builder{market}"
        if event == "iteration_start":
            total = int(payload.get("max_iterations", 0))
            return f"Iteration {iteration}/{total or '?'} demarree"
        if event == "proposal_candidate":
            proposal = dict(payload.get("proposal") or {})
            hypothesis = str(proposal.get("hypothesis", "") or "hypothese candidate")
            return f"Proposition candidate{self._live_branch_suffix(branch_label, include_main=True)} - {hypothesis}"
        if event == "proposal_selected":
            proposal = dict(payload.get("proposal") or {})
            hypothesis = str(proposal.get("hypothesis", "") or "hypothese retenue")
            target_branch = selected_branch_label or branch_label
            return f"Branche retenue{self._live_branch_suffix(target_branch, include_main=True)} - {hypothesis}"
        if event == "phase_start":
            detail = str(payload.get("detail", "") or "").strip()
            message = f"{self._live_phase_label(phase).capitalize()} en cours{self._live_branch_suffix(branch_label)}"
            if detail:
                message += f" - {detail}"
            return message
        if event == "phase_done":
            detail = str(payload.get("detail", "") or "").strip()
            message = f"{self._live_phase_label(phase).capitalize()} terminee{self._live_branch_suffix(branch_label)}"
            if phase == "backtest":
                sharpe = payload.get("sharpe")
                ret_pct = payload.get("total_return_pct")
                try:
                    return (
                        f"{message} - Sharpe {float(sharpe or 0):.3f} | "  # type: ignore[arg-type]
                        f"Return {float(ret_pct or 0):+.2f}%"  # type: ignore[arg-type]
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("phase_done metric format failed sharpe=%s ret_pct=%s", sharpe, ret_pct)
            if detail:
                message += f" - {detail}"
            return message
        if event == "diagnostic":
            diagnostic = dict(payload.get("diagnostic") or {})
            summary = str(diagnostic.get("summary", "") or "").strip()
            category = str(diagnostic.get("category", "") or "").strip()
            if summary and category:
                return f"Diagnostic {category} - {summary}"
            if summary:
                return summary
            return "Diagnostic mis a jour"
        if event == "analysis":
            decision = str(payload.get("decision", "") or "").strip()
            if decision:
                return f"Analyse terminee - decision {decision}"
            return "Analyse terminee"
        if event == "warning":
            return str(payload.get("detail", "") or "Avertissement Builder").strip()
        if event == "iteration_done":
            decision = str(payload.get("decision", "") or "").strip()
            message = f"Iteration {iteration} terminee"
            if decision:
                message += f" - decision {decision}"
            if payload.get("new_best"):
                message += " - nouveau meilleur resultat"
            return message
        if event == "iteration_error":
            error_text = str(payload.get("error", "") or "").strip()
            return (
                f"Iteration {iteration} en erreur - {error_text}" if error_text else f"Iteration {iteration} en erreur"
            )
        if event == "session_done":
            total_iterations = int(payload.get("total_iterations", 0))
            return f"Session terminee - {status} ({total_iterations} iterations)"
        return str(payload.get("detail", "") or "").strip()

    def _emit_progress(self, event: str, **payload: Any) -> None:
        """Emet un evenement live canonique vers le terminal et l'UI."""
        message = self._build_live_event(event, **payload)

        thought_stream = self._active_thought_stream
        if thought_stream is not None:
            try:
                thought_stream.consume(message)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "builder_thought_stream_consume_failed event=%s",
                    event,
                    exc_info=True,
                )

        callback = self.progress_callback
        if callback is None:
            return
        try:
            callback(message)
        except Exception:  # noqa: BLE001
            logger.debug(
                "builder_progress_callback_failed event=%s",
                event,
                exc_info=True,
            )

    def _emit_stream_chunk(self, phase: str, chunk: str) -> None:
        callback = self.stream_callback
        if callback is not None:
            try:
                callback(phase, chunk)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "builder_stream_callback_failed phase=%s",
                    phase,
                    exc_info=True,
                )

        thought_stream = self._active_thought_stream
        if thought_stream is None:
            return
        try:
            thought_stream.stream_chunk(phase, chunk)
        except Exception:  # noqa: BLE001
            logger.debug(
                "builder_thought_stream_chunk_failed phase=%s",
                phase,
                exc_info=True,
            )

    def _emit_terminal_stage(
        self,
        phase: str,
        *,
        status: str = "start",
        detail: str = "",
        branch_label: str = "",
    ) -> None:
        thought_stream = self._active_thought_stream
        if thought_stream is None:
            return
        try:
            thought_stream.consume(
                self._build_live_event(
                    "phase_start" if str(status or "start") == "start" else "phase_done",
                    phase=phase,
                    status=status,
                    detail=detail,
                    branch_label=branch_label,
                )
            )
        except (ValueError, KeyError, RuntimeError, AttributeError, TypeError, IndexError):
            logger.debug(
                "builder_terminal_stage_failed phase=%s status=%s",
                phase,
                status,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # LLM call helper (streaming si callback défini)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Répétition token guard (léger, O(N) sur fenêtre glissante)
    # ------------------------------------------------------------------

    class _StreamRepetitionGuard:
        """Détecte les boucles de répétition dans le flux stream LLM.

        Déclenche ``StreamAbortRequest`` quand une unité de longueur L se répète
        au moins ``_THRESHOLD`` fois consécutives en fin de buffer. Coût : O(1) par
        chunk (scan déclenché seulement tous les ``_CHECK_EVERY`` chars).
        """

        # Invariant: _WINDOW >= _MAX_UNIT * _THRESHOLD, sinon max_u est plafonné
        # par n // _THRESHOLD et les longues répétitions échappent à la détection.
        _WINDOW: int = 1200  # chars inspectés à chaque scan
        _MIN_UNIT: int = 3  # longueur min de l'unité répétée
        _MAX_UNIT: int = 200  # longueur max (couvre répétitions de 2-3 lignes)
        _THRESHOLD: int = 5  # répétitions consécutives pour déclencher
        _CHECK_EVERY: int = 40  # déclencher le scan tous les N chars reçus

        def __init__(self) -> None:
            self._buf: List[str] = []
            self._buf_len: int = 0
            self._since_check: int = 0
            self._triggered: bool = False

        def feed(self, chunk: str) -> None:
            """Consomme un chunk. Lève ``StreamAbortRequest`` si répétition détectée."""
            if self._triggered:
                raise StreamAbortRequest("repetition_loop")
            self._buf.append(chunk)
            self._buf_len += len(chunk)
            self._since_check += len(chunk)
            if self._since_check >= self._CHECK_EVERY:
                self._since_check = 0
                tail = "".join(self._buf)[-self._WINDOW :]
                if self._detect_repetition(tail):
                    self._triggered = True
                    raise StreamAbortRequest("repetition_loop")

        def _detect_repetition(self, text: str) -> bool:
            n = len(text)
            threshold = self._THRESHOLD
            min_u = self._MIN_UNIT
            max_u = min(self._MAX_UNIT, n // threshold)
            if max_u < min_u:
                return False
            for unit_len in range(min_u, max_u + 1):
                needed = unit_len * threshold
                if n < needed:
                    continue
                unit = text[-unit_len:]
                region = text[-needed:]
                # Vérifier que toute la région est une répétition de l'unité
                if all(region[i : i + unit_len] == unit for i in range(0, needed, unit_len)):
                    return True
            return False

    @staticmethod
    def _make_corrective_messages(messages: List[LLMMessage]) -> List[LLMMessage]:
        """Ajoute une instruction corrective sur le dernier message utilisateur.

        Appelé quand le LLM vient de partir en boucle de répétition token.
        """
        if not messages:
            return messages
        correction = (
            "\n\n⚠️ IMPORTANT : ta réponse précédente s'est répétée en boucle de tokens. "
            "Recommence depuis le début. Génère une réponse COMPLÈTE et CONCISE, "
            "sans répétition, directement au but."
        )
        corrected: List[LLMMessage] = list(messages)
        for i in range(len(corrected) - 1, -1, -1):
            if corrected[i].role == "user":
                corrected[i] = LLMMessage(
                    role="user",
                    content=corrected[i].content + correction,
                )
                break
        return corrected

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
        original_host = getattr(client_config, "ollama_host", None) if client_config else None
        route_snapshot: dict[str, str] | None = None
        route_restore = None
        route = self.llm_topology_config.resolve_builder_phase_route(
            phase,
            fallback_host=original_host,
        )
        route_host = str(route.ollama_host or "").rstrip("/")
        current_host = str(original_host or "").rstrip("/")
        if route_host and route_host != current_host:
            set_runtime_route = getattr(llm_client, "set_runtime_route", None)
            route_restore = getattr(llm_client, "restore_runtime_route", None)
            if callable(set_runtime_route) and callable(route_restore):
                route_snapshot = set_runtime_route(ollama_host=route_host)
            elif client_config is not None:
                client_config.ollama_host = route_host

        # Capture les référencees au moment de la définition du closure pour éviter
        # que des threads résiduels (après timeout) écrivent dans le mauvais stream.
        _captured_ts = self._active_thought_stream
        _captured_cb = self.stream_callback

        # Guard de répétition : instance fraîche par appel LLM
        _rep_guard = self._StreamRepetitionGuard()

        def _do_call(
            _msgs: Any = None,
            _temp: Any = None,
            _guard: "StrategyBuilder._StreamRepetitionGuard | None" = None,
        ) -> Any:
            msgs_ = messages if _msgs is None else _msgs
            temp_ = temperature if _temp is None else _temp
            guard_ = _rep_guard if _guard is None else _guard
            if (_captured_cb or _captured_ts) and hasattr(llm_client, "chat_stream"):

                def _on_chunk(c: str) -> None:
                    if _captured_ts is not None:
                        accepts_streaming = getattr(_captured_ts, "accepts_streaming", None)
                        if callable(accepts_streaming) and not accepts_streaming():
                            raise StreamAbortRequest("stale_thought_stream")
                    guard_.feed(c)  # StreamAbortRequest propagates to chat_stream
                    if _captured_cb is not None:
                        try:
                            _captured_cb(phase, c)
                        except Exception:  # noqa: BLE001
                            pass
                    if _captured_ts is not None:
                        try:
                            _captured_ts.stream_chunk(phase, c)
                        except Exception:  # noqa: BLE001
                            pass

                # Pass per-phase timeout to httpx so the in-flight stream
                # actually closes when the Builder's per-phase budget is hit,
                # rather than dangling on the default 600s adaptive timeout.
                try:
                    return llm_client.chat_stream(
                        msgs_,
                        on_chunk=_on_chunk,
                        json_mode=json_mode,
                        temperature=temp_,
                        max_tokens=max_tokens,
                        http_timeout=float(timeout_sec) + 5.0,
                    )
                except TypeError:
                    # Older client signature without http_timeout.
                    return llm_client.chat_stream(
                        msgs_,
                        on_chunk=_on_chunk,
                        json_mode=json_mode,
                        temperature=temp_,
                        max_tokens=max_tokens,
                    )
            return llm_client.chat(
                msgs_,
                json_mode=json_mode,
                temperature=temp_,
                max_tokens=max_tokens,
            )

        # --- Soumission commune : submit + timeout + exception handling ---
        def _submit_to_pool(
            fn: Any,
            pool: Any,
            label: str,
        ) -> Any:
            """Submit *fn* dans *pool*, attend *timeout_sec* et retourne le résultat.

            Toute erreur réseau/timeout/inattendue retourne un stub vide au lieu
            de crasher la session.  Les streams actifs sont abortés si nécessaire.
            """
            try:
                future = pool.submit(fn)
            except RuntimeError as exc:
                if _is_interpreter_shutdown_runtime_error(exc):
                    logger.info(
                        "builder_llm_submit_aborted phase=%s label=%s reason=interpreter_shutdown",
                        phase,
                        label,
                    )
                    raise KeyboardInterrupt() from exc
                raise
            try:
                res = future.result(timeout=timeout_sec)
                if _captured_ts is not None:
                    try:
                        _captured_ts.flush_stream()
                    except Exception:  # noqa: BLE001
                        pass
                return res
            except (
                concurrent.futures.TimeoutError,
                ConnectionError,
                OSError,
            ) as exc:
                self._abort_active_llm_streams()
                logger.warning(
                    "builder_llm_error phase=%s label=%s error_type=%s error=%s",
                    phase,
                    label,
                    type(exc).__name__,
                    exc,
                )
                return SimpleNamespace(content="")
            except Exception as exc:  # noqa: BLE001
                self._abort_active_llm_streams()
                logger.error(
                    "builder_llm_unexpected_error phase=%s label=%s error=%s",
                    phase,
                    label,
                    exc,
                    exc_info=True,
                )
                return SimpleNamespace(content="")

        try:
            pool = _new_streamlit_aware_thread_pool(max_workers=1)
            try:
                result = _submit_to_pool(_do_call, pool, "main")
            finally:
                pool.shutdown(wait=False)

            # --- Corrective kick si boucle de répétition détectée ---
            if result is not None and getattr(result, "aborted", False):
                self._emit_progress(
                    "repetition_kick",
                    phase=phase,
                    status="warning",
                    message=(
                        f"⚡ Boucle de répétition détectée ({phase}) — relance correctrice avec instruction explicite"
                    ),
                )
                logger.warning(
                    "builder_llm_repetition_kick phase=%s model=%s",
                    phase,
                    getattr(client_config, "model", "?") if client_config else "?",
                )
                corrected_msgs = self._make_corrective_messages(messages)
                corrective_temp = min((temperature or 0.5) + 0.15, 1.0)
                pool_kick = _new_streamlit_aware_thread_pool(max_workers=1)
                try:
                    result = _submit_to_pool(
                        lambda: _do_call(corrected_msgs, corrective_temp, self._StreamRepetitionGuard()),
                        pool_kick,
                        "repetition_kick",
                    )
                finally:
                    pool_kick.shutdown(wait=False)

            return result
        finally:
            if route_snapshot is not None and callable(route_restore):
                try:
                    route_restore(route_snapshot)
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "builder_llm_route_restore_failed phase=%s",
                        phase,
                        exc_info=True,
                    )
            elif client_config is not None:
                client_config.ollama_host = original_host

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    @staticmethod
    def create_session_id(objective: str) -> str:
        return create_session_id(objective)

    @staticmethod
    def get_session_dir(session_id: str):
        return get_session_dir(session_id)

    def _safe_save_session_summary(self, session):
        safe_save_session_summary(session)

    def _attempt_session_auto_reset(self, session, **kwargs):
        def _save_callback(target_session: BuilderSession) -> None:
            save_func = getattr(self, "_save_session_summary", None)
            if callable(save_func):
                try:
                    save_func(target_session)
                    return
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "builder_auto_reset_instance_save_failed session=%s",
                        getattr(target_session, "session_id", "unknown"),
                        exc_info=True,
                    )
            safe_save_session_summary(target_session)

        return attempt_session_auto_reset(session, save_callback=_save_callback, **kwargs)

    def _build_cross_session_memory_prompt(
        self,
        session: BuilderSession,
        *,
        max_chars: int,
    ) -> str:
        entries = list(getattr(session, "cross_session_memory", []) or [])
        return format_builder_cross_session_memory(entries, max_chars=max_chars)

    def _build_mono_llm_model_prompt_context(
        self,
        session: BuilderSession,
        *,
        phase: str,
    ) -> Dict[str, Any]:
        model_name = str(
            getattr(session, "model_name", "")
            or getattr(getattr(self.llm, "config", None), "model", "")
            or ""
        )
        return build_builder_model_prompt_guidance(
            model_name,
            phase=cast(Literal["proposal", "code"], str(phase or "proposal")),
            builder_execution_mode=str(getattr(session, "builder_execution_mode", "") or ""),
        )

    # ------------------------------------------------------------------
    # Indicator ranking (shared between proposal & code phases)
    # ------------------------------------------------------------------

    def _rank_indicators_for_phase(
        self,
        *,
        objective: str,
        diagnostic: Optional[Dict[str, Any]] = None,
        previous_indicators: Optional[List[str]] = None,
        session_seed: str,
        prefer_diversity: bool = False,
    ) -> List[str]:
        """Rank available indicators using inter-session diversity policy.

        Returns a sorted list of indicator names, or a prompt-local randomized
        presentation order when the ``indicator_ranking`` ablation step is
        disabled.
        """
        if not self.ablation.is_enabled("indicator_ranking"):
            return shuffle_indicator_presentation_order(
                self.available_indicators,
                session_seed=session_seed,
            )

        from config.indicator_history import (  # noqa: PLC0415,I001
            get_banned_indicators,
            get_recent_families,
            get_recent_indicators,
        )

        hist = getattr(self, "_indicator_history", {})
        pol = getattr(self, "_indicator_policy", {})
        enabled = pol.get("enabled", True)
        banned = get_banned_indicators(hist, pol) if enabled else set()
        recent = get_recent_indicators(hist, pol) if enabled else []
        families = get_recent_families(hist, pol) if enabled else []
        performance_priors = self._get_indicator_performance_priors()
        return rank_indicator_selection(
            self.available_indicators,
            objective=objective,
            diagnostic=diagnostic or {},
            previous_indicators=previous_indicators or [],
            session_seed=session_seed,
            prefer_diversity=prefer_diversity,
            banned_indicators=banned,
            inter_session_indicators=recent,
            inter_session_penalty=float(pol.get("previous_penalty", 0.0)),
            inter_session_novelty_bonus=(float(pol.get("novelty_bonus", 0.0)) if prefer_diversity else 0.0),
            previous_families=families,
            family_penalty=float(pol.get("family_penalty", 0.0)),
            family_bonus=float(pol.get("family_bonus", 0.0)),
            performance_priors=performance_priors,
            performance_prior_weight=float(os.getenv("BACKTEST_BUILDER_INDICATOR_PRIOR_WEIGHT", "0.75")),
        )

    def _get_indicator_performance_priors(self) -> Dict[str, float]:
        """Charge un prior conservateur indicateur->score depuis l'historique Builder."""
        global _INDICATOR_PERFORMANCE_PRIORS_CACHE
        raw_enabled = os.getenv("BACKTEST_BUILDER_INDICATOR_PRIORS", "1").strip().lower()
        if raw_enabled in {"0", "false", "no", "off"}:
            return {}
        if _INDICATOR_PERFORMANCE_PRIORS_CACHE is not None:
            return dict(_INDICATOR_PERFORMANCE_PRIORS_CACHE)
        priors: Dict[str, float] = {}
        try:
            from analytics.indicator_stats import Filters, load_iterations, per_indicator_stats

            max_sessions = int(float(os.getenv("BACKTEST_BUILDER_INDICATOR_PRIOR_SESSIONS", "400")))
            min_n = int(float(os.getenv("BACKTEST_BUILDER_INDICATOR_PRIOR_MIN_N", "20")))
            rows = load_iterations(max_sessions=max_sessions)
            stats = per_indicator_stats(
                rows,
                filters=Filters(min_trades=1, exclude_no_trades=True),
                mode="session_best",
                min_n=max(1, min_n),
            )
            for row in stats:
                indicator = str(row.get("indicator") or "").strip().lower()
                if not indicator:
                    continue
                lift = float(row.get("lift") or 0.0)
                priors[indicator] = max(-1.5, min(1.5, lift / 25.0))
        except Exception:  # noqa: BLE001
            logger.debug("builder_indicator_performance_priors_unavailable", exc_info=True)
            priors = {}
        _INDICATOR_PERFORMANCE_PRIORS_CACHE = dict(priors)
        return dict(priors)

    # ------------------------------------------------------------------
    # LLM interactions
    # ------------------------------------------------------------------

    @staticmethod
    def _build_session_market_context(session: "BuilderSession") -> Dict[str, Any]:
        """Champs de contexte marché communs aux prompts proposal et code."""
        return {
            "objective": session.objective,
            "direction_constraint": session.direction_constraint,
            "symbol": session.symbol,
            "timeframe": session.timeframe,
            "n_bars": session.n_bars,
            "fees_bps": session.fees_bps,
            "slippage_bps": session.slippage_bps,
            "initial_capital": session.initial_capital,
            "cross_session_memory_count": len(session.cross_session_memory or []),
        }

    def _build_indicator_stats_block(self, session: "BuilderSession") -> str:
        """Construit le bloc indicateur x perf cross-sessions a injecter dans le prompt.

        Pilote par `config/indicator_policy.json` :
        - `inject_stats_into_prompt` (defaut False) : kill-switch
        - `inject_stats_min_n_known` : seuil n des indicateurs eprouves
        - `inject_stats_top_n` : taille max par tableau
        - `inject_stats_filter_by_context` : filtrage par symbol/timeframe courants

        Retourne "" si desactive ou si pas de donnees exploitables.
        Le bloc est aussi snapshotte dans `session.indicator_stats_snapshot`
        pour audit retroactif (cf. correlation perf <-> nudge).
        """
        policy = getattr(self, "_indicator_policy", None) or {}
        if not bool(policy.get("inject_stats_into_prompt", False)):
            return ""
        try:
            from analytics.indicator_stats import (
                Filters,
                format_indicator_tables_for_prompt,
                load_iterations,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("indicator_stats_block_import_failed err=%s", exc)
            return ""

        try:
            rows = load_iterations()
        except Exception as exc:  # noqa: BLE001
            logger.warning("indicator_stats_block_load_failed err=%s", exc)
            return ""
        if not rows:
            return ""

        symbols: frozenset[str] = frozenset()
        timeframes: frozenset[str] = frozenset()
        if bool(policy.get("inject_stats_filter_by_context", False)):
            if session.symbol:
                symbols = frozenset({str(session.symbol)})
            if session.timeframe:
                timeframes = frozenset({str(session.timeframe)})

        filters = Filters(symbols=symbols, timeframes=timeframes)
        top_n = int(policy.get("inject_stats_top_n", 10) or 10)
        min_n_known = int(policy.get("inject_stats_min_n_known", 50) or 50)
        try:
            return format_indicator_tables_for_prompt(
                rows,
                filters=filters,
                mode="session_best",
                top_n=top_n,
                flop_n=top_n,
                min_n_known=min_n_known,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("indicator_stats_block_format_failed err=%s", exc)
            return ""

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
        ctx = IterationContext(last_iteration)
        previous_indicators = list(_previous_iteration_indicators(ctx))
        diagnostic_detail = ctx.diagnostic_detail
        prefer_diversity = ctx.exists and _requires_indicator_exploration(ctx)
        ordered_prompt_indicators = self._rank_indicators_for_phase(
            objective=session.objective,
            diagnostic=diagnostic_detail,
            previous_indicators=previous_indicators,
            session_seed=f"{session.session_id}:proposal:{len(session.iterations) + 1}",
            prefer_diversity=prefer_diversity,
        )

        context = {
            **self._build_session_market_context(session),
            **self._build_mono_llm_model_prompt_context(session, phase="proposal"),
            "available_indicators": ordered_prompt_indicators,
            "available_indicator_guide": build_indicator_selection_guide(ordered_prompt_indicators),
            "cross_session_memory_prompt": self._build_cross_session_memory_prompt(
                session,
                max_chars=BUILDER_MEMORY_PROPOSAL_MAX_CHARS,
            ),
            "iteration": len(session.iterations) + 1,
            "max_iterations": session.max_iterations,
            # Contexte de marché étendu (proposal seulement)
            "date_range_start": session.date_range_start,
            "date_range_end": session.date_range_end,
            "objective_indicators": list(session.objective_indicators or []),
            "indicator_lock_mode": str(session.indicator_lock_mode or ""),
        }

        if ctx.has_backtest:
            metrics = ctx.metrics
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
            context["last_code"] = ctx.code
            context["last_analysis"] = ctx.analysis
            context["best_sharpe"] = session.best_sharpe
            if previous_indicators:
                context["previous_indicators"] = previous_indicators
            # Diagnostic pré-calculé de la dernière itération
            if diagnostic_detail and self.ablation.is_enabled("diagnostic_context"):
                context["diagnostic"] = diagnostic_detail
            last_backtest_feedback = ctx.backtest_feedback
            if last_backtest_feedback.get("mode") == "sweep":
                context["last_sweep"] = {
                    "total_tested": last_backtest_feedback.get("sweep_total_tested", 0),
                    "success": last_backtest_feedback.get("sweep_success", 0),
                    "failed": last_backtest_feedback.get("sweep_failed", 0),
                    "best_params": last_backtest_feedback.get("sweep_best_params", {}),
                    "top_results": last_backtest_feedback.get("sweep_top_results", []),
                }
            # Stagnation détectée : forcer le LLM à changer radicalement
            if ctx.has_identical_metrics_stagnation:
                context["stagnation_warning"] = (
                    "CRITICAL: Previous iteration produced IDENTICAL metrics. "
                    "Your changes had NO effect. You MUST change the fundamental "
                    "approach: use DIFFERENT indicators, DIFFERENT entry logic, "
                    "or DIFFERENT strategy type (e.g. trend-following instead of "
                    "mean-reversion). Do NOT repeat the same logic with minor tweaks."
                )
            context["should_consider_indicator_expansion"] = _requires_indicator_exploration(ctx)

        if branch_directive:
            context["branch_directive"] = branch_directive

        if session.iterations and self.ablation.is_enabled("iteration_history"):

            history_entries: list = []
            for it in session.iterations[-5:]:
                ctx = IterationContext(it)
                bf = ctx.backtest_feedback
                m = ctx.metrics
                history_entries.append(
                    {
                        "backtest_feedback": bf,
                        "iteration": it.iteration,
                        "hypothesis": it.hypothesis,
                        "change_type": it.change_type,
                        "diagnostic_category": it.diagnostic_category,
                        "decision": it.decision,
                        "indicators": ctx.used_indicators,
                        "sharpe": m.get("sharpe_ratio", 0),
                        "return_pct": m.get("total_return_pct", 0),
                        "trades": m.get("total_trades", 0),
                        "win_rate": m.get("win_rate_pct", 0),
                        "max_drawdown_pct": m.get("max_drawdown_pct", 0),
                        "profit_factor": m.get("profit_factor", 0),
                        "error": it.error,
                        "is_fallback": ctx.is_fallback,
                        "evaluation_mode": bf.get("mode", ""),
                        "sweep_total_tested": bf.get("sweep_total_tested"),
                        "params_used": bf.get("params_used"),
                    }
                )
            context["iteration_history"] = history_entries

        # Fournir la meilleure config session pour ancrer le modèle
        best_ctx = IterationContext(session.best_iteration)
        if best_ctx.has_backtest:
            bm = best_ctx.metrics
            context["best_so_far"] = {
                "iteration": best_ctx.raw.iteration if best_ctx.raw else 0,
                "hypothesis": best_ctx.hypothesis,
                "indicators": best_ctx.used_indicators,
                "sharpe": bm.get("sharpe_ratio", 0),
                "return_pct": bm.get("total_return_pct", 0),
                "max_drawdown_pct": bm.get("max_drawdown_pct", 0),
                "win_rate": bm.get("win_rate_pct", 0),
                "trades": bm.get("total_trades", 0),
                "profit_factor": bm.get("profit_factor", 0),
            }

        stats_block = self._build_indicator_stats_block(session)
        if stats_block:
            context["indicator_stats_block"] = stats_block
            session.indicator_stats_snapshot = stats_block

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

        # --- Helper local : extraire, sanitiser, valider une réponse brute ---
        def _extract_and_validate(raw_text: str) -> tuple:
            """Retourne (proposal, issues) après extraction JSON + sanitization."""
            prop = _normalize_proposal_keys(_extract_json_from_response(raw_text))
            if self.ablation.is_enabled("proposal_sanitize"):
                prop = _sanitize_proposal_payload(
                    prop,
                    available_indicators=self.available_indicators,
                    objective=session.objective,
                    direction_constraint=session.direction_constraint,
                    market_symbol=session.symbol,
                )
            return prop, _proposal_issues(prop)

        proposal, issues = _extract_and_validate(raw)
        feedback["issues"] = issues
        if not issues:
            proposal["change_type"] = _normalize_change_type(proposal.get("change_type", "logic"))
            feedback["final_kind"] = feedback["initial_kind"]
            feedback["final_valid"] = True
            return proposal, feedback
        feedback["error_code"] = _proposal_error_code(issues)

        # Phase guard: certains modèles répondent du code / texte libre.
        for attempt in range(1, PROPOSAL_REALIGN_ATTEMPTS + 1):
            mismatch = _classify_raw_response_mismatch(raw, phase="proposal")

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
            proposal, issues = _extract_and_validate(raw)
            feedback["issues"] = issues
            if not issues:
                proposal["change_type"] = _normalize_change_type(proposal.get("change_type", "logic"))
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
        _ = iteration_num
        instr = self.instrumentation
        if not instr.enabled:
            return
        trace = instr._current_trace  # noqa: SLF001
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
                code_fb.get("fallback_deterministic_used") or code_fb.get("source") == "deterministic_fallback"
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
        if code_fb.get("fallback_deterministic_used") or code_fb.get("source") == "deterministic_fallback":
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
        ctx = IterationContext(last_iteration)
        # Extraire les actions diagnostiques de la dernière itération
        diag_actions: List[str] = []
        diag_donts: List[str] = []
        if ctx.exists and self.ablation.is_enabled("diagnostic_context"):
            diag_actions = ctx.diagnostic_actions
            diag_donts = ctx.diagnostic_donts

        ordered_code_indicators = self._rank_indicators_for_phase(
            objective=(
                f"{session.objective} {proposal.get('hypothesis', '')} "
                f"{' '.join(proposal.get('used_indicators', []) or [])}"
            ),
            diagnostic=ctx.diagnostic_detail,
            previous_indicators=proposal.get("used_indicators", []),
            session_seed=f"{session.session_id}:code:{len(session.iterations) + 1}",
            prefer_diversity=False,
        )

        context = {
            **self._build_session_market_context(session),
            **self._build_mono_llm_model_prompt_context(session, phase="code"),
            "proposal": proposal,
            "available_indicators": ordered_code_indicators,
            "available_indicator_guide": build_indicator_selection_guide(ordered_code_indicators),
            "cross_session_memory_prompt": self._build_cross_session_memory_prompt(
                session,
                max_chars=BUILDER_MEMORY_CODE_MAX_CHARS,
            ),
            "class_name": GENERATED_CLASS_NAME,
            "previous_code": ctx.code,
            # Diagnostic de l'itération précédente (injecté dans le template)
            "diagnostic_actions": diag_actions,
            "diagnostic_donts": diag_donts,
        }

        prompt = render_prompt("strategy_builder_code.jinja2", context)
        safe_mode = _safe_path_mode(getattr(session, "universe_purpose", ""))

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
            mismatch = _classify_raw_response_mismatch(raw, phase="logic")

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
        objective_indicators = _extract_objective_indicator_names(
            objective,
            available_indicators=self.available_indicators,
        )
        example_indicators = (
            objective_indicators[:3] if objective_indicators else list(self.available_indicators[:3] or ["atr"])
        )
        example_indicators_json = ", ".join(f'"{ind}"' for ind in example_indicators)
        prompt = (
            f"Design a simple trading strategy for: {objective}\n\n"
            f"Available indicators: {indicators_str}\n\n"
            "If the objective explicitly names indicators, start from exactly that set.\n"
            "Semi-open exception: in logic/both mode, you may add OR replace at most one indicator, "
            "and you must explain it via indicator_override_reason.\n\n"
            "Reply ONLY with this JSON:\n"
            "{\n"
            '  "strategy_name": "my_strategy",\n'
            '  "hypothesis": "one concrete sentence explaining why this setup should work",\n'
            '  "change_type": "logic",\n'
            f'  "used_indicators": [{example_indicators_json}],\n'
            '  "indicator_override_reason": "optional: explain the single add/replace if you deviate from explicit objective indicators",\n'
            '  "entry_long_logic": "one explicit boolean entry condition using the selected indicators",\n'
            '  "entry_short_logic": "one explicit boolean short condition using the selected indicators, or empty string if long_only",\n'
            '  "exit_logic": "one explicit exit condition using the selected indicators",\n'
            '  "risk_management": "ATR stop and ATR take-profit with concrete multipliers",\n'
            '  "default_params": {"leverage": 1, "stop_atr_mult": 1.5, "tp_atr_mult": 3.0, "warmup": 50},\n'
            '  "parameter_specs": {"stop_atr_mult": {"min": 1.0, "max": 2.0, "default": 1.5, "type": "float"}}\n'
            "}"
        )
        sys_msg = LLMMessage(
            role="system",
            content=(
                "You are a quant trader. Reply ONLY with valid JSON. No commentary. No thinking. No placeholders."
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
        result = _normalize_proposal_keys(_extract_json_from_response(response.content))
        if result:
            return result

        # Tentative 2 : sans json_mode (certains modèles locaux échouent avec format=json)
        logger.warning(
            "retry_proposal: json_mode a échoué, tentative sans json_mode. Réponse brute (200 premiers chars): %.200s",
            response.content[:200] if response.content else "(vide)",
        )
        response = self._chat_llm(
            messages=[sys_msg, user_msg],
            phase="retry_proposal_nojson",
            json_mode=False,
            max_tokens=4096,
        )
        return _normalize_proposal_keys(_extract_json_from_response(response.content))

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
            "- ema/rsi/atr are plain arrays. For multiple EMA/ATR periods, use named keys supplied by the host "
            "such as indicators['ema_21'] and indicators['ema_50']; NEVER use indicators['ema']['ema_21'] style.\n\n"
            "- ALWAYS include leverage=1 in default_params\n"
            "- If using ATR-based SL/TP: write df['bb_stop_long/bb_tp_long/bb_stop_short/bb_tp_short'] on entry bars\n"
            "- Never hard-code ATR risk multipliers like 2*atr or 4*atr; use params.get('stop_atr_mult', 1.5) "
            "and params.get('tp_atr_mult', 3.0)\n\n"
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
                    content=("Generate ONLY Python code inside a ```python block. No explanation. No commentary."),
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
            "- Plain arrays (no sub-keys): ema, rsi, atr, cci, obv, mfi. Parameterized instances are separate "
            "keys such as indicators['ema_21'], indicators['ema_50'], indicators['atr_20'].\n"
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
                "retry_code_runtime_fix LLM call failed: %s\nruntime_error=%s\nfailing_code (first 500 chars)=%.500s",
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

        phase_feedback, backtest_feedback = _extract_phase_feedback(iteration)
        if backtest_feedback.get("mode") == "sweep":
            lines.extend(_format_sweep_context_lines(backtest_feedback))

        # Historique complet de la session (tendance visible itération par itération)
        if len(session.iterations) > 1:
            lines.append("")
            lines.append("### Historique de la session")
            for prev_it in session.iterations:
                prev_ctx = IterationContext(prev_it)
                if prev_ctx.has_backtest:
                    pm = prev_ctx.metrics
                    ps = float(pm.get("sharpe_ratio", 0))
                    pr = float(pm.get("total_return_pct", 0))
                    pd_ = float(pm.get("max_drawdown_pct", 0))
                    pt = int(pm.get("total_trades", 0))
                    pwr = float(pm.get("win_rate_pct", 0))
                    best_mark = (
                        " ★"
                        if session.best_iteration is not None and prev_it.iteration == session.best_iteration.iteration
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
            auto = _check_auto_accept(diagnostic, n_trades=n_trades, dd=dd, sharpe=sharpe)
            if auto is not None:
                return auto

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
                LLMMessage(
                    role="system",
                    content=(
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
                    ),
                ),
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
        _ = code  # paramètre stable d'API, utilisé dans les prompts futurs
        history_lines = []
        for it in session.iterations[-3:]:
            ctx = IterationContext(it)
            if ctx.has_backtest:
                m = ctx.metrics
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
                    LLMMessage(
                        role="system",
                        content=(
                            "You are a quant strategy critic. The backtest is still running — "
                            "you have NOT seen results. Self-critique the strategy and prepare "
                            "a backup plan. Be concise and concrete."
                        ),
                    ),
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
                return f"[Pre-reflection] {reflection}" + (f"\n[Backup plan] {backup}" if backup else "")
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
- If the prompt exposes explicit objective indicators, treat them as the sovereign starting set
- Do NOT fall back to your favorite RSI/Bollinger/ATR/ADX template when the objective names a different set
- Semi-open indicator policy: you may add OR replace at most one indicator only when change_type is logic or both, and then you MUST explain it via indicator_override_reason
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
    If the proposal uses parameterized instances, access separate keys like indicators['ema_21'] / indicators['ema_50'].
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
    Never hard-code ATR multipliers such as 2*atr, atr*3, or 4*atr when stop_atr_mult/tp_atr_mult exist.
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
            exec(compiled, sandbox_globals, sandbox_globals)  # noqa: S102  # pylint: disable=exec-used
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

    def _auto_fix_required_indicators(self, strategy_cls: type, code: str) -> type:
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
        strategy_cls.required_indicators = property(  # type: ignore[attr-defined]
            lambda self, _patched=tuple(patched_required): list(_patched)  # type: ignore[return-value,misc]
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
        *,
        max_bars: int | None = None,
    ) -> Dict[str, Any]:
        """Estime le nombre de signaux avant simulation complète.

        Objectif: détecter très tôt les itérations "no trades" et éviter
        d'exécuter un backtest complet inutile.

        `max_bars` (ou env PRECHECK_MAX_BARS) tronque le dataset aux N dernières
        bougies — accélère le précheck sur petits timeframes (5m/15m) tout en
        gardant la capacité à détecter 0-trade.
        """
        try:
            engine = BacktestEngine(initial_capital=initial_capital, run_id=generate_run_id())
            strategy_instance = strategy_cls()

            base_params = getattr(strategy_instance, "default_params", {}) or {}
            merged_params = dict(base_params)
            merged_params.update(params or {})
            merged_params.setdefault("fees_bps", fees_bps)
            merged_params.setdefault("slippage_bps", slippage_bps)

            effective_max_bars = int(max_bars) if max_bars is not None else PRECHECK_MAX_BARS
            truncated = False
            if effective_max_bars > 0 and len(data) > effective_max_bars:
                probe_df = data.iloc[-effective_max_bars:].copy(deep=True)
                truncated = True
            else:
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
            signal_density = float(total_count / bar_count) if bar_count > 0 else 0.0
            transition_density = float(transition_count / bar_count) if bar_count > 0 else 0.0
            repeated_same_ratio = float(repeated_same_count / total_count) if total_count > 0 else 0.0

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
                "precheck_truncated": truncated,
                "precheck_max_bars": effective_max_bars if truncated else 0,
                "full_dataset_bars": int(len(data)),
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

        total_signals = int(signal_probe.get("total_signals", 0))
        signal_density = float(signal_probe.get("signal_density", 0.0))
        transition_density = float(signal_probe.get("transition_density", 0.0))
        repeated_same_ratio = float(signal_probe.get("repeated_same_ratio", 0.0))

        if total_signals < MIN_SIGNAL_COUNT_FOR_DENSITY_PRECHECK:
            return False

        if signal_density < MAX_SIGNAL_DENSITY_PRECHECK:
            return False

        return (
            repeated_same_ratio >= MAX_REPEATED_SAME_SIGNAL_RATIO_PRECHECK
            or transition_density >= MAX_SIGNAL_TRANSITION_DENSITY_PRECHECK
        )

    def _classify_signal_precheck_block(
        self,
        signal_probe: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Retourne la décision synthétique de précheck, ou None si backtest utile."""
        if not signal_probe.get("ok"):
            return None

        total_signals = int(signal_probe.get("total_signals", 0))
        bar_count = int(signal_probe.get("bar_count", 0))
        if bar_count > 0 and total_signals == 0:
            skip_reason = "no_trade_signal_profile"
            return {
                "flag": skip_reason,
                "skip_reason": skip_reason,
                "detail": "précheck bloquant: aucun signal d'entrée détecté",
                "result": self._build_precheck_blocked_result(signal_probe, skip_reason=skip_reason),
            }

        if self._is_pathological_signal_profile(signal_probe):
            skip_reason = "pathological_signal_density"
            return {
                "flag": skip_reason,
                "skip_reason": skip_reason,
                "detail": "précheck bloquant: densité de signaux pathologique",
                "result": self._build_precheck_blocked_result(signal_probe, skip_reason=skip_reason),
            }

        return None

    @staticmethod
    def _build_precheck_blocked_result(
        signal_probe: Dict[str, Any],
        *,
        skip_reason: str,
    ) -> SimpleNamespace:
        """Construit un résultat synthétique pour un blocage pré-backtest."""
        total_signals = int(signal_probe.get("total_signals", 0))
        bar_count = int(signal_probe.get("bar_count", 0))
        signal_density = float(signal_probe.get("signal_density", 0.0))
        transition_density = float(signal_probe.get("transition_density", 0.0))
        repeated_same_ratio = float(signal_probe.get("repeated_same_ratio", 0.0))

        metrics = {
            "total_return_pct": -5.0 if skip_reason == "no_trade_signal_profile" else 0.0,
            "sharpe_ratio": -2.0 if skip_reason == "no_trade_signal_profile" else 0.0,
            "sortino_ratio": -2.0 if skip_reason == "no_trade_signal_profile" else 0.0,
            "calmar_ratio": -1.0 if skip_reason == "no_trade_signal_profile" else 0.0,
            "max_drawdown_pct": 0.0,
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0 if skip_reason == "no_trade_signal_profile" else 1.0,
            "expectancy": -0.05 if skip_reason == "no_trade_signal_profile" else 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "volatility_annual": 0.0,
            "precheck_skip_reason": skip_reason,
            "precheck_signal_density": signal_density,
            "precheck_transition_density": transition_density,
            "precheck_repeated_same_ratio": repeated_same_ratio,
            "precheck_truncated": bool(signal_probe.get("precheck_truncated", False)),
            "precheck_max_bars": int(signal_probe.get("precheck_max_bars", 0) or 0),
            "precheck_full_dataset_bars": int(signal_probe.get("full_dataset_bars", 0) or 0),
        }
        if skip_reason == "pathological_signal_density":
            metrics.update(
                {
                    "total_return_pct": -10.0,
                    "sharpe_ratio": -5.0,
                    "sortino_ratio": -5.0,
                    "calmar_ratio": -1.0,
                    "max_drawdown_pct": -25.0,
                    "total_trades": total_signals,
                    "profit_factor": 0.5,
                    "expectancy": -0.05,
                    "avg_loss": -1.0,
                },
            )

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
                "skip_reason": skip_reason,
                "bar_count": bar_count,
                "signal_density": signal_density,
                "transition_density": transition_density,
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
                    fast_metrics=True,
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

        best_result = self._run_backtest(
            strategy_cls,
            data,
            dict(best_params),
            initial_capital,
            symbol=symbol,
            timeframe=timeframe,
            fees_bps=fees_bps,
            slippage_bps=slippage_bps,
            direction_constraint=direction_constraint,
            fast_metrics=False,
        )

        duration_ms = (datetime.now() - start).total_seconds() * 1000.0
        successful_rows.sort(
            key=lambda row: float(row.get("telemetry_score", float("-inf")) or float("-inf")),
            reverse=True,
        )

        raw_result = getattr(best_result, "run_result", None)
        if raw_result is not None and isinstance(getattr(raw_result, "meta", None), dict):
            raw_result.meta["builder_evaluation_mode"] = "sweep"
            raw_result.meta["builder_sweep_total_tested"] = int(len(sweep_plan.get("param_grid", [])))
            raw_result.meta["builder_sweep_success"] = int(success_count)
            raw_result.meta["builder_sweep_failed"] = int(fail_count)
            raw_result.meta["builder_sweep_best_params"] = dict(best_params)
            raw_result.meta["builder_sweep_parameter_values"] = dict(sweep_plan.get("parameter_values", {}))
            raw_result.meta["builder_sweep_fast_metrics"] = True
            raw_result.meta["builder_sweep_full_rerun"] = True
            raw_result.meta["params"] = dict(best_params)

        return best_result, {
            "mode": "sweep",
            "params_used": dict(best_params),
            "sweep_total_tested": int(len(sweep_plan.get("param_grid", []))),
            "sweep_success": int(success_count),
            "sweep_failed": int(fail_count),
            "sweep_duration_ms": round(duration_ms, 3),
            "sweep_fast_metrics": True,
            "sweep_full_rerun": True,
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
        fast_metrics: bool = False,
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
                detail = f"`{missing_name}` is not defined" if missing_name else str(exc)
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
            # Les sweeps Builder utilisent fast_metrics=True, puis relancent le
            # meilleur candidat en métriques complètes avant décision finale.
            fast_metrics=bool(fast_metrics),
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
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
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
        session_id: str | None = None,
        resume_seed_iterations: Optional[List[BuilderIteration]] = None,
        resume_parent_session_id: str = "",
        resume_mode: str = "",
        resume_from_iteration: int = 0,
        resume_extra_iterations: int = 0,
        resume_original_status: str = "",
        resume_source_summary_path: str = "",
        resume_original_model_name: str = "",
        resume_source_session_dir: Path | str | None = None,
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
            raise ValueError("Objectif Builder vide ou invalide après nettoyage (probable collage de logs/traceback).")

        session_id = str(session_id or "").strip() or self.create_session_id(objective)
        session_dir = self.get_session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        objective_indicators = _extract_objective_indicator_names(
            objective,
            available_indicators=self.available_indicators,
        )

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
            logger.warning("date_range extraction failed for data.index", exc_info=True)

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
            objective_indicators=list(objective_indicators),
            indicator_lock_mode=("semi_open" if objective_indicators else ""),
            universe_purpose=str(universe_purpose or "builder"),
            universe_strategy_type=infer_strategy_type(
                strategy_type=universe_strategy_type,
                objective=objective,
            ),
            universe_meta=(dict(universe_meta) if isinstance(universe_meta, dict) else {}),
            builder_execution_mode=str(self.builder_execution_mode or "mono_single_llm"),
            orchestration_mode=str(self.orchestration_mode or "single_llm"),
            instrumentation_enabled=bool(self.instrumentation.enabled),
            ablation_config=dict(self.ablation.get_config()),
            resume_parent_session_id=str(resume_parent_session_id or ""),
            resume_mode=str(resume_mode or ""),
            resume_from_iteration=int(resume_from_iteration or 0),
            resume_extra_iterations=int(resume_extra_iterations or 0),
            resume_original_status=str(resume_original_status or ""),
            resume_source_summary_path=str(resume_source_summary_path or ""),
            resume_original_model_name=str(resume_original_model_name or ""),
        )
        session.direction_constraint = _infer_direction_constraint_from_objective(objective)
        try:
            session.cross_session_memory = load_builder_cross_session_memory(
                objective=objective,
                symbol=symbol,
                timeframe=timeframe,
                session_id=session_id,
                universe_mode=session.universe_mode,
                universe_strategy_type=session.universe_strategy_type,
            )
        except Exception:  # noqa: BLE001
            logger.debug("builder_cross_session_memory_load_failed session=%s", session_id, exc_info=True)
            session.cross_session_memory = []
        model_name = getattr(getattr(self.llm, "config", None), "model", "?")
        session.model_name = model_name
        session.resume_requested_model_name = str(model_name or "")
        if resume_seed_iterations:
            _resume_seed_session_state(session, list(resume_seed_iterations))
        if resume_source_session_dir is not None:
            _resume_copy_strategy_files(Path(resume_source_session_dir), session_dir)
        thought_stream = ThoughtStream(session_id, objective, model_name)
        previous_thought_stream = self._active_thought_stream
        previous_session_id = self._active_builder_session_id
        self._active_thought_stream = thought_stream
        self._active_builder_session_id = session_id

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
            self._abort_active_llm_streams()
            self._active_builder_session_id = previous_session_id
            self._active_thought_stream = previous_thought_stream
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
            self._indicator_history = (
                load_history(self._indicator_policy) if self._indicator_policy.get("enabled", True) else {}
            )
        except Exception:  # noqa: BLE001
            self._indicator_history = {}
        try:
            run_builder_loop_v2(
                self,
                session=session,
                data=data,
                initial_capital=initial_capital,
                thought_stream=thought_stream,
            )
        finally:
            if sys.exc_info()[0] is not None:
                self._active_builder_session_id = previous_session_id
                self._active_thought_stream = previous_thought_stream

        session.instrumentation_enabled = bool(self.instrumentation.enabled)
        session.ablation_config = dict(self.ablation.get_config())
        session.instrumentation_summary = self.instrumentation.session_summary() if self.instrumentation.enabled else {}
        session.restriction_events = dict(session.instrumentation_summary.get("restriction_events", {}) or {})
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
        self._abort_active_llm_streams()
        self._active_builder_session_id = previous_session_id
        self._active_thought_stream = previous_thought_stream

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
                    for ind in it.used_indicators or []:
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
        except Exception:  # noqa: BLE001
            logger.debug("indicator_history_update_failed", exc_info=True)

        return session

    def resume_from_summary(
        self,
        summary_path: Path | str,
        data: pd.DataFrame,
        *,
        mode: Literal["exact_continue", "objective_restart"] = "exact_continue",
        extra_iterations: int = 10,
        restart_max_iterations: int = 20,
        target_sharpe: float | None = None,
        initial_capital: float | None = None,
        symbol: str | None = None,
        timeframe: str | None = None,
        fees_bps: float | None = None,
        slippage_bps: float | None = None,
        universe_mode: str | None = None,
        universe_purpose: str | None = None,
        universe_strategy_type: str | None = None,
        universe_meta: Optional[Dict[str, Any]] = None,
    ) -> BuilderSession:
        """Reprend une session Builder arrêtée à `max_iterations`.

        `exact_continue` réinjecte les itérations déjà persistées et ajoute
        `extra_iterations` au compteur existant. `objective_restart` conserve
        uniquement l'objectif et les paramètres de marché, avec un plafond neuf.
        """
        source_summary_path = Path(summary_path)
        summary = json.loads(source_summary_path.read_text(encoding="utf-8"))
        if not isinstance(summary, dict):
            raise ValueError(f"Résumé Builder invalide: {source_summary_path}")

        source_session_dir = source_summary_path.parent
        parent_session_id = str(summary.get("session_id") or source_session_dir.name or "").strip()
        objective = str(summary.get("objective") or "").strip()
        if not objective:
            raise ValueError(f"Résumé Builder sans objectif exploitable: {source_summary_path}")

        requested_mode = str(mode or "exact_continue").strip()
        seed_iterations: list[BuilderIteration] = []
        resolved_mode = "objective_restart"
        resume_from_iteration = 0
        max_iterations = max(1, int(restart_max_iterations or 20))
        if requested_mode == "exact_continue":
            seed_iterations = _resume_load_seed_iterations(summary, source_session_dir)
            resume_from_iteration = max(
                (int(getattr(iteration, "iteration", 0) or 0) for iteration in seed_iterations),
                default=0,
            )
            if resume_from_iteration > 0:
                resolved_mode = "exact_continue"
                max_iterations = resume_from_iteration + max(1, int(extra_iterations or 10))
            else:
                seed_iterations = []

        run_symbol = str(symbol or summary.get("symbol") or "UNKNOWN").strip() or "UNKNOWN"
        run_timeframe = str(timeframe or summary.get("timeframe") or "1h").strip() or "1h"
        run_initial_capital = (
            float(initial_capital)
            if initial_capital is not None
            else _resume_safe_float(summary.get("initial_capital"), 10000.0)
        )
        run_target_sharpe = (
            float(target_sharpe)
            if target_sharpe is not None
            else _resume_safe_float(summary.get("target_sharpe"), 1.0)
        )
        run_fees_bps = float(fees_bps) if fees_bps is not None else _resume_safe_float(summary.get("fees_bps"), 10.0)
        run_slippage_bps = (
            float(slippage_bps)
            if slippage_bps is not None
            else _resume_safe_float(summary.get("slippage_bps"), 5.0)
        )
        source_universe_meta = summary.get("universe_meta") if isinstance(summary.get("universe_meta"), dict) else {}
        resume_session_id = _resume_session_id(parent_session_id, resolved_mode)

        return self.run(
            objective,
            data,
            max_iterations=max_iterations,
            target_sharpe=run_target_sharpe,
            initial_capital=run_initial_capital,
            symbol=run_symbol,
            timeframe=run_timeframe,
            fees_bps=run_fees_bps,
            slippage_bps=run_slippage_bps,
            universe_mode=str(universe_mode or summary.get("universe_mode") or "canonical"),
            universe_purpose=str(universe_purpose or summary.get("universe_purpose") or "builder"),
            universe_strategy_type=str(
                universe_strategy_type
                if universe_strategy_type is not None
                else summary.get("universe_strategy_type") or "",
            ),
            universe_meta=(
                dict(universe_meta)
                if isinstance(universe_meta, dict)
                else dict(source_universe_meta)
            ),
            session_id=resume_session_id,
            resume_seed_iterations=seed_iterations if resolved_mode == "exact_continue" else None,
            resume_parent_session_id=parent_session_id,
            resume_mode=resolved_mode,
            resume_from_iteration=resume_from_iteration,
            resume_extra_iterations=(
                max(1, int(extra_iterations or 10))
                if resolved_mode == "exact_continue"
                else max_iterations
            ),
            resume_original_status=str(summary.get("status") or ""),
            resume_source_summary_path=str(source_summary_path),
            resume_original_model_name=str(summary.get("model_name") or ""),
            resume_source_session_dir=source_session_dir if resolved_mode == "exact_continue" else None,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_session_summary(self, session):
        save_session_summary(session)


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
    symbol: "str | List[str] | None" = "BTCUSDC",
    timeframe: "str | List[str] | None" = "1h",
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


def align_objective_market_context(objective: str, *, symbol: str, timeframe: str) -> str:
    from agents.builder_objectives import align_objective_market_context as _impl

    return _impl(objective, symbol=symbol, timeframe=timeframe)


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
