"""
Module-ID: utils.__init__

Purpose: Package utils - exports config, log, visualization, observability.

Role in pipeline: core infrastructure

Key components: Re-exports Config, get_logger, visualization functions

Inputs: None (module imports only)

Outputs: Public API via __all__

Dependencies: Internal (config, log, visualization modules)

Conventions: __all__ définit API publique; imports conditionnels si deps optionnelles.

Read-if: Modification exports ou ordre imports.

Skip-if: Vous importez directement depuis utils.config ou utils.log.
"""

from .config import Config
from .log import get_logger
from .visualization import (
    PLOTLY_AVAILABLE,
    load_and_visualize,
    plot_drawdown,
    plot_equity_curve,
    plot_trades,
    visualize_backtest,
)

__all__ = [
    "get_logger",
    "Config",
    "plot_trades",
    "plot_equity_curve",
    "plot_drawdown",
    "visualize_backtest",
    "load_and_visualize",
    "PLOTLY_AVAILABLE",
]
