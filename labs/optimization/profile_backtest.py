#!/usr/bin/env python3
"""
Script de profiling complet pour identifier les goulots d'étranglement.

Usage:
    python profile_backtest.py                    # Profiling complet
    python profile_backtest.py --quick            # Profiling rapide (1000 barres)
    python profile_backtest.py --detailed         # Profiling ligne par ligne
    python profile_backtest.py --memory           # Profiling mémoire
"""

import cProfile
import io
import math
import os
import pstats
import sys
import time
from pathlib import Path
from typing import Optional

# Ajouter le répertoire racine au PYTHONPATH
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

import numpy as np
import pandas as pd


def create_test_data(n_bars: int = 10000) -> pd.DataFrame:
    """Crée des données OHLCV de test."""
    np.random.seed(42)

    # Générer un prix avec tendance + bruit
    base_price = 100.0
    returns = np.random.normal(0.0001, 0.02, n_bars)
    prices = base_price * np.exp(np.cumsum(returns))

    # Créer OHLCV
    high = prices * (1 + np.abs(np.random.normal(0, 0.01, n_bars)))
    low = prices * (1 - np.abs(np.random.normal(0, 0.01, n_bars)))
    open_ = prices + np.random.normal(0, 0.5, n_bars)
    volume = np.random.uniform(1000, 10000, n_bars)

    # Index temporel
    dates = pd.date_range(start="2020-01-01", periods=n_bars, freq="1h")

    df = pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": prices,
        "volume": volume,
    }, index=dates)

    return df


def profile_indicators(df: pd.DataFrame, iterations: int = 10) -> dict:
    """Profile tous les indicateurs."""
    from indicators.registry import calculate_indicator

    results = {}
    indicators_to_test = [
        ("bollinger", {"period": 20, "std_dev": 2.0}),
        ("atr", {"period": 14}),
        ("rsi", {"period": 14}),
        ("ema", {"period": 20}),
        ("macd", {"fast_period": 12, "slow_period": 26, "signal_period": 9}),
        ("stochastic", {"k_period": 14, "d_period": 3}),
        ("adx", {"period": 14}),
        ("supertrend", {"period": 10, "multiplier": 3.0}),
        ("vwap", {}),
    ]

    print("\n" + "="*60)
    print("📊 PROFILING INDICATEURS")
    print("="*60)

    for name, params in indicators_to_test:
        try:
            # Warmup
            calculate_indicator(name, df, params)

            # Mesure
            times = []
            for _ in range(iterations):
                start = time.perf_counter()
                calculate_indicator(name, df, params)
                times.append(time.perf_counter() - start)

            avg_time = np.mean(times) * 1000  # ms
            std_time = np.std(times) * 1000

            results[name] = {
                "avg_ms": avg_time,
                "std_ms": std_time,
                "calls_per_sec": 1000 / avg_time if avg_time > 0 else 0,
            }

            speed_icon = "🚀" if avg_time < 5 else "⚡" if avg_time < 20 else "🐢"
            print(f"{speed_icon} {name:20s}: {avg_time:8.2f}ms ± {std_time:.2f}ms ({results[name]['calls_per_sec']:.0f}/s)")

        except Exception as e:
            print(f"❌ {name:20s}: Erreur - {e}")

    return results


