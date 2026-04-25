"""Module-ID: cli.report_generator

Purpose: Génération de rapports et exports (HTML, CSV, Excel).

Role in pipeline: Export des résultats de backtest/sweep/optuna.

Key components: export_html, export_csv, export_excel, generate_backtest_report

Dependencies: pandas, pathlib, json

Conventions: Tous les exports retournent le Path du fichier créé.

Read-if: Modification des formats d'export.

Skip-if: Utilisation des exports existants.
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from backtest.result_store import get_results_root_dir

# =============================================================================
# TEMPLATES HTML
# =============================================================================

HTML_TEMPLATE_HEADER = """<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        :root {{
            --primary: #4CAF50;
            --danger: #f44336;
            --warning: #ff9800;
            --info: #2196F3;
            --dark: #333;
            --light: #f5f5f5;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            margin: 0;
            padding: 20px;
            background: var(--light);
            color: var(--dark);
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ color: var(--dark); border-bottom: 3px solid var(--primary); padding-bottom: 10px; }}
        h2 {{ color: var(--primary); margin-top: 30px; }}
        .card {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin: 15px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        .metric {{
            text-align: center;
            padding: 15px;
            border-radius: 6px;
            background: var(--light);
        }}
        .metric-value {{
            font-size: 1.8em;
            font-weight: bold;
        }}
        .metric-label {{ color: #666; font-size: 0.9em; }}
        .positive {{ color: var(--primary); }}
        .negative {{ color: var(--danger); }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background: var(--primary);
            color: white;
            font-weight: 600;
        }}
        tr:hover {{ background: #f5f5f5; }}
        .timestamp {{ color: #999; font-size: 0.8em; }}
    </style>
</head>
<body>
<div class="container">
"""

HTML_TEMPLATE_FOOTER = """
    <p class="timestamp">Généré le {timestamp}</p>
</div>
</body>
</html>
"""


# =============================================================================
# EXPORT HTML
# =============================================================================


def export_html(data: dict, output_path: Path, title: str = "Rapport de Backtest") -> Path:
    """Exporte des résultats en HTML formaté.

    Args:
        data: Dictionnaire des résultats
        output_path: Chemin du fichier de sortie
        title: Titre du rapport

    Returns:
        Path du fichier créé

    """
    html_parts = [HTML_TEMPLATE_HEADER.format(title=title)]

    # Titre et infos générales
    strategy = data.get("strategy", "N/A")
    result_type = data.get("type", "backtest")

    html_parts.append(f"<h1>📊 {title}</h1>")
    html_parts.append(f"<p><strong>Stratégie:</strong> {strategy}</p>")
    html_parts.append(f"<p><strong>Type:</strong> {result_type}</p>")

    # Section métriques
    metrics = data.get("metrics", data.get("best_metrics", {}))
    if metrics:
        html_parts.append("<h2>📈 Métriques</h2>")
        html_parts.append('<div class="card"><div class="metrics-grid">')

        metric_display = {
            "total_pnl": ("💰 P&L Total", "${:,.2f}"),
            "total_return_pct": ("📊 Return", "{:+.2f}%"),
            "sharpe_ratio": ("📐 Sharpe", "{:.3f}"),
            "sortino_ratio": ("📐 Sortino", "{:.3f}"),
            "max_drawdown_pct": ("📉 Max DD", "{:.2f}%"),
            "win_rate_pct": ("🎯 Win Rate", "{:.1f}%"),
            "profit_factor": ("💹 Profit Factor", "{:.2f}"),
            "total_trades": ("🔄 Trades", "{}"),
        }

        for key, (label, fmt) in metric_display.items():
            value = metrics.get(key)
            if value is not None:
                formatted = fmt.format(value)
                css_class = ""
                if "pnl" in key.lower() or "return" in key.lower():
                    css_class = "positive" if value >= 0 else "negative"
                elif key == "sharpe_ratio":
                    css_class = "positive" if value >= 1 else "negative" if value < 0 else ""

                html_parts.append(f"""
                    <div class="metric">
                        <div class="metric-value {css_class}">{formatted}</div>
                        <div class="metric-label">{label}</div>
                    </div>
                """)

        html_parts.append("</div></div>")

    # Section paramètres
    params = data.get("params", data.get("best_params", {}))
    if params:
        html_parts.append("<h2>⚙️ Paramètres</h2>")
        html_parts.append('<div class="card"><table>')
        html_parts.append("<tr><th>Paramètre</th><th>Valeur</th></tr>")
        for key, value in params.items():
            html_parts.append(f"<tr><td>{key}</td><td>{value}</td></tr>")
        html_parts.append("</table></div>")

    # Section résultats sweep/optuna
    results = data.get("results", [])
    if results and len(results) > 1:
        html_parts.append(f"<h2>📋 Résultats ({len(results)} combinaisons)</h2>")
        html_parts.append('<div class="card"><table>')

        # Headers dynamiques
        first_result = results[0]
        param_keys = list(first_result.get("params", {}).keys())
        metric_keys = ["total_pnl", "sharpe_ratio", "win_rate_pct"]

        html_parts.append("<tr>")
        for pk in param_keys[:5]:  # Limiter à 5 params
            html_parts.append(f"<th>{pk}</th>")
        for mk in metric_keys:
            html_parts.append(f"<th>{mk}</th>")
        html_parts.append("</tr>")

        # Top 20 résultats
        for r in results[:20]:
            html_parts.append("<tr>")
            for pk in param_keys[:5]:
                html_parts.append(f"<td>{r.get('params', {}).get(pk, '')}</td>")
            for mk in metric_keys:
                val = r.get("metrics", {}).get(mk, 0)
                css = "positive" if val > 0 else "negative" if val < 0 else ""
                html_parts.append(f'<td class="{css}">{val:.4f}</td>')
            html_parts.append("</tr>")

        html_parts.append("</table></div>")

    # Footer
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_parts.append(HTML_TEMPLATE_FOOTER.format(timestamp=timestamp))

    # Écriture fichier
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))

    return output_path


# =============================================================================
# EXPORT CSV
# =============================================================================


def export_csv(data: dict, output_path: Path) -> Path:
    """Exporte des résultats en CSV.

    Args:
        data: Dictionnaire des résultats
        output_path: Chemin du fichier de sortie

    Returns:
        Path du fichier créé

    """
    results = data.get("results", [])

    if results:
        # Multiple résultats (sweep/optuna)
        rows = []
        for r in results:
            row = {**r.get("params", {}), **r.get("metrics", {})}
            rows.append(row)
        df = pd.DataFrame(rows)
    else:
        # Single backtest
        metrics = data.get("metrics", {})
        params = data.get("params", {})
        df = pd.DataFrame([{**params, **metrics}])

    df.to_csv(output_path, index=False)
    return output_path


# =============================================================================
# EXPORT EXCEL
# =============================================================================


def export_excel(data: dict, output_path: Path) -> Path:
    """Exporte des résultats en Excel avec plusieurs feuilles.

    Args:
        data: Dictionnaire des résultats
        output_path: Chemin du fichier de sortie

    Returns:
        Path du fichier créé

    Raises:
        ImportError: Si openpyxl n'est pas installé

    """
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        raise ImportError("openpyxl requis pour export Excel: pip install openpyxl")

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        results = data.get("results", [])

        if results:
            # Feuille principale : tous les résultats
            rows = []
            for r in results:
                row = {**r.get("params", {}), **r.get("metrics", {})}
                rows.append(row)
            df_results = pd.DataFrame(rows)
            df_results.to_excel(writer, sheet_name="Résultats", index=False)

            # Feuille top 10
            if len(rows) > 10:
                df_top = df_results.nlargest(10, "total_pnl") if "total_pnl" in df_results else df_results.head(10)
                df_top.to_excel(writer, sheet_name="Top 10", index=False)
        else:
            # Single backtest
            metrics = data.get("metrics", {})
            params = data.get("params", {})

            # Feuille métriques
            df_metrics = pd.DataFrame([metrics])
            df_metrics.to_excel(writer, sheet_name="Métriques", index=False)

            # Feuille paramètres
            if params:
                df_params = pd.DataFrame([params])
                df_params.to_excel(writer, sheet_name="Paramètres", index=False)

        # Feuille info
        info = {
            "Stratégie": data.get("strategy", "N/A"),
            "Type": data.get("type", "backtest"),
            "Généré le": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        df_info = pd.DataFrame([info])
        df_info.to_excel(writer, sheet_name="Info", index=False)

    return output_path


# =============================================================================
# GÉNÉRATION RAPPORT COMPLET
# =============================================================================


def generate_backtest_report(
    metrics: dict,
    params: dict,
    trades: list[dict] = None,
    equity_curve: list[float] = None,
    strategy: str = "Unknown",
    symbol: str = "Unknown",
    timeframe: str = "Unknown",
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Génère un rapport complet de backtest (HTML + CSV).

    Args:
        metrics: Métriques de performance
        params: Paramètres utilisés
        trades: Liste des trades (optionnel)
        equity_curve: Courbe d'équité (optionnel)
        strategy: Nom de la stratégie
        symbol: Symbole tradé
        timeframe: Timeframe
        output_dir: Répertoire de sortie (par défaut: backtest_results/)

    Returns:
        Dict avec paths des fichiers générés {html, csv, json}

    """
    if output_dir is None:
        output_dir = get_results_root_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{strategy}_{symbol}_{timeframe}_{timestamp}"

    # Préparer les données
    data = {
        "strategy": strategy,
        "symbol": symbol,
        "timeframe": timeframe,
        "type": "backtest",
        "params": params,
        "metrics": metrics,
        "generated_at": datetime.now().isoformat(),
    }

    if trades:
        data["trades"] = trades
        data["trade_count"] = len(trades)

    if equity_curve:
        data["equity_curve"] = equity_curve

    output_files = {}

    # Export JSON
    json_path = output_dir / f"{base_name}.json"
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    output_files["json"] = json_path

    # Export HTML
    html_path = output_dir / f"{base_name}.html"
    export_html(data, html_path, title=f"Backtest {strategy} - {symbol}")
    output_files["html"] = html_path

    # Export CSV (métriques uniquement)
    csv_path = output_dir / f"{base_name}_metrics.csv"
    export_csv(data, csv_path)
    output_files["csv"] = csv_path

    return output_files


def generate_sweep_report(
    results: list[dict],
    best_params: dict,
    best_metrics: dict,
    strategy: str,
    total_combinations: int,
    total_time: float,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Génère un rapport complet de sweep/optimisation.

    Args:
        results: Liste des résultats {params, metrics}
        best_params: Meilleurs paramètres trouvés
        best_metrics: Métriques du meilleur résultat
        strategy: Nom de la stratégie
        total_combinations: Nombre total de combinaisons testées
        total_time: Temps total d'exécution (secondes)
        output_dir: Répertoire de sortie

    Returns:
        Dict avec paths des fichiers générés

    """
    if output_dir is None:
        output_dir = get_results_root_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"sweep_{strategy}_{timestamp}"

    data = {
        "strategy": strategy,
        "type": "sweep",
        "total_combinations": total_combinations,
        "total_time": total_time,
        "best_params": best_params,
        "best_metrics": best_metrics,
        "results": results,
        "generated_at": datetime.now().isoformat(),
    }

    output_files = {}

    # Export JSON complet
    json_path = output_dir / f"{base_name}.json"
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    output_files["json"] = json_path

    # Export HTML
    html_path = output_dir / f"{base_name}.html"
    export_html(data, html_path, title=f"Sweep {strategy}")
    output_files["html"] = html_path

    # Export CSV (tous les résultats)
    csv_path = output_dir / f"{base_name}.csv"
    export_csv(data, csv_path)
    output_files["csv"] = csv_path

    return output_files


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Exports individuels
    "export_html",
    "export_csv",
    "export_excel",
    # Générateurs de rapports
    "generate_backtest_report",
    "generate_sweep_report",
]
