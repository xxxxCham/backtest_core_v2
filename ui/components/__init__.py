"""
Module-ID: ui.components.__init__

Purpose: Package UI components - centralizes re-exports (charts, monitor, selector, validation, sweep).

Role in pipeline: user interface

Key components: Re-exports render_* functions from active modules

Inputs: None (module imports only)

Outputs: Public API via __all__

Dependencies: .charts, .monitor, .model_selector, .validation_viewer, .sweep_monitor

Conventions: __all__ définit API publique; imports optionnels si deps manquent.

Read-if: Ajout nouveau component ou modification structure.

Skip-if: Vous importez directement depuis ui.components.charts.
"""

# Agent timeline
from .agent_timeline import (
    ActivityType,
    AgentActivity,
    AgentActivityTimeline,
    AgentDecision,
    AgentType,
    DecisionType,
    MetricsSnapshot,
    render_agent_timeline,
    render_mini_timeline,
)

# Charts
from .charts import (
    render_comparison_chart,
    render_equity_and_drawdown,
    render_equity_curve,
    render_multi_sweep_heatmap,
    render_multi_sweep_ranking,
    render_ohlcv_with_indicators,
    render_ohlcv_with_trades,
    render_ohlcv_with_trades_and_indicators,
    render_returns_distribution,
    render_strategy_param_diagram,
    render_trade_pnl_distribution,
)

# Diagram factory
from .diagram_factory import (
    create_atr_channel_diagram,
    create_bollinger_atr_diagram,
    create_ema_cross_diagram,
    create_macd_cross_diagram,
    create_rsi_reversal_diagram,
    render_strategy_diagram,
)

# Model selector
from .model_selector import (
    FALLBACK_LLM_MODELS,
    get_available_models_for_ui,
    get_model_info,
    get_optimal_config_for_role,
    render_model_selector,
)

# Monitor
from .monitor import (
    ResourceReading,
    SystemMonitor,
    SystemMonitorConfig,
    render_mini_monitor,
    render_system_monitor,
)

# Sweep monitor
from .sweep_monitor import (
    SweepMonitor,
    SweepResult,
    SweepStats,
    render_sweep_progress,
    render_sweep_summary,
)

# Validation viewer
from .validation_viewer import (
    ValidationReport,
    ValidationStatus,
    WindowResult,
    render_validation_report,
    render_validation_summary_card,
)

__all__ = [
    # Agent timeline
    "AgentActivity",
    "AgentActivityTimeline",
    "AgentType",
    "ActivityType",
    "DecisionType",
    "MetricsSnapshot",
    "AgentDecision",
    "render_agent_timeline",
    "render_mini_timeline",
    # Charts
    "render_equity_and_drawdown",
    "render_equity_curve",
    "render_ohlcv_with_trades",
    "render_ohlcv_with_trades_and_indicators",
    "render_ohlcv_with_indicators",
    "render_comparison_chart",
    "render_strategy_param_diagram",
    "render_trade_pnl_distribution",
    "render_returns_distribution",
    "render_multi_sweep_heatmap",
    "render_multi_sweep_ranking",
    # Diagram factory
    "create_bollinger_atr_diagram",
    "create_ema_cross_diagram",
    "create_macd_cross_diagram",
    "create_rsi_reversal_diagram",
    "create_atr_channel_diagram",
    "render_strategy_diagram",
    # Model selector
    "FALLBACK_LLM_MODELS",
    "get_available_models_for_ui",
    "get_model_info",
    "get_optimal_config_for_role",
    "render_model_selector",
    # Monitor
    "ResourceReading",
    "SystemMonitor",
    "SystemMonitorConfig",
    "render_system_monitor",
    "render_mini_monitor",
    # Sweep monitor
    "SweepResult",
    "SweepStats",
    "SweepMonitor",
    "render_sweep_progress",
    "render_sweep_summary",
    # Validation viewer
    "ValidationStatus",
    "WindowResult",
    "ValidationReport",
    "render_validation_report",
    "render_validation_summary_card",
]