def profile_simulator(df: pd.DataFrame, iterations: int = 5) -> dict:
    """Profile le simulateur de trades."""
    from backtest.simulator import simulate_trades
    from backtest.simulator_fast import HAS_NUMBA, simulate_trades_fast

    results = {}

    print("\n" + "="*60)
    print("🎯 PROFILING SIMULATEUR")
    print(f"   Numba: {'✅ Activé' if HAS_NUMBA else '❌ Désactivé (LENT!)'}")
    print("="*60)

    # Générer des signaux de test
    np.random.seed(42)
    n = len(df)
    signals = np.zeros(n)
    # Créer ~50 trades
    trade_points = np.random.choice(n, size=100, replace=False)
    trade_points.sort()
    for i in range(0, len(trade_points), 2):
        if i + 1 < len(trade_points):
            signals[trade_points[i]] = 1  # Entry
            signals[trade_points[i+1]] = 0  # Exit

    signals_series = pd.Series(signals, index=df.index)

    # Paramètres pour le simulateur (nouvelle API)
    params = {
        "initial_capital": 10000.0,
        "position_size": 0.1,
        "fees_bps": 10,
        "slippage_bps": 5,
        "k_sl": 0.02,
        "leverage": 1.0,
    }

    # Test simulator_fast
    print("\n🔥 simulate_trades_fast (Numba):")
    times_fast = []
    trades_fast = None
    for _ in range(iterations):
        start = time.perf_counter()
        trades_fast = simulate_trades_fast(df=df, signals=signals_series, params=params)
        times_fast.append(time.perf_counter() - start)

    avg_fast = np.mean(times_fast) * 1000
    num_trades_fast = len(trades_fast) if trades_fast is not None else 0
    results["simulator_fast"] = {
        "avg_ms": avg_fast,
        "trades": num_trades_fast,
        "bt_per_sec": 1000 / avg_fast if avg_fast > 0 else 0,
    }
    print(f"   Temps moyen: {avg_fast:.2f}ms ({results['simulator_fast']['bt_per_sec']:.0f} bt/s)")
    print(f"   Trades générés: {num_trades_fast}")

    # Test simulator lent (référence)
    print("\n🐢 simulate_trades (Python pur):")
    times_slow = []
    trades_slow = None
    for _ in range(min(iterations, 2)):  # Moins d'itérations car lent
        start = time.perf_counter()
        trades_slow = simulate_trades(df=df, signals=signals_series, params=params)
        times_slow.append(time.perf_counter() - start)

    avg_slow = np.mean(times_slow) * 1000
    num_trades_slow = len(trades_slow) if trades_slow is not None else 0
    results["simulator_slow"] = {
        "avg_ms": avg_slow,
        "trades": num_trades_slow,
        "bt_per_sec": 1000 / avg_slow if avg_slow > 0 else 0,
    }
    print(f"   Temps moyen: {avg_slow:.2f}ms ({results['simulator_slow']['bt_per_sec']:.0f} bt/s)")

    # Ratio d'accélération
    speedup = avg_slow / avg_fast if avg_fast > 0 else 0
    print(f"\n📈 Accélération Numba: {speedup:.1f}x plus rapide")

    return results


def profile_engine(df: pd.DataFrame, iterations: int = 3) -> dict:
    """Profile le moteur de backtest complet."""
    from backtest.engine import BacktestEngine
    from strategies import get_strategy
    from utils.config import Config

    results = {}

    print("\n" + "="*60)
    print("🔧 PROFILING MOTEUR COMPLET")
    print("="*60)

    strategies_to_test = ["ema_cross", "rsi_reversal", "macd_cross"]
    config = Config(fees_bps=10, slippage_bps=5)

    for strategy_name in strategies_to_test:
        try:
            strategy_class = get_strategy(strategy_name)
            if strategy_class is None:
                continue

            strategy = strategy_class()  # Instancier la stratégie
            engine = BacktestEngine(initial_capital=10000.0, config=config)

            # Warmup
            engine.run(df, strategy, strategy.default_params, fast_metrics=True)

            # Mesure
            times = []
            for _ in range(iterations):
                engine = BacktestEngine(initial_capital=10000.0, config=config)
                start = time.perf_counter()
                result = engine.run(df, strategy, strategy.default_params, fast_metrics=True)
                times.append(time.perf_counter() - start)

            avg_time = np.mean(times) * 1000
            results[strategy_name] = {
                "avg_ms": avg_time,
                "bt_per_sec": 1000 / avg_time if avg_time > 0 else 0,
                "trades": result.metrics.get("total_trades", 0),
            }

            speed_icon = "🚀" if avg_time < 100 else "⚡" if avg_time < 500 else "🐢"
            print(f"{speed_icon} {strategy_name:20s}: {avg_time:8.2f}ms ({results[strategy_name]['bt_per_sec']:.1f} bt/s) - {results[strategy_name]['trades']} trades")

        except Exception as e:
            print(f"❌ {strategy_name:20s}: Erreur - {e}")

    return results


