"""Script de diagnostic pour vérifier l'activité d'un sweep en cours.

Usage:
    python utils/diagnose_sweep_activity.py

Vérifie:
- Processus Python actifs (workers)
- Utilisation CPU/RAM par processus
- Logs récents du backtest
- Vitesse d'écriture dans les fichiers de résultats (si actifs)
"""

import sys
import time
from pathlib import Path

# Ajouter le répertoire parent au PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
    print("⚠️  psutil non disponible. Installez-le avec: pip install psutil")


def find_backtest_processes():
    """Trouve tous les processus Python liés au backtest."""
    if not HAS_PSUTIL:
        return []

    backtest_procs = []
    for proc in psutil.process_iter(["pid", "name", "cmdline", "cpu_percent", "memory_percent"]):
        try:
            if proc.info["name"] and "python" in proc.info["name"].lower():
                cmdline = proc.info.get("cmdline", [])
                if cmdline and any(
                    "backtest" in str(arg).lower() or "streamlit" in str(arg).lower() for arg in cmdline
                ):
                    backtest_procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return backtest_procs


def get_system_stats():
    """Récupère les stats système globales."""
    if not HAS_PSUTIL:
        return None

    cpu_percent = psutil.cpu_percent(interval=1, percpu=False)
    mem = psutil.virtual_memory()
    return {
        "cpu_percent": cpu_percent,
        "ram_used_gb": mem.used / (1024**3),
        "ram_total_gb": mem.total / (1024**3),
        "ram_percent": mem.percent,
    }


def check_log_activity():
    """Vérifie l'activité dans les logs récents."""
    log_files = [
        "logs/backtest.log",
        "logs/sweep.log",
    ]

    for log_file in log_files:
        log_path = Path(__file__).parent.parent / log_file
        if log_path.exists():
            stat = log_path.stat()
            modified_ago = time.time() - stat.st_mtime
            size_mb = stat.st_size / (1024**2)
            print(f"\n📄 {log_file}")
            print(f"   Taille: {size_mb:.2f} MB")
            print(f"   Modifié: il y a {modified_ago:.0f}s")
            if modified_ago < 60:
                print("   ✅ Activité récente détectée")
            elif modified_ago < 300:
                print(f"   ⚠️  Pas d'activité depuis {modified_ago / 60:.0f} minutes")
            else:
                print(f"   ❌ Inactif depuis {modified_ago / 60:.0f} minutes")


def check_result_files():
    """Vérifie l'écriture dans les fichiers de résultats."""
    results_dir = Path(__file__).parent.parent / "backtest_results"
    if not results_dir.exists():
        print("\n⚠️  Dossier backtest_results non trouvé")
        return

    recent_files = []
    now = time.time()
    for file in results_dir.rglob("*.json"):
        mtime = file.stat().st_mtime
        age = now - mtime
        if age < 3600:  # Modifié dans la dernière heure
            recent_files.append((file, age))

    if recent_files:
        print(f"\n📊 {len(recent_files)} fichiers de résultats modifiés récemment:")
        for file, age in sorted(recent_files, key=lambda x: x[1])[:5]:
            print(f"   • {file.name} (il y a {age / 60:.0f}m)")
    else:
        print("\n❌ Aucun fichier de résultats récent (< 1h)")


def main():
    """Point d'entrée principal."""
    print("=" * 70)
    print("🔍 DIAGNOSTIC D'ACTIVITÉ SWEEP")
    print("=" * 70)

    # Stats système globales
    stats = get_system_stats()
    if stats:
        print("\n🖥️  Système:")
        print(f"   CPU: {stats['cpu_percent']:.1f}%")
        print(f"   RAM: {stats['ram_used_gb']:.1f}/{stats['ram_total_gb']:.1f} GB ({stats['ram_percent']:.1f}%)")

    # Processus Python actifs
    procs = find_backtest_processes()
    if procs:
        print(f"\n🐍 Processus Python backtest actifs: {len(procs)}")
        total_cpu = 0
        total_mem = 0
        for proc in procs:
            try:
                cpu = proc.cpu_percent(interval=0.1)
                mem = proc.memory_percent()
                total_cpu += cpu
                total_mem += mem
                cmdline_str = " ".join(proc.cmdline()[:3]) if proc.cmdline() else "N/A"
                print(f"   PID {proc.pid}: CPU {cpu:.1f}% | RAM {mem:.1f}% | {cmdline_str[:60]}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        print(f"\n   Total: CPU {total_cpu:.1f}% | RAM {total_mem:.1f}%")

        if total_cpu > 5:
            print("   ✅ Activité CPU détectée - Le sweep est probablement actif")
        else:
            print("   ⚠️  CPU faible - Le sweep pourrait être bloqué ou en attente")
    else:
        print("\n❌ Aucun processus Python backtest trouvé")

    # Vérifier logs
    check_log_activity()

    # Vérifier fichiers de résultats
    check_result_files()

    print("\n" + "=" * 70)
    print("Diagnostic terminé")
    print("=" * 70)

    # Recommandations
    if procs and stats and stats["cpu_percent"] < 10:
        print("\n💡 Recommandation: CPU faible détecté.")
        print("   Le sweep utilise peut-être peu de workers ou est bloqué.")
        print("   Vérifiez les logs pour d'éventuelles erreurs.")


if __name__ == "__main__":
    main()
