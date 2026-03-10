"""
Module-ID: ui.components.validation_viewer

Purpose: Renderer Streamlit pour rapports walk-forward validation - résumé, graphiques, overfitting flags.

Role in pipeline: visualization/analysis

Key components: render_validation_report(), render_validation_summary_card(), ValidationReport dataclass

Inputs: WalkForwardValidator results {train_metrics, test_metrics per window}

Outputs: Streamlit UI {tabs, cards, charts}, overfitting warnings

Dependencies: streamlit (optionnel), plotly (optionnel), pandas, dataclasses

Conventions: Train (bleu), Test (orange); overfitting flag si ratio > 1.2; TTL cache 1h.

Read-if: Modification validation rendering ou métrique selection.

Skip-if: Vous appelez render_validation_report(report).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    import plotly.graph_objects as go
    import streamlit as st
    from plotly.subplots import make_subplots
    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False


class ValidationStatus(Enum):
    """Statut de validation."""
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    OVERFITTING = "overfitting"


@dataclass
class WindowResult:
    """
    Represents metrics and parameters for a single walk-forward fold.

    Captures train/test metrics/degradation to allow UI cards and charts to flag
    problematic windows while keeping the validation logic separated.
    """
    window_id: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime

    # Métriques train
    train_sharpe: float
    train_return: float
    train_drawdown: float
    train_trades: int

    # Métriques test
    test_sharpe: float
    test_return: float
    test_drawdown: float
    test_trades: int

    # Paramètres optimaux
    params: Dict[str, Any] = field(default_factory=dict)

    @property
    def sharpe_degradation(self) -> float:
        """Dégradation du Sharpe entre train et test."""
        if self.train_sharpe == 0:
            return 0.0
        return (self.train_sharpe - self.test_sharpe) / abs(self.train_sharpe)

    @property
    def return_degradation(self) -> float:
        """Dégradation du return entre train et test."""
        if self.train_return == 0:
            return 0.0
        return (self.train_return - self.test_return) / abs(self.train_return)

    @property
    def is_overfitting(self) -> bool:
        """Détecte si cette fenêtre montre de l'overfitting."""
        # Overfitting si dégradation > 50% ou test négatif avec train positif
        if self.sharpe_degradation > 0.5:
            return True
        if self.train_sharpe > 0 and self.test_sharpe < 0:
            return True
        if self.train_return > 0 and self.test_return < 0:
            return True
        return False

    @property
    def status(self) -> ValidationStatus:
        """Détermine le statut de validation."""
        if self.is_overfitting:
            return ValidationStatus.OVERFITTING
        if self.sharpe_degradation > 0.3:
            return ValidationStatus.WARNING
        if self.test_sharpe < 0:
            return ValidationStatus.FAILED
        return ValidationStatus.PASSED

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "window_id": self.window_id,
            "train_period": f"{self.train_start.date()} → {self.train_end.date()}",
            "test_period": f"{self.test_start.date()} → {self.test_end.date()}",
            "train_sharpe": self.train_sharpe,
            "test_sharpe": self.test_sharpe,
            "train_return": self.train_return,
            "test_return": self.test_return,
            "train_drawdown": self.train_drawdown,
            "test_drawdown": self.test_drawdown,
            "sharpe_degradation": self.sharpe_degradation,
            "status": self.status.value,
            "params": self.params,
        }


