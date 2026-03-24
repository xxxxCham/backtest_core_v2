"""
Script de profiling pour identifier les goulots d'étranglement dans les sweeps.
"""
import cProfile
import io
import pstats
from pstats import SortKey

from backtest.engine import BacktestEngine
from backtest.result_store import get_profiling_results_dir
from data.loader import load_ohlcv


def profile_sweep():
    """Profile un petit sweep de 20 backtests."""
    print("=" * 80)
    print("PROFILING SWEEP - Identification des goulots d'étranglement")
    print("=" * 80)

    # Charger données
    print("\n[1/3] Chargement données BTCUSDC/30m...")
    df = load_ohlcv("BTCUSDC", "30m")
    print(f"✓ {len(df):,} barres chargées")

    # Préparer stratégie
    strategy_key = "bollinger_atr"

    # Générer 20 combinaisons de paramètres
    print(f"\n[2/3] Préparation sweep {strategy_key}...")
    param_combos = []
    for entry_z in [1.5, 2.0, 2.5]:
        for k_sl in [1.0, 1.5, 2.0]:
            for leverage in [1, 3]:
                param_combos.append({
                    "entry_z": entry_z,
                    "k_sl": k_sl,
                    "leverage": leverage,
                    "bb_period": 20,
                    "bb_std_dev": 2.0,
                    "atr_period": 14,
                })

    print(f"✓ {len(param_combos)} combinaisons générées")

    # Profiler l'exécution
    print(f"\n[3/3] Profiling {len(param_combos)} backtests...")

    profiler = cProfile.Profile()
    profiler.enable()

    # Exécuter le sweep
    engine = BacktestEngine(initial_capital=10000)
    results = []

    for i, params in enumerate(param_combos, 1):
        try:
            result = engine.run(
                df=df,
                strategy=strategy_key,
                params=params,
                symbol="BTCUSDC",
                timeframe="30m",
                silent_mode=True,
                fast_metrics=True
            )
            results.append(result)

            if i % 5 == 0:
                print(f"  {i}/{len(param_combos)} backtests terminés...")
        except Exception as e:
            print(f"  ❌ Backtest {i} échoué: {e}")

    profiler.disable()

    # Analyser les résultats
    print("\n" + "=" * 80)
    print("RÉSULTATS DU PROFILING")
    print("=" * 80)

    # Statistiques de base
    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s)
    ps.strip_dirs()

    # Top 30 fonctions par temps cumulé
    print("\n📊 TOP 30 FONCTIONS PAR TEMPS CUMULÉ:")
    print("-" * 80)
    ps.sort_stats(SortKey.CUMULATIVE)
    ps.print_stats(30)
    print(s.getvalue())

    # Rechercher spécifiquement les fonctions critiques
    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s)
    ps.strip_dirs()

    print("\n" + "=" * 80)
    print("🔍 ANALYSE DÉTAILLÉE DES INDICATEURS")
    print("=" * 80)

    # Filtrer les fonctions d'indicateurs
    ps.sort_stats(SortKey.CUMULATIVE)
    ps.print_stats('bollinger|atr|rsi|ema|calculate_indicator')
    print(s.getvalue())

    # Vérifier si le cache est utilisé
    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s)
    ps.strip_dirs()

    print("\n" + "=" * 80)
    print("💾 ANALYSE DU CACHE")
    print("=" * 80)

    ps.sort_stats(SortKey.CUMULATIVE)
    ps.print_stats('cache|get_indicator|put')
    cache_output = s.getvalue()
    print(cache_output)

    if 'get_indicator_bank' in cache_output or '_worker_indicator_cache' in cache_output:
        print("✓ Cache détecté dans le profiling")
    else:
        print("❌ PROBLÈME: Aucune fonction de cache détectée!")
        print("   → Les indicateurs sont recalculés à chaque fois")

    # Résumé
    print("\n" + "=" * 80)
    print("📈 RÉSUMÉ")
    print("=" * 80)
    print(f"Backtests réussis: {len(results)}/{len(param_combos)}")

    # Calculer le temps total
    total_time = sum(stat[3] for stat in ps.stats.values())
    avg_time_per_bt = total_time / len(param_combos) if param_combos else 0

    print(f"Temps total: {total_time:.2f}s")
    print(f"Temps moyen/backtest: {avg_time_per_bt:.3f}s")
    print(f"Débit: {len(param_combos)/total_time:.1f} backtests/sec")

    # Sauvegarder le profiling complet
    profiling_dir = get_profiling_results_dir()
    profiling_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profiling_dir / "sweep_profile.prof"
    profiler.dump_stats(str(profile_path))
    print(f"\n✓ Profiling complet sauvegardé: {profile_path}")
    print(f"  Analysez avec: python -m pstats {profile_path}")


if __name__ == "__main__":
    profile_sweep()
