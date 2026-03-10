"""
Module-ID: agents.builder_constants

Purpose: Constantes partagées entre les sous-modules du Strategy Builder.

Role in pipeline: configuration / données de référence

Skip-if: Vous n'utilisez pas le Strategy Builder.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict

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
MIN_SUCCESSFUL_ITERATIONS_BEFORE_STOP = 3
# Checkpoints de progression positive pour arrêter tôt les sessions peu prometteuses
POSITIVE_PROGRESS_GATE_CHECKPOINTS: Dict[int, int] = {3: 1, 6: 2}
MIN_TRADES_FOR_POSITIVE_PROGRESS = 1
# Nombre mini de trades pour accepter une stratégie en cours d'optimisation
MIN_TRADES_FOR_ACCEPT = 10
MAX_DRAWDOWN_PCT_FOR_ACCEPT = 60.0
MIN_RETURN_PCT_FOR_ACCEPT = 0.0
# Nombre max de fallbacks déterministes avant arrêt de la session
MAX_DETERMINISTIC_FALLBACKS = 4
PROPOSAL_REALIGN_ATTEMPTS = 1
MIN_BUILDER_BARS = 300

# Per-phase LLM call timeouts (seconds).
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
