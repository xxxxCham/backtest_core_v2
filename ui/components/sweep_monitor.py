"""
Module-ID: ui.components.sweep_monitor

Purpose: Monitor live pour sweeps/optimisation - progress, ETA, top results, ranking.

Role in pipeline: visualization/monitoring

Key components: SweepMonitor, render_sweep_progress(), render_sweep_summary(), SweepStats

Inputs: Sweep updates {completed, total, current_result}

Outputs: Progress bar, ETA estimate, top-N table, live chart updates

Dependencies: streamlit (optionnel), plotly (optionnel), numpy, dataclasses

Conventions: ETA based on rolling avg; refresh 100ms; top-5 constant display.

Read-if: Modification ETA algo ou layout progress.

Skip-if: Vous appelez render_sweep_progress(monitor).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

try:
    import streamlit as st
    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False

try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

import numpy as np
import pandas as pd


def _pnl_per_day(total_pnl: float, period_days: Optional[float]) -> Optional[float]:
    if not period_days:
        return None
    try:
        return float(total_pnl) / float(period_days)
    except Exception:
        return None


@dataclass
class SweepResult:
    """
    Stores the parameters, metrics and timing of a single sweep evaluation.

    Used by `SweepMonitor` to surface the latest runs and compute leaderboards
    without coupling to the backtest engine.
    """
    params: Dict[str, Any]
    metrics: Dict[str, float]
    timestamp: datetime = field(default_factory=lambda: datetime.now())
    duration_ms: float = 0.0

    @property
    def sharpe(self) -> float:
        """Raccourci pour Sharpe Ratio."""
        return self.metrics.get('sharpe_ratio', 0.0)

    @property
    def total_return(self) -> float:
        """Raccourci pour rendement total."""
        return self.metrics.get('total_return', 0.0)


@dataclass
class SweepStats:
    """
    Running statistics for an in-progress sweep.

    Tracks counts, elapsed time and provides ETA/rate helpers so renderers can
    present useful progress indicators.
    """
    total_combinations: int = 0
    evaluated: int = 0
    pruned: int = 0
    errors: int = 0
    start_time: Optional[datetime] = None

    @property
    def progress_percent(self) -> float:
        """Pourcentage de progression."""
        if self.total_combinations == 0:
            return 0.0
        return (self.evaluated / self.total_combinations) * 100

    @property
    def elapsed(self) -> timedelta:
        """Temps écoulé."""
        if not self.start_time:
            return timedelta(0)
        return datetime.now() - self.start_time

    @property
    def elapsed_seconds(self) -> float:
        """Temps écoulé en secondes."""
        return self.elapsed.total_seconds()

    @property
    def rate(self) -> float:
        """Taux d'évaluation (eval/sec)."""
        if self.elapsed_seconds == 0:
            return 0.0
        return self.evaluated / self.elapsed_seconds

    @property
    def eta(self) -> Optional[timedelta]:
        """Temps estimé restant."""
        if self.rate == 0:
            return None
        remaining = self.total_combinations - self.evaluated
        return timedelta(seconds=remaining / self.rate)

    @property
    def eta_str(self) -> str:
        """ETA formaté."""
        eta = self.eta
        if eta is None:
            return "Calcul..."

        total_secs = int(eta.total_seconds())
        if total_secs < 60:
            return f"{total_secs}s"
        elif total_secs < 3600:
            return f"{total_secs // 60}m {total_secs % 60}s"
        else:
            hours = total_secs // 3600
            mins = (total_secs % 3600) // 60
            return f"{hours}h {mins}m"


