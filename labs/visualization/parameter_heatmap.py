"""
Visualisation heatmap des performances par paramètres.

Objectif : Voir visuellement quelles plages de paramètres sont rentables.
"""
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


def create_parameter_heatmap(
    results_csv: str,
    param_x: str = 'bb_period',
    param_y: str = 'entry_z',
    metric: str = 'total_pnl',
    output_file: str = 'labs/visualization/param_heatmap.png'
):
    """
    Crée une heatmap des performances selon 2 paramètres.

    Args:
        results_csv: Chemin vers le CSV des résultats du sweep
        param_x: Paramètre pour l'axe X
        param_y: Paramètre pour l'axe Y
        metric: Métrique à afficher ('total_pnl', 'sharpe', 'win_rate')
        output_file: Fichier de sortie
    """
    # Charger résultats
    df = pd.read_csv(results_csv)

    # Parser params_dict (format JSON dans le CSV)
    import json
    params_data = []
    for idx, row in df.iterrows():
        try:
            params = json.loads(row['params_dict'])
            params[metric] = row[metric]
            params_data.append(params)
        except Exception:
            pass

    df_params = pd.DataFrame(params_data)

    # Créer pivot table pour heatmap
    pivot = df_params.pivot_table(
        values=metric,
        index=param_y,
        columns=param_x,
        aggfunc='mean'
    )

    # Créer heatmap
    plt.figure(figsize=(12, 8))
    sns.heatmap(
        pivot,
        annot=False,
        fmt='.0f',
        cmap='RdYlGn',
        center=0,
        cbar_kws={'label': metric}
    )

    plt.title(f'Heatmap: {metric} par {param_x} × {param_y}')
    plt.xlabel(param_x)
    plt.ylabel(param_y)

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"✅ Heatmap sauvegardée: {output_file}")

    # Identifier zones rentables
    profitable_zones = pivot > 0
    pct_profitable = profitable_zones.sum().sum() / (pivot.shape[0] * pivot.shape[1]) * 100

    print(f"Zones rentables: {pct_profitable:.1f}% des combinaisons")

    return pivot


if __name__ == "__main__":
    # Exemple d'utilisation
    # create_parameter_heatmap(
    #     results_csv="docs/2026-02-05T01-01_export.csv",
    #     param_x='bb_period',
    #     param_y='entry_z',
    #     metric='total_pnl'
    # )

    print("Script prêt. Lancez create_parameter_heatmap() avec votre CSV de résultats.")
