"""
Module-ID: ui.components.charts

Purpose: Renderers Plotly/Seaborn pour UI - equity, OHLCV, comparaisons, stratégie diagrams.

Role in pipeline: visualization

Key components: render_equity_and_drawdown(), render_ohlcv_with_trades(), render_comparison_chart()

Inputs: Series/DataFrames (equity, OHLCV, metrics), trade results

Outputs: Plotly figures, Streamlit renderers

Dependencies: plotly, seaborn, pandas, streamlit (optionnel)

Conventions: Couleurs cohérentes; resampler pour performance; tooltips interactifs.

Read-if: Modification styling/layout graphiques ou ajout nouveau chart type.

Skip-if: Vous appelez render_equity_and_drawdown(equity, drawdown).
"""

# pylint: disable=too-many-lines

# ============================================================================
# 1. IMPORTS ET CONFIGURATION GLOBALE
# ============================================================================

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from ui.components.diagram_factory import create_bollinger_atr_diagram
from utils.log import get_logger

# Import optionnel de seaborn pour distributions statistiques
try:
    import matplotlib.pyplot as plt
    import seaborn as sns
    SEABORN_AVAILABLE = True
except ImportError:
    SEABORN_AVAILABLE = False

# Import optionnel de plotly-resampler pour downsampling intelligent
try:
    from plotly_resampler import FigureResampler
    PLOTLY_RESAMPLER_AVAILABLE = True
except ImportError:
    PLOTLY_RESAMPLER_AVAILABLE = False

logger = get_logger(__name__)


# ============================================================================
# 2. CONSTANTES ET CONFIGURATION
# ============================================================================

# Configuration Plotly
PLOTLY_CHART_CONFIG = {"scrollZoom": True}
RESAMPLER_THRESHOLD = 100000  # Utiliser resampler si > 100k points

# Palette de couleurs cohérente pour tous les graphiques
COLOR_PALETTE = {
    # Couleurs principales
    "equity_line": "#26a69a",
    "equity_fill": "rgba(38, 166, 154, 0.15)",
    "drawdown_line": "#ef5350",
    "drawdown_fill": "rgba(239, 83, 80, 0.3)",

    # Candlesticks
    "candle_up": "#26a69a",
    "candle_down": "#ef5350",

    # Trades
    "entry_long": "#42a5f5",
    "entry_short": "#ab47bc",
    "exit_profit": "#4caf50",
    "exit_loss": "#f44336",

    # Indicateurs
    "bb_mid": "#ffa726",
    "bb_bands": "#42a5f5",
    "bb_bands_rgba": "rgba(66, 165, 245, 0.1)",
    "bb_entry_z": "rgba(255, 204, 128, 0.9)",
    "ema_fast": "#42a5f5",
    "ema_slow": "#ffb74d",
    "ema_center": "#42a5f5",
    "macd_line": "#26a69a",
    "macd_signal": "#ef5350",
    "rsi_line": "#42a5f5",
    "rsi_oversold": "#26a69a",
    "rsi_overbought": "#ef5350",
    "atr_line": "#ab47bc",
    "atr_threshold": "#ffa726",
    "atr_channel_upper": "#ef5350",
    "atr_channel_lower": "#26a69a",
    "stoch_k": "#42a5f5",
    "stoch_d": "#ffb74d",

    # Diagrammes de stratégies
    "price_line": "#e0e0e0",
    "stop_loss": "#ef5350",
    "take_profit": "#4caf50",
    "bollinger_low": "rgba(100, 160, 200, 0.6)",
    "bollinger_high": "rgba(100, 160, 200, 0.6)",
    "bollinger_fill": "rgba(100, 160, 200, 0.15)",
    "bollinger_mid": "rgba(140, 200, 255, 0.9)",
    "stop_long": "rgba(239, 83, 80, 0.7)",
    "stop_short": "rgba(239, 83, 80, 0.7)",
    "entry_level_long": "rgba(76, 175, 80, 0.9)",
    "entry_level_short": "rgba(171, 71, 188, 0.9)",
    "annotation_stop": "#ef9a9a",
    "annotation_tp": "#81c784",

    # UI
    "text_primary": "#a8b2d1",
    "grid_color": "rgba(128,128,128,0.1)",
    "capital_line": "rgba(200, 200, 200, 0.5)",
}

# Configuration de layout par défaut pour Plotly
DEFAULT_LAYOUT_CONFIG = {
    "template": "plotly_dark",
    "plot_bgcolor": "rgba(0,0,0,0)",
    "paper_bgcolor": "rgba(0,0,0,0)",
    "font": {"color": COLOR_PALETTE["text_primary"], "size": 11},
    "hovermode": "x unified",
}

DEFAULT_GRID_COLOR = COLOR_PALETTE["grid_color"]

# Constantes Seaborn
SEABORN_BG_COLOR = "#0e1117"
SEABORN_AXES_BG_COLOR = "#1e272e"
SEABORN_EDGE_COLOR = "#1e272e"
SEABORN_TEXT_COLOR = COLOR_PALETTE["text_primary"]


# ============================================================================
# 3. HELPERS UTILITAIRES GÉNÉRAUX
# ============================================================================

def _wrap_with_resampler(fig: go.Figure, n_datapoints: int) -> go.Figure:
    """
    Wrap une figure Plotly avec FigureResampler si le dataset est grand.

    Args:
        fig: Figure Plotly originale
        n_datapoints: Nombre de points de données

    Returns:
        Figure Plotly (wrappée ou non)
    """
    if PLOTLY_RESAMPLER_AVAILABLE and n_datapoints > RESAMPLER_THRESHOLD:
        logger.info(
            "Dataset large (%s points) - Activation du resampler",
            "{:,}".format(n_datapoints),
        )
        try:
            # Convertir en FigureResampler pour downsampling intelligent
            return FigureResampler(fig, default_n_shown_samples=2000)
        except Exception as e:
            logger.warning(
                "Echec du resampler: %s - Utilisation de la figure standard",
                e,
            )
            return fig
    return fig


def _apply_axis_interaction(fig: go.Figure, lock_x: bool = False) -> None:
    """
    Enable zoom on Y while keeping X interactive when needed.

    Args:
        fig: Figure Plotly
        lock_x: Verrouiller l'axe X
    """
    fig.update_layout(dragmode="zoom")
    fig.update_xaxes(fixedrange=lock_x)
    fig.update_yaxes(fixedrange=False)


