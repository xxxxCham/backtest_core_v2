"""
Factory pour la génération de diagrammes de stratégies.

Ce module centralise la logique commune des 8 fonctions _render_*_diagram
en utilisant le pattern Factory pour réduire la duplication de code (~860 lignes → ~350 lignes).

Architecture:
    - DiagramConfig: Configuration dataclass pour un diagramme
    - create_base_figure(): Crée la figure Plotly avec subplots optionnels
    - add_price_trace(): Ajoute la trace de prix
    - add_bollinger_traces(): Ajoute les bandes de Bollinger
    - add_indicator_panel(): Ajoute un panel d'indicateur (ATR, RSI, MACD)
    - add_entry_marker(): Ajoute un marqueur d'entrée
    - render_diagram(): Rendu final avec Streamlit

Usage:
    from ui.components.diagram_factory import (
        DiagramConfig, create_base_figure, add_price_trace,
        add_bollinger_traces, render_diagram
    )

    config = DiagramConfig(rows=2, row_heights=[0.7, 0.3], titles=["Prix", "ATR"])
    fig = create_base_figure(config)
    add_price_trace(fig, x, price)
    add_bollinger_traces(fig, x, bb_upper, bb_middle, bb_lower)
    render_diagram(fig, key="diagram_key", caption="Params: ...", help_text="...")

Créé le 23/01/2026 - Phase 3 refactoring charts.py
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# Import du système de thème centralisé
try:
    from ui.theme import get_color, get_colors
    THEME_AVAILABLE = True
except ImportError:
    THEME_AVAILABLE = False
    def get_color(name: str, default: str = "#ffffff") -> str:
        return default
    def get_colors() -> Dict[str, str]:
        return {}

# Configuration Plotly par défaut
PLOTLY_CHART_CONFIG = {
    "displayModeBar": True,
    "displaylogo": False,
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    "scrollZoom": True,
}

DEFAULT_LAYOUT = {
    "template": "plotly_dark",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "paper_bgcolor": "rgba(0,0,0,0)",
    "font": {"color": "#e0e0e0", "size": 11},
}


# ============================================================================
# DATACLASSES DE CONFIGURATION
# ============================================================================

@dataclass
class DiagramConfig:
    """Configuration pour un diagramme de stratégie."""

    rows: int = 1
    cols: int = 1
    row_heights: Optional[List[float]] = None
    subplot_titles: Optional[Tuple[str, ...]] = None
    shared_xaxes: bool = True
    vertical_spacing: float = 0.08
    height: int = 500
    title: Optional[str] = None

    def __post_init__(self):
        if self.row_heights is None and self.rows > 1:
            # Distribution par défaut: 70% prix, 30% indicateur
            self.row_heights = [0.7] + [0.3 / (self.rows - 1)] * (self.rows - 1)


@dataclass
class TraceConfig:
    """Configuration pour une trace Plotly."""

    name: str
    color_key: str  # Clé dans le système de couleurs
    width: float = 1.5
    dash: Optional[str] = None  # "solid", "dot", "dash", "dashdot"
    fill: Optional[str] = None  # "tozeroy", "tonexty", etc.
    fillcolor: Optional[str] = None
    opacity: float = 1.0
    mode: str = "lines"  # "lines", "markers", "lines+markers"
    row: int = 1
    col: int = 1


@dataclass
class MarkerConfig:
    """Configuration pour un marqueur (entrée, sortie, signal)."""

    x: float
    y: float
    name: str
    color_key: str
    symbol: str = "triangle-up"  # "triangle-up", "triangle-down", "circle", "x"
    size: int = 14
    row: int = 1
    col: int = 1


# ============================================================================
# PALETTE DE COULEURS (avec fallback)
# ============================================================================

def _get_palette() -> Dict[str, str]:
    """Retourne la palette de couleurs active."""
    if THEME_AVAILABLE:
        return get_colors()
    # Fallback palette
    return {
        "price_line": "#90caf9",
        "bb_upper": "#ff9800",
        "bb_middle": "#9c27b0",
        "bb_lower": "#4caf50",
        "atr_line": "#ff5252",
        "atr_threshold": "#ffeb3b",
        "ema_fast": "#00bcd4",
        "ema_slow": "#ff9800",
        "macd_line": "#2196f3",
        "macd_signal": "#ff9800",
        "rsi_line": "#9c27b0",
        "rsi_oversold": "#4caf50",
        "rsi_overbought": "#f44336",
        "entry_long": "#00e676",
        "entry_short": "#ff5252",
        "stop_loss": "#f44336",
        "take_profit": "#00e676",
        "atr_channel_upper": "#ff9800",
        "atr_channel_lower": "#4caf50",
        "ema_center": "#9c27b0",
        "equity_line": "#00e676",
    }


def _get_color(key: str, default: str = "#ffffff") -> str:
    """Récupère une couleur du thème ou du fallback."""
    palette = _get_palette()
    return palette.get(key, default)


# ============================================================================
# CRÉATION DE FIGURE
# ============================================================================

def create_base_figure(config: DiagramConfig) -> go.Figure:
    """
    Crée une figure Plotly de base avec configuration optionnelle de subplots.

    Args:
        config: Configuration du diagramme

    Returns:
        Figure Plotly configurée
    """
    if config.rows > 1 or config.cols > 1:
        fig = make_subplots(
            rows=config.rows,
            cols=config.cols,
            shared_xaxes=config.shared_xaxes,
            vertical_spacing=config.vertical_spacing,
            row_heights=config.row_heights,
            subplot_titles=config.subplot_titles,
        )
    else:
        fig = go.Figure()

    return fig


def apply_standard_layout(
    fig: go.Figure,
    config: DiagramConfig,
    dark_theme: bool = True,
) -> None:
    """
    Applique le layout standard à une figure.

    Args:
        fig: Figure Plotly
        config: Configuration du diagramme
        dark_theme: Activer le thème sombre
    """
    layout_update = {
        "height": config.height,
        "template": DEFAULT_LAYOUT["template"] if dark_theme else "plotly_white",
        "plot_bgcolor": DEFAULT_LAYOUT["plot_bgcolor"],
        "paper_bgcolor": DEFAULT_LAYOUT["paper_bgcolor"],
        "font": DEFAULT_LAYOUT["font"],
        "legend": dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        "margin": dict(l=40, r=40, t=40, b=40),
    }

    if config.title:
        layout_update["title"] = config.title

    fig.update_layout(**layout_update)

    # Axes interactifs
    _apply_axis_interaction(fig)


def _apply_axis_interaction(fig: go.Figure) -> None:
    """Active l'interaction sur les axes (zoom, pan)."""
    fig.update_xaxes(
        showgrid=True,
        gridwidth=1,
        gridcolor="rgba(128,128,128,0.2)",
        zeroline=False,
    )
    fig.update_yaxes(
        showgrid=True,
        gridwidth=1,
        gridcolor="rgba(128,128,128,0.2)",
        zeroline=False,
    )