def profile_sweep_simulation(df: pd.DataFrame, n_combinations: int = 100) -> dict:
    """Simule un mini-sweep pour estimer le temps total."""
    from backtest.engine import BacktestEngine
    from strategies import get_strategy
    from utils.config import Config

    print("\n" + "="*60)
    print(f"🔄 SIMULATION SWEEP ({n_combinations} combinaisons)")
    print("="*60)

    strategy_class = get_strategy("ema_cross")
    if strategy_class is None:
        print("❌ Stratégie ema_cross non trouvée")
        return {}

    strategy = strategy_class()  # Instancier la stratégie
    config = Config(fees_bps=10, slippage_bps=5)

    # Générer des combinaisons de paramètres
    fast_periods = [5, 8, 10, 12, 15]
    slow_periods = [20, 25, 30, 35, 40]

    combinations = []
    for fast in fast_periods:
        for slow in slow_periods:
            if fast < slow:
                combinations.append({"fast_period": fast, "slow_period": slow})

    combinations = combinations[:n_combinations]

    # Mesurer le temps
    start = time.perf_counter()
    completed = 0

    for params in combinations:
        engine = BacktestEngine(initial_capital=10000.0, config=config)
        engine.run(df, strategy, params, fast_metrics=True)
        completed += 1

        if completed % 10 == 0:
            elapsed = time.perf_counter() - start
            bt_per_sec = completed / elapsed
            eta = (len(combinations) - completed) / bt_per_sec
            print(f"   {completed}/{len(combinations)} - {bt_per_sec:.1f} bt/s - ETA: {eta:.1f}s")

    total_time = time.perf_counter() - start
    bt_per_sec = len(combinations) / total_time

    print("\n📊 Résultat:")
    print(f"   Combinaisons: {len(combinations)}")
    print(f"   Temps total: {total_time:.2f}s")
    print(f"   Vitesse: {bt_per_sec:.1f} bt/s")

    # Extrapolation
    print("\n📈 Extrapolation:")
    for target in [1000, 10000, 100000, 1000000]:
        est_time = target / bt_per_sec
        if est_time < 60:
            print(f"   {target:>10,} combinaisons: {est_time:.0f}s")
        elif est_time < 3600:
            print(f"   {target:>10,} combinaisons: {est_time/60:.1f}min")
        elif est_time < 86400:
            print(f"   {target:>10,} combinaisons: {est_time/3600:.1f}h")
        else:
            print(f"   {target:>10,} combinaisons: {est_time/86400:.1f}j")

    return {
        "combinations": len(combinations),
        "total_time_s": total_time,
        "bt_per_sec": bt_per_sec,
    }


def profile_grid_sweep(
    df: pd.DataFrame,
    n_combinations: int = 64,
    workers: Optional[int] = None,
    use_processes: bool = True,
) -> dict:
    """Profile un sweep grille réel via SweepEngine."""
    from backtest.sweep import SweepEngine
    from strategies import get_strategy

    print("\n" + "="*60)
    print(f"🧮 PROFILING SWEEP GRILLE (~{n_combinations} combinaisons)")
    print("="*60)

    strategy_class = get_strategy("rsi_reversal")
    if strategy_class is None:
        print("❌ Stratégie rsi_reversal non trouvée")
        return {}

    strategy = strategy_class()
    grid_size = max(1, int(round(math.sqrt(n_combinations))))
    rsi_periods = list(range(10, 10 + grid_size))
    oversold_levels = list(range(20, 20 + grid_size))

    param_grid = {
        "rsi_period": rsi_periods,
        "oversold_level": oversold_levels,
    }

    total_combos = len(rsi_periods) * len(oversold_levels)
    max_workers = workers if workers and workers > 0 else min(4, os.cpu_count() or 4)

    engine = SweepEngine(
        max_workers=max_workers,
        use_processes=use_processes,
        auto_save=False,
    )

    start = time.perf_counter()
    results = engine.run_sweep(
        df=df,
        strategy=strategy,
        param_grid=param_grid,
        show_progress=False,
    )
    elapsed = time.perf_counter() - start
    bt_per_sec = total_combos / elapsed if elapsed > 0 else 0

    print(f"   Mode: {'processes' if use_processes else 'threads'}")
    print(f"   Workers: {max_workers}")
    print(f"   Combinaisons: {total_combos}")
    print(f"   Temps total: {elapsed:.2f}s")
    print(f"   Vitesse: {bt_per_sec:.1f} bt/s")
    print(f"   Completed: {results.n_completed} | Failed: {results.n_failed}")

    return {
        "combinations": total_combos,
        "total_time_s": elapsed,
        "bt_per_sec": bt_per_sec,
        "completed": results.n_completed,
        "failed": results.n_failed,
    }


def detailed_cprofile(df: pd.DataFrame) -> None:
    """Profiling détaillé avec cProfile."""
    from backtest.engine import BacktestEngine
    from strategies.registry import get_strategy

    print("\n" + "="*60)
    print("🔬 PROFILING DÉTAILLÉ (cProfile)")
    print("="*60)

    strategy = get_strategy("ema_cross")

    # Profiler
    profiler = cProfile.Profile()
    profiler.enable()

    # Exécuter 10 backtests
    for _ in range(10):
        engine = BacktestEngine(initial_capital=10000.0, fees_bps=10)
        engine.run(df, strategy, strategy.default_params)

    profiler.disable()

    # Analyser
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("cumulative")
    stats.print_stats(30)

    print(stream.getvalue())

    # Sauvegarder
    output_file = "profile_results.prof"
    stats.dump_stats(output_file)
    print(f"\n💾 Résultats sauvegardés dans {output_file}")
    print("   Visualiser avec: snakeviz profile_results.prof")


