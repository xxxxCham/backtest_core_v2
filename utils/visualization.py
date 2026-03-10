"""
Module-ID: utils.visualization

Purpose: Visualisation interactive - candlesticks, trades, equity curve, dashboard.

Role in pipeline: UI / reporting

Key components: plot_trades, visualize_results, TradePlotter, Plotly-based

Inputs: DataFrame OHLCV, trades (signaux, entries/exits), metrics

Outputs: Graphiques Plotly interactifs, HTML reports

Dependencies: plotly, pandas, numpy, json

Conventions: Candlesticks OHLCV; marqueurs triangles trades (entrée/sortie); equity curve + drawdown; tooltips.

Read-if: Modification graphiques, markers, layout.

Skip-if: Vous n'avez pas besoin visualiser résultats.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    go = None

logger = logging.getLogger(__name__)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class TradeMarker:
    """Marqueur de trade pour visualisation."""
    timestamp: pd.Timestamp
    price: float
    side: str  # "LONG" ou "SHORT"
    action: str  # "entry" ou "exit"
    pnl: Optional[float] = None
    trade_id: int = 0
    exit_reason: Optional[str] = None
    size: Optional[float] = None


@dataclass
class BacktestVisualData:
    """Données complètes pour visualisation d'un backtest."""
    ohlcv: pd.DataFrame
    trades: List[Dict[str, Any]]
    equity_curve: Optional[List[float]] = None
    signals: Optional[pd.Series] = None
    params: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    strategy_name: str = ""
    symbol: str = ""
    timeframe: str = ""


# ============================================================================
# CORE PLOTTING FUNCTIONS
# ============================================================================

