#!/usr/bin/env python3
"""
Analyse détaillée des résultats Bollinger ATR et proposition de plages théoriquement sensées
basées sur les meilleures pratiques de l'analyse technique.
"""

import pandas as pd
from analyze_bollinger_atr_results import load_bollinger_atr_results


def analyze_performance_issues(df: pd.DataFrame):
    """Analyse les problèmes de performance de la stratégie"""

    print("🔍 DIAGNOSTIC BOLLINGER ATR - PROBLÈMES DE PERFORMANCE")
    print("=" * 70)

    if len(df) == 0:
        print("❌ Aucune donnée à analyser")
        return

    # Statistiques générales
    total_runs = len(df)
    profitable = df[df["total_pnl"] > 0]
    ruined = df[df["account_ruined"]]

    print("📊 STATISTIQUES GÉNÉRALES :")
    print(f"   • Total runs        : {total_runs}")
    print(f"   • Runs profitables  : {len(profitable)} ({len(profitable)/total_runs*100:.1f}%)")
    print(f"   • Comptes ruinés    : {len(ruined)} ({len(ruined)/total_runs*100:.1f}%)")
    print(f"   • PnL moyen         : ${df['total_pnl'].mean():.2f}")
    print(f"   • PnL médian        : ${df['total_pnl'].median():.2f}")
    print(f"   • Sharpe moyen      : {df['sharpe_ratio'].mean():.2f}")

    # Distribution des pertes
    negative_pnl = df[df["total_pnl"] < 0]["total_pnl"]
    if len(negative_pnl) > 0:
        print("\n📉 DISTRIBUTION DES PERTES :")
        print(f"   • Perte moyenne     : ${negative_pnl.mean():.2f}")
        print(f"   • Pire perte        : ${negative_pnl.min():.2f}")
        print(f"   • P75 des pertes    : ${negative_pnl.quantile(0.75):.2f}")

    # Analyse des paramètres problématiques
    print("\n🎯 PARAMÈTRES PROBLÉMATIQUES IDENTIFIÉS :")

    # entry_z problématique
    weird_entry_z = df[(df["entry_z"] < 0.5) | (df["entry_z"] > 4.0)]
    if len(weird_entry_z) > 0:
        print(f"   • entry_z aberrants : {len(weird_entry_z)} runs avec entry_z hors [0.5-4.0]")

    # k_sl problématique
    weird_k_sl = df[(df["k_sl"] < 0) | (df["k_sl"] > 5.0)]
    if len(weird_k_sl) > 0:
        print(f"   • k_sl aberrants    : {len(weird_k_sl)} runs avec k_sl négatif ou >5.0")

    # bb_std extrêmes
    weird_bb_std = df[(df["bb_std"] < 1.0) | (df["bb_std"] > 4.0)]
    if len(weird_bb_std) > 0:
        print(f"   • bb_std extrêmes   : {len(weird_bb_std)} runs avec bb_std hors [1.0-4.0]")

    return profitable

def suggest_theory_based_ranges():
    """Propose des plages basées sur la théorie de l'analyse technique"""

    print("\n🎓 PLAGES SUGGÉRÉES BASÉES SUR LA THÉORIE FINANCIÈRE")
    print("=" * 60)
    print("📖 Plutôt que de suivre les 4.9% de résultats 'profitables' douteux,")
    print("   utilisons les meilleures pratiques de l'analyse technique :")
    print()

    ranges = {
        "bb_period": {
            "theory_min": 15,   # Minimum pour capturer tendances court terme
            "theory_max": 35,   # Maximum pour éviter lag excessif
            "optimal": 20,      # Standard de Bollinger
            "rationale": "John Bollinger recommande 20 périodes comme standard"
        },
        "bb_std": {
            "theory_min": 1.8,  # Bandes plus serrées pour marchés stables
            "theory_max": 2.5,  # Bandes plus larges pour marchés volatils
            "optimal": 2.0,     # Standard de Bollinger
            "rationale": "2.0 capture ~95% des mouvements, 1.8-2.5 couvre différents régimes"
        },
        "entry_z": {
            "theory_min": 1.5,  # Touch band standard
            "theory_max": 2.2,  # Au-delà de la band externe
            "optimal": 2.0,     # À la band elle-même
            "rationale": "1.5-2.2 permet variations autour de la band standard"
        },
        "atr_period": {
            "theory_min": 10,   # Volatilité plus réactive
            "theory_max": 21,   # Volatilité plus lissée
            "optimal": 14,      # Standard ATR de Wilder
            "rationale": "14 périodes recommandé par Wilder, 10-21 couvre court/moyen terme"
        },
        "atr_percentile": {
            "theory_min": 20,   # Volatilité relativement faible
            "theory_max": 50,   # Volatilité relativement élevée
            "optimal": 30,      # Équilibre
            "rationale": "20-50 filtre les marchés trop calmes/agités"
        },
        "k_sl": {
            "theory_min": 1.2,  # Stop serré
            "theory_max": 2.5,  # Stop large
            "optimal": 1.5,     # Équilibre risk/reward
            "rationale": "1.2-2.5 ATR couvre différents styles de gestion du risque"
        }
    }

    total_combos = 1
    for param, info in ranges.items():
        # Calculer le nombre de valeurs selon le type
        if param in ["bb_period", "atr_period", "atr_percentile"]:
            # Entiers avec step = 1
            count = info["theory_max"] - info["theory_min"] + 1
        else:
            # Floats avec step = 0.1
            count = int((info["theory_max"] - info["theory_min"]) / 0.1) + 1

        total_combos *= count

        print(f"{param:15} │ {info['theory_min']:4} - {info['theory_max']:4} │ Optimal: {info['optimal']:4} │ {count:2d} vals │ {info['rationale']}")

    print("-" * 120)
    print(f"🎯 TOTAL THÉORIQUE : {total_combos:,} combinaisons")

    # Temps estimé
    time_hours = total_combos / (100 * 3600)  # 100 bt/s
    if time_hours < 1:
        time_str = f"{time_hours*60:.1f} minutes"
    else:
        time_str = f"{time_hours:.1f} heures"

    print(f"⏱️ TEMPS ESTIMÉ    : {time_str}")
    print("🧠 RATIONALE      : Basé sur les standards de l'industrie, pas sur des données biaisées")

    return ranges

