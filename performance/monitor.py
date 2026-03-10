"""
Module-ID: performance.monitor

Purpose: Monitoring temps réel système (CPU, mémoire, I/O, GPU) pendant exécution.

Role in pipeline: observability

Key components: PerformanceMonitor, ResourceTracker, psutil wrapper, Rich display

Inputs: None (reads system metrics)

Outputs: Stats {cpu_pct, mem_mb, io_r_mb, gpu_mem_mb}, timeline

Dependencies: psutil, threading, time, rich (optionnel)

Conventions: Background thread safe; thread-safe stats dict; 1s interval.

Read-if: Modification metrics collection ou refresh interval.

Skip-if: Vous appelez monitor.get_stats().
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# psutil pour métriques système
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    logger.warning("psutil non disponible - monitoring limité")

# rich pour affichage console
try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    logger.warning("rich non disponible - affichage console basique")


@dataclass
class ResourceSnapshot:
    """Snapshot des ressources système à un instant t."""
    timestamp: float
    cpu_percent: float
    memory_used_gb: float
    memory_available_gb: float
    memory_percent: float
    disk_read_mb: float = 0.0
    disk_write_mb: float = 0.0
    gpu_memory_used_gb: Optional[float] = None
    gpu_utilization: Optional[float] = None


@dataclass
class ResourceStats:
    """Statistiques agrégées des ressources."""
    duration_seconds: float
    cpu_avg: float
    cpu_max: float
    memory_avg_gb: float
    memory_max_gb: float
    memory_peak_percent: float
    samples_count: int
    gpu_memory_max_gb: Optional[float] = None
    gpu_utilization_avg: Optional[float] = None


class ResourceTracker:
    """
    Tracker de ressources en arrière-plan.

    Capture les métriques CPU/RAM/GPU à intervalles réguliers.

    Example:
        >>> tracker = ResourceTracker(interval=0.5)
        >>> tracker.start()
        >>>
        >>> # ... exécution du backtest ...
        >>>
        >>> stats = tracker.stop()
        >>> print(f"CPU max: {stats.cpu_max}%")
        >>> print(f"RAM max: {stats.memory_max_gb:.2f} GB")
    """

    def __init__(self, interval: float = 1.0):
        """
        Initialise le tracker.

        Args:
            interval: Intervalle de sampling en secondes
        """
        self.interval = interval
        self._snapshots: List[ResourceSnapshot] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._start_time: float = 0.0

        # Compteurs IO disque de base
        self._disk_io_start = None
        if HAS_PSUTIL:
            try:
                self._disk_io_start = psutil.disk_io_counters()
            except Exception:
                pass

    def _take_snapshot(self) -> ResourceSnapshot:
        """Capture un snapshot des ressources."""
        timestamp = time.time()

        if HAS_PSUTIL:
            cpu_percent = psutil.cpu_percent(interval=0)
            mem = psutil.virtual_memory()

            # IO disque
            disk_read_mb = 0.0
            disk_write_mb = 0.0
            try:
                io = psutil.disk_io_counters()
                if self._disk_io_start:
                    disk_read_mb = (
                        io.read_bytes - self._disk_io_start.read_bytes
                    ) / (1024**2)
                    disk_write_mb = (
                        io.write_bytes - self._disk_io_start.write_bytes
                    ) / (1024**2)
            except Exception:
                pass

            return ResourceSnapshot(
                timestamp=timestamp,
                cpu_percent=cpu_percent,
                memory_used_gb=mem.used / (1024**3),
                memory_available_gb=mem.available / (1024**3),
                memory_percent=mem.percent,
                disk_read_mb=disk_read_mb,
                disk_write_mb=disk_write_mb,
            )
        else:
            # Fallback sans psutil
            return ResourceSnapshot(
                timestamp=timestamp,
                cpu_percent=0.0,
                memory_used_gb=0.0,
                memory_available_gb=0.0,
                memory_percent=0.0,
            )

    def _sampling_loop(self):
        """Boucle de sampling en arrière-plan."""
        while self._running:
            snapshot = self._take_snapshot()
            self._snapshots.append(snapshot)
            time.sleep(self.interval)

    def start(self):
        """Démarre le tracking."""
        if self._running:
            return

        self._running = True
        self._start_time = time.time()
        self._snapshots = []

        self._thread = threading.Thread(
            target=self._sampling_loop,
            daemon=True,
        )
        self._thread.start()

        logger.debug("ResourceTracker démarré")

    def stop(self) -> ResourceStats:
        """
        Arrête le tracking et retourne les statistiques.

        Returns:
            ResourceStats avec métriques agrégées
        """
        self._running = False

        if self._thread:
            self._thread.join(timeout=2.0)

        # Calculer les stats
        duration = time.time() - self._start_time

        if not self._snapshots:
            return ResourceStats(
                duration_seconds=duration,
                cpu_avg=0.0,
                cpu_max=0.0,
                memory_avg_gb=0.0,
                memory_max_gb=0.0,
                memory_peak_percent=0.0,
                samples_count=0,
            )

        cpu_values = [s.cpu_percent for s in self._snapshots]
        mem_values = [s.memory_used_gb for s in self._snapshots]
        mem_pct_values = [s.memory_percent for s in self._snapshots]

        return ResourceStats(
            duration_seconds=duration,
            cpu_avg=sum(cpu_values) / len(cpu_values),
            cpu_max=max(cpu_values),
            memory_avg_gb=sum(mem_values) / len(mem_values),
            memory_max_gb=max(mem_values),
            memory_peak_percent=max(mem_pct_values),
            samples_count=len(self._snapshots),
        )

    def get_current(self) -> ResourceSnapshot:
        """Retourne le snapshot actuel."""
        return self._take_snapshot()

    def get_history(self) -> List[ResourceSnapshot]:
        """Retourne l'historique des snapshots."""
        return self._snapshots.copy()