def plot_trades(
    df: pd.DataFrame,
    trades: List[Dict[str, Any]],
    title: str = "Backtest - Trades",
    show_volume: bool = True,
    height: int = 800,
    max_candles: int = 2000,
) -> "go.Figure":
    """
    Crée un graphique candlestick avec les marqueurs de trades.

    Args:
        df: DataFrame OHLCV avec colonnes open, high, low, close, volume
        trades: Liste de trades (dicts avec entry_ts, exit_ts, pnl, side, etc.)
        title: Titre du graphique
        show_volume: Afficher le volume en sous-graphique
        height: Hauteur du graphique en pixels
        max_candles: Nombre maximum de bougies à afficher

    Returns:
        Figure Plotly interactive
    """
    if not PLOTLY_AVAILABLE:
        raise ImportError("Plotly requis: pip install plotly")

    # Limiter le nombre de bougies pour performance
    if len(df) > max_candles:
        df = df.iloc[-max_candles:]

    # Préparer les données
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        if 'timestamp' in df.columns:
            df.set_index('timestamp', inplace=True)
        elif 'date' in df.columns:
            df.set_index('date', inplace=True)

    # Créer la figure avec subplots
    rows = 2 if show_volume else 1
    row_heights = [0.75, 0.25] if show_volume else [1.0]

    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=row_heights,
        subplot_titles=("", "Volume") if show_volume else None,
    )

    # === Candlestick ===
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name='OHLC',
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350',
            increasing_fillcolor='#26a69a',
            decreasing_fillcolor='#ef5350',
        ),
        row=1, col=1,
    )

    # === Volume ===
    if show_volume and 'volume' in df.columns:
        colors = ['#26a69a' if c >= o else '#ef5350'
                  for o, c in zip(df['open'], df['close'])]

        fig.add_trace(
            go.Bar(
                x=df.index,
                y=df['volume'],
                name='Volume',
                marker_color=colors,
                opacity=0.7,
            ),
            row=2, col=1,
        )

    # === Marqueurs de trades ===
    if trades:
        entries_long = []
        entries_short = []
        exits_win = []
        exits_loss = []

        for i, trade in enumerate(trades):
            # Conversion des timestamps avec validation
            try:
                entry_ts_raw = trade.get('entry_ts')
                exit_ts_raw = trade.get('exit_ts')

                if entry_ts_raw is None or exit_ts_raw is None:
                    logger.warning(f"Trade #{i} missing timestamps, skip")
                    continue

                entry_ts = pd.Timestamp(entry_ts_raw)
                exit_ts = pd.Timestamp(exit_ts_raw)
            except (ValueError, TypeError, KeyError) as e:
                logger.warning(f"Trade #{i} timestamp conversion error: {e}")
                continue

            # Vérifier si le trade est dans la plage affichée
            if entry_ts < df.index[0] and exit_ts < df.index[0]:
                continue

            side = trade.get('side', 'LONG')
            pnl = trade.get('pnl', 0)
            entry_price = trade.get('price_entry', trade.get('entry_price', 0))
            exit_price = trade.get('price_exit', trade.get('exit_price', 0))
            exit_reason = trade.get('exit_reason', 'unknown')
            size = trade.get('size', 0)

            # Entrée
            entry_marker = {
                'ts': entry_ts,
                'price': entry_price,
                'text': f"<b>ENTRÉE {side}</b><br>"
                        f"Trade #{i+1}<br>"
                        f"Prix: {entry_price:,.2f}<br>"
                        f"Taille: {size:,.4f}",
                'trade_id': i + 1,
            }

            if side == 'LONG':
                entries_long.append(entry_marker)
            else:
                entries_short.append(entry_marker)

            # Sortie
            exit_marker = {
                'ts': exit_ts,
                'price': exit_price,
                'text': f"<b>SORTIE {side}</b><br>"
                        f"Trade #{i+1}<br>"
                        f"Prix: {exit_price:,.2f}<br>"
                        f"PnL: <b style='color:{'#26a69a' if pnl >= 0 else '#ef5350'}'>"
                        f"{pnl:+,.2f}</b><br>"
                        f"Raison: {exit_reason}",
                'trade_id': i + 1,
                'pnl': pnl,
            }

            if pnl >= 0:
                exits_win.append(exit_marker)
            else:
                exits_loss.append(exit_marker)

        # Ajouter les marqueurs d'entrée LONG (triangle vert vers le haut)
        if entries_long:
            fig.add_trace(
                go.Scatter(
                    x=[m['ts'] for m in entries_long],
                    y=[m['price'] for m in entries_long],
                    mode='markers',
                    name='Entrée LONG',
                    marker=dict(
                        symbol='triangle-up',
                        size=14,
                        color='#00e676',
                        line=dict(color='white', width=1),
                    ),
                    text=[m['text'] for m in entries_long],
                    hoverinfo='text',
                    hovertemplate='%{text}<extra></extra>',
                ),
                row=1, col=1,
            )

        # Entrées SHORT (triangle rouge vers le bas)
        if entries_short:
            fig.add_trace(
                go.Scatter(
                    x=[m['ts'] for m in entries_short],
                    y=[m['price'] for m in entries_short],
                    mode='markers',
                    name='Entrée SHORT',
                    marker=dict(
                        symbol='triangle-down',
                        size=14,
                        color='#ff5252',
                        line=dict(color='white', width=1),
                    ),
                    text=[m['text'] for m in entries_short],
                    hoverinfo='text',
                    hovertemplate='%{text}<extra></extra>',
                ),
                row=1, col=1,
            )

        # Sorties gagnantes (cercle vert)
        if exits_win:
            fig.add_trace(
                go.Scatter(
                    x=[m['ts'] for m in exits_win],
                    y=[m['price'] for m in exits_win],
                    mode='markers',
                    name='Sortie Win',
                    marker=dict(
                        symbol='circle',
                        size=12,
                        color='#00e676',
                        line=dict(color='white', width=2),
                    ),
                    text=[m['text'] for m in exits_win],
                    hoverinfo='text',
                    hovertemplate='%{text}<extra></extra>',
                ),
                row=1, col=1,
            )

        # Sorties perdantes (cercle rouge)
        if exits_loss:
            fig.add_trace(
                go.Scatter(
                    x=[m['ts'] for m in exits_loss],
                    y=[m['price'] for m in exits_loss],
                    mode='markers',
                    name='Sortie Loss',
                    marker=dict(
                        symbol='circle',
                        size=12,
                        color='#ff5252',
                        line=dict(color='white', width=2),
                    ),
                    text=[m['text'] for m in exits_loss],
                    hoverinfo='text',
                    hovertemplate='%{text}<extra></extra>',
                ),
                row=1, col=1,
            )

        # Lignes connectant entrée et sortie
        for i, trade in enumerate(trades):
            entry_ts = pd.Timestamp(trade.get('entry_ts'))
            exit_ts = pd.Timestamp(trade.get('exit_ts'))

            if entry_ts < df.index[0] and exit_ts < df.index[0]:
                continue

            entry_price = trade.get('price_entry', trade.get('entry_price', 0))
            exit_price = trade.get('price_exit', trade.get('exit_price', 0))
            pnl = trade.get('pnl', 0)

            line_color = 'rgba(0, 230, 118, 0.4)' if pnl >= 0 else 'rgba(255, 82, 82, 0.4)'

            fig.add_trace(
                go.Scatter(
                    x=[entry_ts, exit_ts],
                    y=[entry_price, exit_price],
                    mode='lines',
                    line=dict(color=line_color, width=1, dash='dot'),
                    showlegend=False,
                    hoverinfo='skip',
                ),
                row=1, col=1,
            )

    # === Layout ===
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=18),
        ),
        template='plotly_dark',
        height=height,
        xaxis_rangeslider_visible=False,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor='rgba(0,0,0,0.5)',
        ),
        hovermode='x unified',
    )

    # Formater les axes
    fig.update_xaxes(
        showgrid=True,
        gridwidth=1,
        gridcolor='rgba(128,128,128,0.2)',
    )
    fig.update_yaxes(
        showgrid=True,
        gridwidth=1,
        gridcolor='rgba(128,128,128,0.2)',
    )

    return fig


