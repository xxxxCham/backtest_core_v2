"""
Module-ID: utils.health

Purpose: Health Monitor - surveillance CPU/RAM/GPU/Disk avec alertes et seuils.

Role in pipeline: performance / monitoring

Key components: HealthMonitor, HealthMetrics, HealthAlert, Severity enum

Inputs: Seuils (%), polling intervals

Outputs: Métriques santé, alertes, déclenchement actions

Dependencies: psutil, threading, dataclasses, cpu_percent, memory_percent

Conventions: Seuils configurables; alertes sévérité (CRITICAL/WARNING); polling asynchrone.

Read-if: Modification seuils, métriques collectées, ou actions alertes.

Skip-if: Vous utilisez juste HealthMonitor.check().
"""

from __future__ import annotations

import gc
import logging
import os
import platform
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """États de santé du système."""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ResourceType(Enum):
    """Types de ressources surveillées."""
    CPU = "cpu"
    MEMORY = "memory"
    GPU = "gpu"
    DISK = "disk"


@dataclass
class ResourceMetrics:
    """Métriques d'une ressource."""
    resource_type: ResourceType
    usage_percent: float
    available: float  # En bytes ou %
    total: float      # En bytes ou %
    status: HealthStatus = HealthStatus.UNKNOWN
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "resource": self.resource_type.value,
            "usage_percent": round(self.usage_percent, 2),
            "available": self.available,
            "total": self.total,
            "status": self.status.value,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class HealthThresholds:
    """Seuils pour les alertes de santé."""
    # CPU
    cpu_warning: float = 80.0
    cpu_critical: float = 95.0

    # Memory
    memory_warning: float = 75.0
    memory_critical: float = 90.0

    # GPU
    gpu_warning: float = 85.0
    gpu_critical: float = 95.0

    # Disk
    disk_warning: float = 80.0
    disk_critical: float = 95.0

    def get_status(self, resource: ResourceType, usage: float) -> HealthStatus:
        """Détermine le status basé sur l'usage."""
        if resource == ResourceType.CPU:
            warning, critical = self.cpu_warning, self.cpu_critical
        elif resource == ResourceType.MEMORY:
            warning, critical = self.memory_warning, self.memory_critical
        elif resource == ResourceType.GPU:
            warning, critical = self.gpu_warning, self.gpu_critical
        elif resource == ResourceType.DISK:
            warning, critical = self.disk_warning, self.disk_critical
        else:
            return HealthStatus.UNKNOWN

        if usage >= critical:
            return HealthStatus.CRITICAL
        elif usage >= warning:
            return HealthStatus.WARNING
        else:
            return HealthStatus.HEALTHY


@dataclass
class HealthSnapshot:
    """Snapshot complet de l'état de santé."""
    timestamp: datetime
    overall_status: HealthStatus
    metrics: Dict[ResourceType, ResourceMetrics]
    alerts: List[str] = field(default_factory=list)
    system_info: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dictionnaire."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "overall_status": self.overall_status.value,
            "metrics": {k.value: v.to_dict() for k, v in self.metrics.items()},
            "alerts": self.alerts,
            "system_info": self.system_info,
        }