@dataclass
class ValidationReport:
    """
    Aggregated walk-forward validation report.

    Contains windows, aggregate metrics, and helpers to surface the best params.
    Lifespan: produced by the validation runner and consumed by UI renderers.
    """
    strategy_name: str
    created_at: datetime
    windows: List[WindowResult]

    # Configuration
    n_splits: int = 5
    train_ratio: float = 0.8
    purge_gap: int = 0

    # Métriques globales (calculées)
    _aggregate_metrics: Optional[Dict[str, float]] = field(default=None, repr=False)

    @property
    def aggregate_metrics(self) -> Dict[str, float]:
        """Calcule les métriques agrégées."""
        if self._aggregate_metrics is not None:
            return self._aggregate_metrics

        if not self.windows:
            return {}

        train_sharpes = [w.train_sharpe for w in self.windows]
        test_sharpes = [w.test_sharpe for w in self.windows]
        train_returns = [w.train_return for w in self.windows]
        test_returns = [w.test_return for w in self.windows]
        degradations = [w.sharpe_degradation for w in self.windows]

        import numpy as np

        self._aggregate_metrics = {
            "avg_train_sharpe": float(np.mean(train_sharpes)),
            "avg_test_sharpe": float(np.mean(test_sharpes)),
            "std_test_sharpe": float(np.std(test_sharpes)),
            "avg_train_return": float(np.mean(train_returns)),
            "avg_test_return": float(np.mean(test_returns)),
            "avg_degradation": float(np.mean(degradations)),
            "max_degradation": float(np.max(degradations)),
            "consistency_ratio": float(np.mean([1 if w.test_sharpe > 0 else 0 for w in self.windows])),
            "overfitting_windows": sum(1 for w in self.windows if w.is_overfitting),
        }

        return self._aggregate_metrics

    @property
    def overall_status(self) -> ValidationStatus:
        """Statut global de la validation."""
        metrics = self.aggregate_metrics

        # Échec si trop de fenêtres overfitting
        if metrics.get("overfitting_windows", 0) >= len(self.windows) // 2:
            return ValidationStatus.OVERFITTING

        # Warning si dégradation moyenne > 30%
        if metrics.get("avg_degradation", 0) > 0.3:
            return ValidationStatus.WARNING

        # Échec si Sharpe test moyen négatif
        if metrics.get("avg_test_sharpe", 0) < 0:
            return ValidationStatus.FAILED

        # Passé si consistance > 70%
        if metrics.get("consistency_ratio", 0) >= 0.7:
            return ValidationStatus.PASSED

        return ValidationStatus.WARNING

    @property
    def is_valid(self) -> bool:
        """La stratégie est-elle validée?"""
        return self.overall_status == ValidationStatus.PASSED

    def get_best_params(self) -> Dict[str, Any]:
        """Retourne les paramètres les plus robustes."""
        if not self.windows:
            return {}

        # Prendre les params de la fenêtre avec le meilleur test_sharpe
        # tout en ayant une bonne consistance train/test
        valid_windows = [w for w in self.windows if not w.is_overfitting]

        if not valid_windows:
            valid_windows = self.windows

        best = max(valid_windows, key=lambda w: w.test_sharpe)
        return best.params

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        return {
            "strategy_name": self.strategy_name,
            "created_at": self.created_at.isoformat(),
            "n_splits": self.n_splits,
            "train_ratio": self.train_ratio,
            "purge_gap": self.purge_gap,
            "overall_status": self.overall_status.value,
            "is_valid": self.is_valid,
            "aggregate_metrics": self.aggregate_metrics,
            "windows": [w.to_dict() for w in self.windows],
            "best_params": self.get_best_params(),
        }


# Couleurs par statut
STATUS_COLORS = {
    ValidationStatus.PASSED: "#4caf50",
    ValidationStatus.WARNING: "#ff9800",
    ValidationStatus.FAILED: "#f44336",
    ValidationStatus.OVERFITTING: "#9c27b0",
}

STATUS_ICONS = {
    ValidationStatus.PASSED: "✅",
    ValidationStatus.WARNING: "⚠️",
    ValidationStatus.FAILED: "❌",
    ValidationStatus.OVERFITTING: "📈❌",
}


def create_validation_figure(report: ValidationReport) -> go.Figure:
    """
    Crée une figure Plotly du rapport de validation.

    Args:
        report: Rapport à visualiser

    Returns:
        Figure Plotly
    """
    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "Sharpe Ratio: Train vs Test",
            "Return: Train vs Test",
            "Dégradation par fenêtre",
            "Statut par fenêtre",
        ),
        vertical_spacing=0.15,
        horizontal_spacing=0.1,
    )

    window_ids = [w.window_id for w in report.windows]

    # Sharpe comparison
    fig.add_trace(
        go.Bar(
            x=window_ids,
            y=[w.train_sharpe for w in report.windows],
            name="Train Sharpe",
            marker_color="#2196f3",
            opacity=0.7,
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=window_ids,
            y=[w.test_sharpe for w in report.windows],
            name="Test Sharpe",
            marker_color="#4caf50",
            opacity=0.7,
        ),
        row=1,
        col=1,
    )

    # Return comparison
    fig.add_trace(
        go.Bar(
            x=window_ids,
            y=[w.train_return * 100 for w in report.windows],
            name="Train Return %",
            marker_color="#2196f3",
            opacity=0.7,
            showlegend=False,
        ),
        row=1,
        col=2,
    )
    fig.add_trace(
        go.Bar(
            x=window_ids,
            y=[w.test_return * 100 for w in report.windows],
            name="Test Return %",
            marker_color="#4caf50",
            opacity=0.7,
            showlegend=False,
        ),
        row=1,
        col=2,
    )

    # Degradation
    degradations = [w.sharpe_degradation * 100 for w in report.windows]
    colors = ["#f44336" if d > 50 else "#ff9800" if d > 30 else "#4caf50" for d in degradations]

    fig.add_trace(
        go.Bar(
            x=window_ids,
            y=degradations,
            name="Dégradation %",
            marker_color=colors,
        ),
        row=2,
        col=1,
    )

    # Ligne seuil 30%
    fig.add_hline(y=30, line_dash="dash", line_color="orange", row=2, col=1)
    fig.add_hline(y=50, line_dash="dash", line_color="red", row=2, col=1)

    # Status indicators
    status_values = []
    status_colors = []
    for w in report.windows:
        status = w.status
        status_values.append(list(ValidationStatus).index(status))
        status_colors.append(STATUS_COLORS[status])

    fig.add_trace(
        go.Bar(
            x=window_ids,
            y=[1] * len(window_ids),
            name="Statut",
            marker_color=status_colors,
            text=[STATUS_ICONS[w.status] for w in report.windows],
            textposition="inside",
        ),
        row=2,
        col=2,
    )

    # Styling
    fig.update_layout(
        height=600,
        template="plotly_dark",
        barmode="group",
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )

    fig.update_xaxes(title_text="Fenêtre", row=2, col=1)
    fig.update_xaxes(title_text="Fenêtre", row=2, col=2)
    fig.update_yaxes(title_text="Sharpe Ratio", row=1, col=1)
    fig.update_yaxes(title_text="Return (%)", row=1, col=2)
    fig.update_yaxes(title_text="Dégradation (%)", row=2, col=1)

    return fig