def plot_equity_curve(
    equity_curve: List[float],
    trades: Optional[List[Dict[str, Any]]] = None,
    initial_capital: float = 10000,
    title: str = "Equity Curve",
    height: int = 400,
) -> "go.Figure":
    """
    Crée un graphique de la courbe d'equity.

    Args:
        equity_curve: Liste des valeurs d'equity
        trades: Trades pour marquer les positions
        initial_capital: Capital initial
        title: Titre du graphique
        height: Hauteur en pixels

    Returns:
        Figure Plotly
    """
    if not PLOTLY_AVAILABLE:
        raise ImportError("Plotly requis: pip install plotly")

    fig = go.Figure()

    x = list(range(len(equity_curve)))

    # Courbe d'equity
    fig.add_trace(
        go.Scatter(
            x=x,
            y=equity_curve,
            mode='lines',
            name='Equity',
            line=dict(color='#00e676', width=2),
            fill='tozeroy',
            fillcolor='rgba(0, 230, 118, 0.1)',
        )
    )

    # Ligne de capital initial
    fig.add_hline(
        y=initial_capital,
        line_dash="dash",
        line_color="rgba(255,255,255,0.5)",
        annotation_text=f"Capital initial: {initial_capital:,.0f}",
    )

    # High water mark
    hwm = pd.Series(equity_curve).cummax()
    fig.add_trace(
        go.Scatter(
            x=x,
            y=hwm,
            mode='lines',
            name='High Water Mark',
            line=dict(color='rgba(255,255,255,0.3)', width=1, dash='dot'),
        )
    )

    # PnL final
    final_equity = equity_curve[-1] if equity_curve else initial_capital
    pnl = final_equity - initial_capital
    pnl_pct = (pnl / initial_capital) * 100

    fig.add_annotation(
        x=len(equity_curve) - 1,
        y=final_equity,
        text=f"PnL: {pnl:+,.2f} ({pnl_pct:+.1f}%)",
        showarrow=True,
        arrowhead=2,
        font=dict(
            color='#00e676' if pnl >= 0 else '#ff5252',
            size=14,
        ),
        bgcolor='rgba(0,0,0,0.7)',
        borderpad=4,
    )

    fig.update_layout(
        title=title,
        template='plotly_dark',
        height=height,
        xaxis_title='Barres',
        yaxis_title='Equity',
        showlegend=True,
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="right",
            x=0.99,
        ),
    )

    return fig


def plot_drawdown(
    equity_curve: List[float],
    title: str = "Drawdown",
    height: int = 250,
) -> "go.Figure":
    """
    Crée un graphique de drawdown.

    Args:
        equity_curve: Liste des valeurs d'equity
        title: Titre
        height: Hauteur en pixels

    Returns:
        Figure Plotly
    """
    if not PLOTLY_AVAILABLE:
        raise ImportError("Plotly requis: pip install plotly")

    equity = pd.Series(equity_curve)
    hwm = equity.cummax()
    drawdown = (equity - hwm) / hwm * 100  # En pourcentage

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=list(range(len(drawdown))),
            y=drawdown,
            mode='lines',
            name='Drawdown',
            line=dict(color='#ff5252', width=1),
            fill='tozeroy',
            fillcolor='rgba(255, 82, 82, 0.3)',
        )
    )

    # Max drawdown
    max_dd = drawdown.min()
    max_dd_idx = drawdown.idxmin()

    fig.add_annotation(
        x=max_dd_idx,
        y=max_dd,
        text=f"Max DD: {max_dd:.1f}%",
        showarrow=True,
        arrowhead=2,
        font=dict(color='#ff5252', size=12),
    )

    fig.update_layout(
        title=title,
        template='plotly_dark',
        height=height,
        xaxis_title='Barres',
        yaxis_title='Drawdown %',
        showlegend=False,
    )

    return fig


