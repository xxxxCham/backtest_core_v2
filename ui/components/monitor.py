"""
Module-ID: ui.components.monitor

Purpose: Renderer Streamlit pour monitoring système temps réel - CPU, RAM, GPU, Disk.

Role in pipeline: visualization/monitoring

Key components: SystemMonitor, render_system_monitor(), render_mini_monitor(), ResourceReading

Inputs: System snapshots via psutil

Outputs: Streamlit metric cards, rolling history charts

Dependencies: streamlit (optionnel), plotly (optionnel), psutil (optionnel)

Conventions: 1s interval; rolling window 100 points; color alerts (% thresholds).

Read-if: Modification metrics collection ou alert thresholds.

Skip-if: Vous appelez render_system_monitor().
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

try:
    import streamlit as st
    STREAMLIT_AVAILABLE = True
except ImportError:
    STREAMLIT_AVAILABLE = False

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


@dataclass
class ResourceReading:
    """
    Snapshot of the system resource state at a given timestamp.

    Captures CPU, RAM, GPU and disk utilization so that the monitor panels
    can display time series and thresholds without coupling to psutil later.
    """
    timestamp: datetime
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used_gb: float = 0.0
    memory_total_gb: float = 0.0
    gpu_percent: float = 0.0
    gpu_memory_percent: float = 0.0
    gpu_memory_used_gb: float = 0.0
    gpu_memory_total_gb: float = 0.0
    disk_percent: float = 0.0
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0


@dataclass
class SystemMonitorConfig:
    """
    Alerting thresholds and refresh settings for the system monitor.

    Defines percent thresholds for warnings/critical states and how often
    telemetry is sampled. Passed to `SystemMonitor` at construction.
    """
    # Seuils d'alerte (pourcentage)
    cpu_warning: float = 80.0
    cpu_critical: float = 95.0
    memory_warning: float = 80.0
    memory_critical: float = 90.0
    gpu_warning: float = 85.0
    gpu_critical: float = 95.0
    disk_warning: float = 85.0
    disk_critical: float = 95.0

    # Historique
    max_history: int = 60  # Points d'historique

    # Rafraîchissement
    refresh_interval: float = 2.0  # Secondes


class SystemMonitor:
    """
    Collector responsible for polling and storing `ResourceReading` history.

    Lifecycle: instantiated at Streamlit startup, optionally scheduled to sample every
    `refresh_interval`, and queried by renderers to plot current values or sparkline.
    """

    def __init__(self, config: Optional[SystemMonitorConfig] = None):
        """
        Args:
            config: Configuration du moniteur
        """
        self.config = config or SystemMonitorConfig()
        self._history: List[ResourceReading] = []
        self._gpu_available = self._check_gpu()

    def _check_gpu(self) -> bool:
        """Monitoring GPU désactivé (CPU-only)."""
        return False

    def get_current_reading(self) -> ResourceReading:
        """
        Collecte les métriques actuelles.

        Returns:
            ResourceReading avec toutes les métriques
        """
        reading = ResourceReading(timestamp=datetime.now())

        if PSUTIL_AVAILABLE:
            # CPU
            reading.cpu_percent = psutil.cpu_percent(interval=0.1)

            # Memory
            mem = psutil.virtual_memory()
            reading.memory_percent = mem.percent
            reading.memory_used_gb = mem.used / (1024**3)
            reading.memory_total_gb = mem.total / (1024**3)

            # Disk
            disk = psutil.disk_usage('/')
            reading.disk_percent = disk.percent
            reading.disk_used_gb = disk.used / (1024**3)
            reading.disk_total_gb = disk.total / (1024**3)

        # GPU
        if self._gpu_available:
            try:
                import pynvml
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)

                # Utilisation GPU
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                reading.gpu_percent = util.gpu

                # Mémoire GPU
                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                reading.gpu_memory_used_gb = mem_info.used / (1024**3)
                reading.gpu_memory_total_gb = mem_info.total / (1024**3)
                reading.gpu_memory_percent = (mem_info.used / mem_info.total) * 100

            except Exception:
                pass

        return reading

    def update(self) -> ResourceReading:
        """
        Met à jour l'historique avec une nouvelle lecture.

        Returns:
            Dernière lecture
        """
        reading = self.get_current_reading()
        self._history.append(reading)

        # Limiter l'historique
        if len(self._history) > self.config.max_history:
            self._history = self._history[-self.config.max_history:]

        return reading

    @property
    def history(self) -> List[ResourceReading]:
        """Retourne l'historique des lectures."""
        return list(self._history)

    @property
    def gpu_available(self) -> bool:
        """Indique si le GPU est disponible."""
        return self._gpu_available

    def get_status(self, reading: ResourceReading) -> Dict[str, str]:
        """
        Détermine le status de chaque ressource.

        Returns:
            Dict resource -> status ('ok', 'warning', 'critical')
        """
        status = {}

        # CPU
        if reading.cpu_percent >= self.config.cpu_critical:
            status['cpu'] = 'critical'
        elif reading.cpu_percent >= self.config.cpu_warning:
            status['cpu'] = 'warning'
        else:
            status['cpu'] = 'ok'

        # Memory
        if reading.memory_percent >= self.config.memory_critical:
            status['memory'] = 'critical'
        elif reading.memory_percent >= self.config.memory_warning:
            status['memory'] = 'warning'
        else:
            status['memory'] = 'ok'

        # GPU
        if self._gpu_available:
            if reading.gpu_memory_percent >= self.config.gpu_critical:
                status['gpu'] = 'critical'
            elif reading.gpu_memory_percent >= self.config.gpu_warning:
                status['gpu'] = 'warning'
            else:
                status['gpu'] = 'ok'

        # Disk
        if reading.disk_percent >= self.config.disk_critical:
            status['disk'] = 'critical'
        elif reading.disk_percent >= self.config.disk_warning:
            status['disk'] = 'warning'
        else:
            status['disk'] = 'ok'

        return status

    def clear_history(self):
        """Efface l'historique."""
        self._history.clear()


