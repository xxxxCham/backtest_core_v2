"""Module-ID: tools.audit_taxonomy_coverage

Purpose: Compare l'inventaire OHLCV disponible localement à la taxonomie
         `config/token_taxonomy.json` et signaler les écarts.

Cas d'usage:
- Après un run du programme externe `gestionnaire_telechargement_multi-timeframe_clean`
  (qui télécharge de nouveaux tokens depuis Binance), détecter ceux qui n'ont
  pas encore d'entrée dans la taxonomie. Sans ça, ces tokens tombent en
  `decision="MANUAL_REVIEW"` en P3 graduation sans alerte précoce.
- Lister à l'inverse les tokens présents en taxonomie mais sans OHLCV
  (orphelins — token delisté, fichier supprimé, etc.).

Usage:
    python -m tools.audit_taxonomy_coverage
    python -m tools.audit_taxonomy_coverage --json
    python -m tools.audit_taxonomy_coverage --emit-stub

Sortie texte par défaut. `--json` produit une sortie machine-readable.
`--emit-stub` écrit `config/token_taxonomy.unclassified.json` avec
`primary_universe="NEW_LISTING_MISC_HIGH_BETA"` et `liquidity_bucket=null`,
prêt à être édité manuellement puis fusionné dans `token_taxonomy.json`.

Dependencies: data.loader.discover_data_inventory, config.token_taxonomy.

Conventions: Aucune écriture dans token_taxonomy.json (la classification reste
manuelle). Le script informe et propose un template uniquement sur demande
explicite.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def compute_taxonomy_coverage(
    *,
    inventory: dict[str, Any] | None = None,
    taxonomy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare l'inventaire OHLCV à la taxonomie et retourne un rapport structuré.

    Args:
        inventory: Inventaire retourné par data.loader.discover_data_inventory().
                   Si None, scan effectué.
        taxonomy: Taxonomy retournée par config.token_taxonomy.load_token_taxonomy().
                  Si None, chargement effectué.

    Returns:
        {
            "ohlcv_symbol_count": int,
            "taxonomy_symbol_count": int,
            "covered_symbols": list[str],          # OHLCV ∩ taxonomy
            "missing_in_taxonomy": list[str],     # OHLCV \\ taxonomy (à classer)
            "orphan_in_taxonomy": list[str],      # taxonomy \\ OHLCV (orphelins)
            "coverage_pct": float,
        }
    """
    if inventory is None:
        from data.loader import discover_data_inventory

        inventory = discover_data_inventory()
    if taxonomy is None:
        from config.token_taxonomy import load_token_taxonomy

        taxonomy = load_token_taxonomy()

    ohlcv_symbols = {str(symbol).strip().upper() for symbol in (inventory or {}).keys() if str(symbol).strip()}
    taxonomy_tokens = (taxonomy or {}).get("tokens") or {}
    taxonomy_symbols = {str(symbol).strip().upper() for symbol in taxonomy_tokens.keys() if str(symbol).strip()}

    covered = sorted(ohlcv_symbols & taxonomy_symbols)
    missing_in_taxonomy = sorted(ohlcv_symbols - taxonomy_symbols)
    orphan_in_taxonomy = sorted(taxonomy_symbols - ohlcv_symbols)
    coverage_pct = (
        round(len(covered) / len(ohlcv_symbols) * 100.0, 1) if ohlcv_symbols else 0.0
    )
    return {
        "ohlcv_symbol_count": len(ohlcv_symbols),
        "taxonomy_symbol_count": len(taxonomy_symbols),
        "covered_symbols": covered,
        "missing_in_taxonomy": missing_in_taxonomy,
        "orphan_in_taxonomy": orphan_in_taxonomy,
        "coverage_pct": coverage_pct,
    }


def build_unclassified_stub(missing_symbols: list[str]) -> dict[str, Any]:
    """Construit un patch JSON pour les tokens non classés.

    Permet à l'utilisateur d'éditer manuellement primary_universe / liquidity_bucket
    puis de fusionner dans config/token_taxonomy.json.
    """
    stub_tokens: dict[str, dict[str, Any]] = {}
    for symbol in missing_symbols:
        stub_tokens[symbol] = {
            "primary_universe": "NEW_LISTING_MISC_HIGH_BETA",
            "secondary_tags": ["unclassified"],
            "liquidity_bucket": None,
            "_comment": "À classifier manuellement avant fusion dans token_taxonomy.json",
        }
    return {
        "version": "stub",
        "instructions": (
            "Patch généré par tools.audit_taxonomy_coverage. Éditer primary_universe "
            "et liquidity_bucket de chaque token, puis fusionner dans "
            "config/token_taxonomy.json (section 'tokens')."
        ),
        "tokens": stub_tokens,
    }


def render_text_report(report: dict[str, Any]) -> str:
    lines = [
        "=== Audit taxonomie tokens ↔ OHLCV ===",
        f"OHLCV disponibles    : {report['ohlcv_symbol_count']:>4} tokens",
        f"Taxonomie déclarée   : {report['taxonomy_symbol_count']:>4} tokens",
        f"Couverture           : {report['coverage_pct']:.1f}%  "
        f"({len(report['covered_symbols'])} couverts)",
        "",
    ]
    missing = report["missing_in_taxonomy"]
    if missing:
        lines.append(f"⚠️  {len(missing)} token(s) OHLCV absent(s) de la taxonomie (P3 → MANUAL_REVIEW) :")
        for symbol in missing:
            lines.append(f"    - {symbol}")
        lines.append("")
    else:
        lines.append("✅ Aucun token OHLCV manquant en taxonomie.")
        lines.append("")

    orphans = report["orphan_in_taxonomy"]
    if orphans:
        lines.append(f"ℹ️  {len(orphans)} token(s) en taxonomie sans OHLCV (delisting probable) :")
        for symbol in orphans:
            lines.append(f"    - {symbol}")
        lines.append("")
    else:
        lines.append("✅ Aucun orphelin dans la taxonomie.")
    return "\n".join(lines)


def _default_stub_path() -> Path:
    return _project_root() / "config" / "token_taxonomy.unclassified.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools.audit_taxonomy_coverage",
        description=(
            "Compare l'inventaire OHLCV local à config/token_taxonomy.json et "
            "signale les tokens à classer / les orphelins."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Sortie JSON (machine-readable) au lieu du rapport texte.",
    )
    parser.add_argument(
        "--emit-stub",
        action="store_true",
        help=(
            "Si des tokens OHLCV manquent en taxonomie, génère "
            "config/token_taxonomy.unclassified.json comme template d'édition manuelle."
        ),
    )
    parser.add_argument(
        "--stub-path",
        default=str(_default_stub_path()),
        help="Chemin du fichier stub (défaut: config/token_taxonomy.unclassified.json).",
    )
    parser.add_argument(
        "--exit-on-missing",
        action="store_true",
        help="Sort avec code 2 si des tokens manquent en taxonomie (utile pour CI).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    report = compute_taxonomy_coverage()

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_text_report(report))

    if args.emit_stub and report["missing_in_taxonomy"]:
        stub_path = Path(args.stub_path).expanduser().resolve()
        stub_payload = build_unclassified_stub(report["missing_in_taxonomy"])
        stub_path.parent.mkdir(parents=True, exist_ok=True)
        stub_path.write_text(
            json.dumps(stub_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\n📝 Stub écrit : {stub_path}", file=sys.stderr)

    if args.exit_on_missing and report["missing_in_taxonomy"]:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