def _normalize_trades_df(trades_df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize trade column names for chart rendering.

    Args:
        trades_df: DataFrame des trades

    Returns:
        DataFrame avec colonnes normalisées
    """
    if trades_df is None or trades_df.empty:
        return trades_df

    rename_map = {}
    if "entry_time" not in trades_df.columns and "entry_ts" in trades_df.columns:
        rename_map["entry_ts"] = "entry_time"
    if "exit_time" not in trades_df.columns and "exit_ts" in trades_df.columns:
        rename_map["exit_ts"] = "exit_time"
    if "entry_price" not in trades_df.columns and "price_entry" in trades_df.columns:
        rename_map["price_entry"] = "entry_price"
    if "exit_price" not in trades_df.columns and "price_exit" in trades_df.columns:
        rename_map["price_exit"] = "exit_price"

    if not rename_map:
        return trades_df

    return trades_df.rename(columns=rename_map)


# ============================================================================
# 4. HELPERS DE STYLE PLOTLY
# ============================================================================

def _apply_chart_layout(
    fig: go.Figure,
    height: int = 450,
    y_title: str = "",
    show_rangeslider: bool = False,
) -> None:
    """
    Applique un style cohérent aux graphiques Plotly.

    Args:
        fig: Figure Plotly
        height: Hauteur du graphique
        y_title: Titre de l'axe Y
        show_rangeslider: Afficher le range slider en bas
    """
    fig.update_layout(
        height=height,
        margin=dict(l=50, r=50, t=30, b=30),
        template=DEFAULT_LAYOUT_CONFIG["template"],
        xaxis_title="",
        yaxis_title=y_title,
        xaxis=dict(
            rangeslider=dict(visible=show_rangeslider),
            gridcolor=DEFAULT_GRID_COLOR,
        ),
        yaxis=dict(gridcolor=DEFAULT_GRID_COLOR),
        plot_bgcolor=DEFAULT_LAYOUT_CONFIG["plot_bgcolor"],
        paper_bgcolor=DEFAULT_LAYOUT_CONFIG["paper_bgcolor"],
        font=DEFAULT_LAYOUT_CONFIG["font"],
        hovermode=DEFAULT_LAYOUT_CONFIG["hovermode"],
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )


def _get_base_layout_config(height: int = 520) -> dict:
    """
    Retourne la configuration de layout de base pour les sous-graphiques.

    Args:
        height: Hauteur du graphique

    Returns:
        Dict de configuration
    """
    return {
        "height": height,
        "template": DEFAULT_LAYOUT_CONFIG["template"],
        "plot_bgcolor": DEFAULT_LAYOUT_CONFIG["plot_bgcolor"],
        "paper_bgcolor": DEFAULT_LAYOUT_CONFIG["paper_bgcolor"],
        "font": DEFAULT_LAYOUT_CONFIG["font"],
        "legend": dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        "margin": dict(l=40, r=40, t=60, b=40),
    }


def _apply_dark_theme(fig: go.Figure) -> None:
    """
    Applique le thème sombre aux axes d'une figure.

    Args:
        fig: Figure Plotly
    """
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor=DEFAULT_GRID_COLOR)


# ============================================================================
# 5. HELPERS DE CALCUL POUR DIAGRAMMES
# ============================================================================

def _create_synthetic_price(n: int = 160, volatility: float = 2.5) -> tuple:
    """
    Crée un prix synthétique pour les diagrammes de stratégies.

    Args:
        n: Nombre de points
        volatility: Facteur de volatilité (défaut: 2.5 pour simulation réaliste)

    Returns:
        Tuple (x, price, price_series)
    """
    np.random.seed(42)  # Reproductibilité
    x = np.arange(n)

    # Tendance de fond (sinusoïdale lente)
    base = 100 + 4 * np.sin(np.linspace(0, 4 * np.pi, n))

    # Oscillations moyennes fréquences
    mid_freq = 0.9 * np.sin(np.linspace(0, 11 * np.pi, n))

    # Bruit réaliste avec marche aléatoire
    random_walk = np.random.randn(n).cumsum() * 0.3

    # Chocs de volatilité (pics aléatoires)
    shocks = np.random.randn(n) * volatility

    # Composition finale
    price = base + mid_freq + random_walk + shocks
    price_series = pd.Series(price)
    return x, price, price_series


def _calculate_bollinger(
    price_series: pd.Series,
    bb_period: int,
    bb_std: float,
    entry_z: Optional[float] = None,
) -> dict:
    """
    Calcule les bandes de Bollinger.

    Args:
        price_series: Série de prix
        bb_period: Période de la moyenne mobile
        bb_std: Nombre d'écarts-types
        entry_z: Z-score pour les bandes d'entrée (optionnel)

    Returns:
        Dict avec upper, lower, middle, entry_upper, entry_lower
    """
    middle = price_series.rolling(window=bb_period, min_periods=1).mean()
    sigma = price_series.rolling(window=bb_period, min_periods=1).std(ddof=0).fillna(0.5)
    upper = middle + sigma * bb_std
    lower = middle - sigma * bb_std

    result = {
        "upper": upper,
        "lower": lower,
        "middle": middle,
        "sigma": sigma,
    }

    if entry_z is not None:
        result["entry_upper"] = middle + sigma * entry_z
        result["entry_lower"] = middle - sigma * entry_z

    return result


def _calculate_atr(
    price_series: pd.Series,
    atr_period: int,
    atr_percentile: float,
) -> tuple:
    """
    Calcule l'ATR (Average True Range) et son seuil de percentile.

    Args:
        price_series: Série de prix
        atr_period: Période de calcul de l'ATR
        atr_percentile: Percentile pour le seuil

    Returns:
        Tuple (atr_values, atr_threshold)
    """
    atr_values = price_series.diff().abs().rolling(window=atr_period, min_periods=1).mean()
    atr_threshold = float(np.nanpercentile(atr_values, atr_percentile))
    return atr_values, atr_threshold


# ============================================================================
# 6. HELPERS DIAGRAMMES DE STRATÉGIES
# ============================================================================

def _render_bollinger_atr_diagram(
    params: Dict[str, Any],
    key: str,
    n: int = 300,  # Augmenté pour mieux voir l'effet des périodes élevées
) -> None:
    """
    Diagramme pour la stratégie Bollinger ATR v1.

    Args:
        params: Paramètres de la stratégie
        key: Clé unique Streamlit
        n: Nombre de points de données (augmenté à 300 pour périodes élevées)
    """
    x, price, price_series = _create_synthetic_price(n)

    # Extraction des paramètres
    bb_period = max(2, min(int(params.get("bb_period", 20)), n - 1))
    bb_std = float(params.get("bb_std", 2.0))
    entry_z = float(params.get("entry_z", bb_std))
    atr_period = max(2, min(int(params.get("atr_period", 14)), n - 1))
    atr_percentile = float(params.get("atr_percentile", 30))
    k_sl = float(params.get("k_sl", 1.5))

    # Calcul des indicateurs
    bb = _calculate_bollinger(price_series, bb_period, bb_std, entry_z)
    atr_values, atr_threshold = _calculate_atr(price_series, atr_period, atr_percentile)

    # Création du graphique
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
        subplot_titles=(
            "Prix + Bandes de Bollinger (entry_z)",
            "ATR et filtre de volatilite (atr_percentile)",
        ),
    )

    # Bandes de Bollinger
    fig.add_trace(
        go.Scatter(
            x=x, y=bb["lower"], name="Bollinger bas",
            line=dict(color=COLOR_PALETTE["bollinger_low"], width=1),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=bb["upper"], name="Bollinger haut",
            line=dict(color=COLOR_PALETTE["bollinger_high"], width=1),
            fill="tonexty", fillcolor=COLOR_PALETTE["bollinger_fill"],
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=bb["middle"], name="Bollinger milieu",
            line=dict(color=COLOR_PALETTE["bollinger_mid"], width=1.5),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=bb["entry_upper"], name="Seuil entry_z haut",
            line=dict(color=COLOR_PALETTE["bb_entry_z"], width=1, dash="dot"),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=bb["entry_lower"], name="Seuil entry_z bas",
            line=dict(color=COLOR_PALETTE["bb_entry_z"], width=1, dash="dot"),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=price, name="Prix",
            line=dict(color=COLOR_PALETTE["price_line"], width=1.5),
        ),
        row=1, col=1,
    )

    # Exemple d'entrée avec stop-loss
    entry_index = int(n * 0.72)
    entry_price = price[entry_index]
    atr_at_entry = float(atr_values.iloc[entry_index])
    stop_price = entry_price - k_sl * atr_at_entry

    fig.add_trace(
        go.Scatter(
            x=[entry_index], y=[entry_price],
            mode="markers", name="Exemple entree",
            marker=dict(color=COLOR_PALETTE["equity_line"], size=8),
        ),
        row=1, col=1,
    )
    fig.add_shape(
        type="line", x0=entry_index, x1=entry_index,
        y0=entry_price, y1=stop_price,
        line=dict(color=COLOR_PALETTE["stop_loss"], width=2),
        row=1, col=1,
    )
    fig.add_annotation(
        x=entry_index, y=stop_price,
        text=f"Stop = k_sl x ATR ({k_sl:.2f})",
        showarrow=True, arrowhead=2, ax=20, ay=20,
        font=dict(color=COLOR_PALETTE["annotation_stop"], size=10),
        row=1, col=1,
    )

    # ATR
    fig.add_trace(
        go.Scatter(
            x=x, y=atr_values, name="ATR",
            line=dict(color=COLOR_PALETTE["atr_line"], width=1.5),
        ),
        row=2, col=1,
    )
    fig.add_hline(
        y=atr_threshold, line_dash="dot",
        line_color=COLOR_PALETTE["atr_threshold"],
        annotation_text=f"Seuil {atr_percentile:.0f}%",
        annotation_position="top left",
        row=2, col=1,
    )

    # Layout
    fig.update_layout(**_get_base_layout_config())
    _apply_dark_theme(fig)
    _apply_axis_interaction(fig)

    st.plotly_chart(fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG)
    st.caption(
        f"Parametres: bb_period={bb_period}, bb_std={bb_std:.2f}, entry_z={entry_z:.2f}, "
        f"atr_period={atr_period}, atr_percentile={atr_percentile:.0f}%, k_sl={k_sl:.2f}"
    )
    st.markdown(
        "- bb_period: fenetre de moyenne pour la ligne centrale.\n"
        "- bb_std: largeur des bandes (ecart-type).\n"
        "- entry_z: seuil d'entree en z-score (declenchement).\n"
        "- atr_period: fenetre ATR pour la volatilite.\n"
        "- atr_percentile: seuil de volatilite minimum.\n"
        "- k_sl: distance du stop = k_sl x ATR."
    )


def _render_bollinger_atr_v2_diagram(
    params: Dict[str, Any],
    key: str,
    n: int = 300,
) -> None:
    """
    Diagramme pour la stratégie Bollinger ATR v2 (stop-loss basé sur Bollinger).

    Args:
        params: Paramètres de la stratégie
        key: Clé unique Streamlit
        n: Nombre de points de données (augmenté à 300 pour périodes élevées)
    """
    x, price, price_series = _create_synthetic_price(n)

    # Extraction des paramètres
    bb_period = max(2, min(int(params.get("bb_period", 20)), n - 1))
    bb_std = float(params.get("bb_std", 2.0))
    entry_z = float(params.get("entry_z", bb_std))
    atr_period = max(2, min(int(params.get("atr_period", 14)), n - 1))
    atr_percentile = float(params.get("atr_percentile", 30))
    bb_stop_factor = float(params.get("bb_stop_factor", 0.5))

    # Calcul des indicateurs
    bb = _calculate_bollinger(price_series, bb_period, bb_std, entry_z)
    atr_values, atr_threshold = _calculate_atr(price_series, atr_period, atr_percentile)

    # Calculer les stop-loss Bollinger
    bb_distance_lower = bb["middle"] - bb["lower"]
    bb_distance_upper = bb["upper"] - bb["middle"]
    stop_long = bb["lower"] - bb_stop_factor * bb_distance_lower
    stop_short = bb["upper"] + bb_stop_factor * bb_distance_upper

    # Création du graphique
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
        subplot_titles=(
            "Prix + Bandes de Bollinger + Stop-Loss Bollinger (V2)",
            "ATR et filtre de volatilite",
        ),
    )

    # Bandes de Bollinger
    fig.add_trace(
        go.Scatter(
            x=x, y=bb["lower"], name="Bollinger bas",
            line=dict(color=COLOR_PALETTE["bollinger_low"], width=1),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=bb["upper"], name="Bollinger haut",
            line=dict(color=COLOR_PALETTE["bollinger_high"], width=1),
            fill="tonexty", fillcolor=COLOR_PALETTE["bollinger_fill"],
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=bb["middle"], name="Bollinger milieu",
            line=dict(color=COLOR_PALETTE["bollinger_mid"], width=1.5),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=bb["entry_upper"], name="Seuil entry_z haut",
            line=dict(color=COLOR_PALETTE["bb_entry_z"], width=1, dash="dot"),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=bb["entry_lower"], name="Seuil entry_z bas",
            line=dict(color=COLOR_PALETTE["bb_entry_z"], width=1, dash="dot"),
        ),
        row=1, col=1,
    )

    # Niveaux de stop-loss
    fig.add_trace(
        go.Scatter(
            x=x, y=stop_long, name="Stop LONG",
            line=dict(color=COLOR_PALETTE["stop_long"], width=1.2, dash="dash"),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=stop_short, name="Stop SHORT",
            line=dict(color=COLOR_PALETTE["stop_short"], width=1.2, dash="dash"),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=price, name="Prix",
            line=dict(color=COLOR_PALETTE["price_line"], width=1.5),
        ),
        row=1, col=1,
    )

    # Exemple d'entrée LONG
    entry_index = int(n * 0.25)
    entry_price = float(bb["entry_lower"].iloc[entry_index])
    stop_price = float(stop_long.iloc[entry_index])

    fig.add_trace(
        go.Scatter(
            x=[entry_index], y=[entry_price],
            mode="markers", name="Exemple entree LONG",
            marker=dict(color=COLOR_PALETTE["equity_line"], size=8),
        ),
        row=1, col=1,
    )
    fig.add_shape(
        type="line", x0=entry_index, x1=entry_index,
        y0=entry_price, y1=stop_price,
        line=dict(color=COLOR_PALETTE["stop_loss"], width=2),
        row=1, col=1,
    )
    fig.add_annotation(
        x=entry_index, y=stop_price,
        text=f"Stop = lower - {bb_stop_factor:.1f} × (mid-low)",
        showarrow=True, arrowhead=2, ax=-40, ay=20,
        font=dict(color=COLOR_PALETTE["annotation_stop"], size=10),
        row=1, col=1,
    )

    # ATR
    fig.add_trace(
        go.Scatter(
            x=x, y=atr_values, name="ATR",
            line=dict(color=COLOR_PALETTE["atr_line"], width=1.5),
        ),
        row=2, col=1,
    )
    fig.add_hline(
        y=atr_threshold, line_dash="dot",
        line_color=COLOR_PALETTE["atr_threshold"],
        annotation_text=f"Seuil {atr_percentile:.0f}%",
        annotation_position="top left",
        row=2, col=1,
    )

    # Layout
    fig.update_layout(**_get_base_layout_config())
    _apply_dark_theme(fig)
    _apply_axis_interaction(fig)

    st.plotly_chart(fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG)
    st.caption(
        f"Parametres: bb_period={bb_period}, bb_std={bb_std:.2f}, entry_z={entry_z:.2f}, "
        f"atr_period={atr_period}, atr_percentile={atr_percentile:.0f}%, bb_stop_factor={bb_stop_factor:.2f}"
    )
    st.markdown(
        "**V2: Stop-loss basé sur les Bandes de Bollinger**\n\n"
        "- bb_stop_factor: Distance du stop depuis les bandes (0.2=proche, 2.0=loin).\n"
        "- LONG: stop = lower - bb_stop_factor × (middle - lower)\n"
        "- SHORT: stop = upper + bb_stop_factor × (upper - middle)\n"
        "- Le stop-loss est FIXE au moment de l'entrée."
    )


def _render_bollinger_atr_v3_diagram(
    params: Dict[str, Any],
    key: str,
    n: int = 300,
) -> None:
    """
    Diagramme pour la stratégie Bollinger ATR v3 (entrées, stop et TP variables).

    Args:
        params: Paramètres de la stratégie
        key: Clé unique Streamlit
        n: Nombre de points de données (augmenté à 300 pour périodes élevées)
    """
    x, price, price_series = _create_synthetic_price(n)

    # Extraction des paramètres
    bb_period = max(2, min(int(params.get("bb_period", 20)), n - 1))
    bb_std = float(params.get("bb_std", 2.0))
    atr_period = max(2, min(int(params.get("atr_period", 14)), n - 1))
    atr_percentile = float(params.get("atr_percentile", 30))
    entry_pct_long = float(params.get("entry_pct_long", 0.0))
    entry_pct_short = float(params.get("entry_pct_short", 1.0))
    stop_factor = float(params.get("stop_factor", 0.5))
    tp_factor = float(params.get("tp_factor", 0.7))

    # Calcul des indicateurs
    bb = _calculate_bollinger(price_series, bb_period, bb_std)
    atr_values, atr_threshold = _calculate_atr(price_series, atr_period, atr_percentile)

    # Calculer les niveaux d'entrée sur l'échelle unifiée
    total_distance = bb["upper"] - bb["lower"]
    entry_level_long = bb["lower"] + entry_pct_long * total_distance
    entry_level_short = bb["lower"] + entry_pct_short * total_distance

    # Création du graphique
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
        subplot_titles=(
            f"Prix + Bandes de Bollinger (V3: {bb_std:.1f}σ) + Niveaux d'entrée variables",
            "ATR et filtre de volatilite",
        ),
    )

    # Bandes de Bollinger
    fig.add_trace(
        go.Scatter(
            x=x, y=bb["lower"], name="Bollinger bas (0%)",
            line=dict(color=COLOR_PALETTE["bollinger_low"], width=1),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=bb["upper"], name="Bollinger haut (100%)",
            line=dict(color=COLOR_PALETTE["bollinger_high"], width=1),
            fill="tonexty", fillcolor=COLOR_PALETTE["bollinger_fill"],
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=bb["middle"], name="Bollinger milieu (50%)",
            line=dict(color=COLOR_PALETTE["bollinger_mid"], width=1.5),
        ),
        row=1, col=1,
    )

    # Niveaux d'entrée
    fig.add_trace(
        go.Scatter(
            x=x, y=entry_level_long,
            name=f"Entrée LONG ({entry_pct_long*100:.0f}%)",
            line=dict(color=COLOR_PALETTE["entry_level_long"], width=1.5, dash="dot"),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=entry_level_short,
            name=f"Entrée SHORT ({entry_pct_short*100:.0f}%)",
            line=dict(color=COLOR_PALETTE["entry_level_short"], width=1.5, dash="dot"),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=price, name="Prix",
            line=dict(color=COLOR_PALETTE["price_line"], width=1.5),
        ),
        row=1, col=1,
    )

    # Exemple de trade LONG
    entry_index = int(n * 0.25)
    entry_price = float(entry_level_long.iloc[entry_index])
    distance = float(total_distance.iloc[entry_index])
    stop_price = entry_price - stop_factor * distance
    tp_price = entry_price + tp_factor * distance

    fig.add_trace(
        go.Scatter(
            x=[entry_index], y=[entry_price],
            mode="markers", name="Exemple entree LONG",
            marker=dict(color=COLOR_PALETTE["equity_line"], size=8),
        ),
        row=1, col=1,
    )

    # Ligne Stop
    fig.add_shape(
        type="line", x0=entry_index, x1=entry_index + 15,
        y0=stop_price, y1=stop_price,
        line=dict(color=COLOR_PALETTE["stop_loss"], width=2, dash="dash"),
        row=1, col=1,
    )
    # Ligne TP
    fig.add_shape(
        type="line", x0=entry_index, x1=entry_index + 15,
        y0=tp_price, y1=tp_price,
        line=dict(color=COLOR_PALETTE["take_profit"], width=2, dash="dash"),
        row=1, col=1,
    )
    fig.add_annotation(
        x=entry_index + 15, y=stop_price,
        text=f"Stop ({stop_factor*100:.0f}%)",
        showarrow=False, xshift=45,
        font=dict(color=COLOR_PALETTE["annotation_stop"], size=9),
        row=1, col=1,
    )
    fig.add_annotation(
        x=entry_index + 15, y=tp_price,
        text=f"TP ({tp_factor*100:.0f}%)",
        showarrow=False, xshift=35,
        font=dict(color=COLOR_PALETTE["annotation_tp"], size=9),
        row=1, col=1,
    )

    # ATR
    fig.add_trace(
        go.Scatter(
            x=x, y=atr_values, name="ATR",
            line=dict(color=COLOR_PALETTE["atr_line"], width=1.5),
        ),
        row=2, col=1,
    )
    fig.add_hline(
        y=atr_threshold, line_dash="dot",
        line_color=COLOR_PALETTE["atr_threshold"],
        annotation_text=f"Seuil {atr_percentile:.0f}%",
        annotation_position="top left",
        row=2, col=1,
    )

    # Layout
    fig.update_layout(**_get_base_layout_config())
    _apply_dark_theme(fig)
    _apply_axis_interaction(fig)

    st.plotly_chart(fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG)
    st.caption(
        f"Parametres: bb_period={bb_period}, bb_std={bb_std:.2f}, "
        f"entry_long={entry_pct_long*100:.0f}%, entry_short={entry_pct_short*100:.0f}%, "
        f"stop_factor={stop_factor:.2f}, tp_factor={tp_factor:.2f}"
    )
    st.markdown(
        "**V3: Entrées, Stop et TP Variables sur Échelle Unifiée**\n\n"
        "- **Échelle**: 0% = lower_band, 50% = middle_band, 100% = upper_band\n"
        "- **entry_pct_long**: Position d'entrée LONG (-50% à +20%)\n"
        "- **entry_pct_short**: Position d'entrée SHORT (+80% à +150%)\n"
        "- **stop_factor**: Distance stop depuis entry_price (10% à 100% de distance totale)\n"
        "- **tp_factor**: Distance TP depuis entry_price (20% à 150% de distance totale)\n"
        "- **bb_std**: Amplitude des bandes (1σ à 4σ)\n\n"
        "Formule: entry_level = lower + entry_pct × (upper - lower)"
    )


def _render_ema_cross_diagram(
    params: Dict[str, Any],
    key: str,
    n: int = 160,
) -> None:
    """
    Diagramme pour la stratégie EMA Cross.

    Args:
        params: Paramètres de la stratégie
        key: Clé unique Streamlit
        n: Nombre de points de données
    """
    x, price, price_series = _create_synthetic_price(n)

    # Extraction des paramètres
    fast_period = max(2, min(int(params.get("fast_period", 12)), n - 1))
    slow_period = max(3, min(int(params.get("slow_period", 26)), n - 1))

    # Calcul des EMA
    ema_fast = price_series.ewm(span=fast_period, adjust=False).mean()
    ema_slow = price_series.ewm(span=slow_period, adjust=False).mean()

    # Détection des croisements
    diff = ema_fast - ema_slow
    cross_idx = diff.diff().fillna(0)
    cross_points = cross_idx[cross_idx != 0].index.tolist()
    marker_index = int(cross_points[0]) if cross_points else int(n * 0.55)

    # Création du graphique
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=x, y=price, name="Prix",
            line=dict(color=COLOR_PALETTE["price_line"], width=1.5),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=ema_fast, name=f"EMA rapide ({fast_period})",
            line=dict(color=COLOR_PALETTE["ema_fast"], width=1.8),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=ema_slow, name=f"EMA lente ({slow_period})",
            line=dict(color=COLOR_PALETTE["ema_slow"], width=1.8),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[marker_index], y=[price[marker_index]],
            mode="markers", name="Exemple croisement",
            marker=dict(color=COLOR_PALETTE["equity_line"], size=8),
        )
    )

    # Layout
    fig.update_layout(
        height=460,
        template=DEFAULT_LAYOUT_CONFIG["template"],
        plot_bgcolor=DEFAULT_LAYOUT_CONFIG["plot_bgcolor"],
        paper_bgcolor=DEFAULT_LAYOUT_CONFIG["paper_bgcolor"],
        font=DEFAULT_LAYOUT_CONFIG["font"],
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=40, t=40, b=40),
        title="EMA Cross: croisement de moyennes mobiles",
    )
    _apply_dark_theme(fig)
    _apply_axis_interaction(fig)

    st.plotly_chart(fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG)
    st.caption(f"Parametres: fast_period={fast_period}, slow_period={slow_period}")
    st.markdown(
        "- fast_period: vitesse de la moyenne rapide.\n"
        "- slow_period: tendance de fond (plus lente).\n"
        "- Un signal apparait quand la rapide croise la lente."
    )


def _render_macd_cross_diagram(
    params: Dict[str, Any],
    key: str,
    n: int = 160,
) -> None:
    """
    Diagramme pour la stratégie MACD Cross.

    Args:
        params: Paramètres de la stratégie
        key: Clé unique Streamlit
        n: Nombre de points de données
    """
    x, price, price_series = _create_synthetic_price(n)

    # Extraction des paramètres
    fast_period = max(2, min(int(params.get("fast_period", 12)), n - 1))
    slow_period = max(3, min(int(params.get("slow_period", 26)), n - 1))
    signal_period = max(2, min(int(params.get("signal_period", 9)), n - 1))

    # Calcul du MACD
    ema_fast = price_series.ewm(span=fast_period, adjust=False).mean()
    ema_slow = price_series.ewm(span=slow_period, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()

    # Création du graphique
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.65, 0.35],
        subplot_titles=("Prix", "MACD (ligne vs signal)"),
    )

    fig.add_trace(
        go.Scatter(
            x=x, y=price, name="Prix",
            line=dict(color=COLOR_PALETTE["price_line"], width=1.5),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=macd_line, name="MACD",
            line=dict(color=COLOR_PALETTE["macd_line"], width=1.6),
        ),
        row=2, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=signal_line, name="Signal",
            line=dict(color=COLOR_PALETTE["macd_signal"], width=1.4),
        ),
        row=2, col=1,
    )

    # Layout
    fig.update_layout(**_get_base_layout_config())
    _apply_dark_theme(fig)
    _apply_axis_interaction(fig)

    st.plotly_chart(fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG)
    st.caption(
        f"Parametres: fast_period={fast_period}, slow_period={slow_period}, "
        f"signal_period={signal_period}"
    )
    st.markdown(
        "- fast_period: EMA rapide pour le MACD.\n"
        "- slow_period: EMA lente pour le MACD.\n"
        "- signal_period: lissage de la ligne MACD.\n"
        "- Signal quand MACD croise la ligne signal."
    )


def _render_rsi_reversal_diagram(
    params: Dict[str, Any],
    key: str,
    n: int = 160,
) -> None:
    """
    Diagramme pour la stratégie RSI Reversal.

    Args:
        params: Paramètres de la stratégie
        key: Clé unique Streamlit
        n: Nombre de points de données
    """
    x, price, price_series = _create_synthetic_price(n)

    # Extraction des paramètres
    rsi_period = max(2, min(int(params.get("rsi_period", 14)), n - 1))
    oversold = float(params.get("oversold_level", 30))
    overbought = float(params.get("overbought_level", 70))

    # Calcul du RSI
    delta = price_series.diff().fillna(0)
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / rsi_period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / rsi_period, adjust=False).mean().replace(0, 1e-6)
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # Création du graphique
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.6, 0.4],
        subplot_titles=("Prix", "RSI et zones extremes"),
    )

    fig.add_trace(
        go.Scatter(
            x=x, y=price, name="Prix",
            line=dict(color=COLOR_PALETTE["price_line"], width=1.5),
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=rsi, name="RSI",
            line=dict(color=COLOR_PALETTE["rsi_line"], width=1.6),
        ),
        row=2, col=1,
    )
    fig.add_hline(
        y=oversold, line_dash="dot",
        line_color=COLOR_PALETTE["rsi_oversold"],
        annotation_text="Oversold",
        annotation_position="bottom left",
        row=2, col=1,
    )
    fig.add_hline(
        y=overbought, line_dash="dot",
        line_color=COLOR_PALETTE["rsi_overbought"],
        annotation_text="Overbought",
        annotation_position="top left",
        row=2, col=1,
    )

    # Layout
    fig.update_layout(**_get_base_layout_config())
    _apply_dark_theme(fig)
    _apply_axis_interaction(fig)

    st.plotly_chart(fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG)
    st.caption(
        f"Parametres: rsi_period={rsi_period}, oversold={oversold:.0f}, overbought={overbought:.0f}"
    )
    st.markdown(
        "- rsi_period: fenetre de calcul du RSI.\n"
        "- oversold_level: seuil bas pour signal long.\n"
        "- overbought_level: seuil haut pour signal short."
    )


def _render_atr_channel_diagram(
    params: Dict[str, Any],
    key: str,
    n: int = 160,
) -> None:
    """
    Diagramme pour la stratégie ATR Channel.

    Args:
        params: Paramètres de la stratégie
        key: Clé unique Streamlit
        n: Nombre de points de données
    """
    x, price, price_series = _create_synthetic_price(n)

    # Extraction des paramètres
    atr_period = max(2, min(int(params.get("atr_period", 14)), n - 1))
    atr_mult = float(params.get("atr_mult", 2.0))

    # Calcul de l'ATR Channel
    ema_center = price_series.ewm(span=atr_period, adjust=False).mean()
    high = price_series + 0.6 + 0.3 * np.sin(np.linspace(0, 8 * np.pi, n))
    low = price_series - 0.6 - 0.3 * np.sin(np.linspace(0, 8 * np.pi, n))
    prev_close = price_series.shift(1).fillna(price_series.iloc[0])
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_values = tr.ewm(span=atr_period, adjust=False).mean()
    upper = ema_center + atr_values * atr_mult
    lower = ema_center - atr_values * atr_mult

    # Création du graphique
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=x, y=price, name="Prix",
            line=dict(color=COLOR_PALETTE["price_line"], width=1.5),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=upper, name="Canal haut",
            line=dict(color=COLOR_PALETTE["atr_channel_upper"], width=1.2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=lower, name="Canal bas",
            line=dict(color=COLOR_PALETTE["atr_channel_lower"], width=1.2),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x, y=ema_center, name="EMA centre",
            line=dict(color=COLOR_PALETTE["ema_center"], width=1.4, dash="dot"),
        )
    )

    # Layout
    fig.update_layout(
        height=460,
        template=DEFAULT_LAYOUT_CONFIG["template"],
        plot_bgcolor=DEFAULT_LAYOUT_CONFIG["plot_bgcolor"],
        paper_bgcolor=DEFAULT_LAYOUT_CONFIG["paper_bgcolor"],
        font=DEFAULT_LAYOUT_CONFIG["font"],
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=40, t=40, b=40),
        title="ATR Channel: EMA +/- ATR * multiplier",
    )
    _apply_dark_theme(fig)
    _apply_axis_interaction(fig)

    st.plotly_chart(fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG)
    st.caption(f"Parametres: atr_period={atr_period}, atr_mult={atr_mult:.2f}")
    st.markdown(
        "- atr_period: fenetre ATR et EMA du canal.\n"
        "- atr_mult: largeur du canal (volatilite)."
    )


# ============================================================================
# 7. HELPERS SEABORN
# ============================================================================

def _apply_seaborn_dark_style(fig, ax) -> None:
    """
    Applique le style sombre cohérent pour les graphiques Seaborn.

    Args:
        fig: Figure matplotlib
        ax: Axes matplotlib
    """
    fig.patch.set_facecolor(SEABORN_BG_COLOR)
    ax.set_facecolor(SEABORN_AXES_BG_COLOR)
    ax.tick_params(colors=SEABORN_TEXT_COLOR)
    ax.spines['bottom'].set_color(SEABORN_TEXT_COLOR)
    ax.spines['top'].set_color(SEABORN_TEXT_COLOR)
    ax.spines['right'].set_color(SEABORN_TEXT_COLOR)
    ax.spines['left'].set_color(SEABORN_TEXT_COLOR)


# ============================================================================
# 8. FONCTIONS PUBLIQUES - EQUITY CURVES
# ============================================================================

def render_equity_and_drawdown(
    equity: pd.Series,
    initial_capital: float = 10000.0,
    key: str = "equity_dd",
    height: int = 550,
) -> None:
    """
    Affiche la courbe d'équité et le drawdown dans un graphique à 2 panneaux.

    Args:
        equity: Série pandas de l'équité
        initial_capital: Capital initial
        key: Clé unique Streamlit
        height: Hauteur du graphique
    """
    if equity is None or equity.empty:
        st.warning("⚠️ Aucune donnée d'équité à afficher")
        return

    # Calculer le drawdown
    cummax = equity.expanding().max()
    drawdown = ((equity - cummax) / cummax) * 100

    # Créer le graphique à 2 sous-graphiques
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
        subplot_titles=("💰 Équité ($)", "📉 Drawdown (%)"),
    )

    # Graphique d'équité
    fig.add_trace(
        go.Scatter(
            x=equity.index,
            y=equity.values,
            name="Équité",
            line=dict(color=COLOR_PALETTE["equity_line"], width=2),
            fill="tozeroy",
            fillcolor=COLOR_PALETTE["equity_fill"],
            hovertemplate="<b>%{x}</b><br>$%{y:,.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    # Ligne du capital initial
    fig.add_hline(
        y=initial_capital,
        line_dash="dash",
        line_color=COLOR_PALETTE["capital_line"],
        annotation_text=f"Capital: ${initial_capital:,.0f}",
        annotation_position="left",
        row=1,
        col=1,
    )

    # Graphique de drawdown
    fig.add_trace(
        go.Scatter(
            x=drawdown.index,
            y=drawdown.values,
            name="Drawdown",
            fill="tozeroy",
            line=dict(color=COLOR_PALETTE["drawdown_line"], width=1),
            fillcolor=COLOR_PALETTE["drawdown_fill"],
            hovertemplate="<b>%{x}</b><br>%{y:.2f}%<extra></extra>",
        ),
        row=2,
        col=1,
    )

    # Mise en forme
    fig.update_layout(
        height=height,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=50, t=40, b=30),
        template=DEFAULT_LAYOUT_CONFIG["template"],
        plot_bgcolor=DEFAULT_LAYOUT_CONFIG["plot_bgcolor"],
        paper_bgcolor=DEFAULT_LAYOUT_CONFIG["paper_bgcolor"],
        font=DEFAULT_LAYOUT_CONFIG["font"],
        hovermode=DEFAULT_LAYOUT_CONFIG["hovermode"],
    )

    fig.update_xaxes(gridcolor=DEFAULT_GRID_COLOR)
    fig.update_yaxes(title_text="$", gridcolor=DEFAULT_GRID_COLOR, row=1, col=1)
    fig.update_yaxes(title_text="%", gridcolor=DEFAULT_GRID_COLOR, row=2, col=1)
    _apply_axis_interaction(fig)

    # Wrapper avec resampler si grand dataset
    fig = _wrap_with_resampler(fig, len(equity))

    st.plotly_chart(
        fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG
    )


def render_equity_curve(
    equity: pd.Series,
    initial_capital: float = 10000.0,
    title: str = "💹 Courbe d'Équité",
    key: str = "equity_curve",
    height: int = 350,
) -> None:
    """
    Affiche uniquement la courbe d'équité (version simple).

    Args:
        equity: Série pandas de l'équité
        initial_capital: Capital initial
        title: Titre du graphique
        key: Clé unique Streamlit
        height: Hauteur du graphique
    """
    if equity is None or equity.empty:
        st.warning("⚠️ Aucune donnée d'équité")
        return

    st.markdown(f"#### {title}")

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=equity.index,
            y=equity.values,
            mode="lines",
            name="Équité",
            line=dict(color=COLOR_PALETTE["equity_line"], width=2),
            fill="tozeroy",
            fillcolor=COLOR_PALETTE["equity_fill"],
            hovertemplate="<b>%{x}</b><br>$%{y:,.2f}<extra></extra>",
        )
    )

    # Ligne du capital initial
    fig.add_hline(
        y=initial_capital,
        line_dash="dash",
        line_color=COLOR_PALETTE["capital_line"],
        annotation_text=f"Initial: ${initial_capital:,.0f}",
        annotation_position="right",
    )

    _apply_chart_layout(fig, height=height, y_title="Équité ($)")
    _apply_axis_interaction(fig)
    st.plotly_chart(
        fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG
    )


# ============================================================================
# 9. FONCTIONS PUBLIQUES - OHLCV CHARTS
# ============================================================================

def render_ohlcv_with_trades(
    df: pd.DataFrame,
    trades_df: pd.DataFrame,
    title: str = "📈 Prix et Trades",
    key: str = "ohlcv_trades",
    height: int = 500,
) -> None:
    """
    Affiche un graphique OHLCV avec marqueurs de trades.

    Args:
        df: DataFrame OHLCV avec colonnes open, high, low, close
        trades_df: DataFrame des trades avec entry_time, exit_time, entry_price, exit_price
        title: Titre du graphique
        key: Clé unique Streamlit
        height: Hauteur du graphique
    """
    if df.empty:
        st.warning("⚠️ Aucune donnée OHLCV")
        return

    # Vérifier les colonnes requises
    required_ohlc = {"open", "high", "low", "close"}
    if not required_ohlc.issubset(set(df.columns)):
        st.error(f"❌ Colonnes manquantes: {required_ohlc - set(df.columns)}")
        return

    trades_df = _normalize_trades_df(trades_df)

    st.markdown(f"#### {title}")

    fig = go.Figure()

    # Candlestick OHLC
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="OHLC",
            increasing_line_color=COLOR_PALETTE["candle_up"],
            decreasing_line_color=COLOR_PALETTE["candle_down"],
        )
    )

    # Ajouter les marqueurs de trades
    if not trades_df.empty and "entry_time" in trades_df.columns:
        # Points d'entrée
        entries = trades_df[trades_df["entry_time"].notna()].copy()
        if not entries.empty:
            # Déterminer les couleurs par type de trade (LONG/SHORT)
            entry_colors = entries.get("side", "LONG").map(
                {"LONG": COLOR_PALETTE["entry_long"], "SHORT": COLOR_PALETTE["entry_short"]}
            ).fillna(COLOR_PALETTE["entry_long"])

            fig.add_trace(
                go.Scatter(
                    x=entries["entry_time"],
                    y=entries["entry_price"],
                    mode="markers",
                    name="Entry",
                    marker=dict(
                        symbol="triangle-up",
                        size=10,
                        color=entry_colors,
                        line=dict(width=1, color="white"),
                    ),
                    hovertemplate="<b>Entry</b><br>%{x}<br>$%{y:.2f}<extra></extra>",
                )
            )

        # Points de sortie
        exits = trades_df[trades_df["exit_time"].notna()].copy()
        if not exits.empty:
            # Couleurs basées sur profit/loss
            exit_colors = []
            pnl_values = []
            for _, trade in exits.iterrows():
                pnl = trade.get("pnl", 0)
                pnl_values.append(pnl)
                exit_colors.append(
                    COLOR_PALETTE["exit_profit"] if pnl > 0 else COLOR_PALETTE["exit_loss"]
                )

            fig.add_trace(
                go.Scatter(
                    x=exits["exit_time"],
                    y=exits["exit_price"],
                    mode="markers",
                    name="Exit",
                    marker=dict(
                        symbol="triangle-down",
                        size=10,
                        color=exit_colors,
                        line=dict(width=1, color="white"),
                    ),
                    customdata=pnl_values,
                    hovertemplate="<b>Exit</b><br>%{x}<br>Prix: $%{y:.2f}<br>PNL: $%{customdata:.2f}<extra></extra>",
                )
            )

    _apply_chart_layout(fig, height=height, y_title="Prix (USD)")
    _apply_axis_interaction(fig)
    st.plotly_chart(
        fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG
    )


def render_ohlcv_with_trades_and_indicators(
    df: pd.DataFrame,
    trades_df: pd.DataFrame,
    overlays: Dict[str, Any],
    active_indicators: Optional[List[str]] = None,
    title: str = "📈 Prix, Indicateurs et Trades",
    key: str = "ohlcv_trades_indicators",
    height: int = 650,
) -> None:
    """
    Affiche un graphique OHLCV avec indicateurs et marqueurs de trades.
    """
    if df.empty:
        st.warning("⚠️ Aucune donnée OHLCV")
        return

    if not {"open", "high", "low", "close"}.issubset(set(df.columns)):
        st.error("❌ Colonnes OHLC manquantes")
        return

    trades_df = _normalize_trades_df(trades_df)

    if active_indicators is None:
        active_set = set(overlays.keys())
    else:
        active_set = set(active_indicators)
    active_set = {name for name in active_set if name in overlays}
    has_macd = "macd" in active_set
    has_rsi = "rsi" in active_set
    has_atr = "atr" in active_set
    has_stochastic = "stochastic" in active_set
    show_second_panel = has_macd or has_rsi or has_atr or has_stochastic

    def _add_trace(trace, row: int = 1) -> None:
        if show_second_panel:
            fig.add_trace(trace, row=row, col=1)
        else:
            fig.add_trace(trace)

    if show_second_panel:
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            row_heights=[0.7, 0.3],
            subplot_titles=(title, "Oscillators"),
        )
    else:
        fig = go.Figure()

    candlestick = go.Candlestick(
        x=df.index,
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name="OHLC",
        increasing_line_color=COLOR_PALETTE["candle_up"],
        decreasing_line_color=COLOR_PALETTE["candle_down"],
    )
    _add_trace(candlestick, row=1)

    if "bollinger" in active_set:
        bb = overlays["bollinger"]
        upper = bb.get("upper")
        lower = bb.get("lower")
        mid = bb.get("mid")
        entry_upper = bb.get("entry_upper")
        entry_lower = bb.get("entry_lower")
        if mid is not None:
            _add_trace(
                go.Scatter(
                    x=df.index,
                    y=mid,
                    name="BB Mid",
                    line=dict(color=COLOR_PALETTE["bb_mid"], width=1),
                ),
                row=1,
            )
        if upper is not None:
            _add_trace(
                go.Scatter(
                    x=df.index,
                    y=upper,
                    name="BB Upper",
                    line=dict(color=COLOR_PALETTE["bb_bands"], width=1, dash="dash"),
                ),
                row=1,
            )
        if lower is not None:
            _add_trace(
                go.Scatter(
                    x=df.index,
                    y=lower,
                    name="BB Lower",
                    line=dict(color=COLOR_PALETTE["bb_bands"], width=1, dash="dash"),
                    fill="tonexty",
                    fillcolor=COLOR_PALETTE["bb_bands_rgba"],
                ),
                row=1,
            )
        if entry_upper is not None:
            _add_trace(
                go.Scatter(
                    x=df.index,
                    y=entry_upper,
                    name="Entry Z haut",
                    line=dict(color="#ffcc80", width=1, dash="dot"),
                ),
                row=1,
            )
        if entry_lower is not None:
            _add_trace(
                go.Scatter(
                    x=df.index,
                    y=entry_lower,
                    name="Entry Z bas",
                    line=dict(color="#ffcc80", width=1, dash="dot"),
                ),
                row=1,
            )

    if "ema" in active_set:
        ema = overlays["ema"]
        fast = ema.get("fast")
        slow = ema.get("slow")
        center = ema.get("center")
        if fast is not None:
            _add_trace(
                go.Scatter(
                    x=df.index,
                    y=fast,
                    name="EMA rapide",
                    line=dict(color=COLOR_PALETTE["ema_fast"], width=1.4),
                ),
                row=1,
            )
        if slow is not None:
            _add_trace(
                go.Scatter(
                    x=df.index,
                    y=slow,
                    name="EMA lente",
                    line=dict(color=COLOR_PALETTE["ema_slow"], width=1.4),
                ),
                row=1,
            )
        if center is not None:
            _add_trace(
                go.Scatter(
                    x=df.index,
                    y=center,
                    name="EMA centre",
                    line=dict(color=COLOR_PALETTE["ema_center"], width=1.4, dash="dot"),
                ),
                row=1,
            )

    if "ma" in active_set:
        ma = overlays["ma"]
        fast = ma.get("fast")
        slow = ma.get("slow")
        center = ma.get("center")
        if fast is not None:
            _add_trace(
                go.Scatter(
                    x=df.index,
                    y=fast,
                    name="MA rapide",
                    line=dict(color=COLOR_PALETTE["ema_fast"], width=1.4),
                ),
                row=1,
            )
        if slow is not None:
            _add_trace(
                go.Scatter(
                    x=df.index,
                    y=slow,
                    name="MA lente",
                    line=dict(color=COLOR_PALETTE["ema_slow"], width=1.4),
                ),
                row=1,
            )
        if center is not None:
            _add_trace(
                go.Scatter(
                    x=df.index,
                    y=center,
                    name="MA",
                    line=dict(color=COLOR_PALETTE["ema_center"], width=1.4, dash="dot"),
                ),
                row=1,
            )

    if "atr_channel" in active_set:
        channel = overlays["atr_channel"]
        upper = channel.get("upper")
        lower = channel.get("lower")
        center = channel.get("center")
        if upper is not None:
            _add_trace(
                go.Scatter(
                    x=df.index,
                    y=upper,
                    name="Canal haut",
                    line=dict(color=COLOR_PALETTE["atr_channel_upper"], width=1.2),
                ),
                row=1,
            )
        if lower is not None:
            _add_trace(
                go.Scatter(
                    x=df.index,
                    y=lower,
                    name="Canal bas",
                    line=dict(color=COLOR_PALETTE["atr_channel_lower"], width=1.2),
                ),
                row=1,
            )
        if center is not None:
            _add_trace(
                go.Scatter(
                    x=df.index,
                    y=center,
                    name="EMA centre",
                    line=dict(color=COLOR_PALETTE["ema_center"], width=1.2, dash="dot"),
                ),
                row=1,
            )

    if not trades_df.empty and "entry_time" in trades_df.columns:
        entries = trades_df[trades_df["entry_time"].notna()].copy()
        if not entries.empty:
            entry_colors = entries.get("side", "LONG").map(
                {"LONG": COLOR_PALETTE["entry_long"], "SHORT": COLOR_PALETTE["entry_short"]}
            ).fillna(COLOR_PALETTE["entry_long"])
            _add_trace(
                go.Scatter(
                    x=entries["entry_time"],
                    y=entries["entry_price"],
                    mode="markers",
                    name="Entry",
                    marker=dict(
                        symbol="triangle-up",
                        size=10,
                        color=entry_colors,
                        line=dict(width=1, color="white"),
                    ),
                    hovertemplate="<b>Entry</b><br>%{x}<br>$%{y:.2f}<extra></extra>",
                ),
                row=1,
            )

        exits = trades_df[trades_df["exit_time"].notna()].copy()
        if not exits.empty:
            exit_colors = []
            pnl_values = []
            for _, trade in exits.iterrows():
                pnl = trade.get("pnl", 0)
                pnl_values.append(pnl)
                exit_colors.append(
                    COLOR_PALETTE["exit_profit"] if pnl > 0 else COLOR_PALETTE["exit_loss"]
                )

            _add_trace(
                go.Scatter(
                    x=exits["exit_time"],
                    y=exits["exit_price"],
                    mode="markers",
                    name="Exit",
                    marker=dict(
                        symbol="triangle-down",
                        size=10,
                        color=exit_colors,
                        line=dict(width=1, color="white"),
                    ),
                    customdata=pnl_values,
                    hovertemplate="<b>Exit</b><br>%{x}<br>Prix: $%{y:.2f}<br>PNL: $%{customdata:.2f}<extra></extra>",
                ),
                row=1,
            )

    if show_second_panel:
        if has_macd:
            macd = overlays["macd"]
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=macd.get("macd"),
                    name="MACD",
                    line=dict(color=COLOR_PALETTE["macd_line"], width=1.4),
                ),
                row=2,
                col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=macd.get("signal"),
                    name="Signal",
                    line=dict(color=COLOR_PALETTE["macd_signal"], width=1.2),
                ),
                row=2,
                col=1,
            )
        if has_rsi:
            rsi = overlays["rsi"]
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=rsi.get("rsi"),
                    name="RSI",
                    line=dict(color=COLOR_PALETTE["rsi_line"], width=1.4),
                ),
                row=2,
                col=1,
            )
            oversold = rsi.get("oversold")
            overbought = rsi.get("overbought")
            if oversold is not None:
                fig.add_hline(
                    y=oversold,
                    line_dash="dot",
                    line_color=COLOR_PALETTE["rsi_oversold"],
                    annotation_text="Oversold",
                    annotation_position="bottom left",
                    row=2,
                    col=1,
                )
            if overbought is not None:
                fig.add_hline(
                    y=overbought,
                    line_dash="dot",
                    line_color=COLOR_PALETTE["rsi_overbought"],
                    annotation_text="Overbought",
                    annotation_position="top left",
                    row=2,
                    col=1,
                )
        if has_stochastic:
            stoch = overlays["stochastic"]
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=stoch.get("k"),
                    name="%K",
                    line=dict(color=COLOR_PALETTE["stoch_k"], width=1.2),
                ),
                row=2,
                col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=stoch.get("d"),
                    name="%D",
                    line=dict(color=COLOR_PALETTE["stoch_d"], width=1.2),
                ),
                row=2,
                col=1,
            )
            oversold = stoch.get("oversold")
            overbought = stoch.get("overbought")
            if oversold is not None:
                fig.add_hline(
                    y=oversold,
                    line_dash="dot",
                    line_color=COLOR_PALETTE["rsi_oversold"],
                    annotation_text="Oversold",
                    annotation_position="bottom left",
                    row=2,
                    col=1,
                )
            if overbought is not None:
                fig.add_hline(
                    y=overbought,
                    line_dash="dot",
                    line_color=COLOR_PALETTE["rsi_overbought"],
                    annotation_text="Overbought",
                    annotation_position="top left",
                    row=2,
                    col=1,
                )
        if has_atr:
            atr = overlays["atr"]
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=atr.get("atr"),
                    name="ATR",
                    line=dict(color=COLOR_PALETTE["atr_line"], width=1.4),
                ),
                row=2,
                col=1,
            )
            threshold = atr.get("threshold")
            if threshold is not None:
                fig.add_hline(
                    y=threshold,
                    line_dash="dot",
                    line_color=COLOR_PALETTE["atr_threshold"],
                    annotation_text="ATR Threshold",
                    annotation_position="top left",
                    row=2,
                    col=1,
                )

        fig.update_layout(
            height=height,
            template=DEFAULT_LAYOUT_CONFIG["template"],
            plot_bgcolor=DEFAULT_LAYOUT_CONFIG["plot_bgcolor"],
            paper_bgcolor=DEFAULT_LAYOUT_CONFIG["paper_bgcolor"],
            font=DEFAULT_LAYOUT_CONFIG["font"],
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
            ),
            margin=dict(l=40, r=40, t=60, b=40),
            hovermode=DEFAULT_LAYOUT_CONFIG["hovermode"],
        )
        fig.update_xaxes(showgrid=False)
        fig.update_yaxes(gridcolor=DEFAULT_GRID_COLOR, row=1, col=1)

        # Configuration spécifique pour les oscillateurs (row 2)
        # Déterminer la plage appropriée selon les indicateurs actifs
        if has_rsi or has_stochastic:
            # RSI et Stochastic sont normalisés entre 0-100
            fig.update_yaxes(
                gridcolor=DEFAULT_GRID_COLOR,
                range=[-5, 105],  # Légère marge pour visibilité
                row=2,
                col=1
            )
        elif has_macd:
            # MACD nécessite une échelle auto mais centrée sur 0
            fig.update_yaxes(
                gridcolor=DEFAULT_GRID_COLOR,
                zeroline=True,
                zerolinecolor="rgba(255,255,255,0.3)",
                zerolinewidth=1,
                row=2,
                col=1
            )
        elif has_atr:
            # ATR est toujours positif, auto-scale depuis 0
            fig.update_yaxes(
                gridcolor=DEFAULT_GRID_COLOR,
                rangemode="tozero",
                row=2,
                col=1
            )
        else:
            # Par défaut, auto-scale normal
            fig.update_yaxes(gridcolor=DEFAULT_GRID_COLOR, row=2, col=1)

        _apply_axis_interaction(fig)

        # Wrapper avec resampler si grand dataset
        fig = _wrap_with_resampler(fig, len(df))

        st.plotly_chart(
            fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG
        )
        return

    _apply_chart_layout(fig, height=height, y_title="Prix (USD)")
    _apply_axis_interaction(fig)

    # Wrapper avec resampler si grand dataset
    fig = _wrap_with_resampler(fig, len(df))

    st.plotly_chart(
        fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG
    )


def render_ohlcv_with_indicators(
    df: pd.DataFrame,
    indicators: Dict[str, Any],
    title: str = "📊 Prix et Indicateurs",
    key: str = "ohlcv_indicators",
    height: int = 500,
) -> None:
    """
    Affiche un graphique OHLCV avec indicateurs techniques.

    Args:
        df: DataFrame OHLCV
        indicators: Dict d'indicateurs (ex: {'bollinger': {'upper': series, 'lower': series}})
        title: Titre du graphique
        key: Clé unique Streamlit
        height: Hauteur du graphique
    """
    if df.empty:
        st.warning("⚠️ Aucune donnée OHLCV")
        return

    st.markdown(f"#### {title}")

    fig = go.Figure()

    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="OHLC",
            increasing_line_color=COLOR_PALETTE["candle_up"],
            decreasing_line_color=COLOR_PALETTE["candle_down"],
        )
    )

    # Ajouter les indicateurs
    if "bollinger" in indicators:
        bb = indicators["bollinger"]
        if "upper" in bb and "lower" in bb and "mid" in bb:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=bb["mid"],
                    name="BB Mid",
                    line=dict(color=COLOR_PALETTE["bb_mid"], width=1),
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=bb["upper"],
                    name="BB Upper",
                    line=dict(color=COLOR_PALETTE["bb_bands"], width=1, dash="dash"),
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=bb["lower"],
                    name="BB Lower",
                    line=dict(color=COLOR_PALETTE["bb_bands"], width=1, dash="dash"),
                    fill="tonexty",
                    fillcolor=COLOR_PALETTE["bb_bands_rgba"],
                )
            )

    _apply_chart_layout(fig, height=height, y_title="Prix (USD)")
    _apply_axis_interaction(fig)
    st.plotly_chart(
        fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG
    )


# ============================================================================
# 10. FONCTIONS PUBLIQUES - COMPARISON
# ============================================================================

def render_comparison_chart(
    results_list: List[Dict[str, Any]],
    metric: str = "sharpe_ratio",
    title: str = "📊 Comparaison des Résultats",
    key: str = "comparison",
    height: int = 400,
) -> None:
    """
    Affiche un graphique de comparaison entre plusieurs résultats.

    Args:
        results_list: Liste de dict avec 'name' et 'metrics'
        metric: Métrique à comparer
        title: Titre du graphique
        key: Clé unique Streamlit
        height: Hauteur du graphique
    """
    if not results_list:
        st.warning("⚠️ Aucun résultat à comparer")
        return

    st.markdown(f"#### {title}")

    names = [r.get("name", f"Run {i}") for i, r in enumerate(results_list)]
    values = [r.get("metrics", {}).get(metric, 0) for r in results_list]

    fig = go.Figure(
        data=[
            go.Bar(
                x=names,
                y=values,
                marker_color=[
                    COLOR_PALETTE["equity_line"] if v > 0 else COLOR_PALETTE["drawdown_line"]
                    for v in values
                ],
                text=[f"{v:.2f}" for v in values],
                textposition="outside",
            )
        ]
    )

    fig.update_layout(
        title=metric.replace("_", " ").title(),
        height=height,
        showlegend=False,
        template=DEFAULT_LAYOUT_CONFIG["template"],
        plot_bgcolor=DEFAULT_LAYOUT_CONFIG["plot_bgcolor"],
        paper_bgcolor=DEFAULT_LAYOUT_CONFIG["paper_bgcolor"],
        font=DEFAULT_LAYOUT_CONFIG["font"],
        margin=dict(l=50, r=50, t=50, b=50),
    )

    fig.update_xaxes(gridcolor=DEFAULT_GRID_COLOR)
    fig.update_yaxes(gridcolor=DEFAULT_GRID_COLOR)

    _apply_axis_interaction(fig)
    st.plotly_chart(
        fig, width="stretch", key=key, config=PLOTLY_CHART_CONFIG
    )


# ============================================================================
# 11. FONCTIONS PUBLIQUES - STRATEGY DIAGRAMS
# ============================================================================

def render_strategy_param_diagram(
    strategy_key: str,
    params: Dict[str, Any],
    key: str = "strategy_diagram",
) -> None:
    """
    Affiche un schema explicatif des indicateurs et parametres d'une strategie.

    Dispatcher pour les différentes stratégies.

    Args:
        strategy_key: Identifiant de la stratégie
        params: Paramètres de la stratégie
        key: Clé unique Streamlit
    """
    # Dictionnaire de mapping stratégie -> fonction de rendu
    strategy_renderers = {
        "bollinger_atr": _render_bollinger_atr_diagram,
        "bollinger_best_longe_3i": lambda p, k: create_bollinger_atr_diagram(p, k, variant="long_test"),
        "bollinger_best_short_3i": lambda p, k: create_bollinger_atr_diagram(p, k, variant="long_test"),
        "ema_cross": _render_ema_cross_diagram,
        "macd_cross": _render_macd_cross_diagram,
        "rsi_reversal": _render_rsi_reversal_diagram,
        "atr_channel": _render_atr_channel_diagram,
    }

    # Appeler le renderer approprié
    renderer = strategy_renderers.get(strategy_key)
    if renderer:
        renderer(params, key)
    else:
        st.info("Schema non disponible pour cette strategie.")


# ============================================================================
# 12. FONCTIONS PUBLIQUES - DISTRIBUTIONS
# ============================================================================

def render_trade_pnl_distribution(
    trades_df: pd.DataFrame,
    title: str = "📊 Distribution des P&L par Trade",
    key: str = "trade_pnl_dist",
    height: int = 400,
) -> None:
    """
    Affiche la distribution des P&L par trade avec histogramme + KDE (seaborn).

    Args:
        trades_df: DataFrame des trades avec colonne 'pnl'
        title: Titre du graphique
        key: Clé unique Streamlit
        height: Hauteur du graphique
    """
    _ = key
    if not SEABORN_AVAILABLE:
        st.warning("⚠️ Seaborn non disponible - Distribution non affichée")
        return

    if trades_df.empty or 'pnl' not in trades_df.columns:
        st.warning("⚠️ Aucune donnée de P&L à afficher")
        return

    st.markdown(f"#### {title}")
    st.caption("📊 Graphique généré avec **Seaborn** (histogramme + KDE)")

    # Configuration style seaborn
    sns.set_style("darkgrid")
    fig, ax = plt.subplots(figsize=(10, height / 100))

    # Histogramme + KDE avec seaborn
    pnl_values = trades_df['pnl'].dropna()
    sns.histplot(
        pnl_values,
        kde=True,
        color=COLOR_PALETTE["equity_line"],
        edgecolor=SEABORN_EDGE_COLOR,
        alpha=0.7,
        ax=ax,
        stat="density"
    )

    # Ligne verticale à zéro
    ax.axvline(0, color='white', linestyle='--', linewidth=1, alpha=0.5)

    # Statistiques
    mean_pnl = pnl_values.mean()
    median_pnl = pnl_values.median()
    ax.axvline(
        mean_pnl,
        color=COLOR_PALETTE["bb_mid"],
        linestyle='-',
        linewidth=2,
        label=f'Moyenne: ${mean_pnl:.2f}'
    )
    ax.axvline(
        median_pnl,
        color=COLOR_PALETTE["ema_fast"],
        linestyle='-',
        linewidth=2,
        label=f'Médiane: ${median_pnl:.2f}'
    )

    ax.set_xlabel('P&L ($)', color=SEABORN_TEXT_COLOR, fontsize=11)
    ax.set_ylabel('Densité', color=SEABORN_TEXT_COLOR, fontsize=11)
    ax.set_title(title, color=SEABORN_TEXT_COLOR, fontsize=13, pad=15)
    ax.legend(
        loc='upper right',
        facecolor=SEABORN_AXES_BG_COLOR,
        edgecolor=SEABORN_TEXT_COLOR,
        labelcolor=SEABORN_TEXT_COLOR
    )

    # Appliquer le style sombre
    _apply_seaborn_dark_style(fig, ax)

    st.pyplot(fig, width="stretch")
    plt.close(fig)


def render_returns_distribution(
    returns: pd.Series,
    title: str = "📈 Distribution des Rendements",
    key: str = "returns_dist",
    height: int = 400,
) -> None:
    """
    Affiche la distribution des rendements avec histogramme + KDE (seaborn).

    Args:
        returns: Série des rendements
        title: Titre du graphique
        key: Clé unique Streamlit
        height: Hauteur du graphique
    """
    _ = key
    if not SEABORN_AVAILABLE:
        st.warning("⚠️ Seaborn non disponible - Distribution non affichée")
        return

    if returns.empty:
        st.warning("⚠️ Aucune donnée de rendements à afficher")
        return

    st.markdown(f"#### {title}")
    st.caption("📊 Graphique généré avec **Seaborn** (histogramme + KDE)")

    # Configuration style seaborn
    sns.set_style("darkgrid")
    fig, ax = plt.subplots(figsize=(10, height / 100))

    # Histogramme + KDE
    returns_clean = returns.dropna()
    sns.histplot(
        returns_clean,
        kde=True,
        color=COLOR_PALETTE["ema_fast"],
        edgecolor=SEABORN_EDGE_COLOR,
        alpha=0.7,
        ax=ax,
        stat="density"
    )

    # Ligne verticale à zéro
    ax.axvline(0, color='white', linestyle='--', linewidth=1, alpha=0.5)

    # Statistiques
    mean_ret = returns_clean.mean()
    std_ret = returns_clean.std()
    ax.axvline(
        mean_ret,
        color=COLOR_PALETTE["equity_line"],
        linestyle='-',
        linewidth=2,
        label=f'Moyenne: {mean_ret:.4f}'
    )
    ax.axvline(
        mean_ret + std_ret,
        color=COLOR_PALETTE["drawdown_line"],
        linestyle=':',
        linewidth=1.5,
        label=f'+1σ: {mean_ret + std_ret:.4f}'
    )
    ax.axvline(
        mean_ret - std_ret,
        color=COLOR_PALETTE["drawdown_line"],
        linestyle=':',
        linewidth=1.5,
        label=f'-1σ: {mean_ret - std_ret:.4f}'
    )

    ax.set_xlabel('Rendement', color=SEABORN_TEXT_COLOR, fontsize=11)
    ax.set_ylabel('Densité', color=SEABORN_TEXT_COLOR, fontsize=11)
    ax.set_title(title, color=SEABORN_TEXT_COLOR, fontsize=13, pad=15)
    ax.legend(
        loc='upper right',
        facecolor=SEABORN_AXES_BG_COLOR,
        edgecolor=SEABORN_TEXT_COLOR,
        labelcolor=SEABORN_TEXT_COLOR
    )

    # Appliquer le style sombre
    _apply_seaborn_dark_style(fig, ax)

    st.pyplot(fig, width="stretch")
    plt.close(fig)


# ============================================================================
# 13. VISUALISATIONS MULTI-SWEEP
# ============================================================================

def render_multi_sweep_heatmap(
    results_df: pd.DataFrame,
    metric: str = "total_pnl",
    title: Optional[str] = None,
    key: Optional[str] = None,
) -> None:
    """
    Affiche une heatmap interactive des résultats multi-sweep.

    Args:
        results_df: DataFrame avec colonnes strategy, symbol, timeframe, metric
        metric: Métrique à afficher (default: total_pnl)
        title: Titre optionnel
        key: Clé Streamlit optionnelle
    """
    import plotly.graph_objects as go

    if results_df is None:
        st.warning("Aucun résultat à afficher")
        return

    if not isinstance(results_df, pd.DataFrame):
        results_df = pd.DataFrame(results_df)

    if results_df.empty:
        st.warning("Aucun résultat à afficher")
        return

    # Créer pivot table pour heatmap
    # Lignes = stratégies, Colonnes = symbol_timeframe
    results_df["token_tf"] = results_df["symbol"] + "_" + results_df["timeframe"]

    pivot = results_df.pivot_table(
        index="strategy",
        columns="token_tf",
        values=metric,
        aggfunc="mean"
    )

    # Colorscale centrée sur zéro pour PnL
    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=pivot.columns,
        y=pivot.index,
        colorscale="RdYlGn",  # Rouge négatif, vert positif
        zmid=0,  # Centrer sur zéro
        text=pivot.values.round(2),
        texttemplate='%{text}',
        textfont={"size": 10},
        colorbar=dict(title=metric)
    ))

    fig.update_layout(
        title=title or f"Heatmap {metric}",
        xaxis_title="Token × Timeframe",
        yaxis_title="Stratégie",
        height=400 + len(pivot.index) * 30,  # Hauteur adaptative
        template="plotly_dark"
    )

    st.plotly_chart(fig, width="stretch", key=key)


def render_multi_sweep_ranking(
    results_df: pd.DataFrame,
    metric: str = "total_pnl",
    top_n: int = 20,
    title: Optional[str] = None,
    key: Optional[str] = None,
) -> None:
    """
    Affiche un classement horizontal des meilleurs résultats.

    Args:
        results_df: DataFrame avec colonnes strategy, symbol, timeframe, metric
        metric: Métrique pour le classement (default: total_pnl)
        top_n: Nombre de résultats à afficher (default: 20)
        title: Titre optionnel
        key: Clé Streamlit optionnelle
    """
    import plotly.graph_objects as go

    if results_df is None:
        st.warning("Aucun résultat à afficher")
        return

    if not isinstance(results_df, pd.DataFrame):
        results_df = pd.DataFrame(results_df)

    if results_df.empty:
        st.warning("Aucun résultat à afficher")
        return

    # Filtrer les résultats valides (metric non-None et non-NaN)
    if metric in results_df.columns:
        valid_df = results_df[results_df[metric].notna()].copy()
        if valid_df.empty:
            st.warning(f"Aucun résultat valide pour la métrique '{metric}'")
            return
    else:
        st.error(f"Métrique '{metric}' non trouvée dans les résultats")
        return

    # Créer label combiné
    valid_df["label"] = (
        valid_df["strategy"] + " | " +
        valid_df["symbol"] + " " +
        valid_df["timeframe"]
    )

    # Trier (convertir en numérique si nécessaire)
    valid_df[metric] = pd.to_numeric(valid_df[metric], errors='coerce')

    # Re-filtrer après conversion (éliminer les NaN créés par coerce)
    valid_df = valid_df[valid_df[metric].notna()].copy()

    if valid_df.empty:
        st.warning(f"Aucune valeur numérique valide pour '{metric}'")
        return

    sorted_df = valid_df.nlargest(top_n, metric)

    # Couleur selon signe (vert positif, rouge négatif)
    colors = ["#00e676" if val > 0 else "#ff5252" for val in sorted_df[metric]]

    fig = go.Figure(data=go.Bar(
        x=sorted_df[metric],
        y=sorted_df["label"],
        orientation='h',
        marker=dict(color=colors),
        text=sorted_df[metric].round(2),
        textposition='auto',
    ))

    fig.update_layout(
        title=title or f"Top {top_n} - {metric}",
        xaxis_title=metric,
        yaxis_title="",
        height=400 + top_n * 20,  # Hauteur adaptative
        yaxis=dict(autorange="reversed"),  # Meilleur en haut
        template="plotly_dark"
    )

    st.plotly_chart(fig, width="stretch", key=key)


# ============================================================================
# 15. WALK-FORWARD ANALYSIS — Visualisation folds (10/02/2026)
# ============================================================================

def render_walk_forward_results(summary: Any, key: str = "wfa_chart") -> None:
    """Affiche les résultats WFA avec frise + vues comparatives.

    Compatible avec:
    - WalkForwardSummary (objet dataclass)
    - summary.to_dict() (dict sérialisé)
    """
    if summary is None:
        st.warning("Aucun résultat Walk-Forward à afficher.")
        return

    # Normaliser payload objet -> dict
    if isinstance(summary, dict):
        payload = summary
    elif hasattr(summary, "to_dict"):
        payload = summary.to_dict()
    else:
        st.warning("Format WFA non supporté.")
        return

    folds_raw = payload.get("folds") if isinstance(payload, dict) else None
    if not isinstance(folds_raw, list) or not folds_raw:
        st.warning("Aucun fold WFA à afficher.")
        return

    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            out = float(value)
            if not np.isfinite(out):
                return default
            return out
        except (TypeError, ValueError):
            return default

    def _normalize_fold(fold: Any) -> Dict[str, Any]:
        if isinstance(fold, dict):
            data = dict(fold)
        elif hasattr(fold, "to_dict"):
            data = dict(fold.to_dict())
        else:
            data = {}

        train_range = data.get("train_range")
        test_range = data.get("test_range")

        if not (isinstance(train_range, (list, tuple)) and len(train_range) == 2):
            t0 = data.get("train_start")
            t1 = data.get("train_end")
            train_range = [t0, t1]
        if not (isinstance(test_range, (list, tuple)) and len(test_range) == 2):
            t0 = data.get("test_start")
            t1 = data.get("test_end")
            test_range = [t0, t1]

        train_start = int(_safe_float(train_range[0], 0))
        train_end = int(_safe_float(train_range[1], train_start))
        test_start = int(_safe_float(test_range[0], 0))
        test_end = int(_safe_float(test_range[1], test_start))

        train_sharpe = _safe_float(
            data.get("train_sharpe"),
            _safe_float((data.get("train_metrics") or {}).get("sharpe_ratio"), 0.0),
        )
        test_sharpe = _safe_float(
            data.get("test_sharpe"),
            _safe_float((data.get("test_metrics") or {}).get("sharpe_ratio"), 0.0),
        )
        overfit_ratio = _safe_float(data.get("overfitting_ratio"), np.nan)
        exec_ms = _safe_float(data.get("execution_time_ms"), 0.0)

        return {
            "fold_id": int(_safe_float(data.get("fold_id"), 0)),
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
            "train_bars": max(0, train_end - train_start),
            "test_bars": max(0, test_end - test_start),
            "train_sharpe": train_sharpe,
            "test_sharpe": test_sharpe,
            "overfitting_ratio": overfit_ratio,
            "execution_time_ms": exec_ms,
        }

    folds = [_normalize_fold(f) for f in folds_raw]
    folds = sorted(folds, key=lambda x: x["fold_id"])

    # ── Verdict + Config ────────────────────────────────────────────────
    is_robust = bool(payload.get("is_robust", False))
    confidence = _safe_float(payload.get("confidence_score"), 0.0)
    if is_robust:
        st.success(f"✅ **Stratégie robuste** — Confiance : {confidence:.0%}")
    else:
        st.warning(f"⚠️ **Overfitting probable** — Confiance : {confidence:.0%}")

    cfg = payload.get("config", {}) if isinstance(payload, dict) else {}
    mode_label = "expanding" if bool(cfg.get("expanding", False)) else "rolling"
    st.caption(
        f"Configuration WFA: {int(_safe_float(cfg.get('n_folds'), len(folds)))} folds | "
        f"train_ratio={_safe_float(cfg.get('train_ratio'), 0.7):.0%} | mode={mode_label}"
    )

    # ── Métriques globales ──────────────────────────────────────────────
    avg_train = _safe_float(payload.get("avg_train_sharpe"), 0.0)
    avg_test = _safe_float(payload.get("avg_test_sharpe"), 0.0)
    degradation = _safe_float(payload.get("degradation_pct"), 0.0)
    stability = _safe_float(payload.get("test_stability_std"), 0.0)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sharpe Train (moy.)", f"{avg_train:.2f}")
    c2.metric(
        "Sharpe Test (moy.)",
        f"{avg_test:.2f}",
        delta=f"{avg_test - avg_train:+.2f}",
        delta_color="normal",
    )
    c3.metric(
        "Dégradation",
        f"{degradation:.0f}%",
        delta=f"{-degradation:.0f}%",
        delta_color="inverse",
    )
    c4.metric("Stabilité Test (σ)", f"{stability:.3f}")

    # ── Frise (timeline folds train/test) ───────────────────────────────
    fold_labels = [f"Fold {f['fold_id']}" for f in folds]
    train_starts = [f["train_start"] for f in folds]
    train_lengths = [f["train_bars"] for f in folds]
    test_starts = [f["test_start"] for f in folds]
    test_lengths = [f["test_bars"] for f in folds]

    fig_timeline = go.Figure()
    fig_timeline.add_trace(
        go.Bar(
            name="Train",
            y=fold_labels,
            x=train_lengths,
            base=train_starts,
            orientation="h",
            marker_color="#3b82f6",
            opacity=0.9,
            hovertemplate=(
                "Fold: %{y}<br>"
                "Train start: %{base}<br>"
                "Train bars: %{x}<extra></extra>"
            ),
        )
    )
    fig_timeline.add_trace(
        go.Bar(
            name="Test (OOS)",
            y=fold_labels,
            x=test_lengths,
            base=test_starts,
            orientation="h",
            marker_color="#ef4444",
            opacity=0.9,
            hovertemplate=(
                "Fold: %{y}<br>"
                "Test start: %{base}<br>"
                "Test bars: %{x}<extra></extra>"
            ),
        )
    )
    fig_timeline.update_layout(
        title="Frise Walk-Forward — fenêtres Train/Test par fold (indices barres)",
        barmode="overlay",
        xaxis_title="Index barre",
        yaxis_title="Fold",
        template="plotly_dark",
        height=max(320, 140 + 45 * len(folds)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig_timeline, use_container_width=True, key=f"{key}_timeline")

    # ── Sharpe train vs test par fold ───────────────────────────────────
    train_sharpes = [f["train_sharpe"] for f in folds]
    test_sharpes = [f["test_sharpe"] for f in folds]

    fig_sharpe = go.Figure()
    fig_sharpe.add_trace(
        go.Bar(
            name="Train",
            x=fold_labels,
            y=train_sharpes,
            marker_color="#636EFA",
            text=[f"{v:.2f}" for v in train_sharpes],
            textposition="auto",
        )
    )
    fig_sharpe.add_trace(
        go.Bar(
            name="Test (OOS)",
            x=fold_labels,
            y=test_sharpes,
            marker_color="#EF553B",
            text=[f"{v:.2f}" for v in test_sharpes],
            textposition="auto",
        )
    )
    fig_sharpe.update_layout(
        title="Sharpe Ratio — Train vs Test par fold",
        barmode="group",
        yaxis_title="Sharpe Ratio",
        template="plotly_dark",
        height=360,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig_sharpe, use_container_width=True, key=f"{key}_bars")

    # ── Ratio overfitting par fold ──────────────────────────────────────
    overfit_ratios = [f["overfitting_ratio"] for f in folds]
    fig_ratio = go.Figure()
    fig_ratio.add_trace(
        go.Scatter(
            x=fold_labels,
            y=overfit_ratios,
            mode="lines+markers",
            name="Overfitting ratio",
            line=dict(color="#f59e0b", width=2),
            marker=dict(size=8),
        )
    )
    fig_ratio.add_hline(y=1.0, line_dash="dot", line_color="#22c55e")
    fig_ratio.add_hline(y=2.0, line_dash="dash", line_color="#ef4444")
    fig_ratio.update_layout(
        title="Overfitting Ratio par fold (train_sharpe / test_sharpe)",
        yaxis_title="Ratio",
        template="plotly_dark",
        height=320,
    )
    st.plotly_chart(fig_ratio, use_container_width=True, key=f"{key}_ratio")

    # ── Tableau détaillé ────────────────────────────────────────────────
    rows = []
    for f in folds:
        rows.append(
            {
                "Fold": f["fold_id"],
                "Train [start:end]": f"{f['train_start']}:{f['train_end']}",
                "Test [start:end]": f"{f['test_start']}:{f['test_end']}",
                "Train bars": f["train_bars"],
                "Test bars": f["test_bars"],
                "Sharpe Train": round(f["train_sharpe"], 3),
                "Sharpe Test": round(f["test_sharpe"], 3),
                "Overfitting Ratio": (
                    round(f["overfitting_ratio"], 3)
                    if np.isfinite(f["overfitting_ratio"])
                    else np.nan
                ),
                "Temps (ms)": round(f["execution_time_ms"], 0),
            }
        )

    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    with st.expander("📋 Détails techniques WFA"):
        st.json(payload)


# ============================================================================
# 16. API PUBLIQUE
# ============================================================================

__all__ = [
    "render_equity_and_drawdown",
    "render_ohlcv_with_trades",
    "render_ohlcv_with_trades_and_indicators",
    "render_ohlcv_with_indicators",
    "render_equity_curve",
    "render_comparison_chart",
    "render_strategy_param_diagram",
    "render_trade_pnl_distribution",
    "render_returns_distribution",
    "render_multi_sweep_heatmap",
    "render_multi_sweep_ranking",
    "render_walk_forward_results",
]
