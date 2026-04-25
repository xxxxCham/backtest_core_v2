"""Module-ID: backtest.results_organizer

Purpose: Organiser automatiquement les résultats de backtest en structure hiérarchique claire.

Role in pipeline: organization / archiving

Key components: organize_results, create_category_structure, archive_old_results

Inputs: Répertoire backtest_results

Outputs: Structure hiérarchique organisée par catégorie/stratégie/performance

Dependencies: pathlib, shutil, json

Conventions: Organisation: backtest_results/{category}/{strategy}/{symbol_tf}/{run_id}

Read-if: Organisation ou archivage des résultats.

Skip-if: Structure flat convient à votre usage.
"""

import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ajouter le répertoire racine au PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtest.report_generator import classify_result
from backtest.result_store import (
    get_results_archive_dir,
    get_results_organized_dir,
    get_results_root_dir,
)
from utils.log import get_logger

logger = get_logger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

CATEGORIES = {
    "excellent": "🏆_Excellent",
    "good": "✅_Good",
    "mediocre": "📊_Mediocre",
    "unprofitable": "❌_Unprofitable",
    "failed": "❌_Failed",  # Alias pour unprofitable
    "ruined": "💀_Ruined",
    "insufficient_data": "⚠️_Insufficient_Data",
}

ARCHIVE_AFTER_DAYS = 90  # Archiver résultats > 90 jours


# =============================================================================
# FONCTIONS D'ORGANISATION
# =============================================================================