class PerformanceMonitor:
    """
    Moniteur de performance avec affichage temps réel.

    Utilise rich pour afficher une interface console avec:
    - Barre de progression
    - Métriques CPU/RAM en temps réel
    - Statistiques de performance

    Example:
        >>> with PerformanceMonitor("Backtest") as monitor:
        ...     for i, params in enumerate(param_grid):
        ...         run_backtest(params)
        ...         monitor.update(i + 1, len(param_grid))
    """

    def __init__(
        self,
        title: str = "Backtest",
        show_live: bool = True,
        refresh_rate: int = 4,
    ):
        """
        Initialise le moniteur.

        Args:
            title: Titre de l'opération
            show_live: Afficher le dashboard live
            refresh_rate: Rafraîchissements par seconde
        """
        self.title = title
        self.show_live = show_live and HAS_RICH
        self.refresh_rate = refresh_rate

        self._tracker = ResourceTracker(interval=1.0 / refresh_rate)
        self._start_time: float = 0.0
        self._progress: int = 0
        self._total: int = 0
        self._status: str = "En attente..."
        self._live: Optional[Any] = None
        self._console: Optional[Any] = None

        if HAS_RICH:
            self._console = Console()

    def _build_display(self) -> Any:
        """Construit l'affichage rich."""
        if not HAS_RICH:
            return None

        # Stats actuelles
        snapshot = self._tracker.get_current()
        elapsed = time.time() - self._start_time

        # Table des métriques
        table = Table(title=f"📊 {self.title}", show_header=True)
        table.add_column("Métrique", style="cyan")
        table.add_column("Valeur", style="green")

        table.add_row("⏱️  Temps écoulé", f"{elapsed:.1f}s")
        table.add_row("📈 Progression", f"{self._progress}/{self._total}")
        table.add_row("💻 CPU", f"{snapshot.cpu_percent:.1f}%")
        table.add_row("🧠 RAM utilisée", f"{snapshot.memory_used_gb:.2f} GB")
        table.add_row("📊 RAM %", f"{snapshot.memory_percent:.1f}%")
        table.add_row("📝 Status", self._status)

        # Calcul ETA
        if self._progress > 0 and self._total > 0:
            avg_time = elapsed / self._progress
            remaining = (self._total - self._progress) * avg_time
            table.add_row("⏳ ETA", f"{remaining:.0f}s")

        return Panel(table, border_style="blue")

    def __enter__(self):
        """Context manager entry."""
        self._start_time = time.time()
        self._tracker.start()

        if self.show_live and HAS_RICH:
            self._live = Live(
                self._build_display(),
                console=self._console,
                refresh_per_second=self.refresh_rate,
            )
            self._live.__enter__()

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self._live:
            self._live.__exit__(exc_type, exc_val, exc_tb)

        self._tracker.stop()
        return False

    def update(self, progress: int, total: int, status: str = ""):
        """
        Met à jour la progression.

        Args:
            progress: Nombre de tâches complétées
            total: Nombre total de tâches
            status: Message de status optionnel
        """
        self._progress = progress
        self._total = total
        if status:
            self._status = status
        else:
            self._status = f"Traitement {progress}/{total}..."

        if self._live:
            self._live.update(self._build_display())

    def set_status(self, status: str):
        """Met à jour le message de status."""
        self._status = status
        if self._live:
            self._live.update(self._build_display())

    def get_stats(self) -> ResourceStats:
        """Retourne les statistiques de ressources."""
        return self._tracker.stop()


