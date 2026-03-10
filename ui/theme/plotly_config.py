"""
Module-ID: ui.theme.plotly_config

Purpose: Configuration Plotly centralisée - layouts, grilles, fonts, thèmes.

Role in pipeline: visualization config

Key components: get_layout_config(), apply_dark_theme(), CHART_CONFIG

Inputs: Paramètres de graphique (height, title, etc.)

Outputs: Dicts de configuration Plotly

Dependencies: ui.theme.colors

Conventions: Tout graphique Plotly doit utiliser ces configs pour cohérence.

Read-if: Modification layouts globaux, ajout templates.

Skip-if: Vous appelez juste get_layout_config().
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import plotly.graph_objects as go

from .colors import ColorPalette, get_color, get_colors

# ============================================================================
# CONFIGURATION GLOBALE PLOTLY
# ============================================================================

# Config par défaut pour st.plotly_chart
PLOTLY_CHART_CONFIG: Dict[str, Any] = {
    "scrollZoom": True,
    "displayModeBar": True,
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    "displaylogo": False,
}

# Seuil pour activer le resampler (si installé)
RESAMPLER_THRESHOLD = 100_000


# ============================================================================
# LAYOUT CONFIGS
# ============================================================================

def get_layout_config(
    height: int = 520,
    title: Optional[str] = None,
    show_legend: bool = True,
    palette: Optional[ColorPalette] = None,
) -> Dict[str, Any]:
    """
    Retourne la configuration de layout Plotly standard.

    Args:
        height: Hauteur du graphique
        title: Titre optionnel
        show_legend: Afficher la légende
        palette: Palette de couleurs

    Returns:
        Dict de configuration pour fig.update_layout()
    """
    colors = get_colors(palette)

    config = {
        "height": height,
        "template": "plotly_dark",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "paper_bgcolor": "rgba(0,0,0,0)",
        "font": {
            "color": colors.get("text_primary", "#a8b2d1"),
            "size": 11,
            "family": "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
        },
        "hovermode": "x unified",
        "margin": {"l": 50, "r": 50, "t": 50, "b": 50},
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "bgcolor": "rgba(0,0,0,0.3)",
            "bordercolor": colors.get("border", "rgba(128,128,128,0.3)"),
            "borderwidth": 1,
        },
        "showlegend": show_legend,
    }

    if title:
        config["title"] = {
            "text": title,
            "font": {"size": 14, "color": colors.get("text", "#fafafa")},
            "x": 0.5,
            "xanchor": "center",
        }

    return config


def get_axis_config(
    title: Optional[str] = None,
    show_grid: bool = True,
    palette: Optional[ColorPalette] = None,
) -> Dict[str, Any]:
    """
    Retourne la configuration d'axe Plotly.

    Args:
        title: Titre de l'axe
        show_grid: Afficher la grille
        palette: Palette de couleurs

    Returns:
        Dict de configuration pour xaxis/yaxis
    """
    grid_color = get_color("grid_color", palette)
    text_color = get_color("text_secondary", palette)

    config = {
        "showgrid": show_grid,
        "gridcolor": grid_color if show_grid else "rgba(0,0,0,0)",
        "zeroline": False,
        "tickfont": {"color": text_color, "size": 10},
    }

    if title:
        config["title"] = {
            "text": title,
            "font": {"color": text_color, "size": 11},
        }

    return config


def get_colorscale_diverging(palette: Optional[ColorPalette] = None) -> list:
    """
    Retourne une échelle de couleurs divergente (rouge-blanc-vert).
    Utilisé pour heatmaps PnL.
    """
    down = get_color("chart_down", palette)
    up = get_color("chart_up", palette)

    return [
        [0.0, down],
        [0.5, "rgba(255,255,255,0.1)"],
        [1.0, up],
    ]


def get_colorscale_sequential(
    color_key: str = "primary",
    palette: Optional[ColorPalette] = None
) -> list:
    """Retourne une échelle de couleurs séquentielle."""
    base = get_color(color_key, palette)
    return [
        [0.0, "rgba(0,0,0,0)"],
        [1.0, base],
    ]


# ============================================================================
# APPLICATION DE THÈME
# ============================================================================

def apply_dark_theme(fig: go.Figure, palette: Optional[ColorPalette] = None) -> None:
    """
    Applique le thème dark à une figure Plotly.

    Args:
        fig: Figure Plotly à modifier
        palette: Palette de couleurs
    """
    colors = get_colors(palette)

    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=colors.get("text_primary", "#a8b2d1")),
    )

    grid_color = colors.get("grid_color", "rgba(128,128,128,0.1)")
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor=grid_color)


def apply_chart_layout(
    fig: go.Figure,
    height: int = 520,
    y_title: Optional[str] = None,
    x_title: Optional[str] = None,
    palette: Optional[ColorPalette] = None,
) -> None:
    """
    Applique le layout complet à une figure.

    Args:
        fig: Figure Plotly
        height: Hauteur
        y_title: Titre axe Y
        x_title: Titre axe X
        palette: Palette
    """
    layout = get_layout_config(height=height, palette=palette)
    fig.update_layout(**layout)

    if y_title:
        fig.update_yaxes(**get_axis_config(title=y_title, palette=palette))
    else:
        fig.update_yaxes(**get_axis_config(palette=palette))

    if x_title:
        fig.update_xaxes(**get_axis_config(title=x_title, show_grid=False, palette=palette))
    else:
        fig.update_xaxes(showgrid=False)


def apply_axis_interaction(fig: go.Figure, lock_x: bool = False) -> None:
    """
    Configure les interactions de zoom/pan sur les axes.

    Args:
        fig: Figure Plotly
        lock_x: Verrouiller l'axe X (pour comparaisons)
    """
    if lock_x:
        fig.update_xaxes(fixedrange=True)
    fig.update_yaxes(fixedrange=False)


# ============================================================================
# CANDLESTICK CONFIG
# ============================================================================

def get_candlestick_colors(palette: Optional[ColorPalette] = None) -> Dict[str, str]:
    """Retourne les couleurs pour candlesticks."""
    return {
        "increasing_line_color": get_color("candle_up", palette),
        "decreasing_line_color": get_color("candle_down", palette),
        "increasing_fillcolor": get_color("candle_up", palette),
        "decreasing_fillcolor": get_color("candle_down", palette),
    }


def get_volume_colors(palette: Optional[ColorPalette] = None) -> Dict[str, str]:
    """Retourne les couleurs pour barres de volume."""
    return {
        "up": get_color("candle_up", palette),
        "down": get_color("candle_down", palette),
    }


# ============================================================================
# TRADE MARKERS CONFIG
# ============================================================================

def get_entry_marker_config(
    side: str = "LONG",
    palette: Optional[ColorPalette] = None
) -> Dict[str, Any]:
    """
    Retourne la configuration de marqueur d'entrée.

    Args:
        side: "LONG" ou "SHORT"
        palette: Palette

    Returns:
        Dict pour marker=dict(...)
    """
    color = get_color("entry_long" if side == "LONG" else "entry_short", palette)
    return {
        "symbol": "triangle-up" if side == "LONG" else "triangle-down",
        "size": 10,
        "color": color,
        "line": {"width": 1, "color": "white"},
    }


def get_exit_marker_config(
    pnl: float,
    palette: Optional[ColorPalette] = None
) -> Dict[str, Any]:
    """
    Retourne la configuration de marqueur de sortie.

    Args:
        pnl: Profit/Loss du trade
        palette: Palette

    Returns:
        Dict pour marker=dict(...)
    """
    color = get_color("exit_profit" if pnl >= 0 else "exit_loss", palette)
    return {
        "symbol": "triangle-down",
        "size": 10,
        "color": color,
        "line": {"width": 1, "color": "white"},
    }


# ============================================================================
# INDICATOR LINE CONFIG
# ============================================================================

def get_indicator_line_config(
    indicator: str,
    palette: Optional[ColorPalette] = None
) -> Dict[str, Any]:
    """
    Retourne la configuration de ligne pour un indicateur.

    Args:
        indicator: Nom de l'indicateur (bb_mid, ema_fast, etc.)
        palette: Palette

    Returns:
        Dict pour line=dict(...)
    """
    color = get_color(indicator, palette)

    # Styles par défaut selon le type
    width = 1.4
    dash = None

    if "mid" in indicator or "center" in indicator:
        width = 1.5
    elif "upper" in indicator or "lower" in indicator:
        dash = "dash"
        width = 1.2
    elif "threshold" in indicator:
        dash = "dot"
        width = 1.0

    config = {"color": color, "width": width}
    if dash:
        config["dash"] = dash

    return config


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
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