def create_performance_cards(metrics: Dict[str, Any]) -> str:
    """
    Crée des cartes HTML pour les métriques de performance.

    Args:
        metrics: Dict des métriques

    Returns:
        HTML string
    """
    pnl = metrics.get('pnl', metrics.get('total_pnl', 0))
    total_return_pct = metrics.get('total_return_pct')
    sharpe = metrics.get('sharpe_ratio', 0)
    sortino = metrics.get('sortino_ratio', 0)
    max_dd = metrics.get('max_drawdown', 0)
    win_rate = metrics.get('win_rate', 0)
    num_trades = metrics.get('total_trades', metrics.get('num_trades', 0))
    profit_factor = metrics.get('profit_factor', 0)

    # calculate_metrics returns percentages; agent outputs use fractions.
    if total_return_pct is None:
        total_return_pct = metrics.get('total_return', 0) * 100
        max_dd *= 100
        win_rate *= 100

    pnl_color = '#00e676' if pnl >= 0 else '#ff5252'

    html = f"""
    <div style="display: flex; flex-wrap: wrap; gap: 15px; margin: 20px 0;">
        <div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    padding: 20px; border-radius: 12px; min-width: 150px;
                    border: 1px solid {pnl_color};">
            <div style="color: #888; font-size: 12px;">PnL</div>
            <div style="color: {pnl_color}; font-size: 28px; font-weight: bold;">
                {pnl:+,.2f}
            </div>
            <div style="color: {pnl_color}; font-size: 14px;">
                {total_return_pct:+.2f}%
            </div>
        </div>

        <div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    padding: 20px; border-radius: 12px; min-width: 150px;
                    border: 1px solid #3498db;">
            <div style="color: #888; font-size: 12px;">Sharpe Ratio</div>
            <div style="color: #3498db; font-size: 28px; font-weight: bold;">
                {sharpe:.2f}
            </div>
            <div style="color: #888; font-size: 14px;">
                Sortino: {sortino:.2f}
            </div>
        </div>

        <div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    padding: 20px; border-radius: 12px; min-width: 150px;
                    border: 1px solid #ff5252;">
            <div style="color: #888; font-size: 12px;">Max Drawdown</div>
            <div style="color: #ff5252; font-size: 28px; font-weight: bold;">
                {max_dd:.1f}%
            </div>
        </div>

        <div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    padding: 20px; border-radius: 12px; min-width: 150px;
                    border: 1px solid #9b59b6;">
            <div style="color: #888; font-size: 12px;">Win Rate</div>
            <div style="color: #9b59b6; font-size: 28px; font-weight: bold;">
                {win_rate:.1f}%
            </div>
            <div style="color: #888; font-size: 14px;">
                {num_trades} trades
            </div>
        </div>

        <div style="background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    padding: 20px; border-radius: 12px; min-width: 150px;
                    border: 1px solid #f39c12;">
            <div style="color: #888; font-size: 12px;">Profit Factor</div>
            <div style="color: #f39c12; font-size: 28px; font-weight: bold;">
                {profit_factor:.2f}
            </div>
        </div>
    </div>
    """

    return html


