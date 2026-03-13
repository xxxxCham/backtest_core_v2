"""
Module-ID: backtest.report_generator

Purpose: Générer des rapports de backtest lisibles, organisés et facilement interprétables.

Role in pipeline: reporting / visualization

Key components: generate_summary_report, generate_comparison_table, rank_results

Inputs: Liste de résultats de backtest (StoredResultMetadata ou RunResult)

Outputs: Rapports Markdown/HTML, tableaux comparatifs, classements

Dependencies: pandas, pathlib, json

Conventions: Génère des rapports auto-documentés avec métriques clés en premier.

Read-if: Génération de rapports ou analyse comparative de résultats.

Skip-if: Vous n'avez besoin que des résultats bruts sans rapport.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from utils.log import get_logger

logger = get_logger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# Métriques clés à afficher en priorité dans les rapports
KEY_METRICS = [
    "total_return_pct",
    "sharpe_ratio",
    "max_drawdown_pct",
    "win_rate_pct",
    "profit_factor",
    "total_trades",
]

# Seuils pour classification automatique
PROFITABLE_THRESHOLD = 5.0  # Return > 5%
EXCELLENT_SHARPE = 2.0
GOOD_SHARPE = 1.0
MIN_TRADES = 10  # Nombre minimum de trades pour considérer le résultat valide


# =============================================================================
# FONCTIONS DE CLASSEMENT
# =============================================================================

def classify_result(metrics: Dict[str, Any]) -> Tuple[str, str]:
    """
    Classifie un résultat de backtest selon ses performances.

    Args:
        metrics: Dict des métriques de performance

    Returns:
        (category, emoji) où category in ["excellent", "good", "mediocre", "failed"]

    Example:
        >>> metrics = {"total_return_pct": 18.5, "sharpe_ratio": 2.3}
        >>> classify_result(metrics)
        ("excellent", "🏆")
    """
    total_return = metrics.get("total_return_pct", 0)
    sharpe = metrics.get("sharpe_ratio", 0)
    account_ruined = metrics.get("account_ruined", False)
    total_trades = metrics.get("total_trades", 0)

    # Cas d'échec total
    if account_ruined:
        return "ruined", "💀"

    if total_return <= -20:
        return "failed", "❌"

    # Trop peu de trades
    if total_trades < MIN_TRADES:
        return "insufficient_data", "⚠️"

    # Classification par performance
    if total_return >= PROFITABLE_THRESHOLD and sharpe >= EXCELLENT_SHARPE:
        return "excellent", "🏆"
    elif total_return >= PROFITABLE_THRESHOLD and sharpe >= GOOD_SHARPE:
        return "good", "✅"
    elif total_return >= 0:
        return "mediocre", "📊"
    else:
        return "unprofitable", "❌"


def rank_results(results: List[Dict[str, Any]], sort_by: str = "total_return_pct") -> pd.DataFrame:
    """
    Classe les résultats de backtest par ordre de performance.

    Args:
        results: Liste de métadonnées de résultats
        sort_by: Métrique pour le tri (défaut: total_return_pct)

    Returns:
        DataFrame trié avec classification et emoji

    Example:
        >>> results = [{"run_id": "abc", "metrics": {...}}, ...]
        >>> df = rank_results(results)
        >>> print(df[["run_id", "category", "total_return_pct"]].head())
    """
    rows = []
    for result in results:
        metrics = result.get("metrics", {})
        category, emoji = classify_result(metrics)

        row = {
            "run_id": result.get("run_id", "unknown"),
            "strategy": result.get("strategy", "unknown"),
            "symbol": result.get("symbol", ""),
            "timeframe": result.get("timeframe", ""),
            "timestamp": result.get("timestamp", ""),
            "category": category,
            "emoji": emoji,
            **{k: metrics.get(k, 0) for k in KEY_METRICS},
        }
        rows.append(row)

    df = pd.DataFrame(rows)

    # Trier par métrique choisie
    if sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=False)

    return df


# =============================================================================
# GÉNÉRATION DE RAPPORTS MARKDOWN
# =============================================================================

def generate_summary_report(
    results: List[Dict[str, Any]],
    output_path: Optional[Path] = None,
    title: str = "📊 Rapport de Backtest - Résumé",
) -> str:
    """
    Génère un rapport Markdown résumant les résultats de backtest.

    Args:
        results: Liste de métadonnées de résultats
        output_path: Chemin optionnel pour sauvegarder le rapport
        title: Titre du rapport

    Returns:
        Contenu Markdown du rapport

    Example:
        >>> results = storage.load_all_results()
        >>> report = generate_summary_report(results)
        >>> print(report)
    """
    df = rank_results(results)

    # En-tête
    report_lines = [
        f"# {title}",
        "",
        f"**Date de génération:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Nombre total de backtests:** {len(results)}",
        "",
    ]

    # Statistiques globales
    report_lines.extend([
        "## 📈 Statistiques Globales",
        "",
        f"- **Excellents (🏆):** {len(df[df['category'] == 'excellent'])}",
        f"- **Bons (✅):** {len(df[df['category'] == 'good'])}",
        f"- **Médiocres (📊):** {len(df[df['category'] == 'mediocre'])}",
        f"- **Non rentables (❌):** {len(df[df['category'] == 'unprofitable'])}",
        f"- **Échecs catastrophiques (💀):** {len(df[df['category'] == 'ruined'])}",
        f"- **Données insuffisantes (⚠️):** {len(df[df['category'] == 'insufficient_data'])}",
        "",
    ])

    # Top 10 meilleurs résultats
    top10 = df.head(10)
    report_lines.extend([
        "## 🏆 Top 10 des Meilleurs Résultats",
        "",
        "| Rang | Emoji | Stratégie | Symbole | TF | Return % | Sharpe | Max DD % | Win Rate % | Trades |",
        "|------|-------|-----------|---------|----|---------:|-------:|---------:|-----------:|-------:|",
    ])

    for idx, (_, row) in enumerate(top10.iterrows(), 1):
        report_lines.append(
            f"| {idx} | {row['emoji']} | {row['strategy']} | {row['symbol']} | {row['timeframe']} | "
            f"{row['total_return_pct']:.2f} | {row['sharpe_ratio']:.2f} | "
            f"{row['max_drawdown_pct']:.2f} | {row['win_rate_pct']:.2f} | {int(row['total_trades'])} |"
        )

    report_lines.append("")

    # Pires résultats (Bottom 5)
    bottom5 = df.tail(5).sort_values("total_return_pct", ascending=True)
    report_lines.extend([
        "## ⚠️ Les 5 Pires Résultats",
        "",
        "| Rang | Emoji | Stratégie | Symbole | TF | Return % | Sharpe | Max DD % | Raison |",
        "|------|-------|-----------|---------|----|---------:|-------:|---------:|--------|",
    ])

    for idx, (_, row) in enumerate(bottom5.iterrows(), 1):
        reason = "Compte ruiné" if row.get("category") == "ruined" else "Pertes importantes"
        report_lines.append(
            f"| {idx} | {row['emoji']} | {row['strategy']} | {row['symbol']} | {row['timeframe']} | "
            f"{row['total_return_pct']:.2f} | {row['sharpe_ratio']:.2f} | "
            f"{row['max_drawdown_pct']:.2f} | {reason} |"
        )

    report_lines.append("")

    # Performance par stratégie
    strategy_stats = df.groupby("strategy").agg({
        "total_return_pct": ["mean", "std", "count"],
        "sharpe_ratio": "mean",
        "win_rate_pct": "mean",
    }).round(2)

    report_lines.extend([
        "## 📊 Performance par Stratégie",
        "",
        "| Stratégie | Backtests | Return Moyen % | Return Std % | Sharpe Moyen | Win Rate Moyen % |",
        "|-----------|----------:|---------------:|-------------:|-------------:|-----------------:|",
    ])

    for strategy, row in strategy_stats.iterrows():
        report_lines.append(
            f"| {strategy} | {int(row[('total_return_pct', 'count')])} | "
            f"{row[('total_return_pct', 'mean')]:.2f} | {row[('total_return_pct', 'std')]:.2f} | "
            f"{row[('sharpe_ratio', 'mean')]:.2f} | {row[('win_rate_pct', 'mean')]:.2f} |"
        )

    report_lines.append("")

    # Recommandations
    report_lines.extend([
        "## 🚀 Recommandations",
        "",
    ])

    excellent_count = len(df[df['category'] == 'excellent'])
    if excellent_count > 0:
        top_strategy = top10.iloc[0]
        report_lines.extend([
            "### ✅ Production Immédiate",
            "",
            f"**{top_strategy['strategy']}** sur **{top_strategy['symbol']}** ({top_strategy['timeframe']}) :",
            f"- Return: **{top_strategy['total_return_pct']:.2f}%**",
            f"- Sharpe: **{top_strategy['sharpe_ratio']:.2f}**",
            f"- Max Drawdown: **{top_strategy['max_drawdown_pct']:.2f}%**",
            "",
        ])
    else:
        report_lines.extend([
            "⚠️ Aucune configuration excellente trouvée. Optimisation nécessaire.",
            "",
        ])

    # Avertissements
    ruined_count = len(df[df['category'] == 'ruined'])
    if ruined_count > 0:
        report_lines.extend([
            "### ⚠️ Configurations Dangereuses",
            "",
            f"**{ruined_count} configuration(s)** ont mené à la ruine du compte. À éviter absolument :",
            "",
        ])
        for _, row in df[df['category'] == 'ruined'].head(3).iterrows():
            report_lines.append(
                f"- {row['strategy']} sur {row['symbol']} ({row['timeframe']}) : "
                f"Return {row['total_return_pct']:.2f}%"
            )
        report_lines.append("")

    report_lines.extend([
        "---",
        "",
        "*Rapport généré automatiquement par backtest-core-v2*",
    ])

    report_content = "\n".join(report_lines)

    # Sauvegarder si chemin fourni
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report_content, encoding="utf-8")
        logger.info(f"Rapport sauvegardé : {output_path}")

    return report_content


def generate_comparison_table(
    results: List[Dict[str, Any]],
    filter_category: Optional[str] = None,
    output_format: str = "markdown",
) -> str:
    """
    Génère un tableau comparatif des résultats.

    Args:
        results: Liste de métadonnées de résultats
        filter_category: Filtrer par catégorie (ex: "excellent", "good")
        output_format: Format de sortie ("markdown", "html", "csv")

    Returns:
        Tableau formaté

    Example:
        >>> results = storage.load_all_results()
        >>> table = generate_comparison_table(results, filter_category="excellent")
        >>> print(table)
    """
    df = rank_results(results)

    if filter_category:
        df = df[df["category"] == filter_category]

    if output_format == "markdown":
        return df.to_markdown(index=False, floatfmt=".2f")
    elif output_format == "html":
        return df.to_html(index=False, classes="table table-striped")
    elif output_format == "csv":
        return df.to_csv(index=False)
    else:
        raise ValueError(f"Format non supporté: {output_format}")


# =============================================================================
# SCRIPT PRINCIPAL (si exécuté directement)
# =============================================================================

if __name__ == "__main__":
    print("=== Générateur de Rapports de Backtest ===\n")

    # Charger l'index des résultats
    index_path = Path("backtest_results") / "index.json"
    if not index_path.exists():
        print(f"❌ Fichier index introuvable: {index_path}")
        exit(1)

    with open(index_path, "r") as f:
        index_data = json.load(f)

    results = list(index_data.values())
    print(f"📊 {len(results)} résultats chargés depuis {index_path}\n")

    # Générer rapport récapitulatif
    output_path = Path("backtest_results") / "SUMMARY_REPORT.md"
    report = generate_summary_report(results, output_path=output_path)

    print(f"✅ Rapport généré: {output_path}")
    print("\n--- Aperçu du rapport ---\n")
    print("\n".join(report.split("\n")[:30]))  # Afficher les 30 premières lignes
    print("\n...")