class ProgressBar:
    """
    Barre de progression simple avec rich.

    Example:
        >>> with ProgressBar("Running", total=100) as bar:
        ...     for _ in range(100):
        ...         bar.advance()
    """

    def __init__(self, description: str = "Processing", total: int = 100):
        self.description = description
        self.total = total
        self._progress: Optional[Any] = None
        self._task_id: Optional[int] = None

    def __enter__(self):
        if HAS_RICH:
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
            )
            self._progress.__enter__()
            self._task_id = self._progress.add_task(
                self.description, total=self.total
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._progress:
            self._progress.__exit__(exc_type, exc_val, exc_tb)
        return False

    def advance(self, amount: int = 1):
        """Avance la progression."""
        if self._progress and self._task_id is not None:
            self._progress.update(self._task_id, advance=amount)

    def update(self, completed: int):
        """Met à jour la progression à une valeur spécifique."""
        if self._progress and self._task_id is not None:
            self._progress.update(self._task_id, completed=completed)


# ======================== Fonctions utilitaires ========================

def print_system_info():
    """Affiche les informations système."""
    if HAS_RICH:
        console = Console()

        table = Table(title="🖥️ Informations Système")
        table.add_column("Composant", style="cyan")
        table.add_column("Valeur", style="green")

        if HAS_PSUTIL:
            table.add_row("CPU (cœurs)", str(psutil.cpu_count()))
            cpu_logical = psutil.cpu_count(logical=True)
            table.add_row("CPU (logiques)", str(cpu_logical))

            mem = psutil.virtual_memory()
            table.add_row("RAM totale", f"{mem.total / (1024**3):.1f} GB")
            mem_available_gb = mem.available / (1024**3)
            table.add_row("RAM disponible", f"{mem_available_gb:.1f} GB")

            # psutil.disk_usage("/") plante sur Windows (chemin sans drive).
            # Utiliser l'ancre du CWD.
            try:
                root_path = Path.cwd().anchor or os.path.abspath(os.sep)
                disk = psutil.disk_usage(root_path)
                disk_free_gb = disk.free / (1024**3)
                table.add_row("Disque disponible", f"{disk_free_gb:.1f} GB")
            except Exception:
                table.add_row("Disque disponible", "N/A")
        else:
            table.add_row("psutil", "Non disponible")

        console.print(table)
    else:
        print("=== Informations Système ===")
        if HAS_PSUTIL:
            print(f"CPU: {psutil.cpu_count()} cœurs")
            mem = psutil.virtual_memory()
            ram_total_gb = mem.total / (1024**3)
            ram_available_gb = mem.available / (1024**3)
            print(
                f"RAM: {ram_total_gb:.1f} GB total, "
                f"{ram_available_gb:.1f} GB disponible"
            )


def get_system_resources() -> Dict[str, Any]:
    """Retourne un dict avec les ressources système."""
    resources = {
        "psutil_available": HAS_PSUTIL,
        "rich_available": HAS_RICH,
    }

    if HAS_PSUTIL:
        resources["cpu_count"] = psutil.cpu_count()
        resources["cpu_count_logical"] = psutil.cpu_count(logical=True)

        mem = psutil.virtual_memory()
        resources["memory_total_gb"] = mem.total / (1024**3)
        resources["memory_available_gb"] = mem.available / (1024**3)
        resources["memory_percent"] = mem.percent

        resources["cpu_percent"] = psutil.cpu_percent(interval=0.1)

    return resources
