"""
Module-ID: catalog.runner

Purpose: Orchestrateur principal du catalogue — charge config, génère, filtre, exporte.

Usage CLI:
    python -m catalog.runner --config catalog/example_config.json [--dry-run]

Usage API:
    from catalog.runner import run_catalog
    result = run_catalog("catalog/example_config.json")
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from catalog.builder_export import to_json_proposal, to_text_v1
from catalog.chainer import generate_catalog
from catalog.gating import run_gating_batch
from catalog.models import CatalogConfig, CatalogResult, Variant

logger = logging.getLogger(__name__)


def run_catalog(
    config_path: str,
    df: Optional[pd.DataFrame] = None,
    dry_run: bool = False,
) -> CatalogResult:
    """
    Pipeline complet de génération de catalogue.

    1. Charger CatalogConfig depuis JSON
    2. generate_catalog(config) → variants groupés en batches
    3. Gating optionnel (si activé et df fourni)
    4. Export artefacts (batch JSON + index + meta)

    Args:
        config_path: Chemin vers le fichier de configuration JSON
        df: DataFrame OHLCV optionnel pour le gating
        dry_run: Si True, génère mais n'écrit pas sur disque

    Returns:
        CatalogResult avec statistiques et variants approuvés
    """
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config introuvable: {config_file}")

    config = CatalogConfig.load(config_file)

    # Générer un run_id si absent
    if not config.run_id:
        config.run_id = datetime.now(timezone.utc).strftime("cat_%Y%m%d_%H%M%S")

    logger.info(
        "Catalog run start: run_id=%s target=%d seed=%d",
        config.run_id, config.n_variants_target, config.seed,
    )

    # --- 1. Génération + sanity ---
    result = generate_catalog(config)

    logger.info(
        "Generation done: generated=%d after_sanity=%d rejected=%d",
        result.total_generated, result.total_after_sanity, len(result.rejections),
    )

    # --- 2. Gating optionnel ---
    if config.gating.enabled and df is not None and len(result.variants) > 0:
        logger.info("Gating enabled — running mini-backtests on %d variants", len(result.variants))
        gated = _apply_gating(result.variants, df, config)
        gating_passed = [v for v, passed, _ in gated if passed]
        gating_failed = [
            {"variant_id": v.variant_id, "metrics": m, "stage": "gating"}
            for v, passed, m in gated if not passed
        ]
        result.variants = gating_passed
        result.total_after_gating = len(gating_passed)
        result.rejections.extend(gating_failed)
        logger.info("Gating done: passed=%d failed=%d", len(gating_passed), len(gating_failed))
    else:
        result.total_after_gating = len(result.variants)

    # Recalculer batches
    result.n_batches = (len(result.variants) + config.batch_size - 1) // config.batch_size if result.variants else 0

    # --- 3. Export ---
    if not dry_run:
        _write_artifacts(result, config)
    else:
        logger.info("Dry-run mode — no artifacts written to disk")

    logger.info(
        "Catalog run complete: run_id=%s variants=%d batches=%d",
        result.run_id, len(result.variants), result.n_batches,
    )

    return result


def _apply_gating(
    variants: List[Variant],
    df: pd.DataFrame,
    config: CatalogConfig,
) -> list:
    """Applique le gating par batch."""
    from catalog.gating import run_gating_batch
    return run_gating_batch(variants, df, config.gating)


def _write_artifacts(result: CatalogResult, config: CatalogConfig) -> None:
    """Écrit les artefacts du catalogue sur disque."""
    output_dir = Path(config.output_dir) / result.run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Batches
    batch_size = config.batch_size
    batches_dir = output_dir / "batches"
    batches_dir.mkdir(exist_ok=True)

    batch_manifests: List[Dict[str, Any]] = []

    for batch_idx in range(result.n_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, len(result.variants))
        batch_variants = result.variants[start:end]

        batch_data = {
            "batch_id": batch_idx,
            "n_variants": len(batch_variants),
            "variants": [v.to_dict() for v in batch_variants],
        }

        batch_file = batches_dir / f"batch_{batch_idx:04d}.json"
        batch_file.write_text(
            json.dumps(batch_data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        batch_manifests.append({
            "batch_id": batch_idx,
            "file": str(batch_file.relative_to(output_dir)),
            "n_variants": len(batch_variants),
        })

    # Index
    index = {
        "run_id": result.run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_generated": result.total_generated,
        "total_after_sanity": result.total_after_sanity,
        "total_after_gating": result.total_after_gating,
        "n_batches": result.n_batches,
        "batches": batch_manifests,
        "variant_ids": [v.variant_id for v in result.variants],
    }

    index_file = output_dir / "index.json"
    index_file.write_text(
        json.dumps(index, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Run meta (config + stats rejections)
    meta = {
        "config": config.to_dict(),
        "stats": {
            "total_generated": result.total_generated,
            "total_after_sanity": result.total_after_sanity,
            "total_after_gating": result.total_after_gating,
            "total_rejected": len(result.rejections),
        },
        "rejections_sample": result.rejections[:50],
    }

    meta_file = output_dir / "run_meta.json"
    meta_file.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    logger.info("Artifacts written to %s", output_dir)


def main() -> None:
    """Point d'entrée CLI."""
    parser = argparse.ArgumentParser(
        description="Générateur de catalogue de fiches de stratégies",
        prog="catalog.runner",
    )
    parser.add_argument(
        "--config", "-c",
        required=True,
        help="Chemin vers le fichier de configuration JSON",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Générer sans écrire sur disque",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Activer les logs détaillés",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    result = run_catalog(args.config, dry_run=args.dry_run)

    # Afficher un résumé
    print(f"\n{'='*60}")
    print(f"Catalog Run: {result.run_id}")
    print(f"{'='*60}")
    print(f"  Total generated:    {result.total_generated}")
    print(f"  After sanity:       {result.total_after_sanity}")
    print(f"  After gating:       {result.total_after_gating}")
    print(f"  Batches:            {result.n_batches}")
    print(f"  Rejections:         {len(result.rejections)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
