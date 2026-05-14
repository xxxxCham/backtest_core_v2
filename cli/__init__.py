"""Module-ID: cli.__init__

Purpose: Package CLI - parser argparse, routing commands, entry point.

Role in pipeline: CLI interface

Key components: create_parser(), add_subcommands(), main()

Inputs: sys.argv command-line args

Outputs: Dispatched to cmd_* functions

Dependencies: argparse, .commands

Conventions: Sous-commandes via add_parser(); --verbose/-v global; help auto-generated.

Read-if: Ajout/modification sous-commande ou argument structure.

Skip-if: Vous appelez main() depuis __main__.py.
"""

import argparse
import os

from backtest.result_store import get_results_root_dir

from .commands import (
    cmd_analyze,
    cmd_backtest,
    cmd_benchmark,
    cmd_builder,
    cmd_catalog,
    cmd_check_gpu,
    cmd_cycle,
    cmd_export,
    cmd_grid_backtest,
    cmd_indicators,
    cmd_info,
    cmd_list,
    cmd_llm_optimize,
    cmd_optuna,
    cmd_sweep,
    cmd_validate,
    cmd_visualize,
)


def create_parser() -> argparse.ArgumentParser:
    """Crée le parser principal avec toutes les sous-commandes."""
    default_results_dir = str(get_results_root_dir())

    parser = argparse.ArgumentParser(
        prog="backtest-core-v2",
        description="Moteur de backtesting pour stratégies de trading",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  %(prog)s list strategies              Lister toutes les stratégies
  %(prog)s list indicators              Lister tous les indicateurs
  %(prog)s info strategy bollinger_atr  Détails d'une stratégie
  %(prog)s backtest -s ema_cross -d data.parquet
  %(prog)s sweep -s ema_cross -d data.parquet --granularity 0.3
        """,
    )

    # Parser parent avec arguments communs
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Mode verbose (debug)",
    )
    common_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Mode silencieux",
    )
    common_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Désactiver les couleurs",
    )
    common_parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed pour reproductibilité (défaut: 42)",
    )
    common_parser.add_argument(
        "--config",
        type=str,
        help="Fichier de configuration TOML",
    )
    common_parser.add_argument(
        "--results-write-mode",
        choices=["legacy", "shadow", "v2"],
        default=None,
        help=("Mode persistance résultats: legacy (ancien), shadow (double écriture), v2 (nouveau store uniquement)"),
    )

    # Sous-commandes
    subparsers = parser.add_subparsers(
        title="Commandes",
        dest="command",
        description="Commandes disponibles",
    )

    # === LIST ===
    list_parser = subparsers.add_parser(
        "list",
        parents=[common_parser],
        help="Lister les ressources disponibles",
        description="Liste les stratégies, indicateurs, données ou presets",
    )
    list_parser.add_argument(
        "resource",
        choices=["strategies", "indicators", "data", "presets"],
        help="Type de ressource à lister",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Sortie au format JSON",
    )

    # === INDICATORS (alias list indicators) ===
    indicators_parser = subparsers.add_parser(
        "indicators",
        parents=[common_parser],
        help="Lister les indicateurs disponibles",
        description="Alias de: list indicators",
    )
    indicators_parser.add_argument(
        "--json",
        action="store_true",
        help="Sortie au format JSON",
    )

    # === INFO ===
    info_parser = subparsers.add_parser(
        "info",
        parents=[common_parser],
        help="Informations détaillées sur une ressource",
        description="Affiche les paramètres et documentation d'une stratégie ou indicateur",
    )
    info_parser.add_argument(
        "resource_type",
        choices=["strategy", "indicator"],
        help="Type de ressource",
    )
    info_parser.add_argument(
        "name",
        help="Nom de la ressource",
    )
    info_parser.add_argument(
        "--json",
        action="store_true",
        help="Sortie au format JSON",
    )

    # === BACKTEST ===
    backtest_parser = subparsers.add_parser(
        "backtest",
        parents=[common_parser],
        help="Exécuter un backtest",
        description="Lance un backtest avec une stratégie et des données",
    )
    backtest_parser.add_argument(
        "-s",
        "--strategy",
        required=False,
        help="Nom de la stratégie",
    )
    backtest_parser.add_argument(
        "--from-category",
        action="append",
        help="Sélectionner les stratégies depuis le catalog (catégorie)",
    )
    backtest_parser.add_argument(
        "--from-tag",
        action="append",
        help="Sélectionner les stratégies depuis le catalog (tag)",
    )
    backtest_parser.add_argument(
        "-d",
        "--data",
        required=True,
        help="Chemin vers le fichier de données OHLCV",
    )
    backtest_parser.add_argument(
        "--start",
        type=str,
        help="Date de debut (format ISO)",
    )
    backtest_parser.add_argument(
        "--end",
        type=str,
        help="Date de fin (format ISO)",
    )
    backtest_parser.add_argument(
        "--symbol",
        type=str,
        help="Symbole (override si non present dans le nom du fichier)",
    )
    backtest_parser.add_argument(
        "--timeframe",
        type=str,
        help="Timeframe (override si non present dans le nom du fichier)",
    )
    backtest_parser.add_argument(
        "-p",
        "--params",
        type=str,
        default="{}",
        help="Paramètres stratégie en JSON (défaut: {})",
    )
    backtest_parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Capital initial (défaut: 10000)",
    )
    backtest_parser.add_argument(
        "--fees-bps",
        type=int,
        default=10,
        help="Frais en basis points (défaut: 10 = 0.1%%)",
    )
    backtest_parser.add_argument(
        "--slippage-bps",
        type=float,
        help="Slippage en basis points (defaut: config)",
    )
    backtest_parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Fichier de sortie pour les résultats",
    )
    backtest_parser.add_argument(
        "--format",
        choices=["json", "csv", "parquet"],
        default="json",
        help="Format de sortie (défaut: json)",
    )

    # === SWEEP ===
    sweep_parser = subparsers.add_parser(
        "sweep",
        parents=[common_parser],
        help="Optimisation paramétrique",
        description="Lance une optimisation sur grille de paramètres",
        aliases=["optimize"],
    )
    sweep_parser.add_argument(
        "-s",
        "--strategy",
        required=False,
        help="Nom de la stratégie",
    )
    sweep_parser.add_argument(
        "--from-category",
        action="append",
        help="Sélectionner les stratégies depuis le catalog (catégorie)",
    )
    sweep_parser.add_argument(
        "--from-tag",
        action="append",
        help="Sélectionner les stratégies depuis le catalog (tag)",
    )
    sweep_parser.add_argument(
        "-d",
        "--data",
        required=True,
        help="Chemin vers le fichier de données OHLCV",
    )
    sweep_parser.add_argument(
        "--start",
        type=str,
        help="Date de debut (format ISO)",
    )
    sweep_parser.add_argument(
        "--end",
        type=str,
        help="Date de fin (format ISO)",
    )
    sweep_parser.add_argument(
        "--symbol",
        type=str,
        help="Symbole (override si non present dans le nom du fichier)",
    )
    sweep_parser.add_argument(
        "--timeframe",
        type=str,
        help="Timeframe (override si non present dans le nom du fichier)",
    )
    sweep_parser.add_argument(
        "-g",
        "--granularity",
        type=float,
        default=0.5,
        help="Granularité (0.0=fin, 1.0=grossier, défaut: 0.5)",
    )
    sweep_parser.add_argument(
        "--include-optional-params",
        action="store_true",
        help="Inclure les paramètres optionnels (ex: leverage) dans la grille",
    )
    sweep_parser.add_argument(
        "--max-combinations",
        type=int,
        default=10000,
        help="Limite de combinaisons (défaut: 10000)",
    )
    sweep_parser.add_argument(
        "-m",
        "--metric",
        choices=[
            "sharpe",
            "sharpe_ratio",
            "sortino",
            "sortino_ratio",
            "total_return",
            "max_drawdown",
            "win_rate",
            "profit_factor",
        ],
        default="sharpe",
        help="Métrique d'optimisation. Accepte sharpe/sharpe_ratio, sortino/sortino_ratio (défaut: sharpe)",
    )
    sweep_parser.add_argument(
        "--parallel",
        type=int,
        default=4,
        help="Nombre de workers parallèles (défaut: 4)",
    )
    sweep_parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Fichier de sortie pour les résultats",
    )
    sweep_parser.add_argument(
        "--format",
        choices=["auto", "json", "csv", "parquet"],
        default="auto",
        help="Format de sortie sweep (défaut: auto, inféré depuis le suffixe)",
    )
    sweep_parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Capital initial (défaut: 10000)",
    )
    sweep_parser.add_argument(
        "--fees-bps",
        type=int,
        default=10,
        help="Frais en basis points (défaut: 10)",
    )
    sweep_parser.add_argument(
        "--slippage-bps",
        type=float,
        help="Slippage en basis points (defaut: config)",
    )
    sweep_parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Nombre de meilleurs résultats à afficher (défaut: 10)",
    )

    # === VALIDATE ===
    validate_parser = subparsers.add_parser(
        "validate",
        parents=[common_parser],
        help="Valider configuration",
        description="Vérifie l'intégrité des stratégies, indicateurs et données",
    )
    validate_parser.add_argument(
        "--strategy",
        type=str,
        help="Valider une stratégie spécifique",
    )
    validate_parser.add_argument(
        "--data",
        type=str,
        help="Valider un fichier de données",
    )
    validate_parser.add_argument(
        "--all",
        action="store_true",
        help="Valider tout le système",
    )

    # === EXPORT ===
    export_parser = subparsers.add_parser(
        "export",
        parents=[common_parser],
        help="Exporter résultats",
        description="Exporte les résultats dans différents formats",
    )
    export_parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Fichier de résultats à exporter",
    )
    export_parser.add_argument(
        "-f",
        "--format",
        choices=["html", "excel", "csv"],
        default="html",
        help="Format d'export (défaut: html)",
    )
    export_parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Fichier de sortie",
    )
    export_parser.add_argument(
        "--template",
        type=str,
        help="Template de rapport personnalisé",
    )

    # === OPTUNA ===
    optuna_parser = subparsers.add_parser(
        "optuna",
        parents=[common_parser],
        help="Optimisation bayésienne via Optuna",
        description="Lance une optimisation intelligente des paramètres (10-100x plus rapide que sweep)",
    )
    optuna_parser.add_argument(
        "-s",
        "--strategy",
        required=False,
        help="Nom de la stratégie",
    )
    optuna_parser.add_argument(
        "--from-category",
        action="append",
        help="Sélectionner les stratégies depuis le catalog (catégorie)",
    )
    optuna_parser.add_argument(
        "--from-tag",
        action="append",
        help="Sélectionner les stratégies depuis le catalog (tag)",
    )
    optuna_parser.add_argument(
        "-d",
        "--data",
        required=True,
        help="Chemin vers le fichier de données OHLCV",
    )
    optuna_parser.add_argument(
        "--start",
        type=str,
        help="Date de debut (format ISO)",
    )
    optuna_parser.add_argument(
        "--end",
        type=str,
        help="Date de fin (format ISO)",
    )
    optuna_parser.add_argument(
        "--symbol",
        type=str,
        help="Symbole (override si non present dans le nom du fichier)",
    )
    optuna_parser.add_argument(
        "--timeframe",
        type=str,
        help="Timeframe (override si non present dans le nom du fichier)",
    )
    optuna_parser.add_argument(
        "-n",
        "--n-trials",
        type=int,
        default=100,
        help="Nombre de trials (défaut: 100)",
    )
    optuna_parser.add_argument(
        "-m",
        "--metric",
        default="sharpe",
        help="Métrique à optimiser. Multi-objectif: 'sharpe,max_drawdown' (défaut: sharpe)",
    )
    optuna_parser.add_argument(
        "--sampler",
        choices=["tpe", "cmaes", "random"],
        default="tpe",
        help="Algorithme de sampling (défaut: tpe)",
    )
    optuna_parser.add_argument(
        "--pruning",
        action="store_true",
        help="Activer le pruning (arrêt précoce des trials peu prometteurs)",
    )
    optuna_parser.add_argument(
        "--pruner",
        choices=["median", "hyperband"],
        default="median",
        help="Type de pruner (défaut: median)",
    )
    optuna_parser.add_argument(
        "--multi-objective",
        action="store_true",
        help="Mode multi-objectif (Pareto). Utiliser -m 'sharpe,max_drawdown'",
    )
    optuna_parser.add_argument(
        "--param-space",
        type=str,
        help="Espace de paramètres en JSON (sinon auto-détecté)",
    )
    optuna_parser.add_argument(
        "-c",
        "--constraints",
        nargs="*",
        help="Contraintes: 'slow_period,>,fast_period' (param1,op,param2)",
    )
    optuna_parser.add_argument(
        "--timeout",
        type=int,
        help="Timeout en secondes (optionnel)",
    )
    optuna_parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Nombre de jobs parallèles (défaut: 1, utiliser prudemment)",
    )
    optuna_parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Capital initial (défaut: 10000)",
    )
    optuna_parser.add_argument(
        "--fees-bps",
        type=int,
        default=10,
        help="Frais en basis points (défaut: 10)",
    )
    optuna_parser.add_argument(
        "--slippage-bps",
        type=float,
        help="Slippage en basis points (defaut: config)",
    )
    optuna_parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Nombre de meilleurs résultats à afficher (défaut: 10)",
    )
    optuna_parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Fichier de sortie pour les résultats",
    )
    optuna_parser.add_argument(
        "--early-stop-patience",
        type=int,
        help="Arrêt anticipé après N trials sans amélioration (None = désactivé)",
    )

    # === VISUALIZE ===
    visualize_parser = subparsers.add_parser(
        "visualize",
        parents=[common_parser],
        help="Visualiser les résultats de backtest",
        description="Génère des graphiques interactifs (candlesticks + trades)",
    )
    visualize_parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Fichier de résultats à visualiser (JSON)",
    )
    visualize_parser.add_argument(
        "-d",
        "--data",
        type=str,
        help="Fichier de données OHLCV pour les candlesticks",
    )
    visualize_parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Fichier HTML de sortie",
    )
    visualize_parser.add_argument(
        "--html",
        action="store_true",
        help="Générer automatiquement un fichier HTML",
    )
    visualize_parser.add_argument(
        "-m",
        "--metric",
        type=str,
        help="Métrique pour sélectionner le meilleur (pour sweep/optuna)",
    )
    visualize_parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Capital initial (défaut: 10000)",
    )
    visualize_parser.add_argument(
        "--fees-bps",
        type=int,
        default=10,
        help="Frais en basis points (défaut: 10)",
    )
    visualize_parser.add_argument(
        "--no-show",
        action="store_true",
        help="Ne pas ouvrir le graphique dans le navigateur",
    )

    # === CHECK-GPU ===
    check_gpu_parser = subparsers.add_parser(
        "check-gpu",
        parents=[common_parser],
        help="Diagnostic GPU et benchmark",
        description="Diagnostic GPU désactivé (mode CPU-only)",
    )
    check_gpu_parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Exécuter un benchmark CPU vs GPU (EMA 10k points)",
    )

    # === BENCHMARK ===
    benchmark_parser = subparsers.add_parser(
        "benchmark",
        parents=[common_parser],
        help="Benchmarks de performance",
        description="Exécute des benchmarks synthétiques (indicateurs, simulateur)",
    )
    benchmark_parser.add_argument(
        "--category",
        choices=["indicators", "simulator", "gpu", "all"],
        default="all",
        help="Catégorie de benchmark à exécuter (défaut: all)",
    )
    benchmark_parser.add_argument(
        "--size",
        type=int,
        default=10000,
        help="Taille des données de test (défaut: 10000)",
    )
    benchmark_parser.add_argument(
        "--period",
        type=int,
        default=20,
        help="Période indicateurs (défaut: 20, utilisé pour category=indicators)",
    )

    # === LLM-OPTIMIZE ===
    llm_optimize_parser = subparsers.add_parser(
        "llm-optimize",
        parents=[common_parser],
        help="Optimisation LLM multi-agents",
        description="Lance l'orchestrateur multi-agents (Analyst/Strategist/Critic/Validator) pour optimisation intelligente",
        aliases=["orchestrate"],
    )
    llm_optimize_parser.add_argument(
        "-s",
        "--strategy",
        required=False,
        help="Nom de la stratégie",
    )
    llm_optimize_parser.add_argument(
        "--from-category",
        action="append",
        help="Sélectionner les stratégies depuis le catalog (catégorie)",
    )
    llm_optimize_parser.add_argument(
        "--from-tag",
        action="append",
        help="Sélectionner les stratégies depuis le catalog (tag)",
    )
    llm_optimize_parser.add_argument(
        "--symbol",
        required=True,
        help="Symbole (ex: BTCUSDC)",
    )
    llm_optimize_parser.add_argument(
        "--timeframe",
        required=True,
        help="Timeframe (ex: 1h, 30m, 1d)",
    )
    llm_optimize_parser.add_argument(
        "--start",
        type=str,
        help="Date de début (format ISO)",
    )
    llm_optimize_parser.add_argument(
        "--end",
        type=str,
        help="Date de fin (format ISO)",
    )
    llm_optimize_parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Capital initial (défaut: 10000)",
    )
    llm_optimize_parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Nombre max d'itérations LLM (défaut: 10)",
    )
    llm_optimize_parser.add_argument(
        "--model",
        default="deepseek-r1-distill:14b",
        help="Modèle LLM à utiliser (défaut: deepseek-r1-distill:14b)",
    )
    llm_optimize_parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="Température LLM (défaut: 0.7)",
    )
    llm_optimize_parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        help="Max tokens LLM (défaut: 4096)",
    )
    llm_optimize_parser.add_argument(
        "--timeout",
        type=int,
        default=900,
        help="Timeout LLM en secondes (défaut: 900 = 15min)",
    )
    llm_optimize_parser.add_argument(
        "--min-sharpe",
        type=float,
        default=1.0,
        help="Sharpe ratio minimum requis (défaut: 1.0)",
    )
    llm_optimize_parser.add_argument(
        "--max-drawdown",
        type=float,
        default=0.20,
        help="Max drawdown limite (fraction, défaut: 0.20 = 20%%)",
    )
    llm_optimize_parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Fichier de sortie pour les résultats",
    )

    # === GRID-BACKTEST ===
    grid_backtest_parser = subparsers.add_parser(
        "grid-backtest",
        parents=[common_parser],
        help="Backtest en mode grille",
        description="Exécute un backtest sur une grille de paramètres (différent de sweep)",
        aliases=["grid"],
    )
    grid_backtest_parser.add_argument(
        "-s",
        "--strategy",
        required=False,
        help="Nom de la stratégie",
    )
    grid_backtest_parser.add_argument(
        "--from-category",
        action="append",
        help="Sélectionner les stratégies depuis le catalog (catégorie)",
    )
    grid_backtest_parser.add_argument(
        "--from-tag",
        action="append",
        help="Sélectionner les stratégies depuis le catalog (tag)",
    )
    grid_backtest_parser.add_argument(
        "--symbol",
        required=True,
        help="Symbole (ex: BTCUSDC)",
    )
    grid_backtest_parser.add_argument(
        "--timeframe",
        required=True,
        help="Timeframe (ex: 1h, 30m, 1d)",
    )
    grid_backtest_parser.add_argument(
        "--start",
        type=str,
        help="Date de début (format ISO)",
    )
    grid_backtest_parser.add_argument(
        "--end",
        type=str,
        help="Date de fin (format ISO)",
    )
    grid_backtest_parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Capital initial (défaut: 10000)",
    )
    grid_backtest_parser.add_argument(
        "--fees-bps",
        type=int,
        default=10,
        help="Frais en basis points (défaut: 10)",
    )
    grid_backtest_parser.add_argument(
        "--slippage-bps",
        type=float,
        help="Slippage en basis points (défaut: config)",
    )
    grid_backtest_parser.add_argument(
        "--param-grid",
        type=str,
        help="Grille de paramètres en JSON (ex: '{\"atr_period\": [10, 14, 20]}'). Si omis, grille auto depuis param_ranges",
    )
    grid_backtest_parser.add_argument(
        "--include-optional-params",
        action="store_true",
        help="Inclure les paramètres optionnels (ex: leverage) dans la grille auto",
    )
    grid_backtest_parser.add_argument(
        "--max-combinations",
        type=int,
        default=1000,
        help="Limite de combinaisons (défaut: 1000)",
    )
    grid_backtest_parser.add_argument(
        "-m",
        "--metric",
        choices=["sharpe_ratio", "sortino_ratio", "total_return_pct", "max_drawdown", "win_rate", "profit_factor"],
        default="sharpe_ratio",
        help="Métrique pour trier les résultats (défaut: sharpe_ratio)",
    )
    grid_backtest_parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Nombre de meilleurs résultats à afficher (défaut: 10)",
    )
    grid_backtest_parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Fichier de sortie pour les résultats",
    )

    # === ANALYZE ===
    analyze_parser = subparsers.add_parser(
        "analyze",
        parents=[common_parser],
        help="Analyser les résultats de backtests",
        description=f"Analyse les résultats de backtests stockés dans {default_results_dir}",
    )
    analyze_parser.add_argument(
        "-i",
        "--input",
        type=str,
        help="Fichier unique à analyser (JSON/CSV/Parquet), alternative à --results-dir",
    )
    analyze_parser.add_argument(
        "--results-dir",
        type=str,
        default=default_results_dir,
        help=f"Répertoire des résultats (défaut: {default_results_dir})",
    )
    analyze_parser.add_argument(
        "--profitable-only",
        action="store_true",
        help="Afficher uniquement les runs profitables",
    )
    analyze_parser.add_argument(
        "--sort-by",
        type=str,
        default="total_pnl",
        help="Métrique de tri (défaut: total_pnl)",
    )
    analyze_parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Nombre de runs à afficher (défaut: 10)",
    )
    analyze_parser.add_argument(
        "--min-trades",
        type=int,
        default=0,
        help="Filtrer les runs avec au moins N trades (défaut: 0)",
    )
    analyze_parser.add_argument(
        "--stats",
        action="store_true",
        help="Afficher les statistiques globales",
    )
    analyze_parser.add_argument(
        "--hydrate",
        action="store_true",
        help="Compléter les métriques depuis runs/<run_id>/metrics.json (plus lent)",
    )
    analyze_parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Fichier de sortie pour l'analyse",
    )

    # === CYCLE ===
    cycle_parser = subparsers.add_parser(
        "cycle",
        parents=[common_parser],
        help="Cycle complet baseline+sweep+validation OOS",
        description="Automatise un workflow complet: train baseline, sweep, test hors-échantillon, rapport",
    )
    cycle_parser.add_argument(
        "-s",
        "--strategy",
        required=False,
        help="Nom de la stratégie",
    )
    cycle_parser.add_argument(
        "--from-category",
        action="append",
        help="Sélectionner les stratégies depuis le catalog (catégorie)",
    )
    cycle_parser.add_argument(
        "--from-tag",
        action="append",
        help="Sélectionner les stratégies depuis le catalog (tag)",
    )
    cycle_parser.add_argument(
        "-d",
        "--data",
        required=True,
        help="Chemin vers le fichier de données OHLCV",
    )
    cycle_parser.add_argument(
        "--symbol",
        type=str,
        help="Symbole (override si non present dans le nom du fichier)",
    )
    cycle_parser.add_argument(
        "--timeframe",
        type=str,
        help="Timeframe (override si non present dans le nom du fichier)",
    )
    cycle_parser.add_argument(
        "--train-start",
        type=str,
        help="Date de début train (ISO)",
    )
    cycle_parser.add_argument(
        "--train-end",
        type=str,
        help="Date de fin train (ISO)",
    )
    cycle_parser.add_argument(
        "--test-start",
        type=str,
        help="Date de début test OOS (ISO)",
    )
    cycle_parser.add_argument(
        "--test-end",
        type=str,
        help="Date de fin test OOS (ISO)",
    )
    cycle_parser.add_argument(
        "--split-ratio",
        type=float,
        default=0.7,
        help="Ratio train pour split auto si dates train/test incomplètes (défaut: 0.7)",
    )
    cycle_parser.add_argument(
        "--metric",
        choices=[
            "sharpe",
            "sharpe_ratio",
            "sortino",
            "sortino_ratio",
            "total_return",
            "max_drawdown",
            "win_rate",
            "profit_factor",
        ],
        default="sharpe",
        help="Métrique de sélection du meilleur candidat sweep (défaut: sharpe)",
    )
    cycle_parser.add_argument(
        "-g",
        "--granularity",
        type=float,
        default=0.5,
        help="Granularité sweep (0.0=fin, 1.0=grossier, défaut: 0.5)",
    )
    cycle_parser.add_argument(
        "--max-combinations",
        type=int,
        default=1000,
        help="Limite de combinaisons sweep (défaut: 1000)",
    )
    cycle_parser.add_argument(
        "--parallel",
        type=int,
        default=4,
        help="Nombre de workers sweep (défaut: 4)",
    )
    cycle_parser.add_argument(
        "--include-optional-params",
        action="store_true",
        help="Inclure les paramètres optionnels dans la grille sweep",
    )
    cycle_parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Top résultats sweep à conserver/afficher (défaut: 20)",
    )
    cycle_parser.add_argument(
        "--filter-profile",
        choices=["explore", "balanced", "strict"],
        default="balanced",
        help="Profil de filtres candidats: explore (souple), balanced, strict (défaut: balanced)",
    )
    cycle_parser.add_argument(
        "--min-trades",
        type=int,
        default=None,
        help="Filtre minimum de trades. Si omis, dépend de --filter-profile",
    )
    cycle_parser.add_argument(
        "--max-drawdown",
        type=float,
        help="Filtre drawdown max admissible en %% (ex: 40 ou -40 pour -40%%)",
    )
    cycle_parser.add_argument(
        "--require-positive-train",
        action="store_true",
        help="Exiger un total_return train > 0 pour le candidat retenu",
    )
    cycle_parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Capital initial (défaut: 10000)",
    )
    cycle_parser.add_argument(
        "--fees-bps",
        type=int,
        default=10,
        help="Frais en basis points (défaut: 10)",
    )
    cycle_parser.add_argument(
        "--slippage-bps",
        type=float,
        help="Slippage en basis points (defaut: config)",
    )
    cycle_parser.add_argument(
        "--output-dir",
        type=str,
        default="runs",
        help="Répertoire de sortie des artefacts cycle (défaut: runs)",
    )
    cycle_parser.add_argument(
        "--run-name",
        type=str,
        help="Préfixe de nom pour les fichiers de sortie",
    )
    cycle_parser.add_argument(
        "--export-html",
        action="store_true",
        help="Exporter aussi les résultats test/full au format HTML",
    )
    cycle_parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Ne pas exécuter validate --all avant le cycle",
    )
    cycle_parser.add_argument(
        "--refine",
        action="store_true",
        help="Activer un affinage local des paramètres autour des meilleurs candidats train",
    )
    cycle_parser.add_argument(
        "--refine-top-candidates",
        type=int,
        default=5,
        help="Nombre de candidats coarse à utiliser comme seeds d'affinage (défaut: 5)",
    )
    cycle_parser.add_argument(
        "--refine-granularity",
        type=float,
        default=0.5,
        help="Granularité de l'affinage local (défaut: 0.5)",
    )
    cycle_parser.add_argument(
        "--refine-max-combinations",
        type=int,
        default=1000,
        help="Limite de combinaisons par seed pour l'affinage (défaut: 1000)",
    )
    cycle_parser.add_argument(
        "--refine-range-ratio",
        type=float,
        default=0.25,
        help="Largeur de la fenêtre locale autour du seed (fraction de la plage globale, défaut: 0.25)",
    )
    cycle_parser.add_argument(
        "--report-top",
        type=int,
        default=10,
        help="Nombre de configurations intéressantes à inclure dans le rapport (défaut: 10)",
    )
    cycle_parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="Exécuter une validation walk-forward sur les paramètres retenus",
    )
    cycle_parser.add_argument(
        "--wf-mode",
        choices=["rolling", "expanding", "both"],
        default="both",
        help="Mode walk-forward (défaut: both)",
    )
    cycle_parser.add_argument(
        "--wf-folds",
        type=int,
        default=6,
        help="Nombre de folds walk-forward (défaut: 6)",
    )
    cycle_parser.add_argument(
        "--wf-train-ratio",
        type=float,
        default=0.75,
        help="Ratio train walk-forward (défaut: 0.75)",
    )
    cycle_parser.add_argument(
        "--wf-embargo-pct",
        type=float,
        default=0.02,
        help="Embargo walk-forward en fraction (défaut: 0.02)",
    )
    cycle_parser.add_argument(
        "--wf-min-train-bars",
        type=int,
        default=500,
        help="Minimum de barres train par fold WFA (défaut: 500)",
    )
    cycle_parser.add_argument(
        "--wf-min-test-bars",
        type=int,
        default=200,
        help="Minimum de barres test par fold WFA (défaut: 200)",
    )
    cycle_parser.add_argument(
        "--require-wf-robust",
        action="store_true",
        help="Échouer le cycle si aucune vue walk-forward n'est robuste",
    )

    # === BUILDER ===
    builder_parser = subparsers.add_parser(
        "builder",
        parents=[common_parser],
        help="Créer une stratégie via LLM (Strategy Builder)",
        description="Génère itérativement une stratégie de trading en combinant les indicateurs existants",
    )
    builder_parser.add_argument(
        "--objective",
        type=str,
        required=True,
        help="Objectif de la stratégie (ex: 'Trend-following BTC 30m avec Bollinger + ATR')",
    )
    builder_parser.add_argument(
        "-d",
        "--data",
        type=str,
        required=True,
        help="Chemin vers le fichier de données OHLCV",
    )
    builder_parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="Nombre max d'itérations (défaut: 10)",
    )
    builder_parser.add_argument(
        "--target-sharpe",
        type=float,
        default=1.0,
        help="Sharpe ratio cible pour acceptation (défaut: 1.0)",
    )
    builder_parser.add_argument(
        "--capital",
        type=float,
        default=10000.0,
        help="Capital initial (défaut: 10000)",
    )
    builder_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Modèle LLM à utiliser.",
    )

    # === CATALOG ===
    catalog_parser = subparsers.add_parser(
        "catalog",
        parents=[common_parser],
        help="Gérer le Strategy Catalog",
        description="Lister et déplacer les entrées du catalog de stratégies",
    )
    catalog_sub = catalog_parser.add_subparsers(dest="catalog_action")

    catalog_list = catalog_sub.add_parser(
        "list",
        parents=[common_parser],
        help="Lister les entrées du catalog",
    )
    catalog_list.add_argument("--category", action="append", help="Filtrer par catégorie")
    catalog_list.add_argument("--tag", action="append", help="Filtrer par tag")
    catalog_list.add_argument("--status", type=str, default="active", help="Statut (active/archived)")
    catalog_list.add_argument("--symbol", type=str, help="Filtrer par symbole")
    catalog_list.add_argument("--timeframe", type=str, help="Filtrer par timeframe")
    catalog_list.add_argument("--strategy", type=str, help="Filtrer par stratégie")
    catalog_list.add_argument("--json", action="store_true", help="Sortie JSON")

    catalog_move = catalog_sub.add_parser(
        "move",
        parents=[common_parser],
        help="Déplacer des entrées vers une catégorie",
    )
    catalog_move.add_argument("--id", nargs="+", required=True, help="IDs à déplacer")
    catalog_move.add_argument("--to", required=True, help="Nouvelle catégorie")

    catalog_tag = catalog_sub.add_parser(
        "tag",
        parents=[common_parser],
        help="Tagger des entrées",
    )
    catalog_tag.add_argument("--id", nargs="+", required=True, help="IDs à tagger")
    catalog_tag.add_argument("--tag", required=True, help="Tag à ajouter")

    catalog_note = catalog_sub.add_parser(
        "note",
        parents=[common_parser],
        help="Ajouter/modifier une note",
    )
    catalog_note.add_argument("--id", required=True, help="ID de l'entrée")
    catalog_note.add_argument("--note", required=True, help="Note à enregistrer")

    catalog_archive = catalog_sub.add_parser(
        "archive",
        parents=[common_parser],
        help="Archiver des entrées",
    )
    catalog_archive.add_argument("--id", nargs="+", required=True, help="IDs à archiver")

    return parser


def main(args: list | None = None) -> int:
    """Point d'entrée principal du CLI."""
    # Charger .env (BACKTEST_DATA_DIR, etc.) même sans python-dotenv.
    from backtest.result_store import load_project_env

    load_project_env()

    parser = create_parser()
    parsed = parser.parse_args(args)

    # Si aucune commande, afficher l'aide
    if parsed.command is None:
        parser.print_help()
        return 0

    # Configuration globale
    import numpy as np

    np.random.seed(parsed.seed)
    if getattr(parsed, "results_write_mode", None):
        os.environ["BACKTEST_RESULTS_WRITE_MODE"] = parsed.results_write_mode

    # Dispatcher vers la commande appropriée
    commands = {
        "list": cmd_list,
        "indicators": cmd_indicators,
        "info": cmd_info,
        "backtest": cmd_backtest,
        "sweep": cmd_sweep,
        "optimize": cmd_sweep,
        "optuna": cmd_optuna,
        "validate": cmd_validate,
        "export": cmd_export,
        "visualize": cmd_visualize,
        "check-gpu": cmd_check_gpu,
        "benchmark": cmd_benchmark,
        "llm-optimize": cmd_llm_optimize,
        "orchestrate": cmd_llm_optimize,
        "grid-backtest": cmd_grid_backtest,
        "grid": cmd_grid_backtest,
        "analyze": cmd_analyze,
        "cycle": cmd_cycle,
        "builder": cmd_builder,
        "catalog": cmd_catalog,
    }

    try:
        handler = commands.get(parsed.command)
        if handler:
            return handler(parsed)
        print(f"Commande inconnue: {parsed.command}")
        return 1
    except KeyboardInterrupt:
        print("\n⚠️  Interrompu par l'utilisateur")
        return 130
    except Exception as e:
        if parsed.verbose:
            import traceback

            traceback.print_exc()
        else:
            print(f"❌ Erreur: {e}")
        return 1


__all__ = ["create_parser", "main"]
