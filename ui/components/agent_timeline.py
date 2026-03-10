"""
Module-ID: ui.components.agent_timeline

Purpose: Timeline visuelle activité agents LLM - events détails par agent (Analyst, Strategist, Critic, Validator).

Role in pipeline: visualization/monitoring

Key components: AgentActivity, AgentActivityTimeline, render_agent_timeline(), render_mini_timeline()

Inputs: Agent events (timestamps, decisions, metrics)

Outputs: Plotly interactive timeline Streamlit

Dependencies: streamlit, plotly, dataclasses

Conventions: AgentType enum, ActivityType categorization, metrics snapshot

Read-if: Afficher timeline agents LLM.

Skip-if: Pas d'agents LLM ou monitoring minimal.

Usage:
    >>> from ui.components.agent_timeline import render_agent_timeline
    >>> render_agent_timeline(timeline)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    import plotly.graph_objects as go
    import streamlit as st
    from plotly.subplots import make_subplots
    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False


class AgentType(Enum):
    """Types d'agents dans le système."""
    ANALYST = "analyst"
    STRATEGIST = "strategist"
    CRITIC = "critic"
    VALIDATOR = "validator"
    ORCHESTRATOR = "orchestrator"
    EXECUTOR = "executor"


class ActivityType(Enum):
    """Types d'activités des agents."""
    STARTED = "started"
    COMPLETED = "completed"
    ANALYSIS = "analysis"
    PROPOSAL = "proposal"
    CRITIQUE = "critique"
    DECISION = "decision"
    BACKTEST = "backtest"
    ERROR = "error"
    ITERATION = "iteration"


class DecisionType(Enum):
    """Types de décisions."""
    APPROVE = "approve"
    REJECT = "reject"
    ITERATE = "iterate"
    STOP = "stop"


# Couleurs par agent
AGENT_COLORS = {
    AgentType.ANALYST: "#2196f3",       # Bleu
    AgentType.STRATEGIST: "#4caf50",    # Vert
    AgentType.CRITIC: "#ff9800",        # Orange
    AgentType.VALIDATOR: "#9c27b0",     # Violet
    AgentType.ORCHESTRATOR: "#607d8b",  # Gris-bleu
    AgentType.EXECUTOR: "#00bcd4",      # Cyan
}

# Icônes par type d'activité
ACTIVITY_ICONS = {
    ActivityType.STARTED: "🚀",
    ActivityType.COMPLETED: "✅",
    ActivityType.ANALYSIS: "📊",
    ActivityType.PROPOSAL: "💡",
    ActivityType.CRITIQUE: "🔍",
    ActivityType.DECISION: "⚖️",
    ActivityType.BACKTEST: "📈",
    ActivityType.ERROR: "❌",
    ActivityType.ITERATION: "🔄",
}


@dataclass
class AgentActivity:
    """
    Data carrier for a single agent event inside the orchestration timeline.

    Responsible for keeping metadata (agent type, activity type, iteration, duration)
    so that the UI can plot decisions and alerts without leaking orchestration logic.
    Lifecycle: created by `AgentActivityTimeline.log_activity` when the orchestrator
    reports a new event, then rendered in the Streamlit timeline panels.
    """
    timestamp: datetime
    agent: AgentType
    activity_type: ActivityType
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: Optional[float] = None
    iteration: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "agent": self.agent.value,
            "activity_type": self.activity_type.value,
            "message": self.message,
            "details": self.details,
            "duration_ms": self.duration_ms,
            "iteration": self.iteration,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentActivity":
        """Crée depuis un dictionnaire."""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            agent=AgentType(data["agent"]),
            activity_type=ActivityType(data["activity_type"]),
            message=data["message"],
            details=data.get("details", {}),
            duration_ms=data.get("duration_ms"),
            iteration=data.get("iteration", 0),
        )


@dataclass
class MetricsSnapshot:
    """Snapshot des métriques à un moment donné."""
    timestamp: datetime
    iteration: int
    sharpe_ratio: float
    total_return: float
    max_drawdown: float
    win_rate: float
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "iteration": self.iteration,
            "sharpe_ratio": self.sharpe_ratio,
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "params": self.params,
        }


@dataclass
class AgentDecision:
    """
    Represents a discrete decision emitted by an agent.

    Encapsulates agent identity, reasoning and confidence so that the UI can render
    proposal/approval flows in the timeline. Decisions are collected during a run and
    displayed in the Streamlit detail tab, never altering engine state.
    """
    timestamp: datetime
    agent: AgentType
    decision: DecisionType
    reasoning: str
    confidence: float = 0.0
    iteration: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "agent": self.agent.value,
            "decision": self.decision.value,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "iteration": self.iteration,
        }