class SweepMonitor:
    """
    Stateful progress tracker for grid sweeps (optimizations, grid search).

    Lifecycle:
      - Created before a sweep begins with known total combinations.
      - `.update()` is called per evaluation and top results are updated.
      - Handed to `render_sweep_progress`/`render_sweep_summary` for UI render.
    Responsibilities:
      - Record metrics, maintain top-K leaders, and expose ETA/progress.
    """

    def __init__(
        self,
        total_combinations: int,
        objectives: List[str] = None,
        top_k: int = 10,
        max_results: Optional[int] = 100,  # ✅ FIX: Limite par défaut pour éviter OOM
        max_history: Optional[int] = 1000,  # ✅ FIX: Limite par défaut pour graphiques
        initial_capital: Optional[float] = None,
    ):
        """
        Args:
            total_combinations: Nombre total de combinaisons à évaluer
            objectives: Liste des objectifs à tracker
            top_k: Nombre de meilleurs résultats à garder
            max_results: Limite résultats en mémoire (défaut: 100, 0=illimité ⚠️ OOM risk)
            max_history: Limite historique graphiques (défaut: 1000, 0=illimité ⚠️ OOM risk)
        """
        self.total = total_combinations
        # Note: Utiliser les clés correctes retournées par calculate_metrics
        # Ajout de 'total_pnl' pour tracking visible du meilleur gain
        self.objectives = objectives or ['total_pnl', 'sharpe_ratio', 'total_return_pct', 'max_drawdown_pct']
        self.top_k = top_k
        self.max_results = max_results if max_results != 0 else None  # 0 = illimité
        self.max_history = max_history if max_history != 0 else None  # 0 = illimité
        self.initial_capital = initial_capital

        # ✅ FIX: Toujours utiliser deque avec maxlen pour éviter OOM
        self._results: deque = deque(maxlen=self.max_results)
        self._top_results: Dict[str, List[SweepResult]] = {
            obj: [] for obj in self.objectives
        }
        self._stats = SweepStats(total_combinations=total_combinations)
        # ✅ FIX: Toujours deque avec maxlen (1000 par défaut)
        self._metric_history = {
            obj: deque(maxlen=self.max_history or 1000) for obj in self.objectives
        }
        self._last_update = None

        # Compteur pour downsampling automatique
        self._update_count = 0

    def start(self):
        """Démarre le monitoring."""
        self._stats.start_time = datetime.now()

    @staticmethod
    def _normalize_metrics(metrics: Dict[str, Any]) -> Dict[str, float]:
        """Normalise les métriques pour affichage cohérent multi-stratégies."""
        if not metrics:
            return {}
        normalized: Dict[str, float] = {}
        for key, value in metrics.items():
            try:
                normalized[key] = float(value)
            except Exception:
                continue

        # Harmoniser drawdown (toujours positif, en %)
        if "max_drawdown_pct" in normalized:
            normalized["max_drawdown_pct"] = abs(normalized["max_drawdown_pct"])
        if "max_drawdown" in normalized:
            normalized["max_drawdown"] = abs(normalized["max_drawdown"])
        if "max_drawdown_pct" not in normalized and "max_drawdown" in normalized:
            normalized["max_drawdown_pct"] = normalized["max_drawdown"]
        if "max_drawdown" not in normalized and "max_drawdown_pct" in normalized:
            normalized["max_drawdown"] = normalized["max_drawdown_pct"]

        # Harmoniser win_rate (en %)
        if "win_rate" in normalized:
            win_rate = normalized["win_rate"]
            if 0 <= win_rate <= 1.0:
                normalized["win_rate"] = win_rate * 100.0
                normalized["win_rate_pct"] = normalized["win_rate"]
        if "win_rate_pct" in normalized and "win_rate" not in normalized:
            normalized["win_rate"] = normalized["win_rate_pct"]

        # Harmoniser total_trades
        if "total_trades" not in normalized and "trades" in normalized:
            normalized["total_trades"] = normalized["trades"]

        return normalized

    def update(
        self,
        params: Dict[str, Any],
        metrics: Dict[str, float],
        duration_ms: float = 0.0,
        pruned: bool = False,
        error: bool = False,
    ):
        """
        Met à jour avec un nouveau résultat.

        Args:
            params: Paramètres évalués
            metrics: Métriques résultantes
            duration_ms: Durée de l'évaluation
            pruned: Si la combinaison a été prunée
            error: Si une erreur s'est produite
        """
        if self._stats.start_time is None:
            self.start()

        if error:
            self._stats.errors += 1
            self._stats.evaluated += 1
            return

        if pruned:
            self._stats.pruned += 1
            self._stats.evaluated += 1
            return

        self._stats.evaluated += 1
        self._update_count += 1

        metrics = self._normalize_metrics(metrics)

        result = SweepResult(
            params=params,
            metrics=metrics,
            duration_ms=duration_ms,
        )

        # ✅ FIX: deque gère automatiquement la limite (pas besoin de del manuel)
        self._results.append(result)

        # ✅ FIX: Mettre à jour l'historique (deque auto-limite)
        for obj in self.objectives:
            if obj in metrics:
                self._metric_history[obj].append(metrics[obj])

        # Mettre à jour les top résultats
        self._update_top_results(result)
        self._last_update = datetime.now()

        # GC désactivé — le GC forcé toutes les 1000 itérations coûtait
        # 17-85s sur 1.7M résultats (1700 cycles GC). Python gère la
        # mémoire automatiquement via GC générationnel.

    def _update_top_results(self, result: SweepResult):
        """Met à jour les meilleurs résultats."""
        if result.metrics.get("account_ruined"):
            return
        for obj in self.objectives:
            if obj not in result.metrics:
                continue

            top = self._top_results[obj]
            top.append(result)

            # Trier et garder le top_k
            # Minimiser uniquement le drawdown, maximiser tout le reste (PnL, Sharpe, Return)
            reverse = obj not in ['max_drawdown', 'max_drawdown_pct']
            top.sort(key=lambda r: r.metrics.get(obj, 0), reverse=reverse)
            del top[self.top_k:]  # in-place, zéro allocation (vs slice = nouvelle liste)

    @property
    def stats(self) -> SweepStats:
        """Retourne les statistiques."""
        return self._stats

    @property
    def results(self) -> List[SweepResult]:
        """Retourne tous les résultats."""
        return list(self._results)

    def get_top_results(self, objective: str) -> List[SweepResult]:
        """Retourne les meilleurs résultats pour un objectif."""
        return self._top_results.get(objective, [])

    def get_best_result(self, objective: str) -> Optional[SweepResult]:
        """Retourne le meilleur résultat pour un objectif."""
        top = self.get_top_results(objective)
        return top[0] if top else None

    def get_metric_history(self, objective: str) -> List[float]:
        """Retourne l'historique d'une métrique (complet)."""
        history = self._metric_history.get(objective, [])
        return list(history)

    def get_metric_history_downsampled(
        self,
        objective: str,
        max_points: int = 500
    ) -> List[float]:
        """
        Retourne l'historique d'une métrique avec downsampling automatique.

        ✅ FIX OOM: Pour sweeps longs (>10k runs), réduit automatiquement
        le nombre de points affichés sans perdre la tendance visuelle.

        Args:
            objective: Métrique à récupérer
            max_points: Nombre max de points à retourner (défaut: 500)

        Returns:
            Liste de valeurs (downsamplée si nécessaire)
        """
        history = list(self._metric_history.get(objective, []))

        if len(history) <= max_points:
            return history

        # Downsampling simple : prendre 1 point tous les N
        step = len(history) // max_points
        if step < 1:
            step = 1

        return history[::step]

    @property
    def is_complete(self) -> bool:
        """Indique si le sweep est terminé."""
        return self._stats.evaluated >= self.total