def create_trades_table(trades: List[Dict[str, Any]], max_rows: int = 50) -> str:
    """
    Crée une table HTML des trades.

    Args:
        trades: Liste des trades
        max_rows: Nombre maximum de lignes

    Returns:
        HTML string
    """
    html = """
    <style>
        .trades-table {
            width: 100%;
            border-collapse: collapse;
            font-family: 'Consolas', monospace;
            font-size: 13px;
            background: #1a1a2e;
        }
        .trades-table th {
            background: #16213e;
            color: #fff;
            padding: 12px 8px;
            text-align: left;
            border-bottom: 2px solid #3498db;
            position: sticky;
            top: 0;
        }
        .trades-table td {
            padding: 10px 8px;
            border-bottom: 1px solid #2a2a4e;
        }
        .trades-table tr:hover {
            background: #2a2a4e;
        }
        .pnl-positive { color: #00e676; font-weight: bold; }
        .pnl-negative { color: #ff5252; font-weight: bold; }
        .side-long { color: #00e676; }
        .side-short { color: #ff5252; }
    </style>
    <div style="max-height: 400px; overflow-y: auto; border-radius: 8px;">
    <table class="trades-table">
        <thead>
            <tr>
                <th>#</th>
                <th>Side</th>
                <th>Entrée</th>
                <th>Sortie</th>
                <th>Prix Entrée</th>
                <th>Prix Sortie</th>
                <th>PnL</th>
                <th>Return %</th>
                <th>Raison</th>
            </tr>
        </thead>
        <tbody>
    """

    for i, trade in enumerate(trades[:max_rows]):
        side = trade.get('side', 'LONG')
        entry_ts = pd.Timestamp(trade.get('entry_ts')).strftime('%Y-%m-%d %H:%M')
        exit_ts = pd.Timestamp(trade.get('exit_ts')).strftime('%Y-%m-%d %H:%M')
        entry_price = trade.get('price_entry', trade.get('entry_price', 0))
        exit_price = trade.get('price_exit', trade.get('exit_price', 0))
        pnl = trade.get('pnl', 0)
        return_pct = trade.get('return_pct', 0)
        exit_reason = trade.get('exit_reason', '-')

        pnl_class = 'pnl-positive' if pnl >= 0 else 'pnl-negative'
        side_class = 'side-long' if side == 'LONG' else 'side-short'

        html += f"""
            <tr>
                <td>{i + 1}</td>
                <td class="{side_class}">{side}</td>
                <td>{entry_ts}</td>
                <td>{exit_ts}</td>
                <td>{entry_price:,.2f}</td>
                <td>{exit_price:,.2f}</td>
                <td class="{pnl_class}">{pnl:+,.2f}</td>
                <td class="{pnl_class}">{return_pct*100:+.2f}%</td>
                <td>{exit_reason}</td>
            </tr>
        """

    if len(trades) > max_rows:
        html += f"""
            <tr>
                <td colspan="9" style="text-align: center; color: #888;">
                    ... et {len(trades) - max_rows} trades de plus
                </td>
            </tr>
        """

    html += "</tbody></table></div>"
    return html


# ============================================================================
# HIGH-LEVEL VISUALIZATION
# ============================================================================

def visualize_backtest(
    df: pd.DataFrame,
    trades: List[Dict[str, Any]],
    metrics: Dict[str, Any],
    equity_curve: Optional[List[float]] = None,
    title: str = "Backtest Results",
    output_path: Optional[Union[str, Path]] = None,
    show: bool = True,
) -> Dict[str, Any]:
    """
    Crée une visualisation complète d'un backtest.

    Args:
        df: DataFrame OHLCV
        trades: Liste des trades
        metrics: Métriques de performance
        equity_curve: Courbe d'equity optionnelle
        title: Titre du rapport
        output_path: Chemin de sortie HTML (optionnel)
        show: Ouvrir dans le navigateur

    Returns:
        Dict avec les figures générées
    """
    if not PLOTLY_AVAILABLE:
        raise ImportError("Plotly requis: pip install plotly")

    figures = {}

    # Graphique principal avec trades
    fig_trades = plot_trades(df, trades, title=f"{title} - Trades")
    figures['trades'] = fig_trades

    # Equity curve si disponible
    if equity_curve:
        fig_equity = plot_equity_curve(
            equity_curve,
            trades=trades,
            initial_capital=metrics.get('initial_capital', 10000),
            title=f"{title} - Equity Curve",
        )
        figures['equity'] = fig_equity

        fig_dd = plot_drawdown(equity_curve, title=f"{title} - Drawdown")
        figures['drawdown'] = fig_dd

    # Générer HTML si output_path
    if output_path:
        output_path = Path(output_path)

        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <meta charset="utf-8">
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        body {{
            font-family: 'Segoe UI', Arial, sans-serif;
            background: #0a0a1a;
            color: #fff;
            margin: 0;
            padding: 20px;
        }}
        h1 {{
            color: #fff;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #888;
            margin-top: 30px;
        }}
        .chart-container {{
            background: #1a1a2e;
            border-radius: 12px;
            padding: 15px;
            margin: 20px 0;
        }}
        .timestamp {{
            color: #666;
            font-size: 12px;
            text-align: right;
        }}
    </style>