class AgentActivityTimeline:
    """
    Stateful container that records agent activities, decisions, and metrics for a session.

    Position: UI instrumentation layer that subscribes to orchestrator events.
    Responsibilities: aggregate activities/decisions per iteration, compute summary,
    expose serialization helpers, and drive the timeline renderers.
    Lifecycle: created at start of a backtest session, receives `log_activity`/`log_decision`,
    then passed to Streamlit renderers (`render_agent_timeline`, `render_mini_timeline`).
    """

    def __init__(self, session_name: str = "Session"):
        """
        Initialise la timeline.

        Args:
            session_name: Nom de la session
        """
        self.session_name = session_name
        self.start_time = datetime.now()
        self._activities: List[AgentActivity] = []
        self._metrics_history: List[MetricsSnapshot] = []
        self._decisions: List[AgentDecision] = []
        self._current_iteration = 0

    @property
    def activities(self) -> List[AgentActivity]:
        """Liste des activités."""
        return self._activities

    @property
    def metrics_history(self) -> List[MetricsSnapshot]:
        """Historique des métriques."""
        return self._metrics_history

    @property
    def decisions(self) -> List[AgentDecision]:
        """Liste des décisions."""
        return self._decisions

    @property
    def duration(self) -> timedelta:
        """Durée totale de la session."""
        if not self._activities:
            return timedelta(0)
        return self._activities[-1].timestamp - self.start_time

    @property
    def current_iteration(self) -> int:
        """Itération courante."""
        return self._current_iteration

    def log_activity(
        self,
        agent: AgentType,
        activity_type: ActivityType,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[float] = None,
    ) -> AgentActivity:
        """
        Enregistre une activité.

        Args:
            agent: Type d'agent
            activity_type: Type d'activité
            message: Message descriptif
            details: Détails supplémentaires
            duration_ms: Durée en millisecondes

        Returns:
            L'activité créée
        """
        activity = AgentActivity(
            timestamp=datetime.now(),
            agent=agent,
            activity_type=activity_type,
            message=message,
            details=details or {},
            duration_ms=duration_ms,
            iteration=self._current_iteration,
        )
        self._activities.append(activity)
        return activity

    def log_metrics(
        self,
        sharpe_ratio: float,
        total_return: float,
        max_drawdown: float,
        win_rate: float,
        params: Optional[Dict[str, Any]] = None,
    ) -> MetricsSnapshot:
        """
        Enregistre un snapshot de métriques.

        Args:
            sharpe_ratio: Sharpe ratio
            total_return: Rendement total
            max_drawdown: Drawdown maximum
            win_rate: Taux de victoire
            params: Paramètres utilisés

        Returns:
            Le snapshot créé
        """
        snapshot = MetricsSnapshot(
            timestamp=datetime.now(),
            iteration=self._current_iteration,
            sharpe_ratio=sharpe_ratio,
            total_return=total_return,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            params=params or {},
        )
        self._metrics_history.append(snapshot)
        return snapshot

    def log_decision(
        self,
        agent: AgentType,
        decision: DecisionType,
        reasoning: str,
        confidence: float = 0.0,
    ) -> AgentDecision:
        """
        Enregistre une décision.

        Args:
            agent: Agent qui prend la décision
            decision: Type de décision
            reasoning: Raisonnement
            confidence: Niveau de confiance (0-1)

        Returns:
            La décision créée
        """
        dec = AgentDecision(
            timestamp=datetime.now(),
            agent=agent,
            decision=decision,
            reasoning=reasoning,
            confidence=confidence,
            iteration=self._current_iteration,
        )
        self._decisions.append(dec)
        return dec

    def next_iteration(self) -> int:
        """Passe à l'itération suivante."""
        self._current_iteration += 1
        return self._current_iteration

    def get_activities_by_agent(self, agent: AgentType) -> List[AgentActivity]:
        """Filtre les activités par agent."""
        return [a for a in self._activities if a.agent == agent]

    def get_activities_by_iteration(self, iteration: int) -> List[AgentActivity]:
        """Filtre les activités par itération."""
        return [a for a in self._activities if a.iteration == iteration]

    def get_summary(self) -> Dict[str, Any]:
        """
        Génère un résumé de la timeline.

        Returns:
            Dict avec statistiques de la session
        """
        activities_by_agent = {}
        for agent in AgentType:
            activities_by_agent[agent.value] = len(self.get_activities_by_agent(agent))

        decisions_by_type = {}
        for dec in self._decisions:
            key = dec.decision.value
            decisions_by_type[key] = decisions_by_type.get(key, 0) + 1

        best_metrics = None
        if self._metrics_history:
            best = max(self._metrics_history, key=lambda m: m.sharpe_ratio)
            best_metrics = {
                "iteration": best.iteration,
                "sharpe_ratio": best.sharpe_ratio,
                "total_return": best.total_return,
                "params": best.params,
            }

        return {
            "session_name": self.session_name,
            "duration_seconds": self.duration.total_seconds(),
            "total_activities": len(self._activities),
            "total_iterations": self._current_iteration,
            "activities_by_agent": activities_by_agent,
            "total_decisions": len(self._decisions),
            "decisions_by_type": decisions_by_type,
            "best_metrics": best_metrics,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        return {
            "session_name": self.session_name,
            "start_time": self.start_time.isoformat(),
            "current_iteration": self._current_iteration,
            "activities": [a.to_dict() for a in self._activities],
            "metrics_history": [m.to_dict() for m in self._metrics_history],
            "decisions": [d.to_dict() for d in self._decisions],
        }

    def to_json(self) -> str:
        """Sérialise en JSON."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentActivityTimeline":
        """Charge depuis un dictionnaire."""
        timeline = cls(session_name=data["session_name"])
        timeline.start_time = datetime.fromisoformat(data["start_time"])
        timeline._current_iteration = data["current_iteration"]
        timeline._activities = [
            AgentActivity.from_dict(a) for a in data["activities"]
        ]
        # Note: metrics_history et decisions ont des formats simples
        return timeline


def create_timeline_figure(timeline: AgentActivityTimeline) -> go.Figure:
    """
    Builds the Plotly figure used by the timeline renderer.

    This function anchors the streamlit panel with a Gantt-like view of agent activities
    and a summary of metrics history. It is called with the timeline produced by
    `AgentActivityTimeline` just before plotting.

    Args:
        timeline: Timeline containing the current run's activities and metrics.

    Returns:
        Plotly Figure ready for `st.plotly_chart`.
    """
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.1,
        row_heights=[0.6, 0.4],
        subplot_titles=("Timeline des agents", "Évolution des métriques"),
    )

    # Timeline des activités par agent
    for agent in AgentType:
        activities = timeline.get_activities_by_agent(agent)
        if not activities:
            continue

        x = [a.timestamp for a in activities]
        y = [agent.value for a in activities]
        text = [f"{ACTIVITY_ICONS.get(a.activity_type, '')} {a.message}" for a in activities]

        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="markers+text",
                name=agent.value.capitalize(),
                marker=dict(
                    size=12,
                    color=AGENT_COLORS.get(agent, "#666"),
                    symbol="circle",
                ),
                text=[ACTIVITY_ICONS.get(a.activity_type, "•") for a in activities],
                textposition="top center",
                hovertext=text,
                hoverinfo="text",
            ),
            row=1,
            col=1,
        )

    # Évolution des métriques
    if timeline.metrics_history:
        timestamps = [m.timestamp for m in timeline.metrics_history]
        sharpe = [m.sharpe_ratio for m in timeline.metrics_history]
        returns = [m.total_return * 100 for m in timeline.metrics_history]

        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=sharpe,
                mode="lines+markers",
                name="Sharpe Ratio",
                line=dict(color="#2196f3", width=2),
                marker=dict(size=8),
            ),
            row=2,
            col=1,
        )

        fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=returns,
                mode="lines+markers",
                name="Return (%)",
                line=dict(color="#4caf50", width=2),
                marker=dict(size=8),
                yaxis="y3",
            ),
            row=2,
            col=1,
        )

    # Styling
    fig.update_layout(
        height=600,
        template="plotly_dark",
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )

    fig.update_yaxes(
        title_text="Agent",
        row=1,
        col=1,
        categoryorder="array",
        categoryarray=[a.value for a in AgentType],
    )

    fig.update_yaxes(title_text="Sharpe / Return (%)", row=2, col=1)

    return fig


def render_agent_timeline(
    timeline: AgentActivityTimeline,
    key: str = "agent_timeline",
) -> None:
    """
    Streamlit panel that surfaces agent activity and metrics history.

    Called after each orchestration run to visualize session health for analysts.

    Args:
        timeline: Activity timeline collected from the orchestrator.
        key: Unique widget key to allow reruns without collision.
    """
    if not STREAMLIT_AVAILABLE:
        return

    st.subheader(f"🤖 Timeline - {timeline.session_name}")

    # Métriques résumé
    summary = timeline.get_summary()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("⏱️ Durée", f"{summary['duration_seconds']:.1f}s")
    col2.metric("🔄 Itérations", summary["total_iterations"])
    col3.metric("📝 Activités", summary["total_activities"])
    col4.metric("⚖️ Décisions", summary["total_decisions"])

    # Graphique timeline
    fig = create_timeline_figure(timeline)
    st.plotly_chart(fig, width='stretch', key=f"{key}_chart")

    # Détails par onglets
    tab1, tab2, tab3 = st.tabs(["📋 Activités", "⚖️ Décisions", "📊 Métriques"])

    with tab1:
        # Filtrer par agent
        agent_filter = st.multiselect(
            "Filtrer par agent",
            [a.value for a in AgentType],
            default=[a.value for a in AgentType],
            key=f"{key}_agent_filter",
        )

        # Afficher les activités récentes
        activities = [
            a for a in reversed(timeline.activities)
            if a.agent.value in agent_filter
        ][:50]  # Limiter à 50

        for activity in activities:
            icon = ACTIVITY_ICONS.get(activity.activity_type, "•")
            color = AGENT_COLORS.get(activity.agent, "#666")

            with st.container():
                col1, col2 = st.columns([1, 4])
                with col1:
                    st.markdown(
                        f"<span style='color:{color};font-weight:bold'>"
                        f"{activity.agent.value.upper()}</span>",
                        unsafe_allow_html=True,
                    )
                    st.caption(activity.timestamp.strftime("%H:%M:%S"))
                with col2:
                    st.markdown(f"{icon} **{activity.activity_type.value}**")
                    st.write(activity.message)
                    if activity.details:
                        with st.expander("Détails"):
                            st.json(activity.details)
                st.divider()

    with tab2:
        for dec in reversed(timeline.decisions):
            icon = "✅" if dec.decision == DecisionType.APPROVE else \
                   "❌" if dec.decision == DecisionType.REJECT else \
                   "🔄" if dec.decision == DecisionType.ITERATE else "⏹️"

            col1, col2, col3 = st.columns([1, 2, 2])
            with col1:
                st.markdown(f"### {icon}")
                st.caption(f"Iter {dec.iteration}")
            with col2:
                st.markdown(f"**{dec.decision.value.upper()}**")
                st.write(f"Par: {dec.agent.value}")
            with col3:
                st.progress(dec.confidence, text=f"Confiance: {dec.confidence:.0%}")

            st.caption(dec.reasoning)
            st.divider()

    with tab3:
        if timeline.metrics_history:
            # Tableau des métriques
            data = []
            for m in timeline.metrics_history:
                data.append({
                    "Iteration": m.iteration,
                    "Sharpe": f"{m.sharpe_ratio:.3f}",
                    "Return": f"{m.total_return:.2%}",
                    "Drawdown": f"{m.max_drawdown:.2%}",
                    "Win Rate": f"{m.win_rate:.1%}",
                })

            st.dataframe(data, width='stretch')

            # Best result
            if summary["best_metrics"]:
                st.success(
                    f"🏆 Meilleur résultat (Iter {summary['best_metrics']['iteration']}): "
                    f"Sharpe = {summary['best_metrics']['sharpe_ratio']:.3f}"
                )
        else:
            st.info("Aucune métrique enregistrée")

    # Export
    with st.expander("📥 Export"):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Copier JSON", key=f"{key}_copy"):
                st.code(timeline.to_json(), language="json")
        with col2:
            st.download_button(
                "Télécharger JSON",
                timeline.to_json(),
                f"timeline_{timeline.session_name}.json",
                "application/json",
                key=f"{key}_download",
            )


def render_mini_timeline(
    timeline: AgentActivityTimeline,
    max_activities: int = 5,
    key: str = "mini_timeline",
) -> None:
    """
    Compact sidebar summary of the most recent agent events.

    Used by the sidebar to keep orchestration feedback visible while running backtests.

    Args:
        timeline: Same timeline instance rendered in the main panel.
        max_activities: Maximum number items shown for quick review.
        key: Widget key to avoid Streamlit collisions.
    """
    if not STREAMLIT_AVAILABLE:
        return

    st.markdown("### 🤖 Agents")

    # Statut rapide
    col1, col2 = st.columns(2)
    col1.metric("Iter", timeline.current_iteration)
    col2.metric("Acts", len(timeline.activities))

    # Dernières activités
    st.markdown("**Récent:**")
    for activity in list(reversed(timeline.activities))[:max_activities]:
        icon = ACTIVITY_ICONS.get(activity.activity_type, "•")
        agent_short = activity.agent.value[:3].upper()
        st.caption(f"{icon} [{agent_short}] {activity.message[:30]}...")