class HealthMonitor:
    """
    Moniteur de santé du système.

    Surveille CPU, RAM, GPU et disque avec alertes configurables.

    Example:
        >>> monitor = HealthMonitor()
        >>> snapshot = monitor.check_health()
        >>> print(snapshot.overall_status)
        >>>
        >>> # Surveillance continue
        >>> monitor.start_monitoring(interval=5.0)
        >>> # ... plus tard ...
        >>> monitor.stop_monitoring()
    """

    def __init__(
        self,
        thresholds: Optional[HealthThresholds] = None,
        on_alert: Optional[Callable[[str, HealthStatus], None]] = None
    ):
        """
        Initialise le moniteur.

        Args:
            thresholds: Seuils d'alerte personnalisés
            on_alert: Callback appelé lors d'une alerte
        """
        self.thresholds = thresholds or HealthThresholds()
        self.on_alert = on_alert

        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._history: List[HealthSnapshot] = []
        self._max_history = 1000
        self._lock = threading.Lock()

        # Détecter les libs disponibles
        self._has_psutil = self._check_psutil()
        self._has_gpu = self._check_gpu()

        logger.debug(f"HealthMonitor initialisé (psutil={self._has_psutil}, gpu={self._has_gpu})")

    def _check_psutil(self) -> bool:
        """Vérifie si psutil est disponible."""
        try:
            import psutil  # noqa: F401
            return True
        except ImportError:
            logger.warning("psutil non disponible - métriques CPU/RAM limitées")
            return False

    def _check_gpu(self) -> bool:
        """Monitoring GPU désactivé (CPU-only)."""
        return False

    def get_cpu_metrics(self) -> ResourceMetrics:
        """Récupère les métriques CPU."""
        try:
            if self._has_psutil:
                import psutil
                usage = psutil.cpu_percent(interval=0.1)
                freq = psutil.cpu_freq()

                details = {
                    "cores": psutil.cpu_count(logical=False),
                    "threads": psutil.cpu_count(logical=True),
                    "frequency_mhz": freq.current if freq else 0,
                }
            else:
                # Estimation basique sans psutil
                usage = 0.0
                details = {"cores": os.cpu_count() or 1}

            status = self.thresholds.get_status(ResourceType.CPU, usage)

            return ResourceMetrics(
                resource_type=ResourceType.CPU,
                usage_percent=usage,
                available=100.0 - usage,
                total=100.0,
                status=status,
                details=details,
            )
        except Exception as e:
            logger.error(f"Erreur CPU metrics: {e}")
            return ResourceMetrics(
                resource_type=ResourceType.CPU,
                usage_percent=0,
                available=0,
                total=0,
                status=HealthStatus.UNKNOWN,
            )

    def get_memory_metrics(self) -> ResourceMetrics:
        """Récupère les métriques mémoire."""
        try:
            if self._has_psutil:
                import psutil
                mem = psutil.virtual_memory()

                usage = mem.percent
                available = mem.available
                total = mem.total

                details = {
                    "used_gb": round(mem.used / (1024**3), 2),
                    "available_gb": round(mem.available / (1024**3), 2),
                    "total_gb": round(mem.total / (1024**3), 2),
                    "cached_gb": round(getattr(mem, 'cached', 0) / (1024**3), 2),
                }
            else:
                # Estimation basique via gc
                gc.collect()
                usage = 50.0  # Estimation par défaut
                available = 0
                total = 0
                details = {}

            status = self.thresholds.get_status(ResourceType.MEMORY, usage)

            return ResourceMetrics(
                resource_type=ResourceType.MEMORY,
                usage_percent=usage,
                available=available,
                total=total,
                status=status,
                details=details,
            )
        except Exception as e:
            logger.error(f"Erreur memory metrics: {e}")
            return ResourceMetrics(
                resource_type=ResourceType.MEMORY,
                usage_percent=0,
                available=0,
                total=0,
                status=HealthStatus.UNKNOWN,
            )

    def get_gpu_metrics(self) -> ResourceMetrics:
        """Récupère les métriques GPU."""
        return ResourceMetrics(
            resource_type=ResourceType.GPU,
            usage_percent=0,
            available=0,
            total=0,
            status=HealthStatus.UNKNOWN,
            details={"available": False},
        )

    def get_disk_metrics(self, path: str = ".") -> ResourceMetrics:
        """Récupère les métriques disque."""
        try:
            if self._has_psutil:
                import psutil
                disk = psutil.disk_usage(path)

                usage = disk.percent
                available = disk.free
                total = disk.total

                details = {
                    "path": os.path.abspath(path),
                    "used_gb": round(disk.used / (1024**3), 2),
                    "free_gb": round(disk.free / (1024**3), 2),
                    "total_gb": round(disk.total / (1024**3), 2),
                }
            else:
                # Fallback basique
                import shutil
                total, used, free = shutil.disk_usage(path)
                usage = (used / total) * 100
                available = free
                details = {
                    "path": os.path.abspath(path),
                    "free_gb": round(free / (1024**3), 2),
                }

            status = self.thresholds.get_status(ResourceType.DISK, usage)

            return ResourceMetrics(
                resource_type=ResourceType.DISK,
                usage_percent=usage,
                available=available,
                total=total,
                status=status,
                details=details,
            )
        except Exception as e:
            logger.error(f"Erreur disk metrics: {e}")
            return ResourceMetrics(
                resource_type=ResourceType.DISK,
                usage_percent=0,
                available=0,
                total=0,
                status=HealthStatus.UNKNOWN,
            )

    def get_system_info(self) -> Dict[str, Any]:
        """Récupère les informations système."""
        info = {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "platform_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "hostname": platform.node(),
        }

        if self._has_psutil:
            import psutil
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.now() - boot_time
            info["uptime_hours"] = round(uptime.total_seconds() / 3600, 2)
            info["boot_time"] = boot_time.isoformat()

        return info

    def check_health(self) -> HealthSnapshot:
        """
        Effectue un check de santé complet.

        Returns:
            HealthSnapshot avec toutes les métriques
        """
        metrics = {
            ResourceType.CPU: self.get_cpu_metrics(),
            ResourceType.MEMORY: self.get_memory_metrics(),
            ResourceType.GPU: self.get_gpu_metrics(),
            ResourceType.DISK: self.get_disk_metrics(),
        }

        # Déterminer le status global
        statuses = [m.status for m in metrics.values() if m.status != HealthStatus.UNKNOWN]

        if any(s == HealthStatus.CRITICAL for s in statuses):
            overall = HealthStatus.CRITICAL
        elif any(s == HealthStatus.WARNING for s in statuses):
            overall = HealthStatus.WARNING
        elif statuses:
            overall = HealthStatus.HEALTHY
        else:
            overall = HealthStatus.UNKNOWN

        # Générer les alertes
        alerts = []
        for resource, metric in metrics.items():
            if metric.status == HealthStatus.CRITICAL:
                alert = f"CRITICAL: {resource.value} à {metric.usage_percent:.1f}%"
                alerts.append(alert)
                if self.on_alert:
                    self.on_alert(alert, HealthStatus.CRITICAL)
            elif metric.status == HealthStatus.WARNING:
                alert = f"WARNING: {resource.value} à {metric.usage_percent:.1f}%"
                alerts.append(alert)
                if self.on_alert:
                    self.on_alert(alert, HealthStatus.WARNING)

        snapshot = HealthSnapshot(
            timestamp=datetime.now(),
            overall_status=overall,
            metrics=metrics,
            alerts=alerts,
            system_info=self.get_system_info(),
        )

        # Ajouter à l'historique
        with self._lock:
            self._history.append(snapshot)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        return snapshot

    def get_history(self, last_n: int = 100) -> List[HealthSnapshot]:
        """Retourne les derniers snapshots."""
        with self._lock:
            return list(self._history[-last_n:])

    def get_average_usage(
        self,
        resource: ResourceType,
        duration_minutes: int = 5
    ) -> float:
        """Calcule l'usage moyen sur une période."""
        cutoff = datetime.now() - timedelta(minutes=duration_minutes)

        with self._lock:
            recent = [
                s.metrics[resource].usage_percent
                for s in self._history
                if s.timestamp >= cutoff and resource in s.metrics
            ]

        if not recent:
            return 0.0

        return sum(recent) / len(recent)

    def start_monitoring(self, interval: float = 10.0) -> None:
        """
        Démarre la surveillance continue.

        Args:
            interval: Intervalle entre les checks en secondes
        """
        if self._monitoring:
            logger.warning("Monitoring déjà actif")
            return

        self._monitoring = True

        def monitor_loop():
            while self._monitoring:
                try:
                    self.check_health()
                except Exception as e:
                    logger.error(f"Erreur monitoring: {e}")
                time.sleep(interval)

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info(f"Monitoring démarré (interval={interval}s)")

    def stop_monitoring(self) -> None:
        """Arrête la surveillance continue."""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
            self._monitor_thread = None
        logger.info("Monitoring arrêté")

    def is_healthy(self) -> bool:
        """Vérifie si le système est en bonne santé."""
        snapshot = self.check_health()
        return snapshot.overall_status == HealthStatus.HEALTHY

    def wait_for_resources(
        self,
        memory_threshold: float = 80.0,
        timeout: float = 60.0,
        check_interval: float = 1.0
    ) -> bool:
        """
        Attend que les ressources soient disponibles.

        Utile avant de lancer une opération lourde.

        Args:
            memory_threshold: Seuil de mémoire acceptable
            timeout: Timeout en secondes
            check_interval: Intervalle de vérification

        Returns:
            True si ressources disponibles, False si timeout
        """
        start = time.time()

        while time.time() - start < timeout:
            mem = self.get_memory_metrics()

            if mem.usage_percent < memory_threshold:
                return True

            logger.debug(f"Attente ressources: RAM à {mem.usage_percent:.1f}%")
            gc.collect()
            time.sleep(check_interval)

        logger.warning(f"Timeout attente ressources après {timeout}s")
        return False

    def summary(self) -> str:
        """Retourne un résumé textuel de l'état."""
        snapshot = self.check_health()

        lines = [
            "=== Health Monitor ===",
            f"Status: {snapshot.overall_status.value.upper()}",
            f"Time: {snapshot.timestamp.strftime('%H:%M:%S')}",
            "",
        ]

        for resource, metric in snapshot.metrics.items():
            status_icon = {
                HealthStatus.HEALTHY: "✅",
                HealthStatus.WARNING: "⚠️",
                HealthStatus.CRITICAL: "🔴",
                HealthStatus.UNKNOWN: "❓",
            }.get(metric.status, "?")

            lines.append(f"{status_icon} {resource.value.upper()}: {metric.usage_percent:.1f}%")

        if snapshot.alerts:
            lines.append("")
            lines.append("Alerts:")
            for alert in snapshot.alerts:
                lines.append(f"  - {alert}")

        return "\n".join(lines)


# Singleton global
_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    """Retourne le moniteur de santé singleton."""
    global _monitor
    if _monitor is None:
        _monitor = HealthMonitor()
    return _monitor


def check_system_health() -> HealthSnapshot:
    """Raccourci pour vérifier la santé système."""
    return get_health_monitor().check_health()


def is_system_healthy() -> bool:
    """Raccourci pour vérifier si le système est sain."""
    return get_health_monitor().is_healthy()


__all__ = [
    "HealthStatus",
    "ResourceType",
    "ResourceMetrics",
    "HealthThresholds",
    "HealthSnapshot",
    "HealthMonitor",
    "get_health_monitor",
    "check_system_health",
    "is_system_healthy",
]
