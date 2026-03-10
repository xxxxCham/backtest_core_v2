#!/usr/bin/env python3
"""
🧪 Quick Lab Launcher - Backtest Core

Script de lancement rapide pour les outils du laboratoire
"""

import os
from pathlib import Path


def main():
    """Menu principal du laboratoire"""

    print("🧪 LABORATOIRE DE RECHERCHE - BACKTEST CORE")
    print("=" * 50)
    print()

    while True:
        print("Choisissez une action:")
        print("1. 🔍 Analyser les résultats Bollinger ATR")
        print("2. 📊 Diagnostic approfondi Bollinger ATR")
        print("3. 🐛 Debug simulateur complet")
        print("4. ⚡ Debug sweep bloqué")
        print("5. 🎯 Reproduire bug MACD -inf")
        print("6. 💻 Diagnostic GPU/performance")
        print("7. 📁 Voir structure du laboratoire")
        print("0. ❌ Quitter")
        print()

        choice = input("Votre choix (0-7): ").strip()

        if choice == "0":
            print("👋 Au revoir !")
            break
        elif choice == "1":
            run_script("analysis/analyze_bollinger_atr_results.py")
        elif choice == "2":
            run_script("analysis/detailed_bollinger_analysis.py")
        elif choice == "3":
            run_script("debug/debug_full_simulator.py")
        elif choice == "4":
            run_script("debug/diagnostic_sweep_blocked.py")
        elif choice == "5":
            run_script("debug/reproduce_macd_inf.py")
        elif choice == "6":
            run_script("debug/diagnose_gpu.py")
        elif choice == "7":
            show_lab_structure()
        else:
            print("❌ Choix invalide. Veuillez choisir entre 0 et 7.")

        print("\n" + "="*50 + "\n")

def run_script(script_path):
    """Exécute un script du laboratoire"""
    labs_dir = Path(__file__).parent
    script_full_path = labs_dir / script_path

    if not script_full_path.exists():
        print(f"❌ Script non trouvé: {script_path}")
        return

    print(f"🚀 Exécution de {script_path}...")
    print("-" * 30)

    # Changer vers le répertoire racine pour les imports
    original_dir = os.getcwd()
    os.chdir(labs_dir.parent)

    try:
        # Exécuter le script avec context manager
        with open(script_full_path, 'r', encoding='utf-8') as f:
            code = compile(f.read(), str(script_full_path), 'exec')
            exec(code, {"__name__": "__main__"})
    except Exception as e:
        print(f"❌ Erreur lors de l'exécution: {e}")
    finally:
        os.chdir(original_dir)

def show_lab_structure():
    """Affiche la structure du laboratoire"""
    labs_dir = Path(__file__).parent

    print("📁 STRUCTURE DU LABORATOIRE:")
    print("-" * 30)

    for subdir in ["analysis", "debug", "optimization", "performance"]:
        subdir_path = labs_dir / subdir
        if subdir_path.exists():
            files = list(subdir_path.glob("*.py"))
            print(f"📂 {subdir}/ ({len(files)} fichiers)")
            for file in sorted(files):
                print(f"   📄 {file.name}")
        else:
            print(f"📂 {subdir}/ (vide)")
        print()

if __name__ == "__main__":
    main()
