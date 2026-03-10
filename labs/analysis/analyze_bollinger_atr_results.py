#!/usr/bin/env python3
"""
Analyse des résultats Bollinger ATR pour identifier les plages optimales des paramètres
et proposer des ranges resserrés vers les zones profitables.
"""

import json
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd


def load_bollinger_atr_results() -> pd.DataFrame:
    """Charge tous les résultats bollinger_atr depuis backtest_results"""

    results = []
    backtest_dir = Path("backtest_results")

    print("📊 Chargement des résultats bollinger_atr individuels...")

    # Rechercher tous les dossiers de backtest bollinger_atr
    backtest_dirs = [d for d in backtest_dir.iterdir()
                    if d.is_dir() and "bollinger_atr" in d.name.lower()]

    print(f"🔍 Trouvé {len(backtest_dirs)} dossiers de résultats bollinger_atr")

    for result_dir in backtest_dirs:
        try:
            metadata_file = result_dir / "metadata.json"
            if not metadata_file.exists():
                continue

            with open(metadata_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            params = data.get("params", {})
            metrics = data.get("metrics", {})

            # Ne garder que les résultats avec des paramètres bollinger_atr complets
            required_params = ["bb_period", "bb_std", "entry_z", "atr_period", "atr_percentile", "k_sl"]
            if not all(param in params for param in required_params):
                # Essayer les noms alternatifs
                param_mapping = {
                    "entry_z": ["entry_level"],
                    "k_sl": ["sl_level"]
                }

                missing_count = 0
                for param in required_params:
                    if param not in params:
                        alternatives = param_mapping.get(param, [])
                        found_alternative = False
                        for alt in alternatives:
                            if alt in params:
                                params[param] = params[alt]
                                found_alternative = True
                                break
                        if not found_alternative:
                            missing_count += 1

                if missing_count > 2:  # Trop de paramètres manquants
                    continue

            # Extraire informations du nom du dossier
            dir_name = result_dir.name
            parts = dir_name.split('_')
            if len(parts) >= 4:
                strategy = '_'.join(parts[0:-2])  # bollinger_atr
                symbol = parts[-2]  # BTCUSDC
                timeframe = parts[-1].split('_')[0]  # 30m
            else:
                strategy, symbol, timeframe = "bollinger_atr", "UNKNOWN", "UNKNOWN"

            # Valeurs par défaut pour paramètres manquants
            default_values = {
                "bb_period": 20,
                "bb_std": 2.0,
                "entry_z": 2.0,
                "atr_period": 14,
                "atr_percentile": 30,
                "k_sl": 1.5
            }

            row = {
                # Métadonnées
                "strategy": strategy,
                "symbol": symbol,
                "timeframe": timeframe,
                "run_id": data.get("run_id", dir_name),

                # Paramètres (avec valeurs par défaut si manquant)
                "bb_period": params.get("bb_period", default_values["bb_period"]),
                "bb_std": params.get("bb_std", default_values["bb_std"]),
                "entry_z": params.get("entry_z", default_values["entry_z"]),
                "atr_period": params.get("atr_period", default_values["atr_period"]),
                "atr_percentile": params.get("atr_percentile", default_values["atr_percentile"]),
                "k_sl": params.get("k_sl", default_values["k_sl"]),

                # Métriques de performance
                "total_pnl": metrics.get("total_pnl", 0.0),
                "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
                "total_return_pct": metrics.get("total_return_pct", 0.0),
                "max_drawdown_pct": abs(metrics.get("max_drawdown_pct", 0.0)),
                "total_trades": metrics.get("total_trades", 0),
                "win_rate_pct": metrics.get("win_rate_pct", 0.0),
                "profit_factor": metrics.get("profit_factor", 0.0),
                "account_ruined": metrics.get("account_ruined", False),
            }

            results.append(row)

        except Exception as e:
            print(f"⚠️ Erreur lors du chargement de {result_dir}: {e}")
            continue

    df = pd.DataFrame(results)
    print(f"✅ Chargé {len(df)} résultats individuels")

    return df

def analyze_profitable_ranges(df: pd.DataFrame) -> Dict[str, Tuple[float, float]]:
    """Analyse les plages optimales pour chaque paramètre basé sur les résultats profitables"""

    print("\n🎯 Analyse des plages profitables...")

    if len(df) == 0:
        print("❌ Aucune donnée à analyser")
        return {}

    # Filtrer les résultats profitables (PnL > 0 ET Sharpe > 0)
    profitable = df[
        (df["total_pnl"] > 0) &
        (df["sharpe_ratio"] > 0) &
        (df["total_trades"] > 5)  # Minimum de trades pour être significatif
    ].copy()

    print(f"📈 {len(profitable)} résultats profitables sur {len(df)} total ({len(profitable)/len(df)*100:.1f}%)")

    if len(profitable) == 0:
        print("❌ Aucun résultat profitable trouvé")
        return {}

    # Analyser les top 25% des résultats par Sharpe ratio
    top_quartile_threshold = profitable["sharpe_ratio"].quantile(0.75)
    top_results = profitable[profitable["sharpe_ratio"] >= top_quartile_threshold].copy()

    print(f"🏆 {len(top_results)} résultats dans le top 25% (Sharpe >= {top_quartile_threshold:.2f})")

    # Analyser les plages pour chaque paramètre
    param_ranges = {}
    parameters = ["bb_period", "bb_std", "entry_z", "atr_period", "atr_percentile", "k_sl"]

    print("\n📊 Statistiques des paramètres (top 25% des résultats):")
    print("=" * 80)

    for param in parameters:
        if param not in top_results.columns:
            continue

        values = top_results[param].dropna()
        if len(values) == 0:
            continue

        # Statistiques descriptives
        mean_val = values.mean()
        std_val = values.std()
        min_val = values.min()
        max_val = values.max()
        median_val = values.median()
        p25 = values.quantile(0.25)
        p75 = values.quantile(0.75)

        # Plage suggérée : P25 - P75 (quartiles intermédiaires)
        suggested_min = p25
        suggested_max = p75

        # Élargir légèrement si la plage est trop étroite
        if suggested_max - suggested_min < std_val / 2:
            suggested_min = max(min_val, mean_val - std_val)
            suggested_max = min(max_val, mean_val + std_val)

        param_ranges[param] = (suggested_min, suggested_max)

        print(f"{param:15} │ Min: {min_val:6.2f} │ P25: {p25:6.2f} │ Médiane: {median_val:6.2f} │ P75: {p75:6.2f} │ Max: {max_val:6.2f}")
        print(f"{'':15} │ Moyenne: {mean_val:5.2f} │ StdDev: {std_val:5.2f} │ 🎯 Suggéré: [{suggested_min:.2f} - {suggested_max:.2f}]")
        print("-" * 80)

    return param_ranges

def calculate_combination_reduction(current_ranges: Dict, suggested_ranges: Dict) -> None:
    """Calcule la réduction du nombre de combinaisons"""

    print("\n🧮 Calcul de la réduction du nombre de combinaisons:")
    print("=" * 60)

    # Ranges actuels (de bollinger_atr.py)
    current_total = 1
    suggested_total = 1

    param_details = {
        "bb_period": {"current": (10, 50, 1), "type": "int"},
        "bb_std": {"current": (1.5, 3.0, 0.1), "type": "float"},
        "entry_z": {"current": (1.0, 3.0, 0.1), "type": "float"},
        "atr_period": {"current": (7, 21, 1), "type": "int"},
        "atr_percentile": {"current": (0, 60, 1), "type": "int"},
        "k_sl": {"current": (1.0, 3.0, 0.1), "type": "float"},
    }

    for param, info in param_details.items():
        current_min, current_max, step = info["current"]
        param_type = info["type"]

        # Calculer nombre de valeurs actuelles
        if param_type == "int":
            current_count = (current_max - current_min) // step + 1
        else:
            current_count = len(np.arange(current_min, current_max + step/2, step))

        current_total *= current_count

        # Calculer nombre de valeurs suggérées
        if param in suggested_ranges:
            sugg_min, sugg_max = suggested_ranges[param]

            # Arrondir aux valeurs valides selon le step
            if param_type == "int":
                sugg_min = max(current_min, int(sugg_min))
                sugg_max = min(current_max, int(sugg_max))
                suggested_count = (sugg_max - sugg_min) // step + 1
            else:
                sugg_min = max(current_min, round(sugg_min / step) * step)
                sugg_max = min(current_max, round(sugg_max / step) * step)
                suggested_count = len(np.arange(sugg_min, sugg_max + step/2, step))

            suggested_total *= suggested_count

            reduction_pct = (1 - suggested_count / current_count) * 100

            print(f"{param:15} │ Actuel: {current_count:3d} │ Suggéré: {suggested_count:3d} │ Réduction: {reduction_pct:5.1f}%")
        else:
            suggested_total *= current_count
            print(f"{param:15} │ Actuel: {current_count:3d} │ Suggéré: {current_count:3d} │ Réduction:   0.0%")

    print("-" * 60)
    print(f"🔥 TOTAL ACTUEL     : {current_total:,} combinaisons")
    print(f"🎯 TOTAL SUGGÉRÉ    : {suggested_total:,} combinaisons")

    if current_total > 0:
        total_reduction_pct = (1 - suggested_total / current_total) * 100
        speedup_factor = current_total / suggested_total if suggested_total > 0 else float('inf')

        print(f"⚡ RÉDUCTION GLOBALE : {total_reduction_pct:.1f}%")
        print(f"🚀 ACCÉLÉRATION     : {speedup_factor:.1f}x plus rapide")

        # Temps estimés
        time_current_hours = current_total / (100 * 3600)  # 100 bt/s
        time_suggested_hours = suggested_total / (100 * 3600)

        print(f"⏱️ TEMPS ACTUEL     : {time_current_hours:.1f} heures")
        print(f"⏱️ TEMPS SUGGÉRÉ    : {time_suggested_hours:.1f} heures")

def generate_optimized_parameter_specs(suggested_ranges: Dict) -> str:
    """Génère le code Python pour les parameter_specs optimisés"""

    code = '''    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        """Spécifications optimisées basées sur l'analyse des résultats profitables.

        🎯 RANGES OPTIMISÉS via analyse de données réelles :
        - Analyse de {total_results} résultats de backtest
        - Focus sur top 25% des résultats par Sharpe ratio
        - Réduction des combinaisons : {reduction}% ({combo_before:,} → {combo_after:,})
        - Accélération estimée : {speedup}x plus rapide
        """
        return {{'''

    param_configs = {
        "bb_period": {
            "original": (10, 50, 1),
            "type": "int",
            "description": "Période des Bandes de Bollinger"
        },
        "bb_std": {
            "original": (1.5, 3.0, 0.1),
            "type": "float",
            "description": "Écarts-types pour les bandes"
        },
        "entry_z": {
            "original": (1.0, 3.0, 0.1),
            "type": "float",
            "description": "Seuil z-score pour entree"
        },
        "atr_period": {
            "original": (7, 21, 1),
            "type": "int",
            "description": "Période de l'ATR"
        },
        "atr_percentile": {
            "original": (0, 60, 1),
            "type": "int",
            "description": "Percentile volatilite minimum (ATR)"
        },
        "k_sl": {
            "original": (1.0, 3.0, 0.1),
            "type": "float",
            "description": "Multiplicateur ATR pour stop-loss"
        },
    }

    # Calculer les totaux pour les placeholders
    total_before = 1
    total_after = 1

    for param, config in param_configs.items():
        orig_min, orig_max, step = config["original"]
        param_type = config["type"]

        if param_type == "int":
            orig_count = (orig_max - orig_min) // step + 1
        else:
            orig_count = len(np.arange(orig_min, orig_max + step/2, step))

        total_before *= orig_count

        if param in suggested_ranges:
            sugg_min, sugg_max = suggested_ranges[param]
            if param_type == "int":
                sugg_min = max(orig_min, int(sugg_min))
                sugg_max = min(orig_max, int(sugg_max))
                sugg_count = (sugg_max - sugg_min) // step + 1
            else:
                sugg_min = max(orig_min, round(sugg_min / step) * step)
                sugg_max = min(orig_max, round(sugg_max / step) * step)
                sugg_count = len(np.arange(sugg_min, sugg_max + step/2, step))

            total_after *= sugg_count
        else:
            total_after *= orig_count

    reduction_pct = (1 - total_after / total_before) * 100 if total_before > 0 else 0
    speedup = total_before / total_after if total_after > 0 else float('inf')

    # Générer le code pour chaque paramètre
    for param, config in param_configs.items():
        orig_min, orig_max, step = config["original"]
        param_type = config["type"]
        description = config["description"]

        if param in suggested_ranges:
            sugg_min, sugg_max = suggested_ranges[param]

            if param_type == "int":
                sugg_min = max(orig_min, int(sugg_min))
                sugg_max = min(orig_max, int(sugg_max))
                default_val = int((sugg_min + sugg_max) / 2)
            else:
                sugg_min = max(orig_min, round(sugg_min / step) * step)
                sugg_max = min(orig_max, round(sugg_max / step) * step)
                default_val = round((sugg_min + sugg_max) / 2, 1)

            code += f'''
            "{param}": ParameterSpec(
                name="{param}",
                min_val={sugg_min}, max_val={sugg_max}, default={default_val},  # 🎯 Optimisé: était ({orig_min}-{orig_max})
                param_type="{param_type}",
                description="{description}"
            ),'''
        else:
            # Garder les valeurs originales si pas de suggestion
            default_val = int((orig_min + orig_max) / 2) if param_type == "int" else round((orig_min + orig_max) / 2, 1)
            code += f'''
            "{param}": ParameterSpec(
                name="{param}",
                min_val={orig_min}, max_val={orig_max}, default={default_val},  # Original (pas assez de données)
                param_type="{param_type}",
                description="{description}"
            ),'''

    code += '''
            "leverage": ParameterSpec(
                name="leverage",
                min_val=1, max_val=10, default=1,
                param_type="int",
                description="Levier de trading (non optimisé)",
                optimize=False,
            ),
        }'''

    # Remplacer les placeholders
    code = code.replace("{total_results}", "XXX")  # À remplir manuellement
    code = code.replace("{reduction}", f"{reduction_pct:.1f}")
    code = code.replace("{combo_before}", str(total_before))
    code = code.replace("{combo_after}", str(total_after))
    code = code.replace("{speedup}", f"{speedup:.1f}")

    return code

def main():
    """Fonction principale d'analyse"""

    print("🔍 ANALYSE DES RÉSULTATS BOLLINGER ATR")
    print("=" * 50)

    # Charger les données
    df = load_bollinger_atr_results()

    if len(df) == 0:
        print("❌ Aucune donnée trouvée. Vérifiez que des sweeps bollinger_atr existent.")
        return

    # Analyser les plages profitables
    suggested_ranges = analyze_profitable_ranges(df)

    # Calculer la réduction des combinaisons
    calculate_combination_reduction({}, suggested_ranges)

    # Générer le code optimisé
    optimized_code = generate_optimized_parameter_specs(suggested_ranges)

    print("\n💾 CODE OPTIMISÉ GÉNÉRÉ:")
    print("=" * 50)
    print(optimized_code)

    # Sauvegarder dans un fichier
    output_file = "bollinger_atr_optimized_ranges.py"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Code optimisé pour bollinger_atr parameter_specs\n")
        f.write("# Généré automatiquement par analyse des résultats\n\n")
        f.write(optimized_code)

    print(f"\n✅ Code sauvegardé dans: {output_file}")
    print("\n🎯 NEXT STEPS:")
    print("1. Copier le code généré dans strategies/bollinger_atr.py")
    print("2. Tester avec un petit sweep pour valider les performances")
    print("3. Lancer un multi-sweep complet avec les nouvelles plages")

if __name__ == "__main__":
    main()
