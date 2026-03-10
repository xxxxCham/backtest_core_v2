#!/usr/bin/env python3
"""
🚨 DIAGNOSTIC SWEEP BOLLINGER ATR - Problème de grille gigantesque
================================================================

Ce script diagnostique pourquoi le sweep multi-tokens/timeframes se bloque
et propose des solutions pour réduire l'espace de recherche.
"""

def calculate_bollinger_atr_grid_size():
    """Calcule la taille de la grille Bollinger ATR"""

    # Paramètres bollinger_atr avec leurs plages
    params = {
        "bb_period": {"min": 10, "max": 50, "step": 1},      # 41 valeurs
        "bb_std": {"min": 1.5, "max": 3.0, "step": 0.1},    # 16 valeurs
        "entry_z": {"min": 1.0, "max": 3.0, "step": 0.1},   # 21 valeurs
        "atr_period": {"min": 7, "max": 21, "step": 1},     # 15 valeurs
        "atr_percentile": {"min": 0, "max": 60, "step": 1}, # 61 valeurs
        "k_sl": {"min": 1.0, "max": 3.0, "step": 0.1},      # 21 valeurs
    }

    total_combinations = 1
    param_counts = {}

    print("📊 ANALYSE ESPACE DE RECHERCHE BOLLINGER ATR")
    print("=" * 50)

    for param, config in params.items():
        if config["step"] == 1:
            # Paramètre entier
            count = config["max"] - config["min"] + 1
        else:
            # Paramètre float
            import numpy as np
            values = np.arange(config["min"], config["max"] + config["step"]/2, config["step"])
            count = len(values)

        param_counts[param] = count
        total_combinations *= count
        print(f"  {param:15} : {config['min']:4} → {config['max']:4} = {count:3} valeurs")

    print("\n🔥 RÉSULTAT TOTAL:")
    calculation = " × ".join([f"{count}" for count in param_counts.values()])
    print(f"  {calculation}")
    print(f"  = {total_combinations:,} combinaisons")

    # Estimation taille mémoire (très approximative)
    bytes_per_combo = 200  # Dict Python + overhead
    total_mb = (total_combinations * bytes_per_combo) / (1024 * 1024)
    print(f"  ≈ {total_mb:,.0f} MB juste pour la grille en mémoire")

    # Temps d'exécution estimé
    bt_per_sec = 100  # Optimiste avec parallélisme
    total_hours = total_combinations / bt_per_sec / 3600
    print(f"  ≈ {total_hours:,.0f} heures à 100 bt/s")

    return total_combinations, param_counts

def propose_solutions():
    """Propose des solutions pour réduire l'espace de recherche"""

    print("\n🎯 SOLUTIONS RECOMMANDÉES")
    print("=" * 30)

    print("\n1️⃣ RÉDUCTION DRASTIQUE DES PLAGES:")
    print("   bb_period: 15-30 (au lieu de 10-50) → 16 valeurs")
    print("   bb_std: 1.8-2.5 step=0.1 → 8 valeurs")
    print("   entry_z: 1.5-2.5 step=0.2 → 6 valeurs")
    print("   atr_period: 10-20 → 11 valeurs")
    print("   atr_percentile: 10-50 step=10 → 5 valeurs")
    print("   k_sl: 1.2-2.0 step=0.2 → 5 valeurs")
    print("   → 16×8×6×11×5×5 = 211,200 combinaisons (gérable !)")

    print("\n2️⃣ UTILISER OPTUNA (OPTIMISATION BAYÉSIENNE):")
    print("   Au lieu de tester TOUTES les combinaisons,")
    print("   Optuna teste intelligemment ~1000-5000 points")
    print("   → 1000x plus rapide !")

    print("\n3️⃣ SWEEP SÉQUENTIEL PAR PARAMÈTRE:")
    print("   Fixer 5 paramètres, optimiser 1 seul")
    print("   Puis fixer le meilleur, optimiser le suivant")
    print("   → 41+16+21+15+61+21 = 175 runs seulement")

    print("\n4️⃣ UTILISER MAX_COMBOS LIMITE:")
    print("   L'interface a max_combos=50000 par défaut")
    print("   Augmenter à 100K-500K max pour tests")

def create_reduced_params():
    """Crée des paramètres réduits pour test rapide"""

    print("\n💡 PARAMÈTRES RÉDUITS POUR TEST:")
    print("=" * 35)

    reduced = {
        "bb_period": [15, 20, 25, 30],           # 4 valeurs
        "bb_std": [1.8, 2.0, 2.2, 2.5],         # 4 valeurs
        "entry_z": [1.5, 2.0, 2.5],             # 3 valeurs
        "atr_period": [10, 14, 18],              # 3 valeurs
        "atr_percentile": [20, 30, 40],          # 3 valeurs
        "k_sl": [1.2, 1.5, 2.0],                # 3 valeurs
    }

    total = 1
    for param, values in reduced.items():
        count = len(values)
        total *= count
        print(f"  {param:15} : {values} → {count} valeurs")

    print(f"\n  TOTAL RÉDUIT : {total:,} combinaisons")
    print(f"  Temps estimé : ~{total/100/60:.0f} minutes à 100 bt/s")

    return reduced

if __name__ == "__main__":
    print("🚨 DIAGNOSTIC BOLLINGER ATR SWEEP BLOQUÉ")
    print("==========================================")

    total_combos, param_counts = calculate_bollinger_atr_grid_size()

    if total_combos > 1_000_000:
        print("\n❌ PROBLÈME DÉTECTÉ: Grille trop grande!")
        print("   Le système se bloque en essayant de générer")
        print("   675 millions de combinaisons en mémoire.")
        print("   C'est pourquoi ça ne démarre pas depuis 15min.")

    propose_solutions()
    create_reduced_params()

    print("\n🔧 ACTIONS RECOMMANDÉES:")
    print("1. Réduire les plages de paramètres")
    print("2. Utiliser Optuna au lieu de Grid Search")
    print("3. Tester sur 1 seul token/timeframe d'abord")
    print("4. Augmenter max_combos si nécessaire")