def render_validation_report(
    report: ValidationReport,
    key: str = "validation_report",
) -> None:
    """
    Streamlit dashboard that surfaces a Walk-Forward validation report.

    Displays status badges, global metrics, per-window tables and the multi-panel figure
    so that users can judge strategy robustness during backtests.

    Args:
        report: ValidationReport produced by `validation_integration`.
        key: Widget key preventing Streamlit rerun collisions.
    """
    if not STREAMLIT_AVAILABLE:
        return

    # En-tête avec statut global
    status = report.overall_status
    status_color = STATUS_COLORS[status]
    status_icon = STATUS_ICONS[status]

    st.markdown(
        f"## {status_icon} Rapport de Validation - {report.strategy_name}"
    )

    # Badge statut
    st.markdown(
        f"<span style='background-color:{status_color};color:white;padding:5px 15px;"
        f"border-radius:15px;font-weight:bold'>{status.value.upper()}</span>",
        unsafe_allow_html=True,
    )

    st.caption(f"Créé le {report.created_at.strftime('%d/%m/%Y %H:%M')}")

    # Métriques résumé
    st.markdown("### 📊 Métriques Globales")

    metrics = report.aggregate_metrics

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Sharpe Train (moy)",
        f"{metrics.get('avg_train_sharpe', 0):.3f}",
    )
    col2.metric(
        "Sharpe Test (moy)",
        f"{metrics.get('avg_test_sharpe', 0):.3f}",
        delta=f"{-metrics.get('avg_degradation', 0):.1%}",
        delta_color="inverse",
    )
    col3.metric(
        "Consistance",
        f"{metrics.get('consistency_ratio', 0):.0%}",
    )
    col4.metric(
        "Fenêtres Overfitting",
        f"{metrics.get('overfitting_windows', 0)}/{len(report.windows)}",
    )

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Return Train (moy)",
        f"{metrics.get('avg_train_return', 0):.2%}",
    )
    col2.metric(
        "Return Test (moy)",
        f"{metrics.get('avg_test_return', 0):.2%}",
    )
    col3.metric(
        "Dégradation Max",
        f"{metrics.get('max_degradation', 0):.1%}",
    )
    col4.metric(
        "Écart-type Test",
        f"{metrics.get('std_test_sharpe', 0):.3f}",
    )

    # Graphique
    st.markdown("### 📈 Visualisation")
    fig = create_validation_figure(report)
    st.plotly_chart(fig, width='stretch', key=f"{key}_chart")

    # Détails par fenêtre
    st.markdown("### 🔍 Détails par Fenêtre")

    # Tableau récapitulatif
    data = []
    for w in report.windows:
        data.append({
            "Fenêtre": w.window_id,
            "Train": f"{w.train_start.date()} → {w.train_end.date()}",
            "Test": f"{w.test_start.date()} → {w.test_end.date()}",
            "Sharpe (T)": f"{w.train_sharpe:.3f}",
            "Sharpe (V)": f"{w.test_sharpe:.3f}",
            "Dégr.": f"{w.sharpe_degradation:.1%}",
            "Statut": f"{STATUS_ICONS[w.status]} {w.status.value}",
        })

    st.dataframe(data, width='stretch')

    # Détails expandables
    for w in report.windows:
        status_icon = STATUS_ICONS[w.status]
        with st.expander(f"Fenêtre {w.window_id} {status_icon}", expanded=False):
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**📈 Train**")
                st.write(f"Période: {w.train_start.date()} → {w.train_end.date()}")
                st.write(f"Sharpe: {w.train_sharpe:.3f}")
                st.write(f"Return: {w.train_return:.2%}")
                st.write(f"Drawdown: {w.train_drawdown:.2%}")
                st.write(f"Trades: {w.train_trades}")

            with col2:
                st.markdown("**🧪 Test**")
                st.write(f"Période: {w.test_start.date()} → {w.test_end.date()}")
                st.write(f"Sharpe: {w.test_sharpe:.3f}")
                st.write(f"Return: {w.test_return:.2%}")
                st.write(f"Drawdown: {w.test_drawdown:.2%}")
                st.write(f"Trades: {w.test_trades}")

            if w.params:
                st.markdown("**🔧 Paramètres optimaux**")
                st.json(w.params)

    # Recommandation
    st.markdown("### 💡 Recommandation")

    if report.overall_status == ValidationStatus.PASSED:
        st.success(
            "✅ **Stratégie validée** - Les performances sont consistantes entre "
            "l'entraînement et le test. La stratégie peut être utilisée en production."
        )
        best_params = report.get_best_params()
        if best_params:
            st.markdown("**Paramètres recommandés:**")
            st.json(best_params)

    elif report.overall_status == ValidationStatus.WARNING:
        st.warning(
            "⚠️ **Attention** - Dégradation significative entre train et test. "
            "Considérez d'ajuster les paramètres ou de réduire la complexité."
        )

    elif report.overall_status == ValidationStatus.OVERFITTING:
        st.error(
            "📈❌ **Overfitting détecté** - Les performances train ne se généralisent pas "
            "sur les données de test. Simplifiez la stratégie ou utilisez moins de paramètres."
        )

    else:
        st.error(
            "❌ **Échec de validation** - La stratégie ne performe pas de manière "
            "satisfaisante sur les données de test."
        )

    # Export
    with st.expander("📥 Export"):
        import json
        report_json = json.dumps(report.to_dict(), indent=2, default=str)

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "Télécharger JSON",
                report_json,
                f"validation_{report.strategy_name}.json",
                "application/json",
                key=f"{key}_download",
            )
        with col2:
            if st.button("Afficher JSON", key=f"{key}_show_json"):
                st.code(report_json, language="json")