def identify_bottlenecks(indicators_results: dict, simulator_results: dict, engine_results: dict) -> None:
    """Identifie les principaux goulots d'étranglement."""
    print("\n" + "="*60)
    print("🎯 ANALYSE DES GOULOTS D'ÉTRANGLEMENT")
    print("="*60)

    issues = []
    recommendations = []

    # Analyser indicateurs
    slow_indicators = [(name, data) for name, data in indicators_results.items() if data["avg_ms"] > 20]
    if slow_indicators:
        issues.append(f"❌ {len(slow_indicators)} indicateur(s) lent(s) (>20ms)")
        for name, data in slow_indicators:
            recommendations.append(f"   → {name}: vectoriser avec NumPy ou ajouter @njit")

    # Analyser simulateur
    if simulator_results.get("simulator_fast", {}).get("avg_ms", 0) > 50:
        issues.append("❌ Simulateur fast >50ms (devrait être <20ms)")
        recommendations.append("   → Vérifier que Numba compile bien (@njit warmup)")

    # Comparer fast vs slow
    fast = simulator_results.get("simulator_fast", {}).get("avg_ms", 1)
    slow = simulator_results.get("simulator_slow", {}).get("avg_ms", 1)
    speedup = slow / fast if fast > 0 else 0

    if speedup < 10:
        issues.append(f"⚠️ Accélération Numba faible ({speedup:.1f}x, attendu >50x)")
        recommendations.append("   → Vérifier que Numba fonctionne correctement")
        recommendations.append("   → pip install numba --upgrade")

    # Analyser moteur complet
    slow_engines = [(name, data) for name, data in engine_results.items() if data.get("avg_ms", 0) > 500]
    if slow_engines:
        issues.append(f"⚠️ {len(slow_engines)} stratégie(s) lente(s) (>500ms)")
        for name, data in slow_engines:
            recommendations.append(f"   → {name}: optimiser generate_signals()")

    # Résumé
    if issues:
        print("\n🔴 PROBLÈMES DÉTECTÉS:")
        for issue in issues:
            print(f"   {issue}")

        print("\n💡 RECOMMANDATIONS:")
        for rec in recommendations:
            print(rec)
    else:
        print("\n✅ Aucun goulot d'étranglement majeur détecté!")

    # Performance globale
    avg_bt_per_sec = np.mean([data.get("bt_per_sec", 0) for data in engine_results.values() if data.get("bt_per_sec", 0) > 0])

    print("\n📊 PERFORMANCE GLOBALE:")
    print(f"   Vitesse moyenne: {avg_bt_per_sec:.1f} bt/s")

    if avg_bt_per_sec < 10:
        print("   ⚠️ LENT - Vérifier Numba et vectorisation")
    elif avg_bt_per_sec < 50:
        print("   ⚡ CORRECT - Améliorations possibles")
    else:
        print("   🚀 RAPIDE - Performance optimale")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Profiling du système de backtest")
    parser.add_argument("--quick", action="store_true", help="Mode rapide (1000 barres)")
    parser.add_argument("--detailed", action="store_true", help="Profiling cProfile détaillé")
    parser.add_argument("--memory", action="store_true", help="Profiling mémoire")
    parser.add_argument("--bars", type=int, default=10000, help="Nombre de barres de test")
    parser.add_argument("--grid", action="store_true", help="Profiling sweep grille (SweepEngine)")
    parser.add_argument("--grid-combos", type=int, default=64, help="Nombre approx de combinaisons")
    parser.add_argument("--grid-workers", type=int, default=0, help="Nombre de workers (0=auto)")
    parser.add_argument("--grid-threads", action="store_true", help="Utiliser ThreadPoolExecutor (évite fork)")
    args = parser.parse_args()

    n_bars = 1000 if args.quick else args.bars

    print("="*60)
    print("🔬 PROFILING SYSTÈME BACKTEST CORE")
    print("="*60)
    print(f"Barres de test: {n_bars:,}")
    print(f"Mode: {'Rapide' if args.quick else 'Complet'}")

    # Créer données de test
    print("\n📊 Création données de test...")
    df = create_test_data(n_bars)
    print(f"   DataFrame: {len(df)} barres, {df.memory_usage(deep=True).sum() / 1024:.1f} KB")

    # Profiler les différentes composantes
    indicators_results = profile_indicators(df)
    simulator_results = profile_simulator(df)
    engine_results = profile_engine(df)

    # Simulation de sweep
    profile_sweep_simulation(df, n_combinations=50)

    # Profiling sweep grille réel
    if args.grid:
        profile_grid_sweep(
            df,
            n_combinations=args.grid_combos,
            workers=args.grid_workers if args.grid_workers > 0 else None,
            use_processes=not args.grid_threads,
        )

    # Profiling détaillé si demandé
    if args.detailed:
        detailed_cprofile(df)

    # Analyse des goulots d'étranglement
    identify_bottlenecks(indicators_results, simulator_results, engine_results)

    print("\n" + "="*60)
    print("✅ PROFILING TERMINÉ")
    print("="*60)


if __name__ == "__main__":
    main()
