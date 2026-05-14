"""Module-ID: agents.builder_constants

Purpose: Constantes partagées entre les sous-modules du Strategy Builder.

Role in pipeline: configuration / données de référence

Skip-if: Vous n'utilisez pas le Strategy Builder.
"""

from __future__ import annotations

import os
import re

from backtest.result_store import get_builder_sessions_dir

# Dossier racine des sandbox
SANDBOX_ROOT = get_builder_sessions_dir()

# Nom de classe standardisé attendu dans le code généré
GENERATED_CLASS_NAME = "BuilderGeneratedStrategy"

# Nombre max d'échecs consécutifs avant arrêt (circuit breaker)
# Bumped from 3 to 5: gemma4:26b/qwen3.6:35b are unstable and a few transient
# failures shouldn't kill an otherwise-promising session.
MAX_CONSECUTIVE_FAILURES = int(os.getenv("BACKTEST_BUILDER_MAX_CONSECUTIVE_FAILURES", "5"))
# Nombre minimum de lignes pour considérer du code comme non-vide
MIN_CODE_LINES = 10
# Nombre max de tentatives de réalignement quand le LLM répond hors phase
MAX_PHASE_REALIGN_ATTEMPTS = 2

# Exceptions AST récupérables (partagées entre builder_ast_utils et strategy_builder)
_AST_PARSE_RECOVERABLE_EXCEPTIONS = (
    SyntaxError,
    ValueError,
    KeyError,
    RuntimeError,
    AttributeError,
    TypeError,
    IndexError,
)
# Nombre mini d'itérations backtestées avant d'autoriser un arrêt LLM "stop"
MIN_SUCCESSFUL_ITERATIONS_BEFORE_STOP = 5
# Checkpoints de progression positive pour arrêter tôt les sessions peu prometteuses
POSITIVE_PROGRESS_GATE_CHECKPOINTS: dict[int, int] = {6: 1, 9: 2}
MIN_TRADES_FOR_POSITIVE_PROGRESS = 1
# Quota max de fallbacks positifs comptabilisés dans la progression
MAX_POSITIVE_FALLBACK_COUNT = 1
# Nombre mini de trades pour accepter une stratégie en cours d'optimisation
MIN_TRADES_FOR_ACCEPT = 20
MAX_DRAWDOWN_PCT_FOR_ACCEPT = 35.0
MIN_RETURN_PCT_FOR_ACCEPT = 0.0
MIN_PROFIT_FACTOR_FOR_ACCEPT = 1.05
# Tolerance: accept if sharpe >= target * ratio AND PF and DD are strong.
SHARPE_TOLERANCE_RATIO = float(os.getenv("BACKTEST_BUILDER_SHARPE_TOLERANCE", "0.85"))
TOLERANT_MIN_PROFIT_FACTOR = float(os.getenv("BACKTEST_BUILDER_TOLERANT_MIN_PF", "1.20"))
TOLERANT_MAX_DRAWDOWN_PCT = float(os.getenv("BACKTEST_BUILDER_TOLERANT_MAX_DD", "30.0"))
# Late-iteration upgrade: when we approach max_iterations and have a strong
# candidate, force-accept rather than walking away with status=max_iterations.
LATE_UPGRADE_REMAINING_ITERS = int(os.getenv("BACKTEST_BUILDER_LATE_UPGRADE_REMAINING", "2"))
# Elite acceptance path: accept with fewer trades when sharpe meets target.
ELITE_SHARPE_BONUS_RATIO = float(os.getenv("BACKTEST_BUILDER_ELITE_SHARPE_RATIO", "1.00"))
ELITE_MIN_TRADES = int(os.getenv("BACKTEST_BUILDER_ELITE_MIN_TRADES", "10"))
# Nombre max de fallbacks déterministes avant arrêt de la session
MAX_DETERMINISTIC_FALLBACKS = int(os.getenv("BACKTEST_BUILDER_MAX_DETERMINISTIC_FALLBACKS", "6"))
PROPOSAL_REALIGN_ATTEMPTS = 1
MIN_BUILDER_BARS = 300

# Per-phase LLM call timeouts (seconds).
_LLM_PHASE_TIMEOUT_PROPOSAL = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_PROPOSAL", "120"))
_LLM_PHASE_TIMEOUT_CODE = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_CODE", "180"))
_LLM_PHASE_TIMEOUT_ANALYSIS = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_ANALYSIS", "90"))
_LLM_PHASE_TIMEOUT_DEFAULT = int(os.getenv("BACKTEST_BUILDER_TIMEOUT_DEFAULT", "120"))

_LLM_PHASE_TIMEOUTS: dict[str, int] = {
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

_PROPOSAL_PLACEHOLDER_VALUES = {
    "",
    "-",
    "—",
    # EN
    "n/a",
    "na",
    "none",
    "null",
    "brief description",
    "what you expect this change to achieve and why",
    "when to buy",
    "when to sell",
    "when to close",
    # FR
    "aucun",
    "aucune",
    "néant",
    "sans objet",
    "non applicable",
    "description brève",
    "brève description",
    "ce que vous attendez de ce changement et pourquoi",
    "quand acheter",
    "quand vendre",
    "quand clôturer",
    "condition d'achat",
    "condition de vente",
    "condition de sortie",
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