def _get_status_color(status: str) -> str:
    """Retourne la couleur pour un status."""
    colors = {
        'ok': '#00cc00',       # Vert
        'warning': '#ffaa00',  # Orange
        'critical': '#ff0000',  # Rouge
    }
    return colors.get(status, '#888888')


def _create_gauge(
    value: float,
    title: str,
    status: str,
    suffix: str = "%"
) -> go.Figure:
    """Crée un gauge Plotly."""
    color = _get_status_color(status)

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        title={'text': title, 'font': {'size': 14}},
        number={'suffix': suffix, 'font': {'size': 20}},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1},
            'bar': {'color': color},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "gray",
            'steps': [
                {'range': [0, 80], 'color': 'rgba(0, 200, 0, 0.1)'},
                {'range': [80, 90], 'color': 'rgba(255, 170, 0, 0.1)'},
                {'range': [90, 100], 'color': 'rgba(255, 0, 0, 0.1)'},
            ],
        }
    ))

    fig.update_layout(
        height=150,
        margin=dict(l=20, r=20, t=40, b=10),
    )

    return fig


def _create_history_chart(
    history: List[ResourceReading],
    show_gpu: bool = False
) -> go.Figure:
    """Crée le graphique d'historique."""
    if not history:
        fig = go.Figure()
        fig.update_layout(
            height=200,
            title="Historique (en attente de données...)",
        )
        return fig

    timestamps = [r.timestamp for r in history]

    fig = make_subplots(
        rows=1, cols=1,
        shared_xaxes=True,
    )

    # CPU
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=[r.cpu_percent for r in history],
        name="CPU",
        line=dict(color='#1f77b4', width=2),
        fill='tozeroy',
        fillcolor='rgba(31, 119, 180, 0.1)',
    ))

    # Memory
    fig.add_trace(go.Scatter(
        x=timestamps,
        y=[r.memory_percent for r in history],
        name="RAM",
        line=dict(color='#2ca02c', width=2),
    ))

    # GPU si disponible
    if show_gpu:
        fig.add_trace(go.Scatter(
            x=timestamps,
            y=[r.gpu_percent for r in history],
            name="GPU",
            line=dict(color='#ff7f0e', width=2),
        ))
        fig.add_trace(go.Scatter(
            x=timestamps,
            y=[r.gpu_memory_percent for r in history],
            name="VRAM",
            line=dict(color='#d62728', width=2, dash='dash'),
        ))

    fig.update_layout(
        height=200,
        margin=dict(l=40, r=20, t=30, b=30),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        yaxis=dict(range=[0, 100], title="Usage %"),
        xaxis=dict(title=""),
    )

    return fig