</head>
<body>
    <h1>🏆 {title}</h1>
    <p class="timestamp">Généré le {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

    <h2>📊 Performance</h2>
    {create_performance_cards(metrics)}

    <h2>📈 Graphique des Trades</h2>
    <div class="chart-container" id="chart-trades"></div>

"""

        if equity_curve:
            html_content += """
    <h2>💰 Equity Curve</h2>
    <div class="chart-container" id="chart-equity"></div>

    <h2>📉 Drawdown</h2>
    <div class="chart-container" id="chart-drawdown"></div>
"""

        html_content += f"""
    <h2>📋 Détail des Trades ({len(trades)} trades)</h2>
    {create_trades_table(trades)}

    <script>
        Plotly.newPlot('chart-trades', {fig_trades.to_json()}.data, {fig_trades.to_json()}.layout);
"""

        if equity_curve:
            html_content += f"""
        Plotly.newPlot('chart-equity', {fig_equity.to_json()}.data, {fig_equity.to_json()}.layout);
        Plotly.newPlot('chart-drawdown', {fig_dd.to_json()}.data, {fig_dd.to_json()}.layout);
"""

        html_content += """
    </script>
</body>
</html>
"""

        output_path.write_text(html_content, encoding='utf-8')
        print(f"✅ Rapport sauvegardé: {output_path}")

    # Afficher
    if show:
        fig_trades.show()

    return figures


def load_and_visualize(
    results_path: Union[str, Path],
    data_path: Optional[Union[str, Path]] = None,
    output_path: Optional[Union[str, Path]] = None,
    show: bool = True,
) -> Dict[str, Any]:
    """
    Charge un fichier de résultats et génère la visualisation.

    Args:
        results_path: Chemin vers le fichier JSON de résultats
        data_path: Chemin vers les données OHLCV (optionnel)
        output_path: Chemin de sortie HTML
        show: Ouvrir dans le navigateur

    Returns:
        Dict avec les résultats et figures
    """
    results_path = Path(results_path)

    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Extraire les informations
    trades = data.get('trades', [])
    metrics = data.get('metrics', {})
    equity_curve = data.get('equity_curve')
    params = data.get('params', {})
    strategy = data.get('strategy', 'Unknown')

    # Charger les données OHLCV si fournies
    df = None
    if data_path:
        data_path = Path(data_path)
        if data_path.suffix == '.parquet':
            df = pd.read_parquet(data_path)
        elif data_path.suffix == '.csv':
            df = pd.read_csv(data_path)

        # Normaliser les colonnes
        df.columns = df.columns.str.lower()
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)

    # Si pas de données OHLCV et pas de trades, erreur
    if df is None and not trades:
        raise ValueError("Aucune donnée OHLCV ou trade à visualiser")

    # Créer un DataFrame minimal si nécessaire
    if df is None and trades:
        print("⚠️ Pas de données OHLCV fournies, graphique limité")
        # Créer un df minimal depuis les trades
        all_prices = []
        all_times = []
        for t in trades:
            all_times.append(pd.Timestamp(t.get('entry_ts')))
            all_times.append(pd.Timestamp(t.get('exit_ts')))
            all_prices.append(t.get('price_entry', t.get('entry_price', 0)))
            all_prices.append(t.get('price_exit', t.get('exit_price', 0)))

        df = pd.DataFrame({
            'open': all_prices,
            'high': all_prices,
            'low': all_prices,
            'close': all_prices,
        }, index=all_times).sort_index()

    # Générer titre
    title = f"Backtest - {strategy}"
    if params:
        params_str = ", ".join(f"{k}={v}" for k, v in list(params.items())[:3])
        title += f" ({params_str})"

    return visualize_backtest(
        df=df,
        trades=trades,
        metrics=metrics,
        equity_curve=equity_curve,
        title=title,
        output_path=output_path,
        show=show,
    )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'plot_trades',
    'plot_equity_curve',
    'plot_drawdown',
    'create_performance_cards',
    'create_trades_table',
    'visualize_backtest',
    'load_and_visualize',
    'BacktestVisualData',
    'TradeMarker',
    'PLOTLY_AVAILABLE',
]