def render_validation_summary_card(
    report: ValidationReport,
    key: str = "validation_card",
) -> None:
    """
    Compact sidebar card summarizing validation status and best candidates.

    Useful for quick sanity checks without expanding the full report panel.

    Args:
        report: Same validation report as the main panel.
        key: Streamlit widget key.
    """
    if not STREAMLIT_AVAILABLE:
        return

    status = report.overall_status
    status_color = STATUS_COLORS[status]
    status_icon = STATUS_ICONS[status]
    metrics = report.aggregate_metrics

    with st.container():
        st.markdown(
            f"<div style='border-left: 4px solid {status_color}; padding-left: 10px;'>"
            f"<strong>{status_icon} {report.strategy_name}</strong><br/>"
            f"<small>Sharpe Test: {metrics.get('avg_test_sharpe', 0):.3f} | "
            f"Consistance: {metrics.get('consistency_ratio', 0):.0%}</small>"
            f"</div>",
            unsafe_allow_html=True,
        )


def create_sample_report() -> ValidationReport:
    """Crée un rapport exemple pour les tests."""
    import random
    from datetime import timedelta

    windows = []
    base_date = datetime(2024, 1, 1)

    for i in range(5):
        train_start = base_date + timedelta(days=i * 60)
        train_end = train_start + timedelta(days=180)
        test_start = train_end + timedelta(days=1)
        test_end = test_start + timedelta(days=45)

        train_sharpe = random.uniform(0.8, 2.5)
        degradation = random.uniform(0.1, 0.6)

        windows.append(WindowResult(
            window_id=i + 1,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            train_sharpe=train_sharpe,
            train_return=random.uniform(0.05, 0.25),
            train_drawdown=random.uniform(0.05, 0.15),
            train_trades=random.randint(50, 150),
            test_sharpe=train_sharpe * (1 - degradation),
            test_return=random.uniform(-0.02, 0.15),
            test_drawdown=random.uniform(0.05, 0.20),
            test_trades=random.randint(10, 40),
            params={"fast_period": 10 + i, "slow_period": 20 + i * 2},
        ))

    return ValidationReport(
        strategy_name="ema_cross",
        created_at=datetime.now(),
        windows=windows,
        n_splits=5,
        train_ratio=0.8,
    )