def _create_progress_chart(stats: SweepStats) -> go.Figure:
    """Crée un graphique de progression."""
    evaluated = stats.evaluated
    pruned = stats.pruned
    remaining = stats.total_combinations - evaluated - pruned

    fig = go.Figure(data=[go.Pie(
        values=[evaluated, pruned, remaining],
        labels=['Évalués', 'Prunés', 'Restants'],
        marker_colors=['#2ca02c', '#ff7f0e', '#d3d3d3'],
        hole=0.6,
        textinfo='percent',
        textposition='outside',
    )])

    fig.update_layout(
        height=200,
        margin=dict(l=20, r=20, t=20, b=20),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.2),
        annotations=[dict(
            text=f"{stats.progress_percent:.0f}%",
            x=0.5, y=0.5,
            font_size=24,
            showarrow=False
        )],
    )

    return fig


def _create_metric_evolution_chart(
    history: Dict[str, List[float]],
    objectives: List[str],
) -> go.Figure:
    """Crée le graphique d'évolution des métriques."""
    fig = go.Figure()

    colors = ['#1f77b4', '#2ca02c', '#ff7f0e', '#d62728']

    for i, obj in enumerate(objectives):
        values = list(history.get(obj, []))
        if not values:
            continue

        # Calculer la moyenne mobile
        window = min(20, len(values))
        if window > 1:
            moving_avg = np.convolve(values, np.ones(window)/window, mode='valid')
            x_values = list(range(window-1, len(values)))
        else:
            moving_avg = values
            x_values = list(range(len(values)))

        fig.add_trace(go.Scatter(
            x=x_values,
            y=moving_avg,
            name=obj.replace('_', ' ').title(),
            line=dict(color=colors[i % len(colors)], width=2),
        ))

    fig.update_layout(
        height=200,
        margin=dict(l=40, r=20, t=30, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(title="Évaluations"),
        yaxis=dict(title="Valeur"),
    )

    return fig


def _create_param_impact_chart(
    results: List[SweepResult],
    objective: str,
    param_name: str,
) -> go.Figure:
    """Crée un graphique d'impact d'un paramètre."""
    if not results:
        return go.Figure()

    # Extraire les données
    param_values = []
    metric_values = []

    for r in results:
        if param_name in r.params and objective in r.metrics:
            param_values.append(r.params[param_name])
            metric_values.append(r.metrics[objective])

    if not param_values:
        return go.Figure()

    fig = go.Figure(data=go.Scatter(
        x=param_values,
        y=metric_values,
        mode='markers',
        marker=dict(
            color=metric_values,
            colorscale='Viridis',
            size=8,
            showscale=True,
            colorbar=dict(title=objective),
        ),
    ))

    fig.update_layout(
        height=200,
        margin=dict(l=40, r=20, t=30, b=30),
        xaxis=dict(title=param_name),
        yaxis=dict(title=objective),
    )

    return fig


def render_sweep_progress(
    monitor: SweepMonitor,
    key: str = "sweep_monitor",
    show_top_results: bool = True,
    show_evolution: bool = True,
    static_plots: bool = False,
):
    """
    Streamlit panel that renders live sweep progress and leaderboards.

    Called inside the grid search loop to provide real-time feedback,
    including gauges, evolution chart and top results per objective.

    Args:
        monitor: Stateful sweep tracker updated per result.
        key: Unique widget key for rerun safety.
        show_top_results: Toggle the leaderboard section.
        show_evolution: Toggle the metrics evolution chart.
        static_plots: Désactiver interactivité Plotly (réduit WebSocket overhead).
    """
    if not STREAMLIT_AVAILABLE:
        raise ImportError("Streamlit non disponible")

    stats = monitor.stats

    # Header avec stats principales
    st.subheader("🔄 Sweep Progress")

    # ═══════════════════════════════════════════════════════════════════════════
    # 🚀 AFFICHAGE DÉBIT EN TEMPS RÉEL (bt/s) - Style "Gaming"
    # ═══════════════════════════════════════════════════════════════════════════
    rate = stats.rate
    if rate > 0:
        # Couleur selon performance (vert > 100/s, jaune 10-100, rouge < 10)
        if rate >= 100:
            rate_color = "#00ff88"  # Vert néon
            rate_icon = "🚀"
            rate_label = "TURBO"
        elif rate >= 10:
            rate_color = "#ffcc00"  # Jaune
            rate_icon = "⚡"
            rate_label = "FAST"
        else:
            rate_color = "#ff6b6b"  # Rouge
            rate_icon = "🐢"
            rate_label = "SLOW"

        st.markdown(
            f"""<div style='background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            padding: 15px 25px; border-radius: 12px; text-align: center; margin-bottom: 15px;
            border: 2px solid {rate_color}; box-shadow: 0 0 20px {rate_color}40;'>
            <span style='color: #888; font-size: 0.9em; text-transform: uppercase; letter-spacing: 2px;'>
            {rate_label} MODE</span>
            <h2 style='color: {rate_color}; margin: 5px 0; font-size: 2.5em; font-weight: bold;
            text-shadow: 0 0 10px {rate_color};'>
            {rate_icon} {rate:,.1f} bt/s {rate_icon}
            </h2>
            <span style='color: #aaa; font-size: 0.85em;'>
            {stats.evaluated:,} / {stats.total_combinations:,} ({stats.progress_percent:.1f}%) • ETA: {stats.eta_str}
            </span>
            </div>""",
            unsafe_allow_html=True
        )

    # Afficher UNIQUEMENT la meilleure config (PnL, equity, trades, drawdown)
    try:
        best_result = monitor.get_best_result("total_pnl")
        if best_result and best_result.metrics:
            best_pnl = float(best_result.metrics.get("total_pnl", 0.0))
            best_trades = int(best_result.metrics.get("total_trades", best_result.metrics.get("trades", 0)) or 0)
            best_dd = float(best_result.metrics.get("max_drawdown_pct", best_result.metrics.get("max_drawdown", 0.0)) or 0.0)
            equity = None
            if monitor.initial_capital is not None:
                equity = float(monitor.initial_capital) + best_pnl

            pnl_color = "#28a745" if best_pnl > 0 else "#dc3545"
            pnl_icon = "📈" if best_pnl > 0 else "📉"
            best_sign = "+" if best_pnl > 0 else ("-" if best_pnl < 0 else "")

            equity_line = ""
            if equity is not None:
                equity_sign = "+" if equity - float(monitor.initial_capital or 0) > 0 else ""
                equity_line = f"<div style='color: #f8f9fa; font-size: 1.05em; margin-top: 8px;'>💹 Equity: <b>{equity_sign}${equity:,.2f}</b></div>"

            st.markdown(
                f"""<div style='background: linear-gradient(135deg, {pnl_color} 0%, {pnl_color}dd 100%);
                padding: 18px; border-radius: 10px; text-align: center; margin-bottom: 12px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);'>
                <h2 style='color: white; margin: 0; font-size: 1.7em;'>
                {pnl_icon} Meilleure Config: <b>{best_sign}${abs(best_pnl):,.2f}</b> {pnl_icon}
                </h2>
                <div style='color: #f8f9fa; font-size: 1.05em; margin-top: 8px;'>
                🔁 Trades: <b>{best_trades:,}</b> • 📉 Max DD: <b>{abs(best_dd):.2f}%</b>
                </div>
                {equity_line}
                </div>""",
                unsafe_allow_html=True,
            )
    except Exception:
        pass  # Ne pas bloquer l'affichage si erreur

    # Métriques principales avec style amélioré
    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric(
            "📊 Progression",
            f"{stats.progress_percent:.1f}%",
            f"{stats.evaluated}/{stats.total_combinations}",
        )

    with col2:
        st.metric(
            "⚡ Vitesse",
            f"{stats.rate:.1f}/s",
            f"{stats.elapsed_seconds:.0f}s écoulés",
        )

    with col3:
        st.metric("⏱️ ETA", stats.eta_str)

    with col4:
        st.metric(
            "✂️ Prunés",
            f"{stats.pruned}",
            delta=f"-{stats.pruned}" if stats.pruned > 0 else None,
            delta_color="off"
        )

    with col5:
        st.metric(
            "❌ Erreurs",
            f"{stats.errors}",
            delta=f"+{stats.errors}" if stats.errors > 0 else None,
            delta_color="inverse"
        )

    # Barre de progression avec couleur
    progress_color = "#28a745" if stats.progress_percent > 50 else "#ffc107" if stats.progress_percent > 25 else "#dc3545"
    st.markdown(f"""
        <div style='margin: 10px 0;'>
            <div style='background-color: #e9ecef; border-radius: 10px; overflow: hidden; height: 30px;'>
                <div style='background: linear-gradient(90deg, {progress_color} 0%, {progress_color}aa 100%);
                width: {stats.progress_percent}%; height: 100%; display: flex; align-items: center;
                justify-content: center; color: white; font-weight: bold; transition: width 0.3s;'>
                {stats.progress_percent:.1f}%
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # Graphiques côte à côte
    if PLOTLY_AVAILABLE:
        # Configuration Plotly : mode statique réduit la taille des messages WebSocket
        plotly_config = {
            "staticPlot": static_plots,  # Désactiver toute interactivité si demandé
            "displayModeBar": not static_plots,  # Masquer la toolbar en mode statique
            "displaylogo": False,
        } if static_plots else {"displaylogo": False}

        col_left, col_right = st.columns(2)

        with col_left:
            st.markdown("**Distribution**")
            fig = _create_progress_chart(stats)
            st.plotly_chart(
                fig,
                width="stretch",
                key=f"{key}_dist",
                config=plotly_config
            )

        if show_evolution and monitor.get_metric_history(monitor.objectives[0]):
            with col_right:
                st.markdown("**Évolution des métriques**")
                # ✅ FIX OOM: Utiliser downsampling pour gros volumes
                history_downsampled = {
                    obj: monitor.get_metric_history_downsampled(obj, max_points=500)
                    for obj in monitor.objectives
                }
                fig = _create_metric_evolution_chart(
                    history_downsampled,
                    monitor.objectives,
                )
                st.plotly_chart(
                    fig,
                    width="stretch",
                    key=f"{key}_evol",
                    config=plotly_config
                )

    # Meilleurs résultats avec design amélioré
    if show_top_results:
        st.markdown("---")
        st.markdown("### 🏆 Top Résultats par Métrique")

        tabs = st.tabs([f"{obj.replace('_', ' ').title()}" for obj in monitor.objectives])

        for i, obj in enumerate(monitor.objectives):
            with tabs[i]:
                top_results = monitor.get_top_results(obj)

                if top_results:
                    # Tableau des résultats avec formatage amélioré
                    data = []
                    display_results = top_results[:monitor.top_k]
                    for rank, r in enumerate(display_results, 1):
                        # Médailles pour le top 3
                        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"#{rank}"

                        row = {"🏅": medal}

                        # Ajouter les paramètres
                        for k, v in r.params.items():
                            if isinstance(v, np.integer):
                                row[k] = int(v)
                            elif isinstance(v, np.floating):
                                row[k] = round(float(v), 3)
                            elif isinstance(v, float):
                                row[k] = round(v, 3)
                            elif isinstance(v, int) and not isinstance(v, bool):
                                row[k] = v
                            else:
                                row[k] = str(v)

                        # Ajouter les métriques clés
                        total_pnl = r.metrics.get("total_pnl", 0.0) or 0.0
                        pnl_day = _pnl_per_day(total_pnl, r.metrics.get("period_days"))
                        total_return = r.metrics.get("total_return_pct", 0.0) or 0.0
                        sharpe = r.metrics.get("sharpe_ratio", 0.0) or 0.0
                        max_dd = r.metrics.get("max_drawdown_pct", 0.0) or 0.0
                        row["PnL"] = float(total_pnl)
                        if pnl_day is not None:
                            row["PnL/jour"] = float(pnl_day)
                        row["Return%"] = float(total_return)
                        row["Sharpe"] = float(sharpe)
                        row["MaxDD%"] = abs(float(max_dd))

                        data.append(row)

                    results_df = pd.DataFrame(data)
                    st.dataframe(
                        results_df,
                        width="stretch",
                        hide_index=True,
                        height=min(400, len(results_df) * 35 + 38),  # Hauteur dynamique
                        column_config={
                            "PnL": st.column_config.NumberColumn("PnL", format="$%.0f"),
                            "PnL/jour": st.column_config.NumberColumn("PnL/jour", format="$%.2f"),
                            "Return%": st.column_config.NumberColumn("Return%", format="%.1f%%"),
                            "Sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f"),
                            "MaxDD%": st.column_config.NumberColumn("MaxDD%", format="%.1f%%"),
                        },
                    )
                else:
                    st.info("⏳ En attente des premiers résultats...")


def render_sweep_summary(monitor: SweepMonitor, key: str = "sweep_summary"):
    """
    Summary view rendered once the sweep completes.

    Highlights total duration, rate, pruning ratio and best parameter sets per objective.

    Args:
        monitor: SweepMonitor that tracked the recently finished sweep.
        key: Widget key for the summary block.
    """
    if not STREAMLIT_AVAILABLE:
        return

    stats = monitor.stats

    st.success(f"✅ Sweep terminé - {stats.evaluated} combinaisons évaluées")
    ruined_count = sum(1 for r in monitor.results if r.metrics.get("account_ruined"))
    if ruined_count:
        st.warning(
            f"⚠️ {ruined_count} combinaison(s) ont ruiné le compte "
            "et sont exclues du classement."
        )

    # Stats finales
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Durée totale", f"{stats.elapsed_seconds:.1f}s")

    with col2:
        st.metric("Vitesse moyenne", f"{stats.rate:.2f}/s")

    with col3:
        st.metric("Taux de pruning", f"{(stats.pruned/stats.total_combinations)*100:.1f}%")

    # Meilleurs paramètres
    st.markdown("### 🏆 Meilleurs paramètres")

    any_best_found = False
    for obj in monitor.objectives:
        best = monitor.get_best_result(obj)
        if best:
            any_best_found = True
            with st.expander(f"**{obj.replace('_', ' ').title()}**: {best.metrics.get(obj, 0):.4f}"):
                st.json(best.params)

    if not any_best_found:
        st.warning(
            f"❌ Aucun résultat valide trouvé.\n\n"
            f"**{stats.errors}** erreurs sur **{stats.evaluated}** combinaisons évaluées.\n\n"
            "Vérifiez les logs ci-dessus pour identifier le problème."
        )


__all__ = [
    "SweepResult",
    "SweepStats",
    "SweepMonitor",
    "render_sweep_progress",
    "render_sweep_summary",
]