def organize_results(
    results_dir: Path | None = None,
    organized_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Organise les résultats de backtest en structure hiérarchique.

    Structure cible:
        backtest_results_organized/
        ├── 🏆_Excellent/
        │   ├── ema_cross/
        │   │   └── BTCUSDC_1h/
        │   │       └── run_20260103_abc123/
        │   └── rsi_reversal/
        ├── ✅_Good/
        ├── 📊_Mediocre/
        ├── ❌_Unprofitable/
        └── 💀_Ruined/

    Args:
        results_dir: Répertoire source des résultats
        organized_dir: Répertoire destination (défaut: backtest_results_organized)
        dry_run: Si True, affiche les actions sans les exécuter

    Returns:
        Dict compteur par catégorie

    Example:
        >>> stats = organize_results(dry_run=True)
        >>> print(stats)
        {"excellent": 5, "good": 12, ...}

    """
    results_dir = get_results_root_dir(results_dir)
    if organized_dir is None:
        organized_dir = get_results_organized_dir(results_dir)

    # Charger l'index
    index_path = results_dir / "index.json"
    if not index_path.exists():
        logger.error(f"Index introuvable: {index_path}")
        return {}

    with open(index_path) as f:
        index_data = json.load(f)

    results = list(index_data.values())
    logger.info(f"📊 {len(results)} résultats à organiser")

    stats = dict.fromkeys(CATEGORIES.keys(), 0)

    for result in results:
        run_id = result.get("run_id", "unknown")
        metrics = result.get("metrics", {})
        strategy = result.get("strategy", "unknown")
        symbol = result.get("symbol", "unknown")
        timeframe = result.get("timeframe", "unknown")
        timestamp = result.get("timestamp", "")

        # Classifier
        category, _ = classify_result(metrics)
        stats[category] += 1

        # Construire chemins
        category_name = CATEGORIES.get(category, "Unknown")
        symbol_tf = f"{symbol}_{timeframe}"

        # Extraire date du timestamp
        try:
            ts_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            date_str = ts_dt.strftime("%Y%m%d_%H%M%S")
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning(f"Timestamp invalide: {timestamp}, erreur: {e}")
            date_str = "unknown"

        run_folder_name = f"{date_str}_{run_id[:8]}"

        source_path = results_dir / run_id
        target_path = organized_dir / category_name / strategy / symbol_tf / run_folder_name

        # Copier ou afficher
        if dry_run:
            logger.info(f"[DRY-RUN] {source_path.name} → {target_path}")
        elif source_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists():
                shutil.rmtree(target_path)
            shutil.copytree(source_path, target_path)
            logger.debug(f"✅ Copié: {run_id} → {target_path}")
        else:
            logger.warning(f"⚠️ Source introuvable: {source_path}")

    # Créer README dans chaque catégorie
    if not dry_run:
        create_category_readmes(organized_dir, stats)

    # Afficher statistiques
    logger.info("\n=== Statistiques d'organisation ===")
    for category, count in stats.items():
        emoji_name = CATEGORIES.get(category, category)
        logger.info(f"{emoji_name}: {count} résultats")

    return stats


def create_category_readmes(organized_dir: Path, stats: dict[str, int]):
    """Crée des fichiers README.md dans chaque catégorie.

    Args:
        organized_dir: Répertoire organisé
        stats: Statistiques par catégorie

    """
    descriptions = {
        "excellent": "🏆 Configurations exceptionnelles (Return > 5% ET Sharpe > 2.0). **Prêtes pour production.**",
        "good": "✅ Bonnes configurations (Return > 5% ET Sharpe > 1.0). À valider sur d'autres timeframes/symboles.",
        "mediocre": "📊 Configurations rentables mais médiocres. Nécessitent optimisation.",
        "unprofitable": "❌ Configurations non rentables. À analyser pour comprendre les échecs.",
        "ruined": "💀 **DANGER** : Ces configurations ont mené à la ruine du compte. À éviter absolument.",
        "insufficient_data": "⚠️ Résultats avec trop peu de trades (< 10). Données insuffisantes pour juger.",
    }

    for category, category_name in CATEGORIES.items():
        category_path = organized_dir / category_name
        if not category_path.exists():
            continue

        readme_path = category_path / "README.md"
        count = stats.get(category, 0)

        content = [
            f"# {category_name}",
            "",
            descriptions.get(category, "Catégorie de résultats."),
            "",
            f"**Nombre de résultats:** {count}",
            "",
            "## Structure",
            "",
            "Les résultats sont organisés par :",
            "1. **Stratégie** (ex: ema_cross, rsi_reversal)",
            "2. **Symbole + Timeframe** (ex: BTCUSDC_1h)",
            "3. **Date + Run ID** (ex: 20260103_123456_abc12345)",
            "",
            "## Fichiers dans chaque résultat",
            "",
            "- `metadata.json` : Paramètres et métriques complètes",
            "- `equity.parquet` : Courbe d'équité (si disponible)",
            "- `trades.parquet` : Liste détaillée des trades (si disponible)",
            "",
            "---",
            f"*Généré le {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        ]

        readme_path.write_text("\n".join(content), encoding="utf-8")
        logger.debug(f"📄 README créé: {readme_path}")


def archive_old_results(
    results_dir: Path | None = None,
    archive_dir: Path | None = None,
    days_threshold: int = ARCHIVE_AFTER_DAYS,
    dry_run: bool = False,
) -> int:
    """Archive les résultats anciens (> days_threshold jours).

    Args:
        results_dir: Répertoire des résultats
        archive_dir: Répertoire d'archivage (défaut: backtest_results_archive)
        days_threshold: Seuil en jours pour archivage
        dry_run: Si True, affiche sans archiver

    Returns:
        Nombre de résultats archivés

    Example:
        >>> count = archive_old_results(days_threshold=90, dry_run=True)
        >>> print(f"{count} résultats à archiver")

    """
    results_dir = get_results_root_dir(results_dir)
    if archive_dir is None:
        archive_dir = get_results_archive_dir(results_dir)

    # Charger index
    index_path = results_dir / "index.json"
    if not index_path.exists():
        logger.error(f"Index introuvable: {index_path}")
        return 0

    with open(index_path) as f:
        index_data = json.load(f)

    cutoff_date = datetime.now() - timedelta(days=days_threshold)
    archived_count = 0

    for run_id, result in index_data.items():
        timestamp_str = result.get("timestamp", "")
        try:
            ts_dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning(f"⚠️ Timestamp invalide pour {run_id}: {timestamp_str}, erreur: {e}")
            continue

        if ts_dt < cutoff_date:
            source_path = results_dir / run_id
            target_path = archive_dir / run_id

            if dry_run:
                logger.info(f"[DRY-RUN] Archiver: {run_id} ({ts_dt.strftime('%Y-%m-%d')})")
            elif source_path.exists():
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source_path), str(target_path))
                logger.debug(f"📦 Archivé: {run_id}")

            archived_count += 1

    logger.info(f"📦 {archived_count} résultats archivés (> {days_threshold} jours)")
    return archived_count


# =============================================================================
# SCRIPT PRINCIPAL
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Organiser et archiver les résultats de backtest",
    )
    parser.add_argument(
        "--organize",
        action="store_true",
        help="Organiser les résultats par catégorie",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        help="Archiver les résultats anciens",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mode simulation (ne modifie rien)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=ARCHIVE_AFTER_DAYS,
        help=f"Seuil en jours pour archivage (défaut: {ARCHIVE_AFTER_DAYS})",
    )

    args = parser.parse_args()

    if args.organize:
        print("=== Organisation des résultats ===\n")
        stats = organize_results(dry_run=args.dry_run)
        print(f"\n✅ Organisation {'simulée' if args.dry_run else 'terminée'}")

    if args.archive:
        print("\n=== Archivage des résultats anciens ===\n")
        count = archive_old_results(days_threshold=args.days, dry_run=args.dry_run)
        print(f"\n📦 {count} résultats {'à archiver' if args.dry_run else 'archivés'}")

    if not args.organize and not args.archive:
        parser.print_help()