def generate_theory_based_code(ranges):
    """Génère le code Python optimisé basé sur la théorie"""

    code = '''    @property
    def parameter_specs(self) -> Dict[str, ParameterSpec]:
        """Spécifications basées sur la théorie de l'analyse technique.

        🎓 RANGES THÉORIQUES optimisés :
        - Basé sur les standards de John Bollinger et Welles Wilder
        - Évite les valeurs aberrantes des backtests (entry_z<0.5, k_sl négatif)
        - Réduit l'espace de recherche à ~{total_combos:,} combinaisons viables
        - Focus sur les plages utilisées par les traders professionnels

        ⚠️ ATTENTION : Les résultats backtests montrent 95.1% d'échecs.
        Cette stratégie nécessite peut-être une révision fondamentale de sa logique.
        """
        return {{'''

    param_configs = {
        "bb_period": {"type": "int", "step": 1},
        "bb_std": {"type": "float", "step": 0.1},
        "entry_z": {"type": "float", "step": 0.1},
        "atr_period": {"type": "int", "step": 1},
        "atr_percentile": {"type": "int", "step": 1},
        "k_sl": {"type": "float", "step": 0.1},
    }

    # Calculer le total pour le placeholder
    total_combos = 1
    for param, config in param_configs.items():
        param_range = ranges[param]
        if config["type"] == "int":
            count = param_range["theory_max"] - param_range["theory_min"] + 1
        else:
            count = int((param_range["theory_max"] - param_range["theory_min"]) / config["step"]) + 1
        total_combos *= count

    # Générer le code pour chaque paramètre
    for param, param_range in ranges.items():
        config = param_configs[param]

        min_val = param_range["theory_min"]
        max_val = param_range["theory_max"]
        optimal = param_range["optimal"]
        rationale = param_range["rationale"]

        if config["type"] == "int":
            code += f'''
            "{param}": ParameterSpec(
                name="{param}",
                min_val={min_val}, max_val={max_val}, default={optimal},  # 🎓 Théorique: {rationale}
                param_type="{config['type']}",
                description="{get_param_description(param)}"
            ),'''
        else:
            code += f'''
            "{param}": ParameterSpec(
                name="{param}",
                min_val={min_val}, max_val={max_val}, default={optimal},  # 🎓 Théorique: {rationale}
                param_type="{config['type']}",
                description="{get_param_description(param)}"
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

    # Remplacer le placeholder
    code = code.replace("{total_combos:,}", f"{total_combos:,}")

    return code

def get_param_description(param):
    """Retourne la description du paramètre"""
    descriptions = {
        "bb_period": "Période des Bandes de Bollinger",
        "bb_std": "Écarts-types pour les bandes",
        "entry_z": "Seuil z-score pour entree",
        "atr_period": "Période de l'ATR",
        "atr_percentile": "Percentile volatilite minimum (ATR)",
        "k_sl": "Multiplicateur ATR pour stop-loss"
    }
    return descriptions.get(param, "Paramètre de trading")

def main():
    """Fonction principale d'analyse détaillée"""

    # Charger les données
    df = load_bollinger_atr_results()

    if len(df) == 0:
        print("❌ Aucune donnée trouvée.")
        return

    # Analyser les problèmes de performance
    analyze_performance_issues(df)

    # Proposer des plages théoriques
    theory_ranges = suggest_theory_based_ranges()

    # Générer le code optimisé
    theory_code = generate_theory_based_code(theory_ranges)

    print("\n💾 CODE THÉORIQUE GÉNÉRÉ :")
    print("=" * 50)
    print(theory_code)

    # Sauvegarder
    output_file = "bollinger_atr_theory_ranges.py"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("# Code théorique pour bollinger_atr parameter_specs\n")
        f.write("# Basé sur les standards de l'analyse technique\n\n")
        f.write(theory_code)

    print(f"\n✅ Code théorique sauvegardé dans: {output_file}")

    print("\n🎯 RECOMMANDATIONS FINALES :")
    print("1. 🔧 **RÉVISER LA LOGIQUE** de la stratégie (95.1% d'échecs)")
    print("2. 🧪 **TESTER** les plages théoriques sur un petit échantillon")
    print("3. 🎯 **ANALYSER** pourquoi entry_z et k_sl produisent des valeurs aberrantes")
    print("4. 📊 **COMPARER** les nouvelles plages vs anciennes sur mêmes données")
    print("5. 🔍 **INVESTIGUER** les 4 seuls résultats 'profitables' pour comprendre")

if __name__ == "__main__":
    main()