# ============================================================================
# DONNÉES SYNTHÉTIQUES
# ============================================================================

def create_synthetic_price(
    n: int = 160,
    seed: int = 42,
) -> Tuple[np.ndarray, np.ndarray, pd.Series]:
    """
    Génère des données de prix synthétiques pour les diagrammes.

    Args:
        n: Nombre de points
        seed: Graine pour reproductibilité

    Returns:
        Tuple (x, price_array, price_series)
    """
    np.random.seed(seed)
    x = np.arange(n)
    trend = np.linspace(100, 110, n)
    noise = np.cumsum(np.random.randn(n) * 0.5)
    cycle = 3 * np.sin(np.linspace(0, 4 * np.pi, n))
    price = trend + noise + cycle
    return x, price, pd.Series(price)


# ============================================================================
# CALCULS D'INDICATEURS
# ============================================================================

def calculate_bollinger(
    price_series: pd.Series,
    period: int,
    num_std: float = 2.0,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calcule les bandes de Bollinger.

    Args:
        price_series: Série de prix
        period: Période de la moyenne mobile
        num_std: Nombre d'écarts-types

    Returns:
        Tuple (upper, middle, lower)
    """
    middle = price_series.rolling(window=period, min_periods=1).mean()
    std = price_series.rolling(window=period, min_periods=1).std().fillna(0)
    upper = middle + num_std * std
    lower = middle - num_std * std
    return upper, middle, lower


def calculate_atr(
    price_series: pd.Series,
    period: int,
    volatility_factor: float = 0.6,
) -> pd.Series:
    """
    Calcule l'ATR simplifié pour les diagrammes.

    Args:
        price_series: Série de prix
        period: Période ATR
        volatility_factor: Facteur de volatilité synthétique

    Returns:
        Série ATR
    """
    n = len(price_series)
    high = price_series + volatility_factor + 0.3 * np.sin(np.linspace(0, 8 * np.pi, n))
    low = price_series - volatility_factor - 0.3 * np.sin(np.linspace(0, 8 * np.pi, n))
    prev_close = price_series.shift(1).fillna(price_series.iloc[0])

    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    return tr.ewm(span=period, adjust=False).mean()


def calculate_ema(price_series: pd.Series, period: int) -> pd.Series:
    """Calcule une EMA."""
    return price_series.ewm(span=period, adjust=False).mean()


def calculate_rsi(price_series: pd.Series, period: int) -> pd.Series:
    """Calcule le RSI."""
    delta = price_series.diff().fillna(0)
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1/period, adjust=False).mean().replace(0, 1e-6)
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_macd(
    price_series: pd.Series,
    fast_period: int,
    slow_period: int,
    signal_period: int,
) -> Tuple[pd.Series, pd.Series]:
    """Calcule le MACD et sa ligne signal."""
    ema_fast = price_series.ewm(span=fast_period, adjust=False).mean()
    ema_slow = price_series.ewm(span=slow_period, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    return macd_line, signal_line


# ============================================================================
# AJOUT DE TRACES
# ============================================================================

def add_price_trace(
    fig: go.Figure,
    x: np.ndarray,
    price: np.ndarray,
    name: str = "Prix",
    row: int = 1,
    col: int = 1,
) -> None:
    """Ajoute une trace de prix."""
    color = _get_color("price_line", "#90caf9")
    trace = go.Scatter(
        x=x, y=price, name=name,
        line=dict(color=color, width=1.5),
    )
    if row > 1 or col > 1:
        fig.add_trace(trace, row=row, col=col)
    else:
        fig.add_trace(trace)


def add_bollinger_traces(
    fig: go.Figure,
    x: np.ndarray,
    upper: pd.Series,
    middle: pd.Series,
    lower: pd.Series,
    row: int = 1,
    col: int = 1,
    show_fill: bool = True,
) -> None:
    """Ajoute les traces de Bollinger."""
    palette = _get_palette()

    traces = [
        go.Scatter(
            x=x, y=upper, name="BB Upper",
            line=dict(color=palette.get("bb_upper", "#ff9800"), width=1.2),
        ),
        go.Scatter(
            x=x, y=middle, name="BB Middle",
            line=dict(color=palette.get("bb_middle", "#9c27b0"), width=1.4, dash="dot"),
        ),
        go.Scatter(
            x=x, y=lower, name="BB Lower",
            line=dict(color=palette.get("bb_lower", "#4caf50"), width=1.2),
            fill="tonexty" if show_fill else None,
            fillcolor="rgba(156, 39, 176, 0.1)" if show_fill else None,
        ),
    ]

    for trace in traces:
        if row > 1:
            fig.add_trace(trace, row=row, col=col)
        else:
            fig.add_trace(trace)


def add_atr_panel(
    fig: go.Figure,
    x: np.ndarray,
    atr_values: pd.Series,
    threshold: Optional[float] = None,
    row: int = 2,
    col: int = 1,
) -> None:
    """Ajoute un panel ATR."""
    palette = _get_palette()

    fig.add_trace(
        go.Scatter(
            x=x, y=atr_values, name="ATR",
            line=dict(color=palette.get("atr_line", "#ff5252"), width=1.5),
        ),
        row=row, col=col,
    )

    if threshold is not None:
        fig.add_hline(
            y=threshold, line_dash="dot",
            line_color=palette.get("atr_threshold", "#ffeb3b"),
            annotation_text="Seuil ATR",
            annotation_position="top left",
            row=row, col=col,
        )


def add_rsi_panel(
    fig: go.Figure,
    x: np.ndarray,
    rsi_values: pd.Series,
    oversold: float = 30,
    overbought: float = 70,
    row: int = 2,
    col: int = 1,
) -> None:
    """Ajoute un panel RSI avec zones."""
    palette = _get_palette()

    fig.add_trace(
        go.Scatter(
            x=x, y=rsi_values, name="RSI",
            line=dict(color=palette.get("rsi_line", "#9c27b0"), width=1.6),
        ),
        row=row, col=col,
    )

    fig.add_hline(
        y=oversold, line_dash="dot",
        line_color=palette.get("rsi_oversold", "#4caf50"),
        annotation_text="Oversold",
        annotation_position="bottom left",
        row=row, col=col,
    )
    fig.add_hline(
        y=overbought, line_dash="dot",
        line_color=palette.get("rsi_overbought", "#f44336"),
        annotation_text="Overbought",
        annotation_position="top left",
        row=row, col=col,
    )


def add_macd_panel(
    fig: go.Figure,
    x: np.ndarray,
    macd_line: pd.Series,
    signal_line: pd.Series,
    row: int = 2,
    col: int = 1,
) -> None:
    """Ajoute un panel MACD."""
    palette = _get_palette()

    fig.add_trace(
        go.Scatter(
            x=x, y=macd_line, name="MACD",
            line=dict(color=palette.get("macd_line", "#2196f3"), width=1.6),
        ),
        row=row, col=col,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=signal_line, name="Signal",
            line=dict(color=palette.get("macd_signal", "#ff9800"), width=1.4),
        ),
        row=row, col=col,
    )


def add_ema_traces(
    fig: go.Figure,
    x: np.ndarray,
    ema_fast: pd.Series,
    ema_slow: pd.Series,
    fast_label: str = "EMA rapide",
    slow_label: str = "EMA lente",
    row: int = 1,
    col: int = 1,
) -> None:
    """Ajoute les traces EMA."""
    palette = _get_palette()

    traces = [
        go.Scatter(
            x=x, y=ema_fast, name=fast_label,
            line=dict(color=palette.get("ema_fast", "#00bcd4"), width=1.5),
        ),
        go.Scatter(
            x=x, y=ema_slow, name=slow_label,
            line=dict(color=palette.get("ema_slow", "#ff9800"), width=1.5),
        ),
    ]

    for trace in traces:
        if row > 1:
            fig.add_trace(trace, row=row, col=col)
        else:
            fig.add_trace(trace)


def add_atr_channel_traces(
    fig: go.Figure,
    x: np.ndarray,
    upper: pd.Series,
    center: pd.Series,
    lower: pd.Series,
) -> None:
    """Ajoute les traces de canal ATR."""
    palette = _get_palette()

    fig.add_trace(go.Scatter(
        x=x, y=upper, name="Canal haut",
        line=dict(color=palette.get("atr_channel_upper", "#ff9800"), width=1.2),
    ))
    fig.add_trace(go.Scatter(
        x=x, y=center, name="EMA centre",
        line=dict(color=palette.get("ema_center", "#9c27b0"), width=1.4, dash="dot"),
    ))
    fig.add_trace(go.Scatter(
        x=x, y=lower, name="Canal bas",
        line=dict(color=palette.get("atr_channel_lower", "#4caf50"), width=1.2),
    ))


def add_entry_marker(
    fig: go.Figure,
    x: float,
    y: float,
    name: str = "Entrée",
    is_long: bool = True,
    row: int = 1,
    col: int = 1,
) -> None:
    """Ajoute un marqueur d'entrée."""
    palette = _get_palette()
    color = palette.get("entry_long" if is_long else "entry_short", "#00e676" if is_long else "#ff5252")
    symbol = "triangle-up" if is_long else "triangle-down"

    trace = go.Scatter(
        x=[x], y=[y], name=name,
        mode="markers",
        marker=dict(color=color, symbol=symbol, size=14),
    )

    if row > 1:
        fig.add_trace(trace, row=row, col=col)
    else:
        fig.add_trace(trace)


def add_stop_loss_line(
    fig: go.Figure,
    y_value: float,
    x_start: float,
    x_end: float,
    row: int = 1,
    col: int = 1,
) -> None:
    """Ajoute une ligne de stop-loss."""
    palette = _get_palette()

    trace = go.Scatter(
        x=[x_start, x_end], y=[y_value, y_value],
        name="Stop Loss",
        line=dict(color=palette.get("stop_loss", "#f44336"), width=2, dash="dash"),
    )

    if row > 1:
        fig.add_trace(trace, row=row, col=col)
    else:
        fig.add_trace(trace)


def add_take_profit_line(
    fig: go.Figure,
    y_value: float,
    x_start: float,
    x_end: float,
    row: int = 1,
    col: int = 1,
) -> None:
    """Ajoute une ligne de take-profit."""
    palette = _get_palette()

    trace = go.Scatter(
        x=[x_start, x_end], y=[y_value, y_value],
        name="Take Profit",
        line=dict(color=palette.get("take_profit", "#00e676"), width=2, dash="dash"),
    )

    if row > 1:
        fig.add_trace(trace, row=row, col=col)
    else:
        fig.add_trace(trace)


# ============================================================================
# RENDU STREAMLIT
# ============================================================================

def render_diagram(
    fig: go.Figure,
    key: str,
    caption: Optional[str] = None,
    help_text: Optional[str] = None,
) -> None:
    """
    Effectue le rendu final du diagramme avec Streamlit.

    Args:
        fig: Figure Plotly configurée
        key: Clé unique Streamlit
        caption: Texte de légende (paramètres)
        help_text: Texte d'aide Markdown
    """
    st.plotly_chart(fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG)

    if caption:
        st.caption(caption)

    if help_text:
        st.markdown(help_text)


# ============================================================================
# FACTORY FUNCTIONS - DIAGRAMMES COMPLETS
# ============================================================================

def create_bollinger_atr_diagram(
    params: Dict[str, Any],
    key: str,
    n: int = 160,
    variant: str = "standard",  # "standard", "v2", "v3", "long_test"
) -> None:
    """
    Factory pour les diagrammes Bollinger + ATR.

    Args:
        params: Paramètres de la stratégie
        key: Clé unique Streamlit
        n: Nombre de points
        variant: Type de diagramme ("standard", "v2", "v3", "long_test")
    """
    x, price, price_series = create_synthetic_price(n)

    # Extraction des paramètres communs
    bb_period = max(2, min(int(params.get("bb_period", 20)), n - 1))
    bb_std = float(params.get("bb_std", 2.0))
    atr_period = max(2, min(int(params.get("atr_period", 14)), n - 1))

    # Calculs
    bb_upper, bb_middle, bb_lower = calculate_bollinger(price_series, bb_period, bb_std)
    atr_values = calculate_atr(price_series, atr_period)

    # Configuration selon variant
    if variant == "long_test":
        # Version simplifiée sans ATR panel
        config = DiagramConfig(
            rows=1,
            subplot_titles=("Prix + Bollinger",),
            height=460,
        )
        fig = create_base_figure(config)
        add_price_trace(fig, x, price)
        add_bollinger_traces(fig, x, bb_upper, bb_middle, bb_lower)

        # Niveaux bb_pos
        entry_level = float(params.get("entry_level", 0.0))
        sl_level = float(params.get("sl_level", -0.5))
        tp_level = float(params.get("tp_level", 1.0))

        bb_range = (bb_upper - bb_lower).mean()
        entry_y = bb_lower.iloc[n//2] + entry_level * bb_range
        sl_y = bb_lower.iloc[n//2] + sl_level * bb_range
        tp_y = bb_lower.iloc[n//2] + tp_level * bb_range

        add_entry_marker(fig, n//2, entry_y, "Entrée")
        add_stop_loss_line(fig, sl_y, n//2, n-1)
        add_take_profit_line(fig, tp_y, n//2, n-1)

        apply_standard_layout(fig, config)
        caption = f"bb_period={bb_period}, entry={entry_level:.2f}, sl={sl_level:.2f}, tp={tp_level:.2f}"
        help_text = "- Entry: niveau bb_pos pour entrée\n- SL/TP: niveaux relatifs aux bandes"

    else:
        # Versions avec panel ATR
        config = DiagramConfig(
            rows=2,
            row_heights=[0.7, 0.3],
            subplot_titles=("Prix + Bollinger", "ATR"),
            height=550,
        )
        fig = create_base_figure(config)
        add_price_trace(fig, x, price, row=1, col=1)
        add_bollinger_traces(fig, x, bb_upper, bb_middle, bb_lower, row=1, col=1)

        # Paramètres selon variant
        if variant == "v2":
            k_sl = float(params.get("k_sl", 1.5))
            atr_threshold = atr_values.mean() * k_sl
            add_atr_panel(fig, x, atr_values, threshold=atr_threshold, row=2, col=1)
            caption = f"bb_period={bb_period}, bb_std={bb_std:.1f}, atr_period={atr_period}, k_sl={k_sl:.2f}"
            help_text = "- k_sl: multiplicateur ATR pour stop-loss\n- SL basé sur Bollinger lower"

        elif variant == "v3":
            entry_pct_long = float(params.get("entry_pct_long", 0.2))
            stop_factor = float(params.get("stop_factor", 1.5))
            tp_factor = float(params.get("tp_factor", 2.0))
            add_atr_panel(fig, x, atr_values, row=2, col=1)
            caption = f"entry_pct_long={entry_pct_long:.2f}, stop_factor={stop_factor:.2f}, tp_factor={tp_factor:.2f}"
            help_text = "- entry_pct: % dans les bandes\n- stop/tp_factor: multiples ATR"

        else:  # standard
            atr_threshold = float(params.get("atr_threshold", 1.2))
            add_atr_panel(fig, x, atr_values, threshold=atr_threshold, row=2, col=1)
            caption = f"bb_period={bb_period}, bb_std={bb_std:.1f}, atr_period={atr_period}, atr_threshold={atr_threshold:.2f}"
            help_text = "- bb_period/bb_std: bandes de Bollinger\n- atr_period/atr_threshold: filtrage volatilité"

        apply_standard_layout(fig, config)

    render_diagram(fig, key, caption, help_text)


def create_ema_cross_diagram(
    params: Dict[str, Any],
    key: str,
    n: int = 160,
) -> None:
    """Factory pour le diagramme EMA Cross."""
    x, price, price_series = create_synthetic_price(n)

    fast_period = max(2, min(int(params.get("fast_period", 9)), n - 1))
    slow_period = max(3, min(int(params.get("slow_period", 21)), n - 1))

    ema_fast = calculate_ema(price_series, fast_period)
    ema_slow = calculate_ema(price_series, slow_period)

    config = DiagramConfig(
        rows=1,
        height=460,
        title="EMA Cross: croisement rapide/lente",
    )
    fig = create_base_figure(config)

    add_price_trace(fig, x, price)
    add_ema_traces(fig, x, ema_fast, ema_slow, f"EMA {fast_period}", f"EMA {slow_period}")

    apply_standard_layout(fig, config)
    render_diagram(
        fig, key,
        caption=f"fast_period={fast_period}, slow_period={slow_period}",
        help_text="- fast_period: EMA rapide\n- slow_period: EMA lente\n- Signal sur croisement",
    )


def create_macd_cross_diagram(
    params: Dict[str, Any],
    key: str,
    n: int = 160,
) -> None:
    """Factory pour le diagramme MACD Cross."""
    x, price, price_series = create_synthetic_price(n)

    fast_period = max(2, min(int(params.get("fast_period", 12)), n - 1))
    slow_period = max(3, min(int(params.get("slow_period", 26)), n - 1))
    signal_period = max(2, min(int(params.get("signal_period", 9)), n - 1))

    macd_line, signal_line = calculate_macd(price_series, fast_period, slow_period, signal_period)

    config = DiagramConfig(
        rows=2,
        row_heights=[0.65, 0.35],
        subplot_titles=("Prix", "MACD (ligne vs signal)"),
        height=500,
    )
    fig = create_base_figure(config)

    add_price_trace(fig, x, price, row=1, col=1)
    add_macd_panel(fig, x, macd_line, signal_line, row=2, col=1)

    apply_standard_layout(fig, config)
    render_diagram(
        fig, key,
        caption=f"fast_period={fast_period}, slow_period={slow_period}, signal_period={signal_period}",
        help_text="- fast/slow_period: EMAs du MACD\n- signal_period: lissage\n- Signal sur croisement",
    )


def create_rsi_reversal_diagram(
    params: Dict[str, Any],
    key: str,
    n: int = 160,
) -> None:
    """Factory pour le diagramme RSI Reversal."""
    x, price, price_series = create_synthetic_price(n)

    rsi_period = max(2, min(int(params.get("rsi_period", 14)), n - 1))
    oversold = float(params.get("oversold_level", 30))
    overbought = float(params.get("overbought_level", 70))

    rsi = calculate_rsi(price_series, rsi_period)

    config = DiagramConfig(
        rows=2,
        row_heights=[0.6, 0.4],
        subplot_titles=("Prix", "RSI et zones extremes"),
        height=500,
    )
    fig = create_base_figure(config)

    add_price_trace(fig, x, price, row=1, col=1)
    add_rsi_panel(fig, x, rsi, oversold, overbought, row=2, col=1)

    apply_standard_layout(fig, config)
    render_diagram(
        fig, key,
        caption=f"rsi_period={rsi_period}, oversold={oversold:.0f}, overbought={overbought:.0f}",
        help_text="- rsi_period: fenêtre RSI\n- oversold/overbought: seuils de signal",
    )


def create_atr_channel_diagram(
    params: Dict[str, Any],
    key: str,
    n: int = 160,
) -> None:
    """Factory pour le diagramme ATR Channel."""
    x, price, price_series = create_synthetic_price(n)

    atr_period = max(2, min(int(params.get("atr_period", 14)), n - 1))
    atr_mult = float(params.get("atr_mult", 2.0))

    ema_center = calculate_ema(price_series, atr_period)
    atr_values = calculate_atr(price_series, atr_period)

    upper = ema_center + atr_values * atr_mult
    lower = ema_center - atr_values * atr_mult

    config = DiagramConfig(
        rows=1,
        height=460,
        title="ATR Channel: EMA +/- ATR * multiplier",
    )
    fig = create_base_figure(config)

    add_price_trace(fig, x, price)
    add_atr_channel_traces(fig, x, upper, ema_center, lower)

    apply_standard_layout(fig, config)
    render_diagram(
        fig, key,
        caption=f"atr_period={atr_period}, atr_mult={atr_mult:.2f}",
        help_text="- atr_period: fenêtre ATR/EMA\n- atr_mult: largeur du canal",
    )


# ============================================================================
# DISPATCH TABLE
# ============================================================================

DIAGRAM_FACTORIES = {
    "bollinger_atr": lambda p, k: create_bollinger_atr_diagram(p, k, variant="standard"),
    "bollinger_best_longe_3i": lambda p, k: create_bollinger_atr_diagram(p, k, variant="long_test"),
    "bollinger_best_short_3i": lambda p, k: create_bollinger_atr_diagram(p, k, variant="long_test"),
    "bollinger_long_test": lambda p, k: create_bollinger_atr_diagram(p, k, variant="long_test"),
    "bollinger_short_test": lambda p, k: create_bollinger_atr_diagram(p, k, variant="long_test"),  # Même logique
    "bollinger_dual": lambda p, k: create_bollinger_atr_diagram(p, k, variant="standard"),
    "ema_cross": create_ema_cross_diagram,
    "macd_cross": create_macd_cross_diagram,
    "rsi_reversal": create_rsi_reversal_diagram,
    "atr_channel": create_atr_channel_diagram,
    "ma_crossover": create_ema_cross_diagram,  # Même logique
    "ema_stochastic_scalp": create_ema_cross_diagram,  # Fallback EMA
}


def render_strategy_diagram(
    strategy_key: str,
    params: Dict[str, Any],
    key: str,
) -> bool:
    """
    Point d'entrée principal pour rendre un diagramme de stratégie.

    Args:
        strategy_key: Clé de la stratégie
        params: Paramètres de la stratégie
        key: Clé unique Streamlit

    Returns:
        True si le diagramme a été rendu, False sinon
    """
    factory = DIAGRAM_FACTORIES.get(strategy_key)

    if factory is None:
        st.info(f"Schéma non disponible pour la stratégie '{strategy_key}'")
        return False

    try:
        factory(params, key)
        return True
    except Exception as e:
        st.warning(f"Erreur lors du rendu du diagramme: {e}")
        return False


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Config
    "DiagramConfig",
    "TraceConfig",
    "MarkerConfig",
    "PLOTLY_CHART_CONFIG",
    # Figure
    "create_base_figure",
    "apply_standard_layout",
    # Données
    "create_synthetic_price",
    # Indicateurs
    "calculate_bollinger",
    "calculate_atr",
    "calculate_ema",
    "calculate_rsi",
    "calculate_macd",
    # Traces
    "add_price_trace",
    "add_bollinger_traces",
    "add_atr_panel",
    "add_rsi_panel",
    "add_macd_panel",
    "add_ema_traces",
    "add_atr_channel_traces",
    "add_entry_marker",
    "add_stop_loss_line",
    "add_take_profit_line",
    # Rendu
    "render_diagram",
    # Factories
    "create_bollinger_atr_diagram",
    "create_ema_cross_diagram",
    "create_macd_cross_diagram",
    "create_rsi_reversal_diagram",
    "create_atr_channel_diagram",
    # Dispatch
    "DIAGRAM_FACTORIES",
    "render_strategy_diagram",
]
