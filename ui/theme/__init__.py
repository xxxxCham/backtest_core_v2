"""
Module-ID: ui.theme

Purpose: Système de thème centralisé pour toute l'application.

Role in pipeline: UI theming

Key components: colors, plotly_config

Usage:
    from ui.theme import get_color, get_layout_config, ColorPalette

    # Couleur simple
    color = get_color("primary")

    # Couleur avec palette spécifique
    color = get_color("chart_up", ColorPalette.TRADING)

    # Layout Plotly
    layout = get_layout_config(height=500)

    # Config candlestick
    candle_colors = get_candlestick_colors()

Dependencies: Aucune externe

Conventions:
    - Utiliser get_color() pour toute couleur
    - Utiliser get_layout_config() pour tout layout Plotly
    - Ne JAMAIS hardcoder de couleurs
"""

from .colors import (
    # Constantes
    PALETTES,
    # Dataclass
    ChartColorConfig,
    ColorPalette,
    # Enums
    ThemeMode,
    get_agent_color,
    # Fonctions principales
    get_color,
    get_colors,
    get_palette,
    get_palette_names,
    # Helpers
    get_profit_color,
    get_theme_mode,
    get_trade_color,
    set_palette,
    set_theme_mode,
)
from .plotly_config import (
    # Config globale
    PLOTLY_CHART_CONFIG,
    RESAMPLER_THRESHOLD,
    apply_axis_interaction,
    apply_chart_layout,
    # Application
    apply_dark_theme,
    get_axis_config,
    # Candlesticks
    get_candlestick_colors,
    get_colorscale_diverging,
    get_colorscale_sequential,
    # Trade markers
    get_entry_marker_config,
    get_exit_marker_config,
    # Indicators
    get_indicator_line_config,
    # Layout
    get_layout_config,
    get_volume_colors,
)

__all__ = [
    # === colors.py ===
    # Enums
    "ThemeMode",
    "ColorPalette",
    # Fonctions principales
    "get_color",
    "get_colors",
    "get_palette",
    "set_palette",
    "get_palette_names",
    "set_theme_mode",
    "get_theme_mode",
    # Helpers
    "get_profit_color",
    "get_trade_color",
    "get_agent_color",
    # Dataclass
    "ChartColorConfig",
    # Constantes
    "PALETTES",

    # === plotly_config.py ===
    # Config globale
    "PLOTLY_CHART_CONFIG",
    "RESAMPLER_THRESHOLD",
    # Layout
    "get_layout_config",
    "get_axis_config",
    "get_colorscale_diverging",
    "get_colorscale_sequential",
    # Application
    "apply_dark_theme",
    "apply_chart_layout",
    "apply_axis_interaction",
    # Candlesticks
    "get_candlestick_colors",
    "get_volume_colors",
    # Trade markers
    "get_entry_marker_config",
    "get_exit_marker_config",
    # Indicators
    "get_indicator_line_config",
]