def render_system_monitor(
    key: str = "system_monitor",
    show_history: bool = True,
    show_gauges: bool = True,
    compact: bool = False,
):
    """
    Streamlit panel that keeps system resource usage visible during a backtest.

    Uses the session-scoped `SystemMonitor` instance to poll ResourceReading snapshots,
    then draws alerts/gauges/history so the operator can stop a run before hitting limits.

    Args:
        key: Unique Streamlit key so reruns remain idempotent.
        show_history: Display the time-series history chart.
        show_gauges: Render gauge widgets for CPU/RAM/GPU/Disk.
        compact: Reduce the detail level for sidebar embedding.
    """
    if not STREAMLIT_AVAILABLE:
        raise ImportError("Streamlit non disponible")

    if not PLOTLY_AVAILABLE:
        st.error("Plotly requis pour le System Monitor")
        return

    # Initialiser le moniteur dans session_state
    monitor_key = f"{key}_monitor"
    if monitor_key not in st.session_state:
        st.session_state[monitor_key] = SystemMonitor()

    monitor: SystemMonitor = st.session_state[monitor_key]

    # Collecter les données
    reading = monitor.update()
    status = monitor.get_status(reading)

    # Header
    st.subheader("📊 System Monitor")

    # Alertes
    alerts = []
    if status.get('cpu') == 'critical':
        alerts.append(f"⚠️ CPU critique: {reading.cpu_percent:.1f}%")
    if status.get('memory') == 'critical':
        alerts.append(f"⚠️ RAM critique: {reading.memory_percent:.1f}%")
    if status.get('gpu') == 'critical':
        alerts.append(f"⚠️ GPU critique: {reading.gpu_memory_percent:.1f}%")
    if status.get('disk') == 'critical':
        alerts.append(f"⚠️ Disk critique: {reading.disk_percent:.1f}%")

    if alerts:
        for alert in alerts:
            st.error(alert)

    # Gauges
    if show_gauges:
        cols = st.columns(4 if monitor.gpu_available else 3)

        with cols[0]:
            fig = _create_gauge(reading.cpu_percent, "CPU", status.get('cpu', 'ok'))
            st.plotly_chart(fig, width='stretch', key=f"{key}_cpu_gauge")
            if not compact:
                st.caption(f"Cœurs: {psutil.cpu_count() if PSUTIL_AVAILABLE else 'N/A'}")

        with cols[1]:
            fig = _create_gauge(reading.memory_percent, "RAM", status.get('memory', 'ok'))
            st.plotly_chart(fig, width='stretch', key=f"{key}_ram_gauge")
            if not compact:
                st.caption(f"{reading.memory_used_gb:.1f} / {reading.memory_total_gb:.1f} GB")

        if monitor.gpu_available:
            with cols[2]:
                fig = _create_gauge(reading.gpu_memory_percent, "VRAM", status.get('gpu', 'ok'))
                st.plotly_chart(fig, width='stretch', key=f"{key}_gpu_gauge")
                if not compact:
                    st.caption(f"{reading.gpu_memory_used_gb:.1f} / {reading.gpu_memory_total_gb:.1f} GB")

            disk_col = cols[3]
        else:
            disk_col = cols[2]

        with disk_col:
            fig = _create_gauge(reading.disk_percent, "Disk", status.get('disk', 'ok'))
            st.plotly_chart(fig, width='stretch', key=f"{key}_disk_gauge")
            if not compact:
                st.caption(f"{reading.disk_used_gb:.1f} / {reading.disk_total_gb:.1f} GB")

    # Historique
    if show_history and len(monitor.history) > 1:
        st.markdown("**Historique**")
        fig = _create_history_chart(monitor.history, show_gpu=monitor.gpu_available)
        st.plotly_chart(fig, width='stretch', key=f"{key}_history")

    # Info de mise à jour
    st.caption(f"Dernière mise à jour: {reading.timestamp.strftime('%H:%M:%S')}")


def render_mini_monitor(key: str = "mini_monitor"):
    """
    Lightweight sidebar card showing the latest CPU/RAM/GPU state.

    Designed to stay visible beside the main Streamlit canvas so that operators
    monitor resource pressure while long sweeps run in the background.

    Args:
        key: Unique widget key for the sidebar card.
    """
    if not STREAMLIT_AVAILABLE or not PSUTIL_AVAILABLE:
        return

    # Collecter les données basiques
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()

    # Indicateurs simples
    st.markdown("**📊 Ressources**")

    # CPU avec couleur
    cpu_color = "🟢" if cpu < 80 else ("🟡" if cpu < 95 else "🔴")
    st.markdown(f"{cpu_color} CPU: **{cpu:.0f}%**")

    # RAM avec couleur
    mem_color = "🟢" if mem.percent < 80 else ("🟡" if mem.percent < 90 else "🔴")
    st.markdown(f"{mem_color} RAM: **{mem.percent:.0f}%** ({mem.used/(1024**3):.1f}GB)")

    # GPU si disponible
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        gpu_pct = (mem_info.used / mem_info.total) * 100
        gpu_color = "🟢" if gpu_pct < 85 else ("🟡" if gpu_pct < 95 else "🔴")
        st.markdown(f"{gpu_color} GPU: **{gpu_pct:.0f}%** ({mem_info.used/(1024**3):.1f}GB)")
    except Exception:
        pass


__all__ = [
    "ResourceReading",
    "SystemMonitorConfig",
    "SystemMonitor",
    "render_system_monitor",
    "render_mini_monitor",
]
