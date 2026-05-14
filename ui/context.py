"""Module-ID: ui.context

Purpose: Context loaders - chargement imports backend avec error handling, fallbacks gracieux.

Role in pipeline: configuration/initialization

Key components: BACKEND_AVAILABLE flag, lazy imports BacktestEngine/RunResult/data/strategies/agents

Inputs: None (dynamic imports)

Outputs: Modules importés (ou None + IMPORT_ERROR si echec)

Dependencies: backtest.*, data.*, indicators.*, strategies.*, agents.*

Conventions: sys.path injection; try/except gracieux; fallback lazy loading.

Read-if: Modification imports ou gestion errors.

Skip-if: Vous checked juste BACKEND_AVAILABLE flag.
"""

from __future__ import annotations

# pylint: disable=invalid-name
import sys
from pathlib import Path

# Ensure project root is on sys.path when running via streamlit.
sys.path.insert(0, str(Path(__file__).parent.parent))

BACKEND_AVAILABLE = False
IMPORT_ERROR = ""

BacktestEngine = None
RunResult = None
get_storage = None

# Data/strategy/indicators
load_ohlcv = None
discover_available_data = None
get_data_date_range = None
calculate_indicator = None
get_strategy = None
list_strategies = None
get_strategy_info = None

# Parameters/presets
ParameterSpec = None
compute_search_space_stats = None
list_strategy_versions = None
load_strategy_version = None
resolve_latest_version = None
save_versioned_preset = None

try:
    from backtest.engine import BacktestEngine, RunResult  # noqa: F401
    from backtest.storage import get_storage  # noqa: F401
    from data.loader import discover_available_data, get_data_date_range, load_ohlcv  # noqa: F401
    from indicators.registry import calculate_indicator  # noqa: F401
    from strategies import get_strategy, list_strategies  # noqa: F401
    from strategies.indicators_mapping import get_strategy_info  # noqa: F401
    from utils.parameters import (  # noqa: F401
        ParameterSpec,
        compute_search_space_stats,
        list_strategy_versions,
        load_strategy_version,
        resolve_latest_version,
        save_versioned_preset,
    )

    BACKEND_AVAILABLE = True
except ImportError as exc:
    IMPORT_ERROR = str(exc)
    BACKEND_AVAILABLE = False

LLM_AVAILABLE = False
LLM_IMPORT_ERROR = ""

AutonomousStrategist = None
StrategyBuilder = None
create_optimizer_from_engine = None
create_orchestrator_with_backtest = None
get_strategy_param_bounds = None
get_strategy_param_space = None
create_llm_client = None

OrchestrationLogger = None
generate_session_id = None

ActivityType = None
AgentActivity = None
AgentActivityTimeline = None
AgentType = None
render_agent_timeline = None
render_mini_timeline = None

render_mini_monitor = None
render_deep_trace_viewer = None
render_llm_model_stats_panel = None

LiveOrchestrationViewer = None
render_full_orchestration_viewer = None
render_live_orchestration_panel = None
render_orchestration_logs = None
render_orchestration_summary_table = None

BUILTIN_PRESETS = None
apply_preset_to_config = None
delete_model_preset = None
get_current_config_as_dict = None
list_model_presets = None
load_model_preset = None
save_model_preset = None

try:
    from agents.autonomous_strategist import AutonomousStrategist  # noqa: F401
    from agents.integration import (  # noqa: F401
        create_optimizer_from_engine,
        create_orchestrator_with_backtest,
        get_strategy_param_bounds,
        get_strategy_param_space,
    )
    from agents.llm_client import create_llm_client  # noqa: F401
    from agents.orchestration_logger import OrchestrationLogger, generate_session_id  # noqa: F401
    from agents.strategy_builder import StrategyBuilder  # noqa: F401
    from ui.components.agent_timeline import (  # noqa: F401
        ActivityType,
        AgentActivity,
        AgentActivityTimeline,
        AgentType,
        render_agent_timeline,
        render_mini_timeline,
    )
    from ui.components.monitor import render_mini_monitor  # noqa: F401
    from ui.deep_trace_viewer import (  # noqa: F401
        render_deep_trace_viewer,
        render_llm_model_stats_panel,
    )
    from ui.model_presets import (  # noqa: F401
        BUILTIN_PRESETS,
        apply_preset_to_config,
        delete_model_preset,
        get_current_config_as_dict,
        list_model_presets,
        load_model_preset,
        save_model_preset,
    )
    from ui.orchestration_viewer import (  # noqa: F401
        LiveOrchestrationViewer,
        render_full_orchestration_viewer,
        render_live_orchestration_panel,
        render_orchestration_logs,
        render_orchestration_summary_table,
    )

    LLM_AVAILABLE = True
except ImportError as exc:
    LLM_IMPORT_ERROR = str(exc)
    LLM_AVAILABLE = False
